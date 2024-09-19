import asyncio
import logging
import math
from enum import auto, StrEnum
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from ror_server_bot import __version__
from ror_server_bot.config import RoRClientConfig
from ror_server_bot.utils import singledispatchmethod

from .enums import AuthStatus, Color, RoRClientEvents
from .models import Vector3
from .ror_connection import RoRConnection
from .stream_recorder import StreamRecorder

logger = logging.getLogger(__name__)

COMMAND_PREFIX = '>'


class InvalidArgumentsError(Exception):
    """Raised when a command is called with invalid arguments."""


class Command(StrEnum):
    """Enum of commands that can be executed by the bot."""
    HELP = auto()
    PREFIX = auto()
    PING = auto()
    BRB = auto()
    AFK = auto()
    BACK = auto()
    GTG = auto()
    VERSION = auto()
    COUNTDOWN = auto()
    MOVE_ROR_BOT = 'movebot'
    ROTATE_ROR_BOT = 'rotatebot'
    GET_POS = 'getpos'
    GET_ROT = 'getrot'
    RECORD = auto()
    PLAYBACK = auto()
    RECORDINGS = auto()


class RecordingCommand(StrEnum):
    """Enum of subcommands for stream recording commands."""
    START = auto()
    STOP = auto()
    PAUSE = auto()
    RESUME = auto()
    PLAY = auto()


