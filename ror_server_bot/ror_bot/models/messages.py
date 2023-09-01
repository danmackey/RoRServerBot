import logging
import struct
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, Field, field_validator

from ror_server_bot import pformat, RORNET_VERSION
from ror_server_bot.ror_bot.enums import (
    ActorType,
    AuthLevels,
    CharacterAnimation,
    CharacterCommand,
    Color,
    MessageType,
    PlayerColor,
    StreamType,
)

from .vector import Vector3, Vector4

logger = logging.getLogger(__name__)


def strip_nulls_after(*fields: str):
    """A validator that strips null characters from provided fields."""
    def __strip_null_character(v: str) -> str:
        return v.strip('\x00')
    return field_validator(
        *fields,
        mode='after',
        check_fields=False
    )(__strip_null_character)


class Message(BaseModel):
    """A sendable object."""

    STRUCT_FORMAT: ClassVar[str]
    """The struct format of the object."""

    @classmethod
    def calc_size(cls) -> int:
        """The expected size of the `cls.STRUCT_FORMAT` in bytes."""
        return struct.calcsize(cls.STRUCT_FORMAT)

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        """Creates an object from the bytes.

        :param data: The bytes to create the object from.
        :return: The object created from the bytes.
        """
        return cls.model_validate(
            dict(zip(
                cls.model_fields.keys(),
                struct.unpack(cls.STRUCT_FORMAT, data)
            ))
        )

    def __str__(self) -> str:
        return pformat(self)

    def __bytes__(self) -> bytes:
        return self.pack()

    def pack(self) -> bytes:
        """Packs the object into bytes.

        :return: The object packed into bytes.
        """
        values = [
            value.encode() if isinstance(value, str) else value
            for value in self.model_dump().values()
        ]
        return struct.pack(self.STRUCT_FORMAT, *values)


class Packet(Message):
    STRUCT_FORMAT: ClassVar[str] = 'IIII'
    """The struct format of the packet header.
    ```
    I: command
    I: source
    I: stream_id
    I: size
    ```
    """

    command: MessageType
    """The command of this packet."""
    source: int = 0
    """The source of this packet (0 = server)."""
    stream_id: int = Field(default=0, ge=0)
    """The stream id of this packet."""
    size: int = Field(default=0, ge=0)
    """The size of the data in this packet."""
    data: bytes = b''

    time: datetime = Field(default_factory=datetime.now)

    @classmethod
    def from_bytes(cls, header: bytes) -> 'Packet':
        """Creates a packet from the header data.

        :param header: The bytes of the header.
        :return: The packet created from the header data.
        """
        return super().from_bytes(header)

    def pack(self) -> bytes:
        """Packs the packet into bytes.

        :return: The packet packed into bytes.
        """
        return struct.pack(
            f'{self.STRUCT_FORMAT}{self.size}s',
            self.command,
            self.source,
            self.stream_id,
            self.size,
            self.data
        )


class ServerInfo(Message):
    STRUCT_FORMAT: ClassVar[str] = '20s128s128s?4096s'
    """The struct format of the server info data.
    ```
    20s: protocol_version
    128s: terrain_name
    128s: server_name
    ?: has_password
    4096s: info
    ```
    """

    protocol_version: str = Field(default=RORNET_VERSION, max_length=20)
    """The protocol version of the server."""
    terrain_name: str = Field(default='', max_length=128)
    """The name of the terrain."""
    server_name: str = Field(default='', max_length=128)
    """The name of the server."""
    has_password: bool = False
    """Whether the server has a password."""
    info: str = Field(default='', max_length=4096)
    """Info text (MOTD file contents)."""

    # validators
    _strip_null_character = strip_nulls_after(
        'protocol_version',
        'terrain_name',
        'server_name',
        'info',
    )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'ServerInfo':
        """Creates a server info from the bytes.

        :param data: The bytes to create the server info from.
        :return: The server info created from the bytes.
        """
        return super().from_bytes(data)

    def pack(self) -> bytes:
        """Packs the server info into bytes.

        :return: The server info packed into bytes.
        """
        return super().pack()


