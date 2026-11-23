"""Checks against a real MPD. Skipped unless COMET_MPD_LIVE=1 (see docs/raspberry-pi-mpd-verification.md).

The MPD queue is saved before and restored after the test. MPD's configuration, database and
music files are only read. Audio output is not checked: with the null output nothing is heard.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

from app.adapters.mpd.client import MpdClient
from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.skipif(os.environ.get("COMET_MPD_LIVE") != "1", reason="set COMET_MPD_LIVE=1 to test against a running MPD")

HOST = os.environ.get("COMET_MPD_HOST", "127.0.0.1")
PORT = int(os.environ.get("COMET_MPD_PORT", "6601"))


@pytest.fixture
def live():
    mpd = MpdClient(HOST, PORT)
    status = dict(mpd.command("status"))
    saved = [value for key, value in mpd.command("playlistinfo") if key == "file"]
    client = TestClient(create_app(Settings(audio_engine="mpd", mpd_host=HOST, mpd_port=PORT, dev_api=False)))
    yield client, status
    mpd.execute([("clear",), *[("add", uri) for uri in saved]] if saved else [("clear",)])
    if "song" in status:
        restore = {"play": [], "pause": [("pause", "1")], "stop": [("stop",)]}[status["state"]]
        mpd.execute([("play", status["song"]), *restore])
    mpd.close()


def test_live_mpd(live):
    client, before = live
    assert before.get("consume") != "1", "consume mode removes played songs; turn it off for this test (mpc consume off)"

    system = client.get("/api/system").json()["audioEngine"]
    assert (system["kind"], system["connected"]) == ("mpd", True), system["description"]
    print("\nMPD:", system["description"])

    tracks = client.get("/api/library").json()["tracks"]
    wavs = [track for track in tracks if track["id"].lower().endswith(".wav")]
    assert len(wavs) >= 2, f"expected the 44.1/48 kHz WAV test files in the MPD library, found {[t['id'] for t in tracks]}"
    print("library:", [(t["id"], t["duration"]) for t in wavs])

    body = client.put("/api/queue", json={"trackIds": [wavs[0]["id"], wavs[1]["id"]]}).json()
    assert (body["status"], body["track"]["id"]) == ("playing", wavs[0]["id"])
    print("format:", body["format"])
    time.sleep(2.5)
    moving = client.get("/api/player").json()
    assert moving["position"] >= 1.5, f"position did not advance: {moving['position']}"

    paused = client.post("/api/player/pause").json()
    time.sleep(1.2)
    assert client.get("/api/player").json()["position"] == pytest.approx(paused["position"], abs=0.05)

    following = client.post("/api/player/next").json()
    assert (following["track"]["id"], following["status"]) == (wavs[1]["id"], "paused")
    back = client.post("/api/player/previous").json()
    assert (back["track"]["id"], back["status"]) == (wavs[0]["id"], "paused")

    sought = client.post("/api/player/seek", json={"seconds": 1.0}).json()
    assert sought["status"] == "paused" and sought["position"] == pytest.approx(1.0, abs=0.1)

    stopped = client.post("/api/player/stop").json()
    assert (stopped["status"], stopped["position"], stopped["currentId"]) == ("stopped", 0.0, back["currentId"])
    from_stop = client.post("/api/player/seek", json={"seconds": 2.0}).json()
    print("seek while stopped ->", from_stop["status"], from_stop["position"])

    ids = [item["id"] for item in client.get("/api/queue").json()["items"]]
    moved = client.post(f"/api/queue/items/{ids[1]}/move", json={"direction": -1}).json()
    assert [item["id"] for item in moved["queue"]] == [ids[1], ids[0]]
    removed = client.delete(f"/api/queue/items/{ids[1]}").json()
    assert [item["id"] for item in removed["queue"]] == [ids[0]]
    assert client.delete("/api/queue").json()["queue"] == []
