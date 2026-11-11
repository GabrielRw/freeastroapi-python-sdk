from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class FreeAstroError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id
        self.details = details


class AuthenticationError(FreeAstroError):
    pass


class PermissionError(FreeAstroError):
    pass


class ValidationError(FreeAstroError):
    pass


class ConflictError(FreeAstroError):
    pass


class RateLimitError(FreeAstroError):
    """HTTP 429. ``retry_after`` is the suggested wait in seconds (``Retry-After`` header or
    ``retry_after_ms`` in the body), or ``None``."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(FreeAstroError):
    pass


class NetworkError(FreeAstroError):
    pass


class TimeoutError(NetworkError):
    pass


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {"detail": payload}


def retry_after(response: httpx.Response) -> float | None:
    """Seconds to wait before retrying: the ``Retry-After`` header (seconds or an HTTP date),
    else ``retry_after_ms`` in the error body."""
    seconds = _retry_after_seconds(response.headers.get("retry-after"))
    if seconds is not None:
        return seconds
    milliseconds = _payload(response).get("retry_after_ms")
    if isinstance(milliseconds, int | float) and not isinstance(milliseconds, bool):
        return max(0.0, milliseconds / 1000)
    return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _validation_message(detail: Any) -> str | None:
    """``"body.year: Field required"`` for the first item of an ``HTTPValidationError``."""
    if not isinstance(detail, list) or not detail or not isinstance(detail[0], dict):
        return None
    first = detail[0]
    message = _text(first.get("msg"))
    location = first.get("loc")
    if message and isinstance(location, list) and location:
        return f"{'.'.join(str(part) for part in location)}: {message}"
    return message


def error_from_response(response: httpx.Response) -> FreeAstroError:
    """The typed error for a non-2xx response.

    Error bodies follow the spec's ``ErrorResponse``: ``detail`` is a message or an object with
    an ``error`` code and a ``message``; gateway errors carry a top-level ``error`` code.
    """
    payload = _payload(response)
    detail = payload.get("detail")
    detail_object: dict[str, Any] = detail if isinstance(detail, dict) else {}

    message = (
        _text(detail)
        or _text(detail_object.get("message"))
        or _text(payload.get("message"))
        or _text(payload.get("error"))
        or _validation_message(detail)
        or response.reason_phrase
        or f"HTTP {response.status_code}"
    )
    code = _text(payload.get("code")) or _text(payload.get("error")) or _text(detail_object.get("error"))
    request_id = _text(response.headers.get("x-request-id")) or _text(payload.get("trace_id"))

    def error(error_type: type[FreeAstroError]) -> FreeAstroError:
        return error_type(
            message,
            status=response.status_code,
            code=code,
            request_id=request_id,
            details=payload,
        )

    if response.status_code == 401:
        return error(AuthenticationError)
    if response.status_code == 403:
        return error(PermissionError)
    if response.status_code in (400, 422):
        return error(ValidationError)
    if response.status_code == 409:
        return error(ConflictError)
    if response.status_code == 429:
        return RateLimitError(
            message,
            retry_after=retry_after(response),
            status=response.status_code,
            code=code,
            request_id=request_id,
            details=payload,
        )
    if response.status_code >= 500:
        return error(ServerError)
    return error(FreeAstroError)
