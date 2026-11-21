from fastapi import APIRouter, status

from app.schemas.player import MoveRequest, PlaybackState, Queue, ReplaceQueueRequest, TrackRequest

from .deps import ServicesDep

# Queue changes can move the current track, so every command answers with the full PlaybackState.
router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("", response_model=Queue)
async def queue(services: ServicesDep):
    return services.player.queue()


@router.put("", response_model=PlaybackState, summary="Replace the queue (e.g. with an album) and play its first track")
async def replace(body: ReplaceQueueRequest, services: ServicesDep):
    return services.player.replace_queue(body.track_ids)


@router.delete("", response_model=PlaybackState, summary="Clear the queue and stop")
async def clear(services: ServicesDep):
    return services.player.clear()


@router.post("/items", response_model=PlaybackState, status_code=status.HTTP_201_CREATED, summary="Append a track")
async def enqueue(body: TrackRequest, services: ServicesDep):
    return services.player.enqueue(body.track_id)


@router.delete("/items/{item_id}", response_model=PlaybackState)
async def remove(item_id: int, services: ServicesDep):
    return services.player.remove(item_id)


@router.post("/items/{item_id}/move", response_model=PlaybackState, summary="Move one position up (-1) or down (1)")
async def move(item_id: int, body: MoveRequest, services: ServicesDep):
    return services.player.move(item_id, body.direction)


@router.post("/items/{item_id}/play", response_model=PlaybackState, summary="Jump to a queue item and play it")
async def play_item(item_id: int, services: ServicesDep):
    return services.player.play_queue_item(item_id)
