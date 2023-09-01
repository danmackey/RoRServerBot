import asyncio
import hashlib
import logging
import math
import struct
import time
from datetime import datetime
from itertools import chain
from typing import Callable

from pyee.asyncio import AsyncIOEventEmitter

from ror_server_bot import pformat, RORNET_VERSION

from .enums import (
    AuthLevels,
    CharacterAnimation,
    CharacterCommand,
    MessageType,
    StreamType,
)
from .models import (
    ActorStreamRegister,
    CharacterPositionStreamData,
    CharacterStreamRegister,
    ChatStreamRegister,
    GlobalStats,
    Packet,
    ServerInfo,
    StreamRegister,
    UserInfo,
    Vector3,
    Vector4,
)
from .user import User

logger = logging.getLogger(__name__)


class PacketError(Exception):
    """An error that occurs when a packet is malformed."""


class UnexpectedCommandError(Exception):
    """An error that occurs when a packet with an unexpected command is
    received."""


class UserNotFoundError(Exception):
    """Raised when a user is not found."""


class RoRConnection(AsyncIOEventEmitter):
    def __init__(
        self,
        username: str,
        user_token: str,
        password: str,
        host: str,
        port: int,
        heartbeat_interval: float = 1.0
    ) -> None:
        """Creates a new RoRConnection object. This object should be used
        with the async with statement.

        For example:
        ```
        >>> async with RoRConnection(...) as conn:
        >>>     await conn.send_chat('Hello World!')
        ```

        :param username: The username to connect with.
        :param user_token: The user token to connect with.
        :param password: The password to the server in plain text.
        :param host: The IP address of the server.
        :param port: The port the server is running on.
        :param heartbeat_interval: The interval, in seconds, to send
        heartbeat packets to the server, defaults to 1.0.
        """
        super().__init__()

        self.add_listener('new_listener', self._new_listener)
        self.add_listener('error', self._error)

        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter
        self._writer_lock: asyncio.Lock

        self._reader_task: asyncio.Task
        self._heartbeat_task: asyncio.Task

        self._task_group = asyncio.TaskGroup()

        self._connect_time: datetime

        self.stream_id = 10  # stream ids under 10 are reserved
        self.net_quality = 0

        self._host = host
        self._port = port
        self._password = hashlib.sha1(password.encode()).hexdigest().upper()
        self._heartbeat_interval = heartbeat_interval

        self._is_connected = False

        self.server_info: ServerInfo
        self.user_info = UserInfo(
            auth_status=AuthLevels.BOT,
            username=username,
            user_token=user_token,
            server_password=self._password,
            language='en-US',
            client_name='bot',
            client_version='2022.12',
            client_guid='',
            session_type='bot',
            session_options='',
        )
        self.users: dict[int, User] = {}
        self.global_stats = GlobalStats()

    @property
    def is_connected(self) -> bool:
        """Gets if the client is connected to the server."""
        return self._is_connected

    @property
    def connect_time(self) -> datetime:
        """Gets the time the client connected to the server."""
        return self._connect_time

    @property
    def address(self) -> str:
        """Gets the address of the server."""
        return f'{self._host}:{self._port}'

    @property
    def unique_id(self) -> int:
        """Gets the unique id of the client."""
        return self.user_info.unique_id

    @property
    def user_count(self) -> int:
        """Gets the number of users."""
        return len(self.users) - 1  # subtract 1 for the server client

    @property
    def user_ids(self) -> list[int]:
        """Gets the ids of the users."""
        return list(self.users.keys())

    @property
    def stream_ids(self) -> list[int]:
        """Gets the ids of every stream for every user."""
        return list(chain.from_iterable(
            user.stream_ids for user in self.users.values()
        ))

    async def __aenter__(self) -> 'RoRConnection':
        """Connects to the server.

        :return: The connected RoRConnection object.
        """
        await self._task_group.__aenter__()

        logger.info('Connecting to %s', self.address)

        self._reader, self._writer = await asyncio.open_connection(
            self._host,
            self._port
        )

        self._writer_lock = asyncio.Lock()

        logger.info('Starting reader loop')

        self._reader_task = self._task_group.create_task(
            self.__reader_loop(),
            name='reader_loop'
        )

        hello_packet = await self.__send_hello()
        self.server_info = ServerInfo.from_bytes(hello_packet.data)

        logger.info('Received Server Info: %s', self.server_info)

        welcome_packet = await self.__send_welcome()
        self.user_info = UserInfo.from_bytes(welcome_packet.data)

        logger.info('Received User Info: %s', self.user_info)
        self.add_user(self.user_info)

        await self.__register_streams()

        self._connect_time = datetime.now()

        self._is_connected = True

        logger.info('Starting heartbeat loop')

        self._heartbeat_task = self._task_group.create_task(
            self.__heartbeat_loop(),
            name='heartbeat_loop'
        )

        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Disconnects from the server.

        :param exc_type: The exception type.
        :param exc: The exception.
        :param tb: The traceback.
        """
        logger.info('Disconnecting from %s', self.address)

        await self._send(Packet(
            command=MessageType.USER_LEAVE,
            source=self.unique_id,
            stream_id=self.stream_id,
            size=0,
        ))

        await self._task_group.__aexit__(exc_type, exc, tb)

        if self._reader_task is not None:
            self._reader_task.cancel()

        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()

        async with self._writer_lock:
            self._reader.feed_eof()
            self._writer.close()
            await self._writer.wait_closed()

        self._is_connected = False

    async def __send_hello(self) -> Packet:
        logger.info('Sending Hello Message')

        hello_packet = Packet(
            command=MessageType.HELLO,
            source=0,  # we do not have a unique id yet
            stream_id=self.stream_id,
            size=len(RORNET_VERSION),
            data=RORNET_VERSION
        )

        future: asyncio.Future[Packet] = asyncio.Future()

        @self.once('packet')
        async def hello(packet: Packet):
            if packet.command is not MessageType.HELLO:
                raise UnexpectedCommandError('Did not recieve hello response')
            future.set_result(packet)

        await self._send(hello_packet)

        return await future

    async def __send_welcome(self) -> Packet:
        logger.info('Sending User Info: %s', self.user_info)

        data = self.user_info.pack()
        welcome_packet = Packet(
            command=MessageType.USER_INFO,
            source=self.unique_id,
            stream_id=self.stream_id,
            size=len(data),
            data=data
        )

        future: asyncio.Future[Packet] = asyncio.Future()

        @self.once('packet')
        async def welcome(packet: Packet):
            if packet.command is MessageType.WELCOME:
                future.set_result(packet)
            elif packet.command is MessageType.SERVER_FULL:
                raise ConnectionError('Server is full')
            elif packet.command is MessageType.BANNED:
                raise ConnectionError('RoR Client is banned')
            elif packet.command is MessageType.WRONG_PASSWORD:
                raise ConnectionError('Wrong password')
            elif packet.command is MessageType.WRONG_VERSION:
                raise ConnectionError('Wrong version')
            else:
                raise UnexpectedCommandError(
                    'Invalid response: %r',
                    packet.command
                )

        await self._send(welcome_packet)

        return await future

    async def __register_streams(self):
        chat_stream_reg = ChatStreamRegister(
            type=StreamType.CHAT,
            status=0,
            origin_source_id=self.unique_id,
            origin_stream_id=self.stream_id,
            name='chat',
            reg_data='0',
        )
        logger.info('Sending Chat Stream Register: %s', chat_stream_reg)

        await self.register_stream(chat_stream_reg)

        char_stream_reg = CharacterStreamRegister(
            type=StreamType.CHARACTER,
            status=0,
            origin_source_id=self.unique_id,
            origin_stream_id=self.stream_id,
            name='default',
            reg_data=b'\x02',
        )

        logger.info('Sending Character Stream Register: %s', char_stream_reg)

        await self.register_stream(char_stream_reg)

    async def __reader_loop(self):
        """The main reader loop. Reads packets from the server and emits
        events.

        This function should not be called directly.

        This function will emit the following events when a packet is
        received:
        - `packet.*`: Emits for every packet received.
        - `packet.<command name>`: Emits an event with the name of the
        command from the packet received. For example, if a packet with
        the command `MessageType.CHAT` is received, the event
        `packet.CHAT` will be emitted.
        """
        while True:
            header = await self._reader.readexactly(Packet.calc_size())

            logger.debug('[HEAD] %s', header)

            try:
                packet = Packet.from_bytes(header)
            except struct.error as e:
                raise PacketError(
                    f'Failed to read packet header: {header}'
                ) from e

            if (
                packet.command is not MessageType.STREAM_UNREGISTER
                and packet.size == 0
            ):
                raise PacketError(f'No data to read: {packet}')

            payload = await self._reader.read(packet.size)

            if len(payload) != packet.size:
                logger.warning(
                    'Packet size mismatch: data=%s packet=%s',
                    payload,
                    packet
                )

            logger.debug('[RECV] %s', payload)

            packet.data = payload

            logger.debug('[PCKT] %s', packet)

            # emit to packet wildcard
            self.emit('packet', packet)

            # command event
            self.emit('packet.' + packet.command.name, packet)

            await asyncio.sleep(0.01)

    async def __heartbeat_loop(self):
        """The heartbeat loop. Sends a character position stream packet
        to the server on a constant interval. This is done to prevent
        the server from kicking the client for inactivity.

        This function should not be called directly.
        """
        if not self.is_connected:
            raise ConnectionError(
                'Cannot start heartbeat loop when not connected'
            )

        stream = CharacterPositionStreamData(
            command=CharacterCommand.POSITION,
            position=Vector3(),
            rotation=0,
            animation_time=self._heartbeat_interval,
            animation_mode=CharacterAnimation.IDLE_SWAY,
        )

        packet = Packet(
            command=MessageType.STREAM_DATA,
            source=self.unique_id,
            stream_id=self.get_character_sid(self.unique_id)
        )

        logger.info(
            'Sending character stream data every %f seconds. %s',
            self._heartbeat_interval,
            stream
        )

        start_time = time.time()
        current_time = start_time
        delta = 0
        while self._is_connected:
            prev_time = current_time
            current_time = time.time()
            delta += current_time - prev_time

            if delta >= self._heartbeat_interval:
                stream.animation_time = delta
                delta = 0

                if self._heartbeat_interval >= 1:
                    # avoid spamming logs
                    logger.info('Sending heartbeat character stream data.')

                data = stream.pack()
                packet.data = data
                packet.size = len(data)

                await self._send(packet)

            await asyncio.sleep(0.1)

    def _new_listener(self, event: str, listener: Callable):
        """Handles new listener events.

        :param event: The event that was added.
        :param listener: The listener that was added.
        """
        logger.debug(
            'New listener added: event="%s" listener="%s"',
            event,
            listener.__name__
        )

    def _error(self, error: Exception):
        """Handles error events.

        :param error: The error that was emitted.
        """
        logger.error('Error: %r', error, exc_info=True, stacklevel=2)

    async def _send(self, packet: Packet):
        """Sends a packet to the server.

        :param packet: The packet to send.
        """
        async with self._writer_lock:
            data = packet.pack()

            logger.debug('[SEND] %s', data)

            self._writer.write(data)

            await self._writer.drain()

    def get_uid_by_username(self, username: str) -> int | None:
        """Gets the uid of the user by their username.

        :param username: The username of the user.
        :return: The uid of the user.
        """
        for uid, user in self.users.items():
            if user.username == username:
                return uid
        return None

    def get_user(self, uid: int) -> User:
        """Gets a user from the stream manager.

        :param uid: The uid of the user.
        :return: The user.
        """
        try:
            return self.users[uid]
        except KeyError as e:
            raise UserNotFoundError(uid, pformat(self.users)) from e

    def add_user(self, user_info: UserInfo):
        """Adds a client to the stream manager.

        :param user_info: The user info of the client to add.
        """
        # update global stats if this is a new user
        if user_info.unique_id not in self.users:
            self.global_stats.add_user(user_info.username)

        # set the user to a new user if not already set
        self.users.setdefault(user_info.unique_id, User(info=user_info))

        # update the user info for the user
        self.users[user_info.unique_id].info = user_info

        logger.info(
            'Added user %r uid=%d',
            user_info.username,
            user_info.unique_id
        )

    def delete_user(self, uid: int):
        """Deletes a client from the stream manager.

        :param uid: The uid of the client to delete.
        """
        user = self.users.pop(uid)

        self.global_stats.meters_driven += user.stats.meters_driven
        self.global_stats.meters_sailed += user.stats.meters_sailed
        self.global_stats.meters_walked += user.stats.meters_walked
        self.global_stats.meters_flown += user.stats.meters_flown

        self.global_stats.connection_times.append(
            datetime.now() - user.stats.online_since
        )

        logger.debug('Deleted user %r uid=%d', user.username, uid)

    def add_stream(self, stream: StreamRegister):
        """Adds a stream to the stream manager.

        :param stream: The stream to add.
        """
        self.get_user(stream.origin_source_id).add_stream(stream)

    def delete_stream(self, uid: int, sid: int):
        """Deletes a stream from the stream manager.

        :param uid: The uid of the stream to delete.
        :param sid: The sid of the stream to delete.
        """
        self.get_user(uid).delete_stream(sid)

    def get_stream(self, uid: int, sid: int) -> StreamRegister:
        """Gets a stream from the stream manager.

        :param uid: The uid of the stream.
        :param sid: The sid of the stream.
        :return: The stream.
        """
        return self.get_user(uid).get_stream(sid)

    def get_current_stream(self, uid: int) -> StreamRegister:
        """Gets the current stream of the user.

        :param uid: The uid of the user.
        :return: The current stream of the user.
        """
        return self.get_user(uid).get_current_stream()

    def set_current_stream(self, uid: int, actor_uid: int, sid: int):
        """Sets the current stream of the user.

        :param uid: The uid of the user.
        :param actor_uid: The uid of the actor.
        :param sid: The sid of the stream.
        """
        self.get_user(uid).set_current_stream(actor_uid, sid)

    def set_character_sid(self, uid: int, sid: int):
        """Sets the character stream id of the user.

        :param uid: The uid of the user.
        :param sid: The sid of the character stream.
        """
        self.get_user(uid).character_stream_id = sid

    def get_character_sid(self, uid: int) -> int:
        """Gets the character stream id of the user.

        :param uid: The uid of the user.
        :return: The character stream id of the user.
        """
        return self.get_user(uid).character_stream_id

    def set_chat_sid(self, uid: int, sid: int):
        """Sets the chat stream id of the user.

        :param uid: The uid of the user.
        :param sid: The sid of the chat stream.
        """
        self.get_user(uid).chat_stream_id = sid

    def get_chat_sid(self, uid: int) -> int:
        """Gets the chat stream id of the user.

        :param uid: The uid of the user.
        :return: The chat stream id of the user.
        """
        return self.get_user(uid).chat_stream_id

    def set_position(self, uid: int, sid: int, position: Vector3):
        """Sets the position of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream.
        :param position: The position to set.
        """
        self.get_user(uid).set_position(sid, position)

    def get_position(self, uid: int, sid: int = -1) -> Vector3:
        """Gets the position of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream, defaults to -1
        :return: The position of the stream.
        """
        if sid == -1:
            return self.get_current_stream(uid).position
        else:
            return self.get_user(uid).get_stream(sid).position

    def set_rotation(self, uid: int, sid: int, rotation: Vector4):
        """Sets the rotation of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream.
        :param rotation: The rotation to set.
        """
        self.get_user(uid).set_rotation(sid, rotation)

    def get_rotation(self, uid: int, sid: int = -1) -> Vector4:
        """Gets the rotation of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream, defaults to -1
        :return: The rotation of the stream.
        """
        if sid == -1:
            return self.get_current_stream(uid).rotation
        else:
            return self.get_user(uid).get_stream(sid).rotation

    def get_online_since(self, uid: int) -> datetime:
        """Gets the online since of the user.

        :param uid: The uid of the user.
        :return: The online since of the user.
        """
        return self.get_user(uid).stats.online_since

    def total_streams(self, uid: int) -> int:
        """Gets the total number of streams.

        :param uid: The uid of the user.
        :return: The total number of streams.
        """
        return self.get_user(uid).total_streams

    def get_username(self, uid: int) -> str:
        """Gets the username of the user.

        :param uid: The uid of the user.
        :return: The username of the user.
        """
        return self.get_user(uid).username

    def get_username_colored(self, uid: int) -> str:
        """Gets the username of the user with color.

        :param uid: The uid of the user.
        :return: The username of the user with color.
        """
        return self.get_user(uid).username_colored

    def get_language(self, uid: int) -> str:
        """Gets the language of the user.

        :param uid: The uid of the user.
        :return: The language of the user.
        """
        return self.get_user(uid).language

    def get_client_name(self, uid: int) -> str:
        """Gets the client name of the user.

        :param uid: The uid of the user.
        :return: The client name of the user.
        """
        return self.get_user(uid).client_name

    def get_client_version(self, uid: int) -> str:
        """Gets the client version of the user.

        :param uid: The uid of the user.
        :return: The client version of the user.
        """
        return self.get_user(uid).client_version

    def get_client_guid(self, uid: int) -> str:
        """Gets the client guid of the user.

        :param uid: The uid of the user.
        :return: The client guid of the user.
        """
        return self.get_user(uid).client_guid

    def get_auth_status(self, uid: int) -> AuthLevels:
        """Gets the authentication status of the user.

        :param uid: The uid of the user.
        :return: The authentication status of the user.
        """
        return self.get_user(uid).auth_status

    async def register_stream(self, stream: StreamRegister) -> int:
        """Registers a stream with the server as the client.

        :param stream: The stream being registered.
        :return: The stream id of the stream.
        """
        stream.origin_source_id = self.unique_id
        stream.origin_stream_id = self.stream_id

        if isinstance(stream, ActorStreamRegister):
            stream.timestamp = -1

        stream_data = stream.pack()
        packet = Packet(
            command=MessageType.STREAM_REGISTER,
            source=stream.origin_source_id,
            stream_id=stream.origin_stream_id,
            size=len(stream_data),
            data=stream_data
        )
        await self._send(packet)
        self.add_stream(stream)
        self.stream_id += 1

        return stream.origin_stream_id

    async def unregister_stream(self, stream_id: int):
        """Unregisters a stream with the server as the client.

        :param stream_id: The stream id of the stream to unregister.
        """
        packet = Packet(
            command=MessageType.STREAM_UNREGISTER,
            source=self.unique_id,
            stream_id=stream_id,
        )
        await self._send(packet)
        self.delete_stream(self.unique_id, stream_id)

    async def reply_to_stream_register(
        self,
        stream: StreamRegister,
        status: int
    ):
        """Replies to a stream register request.

        :param stream: The stream to reply to.
        :param status: The status to reply with.
        """
        stream.status = status
        data = stream.pack()
        packet = Packet(
            command=MessageType.STREAM_REGISTER_RESULT,
            source=self.unique_id,
            stream_id=stream.origin_stream_id,
            size=len(data),
            data=data
        )
        await self._send(packet)

    async def send_chat(self, message: str):
        """Sends a message to the game chat.

        :param message: The message to send.
        """
        logger.info('[CHAT] message="%s"', message)

        data = message.encode()

        await self._send(Packet(
            command=MessageType.CHAT,
            source=self.unique_id,
            stream_id=self.get_chat_sid(self.unique_id),
            size=len(data),
            data=data
        ))

    async def send_private_chat(self, uid: int, message: str):
        """Sends a private message to a user.

        :param uid: The uid of the user to send the message to.
        :param message: The message to send.
        """
        logger.info('[PRIV] to_uid=%d message="%s"', uid, message)

        data = struct.pack('I8000s', uid, message.encode())
        await self._send(Packet(
            command=MessageType.PRIVATE_CHAT,
            source=self.unique_id,
            stream_id=self.get_chat_sid(self.unique_id),
            size=len(data),
            data=data
        ))

    async def send_multiline_chat(self, message: str):
        """Sends a multiline message to the game chat.

        :param message: The message to send.
        """
        max_line_len = 100
        if len(message) > max_line_len:
            logger.debug('[CHAT] multiline_message="%s"', message)

            total_lines = math.ceil(len(message) / max_line_len)
            for i in range(total_lines):
                line = message[max_line_len*i:max_line_len*(i+1)]
                if i > 0:
                    line = f'| {line}'
                await self.send_chat(line)
        else:
            await self.send_chat(message)

    async def kick(self, uid: int, reason: str = 'No reason given'):
        """Kicks a user from the server.

        :param uid: The uid of the user to kick.
        :param reason: The reason for kicking the user, defaults to
        'No reason given'
        """
        await self.send_chat(f'!kick {uid} {reason}')

    async def ban(self, uid: int, reason: str = 'No reason given'):
        """Bans a user from the server.

        :param uid: The uid of the user to ban.
        :param reason: The reason for banning the user, defaults to
        'No reason given'
        """
        await self.send_chat(f'!ban {uid} {reason}')

    async def say(self, uid: int, message: str):
        """Send a message as a user anonymously.

        :param uid: The uid of the user to send the message to. If -1,
        the message will be sent to everyone.
        :param message: The message to send.
        """
        await self.send_chat(f'!say {uid} {message}')

    async def send_game_cmd(self, command: str):
        """Sends a game command (Angelscript) to the server.

        :param command: The command to send.
        """
        logger.debug('[GAME_CMD] cmd="%s"', command)
        data = command.encode()
        await self._send(Packet(
            command=MessageType.GAME_CMD,
            source=self.unique_id,
            stream_id=0,
            size=len(data),
            data=data
        ))
