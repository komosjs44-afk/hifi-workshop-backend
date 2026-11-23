"""Audio engine backed by a running MPD server.

MPD owns the queue, the transport and the library; this adapter translates. Where MPD's own
reaction to a command differs between versions or states (next/previous/seek while paused or
stopped, removing the current song), the adapter sends the exact follow-up commands in the same
command list, so the result matches the AudioEngine contract regardless of MPD's defaults.

Library ids: a track id is its MPD URI (relative to music_directory). An album id is a hash of
album artist and album title. Queue item ids are MPD song ids (`Id`).

Every call is a blocking round trip on one TCP connection. Request handlers run one at a time
on the event loop (see app/main.py), so the connection is never shared between two requests.
"""
from __future__ import annotations

import hashlib
import posixpath
import re

from app.adapters.base import AudioEngine, ComponentInfo, EngineStatus, QueueEntry
from app.adapters.mpd.client import Command, MpdClient, MpdConnectionError, MpdProtocolError, Pairs
from app.errors import ConflictError, DomainError, EngineError, EngineUnavailableError, NotFoundError
from app.schemas.library import Album, Track
from app.schemas.player import SourceFormat

ACK_NO_EXIST = 50
_STATES = {"play": "playing", "pause": "paused", "stop": "stopped"}
_UNKNOWN_ARTIST = "Unknown Artist"
_UNKNOWN_ALBUM = "Unknown Album"


# ---- conversion of MPD answers ----
def _songs(pairs: Pairs) -> list[dict[str, str]]:
    """Split listallinfo/playlistinfo output into songs. `directory` and `playlist` entries are skipped."""
    songs: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for key, value in pairs:
        if key in ("file", "directory", "playlist"):
            current = {} if key == "file" else None
            if current is not None:
                songs.append(current)
        if current is not None:
            current.setdefault(key, value)  # multi-value tags: keep the first
    return songs


def _number(value: str | None) -> int:
    match = re.match(r"\s*(\d+)", value or "")
    return int(match.group(1)) if match else 0


def album_id(artist: str, title: str) -> str:
    return "album-" + hashlib.sha1(f"{artist}\0{title}".encode("utf-8")).hexdigest()[:12]


def _album_fields(song: dict[str, str]) -> tuple[str, str]:
    """(album artist, album title). Untagged files are grouped by their folder."""
    artist = song.get("AlbumArtist") or song.get("Artist") or _UNKNOWN_ARTIST
    folder = posixpath.basename(posixpath.dirname(song["file"]))
    return artist, song.get("Album") or folder or _UNKNOWN_ALBUM


def to_track(song: dict[str, str]) -> Track:
    uri = song["file"]
    album_artist, album = _album_fields(song)
    duration = song.get("duration") or song.get("Time") or "0"
    return Track(
        id=uri,
        title=song.get("Title") or posixpath.splitext(posixpath.basename(uri))[0] or uri,
        artist=song.get("Artist") or album_artist,
        album=album, album_id=album_id(album_artist, album),
        duration=round(float(duration)),
        art="",  # no cover art yet; the frontend shows its placeholder icon
    )


def _sort_key(song: dict[str, str]):
    artist, album = _album_fields(song)
    return artist.casefold(), album.casefold(), _number(song.get("Disc")), _number(song.get("Track")), song["file"]


def _sample_rate(rate: str) -> str:
    try:
        return f"{int(rate) / 1000:g} kHz"
    except ValueError:
        return rate


def _bit_depth(bits: str) -> str:
    if bits.isdigit():
        return f"{bits}-bit"
    return {"f": "32-bit float"}.get(bits, bits.upper())


def to_format(audio: str | None, uri: str | None) -> SourceFormat | None:
    """`audio` is MPD's "rate:bits:channels" (status `audio` or song `Format`)."""
    parts = (audio or "").split(":")
    if len(parts) != 3:
        return None
    extension = posixpath.splitext(uri or "")[1].lstrip(".")
    return SourceFormat(codec=extension.upper() or "PCM", bit_depth=_bit_depth(parts[1]), sample_rate=_sample_rate(parts[0]))


