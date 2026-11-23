"""API integration tests with COMET_AUDIO_ENGINE=mpd against the fake MPD server."""
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.adapters.mpd.engine import album_id
from app.config import Settings
from app.main import create_app

from .conftest import error_code, free_port
from .fake_mpd import FakeMpd

WAV44, WAV48, TIDES, LOW = "test/sine-44k.wav", "test/sine-48k.wav", "albums/Quiet/01.flac", "albums/Quiet/02.flac"
QUIET = album_id("Northbound", "Quiet Coordinates")


def player(client):
    return client.get("/api/player").json()


def queue_uris(body):
    return [item["track"]["id"] for item in body["queue"]]


# ---- system ----
def test_system_reports_mpd_connected_while_dsp_and_device_stay_simulated(mpd_client):
    body = mpd_client.get("/api/system").json()
    assert body["audioEngine"]["kind"] == "mpd"
    assert (body["audioEngine"]["connected"], body["audioEngine"]["simulated"]) == (True, False)
    assert body["dsp"]["simulated"] is True and body["device"]["simulated"] is True
    assert body["simulated"] is True and body["dataSource"] == "mock"  # not "live" until DSP and device are real
    assert body["devApi"] is False and mpd_client.post("/api/dev/reset").status_code == 404


def test_state_aggregates_mpd_playback(mpd_client, fake_mpd):
    fake_mpd.fill(WAV44)
    body = mpd_client.get("/api/state").json()
    assert body["playback"]["queue"][0]["track"]["id"] == WAV44 and body["playback"]["source"] == "local"


# ---- library ----
def test_library(mpd_client):
    body = mpd_client.get("/api/library").json()
    assert [track["id"] for track in body["tracks"]] == [TIDES, LOW, WAV44, WAV48]
    assert body["albums"][0] == {"id": QUIET, "title": "Quiet Coordinates", "artist": "Northbound", "year": 2024, "art": ""}


def test_library_detail_routes_accept_uris_with_slashes(mpd_client):
    assert mpd_client.get(f"/api/library/tracks/{TIDES}").json()["title"] == "Between the Tides"
    assert mpd_client.get(f"/api/library/tracks/{quote(TIDES, safe='')}").json()["id"] == TIDES
    assert mpd_client.get("/api/library/tracks/nope.flac").status_code == 404
    album = mpd_client.get(f"/api/library/albums/{QUIET}").json()
    assert [track["id"] for track in album["tracks"]] == [TIDES, LOW]
    artist = mpd_client.get("/api/library/artists/Northbound").json()
    assert (artist["albumCount"], artist["trackCount"]) == (1, 2)


# ---- player ----
def test_play_pause_stop_and_seek(mpd_client, fake_mpd):
    fake_mpd.fill(WAV44, WAV48)
    played = mpd_client.post("/api/player/play").json()  # nothing selected: starts the first item
    assert (played["status"], played["track"]["id"], played["position"]) == ("playing", WAV44, 0.0)
    assert played["format"] == {"codec": "WAV", "bitDepth": "16-bit", "sampleRate": "44.1 kHz"}
    assert (played["canControl"], played["canSeek"], played["canQueue"], played["hasPrevious"], played["hasNext"]) == (True, True, True, False, True)
    paused = mpd_client.post("/api/player/pause").json()
    assert paused["status"] == "paused" and paused["revision"] > played["revision"]
    sought = mpd_client.post("/api/player/seek", json={"seconds": 4.5}).json()
    assert (sought["status"], sought["position"]) == ("paused", 4.5)
    stopped = mpd_client.post("/api/player/stop").json()
    assert (stopped["status"], stopped["position"], stopped["currentId"]) == ("stopped", 0.0, played["currentId"])
    from_stop = mpd_client.post("/api/player/seek", json={"seconds": 2}).json()
    assert (from_stop["status"], from_stop["position"]) == ("paused", 2.0)


def test_seek_beyond_the_track_is_rejected(mpd_client, fake_mpd):
    fake_mpd.fill(WAV44)
    mpd_client.post("/api/player/play")
    response = mpd_client.post("/api/player/seek", json={"seconds": 11})
    assert response.status_code == 422 and error_code(response) == "seek_out_of_range"


def test_next_and_previous(mpd_client, fake_mpd):
    fake_mpd.fill(WAV44, WAV48)
    mpd_client.post("/api/player/play")
    mpd_client.post("/api/player/pause")
    following = mpd_client.post("/api/player/next").json()
    assert (following["track"]["id"], following["status"], following["hasNext"]) == (WAV48, "paused", False)
    response = mpd_client.post("/api/player/next")
    assert response.status_code == 409 and error_code(response) == "no_next_track"
    back = mpd_client.post("/api/player/previous").json()
    assert (back["track"]["id"], back["status"]) == (WAV44, "paused")


def test_play_on_an_empty_queue(mpd_client):
    response = mpd_client.post("/api/player/play")
    assert response.status_code == 409 and error_code(response) == "queue_empty"