class UserInfo(Message):
    STRUCT_FORMAT: ClassVar[str] = 'Iiii40s40s40s10s10s25s40s10s128s'
    """The struct format of the user info data.
    ```
    I: uid
    i: auth_status
    i: slot_num
    i: color_idx
    40s: username
    40s: token
    40s: server_password
    10s: language
    10s: client_name
    25s: client_version
    40s: client_guid
    10s: session_type
    128s: session_options
    ```
    """

    unique_id: int = Field(default=0, ge=0)
    """The unique id of the user (set by the server)."""
    auth_status: AuthLevels
    """The authentication status of the user (set by the server)."""
    slot_num: int = -1
    """The slot number the user occupies in the server (set by the
    server)."""
    color_num: int = -1
    """The color number of the user (set by the server)."""
    username: str = Field(max_length=40)
    user_token: str = Field(max_length=40)
    server_password: str = Field(max_length=40)
    language: str = Field(max_length=10)
    """The language of the user (e.g. "de-DE" or "en-US")."""
    client_name: str
    """The name and version of the client."""
    client_version: str = Field(max_length=25)
    """The version of the client (e.g. "2022.12")."""
    client_guid: str = Field(max_length=40)
    session_type: str = Field(max_length=10)
    """The requested session type (e.g. "normal" "bot" "rcon")"""
    session_options: str = Field(max_length=128)
    """Reserved for future options."""

    @property
    def user_color(self) -> str:
        """Get the hex color of the username."""
        colors = list(PlayerColor)
        if -1 < self.color_num < len(colors):
            return colors[self.color_num].value
        return Color.WHITE.value

    # validators
    _strip_nulls = strip_nulls_after(
        'username',
        'user_token',
        'server_password',
        'language',
        'client_name',
        'client_version',
        'client_guid',
        'session_type',
        'session_options',
    )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'UserInfo':
        """Creates a user info from the bytes.

        :param data: The bytes to create the user info from.
        :return: The user info created from the bytes.
        """
        return super().from_bytes(data)

    def pack(self) -> bytes:
        """Packs the user info into bytes.

        :return: The user info packed into bytes.
        """
        return super().pack()


class BaseStreamRegister(BaseModel):
    STRUCT_FORMAT: ClassVar[str] = 'iiii128s'
    """The struct format of the stream register data.
    ```
    i: type
    i: status
    i: origin_source_id
    i: origin_stream_id
    128s: name
    ```
    """

    type: StreamType
    status: int
    origin_source_id: int
    origin_stream_id: int
    name: str = Field(max_length=128)
    """The name of the stream."""

    @field_validator('name', mode='before')
    def __strip_null_character(cls, v: str | bytes) -> str:
        if isinstance(v, bytes):
            return v.strip(b'\x00').decode()
        return v


class GenericStreamRegister(Message, BaseStreamRegister):
    STRUCT_FORMAT: ClassVar[str] = (BaseStreamRegister.STRUCT_FORMAT + '128s')
    """The struct format of the generic stream register data.
    ```
    i: type
    i: status
    i: origin_source_id
    i: origin_stream_id
    128s: name
    128s: reg_data
    ```
    """

    type: Literal[StreamType.CHAT] | Literal[StreamType.CHARACTER]
    name: Literal['chat', 'default']
    reg_data: str = Field(max_length=128)

    position: Vector3 = Vector3()
    """The position of the actor."""
    rotation: Vector4 = Vector4()
    """The rotation of the actor."""

    _strip_nulls = strip_nulls_after('reg_data')

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        """Creates a stream register from the bytes.

        :param data: The bytes to create the stream register from.
        :return: The stream register created from the bytes.
        """
        return super().from_bytes(data)

    def pack(self) -> bytes:
        """Packs the stream register into bytes.

        :return: The stream register packed into bytes.
        """
        return struct.pack(
            self.STRUCT_FORMAT,
            self.type,
            self.status,
            self.origin_source_id,
            self.origin_stream_id,
            self.name.encode(),
            self.reg_data.encode(),
        )


class ChatStreamRegister(GenericStreamRegister):
    type: Literal[StreamType.CHAT]
    name: Literal['chat']
    reg_data: str = Field(max_length=128)


class CharacterStreamRegister(GenericStreamRegister):
    type: Literal[StreamType.CHARACTER]
    name: Literal['default']
    reg_data: str = Field(max_length=128)


