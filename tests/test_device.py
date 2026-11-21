def test_device_is_marked_as_simulated(client):
    body = client.get("/api/device").json()
    assert body["simulated"] is True
    assert set(body) == {"simulated", "info", "samples", "sampleIntervalSeconds"}
    assert set(body["info"]) == {"uptime", "ipAddress", "ethernet", "linkSpeed", "audioOutput", "audioCard", "pcmStream", "pcm", "mpdStatus", "mpdError", "softwareVersion"}
    assert body["info"]["pcm"] == {"sampleRate": "96 kHz", "encoding": "S32_LE", "channels": 2}
    assert len(body["samples"]) == 24 and body["sampleIntervalSeconds"] == 2
    assert set(body["samples"][0]) == {"receive", "send", "cpu", "temperature"}


def test_samples_advance_with_the_server_clock(client, clock):
    first = client.get("/api/device").json()["samples"]
    clock.advance(1.9)
    assert client.get("/api/device").json()["samples"] == first
    clock.advance(0.2)
    second = client.get("/api/device").json()["samples"]
    assert second[:-1] == first[1:] and second[-1] != first[-1]
