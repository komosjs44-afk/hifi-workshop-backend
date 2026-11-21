import pytest

from .conftest import error_code


def state(client):
    return client.get("/api/player").json()


def test_initial_state(client):
    body = state(client)
    assert (body["source"], body["status"], body["position"]) == ("local", "paused", 64.0)
    assert body["track"]["title"] == "Between the Tides" and body["currentId"] == body["queue"][0]["id"]
    assert len(body["queue"]) == 61
    assert body["format"] == {"codec": "FLAC", "bitDepth": "24-bit", "sampleRate": "96 kHz"}
    assert (body["canControl"], body["canSeek"], body["canQueue"], body["hasPrevious"], body["hasNext"]) == (True, True, True, False, True)


def test_position_follows_the_server_clock_only_while_playing(client, clock):
    clock.advance(30)
    assert state(client)["position"] == 64.0  # paused
    assert client.post("/api/player/play").json()["status"] == "playing"
    clock.advance(10.5)
    assert state(client)["position"] == 74.5
    paused = client.post("/api/player/pause").json()
    assert (paused["status"], paused["position"]) == ("paused", 74.5)
    clock.advance(100)
    assert state(client)["position"] == 74.5


def test_play_pause_stop_transitions(client, clock):
    # paused -> playing -> paused -> playing -> stopped -> playing
    assert client.post("/api/player/play").json()["status"] == "playing"
    assert client.post("/api/player/play").json()["status"] == "playing"  # idempotent
    assert client.post("/api/player/pause").json()["status"] == "paused"
    assert client.post("/api/player/pause").json()["status"] == "paused"  # idempotent
    client.post("/api/player/play")
    clock.advance(5)
    stopped = client.post("/api/player/stop").json()
    assert (stopped["status"], stopped["position"]) == ("stopped", 0.0)
    assert stopped["track"]["title"] == "Between the Tides"  # the current item stays selected
    assert client.post("/api/player/pause").json()["status"] == "stopped"  # pause does not leave stopped
    assert client.post("/api/player/stop").json()["status"] == "stopped"  # idempotent
    clock.advance(50)
    assert state(client)["position"] == 0.0
    resumed = client.post("/api/player/play").json()
    assert (resumed["status"], resumed["position"]) == ("playing", 0.0)


def test_track_end_advances_to_the_next_track(client, clock):
    client.post("/api/player/play")  # 64 s into a 248 s track
    before = state(client)["revision"]
    clock.advance(248 - 64 + 3)
    body = state(client)
    assert (body["track"]["title"], body["position"], body["status"]) == ("Soft Geometry", 3.0, "playing")
    assert body["revision"] > before


def test_long_gap_skips_several_tracks(client, clock):
    client.post("/api/player/play")
    clock.advance((248 - 64) + 216 + 10)  # rest of track 1, all of track 2, 10 s of track 3
    body = state(client)
    assert (body["track"]["title"], body["position"]) == ("After the Rain", 10.0)


def test_queue_end_stops_on_the_last_track(client, clock):
    album = [track["id"] for track in client.get("/api/library/albums/glass").json()["tracks"]]
    client.put("/api/queue", json={"trackIds": album})
    clock.advance(10_000)
    body = state(client)
    assert (body["status"], body["position"], body["track"]["title"], body["hasNext"]) == ("stopped", 0.0, "Miles Away", False)


def test_next_and_previous_keep_the_status(client):
    following = client.post("/api/player/next").json()
    assert (following["track"]["title"], following["position"], following["status"]) == ("Soft Geometry", 0.0, "paused")
    assert following["hasPrevious"] is True
    client.post("/api/player/play")
    back = client.post("/api/player/previous").json()
    assert (back["track"]["title"], back["status"]) == ("Between the Tides", "playing")


def test_next_and_previous_at_the_edges_are_409(client):
    response = client.post("/api/player/previous")
    assert response.status_code == 409 and error_code(response) == "no_previous_track"
    last = state(client)["queue"][-1]["id"]
    client.post(f"/api/queue/items/{last}/play")
    response = client.post("/api/player/next")
    assert response.status_code == 409 and error_code(response) == "no_next_track"


def test_seek(client, clock):
    body = client.post("/api/player/seek", json={"seconds": 120}).json()
    assert (body["position"], body["status"]) == (120.0, "paused")
    client.post("/api/player/play")
    clock.advance(2)
    assert client.post("/api/player/seek", json={"seconds": 30.25}).json()["position"] == 30.25
    clock.advance(1)
    assert state(client)["position"] == 31.25
    client.post("/api/player/pause")
    assert client.post("/api/player/seek", json={"seconds": 248}).json()["position"] == 248.0  # the duration itself is allowed


def test_seek_from_stopped_becomes_paused(client):
    client.post("/api/player/stop")
    body = client.post("/api/player/seek", json={"seconds": 10}).json()
    assert (body["status"], body["position"]) == ("paused", 10.0)