class ActorStreamRegister(Message, BaseStreamRegister):
    STRUCT_FORMAT: ClassVar[str] = (
        BaseStreamRegister.STRUCT_FORMAT + 'ii60s60s'
    )
    """The struct format of the actor stream register data.
    ```
    i: type
    i: status
    i: origin_source_id
    i: origin_stream_id
    128s: name
    i: buffer_size
    i: timestamp
    60s: skin
    60s: section_config
    ```
    """

    type: Literal[StreamType.ACTOR]
    buffer_size: int
    timestamp: int
    skin: str = Field(max_length=60)
    section_config: str = Field(max_length=60)

    actor_type: ActorType | None = None
    """The type of the actor (parsed from the actor filename)."""

    position: Vector3 = Vector3()
    """The position of the actor."""
    rotation: Vector4 = Vector4()
    """The rotation of the actor."""

    _strip_nulls = strip_nulls_after('skin', 'section_config')

    @classmethod
    def from_bytes(cls, data: bytes) -> 'ActorStreamRegister':
        """Creates a stream register from the bytes.

        :param data: The bytes to create the stream register from.
        :return: The stream register created from the bytes.
        """
        return cls.model_validate(
            dict(zip(
                cls.model_fields.keys(),
                struct.unpack(cls.STRUCT_FORMAT, data)
            ))
        )

    def pack(self) -> bytes:
        """Packs the stream register into bytes.

        :return: The stream register packed into bytes.
        """
        return struct.pack(
            self.STRUCT_FORMAT,
            self.type,
            self.status,
            self.origin_source_id,
            self.origin_stream_id,
            self.name.encode(),
            self.buffer_size,
            self.timestamp,
            self.skin.encode(),
            self.section_config.encode(),
        )


StreamRegister = Annotated[
    ChatStreamRegister | CharacterStreamRegister | ActorStreamRegister,
    Field(discriminator='type')
]


def stream_register_factory(data: bytes) -> StreamRegister:
    """Creates a stream register of the given type.

    :param data: The bytes to create the stream register from.
    :return: The stream register of the given type.
    """
    uint = 'I'
    uint_size = struct.calcsize(uint)

    stream_type = StreamType(struct.unpack(uint, data[:uint_size])[0])
    if stream_type is StreamType.CHAT:
        return ChatStreamRegister.from_bytes(data)
    elif stream_type is StreamType.CHARACTER:
        return CharacterStreamRegister.from_bytes(data)
    elif stream_type is StreamType.ACTOR:
        return ActorStreamRegister.from_bytes(data)
    raise ValueError(f'Invalid stream type: {type!r}')


class CharacterPositionStreamData(Message):
    STRUCT_FORMAT: ClassVar[str] = 'i3fff10s'
    """The struct format of the character position stream data.
    ```
    i: command
    3f: position
    f: rotation
    f: animation_time
    10s: animation_mode
    ```
    """

    command: Literal[CharacterCommand.POSITION]
    position: Vector3
    rotation: float
    """The rotation in radians."""
    animation_time: float
    animation_mode: CharacterAnimation

    @field_validator('animation_mode', mode='before')
    def __strip_null_character(cls, v: Any) -> Any:
        if isinstance(v, bytes):
            return v.strip(b'\x00').decode()
        return v

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CharacterPositionStreamData':
        """Creates a character position from the bytes.

        :param data: The bytes to create the character position from.
        :return: The character position created from the bytes.
        """
        command, x, y, z, *values = struct.unpack(
            cls.STRUCT_FORMAT,
            data
        )
        return cls.model_validate(
            dict(zip(
                cls.model_fields.keys(),
                (command, Vector3(x=x, y=y, z=z), *values)
            ))
        )

    def pack(self) -> bytes:
        """Packs the character position into bytes.

        :return: The character position packed into bytes.
        """
        return struct.pack(
            self.STRUCT_FORMAT,
            self.command,
            *self.position,
            self.rotation,
            self.animation_time,
            self.animation_mode.value.encode(),
        )


