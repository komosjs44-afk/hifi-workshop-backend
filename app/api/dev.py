"""Development helpers for the mock engine. Mounted only when the dev API is enabled."""
from fastapi import APIRouter

from app.schemas.player import PlaybackState, SourceRequest
from app.schemas.system import AppState

from .deps import ServicesDep

router = APIRouter(prefix="/dev", tags=["development"])


@router.post("/source", response_model=PlaybackState, summary="Preview an input source scenario")
async def set_source(body: SourceRequest, services: ServicesDep):
    return services.player.set_source(body.source)


@router.post("/reset", response_model=AppState, summary="Restore the initial mock state")
async def reset(services: ServicesDep):
    services.reset()
    return services.app_state()
