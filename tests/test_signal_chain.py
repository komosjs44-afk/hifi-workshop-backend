import pytest

from .conftest import error_code

BASE = "/api/signal-chain"


def add(client, kind):
    response = client.post(f"{BASE}/modules", json={"kind": kind})
    assert response.status_code == 201
    return response.json()["moduleId"]


def module(client, module_id):
    return next(item for item in client.get(BASE).json()["modules"] if item["id"] == module_id)


def test_initial_state_and_limits(client):
    assert client.get(BASE).json() == {"revision": 1, "processing": False, "modules": []}
    assert client.get(f"{BASE}/limits").json() == {
        "gain": {"min": -12, "max": 12}, "frequency": {"min": 20, "max": 20000},
        "q": {"min": 0.1, "max": 10}, "crossfeed": {"min": 0, "max": 100}, "eqBands": 8,
    }


def test_processing_switch(client):
    assert client.put(f"{BASE}/processing", json={"enabled": True}).json()["processing"] is True
    assert client.put(f"{BASE}/processing", json={"enabled": False}).json()["processing"] is False
    for payload in ({"enabled": "yes"}, {"enabled": 1}, {}):
        assert client.put(f"{BASE}/processing", json=payload).status_code == 422


def test_add_modules_with_defaults(client):
    gain, eq, crossfeed = add(client, "gain"), add(client, "eq"), add(client, "crossfeed")
    modules = client.get(BASE).json()["modules"]
    assert [item["kind"] for item in modules] == ["gain", "eq", "crossfeed"]
    assert module(client, gain) == {"id": gain, "enabled": True, "kind": "gain", "gain": 0.0}
    assert module(client, crossfeed)["amount"] == 30.0
    bands = module(client, eq)["bands"]
    assert [(band["frequency"], band["gain"], band["q"]) for band in bands] == [(100.0, 0.0, 1.0), (1000.0, 0.0, 1.0), (8000.0, 0.0, 1.0)]
    assert len({gain, eq, crossfeed, *(band["id"] for band in bands)}) == 6
    assert client.post(f"{BASE}/modules", json={"kind": "reverb"}).status_code == 422


def test_gain_setting_and_range(client):
    gain = add(client, "gain")
    assert client.patch(f"{BASE}/modules/{gain}", json={"gain": -3.5}).json()["modules"][0]["gain"] == -3.5
    for value in (-12, 12):
        assert client.patch(f"{BASE}/modules/{gain}", json={"gain": value}).status_code == 200
    for value in (-12.5, 12.01, "loud"):
        response = client.patch(f"{BASE}/modules/{gain}", json={"gain": value})
        assert response.status_code == 422 and error_code(response) == "validation_error"
    assert module(client, gain)["gain"] == 12  # rejected values change nothing


def test_crossfeed_setting_and_range(client):
    crossfeed = add(client, "crossfeed")
    assert client.patch(f"{BASE}/modules/{crossfeed}", json={"amount": 55}).json()["modules"][0]["amount"] == 55
    for value in (-1, 100.5):
        assert client.patch(f"{BASE}/modules/{crossfeed}", json={"amount": value}).status_code == 422


def test_module_on_off(client):
    gain = add(client, "gain")
    assert client.patch(f"{BASE}/modules/{gain}", json={"enabled": False}).json()["modules"][0]["enabled"] is False
    assert client.patch(f"{BASE}/modules/{gain}", json={"enabled": True, "gain": 2}).json()["modules"][0] == {"id": gain, "enabled": True, "kind": "gain", "gain": 2.0}
    assert client.patch(f"{BASE}/modules/{gain}", json={"enabled": "off"}).status_code == 422
    assert client.patch(f"{BASE}/modules/{gain}", json={}).status_code == 422
    assert client.patch(f"{BASE}/modules/{gain}", json={"volume": 3}).status_code == 422


def test_parameter_of_another_module_kind_is_422(client):
    gain, eq = add(client, "gain"), add(client, "eq")
    for module_id, payload in ((gain, {"amount": 10}), (eq, {"gain": 1})):
        response = client.patch(f"{BASE}/modules/{module_id}", json=payload)
        assert response.status_code == 422 and error_code(response) == "parameter_not_applicable"
    response = client.post(f"{BASE}/modules/{gain}/bands")
    assert response.status_code == 422 and error_code(response) == "not_an_eq_module"


