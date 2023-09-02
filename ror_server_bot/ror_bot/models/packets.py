import struct
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import Field, RootModel

from ror_server_bot.ror_bot.enums import MessageType

from .messages import Message


class BasePacket(Message):
    STRUCT_FORMAT: ClassVar[str] = 'IIII'

    type: MessageType
    source: int
    stream_id: int
    size: int
    payload: bytes = Field(default=b'')

    time: datetime = Field(default_factory=datetime.now)

    def pack(self) -> bytes:
        return struct.pack(
            self.STRUCT_FORMAT,
            self.type,
            self.source,
            self.stream_id,
            self.size
        ) + self.payload


class HelloPacket(BasePacket):
    type: Literal[MessageType.HELLO]


class WelcomePacket(BasePacket):
    type: Literal[MessageType.WELCOME]


class ServerFullPacket(BasePacket):
    type: Literal[MessageType.SERVER_FULL]


class WrongPasswordPacket(BasePacket):
    type: Literal[MessageType.WRONG_PASSWORD]


class WrongVersionPacket(BasePacket):
    type: Literal[MessageType.WRONG_VERSION]


class BannedPacket(BasePacket):
    type: Literal[MessageType.BANNED]


class ServerVersionPacket(BasePacket):
    type: Literal[MessageType.SERVER_VERSION]


class ServerSettingsPacket(BasePacket):
    type: Literal[MessageType.SERVER_SETTINGS]


class UserInfoPacket(BasePacket):
    type: Literal[MessageType.USER_INFO]


class MasterServerInfoPacket(BasePacket):
    type: Literal[MessageType.MASTER_SERVER_INFO]


class NetQualityPacket(BasePacket):
    type: Literal[MessageType.NET_QUALITY]


class GameCmdPacket(BasePacket):
    type: Literal[MessageType.GAME_CMD]


class UserJoinPacket(BasePacket):
    type: Literal[MessageType.USER_JOIN]


class UserLeavePacket(BasePacket):
    type: Literal[MessageType.USER_LEAVE]


class ChatPacket(BasePacket):
    type: Literal[MessageType.CHAT]


class PrivateChatPacket(BasePacket):
    type: Literal[MessageType.PRIVATE_CHAT]


class StreamRegisterPacket(BasePacket):
    type: Literal[MessageType.STREAM_REGISTER]


class StreamRegisterResultPacket(BasePacket):
    type: Literal[MessageType.STREAM_REGISTER_RESULT]


class StreamUnregisterPacket(BasePacket):
    type: Literal[MessageType.STREAM_UNREGISTER]


class StreamDataPacket(BasePacket):
    type: Literal[MessageType.STREAM_DATA]


class StreamDataDiscardablePacket(BasePacket):
    type: Literal[MessageType.STREAM_DATA_DISCARDABLE]


class UserInfoLegacyPacket(BasePacket):
    type: Literal[MessageType.USER_INFO_LEGACY]


Packet = Annotated[
    HelloPacket
    | WelcomePacket
    | ServerFullPacket
    | WrongPasswordPacket
    | WrongVersionPacket
    | BannedPacket
    | ServerVersionPacket
    | ServerSettingsPacket
    | UserInfoPacket
    | MasterServerInfoPacket
    | NetQualityPacket
    | GameCmdPacket
    | UserJoinPacket
    | UserLeavePacket
    | ChatPacket
    | PrivateChatPacket
    | StreamRegisterPacket
    | StreamRegisterResultPacket
    | StreamUnregisterPacket
    | StreamDataPacket
    | StreamDataDiscardablePacket
    | UserInfoLegacyPacket,
    Field(discriminator='type')
]


def packet_factory(
    message_type: int,
    source: int,
    stream_id: int,
    size: int
) -> Packet:
    return RootModel[Packet].model_validate({
        'type': message_type,
        'source': source,
        'stream_id': stream_id,
        'size': size
    }).root
