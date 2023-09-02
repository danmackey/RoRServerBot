from enum import auto, StrEnum
from typing import Annotated, Literal, TYPE_CHECKING

from pydantic import BaseModel, Field, RootModel

from ror_server_bot import __version__

from .enums import AuthStatus, Color, RoRClientEvents

if TYPE_CHECKING:
    from .ror_client import RoRClient


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


class BaseChatCommand(BaseModel):
    command: CommandType
    args: list[str] = Field(default_factory=list)

    @property
    def description(self) -> str:
        return 'No description provided.'

    @property
    def usage(self) -> str:
        return 'No usage provided.'

    @property
    def name(self) -> str:
        return self.command.value

    async def execute(self, client: 'RoRClient', uid: int):
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

    @property
    def usage(self) -> str:
        return f'{COMMAND_PREFIX}{self.name}'

    async def execute(self, client: 'RoRClient', uid: int):
        await client.send_chat(
            f'The prefix for commands is: {COMMAND_PREFIX}'
        )


class PingCommand(BaseChatCommand):
    command: Literal[CommandType.PING]

    @property
    def description(self) -> str:
        return 'Ping the bot.'

    @property
    def usage(self) -> str:
        return f'{COMMAND_PREFIX}{self.name}'

    async def execute(self, client: 'RoRClient', uid: int):
        await client.send_chat('pong')


class HelpCommand(BaseChatCommand):
    command: Literal[CommandType.HELP]

    @property
    def description(self) -> str:
        return 'Get help for commands.'

    @property
    def usage(self) -> str:
        return f'{COMMAND_PREFIX}{self.name} [command]'

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

    async def execute(self, client: 'RoRClient', uid: int):
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

    @property
    def usage(self) -> str:
        return f'{COMMAND_PREFIX}{self.name}'

    async def execute(self, client: 'RoRClient', uid: int):
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
            message = 'Too many arguments'

        await client.send_chat(message)


class GetVersionCommand(BaseChatCommand):
    command: Literal[CommandType.VERSION]

    @property
    def description(self) -> str:
        return 'Get the version of the bot.'

    @property
    def usage(self) -> str:
        return f'{COMMAND_PREFIX}{self.name}'

    async def execute(self, client: 'RoRClient', uid: int):
        await client.send_chat(f'RoR Server Bot v{__version__}')


class CountdownCommand(BaseChatCommand):
    command: Literal[CommandType.COUNTDOWN]

    @property
    def description(self) -> str:
        return 'Start a countdown.'

    @property
    def usage(self) -> str:
        return f'{COMMAND_PREFIX}{self.name} <seconds>'

    async def execute(self, client: 'RoRClient', uid: int):
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
        async def on_frame_step(delta: float):
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


ChatCommandTypes = (
    PrefixCommand
    | PingCommand
    | HelpCommand
    | SetStatusCommand
    | GetVersionCommand
    | CountdownCommand
)

ChatCommand = Annotated[ChatCommandTypes, Field(discriminator='command')]


def chat_command_factory(message: str) -> ChatCommand:
    command, *args = message.split(' ')
    return RootModel[ChatCommand].model_validate({
        'command': command,
        'args': args
    }).root