def test_move_and_remove_modules(client):
    gain, eq = add(client, "gain"), add(client, "eq")
    moved = client.post(f"{BASE}/modules/{eq}/move", json={"direction": -1}).json()
    assert [item["id"] for item in moved["modules"]] == [eq, gain]
    response = client.post(f"{BASE}/modules/{eq}/move", json={"direction": -1})
    assert response.status_code == 409 and error_code(response) == "module_move_out_of_range"
    assert client.post(f"{BASE}/modules/{eq}/move", json={"direction": 3}).status_code == 422
    assert [item["id"] for item in client.delete(f"{BASE}/modules/{eq}").json()["modules"]] == [gain]
    for response in (client.delete(f"{BASE}/modules/{eq}"), client.patch(f"{BASE}/modules/{eq}", json={"enabled": True}), client.post(f"{BASE}/modules/{eq}/move", json={"direction": 1})):
        assert response.status_code == 404 and error_code(response) == "module_not_found"


def test_eq_band_parameters(client):
    eq = add(client, "eq")
    band = module(client, eq)["bands"][1]["id"]
    body = client.patch(f"{BASE}/modules/{eq}/bands/{band}", json={"frequency": 630, "gain": 6, "q": 2.5}).json()
    assert body["modules"][0]["bands"][1] == {"id": band, "frequency": 630.0, "gain": 6.0, "q": 2.5}
    partial = client.patch(f"{BASE}/modules/{eq}/bands/{band}", json={"q": 0.7}).json()
    assert partial["modules"][0]["bands"][1] == {"id": band, "frequency": 630.0, "gain": 6.0, "q": 0.7}


@pytest.mark.parametrize("payload", [
    {"frequency": 19.9}, {"frequency": 20000.1}, {"gain": -12.1}, {"gain": 13}, {"q": 0.09}, {"q": 10.1}, {"q": 0},
    {"frequency": "1k"}, {}, {"slope": 12}, {"frequency": 1000, "gain": 99},
])
def test_eq_band_rejects_out_of_range_values(client, payload):
    eq = add(client, "eq")
    before = module(client, eq)
    response = client.patch(f"{BASE}/modules/{eq}/bands/{before['bands'][0]['id']}", json=payload)
    assert response.status_code == 422 and error_code(response) == "validation_error"
    assert module(client, eq) == before


@pytest.mark.parametrize("payload", [{"frequency": 20}, {"frequency": 20000}, {"gain": -12}, {"gain": 12}, {"q": 0.1}, {"q": 10}])
def test_eq_band_accepts_the_limits_themselves(client, payload):
    eq = add(client, "eq")
    band = module(client, eq)["bands"][0]["id"]
    assert client.patch(f"{BASE}/modules/{eq}/bands/{band}", json=payload).status_code == 200


def test_eq_holds_at_most_eight_bands(client):
    eq = add(client, "eq")
    for count in range(4, 9):
        response = client.post(f"{BASE}/modules/{eq}/bands")
        assert response.status_code == 201 and len(response.json()["modules"][0]["bands"]) == count
    newest = response.json()["modules"][0]["bands"][-1]
    assert (newest["frequency"], newest["gain"], newest["q"]) == (1000.0, 0.0, 1.0)
    ninth = client.post(f"{BASE}/modules/{eq}/bands")
    assert ninth.status_code == 409 and error_code(ninth) == "band_limit_reached"
    assert len(module(client, eq)["bands"]) == 8


def test_eq_keeps_at_least_one_band(client):
    eq = add(client, "eq")
    bands = [band["id"] for band in module(client, eq)["bands"]]
    for band in bands[:2]:
        assert client.delete(f"{BASE}/modules/{eq}/bands/{band}").status_code == 200
    last = client.delete(f"{BASE}/modules/{eq}/bands/{bands[2]}")
    assert last.status_code == 409 and error_code(last) == "last_band"
    gone = client.delete(f"{BASE}/modules/{eq}/bands/{bands[0]}")
    assert gone.status_code == 404 and error_code(gone) == "band_not_found"
    assert client.patch(f"{BASE}/modules/{eq}/bands/99999", json={"gain": 1}).status_code == 404


def test_revision_grows_with_every_change(client):
    revisions = [client.get(BASE).json()["revision"]]
    gain = add(client, "gain")
    revisions.append(client.get(BASE).json()["revision"])
    revisions.append(client.patch(f"{BASE}/modules/{gain}", json={"gain": 1}).json()["revision"])
    client.patch(f"{BASE}/modules/{gain}", json={"gain": 99})  # rejected
    revisions.append(client.get(BASE).json()["revision"])
    assert revisions[0] < revisions[1] < revisions[2] == revisions[3]


def test_chain_is_handed_to_the_dsp_adapter(client):
    add(client, "gain")
    applied = client.app.state.services.dsp.last_applied
    assert applied is not None and applied.modules[0].kind == "gain"
    assert client.get("/api/system").json()["dsp"]["connected"] is False
