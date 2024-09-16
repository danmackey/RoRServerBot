from enum import auto, Enum, IntEnum, IntFlag, StrEnum
from typing import Self


class MessageType(IntEnum):
    HELLO = 1025
    """Client sends its version as the first message."""

    # Hello Responses
    SERVER_FULL = auto()
    """Server is full."""
    WRONG_PASSWORD = auto()
    """Wrong password."""
    WRONG_VERSION = auto()
    """Wrong version."""
    BANNED = auto()
    """Client not allowed to join (banned)."""
    WELCOME = auto()
    """Client accepted."""

    # Technical
    SERVER_VERSION = auto()
    """Server sends its version."""
    SERVER_SETTINGS = auto()
    """Server sends client the terrain name."""
    USER_INFO = auto()
    """User data that is sent from the server to clients."""
    MASTER_SERVER_INFO = auto()
    """Server sends master server info."""
    NET_QUALITY = auto()
    """Server sends network quality information."""

    # Gameplay
    GAME_CMD = auto()
    """Script message. Can be sent in both directions."""
    USER_JOIN = auto()
    """New user joined."""
    USER_LEAVE = auto()
    """User leaves."""
    CHAT = auto()
    """Chat line in UTF8 encoding."""
    PRIVATE_CHAT = auto()
    """Private chat line in UTF8 encoding."""

    # Stream Functions
    STREAM_REGISTER = auto()
    """Create new stream."""
    STREAM_REGISTER_RESULT = auto()
    """Result of a stream creation."""
    STREAM_UNREGISTER = auto()
    """Remove stream."""
    STREAM_DATA = auto()
    """Stream data."""
    STREAM_DATA_DISCARDABLE = auto()
    """Stream data that is allowed to be discarded."""

    # Legacy
    USER_INFO_LEGACY = 1003
    """Wrong version."""


class AuthStatus(IntFlag):
    NONE = 0
    """no authentication"""
    ADMIN = auto()
    """admin on the server"""
    RANKED = auto()
    """ranked status"""
    MOD = auto()
    """moderator status"""
    BOT = auto()
    """bot status"""
    BANNED = auto()
    """banned"""

    @classmethod
    def get_auth_str(cls, auth: Self) -> str:
        auth_str = ''
        if auth is AuthStatus.NONE:
            auth_str = ''
        if auth is AuthStatus.ADMIN:
            auth_str = 'A'
        if auth is AuthStatus.MOD:
            auth_str = 'M'
        if auth is AuthStatus.RANKED:
            auth_str = 'R'
        if auth is AuthStatus.BOT:
            auth_str = 'B'
        if auth is AuthStatus.BANNED:
            auth_str = 'X'
        return auth_str

    @property
    def auth_str(self) -> str:
        return self.get_auth_str(self)


class StreamType(IntEnum):
    ACTOR = 0
    CHARACTER = 1
    AI = 2
    CHAT = 3


class ActorStreamStatus(IntEnum):
    MISMATCH = -2
    INVALID = -1
    UNKNOWN = 0
    SUCCESS = 1


class ActorType(Enum):
    TRUCK = 'truck'
    CAR = 'car'
    LOAD = 'load'
    AIRPLANE = 'airplane'
    BOAT = 'boat'
    TRAILER = 'trailer'
    TRAIN = 'train'
    FIXED = 'fixed'


class NetMask(IntFlag):
    HORN = 1
    """Horn is in use."""
    POLICE_AUDIO = auto()
    """Police siren is on."""
    PARTICLE = auto()
    """Custom particles are on."""
    PARKING_BRAKE = auto()
    """Parking brake is on."""
    TRACTION_CONTROL_ACTIVE = auto()
    """Traction control is on."""
    ANTI_LOCK_BRAKES_ACTIVE = auto()
    """Anti-lock brakes are on."""
    ENGINE_CONTACT = auto()
    """Ignition is on."""
    ENGINE_RUN = auto()
    """Engine is running."""
    ENGINE_MODE_AUTOMATIC = auto()
    """Using automatic transmission."""
    ENGINE_MODE_SEMIAUTO = auto()
    """Using semi-automatic transmission."""
    ENGINE_MODE_MANUAL = auto()
    """Using manual transmission."""
    ENGINE_MODE_MANUAL_STICK = auto()
    """Using manual transmission with stick."""
    ENGINE_MODE_MANUAL_RANGES = auto()
    """Using manual transmission with ranges."""


