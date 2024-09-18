import contextlib
import json
import logging
from datetime import datetime
from enum import auto, Enum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ror_server_bot import PROJECT_DIRECTORY, RORNET_VERSION
from ror_server_bot.logging import pformat

from .enums import RoRClientEvents
from .models import (
    ActorStreamData,
    ActorStreamRegister,
    StreamData,
    StreamRegister,
    UserInfo,
)
from .ror_connection import RoRConnection

__version__ = '0.1.0'

logger = logging.getLogger(__name__)

RECORDINGS_PATH = PROJECT_DIRECTORY / 'recordings'
RECORDINGS_PATH.mkdir(exist_ok=True)


class StreamRecordingError(Exception):
    """Raised when there is an error with the stream recording."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class RecordingStatus(Enum):
    """The status of a recording."""

    NONE = auto()
    """No recording is happening."""
    RECORDING = auto()
    PAUSED = auto()
    STOPPED = auto()


class PlaybackStatus(Enum):
    NONE = auto()
    """No playback is happening."""
    STOPPED = auto()
    PAUSED = auto()
    PLAYING = auto()


class Recording(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    server: RoRConnection
    user: UserInfo
    stream: ActorStreamRegister
    frames: list[bytes] = Field(default_factory=list)
    filename: Path = Field(default_factory=Path)

    _playback: PlaybackStatus = PlaybackStatus.NONE
    _recording: RecordingStatus = RecordingStatus.NONE
    _time_delta: float = 0.0
    _last_frame_idx: int = 0
    _curr_frame_idx: int = 0
    _stream_id: int | None = None

    @model_validator(mode='after')
    def __default_filename(self) -> Self:
        if self.filename == Path():
            time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            uid = self.user.unique_id
            sid = self.stream.origin_stream_id
            self.filename = Path(f'{uid:04d}-{sid:02d}-{time}.rec')
        return self

    @property
    def playback(self) -> PlaybackStatus:
        return self._playback

    @property
    def is_recording(self) -> bool:
        return self._recording is RecordingStatus.RECORDING

    @property
    def full_path(self) -> Path:
        return RECORDINGS_PATH / self.filename

    @property
    def stream_id(self) -> int | None:
        """Gets the stream id of the recording when it is being played."""
        return self._stream_id

    @property
    def curr_frame(self) -> ActorStreamData:
        """Gets the current frame of the recording."""
        return ActorStreamData.from_bytes(self.frames[self._curr_frame_idx])

    @property
    def last_frame(self) -> ActorStreamData:
        """Gets the last frame of the recording."""
        return ActorStreamData.from_bytes(self.frames[self._last_frame_idx])

    @classmethod
    def load(cls, filename: Path, server: RoRConnection) -> Self:
        """Load a recording from a file.

        :param filename: The filename of the recording to load.
        :return: The loaded recording.
        """
        logger.info('[REC] Loading recording %s', filename)

        recording_path = RECORDINGS_PATH / filename
        if not recording_path.exists():
            raise StreamRecordingError('ERROR-NO_RECORDING_FOUND')

        with open(recording_path, 'rb') as file:
            contents = file.read().decode()

        data = json.loads(contents)

        if 'version' not in data:
            raise StreamRecordingError('ERROR-NO_VERSION_FOUND')
        elif data['version'] != __version__:
            raise StreamRecordingError('ERROR-VERSION_MISMATCH')

        if 'protocol' not in data:
            raise StreamRecordingError('ERROR-NO_PROTOCOL_FOUND')
        elif data['protocol'] != RORNET_VERSION:
            raise StreamRecordingError('ERROR-PROTOCOL_MISMATCH')

        if 'recording' not in data:
            raise StreamRecordingError('ERROR-NO_RECORDING_FOUND')

        recording = data['recording']
        recording['frames'] = [
            bytes.fromhex(frame) for frame in recording['frames']
        ]

        return cls(server=server, **recording)

    def __str__(self) -> str:
        return pformat(self)

    def _on_stream_data(
        self,
        uid: int,
        stream: StreamRegister,
        stream_data: StreamData
    ) -> None:
        """Record a stream. This is a callback for the RoRConnection. It is
        called when stream data is received.

        :param uid: The UID of the user who sent the stream data.
        :param stream: The stream this data is for.
        :param stream_data: The stream data.
        """
        if uid != self.user.unique_id:
            return  # not our user

        if not (
            isinstance(stream, ActorStreamRegister)
            and isinstance(stream_data, ActorStreamData)
        ):
            return

        if stream.origin_stream_id != self.stream.origin_stream_id:
            return

        if not self.is_recording:
            return

        self.frames.append(stream_data.pack())

    async def _on_frame_step(self, dt: float) -> None:
        """Advance the recording by one frame."""
        if self._playback is PlaybackStatus.PLAYING:
            self._time_delta += dt

            exp_delta = (self.curr_frame.time - self.last_frame.time) / 1000

            if self._time_delta >= exp_delta:
                self._time_delta = 0

                if self._stream_id is None:
                    raise StreamRecordingError('ERROR-NO_STREAM_ID')

                # stream the frame
                await self.server.send_actor_stream_data(
                    self._stream_id,
                    self.curr_frame,
                )

                # advance 1 frame in index
                self._last_frame_idx = self._curr_frame_idx
                self._curr_frame_idx += 1
                if self._curr_frame_idx > len(self.frames) - 1:
                    self._curr_frame_idx = 1
                    self._last_frame_idx = 0

    def save(self) -> None:
        """Save the recording to a file."""
        if not self.frames:
            raise StreamRecordingError('ERROR-NO_DATA_RECORDED')

        logger.info('[REC] Saving recording %s', self.filename)

        recording = self.model_dump(mode='json', exclude={'server', 'frames'})
        recording['frames'] = [frame.hex() for frame in self.frames]

        data = {
            'version': __version__,
            'protocol': RORNET_VERSION,
            'recording': recording
        }

        with open(self.full_path, 'wb') as file:
            file.write(json.dumps(data).encode())

    def start_recording(self) -> None:
        """Start recording. This will attach a listener to the RoRConnection
        to record the stream data.
        """
        logger.info('[REC] Starting recording %s', self.filename)
        self._recording = RecordingStatus.RECORDING
        self.server.on(
            RoRClientEvents.STREAM_DATA,
            self._on_stream_data
        )

    def pause_recording(self) -> None:
        """Pause recording."""
        logger.info('[REC] Pausing recording %s', self.filename)
        self._recording = RecordingStatus.PAUSED

    def resume_recording(self) -> None:
        """Unpause recording."""
        logger.info('[REC] Resuming recording %s', self.filename)
        self._recording = RecordingStatus.RECORDING

    def stop_recording(self) -> None:
        """Stop recording. This will remove the listener from the RoRConnection
        that was recording the stream data.
        """
        logger.info('[REC] Stopping recording %s', self.filename)
        self._recording = RecordingStatus.STOPPED

        logger.debug('[REC] Data %s', self)

        self.server.remove_listener(
            RoRClientEvents.STREAM_DATA,
            self._on_stream_data
        )

    async def play(self) -> None:
        """Play the recording. This will stream the recording to the
        server."""
        logger.info('[REC] Playing recording %s', self.filename)

        self._playback = PlaybackStatus.PLAYING
        self._stream_id = await self.server.register_stream(self.stream)
        self.server.on(RoRClientEvents.FRAME_STEP, self._on_frame_step)

    def pause_playback(self) -> None:
        """Pause playback."""
        logger.info('[REC] Pausing playback %s', self.filename)
        self._playback = PlaybackStatus.PAUSED

    def resume_playback(self) -> None:
        """Resume playback."""
        logger.info('[REC] Resuming playback %s', self.filename)
        self._playback = PlaybackStatus.PLAYING

    async def stop_playback(self) -> None:
        logger.info('[REC] Stopping playback %s', self.filename)

        self.pause_playback()

        if self._stream_id is None:
            raise StreamRecordingError('ERROR-NO_STREAM_ID')

        await self.server.unregister_stream(self._stream_id)
        self.server.remove_listener(
            RoRClientEvents.FRAME_STEP,
            self._on_frame_step
        )


class UserRecordings(dict[int, Recording]):
    def __init__(self, uid: int) -> None:
        self.uid = uid
        super().__init__()

    def __str__(self) -> str:
        return pformat(self)

    def start_recording(
        self,
        server: RoRConnection,
        user: UserInfo,
        stream: ActorStreamRegister,
        filename: Path | None = None,
    ) -> None:
        """Start recording for the given user and stream.

        :param user: The user info for the user to record.
        :param stream: The stream to record.
        :param filename: The filename to save the recording to.
        """
        if stream.origin_source_id != user.unique_id:
            raise StreamRecordingError('ERROR-STREAM_USER_MISMATCH')

        recording = Recording(
            server=server,
            user=user,
            stream=stream,
            filename=filename
        )

        self[stream.origin_stream_id] = recording

        recording.start_recording()

    def pause_recording(self, sid: int | None = None) -> None:
        """Pause recording. If sid is None, then all recordings for the
        user will be paused. Otherwise, only the recording with the
        given sid will be paused.

        :param sid: The stream id of the recording to pause,
        defaults to None
        """
        recordings = self.values() if sid is None else [self[sid]]

        for recording in recordings:
            recording.pause_recording()

    def resume_recording(self, sid: int | None = None) -> None:
        """Unpause recording. If sid is None, then all recordings for the
        user will be unpaused. Otherwise, only the recording with the
        given sid will be unpaused.

        :param sid: The stream id of the recording to unpause,
        defaults to None
        """
        recordings = self.values() if sid is None else [self[sid]]

        for recording in recordings:
            recording.resume_recording()

    def stop_recording(self, sid: int | None = None) -> Recording:
        """Stop recording. If sid is None, then all recordings for the
        user will be stopped. Otherwise, only the recording with the
        given sid will be stopped.

        :param sid: The stream id of the recording to stop,
        defaults to None
        :return: The last recording that was stopped.
        """
        recordings = list(self.values()) if sid is None else [self[sid]]

        for recording in recordings:
            recording.stop_recording()
            recording.save()
            self.pop(recording.stream.origin_stream_id)

        return recordings[-1]


class StreamRecorder:
    def __init__(self, server: RoRConnection) -> None:
        try:
            last_recording = max(
                RECORDINGS_PATH.glob('*.rec'),
                key=lambda f: f.stat().st_mtime
            )
        except ValueError:
            last_recording = None

        self.last_recording = last_recording

        self.server = server
        self.playlist: list[Recording] = []
        self.recordings: dict[int, UserRecordings] = {}
        """A dictionary of active recordings for each user."""

    def __str__(self) -> str:
        return pformat(self)

    @property
    def available_recordings(self) -> list[Path]:
        """Get a list of all available recordings."""
        return list(RECORDINGS_PATH.glob('*.rec'))

    def start_recording(
        self,
        user: UserInfo,
        stream_id: int,
        filename: Path | None = None,
    ) -> None:
        stream = self.server.get_stream(user.unique_id, stream_id)

        if not isinstance(stream, ActorStreamRegister):
            raise StreamRecordingError(
                'You can only record actor streams...'
            )

        if stream.origin_source_id != user.unique_id:
            raise StreamRecordingError(
                'You can only record your own streams...'
            )

        if user.unique_id != stream.origin_source_id:
            raise StreamRecordingError(
                'User and stream origin source id mismatch'
            )

        user_recordings = self.recordings.setdefault(
            user.unique_id,
            UserRecordings(user.unique_id)
        )

        user_recordings.start_recording(self.server, user, stream, filename)

    def stop_recording(self, uid: int, sid: int | None = None) -> str:
        if uid not in self.recordings:
            raise StreamRecordingError(f'ERROR-NO_RECORDINGS_FOR_USER-{uid}')

        user_recordings = self.recordings[uid]

        if sid is None:
            sid = self.server.get_current_stream(uid).origin_stream_id

        if sid not in user_recordings:
            raise StreamRecordingError(
                f'ERROR-NO_RECORDINGS_FOR_STREAM-{sid}'
            )

        self.last_recording = user_recordings.stop_recording(sid).filename

        if not user_recordings:
            self.recordings.pop(uid)

        return self.last_recording.name

    def pause_recording(self, uid: int, stream_id: int | None = None) -> None:
        if uid not in self.recordings:
            raise StreamRecordingError(f'ERROR-NO_RECORDINGS_FOR_USER-{uid}')

        self.recordings[uid].pause_recording(stream_id)

    def resume_recording(self, uid: int, stream_id: int | None = None) -> None:
        if uid not in self.recordings:
            raise StreamRecordingError(f'ERROR-NO_RECORDINGS_FOR_USER-{uid}')

        self.recordings[uid].resume_recording(stream_id)

    async def play_recording(self, filename: Path | None) -> None:
        if filename is None:
            if self.last_recording is None:
                raise StreamRecordingError('ERROR-NO_RECORDING_FOUND')
            filename = self.last_recording

        recording = None
        with contextlib.suppress(Exception):
            recording = Recording.load(filename, self.server)

        if recording is None:
            raise StreamRecordingError('ERROR-NO_RECORDING_FOUND')

        await recording.play()
        self.playlist.append(recording)

    def pause_playback(self, stream_id: int | None = None) -> None:
        for recording in self.playlist:
            if stream_id is None or recording.stream_id == stream_id:
                recording.pause_playback()

    def resume_playback(self, stream_id: int | None = None) -> None:
        for recording in self.playlist:
            if stream_id is None or recording.stream_id == stream_id:
                recording.resume_playback()

    async def stop_playback(self, stream_id: int | None = None) -> None:
        for recording in self.playlist:
            if stream_id is None or recording.stream_id == stream_id:
                await recording.stop_playback()
                self.playlist.remove(recording)