class CharacterAttachStreamData(Message):
    STRUCT_FORMAT: ClassVar[str] = 'iiii'
    """The struct format of the character attach stream data.
    ```
    i: command
    i: source_id
    i: stream_id
    i: position
    ```
    """

    command: Literal[CharacterCommand.ATTACH]
    source_id: int
    stream_id: int
    position: int

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CharacterAttachStreamData':
        """Creates a character attach from the bytes.

        :param data: The bytes to create the character attach from.
        :return: The character attach created from the bytes.
        """
        return cls.model_validate(
            dict(zip(
                cls.model_fields.keys(),
                struct.unpack(cls.STRUCT_FORMAT, data)
            ))
        )

    def pack(self) -> bytes:
        """Packs the character attach into bytes.

        :return: The character attach packed into bytes.
        """
        return struct.pack(
            self.STRUCT_FORMAT,
            self.source_id,
            self.stream_id,
            self.position,
        )


class CharacterDetachStreamData(Message):
    STRUCT_FORMAT: ClassVar[str] = 'i'
    """The struct format of the character detach stream data.
    ```
    i: command
    ```
    """

    command: Literal[CharacterCommand.DETACH]

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CharacterDetachStreamData':
        """Creates a character detach from the bytes.

        :param data: The bytes to create the character detach from.
        :return: The character detach created from the bytes.
        """
        return super().from_bytes(data)

    def pack(self) -> bytes:
        """Packs the character detach into bytes.

        :return: The character detach packed into bytes.
        """
        return super().pack()


class VehicleStreamData(Message):
    STRUCT_FORMAT: ClassVar[str] = 'IfffIfffI3f'
    """The struct format of the vehicle state data.
    ```
    I: time
    f: engine_speed
    f: engine_force
    f: engine_clutch
    I: engine_gear
    f: steering
    f: brake
    f: wheel_speed
    I: flag_mask
    3f: position
    Xs: node_data
    ```
    """

    time: int
    engine_rpm: float
    engine_accerlation: float
    engine_clutch: float
    engine_gear: int
    steering: float
    brake: float
    wheel_speed: float
    flag_mask: int
    position: Vector3
    node_data: bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'VehicleStreamData':
        """Creates a vehicle state from the bytes.

        :param data: The bytes to create the vehicle state from.
        :return: The vehicle state created from the bytes.
        """
        *values, x, y, z = struct.unpack(
            cls.STRUCT_FORMAT,
            data[:cls.calc_size()]
        )

        node_data, *_ = struct.unpack(
            f'{len(data) - cls.calc_size()}s',
            data[cls.calc_size():]
        )

        return cls.model_validate(
            dict(zip(
                cls.model_fields.keys(),
                (*values, Vector3(x=x, y=y, z=z), node_data)
            ))
        )

    def pack(self) -> bytes:
        """Packs the vehicle state into bytes.

        :return: The vehicle state packed into bytes.
        """
        return struct.pack(
            f'{self.STRUCT_FORMAT}{len(self.node_data)}s',
            self.time,
            self.engine_rpm,
            self.engine_accerlation,
            self.engine_clutch,
            self.engine_gear,
            self.steering,
            self.brake,
            self.wheel_speed,
            self.flag_mask,
            *self.position,
            self.node_data,
        )


StreamData = (
    CharacterAttachStreamData
    | CharacterPositionStreamData
    | CharacterDetachStreamData
    | VehicleStreamData
)


def stream_data_factory(type: StreamType, data: bytes) -> StreamData:
    """Creates a stream data of the given type.

    :param type: The type of the stream data.
    :param data: The bytes to create the stream data from.
    :return: The stream data of the given type.
    """
    stream_data: StreamData | None = None
    if type is StreamType.CHARACTER:
        command = CharacterCommand(struct.unpack('i', data[:4])[0])
        if command is CharacterCommand.ATTACH:
            stream_data = CharacterAttachStreamData.from_bytes(data)
        elif command is CharacterCommand.POSITION:
            stream_data = CharacterPositionStreamData.from_bytes(data)
        elif command is CharacterCommand.DETACH:
            stream_data = CharacterDetachStreamData.from_bytes(data)
        else:
            raise ValueError(f'Invalid character command: {command!r}')
    elif type is StreamType.ACTOR:
        stream_data = VehicleStreamData.from_bytes(data)
    else:
        raise ValueError(f'Invalid stream type: {type!r}')
    return stream_data
