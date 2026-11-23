import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import error_code


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["version"] and body["serverId"]


def test_system_reports_mock_and_never_claims_a_connection(client):
    body = client.get("/api/system").json()
    assert body["dataSource"] == "mock" and body["simulated"] is True
    for component in ("audioEngine", "dsp", "device"):
        assert body[component]["kind"] == "mock"
        assert body[component]["connected"] is False and body[component]["simulated"] is True
        assert body[component]["description"]


def test_state_aggregates_every_slice(client):
    body = client.get("/api/state").json()
    assert set(body) == {"serverId", "system", "playback", "signalChain", "device"}
    assert body["playback"] == client.get("/api/player").json()
    assert body["signalChain"] == client.get("/api/signal-chain").json()


def test_server_id_differs_between_instances(client):
    other = TestClient(create_app(Settings()))
    assert client.get("/api/health").json()["serverId"] != other.get("/api/health").json()["serverId"]


def test_unknown_route_and_method_use_the_error_shape(client):
    assert client.get("/api/nope").status_code == 404 and error_code(client.get("/api/nope")) == "not_found"
    assert client.delete("/api/player").status_code == 405 and error_code(client.delete("/api/player")) == "method_not_allowed"


def test_malformed_json_is_422(client):
    response = client.post("/api/player/seek", content="{not json", headers={"content-type": "application/json"})
    assert response.status_code == 422 and error_code(response) == "validation_error"


def test_cors_allows_the_configured_origin_only(client):
    allowed = client.get("/api/health", headers={"origin": "http://localhost:5173"})
    other = client.get("/api/health", headers={"origin": "http://other.example"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in other.headers


def test_dev_api_can_be_disabled():
    client = TestClient(create_app(Settings(dev_api=False)))
    assert client.post("/api/dev/reset").status_code == 404
    assert client.get("/api/system").json()["devApi"] is False


def test_settings_from_the_raspberry_pi_environment(monkeypatch):
    for name, value in {"COMET_AUDIO_ENGINE": "mpd", "COMET_MPD_HOST": "127.0.0.1", "COMET_MPD_PORT": "6601", "COMET_DEV_API": "0"}.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert (settings.audio_engine, settings.mpd_host, settings.mpd_port, settings.dev_api_enabled) == ("mpd", "127.0.0.1", 6601, False)


def test_settings_defaults(monkeypatch):
    for name in ("COMET_AUDIO_ENGINE", "COMET_MPD_HOST", "COMET_MPD_PORT", "COMET_DEV_API", "COMET_CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert (settings.audio_engine, settings.mpd_host, settings.mpd_port, settings.dev_api_enabled) == ("mock", "127.0.0.1", 6600, True)
    monkeypatch.setenv("COMET_AUDIO_ENGINE", "MPD")
    assert Settings.from_env().dev_api_enabled is False  # off by default for real engines
    monkeypatch.setenv("COMET_AUDIO_ENGINE", "alsa")
    with pytest.raises(ValueError):
        Settings.from_env()
