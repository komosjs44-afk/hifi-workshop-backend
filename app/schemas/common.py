from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """snake_case in Python, camelCase in JSON; unknown request fields are rejected."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ErrorBody(CamelModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(CamelModel):
    error: ErrorBody
