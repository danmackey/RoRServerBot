from typing import Self

from pydantic import BaseModel, Field, model_validator

from ror_server_bot import RORNET_VERSION


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

        @model_validator(mode='after')
        def set_enabled(self) -> Self:
            self.enabled = bool(self.messages)
            return self

        def get_next_announcement(self, time_sec: float) -> str:
            idx = int((time_sec / self.delay) % len(self.messages))
            return self.messages[idx]

    id: str
    enabled: bool
    server: ServerConfig
    user: UserConfig
    discord_channel_id: int
    announcements: Announcements | None
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
