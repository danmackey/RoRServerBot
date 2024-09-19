from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_extra_types.color import Color

from ror_server_bot.logging import ConsoleStyle, FileType, LogLevel


def color_to_hex(color: str | Color) -> str:
    """Convert a color name to a hex string.

    :param color: The color to convert.
    :return: The hex string.
    """
    return '#' + ''.join([
        format(v, '02x').upper()
        for v in Color(color).as_rgb_tuple()
    ])


class ServerConfig(BaseModel):
    host: str = ''
    port: int = Field(12000, ge=12000, le=12999)
    password: str = ''

    @field_validator('host', mode='after')
    def __check_ipv4(cls, v: str) -> str:
        if v == 'localhost':
            return v

        try:
            IPv4Address(v)
        except ValueError as e:
            raise ValueError(f'Expected {v} to be an IPv4 address') from e

        return v

    @field_validator('password', mode='before')
    def __set_empty_password(cls, v: Any) -> Any:
        if v is None:
            return ''
        return v


class UserConfig(BaseModel):
    name: str = 'RoR Server Bot'
    token: str = ''
    language: str = 'en_US'


class Announcements(BaseModel):
    delay: int = 300
    """Delay between announcements in seconds."""

    enabled: bool = False

    messages: list[str] = Field(default_factory=list)

    color: str = Field(default='yellow', validate_default=True)
    """The color to use for the announcements. Can be a hex string
    or a color name. If a color name is used, it will be converted
    to a hex string."""

    @field_validator('color', mode='before')
    def __check_color(cls, v: Any) -> Any:
        # we do this because Color does not
        # always output 6 digit hex strings
        if isinstance(v, str | Color):
            return color_to_hex(v)
        return v

    @model_validator(mode='after')
    def __set_disabled(self) -> Self:
        if not self.messages:
            self.enabled = False
        return self

    def get_next_announcement(self, time_sec: float) -> str:
        """Get the next announcement based on the current time.

        :param time_sec: The current time in seconds.
        :return: The next announcement.
        """
        idx = int((time_sec / self.delay) % len(self.messages))
        return self.messages[idx]


class RoRClientConfig(BaseModel):
    id: str

    enabled: bool
    """Whether the client is enabled."""

    server: ServerConfig
    """The server to connect to."""

    user: UserConfig
    """The user to connect as."""

    discord_channel_id: int
    """The discord channel to use to communicate to and from the server."""

    announcements: Announcements = Announcements()
    """The announcements to make on the server."""

    reconnection_interval: int = 5
    """Interval between reconnection attempts in seconds."""
    reconnection_tries: int = 3
    """Number of reconnection attempts before giving up."""


class Config(BaseModel):
    """Represents a configuration used to build RoR server bots"""

    truck_blacklist: Path = Field(default=Path.cwd() / 'truck_blacklist.json')
    """Path to a json file containing a list of truck names to blacklist."""

    recordings_folder: Path = Field(default=Path.cwd() / 'recordings')
    """Path to the folder where recordings are stored."""

    log_folder: Path = Field(default=Path.cwd() / 'logs')
    """Path to the folder where logs are stored."""

    console_log_level: LogLevel = 'INFO'
    """The log level to use when logging to the console.

    Options:
    - DEBUG
    - INFO
    - WARNING
    - ERROR
    - CRITICAL"""

    console_style: ConsoleStyle = 'rich'
    """The style to use when logging to the console.

    rich: Use rich formatting
    basic: Use basic formatting"""

    log_file_type: FileType = 'log'
    """The type of file to write logs to.

    log: Write logs to a plain text file
    gzip: Write logs to a gzip compressed file"""

    discord_client_token: str = ''
    """The token to use for the discord client."""

    ror_clients: list[RoRClientConfig] = Field(min_length=1)

    @field_validator('truck_blacklist', mode='after')
    def __check_truck_blacklist(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f'File not found: {v}')
        if not v.is_file():
            raise ValueError(f'Path must be a file: {v}')
        if not v.suffix == '.json':
            raise ValueError(f'File must be a json file: {v}')
        return v

    @field_validator('recordings_folder', 'log_folder', mode='after')
    def __make_folder(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v

    def get_channel_id_by_client_id(self, id: str) -> int | None:
        for client in self.ror_clients:
            if client.id == id:
                return client.discord_channel_id
        return None

    def get_ror_client_by_id(self, id: str) -> RoRClientConfig | None:
        for client in self.ror_clients:
            if client.id == id:
                return client
        return None
