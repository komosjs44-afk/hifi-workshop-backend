from .common import CamelModel


class Album(CamelModel):
    id: str
    title: str
    artist: str
    year: int
    art: str


class Track(CamelModel):
    id: str
    title: str
    artist: str
    album: str
    album_id: str
    duration: int  # seconds
    art: str


class Library(CamelModel):
    """Same shape as the frontend LibraryState."""
    albums: list[Album]
    tracks: list[Track]


class AlbumDetail(Album):
    tracks: list[Track]


class Artist(CamelModel):
    name: str
    album_count: int
    track_count: int


class ArtistDetail(Artist):
    albums: list[Album]
