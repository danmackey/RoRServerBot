import logging
import math
from enum import auto, StrEnum
from pathlib import Path
from typing import Annotated, Literal, TYPE_CHECKING

from pydantic import BaseModel, Field, TypeAdapter

from ror_server_bot import __version__

from .enums import AuthStatus, Color, RoRClientEvents
from .models import Vector3
from .stream_recorder import StreamRecordingError

if TYPE_CHECKING:
    from .ror_client import RoRClient

logger = logging.getLogger(__name__)

COMMAND_PREFIX = '>'


class CommandType(StrEnum):
    PREFIX = auto()
    PING = auto()
    HELP = auto()
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


class BaseChatCommand(BaseModel):
    command: CommandType
    args: list[str] = Field(default_factory=list)

    @property
    def description(self) -> str:
        return 'No description provided.'

    @property
    def usage(self) -> str:
        return f'{COMMAND_PREFIX}{self.name}'

    @property
    def name(self) -> str:
        return self.command.value

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        """Execute the command.

        :param client: The client to execute the command for.
        :param uid: The UID of the user who sent the command.
        """
        raise NotImplementedError()


class PrefixCommand(BaseChatCommand):
    command: Literal[CommandType.PREFIX]

    @property
    def description(self) -> str:
        return 'Get the prefix for commands.'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        await client.send_chat(
            f'The prefix for commands is: {COMMAND_PREFIX}'
        )


class PingCommand(BaseChatCommand):
    command: Literal[CommandType.PING]

    @property
    def description(self) -> str:
        return 'Ping the bot.'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        await client.send_chat('pong')


class HelpCommand(BaseChatCommand):
    command: Literal[CommandType.HELP]

    @property
    def description(self) -> str:
        return 'Get help for commands.'

    @property
    def usage(self) -> str:
        return f'{super().usage} [command]'

    def no_args(self) -> str:
        commands = ', '.join(CommandType.__members__.values())
        return (
            f'Available commands: {commands}\n'
            f'Use {self.usage} for more information.'
        )

    def one_arg(self) -> str:
        cmd_name = self.args[0]
        if cmd_name in CommandType.__members__.values():
            command = chat_command_factory(cmd_name)
            return (
                f'{COMMAND_PREFIX}{self.name} {cmd_name}\n'
                f'Description: {command.description}\n'
                f'Usage: {command.usage}'
            )
        else:
            return f'Invalid command {cmd_name}'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        if len(self.args) == 0:
            message = self.no_args()
        elif len(self.args) == 1:
            message = self.one_arg()
        else:
            message = 'Too many arguments'

        # why can't AUTH_STATUS.BOT use !say ???
        if client.auth_status in AuthStatus.MOD | AuthStatus.ADMIN:
            await client.say(uid, message)
        else:
            await client.send_chat(message)


class SetStatusCommand(BaseChatCommand):
    command: Literal[
        CommandType.BRB,
        CommandType.AFK,
        CommandType.BACK,
        CommandType.GTG
    ]

    @property
    def description(self) -> str:
        return f'Set your status to {self.name}.'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        if len(self.args) == 0:
            username = client.server.get_username_colored(uid)
            if self.command is CommandType.BRB:
                message = f'{username} will brb!'
            elif self.command is CommandType.AFK:
                message = f'{username} is afk!'
            elif self.command is CommandType.BACK:
                message = f'{username} is back!'
            elif self.command is CommandType.GTG:
                message = f'{username} is gtg'
            else:
                raise ValueError(f'Invalid command {self.command}')
        else:
            message = 'Too many arguments'

        await client.send_chat(message)


class GetVersionCommand(BaseChatCommand):
    command: Literal[CommandType.VERSION]

    @property
    def description(self) -> str:
        return 'Get the version of the bot.'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        await client.send_chat(f'RoR Server Bot v{__version__}')


