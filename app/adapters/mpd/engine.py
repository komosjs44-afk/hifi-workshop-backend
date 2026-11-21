"""Placeholder for the MPD-backed audio engine (planned for the Raspberry Pi stage).

It exists so the selection path (COMET_AUDIO_ENGINE=mpd) and the error behaviour are testable
now. Every operation answers 501; nothing here opens a socket or claims a connection.

Intended mapping when implemented (python-mpd2 or equivalent):
  status()          -> status + currentsong + playlistinfo
  play(item_id)     -> playid <id> / pause 0
  pause(), stop()   -> pause 1, stop
  next(), previous()-> next, previous   (MPD starts playback on next/previous; restore the paused state)
  seek(seconds)     -> seekcur <seconds>
  add(track, index) -> addid <uri> [position]
  remove(item_id)   -> deleteid <id>
  move(item, index) -> moveid <id> <index>
  clear()           -> clear
  albums(), tracks()-> listallinfo / list album
"""
from __future__ import annotations

from app.adapters.base import AudioEngine, ComponentInfo, EngineStatus
from app.errors import NotSupportedError
from app.schemas.library import Album, Track


class MpdAudioEngine(AudioEngine):
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port

    def info(self) -> ComponentInfo:
        return ComponentInfo("mpd", connected=False, simulated=False,
                             description=f"MPD adapter for {self.host}:{self.port} is not implemented yet. No connection is attempted.")

    def _unavailable(self):
        raise NotSupportedError("The MPD audio engine is not implemented in this stage. Run the server with COMET_AUDIO_ENGINE=mock.", "engine_not_implemented")

    def albums(self) -> list[Album]: self._unavailable()
    def tracks(self) -> list[Track]: self._unavailable()
    def status(self) -> EngineStatus: self._unavailable()
    def play(self, item_id: int | None = None) -> None: self._unavailable()
    def pause(self) -> None: self._unavailable()
    def stop(self) -> None: self._unavailable()
    def next(self) -> None: self._unavailable()
    def previous(self) -> None: self._unavailable()
    def seek(self, seconds: float) -> None: self._unavailable()
    def add(self, track_id: str, index: int | None = None) -> int: self._unavailable()
    def remove(self, item_id: int) -> None: self._unavailable()
    def move(self, item_id: int, index: int) -> None: self._unavailable()
    def clear(self) -> None: self._unavailable()
