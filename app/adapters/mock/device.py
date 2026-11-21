"""Illustrative device values. Nothing is read from the host system."""
from __future__ import annotations

import math
import time
from typing import Callable

from app.adapters.base import ComponentInfo, DeviceProbe
from app.config import VERSION
from app.schemas.device import DeviceInfo, DeviceSample, DeviceState, PcmFormat

_HISTORY = 24
_INTERVAL_SECONDS = 2
_INFO = DeviceInfo(
    uptime="2d 14h 32m", ip_address="192.0.2.42", ethernet="linkUp", link_speed="1 Gbps",
    audio_output="hw:0,0", audio_card="HiFiBerry DAC2 Pro", pcm_stream="PREPARED",
    pcm=PcmFormat(sample_rate="96 kHz", encoding="S32_LE", channels=2),
    mpd_status="running", mpd_error=None, software_version=VERSION,
)


def _sample(step: int) -> DeviceSample:
    # Fixed ranges and generated curves; not measurements.
    return DeviceSample(
        receive=round(max(0.0, 1.2 + 0.5 * math.sin(step / 3) + 0.2 * math.sin(step / 1.4)), 4),
        send=round(max(0.0, 0.18 + 0.08 * math.sin(step / 4)), 4),
        cpu=round(18 + 5 * math.sin(step / 3) + 2 * math.sin(step / 1.5)),
        temperature=round(44 + 2 * math.sin(step / 7)),
    )


class MockDeviceProbe(DeviceProbe):
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._started = clock()

    def info(self) -> ComponentInfo:
        return ComponentInfo("mock", connected=False, simulated=True,
                             description="Example device, network and system values. The device name, PCM format and MPD status are placeholders, not readings.")

    def read(self) -> DeviceState:
        step = int((self._clock() - self._started) // _INTERVAL_SECONDS)
        samples = [_sample(step + index - (_HISTORY - 1)) for index in range(_HISTORY)]
        return DeviceState(simulated=True, info=_INFO, samples=samples, sample_interval_seconds=_INTERVAL_SECONDS)