class CountdownCommand(BaseChatCommand):
    command: Literal[CommandType.COUNTDOWN]

    @property
    def description(self) -> str:
        return 'Start a countdown.'

    @property
    def usage(self) -> str:
        return f'{super().usage} <seconds>'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        if len(self.args) != 1:
            await client.send_chat('Invalid number of arguments')
            return

        try:
            seconds = int(self.args[0])
        except ValueError:
            await client.send_chat('Invalid argument')
            return
        else:
            if seconds < 0:
                await client.send_chat('Invalid argument')
                return

        username = client.server.get_username(uid)
        await client.send_chat(
            f'{username} started a {seconds} second countdown!'
        )

        # start at 1 to immediately send the first countdown message
        time: float = 1

        @client.server.on(RoRClientEvents.FRAME_STEP)
        async def on_frame_step(delta: float) -> None:
            # nonlocal is needed to modify the time and seconds variables
            nonlocal time, seconds

            time += delta

            if time >= 1:
                if seconds > 0:
                    await client.send_chat(f'{Color.RED}\t{seconds}')
                    seconds -= 1
                    time = 0
                else:
                    await client.send_chat(f'{Color.GREEN}\tGO!!!')
                    client.server.remove_listener(
                        RoRClientEvents.FRAME_STEP,
                        on_frame_step
                    )


class MoveRoRBotCommand(BaseChatCommand):
    command: Literal[CommandType.MOVE_ROR_BOT]

    @property
    def description(self) -> str:
        return 'Move the bot to a different position on the map.'

    @property
    def usage(self) -> str:
        return f'{super().usage} <x> <y> <z>'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        if len(self.args) != 3:
            await client.send_chat('Invalid number of arguments')
            return

        try:
            new_pos = Vector3(x=self.args[0], y=self.args[1], z=self.args[2])
        except Exception:
            await client.send_chat('Invalid argument')
            return

        await client.move_bot(new_pos)
        await client.send_chat(f'Moved bot to {new_pos}')


class RotateRoRBotCommand(BaseChatCommand):
    command: Literal[CommandType.ROTATE_ROR_BOT]

    @property
    def description(self) -> str:
        return 'Rotate the bot a number of degrees.'

    @property
    def usage(self) -> str:
        return f'{super().usage} <degrees>'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        if len(self.args) != 1:
            await client.send_chat('Invalid number of arguments')
            return

        try:
            rot_deg = float(self.args[0])
        except ValueError:
            await client.send_chat('Invalid argument')
            return

        rot_rad = math.radians(rot_deg)
        await client.rotate_bot(rot_rad)
        await client.send_chat(f'Rotated bot to {rot_deg}')


class GetPositionCommand(BaseChatCommand):
    command: Literal[CommandType.GET_POS]

    @property
    def description(self) -> str:
        return 'Get your current position on the map.'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        position = client.server.get_position(uid)
        await client.send_chat(f'Your position is {position:.2f}')


class GetRotationCommand(BaseChatCommand):
    command: Literal[CommandType.GET_ROT]

    @property
    def description(self) -> str:
        return 'Get your current rotation on the map.'

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        rot_rad = client.server.get_rotation(uid)

        if rot_rad is None:
            await client.send_chat('Your rotation is unknown')
            return

        rot_deg = math.degrees(rot_rad)
        await client.send_chat(f'Your rotation is {rot_deg:.2f}')


class StreamRecorderSubcommand(StrEnum):
    START = auto()
    STOP = auto()
    PLAY = auto()
    PAUSE = auto()
    RESUME = auto()


