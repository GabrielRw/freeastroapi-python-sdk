from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from freeastroapi import (
    AsyncFreeAstro,
    AuthenticationError,
    ConflictError,
    FreeAstro,
    FreeAstroError,
    NetworkError,
    PermissionError,
    RateLimitError,
    RequestOptions,
    RetryConfig,
    ServerError,
    TimeoutError,
    ValidationError,
)


def json_response(request: httpx.Request, data: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers, request=request)


def test_normalizes_base_url_merges_headers_and_protects_authentication_headers() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return json_response(request, {"ok": True})

    options = RequestOptions(headers={"Accept": "text/plain", "X-API-Key": "also-wrong", "X-Request": "one"})
    with FreeAstro(
        api_key="real_key",
        base_url="https://example.test/",
        headers={"X-SDK": "python", "X-API-Key": "wrong"},
        transport=httpx.MockTransport(handler),
    ) as client:
        client.request("GET", "/health", options=options)

    request = captured[0]
    assert request.url == "https://example.test/health"
    assert request.headers.get_list("x-api-key") == ["real_key"]
    assert request.headers["accept"] == "application/json"
    assert request.headers["x-sdk"] == "python"
    assert request.headers["x-request"] == "one"


def test_request_raw_preserves_response_and_parses_json_text_and_empty_content() -> None:
    responses = [
        (200, '{"ok":true}', "application/problem+json"),
        (200, "ready", "text/plain"),
        (204, "", "text/plain"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        status, body, content_type = responses.pop(0)
        return httpx.Response(
            status,
            text=body,
            headers={"content-type": content_type, "x-request-id": "req_123"},
            request=request,
        )

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        raw = client.request_raw("GET", "/json")
        text = client.request("GET", "/text")
        empty = client.request("GET", "/empty")

    assert raw.data == {"ok": True}
    assert raw.response.headers["x-request-id"] == "req_123"
    assert text == "ready"
    assert empty is None


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthenticationError),
        (403, PermissionError),
        (400, ValidationError),
        (422, ValidationError),
        (409, ConflictError),
        (429, RateLimitError),
        (503, ServerError),
        (418, FreeAstroError),
    ],
)
def test_maps_every_error_family(status: int, error_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"detail": "failed"}, status)

    with FreeAstro(api_key="test_key", retry=None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error_type):
            client.request("GET", "/failure")


def test_preserves_structured_error_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            request,
            {"message": "invalid chart", "code": "bad_chart", "field": "year"},
            422,
            **{"x-request-id": "req_456"},
        )

    with FreeAstro(api_key="test_key", retry=None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError) as caught:
            client.request("GET", "/failure")

    assert str(caught.value) == "invalid chart"
    assert caught.value.status == 422
    assert caught.value.code == "bad_chart"
    assert caught.value.request_id == "req_456"
    assert caught.value.details["field"] == "year"


def test_parses_numeric_and_http_date_retry_after_values() -> None:
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=60), usegmt=True)
    values = ["2.5", future]

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"detail": "wait"}, 429, **{"retry-after": values.pop(0)})

    with FreeAstro(api_key="test_key", retry=None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RateLimitError) as numeric:
            client.request("GET", "/limited")
        with pytest.raises(RateLimitError) as dated:
            client.request("GET", "/limited")

    assert numeric.value.retry_after == 2.5
    assert dated.value.retry_after is not None
    assert 55 < dated.value.retry_after <= 60


def test_retries_transient_network_and_timeout_failures_for_get() -> None:
    network_attempts = 0

    def network_handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_attempts
        network_attempts += 1
        if network_attempts == 1:
            raise httpx.ConnectError("offline", request=request)
        return json_response(request, {"ok": True})

    with FreeAstro(
        api_key="test_key",
        retry=RetryConfig(base_delay=0),
        transport=httpx.MockTransport(network_handler),
    ) as client:
        assert client.request("GET", "/unstable") == {"ok": True}

    timeout_attempts = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal timeout_attempts
        timeout_attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    with FreeAstro(
        api_key="test_key",
        retry=RetryConfig(retries=1, base_delay=0),
        transport=httpx.MockTransport(timeout_handler),
    ) as client:
        with pytest.raises(TimeoutError):
            client.request("GET", "/slow")

    assert network_attempts == 2
    assert timeout_attempts == 2


def test_respects_global_and_per_request_retry_controls() -> None:
    no_retry_attempts = 0

    def no_retry_handler(request: httpx.Request) -> httpx.Response:
        nonlocal no_retry_attempts
        no_retry_attempts += 1
        return json_response(request, {"detail": "busy"}, 503)

    with FreeAstro(api_key="test_key", retry=None, transport=httpx.MockTransport(no_retry_handler)) as client:
        with pytest.raises(ServerError):
            client.request("GET", "/busy")

    opt_in_attempts = 0

    def opt_in_handler(request: httpx.Request) -> httpx.Response:
        nonlocal opt_in_attempts
        opt_in_attempts += 1
        if opt_in_attempts == 1:
            return json_response(request, {"detail": "busy"}, 503)
        return json_response(request, {"ok": True})

    retry = RetryConfig(retries=1, base_delay=0)
    with FreeAstro(api_key="test_key", retry=retry, transport=httpx.MockTransport(opt_in_handler)) as client:
        result = client.request("POST", "/safe", options=RequestOptions(retry=True))

    assert no_retry_attempts == 1
    assert opt_in_attempts == 2
    assert result == {"ok": True}


def test_exhausted_transport_failure_becomes_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with FreeAstro(api_key="test_key", retry=None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NetworkError) as caught:
            client.request("GET", "/offline")

    assert isinstance(caught.value.__cause__, httpx.ConnectError)


def test_zero_timeout_is_forwarded_instead_of_replaced_by_the_default() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return json_response(request, {"ok": True})

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        client.request("GET", "/instant", options=RequestOptions(timeout=0))

    assert captured[0].extensions["timeout"] == {"connect": 0, "read": 0, "write": 0, "pool": 0}


def test_sync_context_manager_closes_transport() -> None:
    client = FreeAstro(api_key="test_key", transport=httpx.MockTransport(lambda request: json_response(request, {})))
    with client:
        assert not client._http.is_closed
    assert client._http.is_closed


@pytest.mark.asyncio
async def test_async_client_retries_and_closes_transport() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return json_response(request, {"detail": "busy"}, 503)
        return json_response(request, {"ok": True})

    client = AsyncFreeAstro(
        api_key="test_key",
        retry=RetryConfig(retries=1, base_delay=0),
        transport=httpx.MockTransport(handler),
    )
    async with client:
        assert await client.request("GET", "/unstable") == {"ok": True}
        assert not client._http.is_closed

    assert attempts == 2
    assert client._http.is_closed
