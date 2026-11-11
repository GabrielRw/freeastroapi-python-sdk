from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from freeastroapi import (
    AsyncFreeAstro,
    AuthenticationError,
    FreeAstro,
    RateLimitError,
    RequestOptions,
    RetryConfig,
    ServerError,
    ValidationError,
    WesternSignRequest,
)


def json_response(request: httpx.Request, data: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers, request=request)


def test_api_key_is_required() -> None:
    with pytest.raises(ValueError, match="api_key is required"):
        FreeAstro(api_key="")


def test_geo_search_serializes_query_and_authentication() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return json_response(request, {"results": [], "count": 0})

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        result = client.geo.search("Paris", limit=3, country="FR")

    assert result.count == 0
    assert captured[0].url == "https://api.freeastroapi.com/api/v2/geo/search?q=Paris&limit=3&country=FR"
    assert captured[0].headers["x-api-key"] == "test_key"


def test_western_sign_serializes_model() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return json_response(
            request,
            {
                "point": "Sun",
                "sign": "Gemini",
                "sign_id": "gemini",
                "degree": 12,
                "abs_pos": 72,
                "house": 10,
                "interpretation": None,
            },
        )

    birth = WesternSignRequest(year=1990, month=6, day=15, city="Paris")
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        result = client.western.signs.sun(birth)

    assert result.sign_id == "gemini"
    assert json.loads(captured[0].content)["city"] == "Paris"


def test_get_retries_and_honors_retry_after() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return json_response(request, {"detail": "slow down"}, 429, **{"retry-after": "0"})
        return json_response(request, {"results": [], "count": 0})

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        client.geo.search("Paris")

    assert attempts == 2


def test_calculation_post_retries_server_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("freeastroapi.client.time.sleep", sleeps.append)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return json_response(request, {"detail": "busy"}, 503)

    birth = WesternSignRequest(year=1990, month=6, day=15, city="Paris")
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ServerError, match="busy"):
            client.western.signs.sun(birth)

    assert attempts == 3
    assert len(sleeps) == 2
    assert 0 <= sleeps[0] <= 0.5 and 0 <= sleeps[1] <= 1.0


def test_post_retries_with_idempotency_key() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if len(captured) == 1:
            return json_response(request, {"detail": "busy"}, 503)
        return json_response(
            request,
            {
                "point": "Sun",
                "sign": "Gemini",
                "sign_id": "gemini",
                "degree": 12,
                "abs_pos": 72,
                "house": 10,
                "interpretation": None,
            },
        )

    birth = WesternSignRequest(year=1990, month=6, day=15, city="Paris")
    retry = RetryConfig(base_delay=0)
    options = RequestOptions(idempotency_key="birth-123", retry=retry)
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        client.western.signs.sun(birth, options=options)

    assert len(captured) == 2
    assert all(request.headers["idempotency-key"] == "birth-123" for request in captured)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, AuthenticationError), (422, ValidationError), (429, RateLimitError)],
)
def test_typed_errors(status: int, error_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"detail": "request failed"}, status)

    with FreeAstro(api_key="test_key", retry=None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error_type):
            client.geo.search("Paris")


def test_request_model_requires_a_location() -> None:
    with pytest.raises(PydanticValidationError, match="provide city or both lat and lng"):
        WesternSignRequest(year=1990, month=6, day=15)


def test_generic_request_escape_hatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"ok": request.url.params["enabled"] == "true"})

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        result = client.request("GET", "/api/v1/custom", params={"enabled": "true"})

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_async_client_uses_the_same_resources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"results": [], "count": 0})

    async with AsyncFreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        result = await client.geo.search("Paris")

    assert result.count == 0