class StreamRecorderCommand(BaseChatCommand):
    command: Literal[
        CommandType.RECORD,
        CommandType.PLAYBACK,
        CommandType.RECORDINGS
    ]

    @property
    def description(self) -> str:
        return 'Record or playback a stream.'

    @property
    def usage(self) -> str:
        return super().usage

    @property
    def subcommand(self) -> StreamRecorderSubcommand:
        return StreamRecorderSubcommand(self.args[0])

    async def record(
        self,
        client: 'RoRClient',
        uid: int,
        sid: int
    ) -> None:
        match self.subcommand:
            case (
                StreamRecorderSubcommand.START | StreamRecorderSubcommand.PLAY
            ):
                user_info = client.server.get_user(uid).info
                client.stream_recorder.start_recording(user_info, sid)
                await client.send_chat(f'Recording {uid}:{sid}')
            case StreamRecorderSubcommand.STOP:
                client.stream_recorder.stop_recording(uid, sid)
                await client.send_chat(f'Stopped recording {uid}:{sid}')
            case StreamRecorderSubcommand.PAUSE:
                client.stream_recorder.pause_recording(uid, sid)
                await client.send_chat(f'Paused recording {uid}:{sid}')
            case StreamRecorderSubcommand.RESUME:
                client.stream_recorder.resume_recording(uid, sid)
                await client.send_chat(f'Resumed recording {uid}:{sid}')
            case _:
                await client.send_chat('Invalid subcommand')

    async def playback(self, client: 'RoRClient') -> None:
        if self.subcommand in (
            StreamRecorderSubcommand.START, StreamRecorderSubcommand.PLAY
        ):
            if len(self.args) == 1:
                filename = None
            elif len(self.args) == 2:
                filename = Path(self.args[1])
            else:
                await client.send_chat('Invalid number of arguments')
                return
            await client.stream_recorder.play_recording(filename)
        else:
            if len(self.args) == 1:
                sid = None
            elif len(self.args) == 2:
                sid = int(self.args[1])
            else:
                await client.send_chat('Invalid number of arguments')
                return
            match self.subcommand:
                case StreamRecorderSubcommand.STOP:
                    await client.stream_recorder.stop_playback(sid)
                case StreamRecorderSubcommand.PAUSE:
                    client.stream_recorder.pause_playback(sid)
                case StreamRecorderSubcommand.RESUME:
                    client.stream_recorder.resume_playback(sid)
                case _:
                    await client.send_chat('Invalid subcommand')

    async def recordings(self, client: 'RoRClient') -> None:
        if client.stream_recorder.available_recordings:
            files = '\n'.join(
                file.name for file in
                client.stream_recorder.available_recordings
            )
            await client.send_chat(f'Available recordings:\n{files}')
        else:
            await client.send_chat('No recordings available')

    async def execute(self, client: 'RoRClient', uid: int) -> None:
        user = client.server.get_user(uid)
        if user.auth_status not in AuthStatus.MOD | AuthStatus.ADMIN:
            await client.send_chat('You do not have permission to do that.')
            return

        try:
            if self.args:
                if len(self.args) == 1:
                    sid = client.server.get_user(uid).current_stream.stream_id
                elif len(self.args) == 2:
                    sid = int(self.args[1])
                else:
                    await client.send_chat('Invalid number of arguments')
                    return

                match self.command:
                    case CommandType.RECORD:
                        await self.record(client, uid, sid)
                    case CommandType.PLAYBACK:
                        await self.playback(client)
                    case _:
                        raise ValueError(f'Invalid command {self.command}')
            elif self.command is CommandType.RECORDINGS:
                await self.recordings(client)
            else:
                await client.send_chat('Invalid number of arguments')
        except StreamRecordingError as e:
            logger.error('[REC] %r', e, exc_info=True, stacklevel=2)
            await client.send_chat(str(e))


ChatCommandTypes = (
    PrefixCommand
    | PingCommand
    | HelpCommand
    | SetStatusCommand
    | GetVersionCommand
    | CountdownCommand
    | MoveRoRBotCommand
    | RotateRoRBotCommand
    | GetPositionCommand
    | GetRotationCommand
    | StreamRecorderCommand
)

ChatCommand = Annotated[ChatCommandTypes, Field(discriminator='command')]

ChatCommandValidator = TypeAdapter(ChatCommand)


def chat_command_factory(message: str) -> ChatCommand:
    command, *args = message.split(' ')
    chat_command = ChatCommandValidator.validate_python({
        'command': command,
        'args': args
    })
    if not isinstance(chat_command, BaseChatCommand):
        raise ValueError('Invalid chat command')
    return chat_command
