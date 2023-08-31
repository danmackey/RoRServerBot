import asyncio
import hashlib
import logging
import math
import struct
import time
from datetime import datetime
from typing import Callable

from pyee.asyncio import AsyncIOEventEmitter

from ror_server_bot import RORNET_VERSION

from .enums import (
    AuthLevels,
    CharacterAnimation,
    CharacterCommand,
    MessageType,
    StreamType,
)
from .models import (
    ActorStreamRegister,
    CharacterStreamRegister,
    ChatStreamRegister,
    Packet,
    ServerInfo,
    StreamRegister,
    UserInfo,
)
from .models.sendable import CharacterPositionStreamData
from .models.vector import Vector3
from .stream_manager import StreamManager

logger = logging.getLogger(__name__)


class PacketError(Exception):
    """An error that occurs when a packet is malformed."""


class UnexpectedCommandError(Exception):
    """An error that occurs when a packet with an unexpected command is
    received."""


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
        :param password: The password to the server.
        :param host: The IP address of the server.
        :param port: The port the server is running on.
        :param heartbeat_interval: The interval to send heartbeat
        packets to the server, defaults to 1.0.
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
        self.stream_manager = StreamManager()

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
        self.stream_manager.add_user(self.user_info)

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
            stream_id=self.stream_manager.get_character_sid(self.unique_id)
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
        self.stream_manager.add_stream(stream)
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
        self.stream_manager.delete_stream(self.unique_id, stream_id)

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
            stream_id=self.stream_manager.get_chat_sid(self.unique_id),
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
            stream_id=self.stream_manager.get_chat_sid(self.unique_id),
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
