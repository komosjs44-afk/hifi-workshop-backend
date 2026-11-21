from fastapi import APIRouter

from app.schemas.library import Album, AlbumDetail, Artist, ArtistDetail, Library, Track

from .deps import ServicesDep

router = APIRouter(prefix="/library", tags=["library"])


@router.get("", response_model=Library, summary="All albums and tracks")
async def library(services: ServicesDep):
    return services.player.library()


@router.get("/albums", response_model=list[Album])
async def albums(services: ServicesDep):
    return services.player.library().albums


@router.get("/albums/{album_id}", response_model=AlbumDetail, summary="One album with its tracks")
async def album(album_id: str, services: ServicesDep):
    return services.player.album(album_id)


@router.get("/artists", response_model=list[Artist])
async def artists(services: ServicesDep):
    return services.player.artists()


@router.get("/artists/{name}", response_model=ArtistDetail, summary="One artist with their albums")
async def artist(name: str, services: ServicesDep):
    return services.player.artist(name)


@router.get("/tracks", response_model=list[Track])
async def tracks(services: ServicesDep):
    return services.player.library().tracks


@router.get("/tracks/{track_id}", response_model=Track)
async def track(track_id: str, services: ServicesDep):
    return services.player.track(track_id)
