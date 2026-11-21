"""Builds the adapters and services for one application instance."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable

from app.adapters.base import AudioEngine, ComponentInfo, DeviceProbe, DspEngine
from app.adapters.mock.device import MockDeviceProbe
from app.adapters.mock.dsp import MockDspEngine
from app.adapters.mock.engine import MockAudioEngine
from app.adapters.mpd.engine import MpdAudioEngine
from app.config import VERSION, Settings
from app.schemas.system import AppState, ComponentStatus, SystemStatus
from app.services.player import PlayerService
from app.services.signal_chain import SignalChainService


def _component(info: ComponentInfo) -> ComponentStatus:
    return ComponentStatus(kind=info.kind, connected=info.connected, simulated=info.simulated, description=info.description)


@dataclass
class Services:
    settings: Settings
    clock: Callable[[], float]
    engine: AudioEngine
    dsp: DspEngine
    probe: DeviceProbe
    player: PlayerService
    signal_chain: SignalChainService
    server_id: str
    started_at: float

    def system(self) -> SystemStatus:
        components = [self.engine.info(), self.dsp.info(), self.probe.info()]
        simulated = any(info.simulated for info in components)
        return SystemStatus(
            server_id=self.server_id, version=VERSION, uptime_seconds=round(self.clock() - self.started_at, 3),
            data_source="mock" if simulated else "live", simulated=simulated,
            audio_engine=_component(components[0]), dsp=_component(components[1]), device=_component(components[2]),
            dev_api=self.settings.dev_api_enabled,
        )

    def app_state(self) -> AppState:
        return AppState(server_id=self.server_id, system=self.system(), playback=self.player.state(),
                        signal_chain=self.signal_chain.state(), device=self.probe.read())

    def reset(self) -> None:
        self.engine.reset()
        self.signal_chain.reset()


def build_services(settings: Settings, clock: Callable[[], float] = time.monotonic) -> Services:
    engine: AudioEngine = MockAudioEngine(clock) if settings.audio_engine == "mock" else MpdAudioEngine(settings.mpd_host, settings.mpd_port)
    dsp, probe = MockDspEngine(), MockDeviceProbe(clock)
    return Services(
        settings=settings, clock=clock, engine=engine, dsp=dsp, probe=probe,
        player=PlayerService(engine), signal_chain=SignalChainService(dsp),
        server_id=uuid.uuid4().hex, started_at=clock(),
    )