class LightMask(IntFlag):
    CUSTOM_1 = 1
    CUSTOM_2 = auto()
    CUSTOM_3 = auto()
    CUSTOM_4 = auto()
    CUSTOM_5 = auto()
    CUSTOM_6 = auto()
    CUSTOM_7 = auto()
    CUSTOM_8 = auto()
    CUSTOM_9 = auto()
    CUSTOM_10 = auto()
    HEADLIGHT = auto()
    HIGH_BEAMS = auto()
    FOG_LIGHTS = auto()
    SIDE_LIGHTS = auto()
    BRAKES = auto()
    REVERSE = auto()
    BEACONS = auto()
    BLINK_LEFT = auto()
    BLINK_RIGHT = auto()
    BLINK_WARN = auto()


class CharacterCommand(IntEnum):
    INVALID = 0
    POSITION = auto()
    ATTACH = auto()
    DETACH = auto()


class CharacterAnimation(Enum):
    IDLE_SWAY = 'Idle_sway'
    SPOT_SWIM = 'Spot_swim'
    WALK = 'Walk'
    RUN = 'Run'
    SWIM_LOOP = 'Swim_loop'
    TURN = 'Turn'
    DRIVING = 'Driving'
    SIDE_STEP = 'Side_step'


class PlayerColor(Enum):
    """The color assigned to each player."""

    # names from https://www.color-name.com/
    #! DO NOT REORDER
    GREEN = "#00CC00"
    BLUE = "#0066B3"
    ORANGE = "#FF8000"
    YELLOW = "#FFCC00"
    LIME = "#CCFF00"
    RED = "#FF0000"
    GRAY = "#808080"
    DARK_GREEN = "#008F00"
    WINDSOR_TAN = "#B35A00"
    LIGHT_GOLD = "#B38F00"
    APPLE_GREEN = "#8FB300"
    UE_RED = "#B30000"
    DARK_GRAY = "#BEBEBE"
    LIGHT_GREEN = "#80FF80"
    LIGHT_SKY_BLUE = "#80C9FF"
    MAC_AND_CHEESE = "#FFC080"
    YELLOW_CRAYOLA = "#FFE680"
    LAVENDER_FLORAL = "#AA80FF"
    ELECTRIC_PINK = "#EE00CC"
    CONGO_PINK = "#FF8080"
    BRONZE_YELLOW = "#666600"
    BRILLIANT_LAVENDER = "#FFBFFF"
    SEA_GREEN = "#00FFCC"
    WILD_ORCHID = "#CC6699"
    DARK_YELLOW = "#999900"


class Color(StrEnum):
    BLACK = "#000000"
    GREY = "#999999"
    RED = "#FF0000"
    YELLOW = "#FFFF00"
    WHITE = "#FFFFFF"
    CYAN = "#00FFFF"
    BLUE = "#0000FF"
    GREEN = "#00FF00"
    MAGENTA = "#FF00FF"
    COMMAND = "#941E8D"
    WHISPER = "#967417"
    SCRIPT = "#32436F"


class RoRClientEvents(StrEnum):
    FRAME_STEP = 'frame_step'
    NET_QUALITY = 'net_quality'
    CHAT = 'chat'
    PRIVATE_CHAT = 'private_chat'
    USER_JOIN = 'user_join'
    USER_INFO = 'user_info'
    USER_LEAVE = 'user_leave'
    GAME_CMD = 'game_cmd'
    STREAM_REGISTER = 'stream_register'
    STREAM_REGISTER_RESULT = 'stream_register_result'
    STREAM_DATA = 'stream_data'
    STREAM_UNREGISTER = 'stream_unregister'
