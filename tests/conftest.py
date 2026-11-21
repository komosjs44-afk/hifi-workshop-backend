import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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


def error_code(response) -> str:
    return response.json()["error"]["code"]
