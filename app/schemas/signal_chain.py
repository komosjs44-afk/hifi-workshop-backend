from typing import Annotated, Literal, Union

from pydantic import Field, StrictBool, model_validator

from .common import CamelModel

# Parameter limits. These must stay equal to `limits` in the frontend's src/api/types.ts.
GAIN_MIN, GAIN_MAX = -12.0, 12.0
FREQUENCY_MIN, FREQUENCY_MAX = 20.0, 20000.0
Q_MIN, Q_MAX = 0.1, 10.0
CROSSFEED_MIN, CROSSFEED_MAX = 0.0, 100.0
EQ_MAX_BANDS = 8

Gain = Annotated[float, Field(ge=GAIN_MIN, le=GAIN_MAX, allow_inf_nan=False)]
Frequency = Annotated[float, Field(ge=FREQUENCY_MIN, le=FREQUENCY_MAX, allow_inf_nan=False)]
Q = Annotated[float, Field(ge=Q_MIN, le=Q_MAX, allow_inf_nan=False)]
Amount = Annotated[float, Field(ge=CROSSFEED_MIN, le=CROSSFEED_MAX, allow_inf_nan=False)]
ModuleKind = Literal["gain", "eq", "crossfeed"]


class EqBand(CamelModel):
    id: int
    frequency: Frequency
    gain: Gain
    q: Q


class GainModule(CamelModel):
    id: int
    enabled: bool
    kind: Literal["gain"] = "gain"
    gain: Gain


class EqModule(CamelModel):
    id: int
    enabled: bool
    kind: Literal["eq"] = "eq"
    bands: list[EqBand] = Field(max_length=EQ_MAX_BANDS)


class CrossfeedModule(CamelModel):
    id: int
    enabled: bool
    kind: Literal["crossfeed"] = "crossfeed"
    amount: Amount


ChainModule = Annotated[Union[GainModule, EqModule, CrossfeedModule], Field(discriminator="kind")]


class SignalChainState(CamelModel):
    """Frontend SignalChainState plus `revision`."""
    revision: int
    processing: bool
    modules: list[ChainModule]


class Range(CamelModel):
    min: float
    max: float


class Limits(CamelModel):
    gain: Range
    frequency: Range
    q: Range
    crossfeed: Range
    eq_bands: int


class ProcessingRequest(CamelModel):
    enabled: StrictBool


class AddModuleRequest(CamelModel):
    kind: ModuleKind


class AddModuleResponse(CamelModel):
    module_id: int
    state: SignalChainState


class ModulePatch(CamelModel):
    """Any subset; `gain` applies to gain modules and `amount` to crossfeed modules only."""
    enabled: StrictBool | None = None
    gain: Gain | None = None
    amount: Amount | None = None

    @model_validator(mode="after")
    def _not_empty(self):
        if self.enabled is None and self.gain is None and self.amount is None:
            raise ValueError("at least one of enabled, gain, amount is required")
        return self


class BandPatch(CamelModel):
    frequency: Frequency | None = None
    gain: Gain | None = None
    q: Q | None = None

    @model_validator(mode="after")
    def _not_empty(self):
        if self.frequency is None and self.gain is None and self.q is None:
            raise ValueError("at least one of frequency, gain, q is required")
        return self
