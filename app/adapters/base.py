"""Interfaces between the services and whatever actually handles audio.

Stage 2-A ships mock implementations only (app/adapters/mock). The interfaces are shaped after
the systems planned for later stages so that swapping them in does not touch services or routes:

  AudioEngine  ->  MPD (queue, transport, library)  ->  ALSA  ->  HiFiBerry DAC2 Pro
  DspEngine    ->  CamillaDSP
  DeviceProbe  ->  /proc, ALSA and network interfaces of the Raspberry Pi
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.errors import NotSupportedError
from app.schemas.device import DeviceState
from app.schemas.library import Album, Track
from app.schemas.player import SourceFormat
from app.schemas.signal_chain import SignalChainState


@dataclass(frozen=True)
class ComponentInfo:
    kind: str
    connected: bool
    simulated: bool
    description: str


@dataclass(frozen=True)
class QueueEntry:
    id: int
    track: Track


@dataclass(frozen=True)
class EngineStatus:
    source: str
    status: str  # playing | paused | stopped
    queue: tuple[QueueEntry, ...]
    current_id: int | None
    position: float
    format: SourceFormat | None
    version: int  # grows whenever anything except the position changes


class AudioEngine(ABC):
    """Transport, queue and library. Methods mirror MPD commands closely on purpose."""

    @abstractmethod
    def info(self) -> ComponentInfo: ...

    @abstractmethod
    def albums(self) -> list[Album]: ...

    @abstractmethod
    def tracks(self) -> list[Track]: ...

    @abstractmethod
    def status(self) -> EngineStatus: ...

    @abstractmethod
    def play(self, item_id: int | None = None) -> None:
        """Start the given queue item from 0, or resume the current one when item_id is None."""

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def stop(self) -> None:
        """Stop and rewind to 0. The current item stays selected."""

    @abstractmethod
    def next(self) -> None:
        """Select the following item at position 0. Must keep the transport status."""

    @abstractmethod
    def previous(self) -> None: ...

    @abstractmethod
    def seek(self, seconds: float) -> None: ...

    @abstractmethod
    def add(self, track_id: str, index: int | None = None) -> int:
        """Insert a track at index (append when None) and return the new queue item id."""

    @abstractmethod
    def remove(self, item_id: int) -> None:
        """Removing the current item continues with the following one, or stops at the end."""

    @abstractmethod
    def move(self, item_id: int, index: int) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    # Development helpers. Real engines do not implement them.
    def set_source(self, source: str) -> None:
        raise NotSupportedError("This audio engine reports its input source itself; it cannot be set.", "source_preview_not_supported")

    def reset(self) -> None:
        raise NotSupportedError("This audio engine cannot be reset through the API.", "reset_not_supported")


class DspEngine(ABC):
    """Receives the validated signal chain whenever it changes."""

    @abstractmethod
    def info(self) -> ComponentInfo: ...

    @abstractmethod
    def apply(self, chain: SignalChainState) -> None: ...


class DeviceProbe(ABC):
    @abstractmethod
    def info(self) -> ComponentInfo: ...

    @abstractmethod
    def read(self) -> DeviceState: ...