class AnnouncementsHandler:
    def __init__(
        self,
        delay: int,
        enabled: bool,
        messages: list[str],
        color: str
    ) -> None:
        """Create a new AnnouncementsHandler.

        :param delay: The delay between announcements in seconds.
        :param enabled: Whether announcements are enabled.
        :param messages: The messages to announce.
        :param color: The color to use for the announcements.
        """
        self._delay = delay
        self._enabled = enabled
        self._messages = messages
        self._color = color
        self._time: float = 0
        self._idx: int = 0

    def try_next(self, delta: float) -> str | None:
        """Try to get the next announcement. Returns None if disabled or
        no announcement is ready. Otherwise, returns the announcement.

        The announcement format is as follows:
        ```
        <color>ANNOUNCEMENT: <message>
        ```
        Where `<color>` is the hex color to use for the announcement and
        `<message>` is the message to announce.

        :param delta: The time since the last frame step.
        :return: The announcement if one is ready, otherwise None.
        """
        if not self._enabled:
            return None

        self._time += delta

        if self._time >= self._delay:
            self._time = 0

            message = self._messages[self._idx]

            is_last_idx = self._idx == len(self._messages) - 1

            if is_last_idx:
                self._idx = 0
            else:
                self._idx += 1

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

        self.stream_recorder = StreamRecorder(self.server)

        self._announcements_handler = AnnouncementsHandler(
            delay=client_config.announcements.delay,
            enabled=client_config.announcements.enabled,
            messages=client_config.announcements.messages,
            color=client_config.announcements.color,
        )

        self.server.on(RoRClientEvents.FRAME_STEP, self._on_frame_step)
        self.server.on(RoRClientEvents.CHAT, self._on_chat)

    @property
    def auth_status(self) -> AuthStatus:
        """The authentication status of the client."""
        return self.server.auth_status

    async def __aenter__(self) -> Self:
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

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.server.__aexit__(exc_type, exc_val, exc_tb)

    async def _on_frame_step(self, delta: float) -> None:
        message = self._announcements_handler.try_next(delta)

        if message is not None:
            await self.server.send_chat(message)

    async def _on_chat(self, uid: int, msg: str) -> None:
        if msg.startswith(COMMAND_PREFIX):
            await self._perform_command(uid, msg)

    async def _perform_command(self, uid: int, msg: str) -> None:
        try:
            cmd, *args = msg[len(COMMAND_PREFIX):].split(' ')
            command = Command(cmd)
        except ValueError as exc:
            logger.warning(exc)
            await self.send_chat(f'Invalid command: {msg}')
            return

        logger.info('[CMD] uid=%d cmd=%r args=%s', uid, command, args)

        # Wait a bit before executing the command to give the
        # impression that the bot is typing the response.
        await asyncio.sleep(0.2)

        try:
            await self._execute_command(command, uid, *args, help=False)
        except InvalidArgumentsError:
            await self.send_chat(
                f'Invalid arguments for command: {command.value}\n'
                f'Use {COMMAND_PREFIX}help {command.value} for more info'
            )
        except Exception as exc:
            logger.error(
                'Error executing command: %r',
                exc,
                exc_info=True,
                stacklevel=2
            )

    @singledispatchmethod
    async def _execute_command(
        self,
        command: Command,
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        raise NotImplementedError(f'Command {command} is not implemented')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.HELP],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Shows help for a command.\n'
                f'Usage: {COMMAND_PREFIX}{command.value} <command>'
            )
            return

        match len(args):
            case 0:
                await self.send_chat(
                    f'Available commands: {', '.join(map(str, Command))}\n'
                    f'Use {COMMAND_PREFIX}help <command> for more info'
                )
            case 1:
                await self._execute_command(Command(args[0]), uid, help=True)
            case _:
                await self._execute_command(Command.HELP, uid, help=True)

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.PREFIX],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Retrieves the command prefix.\n'
                f'Usage: {COMMAND_PREFIX}{command.value}'
            )
            return

        if args:
            raise InvalidArgumentsError()

        await self.send_chat(f'The prefix for commands is: {COMMAND_PREFIX}')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.PING],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Pings the bot.\n'
                f'Usage: {COMMAND_PREFIX}{command.value}'
            )
            return

        if args:
            raise InvalidArgumentsError()

        await self.send_chat('pong')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.BRB, Command.AFK, Command.GTG, Command.BACK],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                f'Sets your status to "{command.value}".\n'
                f'Usage: {COMMAND_PREFIX}{command.value}'
            )
            return

        if args:
            raise InvalidArgumentsError()

        username = self.server.get_username_colored(uid)
        match command:
            case Command.BRB:
                await self.send_chat(f'{username} will brb!')
            case Command.AFK:
                await self.send_chat(f'{username} is afk')
            case Command.GTG:
                await self.send_chat(f'{username} is gtg')
            case Command.BACK:
                await self.send_chat(f'{username} is back')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.VERSION],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Shows the version of the bot.\n'
                f'Usage: {COMMAND_PREFIX}{command.value}'
            )
            return

        if args:
            raise InvalidArgumentsError()

        await self.send_chat(f'RoR Server Bot v{__version__}')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.COUNTDOWN],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Starts a countdown.\n'
                f'Usage: {COMMAND_PREFIX}{command.value} <seconds>'
            )
            return

        if len(args) != 1:
            raise InvalidArgumentsError()

        seconds = int(args[0])

        if seconds < 1:
            await self.send_chat('The countdown must be at least 1 second')
            return

        username = self.server.get_username(uid)
        await self.send_chat(
            f'{username} started a {seconds} second countdown!'
        )

        # start at 1 to immediately send the first countdown message
        time: float = 1

        @self.server.on(RoRClientEvents.FRAME_STEP)
        async def on_frame_step(delta: float) -> None:
            # nonlocal is needed to modify the time and seconds variables
            nonlocal time, seconds

            time += delta

            if time >= 1:
                if seconds > 0:
                    await self.send_chat(f'{Color.RED}\t{seconds}')
                    seconds -= 1
                    time = 0
                else:
                    await self.send_chat(f'{Color.GREEN}\tGO!!!')
                    self.server.remove_listener(
                        RoRClientEvents.FRAME_STEP,
                        on_frame_step
                    )

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.MOVE_ROR_BOT],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Moves the bot to a different position on the map.\n'
                f'Usage: {COMMAND_PREFIX}{command.value} <x> <y> <z>'
            )
            return

        if len(args) != 3:
            raise InvalidArgumentsError()

        x, y, z = map(float, args)
        new_pos = Vector3(x=x, y=y, z=z)

        await self.move_bot(new_pos)
        await self.send_chat(f'Moved bot to {new_pos}')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.ROTATE_ROR_BOT],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Rotates the bot a number of degrees.\n'
                f'Usage: {COMMAND_PREFIX}{command.value} <rotation>'
            )
            return

        if len(args) != 1:
            raise InvalidArgumentsError()

        rotation_degrees = float(args[0])

        await self.rotate_bot(math.radians(rotation_degrees))
        await self.send_chat(f'Rotated bot to {rotation_degrees}')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.GET_POS],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Gets your current position on the map.\n'
                f'Usage: {COMMAND_PREFIX}{command.value}'
            )
            return

        if args:
            raise InvalidArgumentsError()

        position = self.server.get_position(uid)
        if position is None:
            await self.send_chat('Could not get your position')
        else:
            await self.send_chat(f'Your position is: {position:.2f}')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.GET_ROT],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Gets your current rotation on the map.\n'
                f'Usage: {COMMAND_PREFIX}{command.value}'
            )
            return

        if args:
            raise InvalidArgumentsError()

        rotation_radians = self.server.get_rotation(uid)
        if rotation_radians is None:
            await self.send_chat('Could not get your rotation')
        else:
            rotation_degrees = math.degrees(rotation_radians)
            await self.send_chat(f'Your rotation is: {rotation_degrees:.2f}')

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.RECORD],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Manage stream recordings. If a stream ID is not provided, '
                'the current stream will be used.\n'
                'Usages:\n'
                + '\n'.join([
                    f'{COMMAND_PREFIX}{command.value} {cmd.value} [sid]'
                    for cmd in (
                        RecordingCommand.START,
                        RecordingCommand.STOP,
                        RecordingCommand.PAUSE,
                        RecordingCommand.RESUME
                    )
                ])
            )
            return

        user = self.server.get_user(uid)
        if user.auth_status not in AuthStatus.MOD | AuthStatus.ADMIN:
            await self.send_chat('You do not have permission to do that')
            return

        match len(args):
            case 1:
                sid = user.current_stream.stream_id
            case 2:
                sid = int(args[1])
            case _:
                raise InvalidArgumentsError()

        subcommand = RecordingCommand(args[0])

        match subcommand:
            case RecordingCommand.START:
                filename = None  # TODO: set the filename
                self.stream_recorder.start_recording(user.info, sid, filename)
                await self.send_chat(f'Started recording uid={uid} sid={sid}')
            case RecordingCommand.STOP:
                self.stream_recorder.stop_recording(uid, sid)
                await self.send_chat(f'Stopped recording uid={uid} sid={sid}')
            case RecordingCommand.PAUSE:
                self.stream_recorder.pause_recording(uid, sid)
                await self.send_chat(f'Paused recording uid={uid} sid={sid}')
            case RecordingCommand.RESUME:
                self.stream_recorder.resume_recording(uid, sid)
                await self.send_chat(f'Resumed recording uid={uid} sid={sid}')
            case _:
                raise InvalidArgumentsError()

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.PLAYBACK],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Control playback of a recording.\n'
                'Usages:\n'
                + '\n'.join([
                    f'{COMMAND_PREFIX}{command.value} {cmd.value} [filename]'
                    for cmd in (
                        RecordingCommand.PLAY,
                        RecordingCommand.STOP,
                        RecordingCommand.PAUSE,
                        RecordingCommand.RESUME
                    )
                ])
            )
            return

        user = self.server.get_user(uid)
        if user.auth_status not in AuthStatus.MOD | AuthStatus.ADMIN:
            await self.send_chat('You do not have permission to do that')
            return

        if not args:
            raise InvalidArgumentsError()

        subcommand = RecordingCommand(args[0])

        if len(args) > 2:
            raise InvalidArgumentsError()

        def sid() -> int | None:
            return None if len(args) == 1 else int(args[1])

        match subcommand:
            case RecordingCommand.PLAY:
                filename = None if len(args) == 1 else Path(args[1])
                await self.stream_recorder.play_recording(filename)
            case RecordingCommand.STOP:
                await self.stream_recorder.stop_playback(sid())
            case RecordingCommand.PAUSE:
                self.stream_recorder.pause_playback(sid())
            case RecordingCommand.RESUME:
                self.stream_recorder.resume_playback(sid())
            case _:
                raise InvalidArgumentsError()

    @_execute_command.register
    async def _(
        self,
        command: Literal[Command.RECORDINGS],
        uid: int,
        *args: str,
        help: bool
    ) -> None:
        if help:
            await self.send_chat(
                'Lists available recordings.\n'
                f'Usage: {COMMAND_PREFIX}{command.value}'
            )
            return

        user = self.server.get_user(uid)
        if user.auth_status not in AuthStatus.MOD | AuthStatus.ADMIN:
            await self.send_chat('You do not have permission to do that')
            return

        if args:
            raise InvalidArgumentsError()

        if self.stream_recorder.available_recordings:
            files = '\n'.join(
                file.name for file in
                self.stream_recorder.available_recordings
            )
            await self.send_chat(f'Available recordings:\n{files}')
        else:
            await self.send_chat('No recordings available')

    async def start(self) -> None:
        """Start the RoR client."""
        async with self:
            while True:
                await asyncio.sleep(0.1)

    async def send_chat(self, message: str) -> None:
        """Send a chat message to the server.

        :param message: The message to send.
        """
        await self.server.send_chat(message)

    async def send_private_chat(self, uid: int, message: str) -> None:
        """Send a private chat message to a user.

        :param uid: The user's UID.
        :param message: The message to send.
        """
        await self.server.send_private_chat(uid, message)

    async def kick(self, uid: int, reason: str = 'No reason given') -> None:
        """Kicks a user from the server.

        :param uid: The uid of the user to kick.
        :param reason: The reason for kicking the user, defaults to
        'No reason given'
        """
        await self.send_chat(f'!kick {uid} {reason}')

    async def ban(self, uid: int, reason: str = 'No reason given') -> None:
        """Bans a user from the server.

        :param uid: The uid of the user to ban.
        :param reason: The reason for banning the user, defaults to
        'No reason given'
        """
        await self.send_chat(f'!ban {uid} {reason}')

    async def say(self, uid: int, message: str) -> None:
        """Send a message as a user anonymously.

        :param uid: The uid of the user to send the message to. If -1,
        the message will be sent to everyone.
        :param message: The message to send.
        """
        await self.send_chat(f'!say {uid} {message}')

    async def send_game_cmd(self, cmd: str) -> None:
        """Send a game command to the server.

        :param cmd: The command to send.
        """
        await self.server.send_game_cmd(cmd)

    async def move_bot(self, position: Vector3) -> None:
        """Move the bot to a position.

        :param position: The position to move the bot to, in meters.
        """
        await self.server.move_bot(position)

    async def rotate_bot(self, rotation: float) -> None:
        """Rotate the bot to a rotation.

        :param rotation: The new rotation of the bot, in radians.
        """
        await self.server.rotate_bot(rotation)
