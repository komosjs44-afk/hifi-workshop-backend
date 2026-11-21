from typing import Literal

from .common import CamelModel
from .device import DeviceState
from .player import PlaybackState
from .signal_chain import SignalChainState


class Health(CamelModel):
    status: Literal["ok"]
    version: str
    server_id: str


class ComponentStatus(CamelModel):
    """One backend component (audio engine, DSP, device probe)."""
    kind: str
    connected: bool  # a real external system is reachable
    simulated: bool  # values are generated in this process
    description: str


class SystemStatus(CamelModel):
    server_id: str  # changes on every server start; clients drop cached state when it changes
    version: str
    uptime_seconds: float
    data_source: Literal["mock", "live"]
    simulated: bool  # true while any component is simulated
    audio_engine: ComponentStatus
    dsp: ComponentStatus
    device: ComponentStatus
    dev_api: bool


class AppState(CamelModel):
    """Everything a client polls, in one response."""
    server_id: str
    system: SystemStatus
    playback: PlaybackState
    signal_chain: SignalChainState
    device: DeviceState
