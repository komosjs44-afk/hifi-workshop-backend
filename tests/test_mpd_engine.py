import pytest

from app.adapters.mpd.engine import MpdAudioEngine, album_id, to_format
from app.errors import ConflictError, EngineError, EngineUnavailableError, NotFoundError
from app.schemas.player import SourceFormat

from .conftest import free_port
from .fake_mpd import MpdAck

WAV44, WAV48, TIDES, LOW = "test/sine-44k.wav", "test/sine-48k.wav", "albums/Quiet/01.flac", "albums/Quiet/02.flac"


@pytest.fixture
def engine(fake_mpd):
    return MpdAudioEngine("127.0.0.1", fake_mpd.port)


@pytest.fixture
def queued(fake_mpd):
    """Queue of three songs, first one selected and paused at 30 s."""
    ids = fake_mpd.fill(WAV44, WAV48, TIDES)
    fake_mpd.current, fake_mpd.state, fake_mpd.elapsed = ids[0], "pause", 30.0
    return ids


def current(engine):
    status = engine.status()
    return status.current_id, status.status, status.position


# ---- library ----
def test_library_maps_tags_and_untagged_files(engine):
    tracks = {track.id: track for track in engine.tracks()}
    assert list(tracks) == [TIDES, LOW, WAV44, WAV48]  # album artist, album, track number, file
    tides = tracks[TIDES]
    assert (tides.title, tides.artist, tides.album, tides.duration, tides.art) == ("Between the Tides", "Northbound", "Quiet Coordinates", 248, "")
    assert tracks[LOW].artist == "Northbound"  # first value of a multi-value tag
    wav = tracks[WAV44]
    assert (wav.title, wav.artist, wav.album, wav.duration) == ("sine-44k", "Unknown Artist", "test", 10)


def test_albums_group_tracks_with_stable_ids(engine):
    albums = engine.albums()
    assert [(album.title, album.artist, album.year) for album in albums] == [("Quiet Coordinates", "Northbound", 2024), ("test", "Unknown Artist", 0)]
    assert albums[0].id == album_id("Northbound", "Quiet Coordinates")
    assert {track.album_id for track in engine.tracks() if track.album == "test"} == {albums[1].id}


def test_library_is_cached_until_the_database_changes(engine, fake_mpd):
    engine.tracks()
    engine.albums()
    assert fake_mpd.log.count("listallinfo") == 1
    fake_mpd.songs.pop()
    fake_mpd.db_update += 1  # `mpc update` finished
    assert len(engine.tracks()) == 3 and fake_mpd.log.count("listallinfo") == 2


# ---- status ----
def test_status_of_an_empty_queue(engine):
    status = engine.status()
    assert (status.source, status.status, status.queue, status.current_id, status.position, status.format) == ("local", "stopped", (), None, 0.0, None)


def test_status_maps_queue_current_position_and_format(engine, queued):
    status = engine.status()
    assert [entry.id for entry in status.queue] == queued and status.queue[2].track.title == "Between the Tides"
    assert (status.current_id, status.status, status.position) == (queued[0], "paused", 30.0)
    assert status.format == SourceFormat(codec="WAV", bit_depth="16-bit", sample_rate="44.1 kHz")


def test_stopped_status_uses_the_song_format(engine, fake_mpd, queued):
    fake_mpd.current, fake_mpd.state = queued[1], "stop"
    status = engine.status()
    assert (status.position, status.format) == (0.0, SourceFormat(codec="WAV", bit_depth="24-bit", sample_rate="48 kHz"))


@pytest.mark.parametrize("audio, uri, expected", [
    ("96000:24:2", "a/b.flac", ("FLAC", "24-bit", "96 kHz")),
    ("176400:32:2", "x.wav", ("WAV", "32-bit", "176.4 kHz")),
    ("44100:f:2", "x.dsf", ("DSF", "32-bit float", "44.1 kHz")),
    ("44100:16:2", "http://stream", ("PCM", "16-bit", "44.1 kHz")),
])
def test_to_format(audio, uri, expected):
    assert to_format(audio, uri) == SourceFormat(codec=expected[0], bit_depth=expected[1], sample_rate=expected[2])
    assert to_format(None, uri) is None and to_format("garbage", uri) is None


def test_queue_is_read_only_when_its_version_changes(engine, fake_mpd, queued):
    engine.status()
    engine.status()
    assert fake_mpd.log.count("playlistinfo") == 1
    fake_mpd.fill(LOW)
    assert len(engine.status().queue) == 4 and fake_mpd.log.count("playlistinfo") == 2


def test_version_grows_on_changes_only(engine, fake_mpd, queued):
    first = engine.status().version
    fake_mpd.elapsed = 31.0  # position only
    assert engine.status().version == first
    fake_mpd.state = "play"  # changed by another client (mpc)
    second = engine.status().version
    assert second > first
    engine.pause()
    assert engine.status().version > second


def test_queue_is_reread_after_a_reconnect(engine, fake_mpd, queued):
    engine.status()
    fake_mpd.drop_next = 1
    engine.status()
    assert fake_mpd.log.count("playlistinfo") == 2


# ---- transport ----
def test_play_resumes_pause_and_restarts_from_stop(engine, fake_mpd, queued):
    engine.play()
    assert current(engine) == (queued[0], "playing", 30.0) and 'pause "0"' in fake_mpd.log
    engine.stop()
    assert current(engine) == (queued[0], "stopped", 0.0)
    engine.play()
    assert current(engine) == (queued[0], "playing", 0.0)


