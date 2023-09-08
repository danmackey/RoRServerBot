from pydantic import BaseModel, Field

from ror_server_bot import TRUCK_TO_NAME_FILE

from .enums import ActorType, AuthStatus, Color, StreamType
from .models import StreamRegister, TruckFile, UserInfo, UserStats, Vector3
from .models.messages import ChatStreamRegister


class StreamNotFoundError(Exception):
    """Raised when a stream is not found."""


class CurrentStream(BaseModel):
    """The current stream of the user. This could be a character or an
    actor. The unique_id is the user associated with the stream. If the
    unique_id does not match the user's unique_id, then the user is in
    another user's vehicle."""

    unique_id: int = -1
    stream_id: int = -1


class User(BaseModel):
    info: UserInfo

    character_stream_id: int = -1
    chat_stream_id: int = -1
    stats: UserStats = UserStats()
    current_stream: CurrentStream = CurrentStream()
    streams: dict[int, StreamRegister] = Field(default={})
    """Streams registered to the user."""

    @property
    def unique_id(self) -> int:
        """Get the unique id of the user."""
        return self.info.unique_id

    @property
    def auth_status(self) -> AuthStatus:
        """Get the authentication status of the user."""
        return self.info.auth_status

    @property
    def username(self) -> str:
        """Get the username of the user."""
        return self.info.username

    @property
    def username_colored(self) -> str:
        """Get the username formatted with the user's color."""
        return (
            f'{self.info.user_color}{self.info.username}{Color.WHITE.value}'
        )

    @property
    def language(self) -> str:
        """Get the language of the user."""
        return self.info.language

    @property
    def client_name(self) -> str:
        """Get the client name of the user."""
        return self.info.client_name

    @property
    def client_version(self) -> str:
        """Get the client version of the user."""
        return self.info.client_version

    @property
    def client_guid(self) -> str:
        """Get the client guid of the user."""
        return self.info.client_guid

    @property
    def total_streams(self) -> int:
        """Get the total number of streams the user has."""
        return len(self.streams)

    @property
    def stream_ids(self) -> list[int]:
        """Get the ids of the streams the user has."""
        return list(self.streams.keys())

    def add_stream(self, stream: StreamRegister):
        """Adds a stream to the user.

        :param stream: The stream to add.
        """
        if stream.type is StreamType.ACTOR:
            filename = TruckFile.from_filename(
                TRUCK_TO_NAME_FILE,
                stream.name
            )
            stream.actor_type = filename.type
        elif stream.type is StreamType.CHARACTER:
            self.character_stream_id = stream.origin_stream_id
        elif stream.type is StreamType.CHAT:
            self.chat_stream_id = stream.origin_stream_id
        self.streams[stream.origin_stream_id] = stream

    def delete_stream(self, stream_id: int):
        """Deletes a stream from the user.

        :param stream_id: The stream id of the stream to delete.
        """
        stream = self.streams.pop(stream_id)

        if stream.origin_stream_id == self.character_stream_id:
            self.character_stream_id = -1
        elif stream.origin_stream_id == self.chat_stream_id:
            self.chat_stream_id = -1

    def get_stream(self, stream_id: int) -> StreamRegister:
        """Gets a stream from the user.

        :param stream_id: The stream id of the stream to get.
        :return: The stream.
        """
        try:
            return self.streams[stream_id]
        except KeyError as e:
            raise StreamNotFoundError(stream_id) from e

    def get_current_stream(self) -> StreamRegister:
        """Gets the current stream of the user.

        :return: The current stream of the user.
        """
        return self.streams[self.current_stream.stream_id]

    def set_current_stream(self, unique_id: int, stream_id: int):
        """Sets the current stream of the user.

        :param unique_id: The id of the user this stream belongs to.
        :param stream_id: The id of the stream.
        """
        self.current_stream.unique_id = unique_id
        self.current_stream.stream_id = stream_id

    def set_position(self, sid: int, position: Vector3):
        """Sets the position of the user.

        :param sid: The sid of the stream.
        :param position: The position of the user.
        """
        stream = self.streams[sid]

        if isinstance(stream, ChatStreamRegister):
            return

        distance_meters = position.distance(stream.position)

        if distance_meters < 1:
            return

        stream.position = position

        if stream.type is StreamType.CHARACTER:
            self.stats.meters_walked += distance_meters
        elif stream.type is StreamType.ACTOR:
            if stream.actor_type in (
                ActorType.CAR,
                ActorType.TRUCK,
                ActorType.TRAIN
            ):
                self.stats.meters_driven += distance_meters
            elif stream.actor_type is ActorType.BOAT:
                self.stats.meters_sailed += distance_meters
            elif stream.actor_type is ActorType.AIRPLANE:
                self.stats.meters_flown += distance_meters

    def get_position(self, sid: int | None) -> Vector3 | None:
        """Gets the position of the user.

        :param sid: The sid of the stream.
        :return: The position of the user.
        """
        if sid is None:
            stream = self.get_current_stream()
        else:
            stream = self.streams[sid]

        if isinstance(stream, ChatStreamRegister):
            return None

        return stream.position

    def set_rotation(self, sid: int, rotation: float):
        """Sets the rotation of the user.

        :param sid: The sid of the stream.
        :param rotation: The rotation of the user in radians.
        """
        self.streams[sid].rotation = rotation

    def get_rotation(self, sid: int | None) -> float | None:
        """Gets the rotation of the user.

        :param sid: The sid of the stream.
        :return: The rotation of the user.
        """
        if sid is None:
            stream = self.get_current_stream()
        else:
            stream = self.streams[sid]

        if isinstance(stream, ChatStreamRegister):
            return None

        return stream.rotation
