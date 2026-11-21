from fastapi import APIRouter

from app.config import VERSION
from app.schemas.system import AppState, Health, SystemStatus

from .deps import ServicesDep

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Health, summary="Liveness check")
async def health(services: ServicesDep):
    return Health(status="ok", version=VERSION, server_id=services.server_id)


@router.get("/system", response_model=SystemStatus, summary="Data source and component status")
async def system(services: ServicesDep):
    return services.system()


@router.get("/state", response_model=AppState, summary="Everything a client polls, in one response")
async def state(services: ServicesDep):
    return services.app_state()