def test_play_item_and_unknown_item(engine, queued):
    engine.play(queued[2])
    assert current(engine) == (queued[2], "playing", 0.0)
    with pytest.raises(NotFoundError) as error:
        engine.play(999)
    assert error.value.code == "queue_item_not_found"


def test_play_without_selection_is_a_conflict(engine, fake_mpd):
    fake_mpd.fill(WAV44)
    with pytest.raises(ConflictError) as error:
        engine.play()
    assert error.value.code == "nothing_selected"


def test_pause_only_affects_playing(engine, fake_mpd, queued):
    fake_mpd.state = "stop"
    engine.pause()
    assert engine.status().status == "stopped"
    fake_mpd.state = "play"
    engine.pause()
    assert engine.status().status == "paused"


@pytest.mark.parametrize("state, expected", [("play", "playing"), ("pause", "paused"), ("stop", "stopped")])
def test_next_and_previous_keep_the_transport_status(engine, fake_mpd, queued, state, expected):
    fake_mpd.state = state
    engine.next()
    assert current(engine) == (queued[1], expected, 0.0)
    engine.previous()
    assert current(engine) == (queued[0], expected, 0.0)
    assert "next" not in fake_mpd.log and "previous" not in fake_mpd.log


def test_next_and_previous_at_the_edges(engine, fake_mpd, queued):
    with pytest.raises(ConflictError) as error:
        engine.previous()
    assert error.value.code == "no_previous_track"
    fake_mpd.current = queued[-1]
    with pytest.raises(ConflictError) as error:
        engine.next()
    assert error.value.code == "no_next_track"


@pytest.mark.parametrize("state, expected", [("play", "playing"), ("pause", "paused"), ("stop", "paused")])
def test_seek_in_every_state(engine, fake_mpd, queued, state, expected):
    fake_mpd.state = state
    engine.seek(5.25)
    assert current(engine) == (queued[0], expected, 5.25)


def test_seek_without_selection(engine, fake_mpd):
    with pytest.raises(ConflictError):
        engine.seek(1)


# ---- queue ----
def test_add_appends_or_inserts(engine, fake_mpd, queued):
    appended = engine.add(LOW)
    inserted = engine.add(WAV48, 1)
    assert [entry.id for entry in engine.status().queue] == [queued[0], inserted, queued[1], queued[2], appended]
    assert engine.status().status == "paused"  # adding does not touch playback


@pytest.mark.parametrize("track_id", ["missing.flac", "http://example.com/stream", "/etc/passwd", "file:///etc/passwd"])
def test_add_accepts_database_songs_only(engine, fake_mpd, track_id):
    with pytest.raises(NotFoundError) as error:
        engine.add(track_id)
    assert error.value.code == "track_not_found"
    assert not any(line.startswith("addid") for line in fake_mpd.log)


def test_remove_other_item_keeps_playback(engine, queued):
    engine.remove(queued[1])
    assert [entry.id for entry in engine.status().queue] == [queued[0], queued[2]]
    assert current(engine) == (queued[0], "paused", 30.0)


@pytest.mark.parametrize("state, expected", [("play", "playing"), ("pause", "paused"), ("stop", "stopped")])
def test_remove_current_continues_with_the_following_item(engine, fake_mpd, queued, state, expected):
    fake_mpd.state = state
    engine.remove(queued[0])
    assert current(engine) == (queued[1], expected, 0.0)


def test_remove_last_current_item_stops(engine, fake_mpd, queued):
    fake_mpd.current, fake_mpd.state = queued[-1], "play"
    engine.remove(queued[-1])
    assert current(engine) == (None, "stopped", 0.0)


def test_remove_unknown_item(engine, queued):
    with pytest.raises(NotFoundError):
        engine.remove(999)


def test_move(engine, queued):
    engine.move(queued[0], 2)
    status = engine.status()
    assert [entry.id for entry in status.queue] == [queued[1], queued[2], queued[0]] and status.current_id == queued[0]
    with pytest.raises(ConflictError) as error:
        engine.move(queued[0], 3)
    assert error.value.code == "queue_move_out_of_range"
    with pytest.raises(NotFoundError):
        engine.move(999, 0)


def test_clear(engine, queued):
    engine.clear()
    assert current(engine) == (None, "stopped", 0.0) and engine.status().queue == ()


# ---- errors ----
def test_unreachable_mpd(fake_mpd):
    engine = MpdAudioEngine("127.0.0.1", free_port(), timeout=0.2)  # Windows waits for the timeout on refused ports
    for call in (engine.status, engine.tracks, engine.play, engine.clear):
        with pytest.raises(EngineUnavailableError) as error:
            call()
        assert (error.value.status_code, error.value.code) == (503, "mpd_unavailable")
    info = engine.info()
    assert (info.kind, info.connected, info.simulated) == ("mpd", False, False) and "not reachable" in info.description


def test_mpd_errors_other_than_missing_become_502(engine, fake_mpd, queued):
    def failing_stop():
        raise MpdAck(52, "system error")

    fake_mpd.cmd_stop = failing_stop
    with pytest.raises(EngineError) as error:
        engine.stop()
    assert (error.value.status_code, error.value.code) == (502, "mpd_error") and "system error" in error.value.message


def test_info_when_connected(engine, fake_mpd):
    info = engine.info()
    assert (info.kind, info.connected, info.simulated) == ("mpd", True, False)
    assert "0.24.4" in info.description and "DAC" not in info.description
    fake_mpd.status_error = "Failed to open audio output"
    assert "Failed to open audio output" in engine.info().description
