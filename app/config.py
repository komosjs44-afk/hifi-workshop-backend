"""Runtime settings, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

VERSION = "0.1.0"
ENGINES = ("mock", "mpd")


@dataclass(frozen=True)
class Settings:
    audio_engine: str = "mock"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    # None means "on for the mock engine, off otherwise".
    dev_api: bool | None = None
    mpd_host: str = "127.0.0.1"
    mpd_port: int = 6600
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def dev_api_enabled(self) -> bool:
        return self.audio_engine == "mock" if self.dev_api is None else self.dev_api

    @classmethod
    def from_env(cls) -> "Settings":
        engine = os.environ.get("COMET_AUDIO_ENGINE", "mock").strip().lower()
        if engine not in ENGINES:
            raise ValueError(f"COMET_AUDIO_ENGINE must be one of {ENGINES}, got {engine!r}")
        origins = os.environ.get("COMET_CORS_ORIGINS")
        dev = os.environ.get("COMET_DEV_API")
        return cls(
            audio_engine=engine,
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()) if origins is not None else cls.cors_origins,
            dev_api=None if dev is None else dev.strip().lower() in ("1", "true", "yes", "on"),
            mpd_host=os.environ.get("COMET_MPD_HOST", cls.mpd_host),
            mpd_port=int(os.environ.get("COMET_MPD_PORT", cls.mpd_port)),
        )
