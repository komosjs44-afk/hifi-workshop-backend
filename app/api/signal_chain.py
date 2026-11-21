from fastapi import APIRouter, status

from app.schemas.player import MoveRequest
from app.schemas.signal_chain import AddModuleRequest, AddModuleResponse, BandPatch, Limits, ModulePatch, ProcessingRequest, SignalChainState
from app.services.signal_chain import LIMITS

from .deps import ServicesDep

router = APIRouter(prefix="/signal-chain", tags=["signal chain"])


@router.get("", response_model=SignalChainState)
async def state(services: ServicesDep):
    return services.signal_chain.state()


@router.get("/limits", response_model=Limits, summary="Parameter ranges enforced by the server")
async def limits():
    return LIMITS


@router.put("/processing", response_model=SignalChainState, summary="Master switch")
async def set_processing(body: ProcessingRequest, services: ServicesDep):
    return services.signal_chain.set_processing(body.enabled)


@router.post("/modules", response_model=AddModuleResponse, status_code=status.HTTP_201_CREATED)
async def add_module(body: AddModuleRequest, services: ServicesDep):
    module_id, chain = services.signal_chain.add_module(body.kind)
    return AddModuleResponse(module_id=module_id, state=chain)


@router.patch("/modules/{module_id}", response_model=SignalChainState, summary="Enable/disable, set gain or crossfeed amount")
async def patch_module(module_id: int, body: ModulePatch, services: ServicesDep):
    return services.signal_chain.patch_module(module_id, body)


@router.delete("/modules/{module_id}", response_model=SignalChainState)
async def remove_module(module_id: int, services: ServicesDep):
    return services.signal_chain.remove_module(module_id)


@router.post("/modules/{module_id}/move", response_model=SignalChainState)
async def move_module(module_id: int, body: MoveRequest, services: ServicesDep):
    return services.signal_chain.move_module(module_id, body.direction)


@router.post("/modules/{module_id}/bands", response_model=SignalChainState, status_code=status.HTTP_201_CREATED)
async def add_band(module_id: int, services: ServicesDep):
    return services.signal_chain.add_band(module_id)


@router.patch("/modules/{module_id}/bands/{band_id}", response_model=SignalChainState)
async def patch_band(module_id: int, band_id: int, body: BandPatch, services: ServicesDep):
    return services.signal_chain.patch_band(module_id, band_id, body)


@router.delete("/modules/{module_id}/bands/{band_id}", response_model=SignalChainState)
async def remove_band(module_id: int, band_id: int, services: ServicesDep):
    return services.signal_chain.remove_band(module_id, band_id)
