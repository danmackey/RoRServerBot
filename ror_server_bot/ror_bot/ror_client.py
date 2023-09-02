import asyncio
import logging
import math

from .commands import chat_command_factory, COMMAND_PREFIX
from .enums import AuthStatus, RoRClientEvents
from .models import RoRClientConfig
from .ror_connection import RoRConnection

logger = logging.getLogger(__name__)


class AnnouncementsHandler:
    def __init__(self, delay: int, messages: list[str], color: str) -> None:
        """Create a new AnnouncementsHandler.

        :param delay: The delay between announcements in seconds.
        :param messages: The messages to announce.
        :param color: The color to use for the announcements.
        """
        self._delay = delay
        self._messages = messages
        self._color = color
        self._time: float = 0
        self._idx: int = 0

    def try_next(self, delta: float) -> str | None:
        """Try to get the next announcement. Returns None if no
        announcement is ready. Otherwise, returns the announcement.

        The announcement format is as follows:
        ```
        <color>ANNOUNCEMENT: <message>
        ```
        Where `<color>` is the hex color to use for the announcement and
        `<message>` is the message to announce.

        :param delta: The time since the last frame step.
        :return: The announcement if one is ready, otherwise None.
        """
        self._time += delta

        if self._time >= self._delay:
            self._time = 0

            idx = self._idx

            if idx == len(self._messages) - 1:
                self._idx = 0
            else:
                self._idx += 1

            message = self._messages[idx]

            return f'{self._color}ANNOUNCEMENT: {message}'
        else:
            return None


class RoRClient:
    def __init__(self, client_config: RoRClientConfig) -> None:
        """Create a new RoRClient.

        :param client_config: The configuration to use for the client.
        """
        self._reconnection_tries = client_config.reconnection_tries
        self._reconnection_interval = client_config.reconnection_interval

        self.server = RoRConnection(
            username=client_config.user.name,
            user_token=client_config.user.token,
            password=client_config.server.password,
            host=client_config.server.host,
            port=client_config.server.port,
        )

        self._announcements_enabled = client_config.announcements.enabled
        self._announcements_handler = AnnouncementsHandler(
            delay=client_config.announcements.delay,
            messages=client_config.announcements.messages,
            color=client_config.announcements.color,
        )

        self.server.on(RoRClientEvents.FRAME_STEP, self._on_frame_step)
        self.server.on(RoRClientEvents.CHAT, self._on_chat)

    @property
    def auth_status(self) -> AuthStatus:
        """The authentication status of the client."""
        return self.server.auth_status

    async def __aenter__(self):
        for attempt in range(self._reconnection_tries):
            try:
                logger.info(
                    'Attempt %d/%d to connect to RoR server: %s',
                    attempt + 1,
                    self._reconnection_tries,
                    self.server.address
                )
                self.server = await self.server.__aenter__()
            except ConnectionRefusedError:
                logger.warning('Connection refused!')

                if attempt < self._reconnection_tries - 1:
                    logger.info(
                        'Waiting %.2f seconds before next attempt',
                        self._reconnection_interval
                    )
                    await asyncio.sleep(self._reconnection_interval)
            else:
                break

        if self.server.is_connected:
            logger.info('Connected to RoR server: %s', self.server.address)
        else:
            raise ConnectionError(
                f'Could not connect to RoR server {self.server.address} '
                f'after {self._reconnection_tries} attempts',
            )

        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.server.__aexit__(exc_type, exc, tb)

    async def _on_frame_step(self, delta: float):
        if self._announcements_enabled:
            message = self._announcements_handler.try_next(delta)

            if message is not None:
                await self.server.send_chat(message)

    async def _on_chat(self, uid: int, msg: str):
        if msg.startswith(COMMAND_PREFIX):
            logger.info('User %d sent command: %r', uid, msg)
            try:
                command = chat_command_factory(
                    msg[len(COMMAND_PREFIX):]
                )
            except ValueError as e:
                logger.warning(e)
                await self.send_private_chat(uid, f'Invalid command: {msg}')
            else:
                # Wait a bit before executing the command to give the
                # impression that the bot is typing the response.
                await asyncio.sleep(0.2)
                await command.execute(self, uid)

    async def send_chat(self, message: str):
        """Send a chat message to the server.

        :param message: The message to send.
        """
        await self.server.send_chat(message)

    async def send_private_chat(self, uid: int, message: str):
        """Send a private chat message to a user.

        :param uid: The user's UID.
        :param message: The message to send.
        """
        await self.server.send_private_chat(uid, message)

    async def send_multiline_chat(self, message: str):
        """Sends a multiline message to the game chat.

        :param message: The message to send.
        """
        max_line_len = 100
        if len(message) > max_line_len:
            logger.debug('[CHAT] multiline_message=%r', message)

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

    async def send_game_cmd(self, cmd: str):
        """Send a game command to the server.

        :param cmd: The command to send.
        """
        await self.server.send_game_cmd(cmd)
