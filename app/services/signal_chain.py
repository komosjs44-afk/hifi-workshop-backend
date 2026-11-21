"""The signal chain configuration. It is owned here and handed to the DSP engine after every change."""
from __future__ import annotations

from app.adapters.base import DspEngine
from app.errors import ConflictError, InvalidRequestError, NotFoundError
from app.schemas.signal_chain import (
    CROSSFEED_MAX, CROSSFEED_MIN, EQ_MAX_BANDS, FREQUENCY_MAX, FREQUENCY_MIN, GAIN_MAX, GAIN_MIN, Q_MAX, Q_MIN,
    BandPatch, CrossfeedModule, EqBand, EqModule, GainModule, Limits, ModulePatch, Range, SignalChainState,
)

_DEFAULT_BANDS = ((100.0, 0.0, 1.0), (1000.0, 0.0, 1.0), (8000.0, 0.0, 1.0))
_NEW_BAND = (1000.0, 0.0, 1.0)
LIMITS = Limits(
    gain=Range(min=GAIN_MIN, max=GAIN_MAX), frequency=Range(min=FREQUENCY_MIN, max=FREQUENCY_MAX),
    q=Range(min=Q_MIN, max=Q_MAX), crossfeed=Range(min=CROSSFEED_MIN, max=CROSSFEED_MAX), eq_bands=EQ_MAX_BANDS,
)


class SignalChainService:
    def __init__(self, dsp: DspEngine):
        self._dsp = dsp
        self._revision = 0
        self.reset()

    def reset(self) -> None:
        self._next_id = 1
        self._processing = False
        self._modules: list[GainModule | EqModule | CrossfeedModule] = []
        self._revision += 1

    def state(self) -> SignalChainState:
        return SignalChainState(revision=self._revision, processing=self._processing, modules=[module.model_copy(deep=True) for module in self._modules])

    def _commit(self) -> SignalChainState:
        self._revision += 1
        state = self.state()
        self._dsp.apply(state)
        return state

    def _id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _band(self, values: tuple[float, float, float]) -> EqBand:
        return EqBand(id=self._id(), frequency=values[0], gain=values[1], q=values[2])

    def _module(self, module_id: int):
        module = next((item for item in self._modules if item.id == module_id), None)
        if module is None:
            raise NotFoundError(f"Module {module_id} does not exist.", "module_not_found")
        return module

    def _eq(self, module_id: int) -> EqModule:
        module = self._module(module_id)
        if not isinstance(module, EqModule):
            raise InvalidRequestError(f"Module {module_id} is a {module.kind} module and has no EQ bands.", "not_an_eq_module")
        return module

    # ---- commands ----
    def set_processing(self, enabled: bool) -> SignalChainState:
        self._processing = enabled
        return self._commit()

    def add_module(self, kind: str) -> tuple[int, SignalChainState]:
        module_id = self._id()
        if kind == "gain":
            module = GainModule(id=module_id, enabled=True, gain=0.0)
        elif kind == "crossfeed":
            module = CrossfeedModule(id=module_id, enabled=True, amount=30.0)
        else:
            module = EqModule(id=module_id, enabled=True, bands=[self._band(values) for values in _DEFAULT_BANDS])
        self._modules.append(module)
        return module_id, self._commit()

    def remove_module(self, module_id: int) -> SignalChainState:
        self._modules.remove(self._module(module_id))
        return self._commit()

    def move_module(self, module_id: int, direction: int) -> SignalChainState:
        index = self._modules.index(self._module(module_id))
        target = index + direction
        if not 0 <= target < len(self._modules):
            raise ConflictError("The module cannot move further in that direction.", "module_move_out_of_range")
        self._modules[index], self._modules[target] = self._modules[target], self._modules[index]
        return self._commit()

    def patch_module(self, module_id: int, patch: ModulePatch) -> SignalChainState:
        module = self._module(module_id)
        if patch.gain is not None and not isinstance(module, GainModule):
            raise InvalidRequestError(f"Module {module_id} is a {module.kind} module; 'gain' applies to gain modules only.", "parameter_not_applicable")
        if patch.amount is not None and not isinstance(module, CrossfeedModule):
            raise InvalidRequestError(f"Module {module_id} is a {module.kind} module; 'amount' applies to crossfeed modules only.", "parameter_not_applicable")
        if patch.enabled is not None:
            module.enabled = patch.enabled
        if patch.gain is not None:
            module.gain = patch.gain
        if patch.amount is not None:
            module.amount = patch.amount
        return self._commit()

    def add_band(self, module_id: int) -> SignalChainState:
        module = self._eq(module_id)
        if len(module.bands) >= EQ_MAX_BANDS:
            raise ConflictError(f"An EQ module holds at most {EQ_MAX_BANDS} bands.", "band_limit_reached")
        module.bands.append(self._band(_NEW_BAND))
        return self._commit()

    def _find_band(self, module: EqModule, band_id: int) -> EqBand:
        band = next((item for item in module.bands if item.id == band_id), None)
        if band is None:
            raise NotFoundError(f"Band {band_id} does not exist in module {module.id}.", "band_not_found")
        return band

    def remove_band(self, module_id: int, band_id: int) -> SignalChainState:
        module = self._eq(module_id)
        band = self._find_band(module, band_id)
        if len(module.bands) == 1:
            raise ConflictError("An EQ module keeps at least one band. Remove or disable the module instead.", "last_band")
        module.bands.remove(band)
        return self._commit()

    def patch_band(self, module_id: int, band_id: int, patch: BandPatch) -> SignalChainState:
        band = self._find_band(self._eq(module_id), band_id)
        for name in ("frequency", "gain", "q"):
            value = getattr(patch, name)
            if value is not None:
                setattr(band, name, value)
        return self._commit()
