"""In-memory audio engine. It keeps a queue and a clock-driven position; it never produces audio."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from app.adapters.base import AudioEngine, ComponentInfo, EngineStatus, QueueEntry
from app.errors import ConflictError, NotFoundError
from app.schemas.library import Album, Track
from app.schemas.player import SourceFormat

_DATA = Path(__file__).parent / "data" / "library.json"
# Example source format for the local source only; external sources do not provide one.
_LOCAL_FORMAT = SourceFormat(codec="FLAC", bit_depth="24-bit", sample_rate="96 kHz")
_INITIAL_POSITION = 64.0


class MockAudioEngine(AudioEngine):
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        data = json.loads(_DATA.read_text(encoding="utf-8"))
        self._albums = [Album.model_validate(item) for item in data["albums"]]
        self._tracks = [Track.model_validate(item) for item in data["tracks"]]
        self._by_id = {track.id: track for track in self._tracks}
        self._version = 0
        self.reset()

    # ---- description and library ----
    def info(self) -> ComponentInfo:
        return ComponentInfo("mock", connected=False, simulated=True,
                             description="In-memory mock engine with fictional library data. No MPD, ALSA device or DAC is connected and no audio is played.")

    def albums(self) -> list[Album]:
        return list(self._albums)

    def tracks(self) -> list[Track]:
        return list(self._tracks)

    # ---- internals ----
    def _index(self) -> int:
        return next((i for i, entry in enumerate(self._queue) if entry.id == self._current_id), -1)

    def _ticking(self) -> bool:
        return self._status == "playing" and self._source == "local" and self._index() >= 0

    def _position(self) -> float:
        return self._anchor + (self._clock() - self._anchored_at) if self._ticking() else self._anchor

    def _sync(self) -> None:
        """Bring the state up to the present: freeze the position and advance past finished tracks."""
        if not self._ticking():
            return
        position, index, moved = self._position(), self._index(), False
        while position >= self._queue[index].track.duration:
            position -= self._queue[index].track.duration
            moved = True
            if index + 1 < len(self._queue):
                index += 1
            else:  # end of the queue: stop on the last item
                self._status, position = "stopped", 0.0
                break
        self._current_id = self._queue[index].id
        self._anchor, self._anchored_at = position, self._clock()
        if moved:
            self._version += 1

    def _changed(self) -> None:
        self._anchored_at = self._clock()
        self._version += 1

    def _entry(self, track: Track) -> QueueEntry:
        entry = QueueEntry(self._next_item_id, track)
        self._next_item_id += 1
        return entry

    def _find(self, item_id: int) -> int:
        index = next((i for i, entry in enumerate(self._queue) if entry.id == item_id), -1)
        if index < 0:
            raise NotFoundError(f"Queue item {item_id} does not exist.", "queue_item_not_found")
        return index

    # ---- state ----
    def status(self) -> EngineStatus:
        self._sync()
        return EngineStatus(
            source=self._source, status=self._status, queue=tuple(self._queue), current_id=self._current_id,
            position=self._position(), format=_LOCAL_FORMAT if self._source == "local" else None, version=self._version,
        )

    # ---- transport ----
    def play(self, item_id: int | None = None) -> None:
        self._sync()
        if item_id is None:
            if self._index() < 0:
                raise ConflictError("No queue item is selected.", "nothing_selected")
        else:
            self._find(item_id)
            self._current_id, self._anchor, self._source = item_id, 0.0, "local"
        self._status = "playing"
        self._changed()

    def pause(self) -> None:
        self._sync()
        if self._status == "playing":
            self._status = "paused"
            self._changed()

    def stop(self) -> None:
        self._sync()
        self._status, self._anchor = "stopped", 0.0
        self._changed()

    def _step(self, direction: int) -> None:
        self._sync()
        target = self._index() + direction
        if self._index() < 0 or not 0 <= target < len(self._queue):
            raise ConflictError("There is no track in that direction.", "no_next_track" if direction > 0 else "no_previous_track")
        self._current_id, self._anchor = self._queue[target].id, 0.0
        self._changed()

    def next(self) -> None:
        self._step(1)

    def previous(self) -> None:
        self._step(-1)

    def seek(self, seconds: float) -> None:
        self._sync()
        self._anchor = seconds
        if self._status == "stopped":
            self._status = "paused"
        self._changed()

    # ---- queue ----
    def add(self, track_id: str, index: int | None = None) -> int:
        self._sync()
        track = self._by_id.get(track_id)
        if track is None:
            raise NotFoundError(f"Track {track_id!r} does not exist.", "track_not_found")
        entry = self._entry(track)
        self._queue.insert(len(self._queue) if index is None else index, entry)
        self._changed()
        return entry.id

    def remove(self, item_id: int) -> None:
        self._sync()
        index = self._find(item_id)
        del self._queue[index]
        if item_id == self._current_id:
            self._anchor = 0.0
            if index < len(self._queue):
                self._current_id = self._queue[index].id
            else:
                self._current_id, self._status = None, "stopped"
        self._changed()

    def move(self, item_id: int, index: int) -> None:
        self._sync()
        current = self._find(item_id)
        if not 0 <= index < len(self._queue):
            raise ConflictError("The queue item cannot move further in that direction.", "queue_move_out_of_range")
        self._queue.insert(index, self._queue.pop(current))
        self._changed()

    def clear(self) -> None:
        self._sync()
        self._queue, self._current_id, self._status, self._anchor = [], None, "stopped", 0.0
        self._changed()

    # ---- development helpers ----
    def set_source(self, source: str) -> None:
        self._sync()
        self._source = source
        self._status = "playing" if source not in ("empty", "local") else "paused"
        self._anchor = 0.0
        self._changed()

    def reset(self) -> None:
        self._next_item_id = 1
        self._queue = [self._entry(track) for track in self._tracks]
        self._current_id = self._queue[0].id if self._queue else None
        self._source, self._status = "local", "paused"
        self._anchor, self._anchored_at = _INITIAL_POSITION, self._clock()
        self._version += 1
