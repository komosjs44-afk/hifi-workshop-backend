from fastapi import APIRouter

from app.schemas.player import PlaybackState, SeekRequest, TrackRequest

from .deps import ServicesDep

# Every command answers with the resulting PlaybackState.
router = APIRouter(prefix="/player", tags=["player"])


@router.get("", response_model=PlaybackState, summary="Current playback state, position included")
async def state(services: ServicesDep):
    return services.player.state()


@router.post("/play", response_model=PlaybackState)
async def play(services: ServicesDep):
    return services.player.play()


@router.post("/pause", response_model=PlaybackState)
async def pause(services: ServicesDep):
    return services.player.pause()


@router.post("/stop", response_model=PlaybackState)
async def stop(services: ServicesDep):
    return services.player.stop()


@router.post("/next", response_model=PlaybackState)
async def next_track(services: ServicesDep):
    return services.player.next()


@router.post("/previous", response_model=PlaybackState)
async def previous_track(services: ServicesDep):
    return services.player.previous()


@router.post("/seek", response_model=PlaybackState)
async def seek(body: SeekRequest, services: ServicesDep):
    return services.player.seek(body.seconds)


@router.post("/play-track", response_model=PlaybackState, summary="Select a library track and play it")
async def play_track(body: TrackRequest, services: ServicesDep):
    return services.player.play_track(body.track_id)