class MpdAudioEngine(AudioEngine):
    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self._client = MpdClient(host, port, timeout)
        self._version = 0
        self._signature: tuple | None = None
        self._queue_key: tuple | None = None
        self._queue: tuple[QueueEntry, ...] = ()
        self._formats: dict[int, str] = {}  # queue item id -> song Format, for when MPD reports no `audio`
        self._library_key: str | None = None
        self._albums: list[Album] = []
        self._tracks: list[Track] = []
        self._uris: set[str] = set()

    # ---- MPD calls ----
    def _run(self, *commands: Command, missing: DomainError | None = None) -> list[Pairs]:
        try:
            return self._client.execute(list(commands))
        except MpdConnectionError as error:
            raise EngineUnavailableError(f"MPD is not reachable: {error}", "mpd_unavailable") from error
        except MpdProtocolError as error:
            if error.code == ACK_NO_EXIST and missing is not None:
                raise missing from error
            raise EngineError(f"MPD refused {error.command!r}: {error.message}", "mpd_error") from error

    def _change(self, *commands: Command, missing: DomainError | None = None) -> list[Pairs]:
        try:
            return self._run(*commands, missing=missing)
        finally:
            self._version += 1  # a failed command list may have run partly

    # ---- description and library ----
    def info(self) -> ComponentInfo:
        address = self._client.address
        try:
            status = dict(self._run(("status",))[0])
        except DomainError as error:
            return ComponentInfo("mpd", connected=False, simulated=False, description=f"MPD at {address}: {error.message}")
        description = (f"Queue, transport and library come from MPD {self._client.server_version} at {address}. "
                       "The audio outputs configured in MPD are not checked by this server.")
        if status.get("error"):
            description += f" MPD reports: {status['error']}"
        return ComponentInfo("mpd", connected=True, simulated=False, description=description)

    def _library(self) -> None:
        stats = dict(self._run(("stats",))[0])
        key = stats.get("db_update", "")
        if key == self._library_key:
            return
        songs = sorted(_songs(self._run(("listallinfo",))[0]), key=_sort_key)
        tracks = [to_track(song) for song in songs]
        albums: dict[str, Album] = {}
        for song, track in zip(songs, tracks):
            if track.album_id not in albums:
                year = re.match(r"\d{4}", song.get("Date", ""))
                albums[track.album_id] = Album(id=track.album_id, title=track.album, artist=_album_fields(song)[0],
                                               year=int(year.group()) if year else 0, art="")
        self._tracks, self._albums, self._uris = tracks, list(albums.values()), {track.id for track in tracks}
        self._library_key = key

    def albums(self) -> list[Album]:
        self._library()
        return list(self._albums)

    def tracks(self) -> list[Track]:
        self._library()
        return list(self._tracks)

    # ---- state ----
    def status(self) -> EngineStatus:
        status = dict(self._run(("status",))[0])
        queue_key = (self._client.generation, status.get("playlist"))
        if queue_key != self._queue_key:
            songs = _songs(self._run(("playlistinfo",))[0])
            self._queue = tuple(QueueEntry(int(song["Id"]), to_track(song)) for song in songs)
            self._formats = {int(song["Id"]): song["Format"] for song in songs if "Format" in song}
            self._queue_key = queue_key
        current_id = int(status["songid"]) if "songid" in status else None
        current = next((entry for entry in self._queue if entry.id == current_id), None)
        state = _STATES.get(status.get("state", "stop"), "stopped")
        audio = status.get("audio") if state != "stopped" else None
        source_format = to_format(audio or self._formats.get(current_id), current.track.id if current else None) if current else None
        signature = (queue_key, state, current_id, source_format)
        if signature != self._signature:
            self._signature = signature
            self._version += 1
        return EngineStatus(
            source="local", status=state, queue=self._queue, current_id=current_id,
            position=float(status.get("elapsed", 0.0)) if state != "stopped" else 0.0,
            format=source_format, version=self._version,
        )

    @staticmethod
    def _index(status: EngineStatus, item_id: int | None) -> int:
        return next((i for i, entry in enumerate(status.queue) if entry.id == item_id), -1)

    def _find(self, status: EngineStatus, item_id: int) -> int:
        index = self._index(status, item_id)
        if index < 0:
            raise NotFoundError(f"Queue item {item_id} does not exist.", "queue_item_not_found")
        return index

    @staticmethod
    def _keep(status: str) -> list[Command]:
        """Commands that return to `status` after a `playid`, which always starts playback."""
        return {"paused": [("pause", "1")], "stopped": [("stop",)]}.get(status, [])

    # ---- transport ----
    def play(self, item_id: int | None = None) -> None:
        if item_id is not None:
            self._change(("playid", str(item_id)), missing=NotFoundError(f"Queue item {item_id} does not exist.", "queue_item_not_found"))
            return
        status = self.status()
        if self._index(status, status.current_id) < 0:
            raise ConflictError("No queue item is selected.", "nothing_selected")
        if status.status == "paused":
            self._change(("pause", "0"))
        elif status.status == "stopped":
            self._change(("playid", str(status.current_id)))

    def pause(self) -> None:
        if self.status().status == "playing":
            self._change(("pause", "1"))

    def stop(self) -> None:
        self._change(("stop",))

    def _step(self, direction: int) -> None:
        status = self.status()
        index = self._index(status, status.current_id)
        target = index + direction
        if index < 0 or not 0 <= target < len(status.queue):
            raise ConflictError("There is no track in that direction.", "no_next_track" if direction > 0 else "no_previous_track")
        self._change(("playid", str(status.queue[target].id)), *self._keep(status.status))

    def next(self) -> None:
        self._step(1)

    def previous(self) -> None:
        self._step(-1)

    def seek(self, seconds: float) -> None:
        status = self.status()
        if self._index(status, status.current_id) < 0:
            raise ConflictError("No queue item is selected.", "not_seekable")
        position = f"{seconds:.3f}"
        if status.status == "playing":
            self._change(("seekcur", position))
        elif status.status == "paused":
            self._change(("seekcur", position), ("pause", "1"))
        else:  # MPD cannot seek while stopped; seeking the song starts it, then pause (contract: stopped -> paused)
            self._change(("seekid", str(status.current_id), position), ("pause", "1"))

    # ---- queue ----
    def add(self, track_id: str, index: int | None = None) -> int:
        self._library()
        if track_id not in self._uris:  # only database songs: no URLs or local paths from clients
            raise NotFoundError(f"Track {track_id!r} does not exist.", "track_not_found")
        command = ("addid", track_id) if index is None else ("addid", track_id, str(index))
        answer = dict(self._change(command, missing=NotFoundError(f"Track {track_id!r} does not exist.", "track_not_found"))[0])
        return int(answer["Id"])

    def remove(self, item_id: int) -> None:
        status = self.status()
        index = self._find(status, item_id)
        commands: list[Command] = [("deleteid", str(item_id))]
        if item_id == status.current_id:
            if index + 1 < len(status.queue):
                commands += [("playid", str(status.queue[index + 1].id)), *self._keep(status.status)]
            else:
                commands.append(("stop",))
        self._change(*commands, missing=NotFoundError(f"Queue item {item_id} does not exist.", "queue_item_not_found"))

    def move(self, item_id: int, index: int) -> None:
        status = self.status()
        self._find(status, item_id)
        if not 0 <= index < len(status.queue):
            raise ConflictError("The queue item cannot move further in that direction.", "queue_move_out_of_range")
        self._change(("moveid", str(item_id), str(index)), missing=NotFoundError(f"Queue item {item_id} does not exist.", "queue_item_not_found"))

    def clear(self) -> None:
        self._change(("clear",))
