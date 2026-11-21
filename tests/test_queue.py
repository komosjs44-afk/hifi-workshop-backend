import pytest

from .conftest import error_code


def ids(body):
    return [item["id"] for item in body["queue"]]


def titles(body):
    return [item["track"]["title"] for item in body["queue"]]


def test_get_queue(client):
    body = client.get("/api/queue").json()
    assert set(body) == {"revision", "items", "currentId"}
    assert len(body["items"]) == 61 and body["currentId"] == body["items"][0]["id"]


def test_enqueue_appends_and_allows_duplicates(client):
    response = client.post("/api/queue/items", json={"trackId": "track-002"})
    assert response.status_code == 201
    body = response.json()
    assert len(body["queue"]) == 62 and body["queue"][-1]["track"]["id"] == "track-002"
    assert len(set(ids(body))) == 62  # every queue item has its own id
    assert body["status"] == "paused" and body["position"] == 64.0  # playback is untouched


def test_enqueue_unknown_track_is_404(client):
    response = client.post("/api/queue/items", json={"trackId": "nope"})
    assert response.status_code == 404 and error_code(response) == "track_not_found"
    assert len(client.get("/api/queue").json()["items"]) == 61


def test_remove_other_item_keeps_playback(client):
    queue = client.get("/api/player").json()["queue"]
    body = client.delete(f"/api/queue/items/{queue[1]['id']}").json()
    assert len(body["queue"]) == 60 and body["currentId"] == queue[0]["id"] and body["position"] == 64.0


def test_remove_current_item_continues_with_the_following_one(client):
    client.post("/api/player/play")
    queue = client.get("/api/player").json()["queue"]
    body = client.delete(f"/api/queue/items/{queue[0]['id']}").json()
    assert (body["currentId"], body["position"], body["status"]) == (queue[1]["id"], 0.0, "playing")
    assert body["track"]["title"] == "Soft Geometry"


def test_remove_unknown_item_is_404(client):
    response = client.delete("/api/queue/items/99999")
    assert response.status_code == 404 and error_code(response) == "queue_item_not_found"
    assert client.delete("/api/queue/items/abc").status_code == 422


def test_move(client):
    before = client.get("/api/player").json()
    down = client.post(f"/api/queue/items/{before['queue'][1]['id']}/move", json={"direction": 1}).json()
    assert titles(down)[:3] == ["Between the Tides", "After the Rain", "Soft Geometry"]
    up = client.post(f"/api/queue/items/{before['queue'][1]['id']}/move", json={"direction": -1}).json()
    assert ids(up) == ids(before)
    assert up["currentId"] == before["currentId"]


def test_move_updates_next_and_previous(client):
    first = client.get("/api/player").json()["queue"][0]["id"]
    body = client.post(f"/api/queue/items/{first}/move", json={"direction": 1}).json()
    assert body["currentId"] == first and body["hasPrevious"] is True


def test_move_at_the_edges_is_409(client):
    queue = client.get("/api/player").json()["queue"]
    for item, direction in ((queue[0], -1), (queue[-1], 1)):
        response = client.post(f"/api/queue/items/{item['id']}/move", json={"direction": direction})
        assert response.status_code == 409 and error_code(response) == "queue_move_out_of_range"
    assert ids(client.get("/api/player").json()) == [item["id"] for item in queue]


@pytest.mark.parametrize("payload", [{"direction": 0}, {"direction": 2}, {"direction": "up"}, {}])
def test_move_rejects_invalid_directions(client, payload):
    item = client.get("/api/player").json()["queue"][3]["id"]
    assert client.post(f"/api/queue/items/{item}/move", json=payload).status_code == 422


def test_move_unknown_item_is_404(client):
    assert client.post("/api/queue/items/99999/move", json={"direction": 1}).status_code == 404


def test_play_item(client):
    item = client.get("/api/player").json()["queue"][7]
    body = client.post(f"/api/queue/items/{item['id']}/play").json()
    assert (body["currentId"], body["status"], body["position"], body["track"]["title"]) == (item["id"], "playing", 0.0, "Small Hours")
    assert client.post("/api/queue/items/99999/play").status_code == 404


def test_replace_queue_with_an_album(client):
    album = [track["id"] for track in client.get("/api/library/albums/quiet").json()["tracks"]]
    body = client.put("/api/queue", json={"trackIds": album}).json()
    assert [item["track"]["id"] for item in body["queue"]] == album
    assert (body["track"]["title"], body["status"], body["position"], body["hasPrevious"], body["hasNext"]) == ("Between the Tides", "playing", 0.0, False, True)


def test_replace_queue_is_all_or_nothing(client):
    before = client.get("/api/player").json()
    response = client.put("/api/queue", json={"trackIds": ["track-001", "nope"]})
    assert response.status_code == 404 and error_code(response) == "track_not_found"
    assert client.get("/api/player").json() == before
    assert client.put("/api/queue", json={"trackIds": []}).status_code == 422
    assert client.put("/api/queue", json={}).status_code == 422


def test_replace_queue_returns_to_the_local_source(client):
    client.post("/api/dev/source", json={"source": "bluetooth"})
    body = client.put("/api/queue", json={"trackIds": ["track-004"]}).json()
    assert (body["source"], body["canControl"], body["track"]["id"]) == ("local", True, "track-004")


def test_clear(client):
    client.post("/api/player/play")
    body = client.delete("/api/queue").json()
    assert (body["queue"], body["status"], body["currentId"]) == ([], "stopped", None)
    assert client.get("/api/queue").json()["items"] == []
    refill = client.post("/api/queue/items", json={"trackId": "track-003"}).json()
    assert refill["currentId"] is None and refill["status"] == "stopped"  # adding does not start playback
    assert client.post("/api/player/play").json()["track"]["id"] == "track-003"
