from typing import Literal

from pydantic import Field

from .common import CamelModel
from .library import Track

SourceKind = Literal["local", "spotify", "airplay", "bluetooth", "empty"]
PlaybackStatus = Literal["playing", "paused", "stopped"]


class SourceFormat(CamelModel):
    codec: str
    bit_depth: str
    sample_rate: str


class QueueItem(CamelModel):
    id: int
    track: Track


class PlaybackState(CamelModel):
    """Frontend PlaybackState plus `revision`, which grows whenever anything but the position changes."""
    revision: int
    source: SourceKind
    status: PlaybackStatus
    track: Track | None
    position: float  # seconds into the current track, computed by the server at response time
    format: SourceFormat | None
    queue: list[QueueItem]
    current_id: int | None
    can_control: bool
    can_seek: bool
    can_queue: bool
    has_previous: bool
    has_next: bool


class Queue(CamelModel):
    revision: int
    items: list[QueueItem]
    current_id: int | None


class SeekRequest(CamelModel):
    seconds: float = Field(ge=0, allow_inf_nan=False)


class TrackRequest(CamelModel):
    track_id: str = Field(min_length=1)


class ReplaceQueueRequest(CamelModel):
    track_ids: list[str] = Field(min_length=1, max_length=2000)


class MoveRequest(CamelModel):
    direction: Literal[-1, 1]


class SourceRequest(CamelModel):
    source: SourceKind
