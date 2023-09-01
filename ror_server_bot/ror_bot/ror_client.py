import asyncio
import logging
import struct
import time
from enum import Enum
from typing import Callable

from pyee.asyncio import AsyncIOEventEmitter

from .enums import MessageType, StreamType
from .models import (
    Packet,
    RoRClientConfig,
    stream_data_factory,
    stream_register_factory,
    UserInfo,
)
from .packet_handler import PacketHandler
from .ror_connection import RoRConnection, UserNotFoundError
from .user import StreamNotFoundError

logger = logging.getLogger(__name__)


def check_packet_type(packet: Packet, message_type: MessageType) -> bool:
    """Check if the packet is of the specified type.

    :param packet: The packet to check.
    :param message_type: The type to check the packet against.
    :return: True if the packet is of the specified type, False
    """
    return packet.command is message_type


class RoRClientEvents(Enum):
    FRAME_STEP = 'frame_step'
    NET_QUALITY = 'net_quality'
    CHAT = 'chat'
    PRIVATE_CHAT = 'private_chat'
    USER_JOIN = 'user_join'
    USER_INFO = 'user_info'
    USER_LEAVE = 'user_leave'
    GAME_CMD = 'game_cmd'
    STREAM_REGISTER = 'stream_register'
    STREAM_REGISTER_RESULT = 'stream_register_result'
    STREAM_DATA = 'stream_data'
    STREAM_UNREGISTER = 'stream_unregister'


