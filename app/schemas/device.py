from typing import Literal

from .common import CamelModel


class PcmFormat(CamelModel):
    sample_rate: str
    encoding: str
    channels: int


class DeviceInfo(CamelModel):
    uptime: str
    ip_address: str
    ethernet: Literal["linkUp"] | None
    link_speed: str
    audio_output: str
    audio_card: str
    pcm_stream: str
    pcm: PcmFormat
    mpd_status: Literal["running"] | None
    mpd_error: str | None
    software_version: str


class DeviceSample(CamelModel):
    receive: float
    send: float
    cpu: int
    temperature: int


class DeviceState(CamelModel):
    """Frontend DeviceState plus `simulated`: true when no value was read from real hardware."""
    simulated: bool
    info: DeviceInfo
    samples: list[DeviceSample]  # oldest first
    sample_interval_seconds: int
