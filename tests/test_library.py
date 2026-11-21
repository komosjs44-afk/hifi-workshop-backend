from .conftest import error_code


def test_library_matches_the_frontend_shape(client):
    body = client.get("/api/library").json()
    assert len(body["albums"]) == 18 and len(body["tracks"]) == 61
    assert set(body["albums"][0]) == {"id", "title", "artist", "year", "art"}
    assert set(body["tracks"][0]) == {"id", "title", "artist", "album", "albumId", "duration", "art"}
    assert body["tracks"][0]["id"] == "track-001"


def test_album_and_track_lists(client):
    assert len(client.get("/api/library/albums").json()) == 18
    assert len(client.get("/api/library/tracks").json()) == 61


def test_album_detail_lists_its_tracks(client):
    body = client.get("/api/library/albums/quiet").json()
    assert body["title"] == "Quiet Coordinates"
    assert [track["title"] for track in body["tracks"]] == ["Between the Tides", "After the Rain", "Small Hours", "Where the Water Ends", "A Place to Begin"]


def test_artists(client):
    artists = client.get("/api/library/artists").json()
    assert len(artists) == 8
    northbound = next(artist for artist in artists if artist["name"] == "Northbound")
    assert northbound == {"name": "Northbound", "albumCount": 3, "trackCount": 12}
    detail = client.get("/api/library/artists/Northbound").json()
    assert [album["id"] for album in detail["albums"]] == ["quiet", "still", "distance"]


def test_track_detail(client):
    assert client.get("/api/library/tracks/track-002").json()["title"] == "Soft Geometry"


def test_unknown_ids_are_404(client):
    for path, code in (("/api/library/albums/nope", "album_not_found"), ("/api/library/artists/Nobody", "artist_not_found"), ("/api/library/tracks/track-999", "track_not_found")):
        response = client.get(path)
        assert response.status_code == 404 and error_code(response) == code
