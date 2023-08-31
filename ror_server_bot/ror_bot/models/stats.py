from datetime import datetime, timedelta

from pydantic import BaseModel, Field


class DistanceStats(BaseModel):
    meters_driven: float = 0
    meters_sailed: float = 0
    meters_walked: float = 0
    meters_flown: float = 0


class GlobalStats(DistanceStats):
    connected_at: datetime = Field(default_factory=datetime.now)
    usernames: set[str] = Field(default=set())
    user_count: int = 0
    connection_times: list[timedelta] = Field(default=[])

    def add_user(self, username: str):
        self.usernames.add(username)
        self.user_count += 1


class UserStats(DistanceStats):
    online_since: datetime = Field(default_factory=datetime.now)