@pytest.mark.parametrize("payload", [{"seconds": -1}, {"seconds": "abc"}, {}, {"seconds": 1, "extra": 1}, {"seconds": None}])
def test_seek_rejects_malformed_input(client, payload):
    response = client.post("/api/player/seek", json=payload)
    assert response.status_code == 422 and error_code(response) == "validation_error"
    assert state(client)["position"] == 64.0


def test_seek_beyond_the_track_is_422(client):
    response = client.post("/api/player/seek", json={"seconds": 248.5})
    assert response.status_code == 422 and error_code(response) == "seek_out_of_range"


def test_empty_queue_handling(client):
    cleared = client.delete("/api/queue").json()
    assert (cleared["queue"], cleared["currentId"], cleared["track"], cleared["status"], cleared["position"]) == ([], None, None, "stopped", 0.0)
    assert (cleared["canSeek"], cleared["hasNext"], cleared["hasPrevious"]) == (False, False, False)
    response = client.post("/api/player/play")
    assert response.status_code == 409 and error_code(response) == "queue_empty"
    assert error_code(client.post("/api/player/seek", json={"seconds": 1})) == "not_seekable"
    assert error_code(client.post("/api/player/next")) == "no_next_track"
    assert client.post("/api/player/stop").status_code == 200 and client.post("/api/player/pause").status_code == 200


def test_play_without_a_current_item_starts_the_first_one(client):
    queue = state(client)["queue"]
    first, last = queue[0]["id"], queue[-1]["id"]
    client.post(f"/api/queue/items/{last}/play")
    after = client.delete(f"/api/queue/items/{last}").json()  # removing the current last item leaves nothing selected
    assert (after["currentId"], after["status"], after["track"]) == (None, "stopped", None)
    played = client.post("/api/player/play").json()
    assert (played["currentId"], played["status"], played["position"]) == (first, "playing", 0.0)


def test_play_track_reuses_the_queue_entry(client):
    body = client.post("/api/player/play-track", json={"trackId": "track-005"}).json()
    assert (body["track"]["title"], body["status"], body["position"], len(body["queue"])) == ("A Distant Signal", "playing", 0.0, 61)


def test_play_track_inserts_after_the_current_item_when_not_queued(client):
    client.put("/api/queue", json={"trackIds": ["track-001", "track-003"]})
    body = client.post("/api/player/play-track", json={"trackId": "track-010"}).json()
    assert [item["track"]["id"] for item in body["queue"]] == ["track-001", "track-010", "track-003"]
    assert body["track"]["id"] == "track-010" and body["status"] == "playing"


def test_play_track_unknown_is_404_and_malformed_is_422(client):
    response = client.post("/api/player/play-track", json={"trackId": "track-999"})
    assert response.status_code == 404 and error_code(response) == "track_not_found"
    assert client.post("/api/player/play-track", json={"trackId": ""}).status_code == 422
    assert client.post("/api/player/play-track", json={"trackId": 5}).status_code == 422


def test_external_sources_limit_control(client):
    bluetooth = client.post("/api/dev/source", json={"source": "bluetooth"}).json()
    assert (bluetooth["track"], bluetooth["format"], bluetooth["canControl"], bluetooth["canSeek"], bluetooth["canQueue"]) == (None, None, False, False, False)
    for command in ("play", "pause", "stop", "next", "previous"):
        response = client.post(f"/api/player/{command}")
        assert response.status_code == 409 and error_code(response) == "not_controllable"
    assert error_code(client.post("/api/player/seek", json={"seconds": 1})) == "not_seekable"

    spotify = client.post("/api/dev/source", json={"source": "spotify"}).json()
    assert (spotify["canControl"], spotify["canSeek"], spotify["status"]) == (True, False, "playing")
    assert spotify["track"] is not None and spotify["format"] is None

    empty = client.post("/api/dev/source", json={"source": "empty"}).json()
    assert (empty["track"], empty["canControl"], empty["status"]) == (None, False, "paused")
    assert client.post("/api/dev/source", json={"source": "cd"}).status_code == 422


def test_external_source_does_not_advance_the_position(client, clock):
    client.post("/api/dev/source", json={"source": "spotify"})
    clock.advance(60)
    assert state(client)["position"] == 0.0


def test_revision_grows_on_changes_but_not_with_time(client, clock):
    first = state(client)["revision"]
    client.post("/api/player/play")
    second = state(client)["revision"]
    clock.advance(5)
    assert second > first and state(client)["revision"] == second


def test_dev_reset_restores_the_initial_state(client):
    client.delete("/api/queue")
    client.post("/api/signal-chain/modules", json={"kind": "gain"})
    old = client.get("/api/state").json()
    body = client.post("/api/dev/reset").json()
    assert len(body["playback"]["queue"]) == 61 and body["playback"]["position"] == 64.0
    assert body["signalChain"]["modules"] == []
    assert body["playback"]["revision"] > old["playback"]["revision"] and body["signalChain"]["revision"] > old["signalChain"]["revision"]
