from fastapi import APIRouter

from app.schemas.device import DeviceState

from .deps import ServicesDep

router = APIRouter(prefix="/device", tags=["device"])


@router.get("", response_model=DeviceState, summary="Device, audio format, network and system values")
async def device(services: ServicesDep):
    return services.probe.read()
