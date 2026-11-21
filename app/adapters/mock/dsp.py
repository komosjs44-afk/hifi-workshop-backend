from app.adapters.base import ComponentInfo, DspEngine
from app.schemas.signal_chain import SignalChainState


class MockDspEngine(DspEngine):
    """Remembers the last chain it was given. Nothing processes audio with it."""

    def __init__(self) -> None:
        self.last_applied: SignalChainState | None = None

    def info(self) -> ComponentInfo:
        return ComponentInfo("mock", connected=False, simulated=True,
                             description="Signal chain settings are stored in memory only. No DSP (CamillaDSP) is running and no audio is processed.")

    def apply(self, chain: SignalChainState) -> None:
        self.last_applied = chain
