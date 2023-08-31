import logging
from datetime import datetime
from itertools import chain

from ror_server_bot import pformat

from .enums import AuthLevels
from .models import GlobalStats, StreamRegister, UserInfo, Vector3, Vector4
from .user import User

logger = logging.getLogger(__name__)


class UserNotFoundError(Exception):
    """Raised when a user is not found."""


class StreamManager:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.global_stats = GlobalStats()

    @property
    def user_count(self) -> int:
        """Gets the number of users."""
        return len(self.users) - 1  # subtract 1 for the server client

    @property
    def user_ids(self) -> list[int]:
        """Gets the ids of the users."""
        return list(self.users.keys())

    @property
    def stream_ids(self) -> list[int]:
        """Gets the ids of the streams."""
        return list(chain.from_iterable(
            user.stream_ids for user in self.users.values()
        ))

    def get_uid_by_username(self, username: str) -> int | None:
        """Gets the uid of the user by their username.

        :param username: The username of the user.
        :return: The uid of the user.
        """
        for uid, user in self.users.items():
            if user.username == username:
                return uid
        return None

    def get_user(self, uid: int) -> User:
        """Gets a user from the stream manager.

        :param uid: The uid of the user.
        :return: The user.
        """
        try:
            return self.users[uid]
        except KeyError as e:
            raise UserNotFoundError(uid, pformat(self.users)) from e

    def add_user(self, user_info: UserInfo):
        """Adds a client to the stream manager.

        :param user_info: The user info of the client to add.
        """
        # update global stats if this is a new user
        if user_info.unique_id not in self.users:
            self.global_stats.add_user(user_info.username)

        # set the user to a new user if not already set
        self.users.setdefault(user_info.unique_id, User(info=user_info))

        # update the user info for the user
        self.users[user_info.unique_id].info = user_info

        logger.info(
            'Added user %r uid=%d',
            user_info.username,
            user_info.unique_id
        )

    def delete_user(self, uid: int):
        """Deletes a client from the stream manager.

        :param uid: The uid of the client to delete.
        """
        user = self.users.pop(uid)

        self.global_stats.meters_driven += user.stats.meters_driven
        self.global_stats.meters_sailed += user.stats.meters_sailed
        self.global_stats.meters_walked += user.stats.meters_walked
        self.global_stats.meters_flown += user.stats.meters_flown

        self.global_stats.connection_times.append(
            datetime.now() - user.stats.online_since
        )

        logger.debug('Deleted user %r uid=%d', user.username, uid)

    def add_stream(self, stream: StreamRegister):
        """Adds a stream to the stream manager.

        :param stream: The stream to add.
        """
        self.get_user(stream.origin_source_id).add_stream(stream)

    def delete_stream(self, uid: int, sid: int):
        """Deletes a stream from the stream manager.

        :param uid: The uid of the stream to delete.
        :param sid: The sid of the stream to delete.
        """
        self.get_user(uid).delete_stream(sid)

    def get_stream(self, uid: int, sid: int) -> StreamRegister:
        """Gets a stream from the stream manager.

        :param uid: The uid of the stream.
        :param sid: The sid of the stream.
        :return: The stream.
        """
        return self.get_user(uid).get_stream(sid)

    def get_current_stream(self, uid: int) -> StreamRegister:
        """Gets the current stream of the user.

        :param uid: The uid of the user.
        :return: The current stream of the user.
        """
        return self.get_user(uid).get_current_stream()

    def set_current_stream(self, uid: int, actor_uid: int, sid: int):
        """Sets the current stream of the user.

        :param uid: The uid of the user.
        :param actor_uid: The uid of the actor.
        :param sid: The sid of the stream.
        """
        self.get_user(uid).set_current_stream(actor_uid, sid)

    def set_character_sid(self, uid: int, sid: int):
        """Sets the character stream id of the user.

        :param uid: The uid of the user.
        :param sid: The sid of the character stream.
        """
        self.get_user(uid).character_stream_id = sid

    def get_character_sid(self, uid: int) -> int:
        """Gets the character stream id of the user.

        :param uid: The uid of the user.
        :return: The character stream id of the user.
        """
        return self.get_user(uid).character_stream_id

    def set_chat_sid(self, uid: int, sid: int):
        """Sets the chat stream id of the user.

        :param uid: The uid of the user.
        :param sid: The sid of the chat stream.
        """
        self.get_user(uid).chat_stream_id = sid

    def get_chat_sid(self, uid: int) -> int:
        """Gets the chat stream id of the user.

        :param uid: The uid of the user.
        :return: The chat stream id of the user.
        """
        return self.get_user(uid).chat_stream_id

    def set_position(self, uid: int, sid: int, position: Vector3):
        """Sets the position of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream.
        :param position: The position to set.
        """
        self.get_user(uid).set_position(sid, position)

    def get_position(self, uid: int, sid: int = -1) -> Vector3:
        """Gets the position of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream, defaults to -1
        :return: The position of the stream.
        """
        if sid == -1:
            return self.get_current_stream(uid).position
        else:
            return self.get_user(uid).get_stream(sid).position

    def set_rotation(self, uid: int, sid: int, rotation: Vector4):
        """Sets the rotation of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream.
        :param rotation: The rotation to set.
        """
        self.get_user(uid).set_rotation(sid, rotation)

    def get_rotation(self, uid: int, sid: int = -1) -> Vector4:
        """Gets the rotation of the stream.

        :param uid: The uid of the user.
        :param sid: The sid of the stream, defaults to -1
        :return: The rotation of the stream.
        """
        if sid == -1:
            return self.get_current_stream(uid).rotation
        else:
            return self.get_user(uid).get_stream(sid).rotation

    def get_online_since(self, uid: int) -> datetime:
        """Gets the online since of the user.

        :param uid: The uid of the user.
        :return: The online since of the user.
        """
        return self.get_user(uid).stats.online_since

    def total_streams(self, uid: int) -> int:
        """Gets the total number of streams.

        :param uid: The uid of the user.
        :return: The total number of streams.
        """
        return self.get_user(uid).total_streams

    def get_username(self, uid: int) -> str:
        """Gets the username of the user.

        :param uid: The uid of the user.
        :return: The username of the user.
        """
        return self.get_user(uid).username

    def get_username_colored(self, uid: int) -> str:
        """Gets the username of the user with color.

        :param uid: The uid of the user.
        :return: The username of the user with color.
        """
        return self.get_user(uid).username_colored

    def get_language(self, uid: int) -> str:
        """Gets the language of the user.

        :param uid: The uid of the user.
        :return: The language of the user.
        """
        return self.get_user(uid).language

    def get_client_name(self, uid: int) -> str:
        """Gets the client name of the user.

        :param uid: The uid of the user.
        :return: The client name of the user.
        """
        return self.get_user(uid).client_name

    def get_client_version(self, uid: int) -> str:
        """Gets the client version of the user.

        :param uid: The uid of the user.
        :return: The client version of the user.
        """
        return self.get_user(uid).client_version

    def get_client_guid(self, uid: int) -> str:
        """Gets the client guid of the user.

        :param uid: The uid of the user.
        :return: The client guid of the user.
        """
        return self.get_user(uid).client_guid

    def get_auth_status(self, uid: int) -> AuthLevels:
        """Gets the authentication status of the user.

        :param uid: The uid of the user.
        :return: The authentication status of the user.
        """
        return self.get_user(uid).auth_status
