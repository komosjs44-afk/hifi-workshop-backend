import socket

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .fake_mpd import FakeMpd


class FakeClock:
    """Manually advanced clock so playback time is deterministic."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(clock: FakeClock) -> TestClient:
    return TestClient(create_app(Settings(), clock))


@pytest.fixture
def fake_mpd():
    server = FakeMpd().start()
    yield server
    server.shutdown()


@pytest.fixture
def mpd_client(fake_mpd: FakeMpd) -> TestClient:
    return TestClient(create_app(Settings(audio_engine="mpd", mpd_port=fake_mpd.port)))


def free_port() -> int:
    """A port with nothing listening on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def error_code(response) -> str:
    return response.json()["error"]["code"]
