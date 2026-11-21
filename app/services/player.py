"""Playback and queue rules that hold for every audio engine."""
from __future__ import annotations

from app.adapters.base import AudioEngine, EngineStatus
from app.errors import ConflictError, InvalidRequestError, NotFoundError
from app.schemas.library import Album, AlbumDetail, Artist, ArtistDetail, Library, Track
from app.schemas.player import PlaybackState, Queue, QueueItem

# Which input sources accept which operations. Remote senders (AirPlay, Bluetooth) control themselves.
_CONTROLLABLE = ("local", "spotify")
_WITH_METADATA = ("local", "spotify", "airplay")


class PlayerService:
    def __init__(self, engine: AudioEngine):
        self._engine = engine

    # ---- library ----
    def library(self) -> Library:
        return Library(albums=self._engine.albums(), tracks=self._engine.tracks())

    def album(self, album_id: str) -> AlbumDetail:
        album = next((item for item in self._engine.albums() if item.id == album_id), None)
        if album is None:
            raise NotFoundError(f"Album {album_id!r} does not exist.", "album_not_found")
        return AlbumDetail(**album.model_dump(), tracks=[track for track in self._engine.tracks() if track.album_id == album_id])

    def artists(self) -> list[Artist]:
        albums, tracks = self._engine.albums(), self._engine.tracks()
        names = list(dict.fromkeys(album.artist for album in albums))
        return [Artist(name=name, album_count=sum(a.artist == name for a in albums), track_count=sum(t.artist == name for t in tracks)) for name in names]

    def artist(self, name: str) -> ArtistDetail:
        artist = next((item for item in self.artists() if item.name == name), None)
        if artist is None:
            raise NotFoundError(f"Artist {name!r} does not exist.", "artist_not_found")
        return ArtistDetail(**artist.model_dump(), albums=[album for album in self._engine.albums() if album.artist == name])

    def track(self, track_id: str) -> Track:
        track = next((item for item in self._engine.tracks() if item.id == track_id), None)
        if track is None:
            raise NotFoundError(f"Track {track_id!r} does not exist.", "track_not_found")
        return track

    # ---- state ----
    @staticmethod
    def _index(status: EngineStatus) -> int:
        return next((i for i, entry in enumerate(status.queue) if entry.id == status.current_id), -1)

    def state(self) -> PlaybackState:
        status = self._engine.status()
        index = self._index(status)
        current = status.queue[index].track if index >= 0 else None
        local = status.source == "local"
        can_control = status.source in _CONTROLLABLE
        if local:
            track = current
        elif status.source in _WITH_METADATA:
            track = current or next(iter(self._engine.tracks()), None)
        else:
            track = None
        return PlaybackState(
            revision=status.version, source=status.source, status=status.status, track=track,
            position=round(status.position, 3), format=status.format,
            queue=[QueueItem(id=entry.id, track=entry.track) for entry in status.queue], current_id=status.current_id,
            can_control=can_control, can_seek=local and current is not None, can_queue=local,
            has_previous=can_control and index > 0, has_next=can_control and 0 <= index < len(status.queue) - 1,
        )

    def queue(self) -> Queue:
        state = self.state()
        return Queue(revision=state.revision, items=state.queue, current_id=state.current_id)

    def _controllable(self) -> PlaybackState:
        state = self.state()
        if not state.can_control:
            raise ConflictError(f"Playback cannot be controlled while the input source is {state.source!r}.", "not_controllable")
        return state

    # ---- transport ----
    def play(self) -> PlaybackState:
        state = self._controllable()
        if state.current_id is not None:
            self._engine.play()
        elif state.queue:
            self._engine.play(state.queue[0].id)
        else:
            raise ConflictError("The queue is empty; there is nothing to play.", "queue_empty")
        return self.state()

    def pause(self) -> PlaybackState:
        self._controllable()
        self._engine.pause()  # no effect unless playing
        return self.state()

    def stop(self) -> PlaybackState:
        self._controllable()
        self._engine.stop()
        return self.state()

    def next(self) -> PlaybackState:
        if not self._controllable().has_next:
            raise ConflictError("There is no next track in the queue.", "no_next_track")
        self._engine.next()
        return self.state()

    def previous(self) -> PlaybackState:
        if not self._controllable().has_previous:
            raise ConflictError("There is no previous track in the queue.", "no_previous_track")
        self._engine.previous()
        return self.state()

    def seek(self, seconds: float) -> PlaybackState:
        state = self.state()
        if not state.can_seek or state.track is None:
            raise ConflictError("The current source or state does not allow seeking.", "not_seekable")
        if seconds > state.track.duration:
            raise InvalidRequestError(f"seconds must be between 0 and the track duration ({state.track.duration}).", "seek_out_of_range")
        self._engine.seek(seconds)
        return self.state()

    # ---- queue ----
    def play_queue_item(self, item_id: int) -> PlaybackState:
        self._engine.play(item_id)
        return self.state()

    def play_track(self, track_id: str) -> PlaybackState:
        """Select a library track: reuse its queue entry, or insert it after the current item."""
        self.track(track_id)
        status = self._engine.status()
        queued = next((entry for entry in status.queue if entry.track.id == track_id), None)
        item_id = queued.id if queued else self._engine.add(track_id, self._index(status) + 1)
        self._engine.play(item_id)
        return self.state()

    def replace_queue(self, track_ids: list[str]) -> PlaybackState:
        """Replace the queue (for example with an album) and play its first track."""
        for track_id in track_ids:
            self.track(track_id)  # reject the whole request before changing anything
        self._engine.clear()
        ids = [self._engine.add(track_id) for track_id in track_ids]
        self._engine.play(ids[0])
        return self.state()

    def enqueue(self, track_id: str) -> PlaybackState:
        self._engine.add(track_id)
        return self.state()

    def remove(self, item_id: int) -> PlaybackState:
        self._engine.remove(item_id)
        return self.state()

    def move(self, item_id: int, direction: int) -> PlaybackState:
        status = self._engine.status()
        index = next((i for i, entry in enumerate(status.queue) if entry.id == item_id), -1)
        if index < 0:
            raise NotFoundError(f"Queue item {item_id} does not exist.", "queue_item_not_found")
        self._engine.move(item_id, index + direction)
        return self.state()

    def clear(self) -> PlaybackState:
        self._engine.clear()
        return self.state()

    # ---- development ----
    def set_source(self, source: str) -> PlaybackState:
        self._engine.set_source(source)
        return self.state()
