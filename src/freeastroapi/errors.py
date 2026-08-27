from __future__ import annotations

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
    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(FreeAstroError):
    pass


class NetworkError(FreeAstroError):
    pass


class TimeoutError(NetworkError):
    pass


def error_from_response(response: httpx.Response) -> FreeAstroError:
    try:
        payload: dict[str, Any] = response.json()
    except (ValueError, TypeError):
        payload = {}

    detail = payload.get("detail")
    message_value = (
        detail
        if isinstance(detail, str) and detail.strip()
        else payload.get("message") or payload.get("error") or response.reason_phrase or f"HTTP {response.status_code}"
    )
    message = message_value if isinstance(message_value, str) else str(message_value)
    code_value = payload.get("code")
    code = code_value if isinstance(code_value, str) else None
    request_id_value = response.headers.get("x-request-id") or payload.get("trace_id")
    request_id = request_id_value if isinstance(request_id_value, str) else None

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
        retry_after_header = response.headers.get("retry-after")
        try:
            retry_after = float(retry_after_header) if retry_after_header is not None else None
        except ValueError:
            retry_after = None
        return RateLimitError(
            message,
            retry_after=retry_after,
            status=response.status_code,
            code=code,
            request_id=request_id,
            details=payload,
        )
    if response.status_code >= 500:
        return error(ServerError)
    return error(FreeAstroError)
