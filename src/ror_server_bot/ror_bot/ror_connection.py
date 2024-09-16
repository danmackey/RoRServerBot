import asyncio
import contextlib
import hashlib
import logging
import math
import struct
import time
from collections.abc import Callable
from datetime import datetime
from functools import singledispatchmethod
from itertools import chain
from types import TracebackType
from typing import Any

from pyee import AsyncIOEventEmitter

from ror_server_bot import RORNET_VERSION
from ror_server_bot.logging import pformat

from .enums import (
    ActorStreamStatus,
    AuthStatus,
    CharacterAnimation,
    CharacterCommand,
    MessageType,
    RoRClientEvents,
    StreamType,
)
from .models import (
    ActorStreamData,
    ActorStreamRegister,
    BannedPacket,
    CharacterAttachStreamData,
    CharacterPositionStreamData,
    CharacterStreamRegister,
    ChatPacket,
    ChatStreamRegister,
    GameCmdPacket,
    GlobalStats,
    HelloPacket,
    NetQualityPacket,
    Packet,
    packet_factory,
    PrivateChatPacket,
    ServerFullPacket,
    ServerInfo,
    stream_data_factory,
    stream_register_factory,
    StreamData,
    StreamDataPacket,
    StreamRegister,
    StreamRegisterPacket,
    StreamRegisterResultPacket,
    StreamUnregisterPacket,
    UserInfo,
    UserInfoPacket,
    UserJoinPacket,
    UserLeavePacket,
    Vector3,
    WelcomePacket,
    WrongPasswordPacket,
    WrongVersionPacket,
)
from .user import StreamNotFoundError, User

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hashes a password using the SHA1 algorithm.

    :param password: The password to hash.
    :return: The hashed password.
    """
    return hashlib.sha1(password.encode()).hexdigest().upper()  # noqa: S324


class UnexpectedMessageError(Exception):
    """An error that occurs when a header with an unexpected message is
    received."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class UserNotFoundError(Exception):
    """Raised when a user is not found."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class UserAlreadyExistsError(Exception):
    """Raised when a user already exists."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class RoRConnection:
    STABLE_FPS = 20

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
        heartbeat packets to the server, defaults to 10.0.
        """
        self._connect_time: datetime

        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter
        self._writer_lock: asyncio.Lock
        self._reader_task: asyncio.Task
        self._heartbeat_task: asyncio.Task
        self._frame_step_task: asyncio.Task

        self._task_group = asyncio.TaskGroup()

        self._host = host
        self._port = port
        self._password = hash_password(password)

        self._net_quality = 0
        self._stream_id = 10  # stream ids under 10 are reserved
        self._is_connected = False
        self._heartbeat_interval = heartbeat_interval

        self._users: dict[int, User] = {}
        self._global_stats = GlobalStats()

        self._event_emitter = AsyncIOEventEmitter()
        self._event_emitter.add_listener('new_listener', self._new_listener)
        self._event_emitter.add_listener('error', self._error)

        self._server_info: ServerInfo | None = None
        self._user_info = UserInfo(
            auth_status=AuthStatus.BOT,
            slot_num=-2,
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

    @property
    def auth_status(self) -> AuthStatus:
        return self._user_info.auth_status

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
        return self._user_info.unique_id

    @property
    def character_sid(self) -> int:
        """Gets the stream id of the character stream."""
        return self.get_character_sid(self.unique_id)

    @property
    def chat_sid(self) -> int:
        """Gets the stream id of the chat stream."""
        return self.get_chat_sid(self.unique_id)

    @property
    def character_stream_register(self) -> CharacterStreamRegister:
        """Gets the character stream."""
        stream = self.get_stream(self.unique_id, self.character_sid)
        if not isinstance(stream, CharacterStreamRegister):
            raise TypeError(
                f'Expected CharacterStreamRegister, got {type(stream)}'
            )
        return stream

    @property
    def chat_stream_register(self) -> ChatStreamRegister:
        """Gets the chat stream."""
        stream = self.get_stream(self.unique_id, self.chat_sid)
        if not isinstance(stream, ChatStreamRegister):
            raise TypeError(f'Expected ChatStreamRegister, got {type(stream)}')
        return stream

    @property
    def user_count(self) -> int:
        """Gets the number of users."""
        return len(self._users) - 1  # subtract 1 for the server client

    @property
    def user_ids(self) -> list[int]:
        """Gets the ids of the users."""
        return list(self._users.keys())

    @property
    def stream_ids(self) -> list[int]:
        """Gets the ids of every stream for every user."""
        return list(chain.from_iterable(
            user.stream_ids for user in self._users.values()
        ))

    @property
    def position(self) -> Vector3:
        """Gets and sets the position of the client. This does not
        update the position of the client on the server."""
        position = self.get_position(self.unique_id, self.character_sid)
        if position is None:
            raise ValueError('Position is None')
        return position

    @position.setter
    def position(self, value: Vector3) -> None:
        self.set_position(self.unique_id, self.character_sid, value)

    @property
    def rotation(self) -> float:
        """Gets and sets the rotation of the client. This does not
        update the rotation of the client on the server."""
        rotation = self.get_rotation(self.unique_id, self.character_sid)
        if rotation is None:
            raise ValueError('Rotation is None')
        return rotation

    @rotation.setter
    def rotation(self, value: float) -> None:
        self.set_rotation(self.unique_id, self.character_sid, value)

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
            name=self.__reader_loop.__name__
        )

        await self.__send_hello()

        await self.__send_welcome()

        await self.__register_streams()

        self._connect_time = datetime.now()

        self._is_connected = True

        logger.info('Starting heartbeat loop')

        self._heartbeat_task = self._task_group.create_task(
            self.__heartbeat_loop(),
            name=self.__heartbeat_loop.__name__
        )

        logger.info('Starting frame step loop')

        self._frame_step_task = self._task_group.create_task(
            self.__frame_step_loop(),
            name=self.__frame_step_loop.__name__
        )

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Disconnects from the server.

        :param exc_type: The exception type.
        :param exc: The exception.
        :param tb: The traceback.
        """
        logger.info('Disconnecting from %s', self.address)

        await self._send(
            UserLeavePacket(
                type=MessageType.USER_LEAVE,
                source=self.unique_id,
                stream_id=self._stream_id,
                size=0,
            )
        )

        await self._task_group.__aexit__(exc_type, exc_val, exc_tb)

        if self._reader_task is not None:
            self._reader_task.cancel()

        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()

        if self._frame_step_task is not None:
            self._frame_step_task.cancel()

        async with self._writer_lock:
            self._reader.feed_eof()
            self._writer.close()
            await self._writer.wait_closed()

        self._is_connected = False

    async def __send_hello(self) -> None:
        logger.info('Sending Hello Message')

        self._server_info = None

        await self._send(
            HelloPacket(
                type=MessageType.HELLO,
                source=0,  # we do not have a unique id yet
                stream_id=self._stream_id,
                size=len(RORNET_VERSION),
                payload=RORNET_VERSION.encode()
            )
        )

        while True:
            if self._server_info is not None:
                break
            await asyncio.sleep(0.1)

    async def __send_welcome(self) -> None:
        logger.info('Sending User Info: %s', self._user_info)

        payload = self._user_info.pack()
        await self._send(UserInfoPacket(
            type=MessageType.USER_INFO,
            source=self.unique_id,
            stream_id=self._stream_id,
            size=len(payload),
            payload=payload
        ))

        while True:
            if self._user_info.color_num != -1:
                break
            await asyncio.sleep(0.1)

    async def __register_streams(self) -> None:
        chat_stream_reg = ChatStreamRegister(
            type=StreamType.CHAT,
            status=0,
            origin_source_id=self.unique_id,
            origin_stream_id=self._stream_id,
            name='chat',
            reg_data='0',
        )
        logger.info('Sending Chat Stream Register: %s', chat_stream_reg)

        await self.register_stream(chat_stream_reg)

        char_stream_reg = CharacterStreamRegister(
            type=StreamType.CHARACTER,
            status=0,
            origin_source_id=self.unique_id,
            origin_stream_id=self._stream_id,
            name='default',
            reg_data=b'\x02',
        )

        logger.info('Sending Character Stream Register: %s', char_stream_reg)

        await self.register_stream(char_stream_reg)

    async def __reader_loop(self) -> None:
        """The main reader loop. Handles packets sent by the server.

        This function should not be called directly.
        """
        header_format = 'IIII'
        header_size = struct.calcsize(header_format)
        while True:
            header = await self._reader.readexactly(header_size)

            logger.debug('[HEAD] %s', header)

            packet = packet_factory(*struct.unpack(header_format, header))

            if (
                packet.type is not MessageType.STREAM_UNREGISTER
                and packet.size == 0
            ):
                raise ValueError(f'No data to read: {packet}')

            payload = await self._reader.read(packet.size)

            logger.debug('[RECV] %s', payload)

            if len(payload) != packet.size:
                raise ValueError(
                    f'Packet size mismatch: data={payload!r} packet={packet}'
                )

            packet.payload = payload

            await self._parse_packet(packet)

            await asyncio.sleep(0.01)

    async def __heartbeat_loop(self) -> None:
        """The heartbeat loop. Sends a character position stream packet
        to the server on a constant interval. This is done to prevent
        the server from kicking the client for inactivity.

        This function should not be called directly.
        """
        if not self.is_connected:
            raise ConnectionError(
                'Cannot start heartbeat loop when not connected'
            )

        self.position = Vector3()
        self.rotation = 0.0

        stream = CharacterPositionStreamData(
            command=CharacterCommand.POSITION,
            position=self.position,
            rotation=self.rotation,
            animation_time=self._heartbeat_interval,
            animation_mode=CharacterAnimation.IDLE_SWAY,
        )

        header = StreamDataPacket(
            type=MessageType.STREAM_DATA,
            source=self.unique_id,
            stream_id=self.character_sid,
        )

        logger.info(
            'Sending character stream data every %f seconds.',
            self._heartbeat_interval
        )

        start_time = time.time()
        curr_time = start_time
        delta = 0.0
        while self._is_connected:
            prev_time = curr_time
            curr_time = time.time()
            delta += curr_time - prev_time

            if delta >= self._heartbeat_interval:
                delta = 0

                stream.position = self.position
                stream.rotation = self.rotation
                stream.animation_time = delta

                payload = stream.pack()

                header.size = len(payload)
                header.payload = payload

                await self._send(header)

            await asyncio.sleep(0.1)

    async def __frame_step_loop(self) -> None:
        """Send frame_step events at a stable rate."""
        start_time = time.time()
        curr_time = start_time
        delta = 0.0
        while True:
            prev_time = curr_time
            curr_time = time.time()
            delta += curr_time - prev_time

            if delta >= (1 / self.STABLE_FPS):
                self._emit(RoRClientEvents.FRAME_STEP, delta)
                delta = 0

            await asyncio.sleep(0.01)

    async def _send(self, packet: Packet) -> None:
        """Sends a message to the server.

        :param header: The packet of the message.
        """
        async with self._writer_lock:
            if packet.size != len(packet.payload):
                raise ValueError(
                    f'Packet size mismatch: data={packet.payload!r} '
                    f'packet={packet}'
                )

            logger.debug('[SEND] %s', packet)

            data = packet.pack()

            logger.debug('[SEND] %s', data)

            self._writer.write(data)
            await self._writer.drain()

    @singledispatchmethod
    async def _parse_packet(self, packet: Packet) -> None:
        """Parses a packet from the server.

        :param packet: The packet to parse.
        """
        raise NotImplementedError(f'No parse method for packet {packet.type}')

    @_parse_packet.register
    async def _(self, packet: HelloPacket) -> None:
        self._server_info = ServerInfo.from_bytes(packet.payload)
        logger.info('Received Server Info: %s', self._server_info)

    @_parse_packet.register
    async def _(
        self,
        packet: (
            WelcomePacket
            | ServerFullPacket
            | WrongPasswordPacket
            | WrongVersionPacket
            | BannedPacket
        ),
    ) -> None:
        match packet.type:
            case MessageType.WELCOME:
                self._user_info = UserInfo.from_bytes(packet.payload)
                logger.info('Received User Info: %s', self._user_info)
                self.add_user(self._user_info)
            case MessageType.SERVER_FULL:
                raise ConnectionError('Server is full')
            case MessageType.WRONG_PASSWORD:
                raise ConnectionError('Wrong password')
            case MessageType.WRONG_VERSION:
                raise ConnectionError('Wrong version')
            case MessageType.BANNED:
                raise ConnectionError('RoR Client is banned')
            case _:
                raise UnexpectedMessageError(
                    f'Unexpected message: {packet.type}'
                )

    @_parse_packet.register
    async def _(self, packet: NetQualityPacket) -> None:
        prev_nq = self._net_quality

        curr_nq, *_ = struct.unpack('I', packet.payload)

        if not isinstance(curr_nq, int):
            raise TypeError(
                'Expected net_quality to be an int, got '
                f'{type(curr_nq)}'
            )

        net_quality_changed = prev_nq != curr_nq

        logger.debug(
            '[NETQ] uid=%d net_quality=(%d -> %d) changed=%s',
            packet.source,
            prev_nq,
            curr_nq,
            net_quality_changed
        )

        self._net_quality = curr_nq

        if net_quality_changed:
            self._emit(RoRClientEvents.NET_QUALITY, curr_nq)

    @_parse_packet.register
    async def _(self, packet: UserJoinPacket) -> None:
        if packet.source == self.unique_id:
            return

        user_info = UserInfo.from_bytes(packet.payload)

        logger.info(
            'User %r with uid %d joined the server',
            user_info.client_name,
            packet.source
        )

        self.add_user(user_info)

        self._emit(RoRClientEvents.USER_JOIN, packet.source, user_info)

    @_parse_packet.register
    async def _(self, packet: UserInfoPacket) -> None:
        user_info = UserInfo.from_bytes(packet.payload)

        self.update_user(user_info)

        logger.info(
            'Recieved user info from user %r uid=%d',
            self.get_username(packet.source),
            packet.source
        )

        self._emit(RoRClientEvents.USER_INFO, packet.source, user_info)

    @_parse_packet.register
    async def _(self, packet: UserLeavePacket) -> None:
        user = self.get_user(packet.source)

        logger.info(
            'User %r with uid %d left with reason: %r',
            user.username,
            packet.source,
            packet.payload.decode()
        )

        if packet.source == self.unique_id:
            raise ConnectionError('Disconnected from the server!')

        self.delete_user(packet.source)

        self._emit(RoRClientEvents.USER_LEAVE, packet.source, user)

    @_parse_packet.register
    async def _(self, packet: ChatPacket | PrivateChatPacket) -> None:
        message = packet.payload.decode().strip('\x00')

        logger.info(
            '[%s] from_uid=%d message=%r',
            'CHAT' if isinstance(packet, ChatPacket) else 'PRIV',
            packet.source,
            message
        )

        if message and packet.source != self.unique_id:
            event = (
                RoRClientEvents.CHAT
                if isinstance(packet, ChatPacket)
                else RoRClientEvents.PRIVATE_CHAT
            )
            self._emit(event, packet.source, message)

    @_parse_packet.register
    async def _(self, packet: GameCmdPacket) -> None:
        if packet.source == self.unique_id:
            return

        game_cmd = packet.payload.decode().strip('\x00')

        logger.debug(
            '[GCMD] [RECV] from_uid=%d cmd=%r',
            packet.source,
            game_cmd
        )

        if game_cmd:
            self._emit(RoRClientEvents.GAME_CMD, packet.source, game_cmd)

    @_parse_packet.register
    async def _(self, packet: StreamRegisterPacket) -> None:
        stream = stream_register_factory(packet.payload)

        self.add_stream(stream)

        logger.info(
            'User %r with uid=%d registered a new %s stream with sid=%d',
            self.get_username(packet.source),
            packet.source,
            stream.type.name.lower(),
            stream.origin_stream_id
        )

        if stream.type is StreamType.ACTOR:
            await self.reply_to_actor_stream_register(
                stream,
                status=ActorStreamStatus.SUCCESS
            )

        self._emit(RoRClientEvents.STREAM_REGISTER, packet.source, stream)

    @_parse_packet.register
    async def _(self, packet: StreamRegisterResultPacket) -> None:
        stream = stream_register_factory(packet.payload)

        logger.info(
            'User %r with uid=%d has registered a %s stream with sid=%d',
            self.get_username(packet.source),
            packet.source,
            stream.type.name.lower(),
            stream.origin_stream_id
        )

        self._emit(
            RoRClientEvents.STREAM_REGISTER_RESULT,
            packet.source,
            stream
        )

    @_parse_packet.register
    async def _(self, packet: StreamDataPacket) -> None:
        if packet.source == self.unique_id:
            return

        # if we are getting stream data from a user or stream we cannot
        # find, we likely just joined the server and are waiting for the
        # server to send us the user info and stream register packets
        with contextlib.suppress(UserNotFoundError, StreamNotFoundError):
            stream = self.get_stream(packet.source, packet.stream_id)

            logger.debug(
                'User %r with uid=%d sent data for %s stream with sid=%d',
                self.get_username(packet.source),
                packet.source,
                stream.type.name.lower(),
                stream.origin_stream_id
            )

            stream_data: StreamData | None = None
            if stream.type in (StreamType.CHARACTER, StreamType.ACTOR):
                stream_data = stream_data_factory(stream.type, packet.payload)
                if isinstance(stream_data, CharacterPositionStreamData):
                    self.set_rotation(
                        packet.source,
                        packet.stream_id,
                        stream_data.rotation
                    )

                if isinstance(
                    stream_data,
                    CharacterPositionStreamData | ActorStreamData
                ):
                    self.set_position(
                        packet.source,
                        packet.stream_id,
                        stream_data.position
                    )
                    self.set_current_stream(
                        packet.source,
                        packet.source,
                        packet.stream_id
                    )
                elif isinstance(stream_data, CharacterAttachStreamData):
                    self.set_current_stream(
                        packet.source,
                        stream_data.source_id,
                        stream_data.stream_id
                    )
                logger.debug('[STREAM] stream_data=%s', stream_data)
            elif stream.type is StreamType.CHAT:
                stream_data = None
            else:
                raise ValueError(f'Unknown stream type: {stream.type!r}')

            self._emit(
                RoRClientEvents.STREAM_DATA,
                packet.source,
                stream,
                stream_data
            )

    @_parse_packet.register
    async def _(self, packet: StreamUnregisterPacket) -> None:
        if len(packet.payload) != 0:
            raise ValueError('Stream unregister packet has data')

        logger.info(
            'User %r with uid=%d unregistered a stream with sid=%d',
            self.get_username(packet.source),
            packet.source,
            packet.stream_id
        )

        self.delete_stream(packet.source, packet.stream_id)

        self._emit(
            RoRClientEvents.STREAM_UNREGISTER,
            packet.source,
            packet.stream_id
        )

    def _new_listener(self, event: str, listener: Callable) -> None:
        """Handles new listener events.

        :param event: The event that was added.
        :param listener: The listener that was added.
        """
        name = listener.__name__
        logger.debug('[EVENT] event=%r new_listener=%r', event, name)

    def _error(self, error: Exception) -> None:
        """Handles error events.

        :param error: The error that was emitted.
        """
        logger.error('[EVENT] error=%r', error, exc_info=True, stacklevel=2)

    def _emit(self, event: RoRClientEvents, *args: Any, **kwargs: Any) -> None:
        """Emit an event on the event emitter.

        :param event: The event to emit.
        :param args: The arguments to pass to the event handler.
        :param kwargs: The keyword arguments to pass to the event handler.
        """
        if event is not RoRClientEvents.FRAME_STEP:
            # we do not need to log every frame_step event emit
            logger.debug(
                '[EMIT] event=%r listeners=%d',
                event.value,
                len(self._event_emitter.listeners(event.value))
            )
        self._event_emitter.emit(event.value, *args, **kwargs)

    def on(
        self,
        event: RoRClientEvents,
        listener: Callable | None = None
    ) -> Callable | Callable[[Callable], Callable]:
        """Decorator to register an event handler on the event emitter.

        :param event: The event to register the handler on.
        :param listener: The listener to register.
        """
        return self._event_emitter.on(event.value, listener)

    def once(
        self,
        event: RoRClientEvents,
        listener: Callable | None = None
    ) -> Callable:
        """Decorator to register a one-time event handler on the event
        emitter.

        :param event: The event to register the handler on.
        :param listener: The listener to register.
        """
        return self._event_emitter.once(event.value, listener)

    def remove_listener(
        self,
        event: RoRClientEvents,
        listener: Callable
    ) -> None:
        """Removes an event handler from the event emitter.

        :param event: The event to remove the handler from.
        :param listener: The listener to remove.
        """
        logger.debug(
            '[EVENT] event=%r remove_listener=%r',
            event.value,
            listener.__name__
        )
        self._event_emitter.remove_listener(event.value, listener)

    async def register_stream(self, stream: StreamRegister) -> int:
        """Registers a stream with the server as the client.

        :param stream: The stream being registered.
        :return: The stream id of the stream.
        """
        stream.origin_source_id = self.unique_id
        stream.origin_stream_id = self._stream_id

        if isinstance(stream, ActorStreamRegister):
            stream.timestamp = -1

        payload = stream.pack()
        await self._send(
            StreamRegisterPacket(
                type=MessageType.STREAM_REGISTER,
                source=stream.origin_source_id,
                stream_id=stream.origin_stream_id,
                size=len(payload),
                payload=payload
            )
        )

        self.add_stream(stream)
        self._stream_id += 1

        return stream.origin_stream_id

    async def unregister_stream(self, stream_id: int) -> None:
        """Unregisters a stream with the server as the client.

        :param stream_id: The stream id of the stream to unregister.
        """
        await self._send(StreamUnregisterPacket(
            type=MessageType.STREAM_UNREGISTER,
            source=self.unique_id,
            stream_id=stream_id,
            size=0,
        ))

    async def reply_to_actor_stream_register(
        self,
        stream: ActorStreamRegister,
        status: ActorStreamStatus
    ) -> None:
        """Replies to an actor stream register request. This will
        determine what upstream arrow will be displayed on the client.

        :param stream: The stream to reply to.
        :param status: The status to reply with.
        """
        stream.status = status
        payload = stream.pack()
        await self._send(StreamRegisterResultPacket(
            type=MessageType.STREAM_REGISTER_RESULT,
            source=self.unique_id,
            stream_id=stream.origin_stream_id,
            size=len(payload),
            payload=payload
        ))

    async def send_stream_data(
        self,
        sid: int,
        stream_data: StreamData
    ) -> None:
        """Sends stream data to the server.

        :param sid: The stream id of the stream to send data to.
        :param stream_data: The stream data to send.
        """
        payload = stream_data.pack()
        await self._send(StreamDataPacket(
            type=MessageType.STREAM_DATA,
            source=self.unique_id,
            stream_id=sid,
            size=len(payload),
            payload=payload,
        ))

    async def send_actor_stream_data(
        self,
        sid: int,
        stream_data: ActorStreamData,
        recalculate_time: bool = True
    ) -> None:
        """Send actor stream data to the server.

        :param sid: The stream ID.
        :param stream_data: The stream data to send.
        :param recalculate_time: Whether or not to recalculate the
        timestamp of the stream data.
        """
        if recalculate_time:
            stream_data.time = math.floor(
                (time.time() - self.connect_time.timestamp()) * 1000
            )
        await self.send_stream_data(sid, stream_data)

    async def send_chat(self, message: str) -> None:
        """Sends a message to the game chat.

        :param message: The message to send.
        """
        logger.info('[CHAT] message=%r', message)

        payload = message.encode()
        await self._send(ChatPacket(
            type=MessageType.CHAT,
            source=self.unique_id,
            stream_id=self.get_chat_sid(self.unique_id),
            size=len(payload),
            payload=payload
        ))

    async def send_private_chat(self, uid: int, message: str) -> None:
        """Sends a private message to a user.

        :param uid: The uid of the user to send the message to.
        :param msg: The message to send.
        """
        logger.info('[PRIV] to_uid=%d message=%r', uid, message)

        payload = struct.pack('I8000s', uid, message.encode())
        await self._send(PrivateChatPacket(
            type=MessageType.PRIVATE_CHAT,
            source=self.unique_id,
            stream_id=self.get_chat_sid(self.unique_id),
            size=len(payload),
            payload=payload
        ))

    async def send_game_cmd(self, command: str) -> None:
        """Sends a game command (Angelscript) to the server.

        :param command: The command to send.
        """
        logger.debug('[GCMD] [SEND] game_cmd=%r', command)

        payload = command.encode()
        await self._send(GameCmdPacket(
            type=MessageType.GAME_CMD,
            source=self.unique_id,
            stream_id=0,
            size=len(payload),
            payload=payload
        ))

    async def move_bot(self, position: Vector3) -> None:
        """Moves the bot to a new position.

        :param position: The position to move the bot to, in meters.
        """
        self.character_stream_register.position = position

        stream_data = CharacterPositionStreamData(
            command=CharacterCommand.POSITION,
            position=position,
            rotation=self.character_stream_register.rotation,
            animation_time=0.0,
            animation_mode=CharacterAnimation.IDLE_SWAY,
        )

        payload = stream_data.pack()
        await self._send(StreamDataPacket(
            type=MessageType.STREAM_DATA,
            source=self.unique_id,
            stream_id=self.character_sid,
            size=len(payload),
            payload=payload
        ))

    async def rotate_bot(self, rotation: float) -> None:
        """Rotates the bot in place.

        :param rotation: The new rotation of the bot, in radians.
        """
        self.character_stream_register.rotation = rotation

        stream_data = CharacterPositionStreamData(
            command=CharacterCommand.POSITION,
            position=self.character_stream_register.position,
            rotation=rotation,
            animation_time=0.0,
            animation_mode=CharacterAnimation.IDLE_SWAY,
        )

        payload = stream_data.pack()
        await self._send(StreamDataPacket(
            type=MessageType.STREAM_DATA,
            source=self.unique_id,
            stream_id=self.character_sid,
            size=len(payload),
            payload=payload
        ))

    def get_uid_by_username(self, username: str) -> int | None:
        """Gets the uid of the user by their username.

        :param username: The username of the user.
        :return: The uid of the user.
        """
        for uid, user in self._users.items():
            if user.username == username:
                return uid
        return None

    def get_user(self, uid: int) -> User:
        """Gets a user from the stream manager.

        :param uid: The uid of the user.
        :return: The user.
        """
        try:
            return self._users[uid]
        except KeyError as e:
            logger.debug(
                '[USER] uid=%d not found in users %s',
                uid,
                pformat(self._users)
            )
            raise UserNotFoundError(f'User uid={uid} not found') from e

    def add_user(self, user_info: UserInfo) -> None:
        """Adds a client to the stream manager.

        :param user_info: The user info of the client to add.
        """
        if user_info.unique_id in self._users:
            raise UserAlreadyExistsError(
                f'User uid={user_info.unique_id} already exists'
            )

        self._users[user_info.unique_id] = User(info=user_info)

        self._global_stats.add_user(user_info.username)

        logger.debug(
            '[USER] Added username=%r uid=%d %s',
            user_info.username,
            user_info.unique_id,
            user_info
        )

    def update_user(self, user_info: UserInfo) -> None:
        """Updates a client in the stream manager.

        :param user_info: The user info of the client to update.
        """
        if user_info.unique_id not in self._users:
            self.add_user(user_info)
        else:
            self._users[user_info.unique_id].info = user_info

        logger.debug(
            '[USER] Updated username=%r uid=%d %s',
            user_info.username,
            user_info.unique_id,
            user_info
        )

    def delete_user(self, uid: int) -> None:
        """Deletes a client from the stream manager.

        :param uid: The uid of the client to delete.
        """
        user = self._users.pop(uid)

        self._global_stats.meters_driven += user.stats.meters_driven
        self._global_stats.meters_sailed += user.stats.meters_sailed
        self._global_stats.meters_walked += user.stats.meters_walked
        self._global_stats.meters_flown += user.stats.meters_flown

        self._global_stats.connection_times.append(
            datetime.now() - user.stats.online_since
        )

        logger.debug(
            '[USER] Deleted username=%r uid=%d %s',
            user.username,
            uid,
            user
        )

    def add_stream(self, stream: StreamRegister) -> None:
        """Adds a stream to the stream manager.

        :param stream: The stream to add.
        """
        self.get_user(stream.origin_source_id).add_stream(stream)

    def delete_stream(self, uid: int, sid: int) -> None:
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

    def set_current_stream(self, uid: int, stream_uid: int, sid: int) -> None:
        """Sets the current stream of the user.

        :param uid: The uid of the user.
        :param stream_uid: The uid of the user this stream belongs to.
        :param sid: The sid of the stream.
        """
        self.get_user(uid).set_current_stream(stream_uid, sid)

    def set_character_sid(self, uid: int, sid: int) -> None:
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

    def set_chat_sid(self, uid: int, sid: int) -> None:
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

    def set_position(self, uid: int, sid: int, position: Vector3) -> None:
        """Sets the position of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream.
        :param position: The position to set.
        """
        self.get_user(uid).set_position(sid, position)

    def get_position(self, uid: int, sid: int | None = None) -> Vector3 | None:
        """Gets the position of the stream. If sid is None, the current
        stream of the user is used. If the current stream is a chat
        stream, None is returned.

        :param uid: The uid of the user.
        :param sid: The sid of the stream, defaults to None
        :return: The position of the stream, if available.
        """
        if sid is None:
            stream = self.get_current_stream(uid)
        else:
            stream = self.get_user(uid).get_stream(sid)

        if isinstance(stream, ChatStreamRegister):
            return None

        return stream.position

    def set_rotation(self, uid: int, sid: int, rotation: float) -> None:
        """Sets the rotation of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream.
        :param rotation: The rotation to set in radians.
        """
        self.get_user(uid).set_rotation(sid, rotation)

    def get_rotation(self, uid: int, sid: int | None = None) -> float | None:
        """Gets the rotation of the stream. If sid is None, the current
        stream of the user is used. If the current stream is a chat
        stream, None is returned.

        :param uid: The uid of the user.
        :param sid: The sid of the stream, defaults to -1
        :return: The rotation of the stream in radians, if available.
        """
        if sid is None:
            stream = self.get_current_stream(uid)
        else:
            stream = self.get_user(uid).get_stream(sid)

        if isinstance(stream, ChatStreamRegister):
            return None

        return stream.rotation

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

    def get_auth_status(self, uid: int) -> AuthStatus:
        """Gets the authentication status of the user.

        :param uid: The uid of the user.
        :return: The authentication status of the user.
        """
        return self.get_user(uid).auth_status
