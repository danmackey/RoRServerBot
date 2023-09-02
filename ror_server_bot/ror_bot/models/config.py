from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_extra_types.color import Color

from ror_server_bot import RORNET_VERSION


def color_to_hex(color: str | Color) -> str:
    """Convert a color name to a hex string.

    :param color: The color to convert.
    :return: The hex string.
    """
    return '#' + ''.join([
        format(v, '02x').upper() for v in Color(color).as_rgb_tuple()
    ])


class RoRClientConfig(BaseModel):
    class ServerConfig(BaseModel):
        host: str = ''
        port: int = Field(12000, ge=12000, le=12999)
        password: str = ''

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
        def __check_color(cls, v: Any) -> str:
            # we do this because Color does not
            # always output 6 digit hex strings
            if isinstance(v, (str, Color)):
                return color_to_hex(v)
            return v

        @model_validator(mode='after')
        def __set_disabled(self) -> Self:
            if not self.messages:
                self.enabled = False
            return self

        def get_next_announcement(self, time_sec: float) -> str:
            idx = int((time_sec / self.delay) % len(self.messages))
            return self.messages[idx]

    id: str
    enabled: bool
    server: ServerConfig
    user: UserConfig
    discord_channel_id: int
    announcements: Announcements = Announcements()
    reconnection_interval: int = 5
    """Interval between reconnection attempts in seconds."""
    reconnection_tries: int = 3
    """Number of reconnection attempts before giving up."""


class Config(BaseModel):
    """Represents a configuration used to build RoR server bots"""

    client_name: str = '2022.04'
    version_num: str = RORNET_VERSION
    discord_bot_token: str
    ror_clients: list[RoRClientConfig]

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