class RoRClient(PacketHandler):
    STABLE_FPS = 20

    def __init__(self, client_config: RoRClientConfig) -> None:
        """Create a new RoRClient. This class is used to connect to a
        RoR server and handle packets received from the server. It
        inherits from PacketHandler and registers event handlers on
        an AsyncIOEventEmitter.

        See `ror_client.packet_handler.PacketHandler` for more information.

        :param client_config: The configuration to use for the client.
        """
        self.config = client_config

        self.server = RoRConnection(
            username=self.config.user.name,
            user_token=self.config.user.token,
            password=self.config.server.password,
            host=self.config.server.host,
            port=self.config.server.port,
        )

        super().__init__(self.server)

        self._frame_step_task: asyncio.Task

        self.event_emitter = AsyncIOEventEmitter()

        self.event_emitter.add_listener('new_listener', self._new_listener)
        self.event_emitter.add_listener('error', self._error)

    async def __aenter__(self):
        for attempt in range(self.config.reconnection_tries):
            try:
                logger.info(
                    'Attempt %d/%d to connect to RoR server: %s',
                    attempt + 1,
                    self.config.reconnection_tries,
                    self.server.address
                )
                self.server = await self.server.__aenter__()
            except ConnectionRefusedError:
                logger.warning('Connection refused!')

                if attempt < self.config.reconnection_tries - 1:
                    logger.info(
                        'Waiting %.2f seconds before next attempt',
                        self.config.reconnection_interval
                    )
                    await asyncio.sleep(self.config.reconnection_interval)
            else:
                break

        if self.server.is_connected:
            logger.info('Connected to RoR server: %s', self.server.address)
        else:
            raise ConnectionError(
                f'Could not connect to RoR server {self.server.address} '
                f'after {self.config.reconnection_tries} attempts',
            )

        self._frame_step_task = asyncio.create_task(
            self._frame_step_loop(),
            name='frame_step_loop'
        )

        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.server.__aexit__(exc_type, exc, tb)

        if self._frame_step_task:
            self._frame_step_task.cancel()

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
        logger.error('%r', error, exc_info=True)

    def on(self, event: RoRClientEvents, listener: Callable | None = None):
        """Decorator to register an event handler on the event emitter.

        :param event: The event to register the handler on.
        :param listener: The listener to register.
        """
        return self.event_emitter.on(event.value, listener)

    def once(self, event: RoRClientEvents, listener: Callable | None = None):
        """Decorator to register a one-time event handler on the event
        emitter.

        :param event: The event to register the handler on.
        :param listener: The listener to register.
        """
        return self.event_emitter.once(event.value, listener)

    def emit(self, event: RoRClientEvents, *args, **kwargs):
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
                len(self.event_emitter.listeners(event.value))
            )
        self.event_emitter.emit(event.value, *args, **kwargs)

    async def _frame_step_loop(self):
        """Send frame_step events at a stable rate."""
        start_time = time.time()
        current_time = start_time
        delta = 0
        while True:
            prev_time = current_time
            current_time = time.time()
            delta += current_time - prev_time

            if delta >= (self.STABLE_FPS / 60):
                self.emit(RoRClientEvents.FRAME_STEP, delta)
                delta = 0

            await asyncio.sleep(0.01)

    def on_packet(self, packet: Packet) -> None:
        """Handle packets received from the server.

        :param packet: The packet to handle.
        """
        if (
            packet.command in (MessageType.HELLO, MessageType.WELCOME)
            or f'packet.{packet.command.name}' in self.server.event_names()
        ):
            return

        logger.warning('Unhandled packet command: %r', packet.command)

    def on_net_quality(self, packet: Packet) -> None:
        """Handle net_quality packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.NET_QUALITY):
            return

        net_quality: int = struct.unpack('I', packet.data)[0]

        if self.server.net_quality != net_quality:
            logger.info(
                'Net quality for uid=%d changed: %d -> %d',
                packet.source,
                self.server.net_quality,
                net_quality
            )
            self.emit(RoRClientEvents.NET_QUALITY, packet.source, net_quality)
        else:
            logger.debug(
                'Net quality unchanged for uid=%d: %d',
                packet.source,
                net_quality
            )

        self.server.net_quality = net_quality

    def on_chat(self, packet: Packet) -> None:
        """Handle chat packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.CHAT):
            return

        message = packet.data.decode().strip('\x00')

        logger.info('[CHAT] from_uid=%d message=%r', packet.source, message)

        if message and packet.source != self.server.unique_id:
            self.emit(RoRClientEvents.CHAT, packet.source, message)

    def on_private_chat(self, packet: Packet) -> None:
        """Handle private_chat packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.PRIVATE_CHAT):
            return

        message = packet.data.decode().strip('\x00')

        logger.info('[PRIV] from_uid=%d message=%r', packet.source, message)

        if message and packet.source != self.server.unique_id:
            self.emit(RoRClientEvents.PRIVATE_CHAT, packet.source, message)

    def on_user_join(self, packet: Packet) -> None:
        """Handle user_join packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.USER_JOIN):
            return

        logger.info('User join received')

        user_info = UserInfo.from_bytes(packet.data)

        self.server.add_user(user_info)

        if user_info.unique_id != self.server.unique_id:
            self.emit(RoRClientEvents.USER_JOIN, packet.source, user_info)

    def on_user_info(self, packet: Packet) -> None:
        """Handle user_info packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.USER_INFO):
            return

        logger.info('User info received')

        user_info = UserInfo.from_bytes(packet.data)

        self.server.add_user(user_info)

        if user_info.unique_id != self.server.unique_id:
            self.emit(RoRClientEvents.USER_INFO, packet.source, user_info)

    def on_user_leave(self, packet: Packet) -> None:
        """Handle user_leave packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.USER_LEAVE):
            return

        logger.info(
            'uid=%r left with reason: %s',
            packet.source,
            packet.data
        )

        if packet.source == self.server.unique_id:
            raise ConnectionError('RoRClient disconnected from the server')

        self.server.delete_user(packet.source)

        self.emit(RoRClientEvents.USER_LEAVE, packet.source)

    def on_game_cmd(self, packet: Packet) -> None:
        """Handle game_cmd packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.GAME_CMD):
            return

        if packet.source == self.server.unique_id:
            return

        game_cmd = packet.data.decode().strip('\x00')

        logger.debug('[GAME_CMD] from_uid=%d cmd=%r', packet.source, game_cmd)

        if game_cmd and packet.source != self.server.unique_id:
            self.emit(RoRClientEvents.GAME_CMD, packet.source, game_cmd)

    async def on_stream_register(self, packet: Packet) -> None:
        """Handle stream_register packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.STREAM_REGISTER):
            return

        stream = stream_register_factory(packet.data)

        logger.info('Stream register received: %s', stream)

        self.server.add_stream(stream)

        if stream.type is StreamType.ACTOR:
            # why?
            await self.server.reply_to_stream_register(stream, status=-1)

        self.emit(RoRClientEvents.STREAM_REGISTER, packet.source, stream)

    def on_stream_register_result(self, packet: Packet) -> None:
        """Handle stream_register_result packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.STREAM_REGISTER_RESULT):
            return

        stream = stream_register_factory(packet.data)

        logger.info('Stream register result received: %s', stream)

        self.emit(
            RoRClientEvents.STREAM_REGISTER_RESULT,
            packet.source,
            stream,
        )

    def on_stream_data(self, packet: Packet) -> None:
        """Handle stream_data packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.STREAM_DATA):
            return

        try:
            stream = self.server.get_stream(
                packet.source,
                packet.stream_id
            )
        except UserNotFoundError:
            logger.error(
                'Could not find user! uid=%d',
                packet.source,
                exc_info=True
            )
        except StreamNotFoundError:
            logger.error(
                'Could not find stream! sid=%d',
                packet.stream_id,
                exc_info=True
            )
        else:
            if stream.type in (StreamType.CHARACTER, StreamType.ACTOR):
                logger.info('%s stream received', stream.type.name.title())
                stream_data = stream_data_factory(stream.type, packet.data)

                logger.debug('Stream data: %s', stream_data)
            elif stream.type is StreamType.CHAT:
                logger.info('Chat stream received')
                stream_data = None
            else:
                raise ValueError(f'Unknown stream type: {stream.type!r}')

            self.emit(
                RoRClientEvents.STREAM_DATA,
                packet.source,
                stream,
                stream_data
            )

    def on_stream_unregister(self, packet: Packet) -> None:
        """Handle stream_unregister packets.

        :param packet: The packet to handle.
        """
        if not check_packet_type(packet, MessageType.STREAM_UNREGISTER):
            return

        if len(packet.data) != 0:
            raise ValueError('Stream unregister packet has data')

        logger.info('Stream unregister received: %s', packet)

        self.server.delete_stream(
            packet.source,
            packet.stream_id
        )

        self.emit(
            RoRClientEvents.STREAM_UNREGISTER,
            packet.source,
            packet.stream_id
        )