def test_play_track_inserts_after_the_current_item(mpd_client, fake_mpd):
    fake_mpd.fill(WAV44, WAV48)
    mpd_client.post("/api/player/play")
    body = mpd_client.post("/api/player/play-track", json={"trackId": TIDES}).json()
    assert queue_uris(body) == [WAV44, TIDES, WAV48] and (body["track"]["id"], body["status"]) == (TIDES, "playing")
    again = mpd_client.post("/api/player/play-track", json={"trackId": WAV48}).json()
    assert len(again["queue"]) == 3 and again["track"]["id"] == WAV48  # reuses the queued entry


# ---- queue ----
def test_queue_add_remove_move_clear(mpd_client):
    added = mpd_client.post("/api/queue/items", json={"trackId": WAV44})
    assert added.status_code == 201 and queue_uris(added.json()) == [WAV44]
    mpd_client.post("/api/queue/items", json={"trackId": WAV48})
    body = mpd_client.post("/api/queue/items", json={"trackId": TIDES}).json()
    ids = [item["id"] for item in body["queue"]]
    moved = mpd_client.post(f"/api/queue/items/{ids[2]}/move", json={"direction": -1}).json()
    assert queue_uris(moved) == [WAV44, TIDES, WAV48]
    edge = mpd_client.post(f"/api/queue/items/{ids[0]}/move", json={"direction": -1})
    assert edge.status_code == 409 and error_code(edge) == "queue_move_out_of_range"
    removed = mpd_client.delete(f"/api/queue/items/{ids[1]}").json()
    assert queue_uris(removed) == [WAV44, TIDES]
    assert mpd_client.get("/api/queue").json()["items"] == removed["queue"]
    cleared = mpd_client.delete("/api/queue").json()
    assert (cleared["queue"], cleared["status"], cleared["currentId"]) == ([], "stopped", None)


def test_queue_errors(mpd_client):
    unknown = mpd_client.post("/api/queue/items", json={"trackId": "http://example.com/stream"})
    assert unknown.status_code == 404 and error_code(unknown) == "track_not_found"
    for response in (mpd_client.delete("/api/queue/items/999"), mpd_client.post("/api/queue/items/999/play"),
                     mpd_client.post("/api/queue/items/999/move", json={"direction": 1})):
        assert response.status_code == 404 and error_code(response) == "queue_item_not_found"


def test_replace_queue_with_an_album(mpd_client, fake_mpd):
    fake_mpd.fill(WAV44)
    tracks = [track["id"] for track in mpd_client.get(f"/api/library/albums/{QUIET}").json()["tracks"]]
    body = mpd_client.put("/api/queue", json={"trackIds": tracks}).json()
    assert queue_uris(body) == [TIDES, LOW] and (body["status"], body["track"]["id"], body["position"]) == ("playing", TIDES, 0.0)
    rejected = mpd_client.put("/api/queue", json={"trackIds": [WAV44, "nope"]})
    assert rejected.status_code == 404 and queue_uris(player(mpd_client)) == [TIDES, LOW]  # all or nothing


def test_remove_current_item_continues(mpd_client, fake_mpd):
    fake_mpd.fill(WAV44, WAV48)
    first = mpd_client.post("/api/player/play").json()["currentId"]
    body = mpd_client.delete(f"/api/queue/items/{first}").json()
    assert (body["track"]["id"], body["status"], body["position"]) == (WAV48, "playing", 0.0)


# ---- connection errors ----
def test_unreachable_mpd_answers_503_and_the_rest_keeps_working():
    client = TestClient(create_app(Settings(audio_engine="mpd", mpd_port=free_port(), mpd_timeout=0.2)))
    assert client.get("/api/health").status_code == 200
    system = client.get("/api/system").json()
    assert (system["audioEngine"]["kind"], system["audioEngine"]["connected"]) == ("mpd", False)
    assert "not reachable" in system["audioEngine"]["description"]
    for response in (client.get("/api/state"), client.get("/api/player"), client.get("/api/library"),
                     client.post("/api/player/play"), client.post("/api/queue/items", json={"trackId": WAV44})):
        assert response.status_code == 503 and error_code(response) == "mpd_unavailable"
        assert response.json()["error"]["message"]
    assert client.get("/api/signal-chain").status_code == 200 and client.get("/api/device").status_code == 200


def test_recovers_when_mpd_comes_back():
    port = free_port()
    client = TestClient(create_app(Settings(audio_engine="mpd", mpd_port=port, mpd_timeout=0.2)))
    assert client.get("/api/player").status_code == 503
    server = FakeMpd().start(port)
    try:
        assert client.get("/api/player").status_code == 200
        assert client.get("/api/system").json()["audioEngine"]["connected"] is True
        server.shutdown()  # MPD restarts: the open connection breaks
        assert client.get("/api/player").status_code == 503
        server = FakeMpd().start(port)
        server.fill(WAV48)
        assert queue_uris(player(client)) == [WAV48]  # new connection, queue read again
    finally:
        server.shutdown()
