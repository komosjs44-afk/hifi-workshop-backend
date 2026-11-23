"""Domain errors. Each maps to one HTTP status and a stable machine-readable code."""
from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(DomainError):
    """The addressed track, queue item, module or band does not exist."""
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    """The request is well-formed but the current state does not allow it."""
    status_code = 409
    code = "conflict"


class InvalidRequestError(DomainError):
    """A value is outside what the current resource accepts."""
    status_code = 422
    code = "invalid_request"


class NotSupportedError(DomainError):
    """The configured engine cannot do this (yet)."""
    status_code = 501
    code = "not_supported"


class EngineError(DomainError):
    """The audio engine (MPD) was reached but refused or failed the command."""
    status_code = 502
    code = "engine_error"


class EngineUnavailableError(DomainError):
    """The audio engine (MPD) cannot be reached. Retrying later may succeed."""
    status_code = 503
    code = "engine_unavailable"
