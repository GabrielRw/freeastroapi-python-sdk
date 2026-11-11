"""The retry policy (README "Retries")."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from freeastroapi import (
    OPERATIONS,
    SIDE_EFFECT_OPERATIONS,
    AsyncFreeAstro,
    FreeAstro,
    NetworkError,
    RateLimitError,
    RequestOptions,
    RetryConfig,
    ServerError,
    ValidationError,
)
from freeastroapi.client import is_side_effecting

Handler = Callable[[httpx.Request], httpx.Response]


def json_response(request: httpx.Request, data: object, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers, request=request)


def failing_then_ok(*failures: int, retry_after: str | None = None) -> tuple[Handler, list[httpx.Request]]:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if len(captured) <= len(failures):
            headers = {"retry-after": retry_after} if retry_after is not None else {}
            return json_response(request, {"detail": "failed"}, failures[len(captured) - 1], **headers)
        return json_response(request, {"ok": True})

    return handler, captured


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr("freeastroapi.client.time.sleep", recorded.append)
    return recorded


CHAT_BODY = {"message": "hello"}


def test_side_effect_operations_exist() -> None:
    assert SIDE_EFFECT_OPERATIONS <= {info.operation_id for info in OPERATIONS}
    assert is_side_effecting("POST", "/api/v2/vedic/chat")
    assert is_side_effecting("POST", "/api/v1/natal/calculate?include_minor=true")
    assert not is_side_effecting("POST", "/api/v2/vedic/chart")
    assert not is_side_effecting("GET", "/api/v1/natal/report/job_123")
    # Unknown paths: only GET, HEAD and OPTIONS count as safe to replay.
    assert is_side_effecting("POST", "/api/v9/unknown")
    assert not is_side_effecting("GET", "/api/v9/unknown")


def test_429_on_a_side_effecting_post_is_retried(sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(429, retry_after="1.5")
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        assert client.request("POST", "/api/v2/vedic/chat", json=CHAT_BODY) == {"ok": True}

    assert len(captured) == 2
    assert sleeps == [1.5]


def test_429_honours_retry_after_ms_in_the_body(sleeps: list[float]) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return json_response(request, {"error": "rate_limited", "retry_after_ms": 250}, 429)
        return json_response(request, {"ok": True})

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        client.request("POST", "/api/v2/vedic/chart", json={})

    assert sleeps == [0.25]


def test_429_with_a_long_retry_after_raises_at_once(sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(429, retry_after="120")
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RateLimitError) as caught:
            client.request("GET", "/api/v2/geo/search", params={"q": "Paris"})

    assert len(captured) == 1
    assert sleeps == []
    assert caught.value.retry_after == 120


def test_503_on_chat_is_not_retried_without_an_idempotency_key(sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(503)
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ServerError):
            client.vedic.chat(CHAT_BODY)

    assert len(captured) == 1


def test_503_on_chat_is_retried_with_an_idempotency_key(sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(503)
    options = RequestOptions(idempotency_key="chat-1")
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        assert client.vedic.chat(CHAT_BODY, options=options) == {"ok": True}

    assert len(captured) == 2
    assert all(request.headers["idempotency-key"] == "chat-1" for request in captured)


def test_503_on_chat_is_retried_with_explicit_opt_in(sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(503)
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        client.vedic.chat(CHAT_BODY, options=RequestOptions(retry=True))

    assert len(captured) == 2


def test_503_on_a_calculation_post_is_retried(sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(503, 502)
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        client.western.natal.insights({})

    assert len(captured) == 3
    assert len(sleeps) == 2


def test_network_errors_on_a_side_effecting_post_are_not_retried(sleeps: list[float]) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("offline", request=request)

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NetworkError):
            client.request("POST", "/api/v1/ai/generate", json={})
        assert attempts == 1
        with pytest.raises(NetworkError):
            client.request("POST", "/api/v2/vedic/chart", json={})

    assert attempts == 1 + 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_other_4xx_are_never_retried(status: int, sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(status)
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(Exception):  # noqa: B017 - the error family is tested elsewhere
            client.request("GET", "/api/v2/geo/search", options=RequestOptions(retry=True))

    assert len(captured) == 1


def test_backoff_is_exponential_with_full_jitter_and_capped(
    sleeps: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("freeastroapi.client.random.uniform", lambda low, high: high)
    handler, captured = failing_then_ok(*[503] * 6)
    with FreeAstro(api_key="test_key", retry=RetryConfig(retries=6), transport=httpx.MockTransport(handler)) as client:
        client.request("GET", "/api/v2/geo/search")

    assert sleeps == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]
    assert len(captured) == 7


def test_per_request_max_retries_and_disable(sleeps: list[float]) -> None:
    handler, captured = failing_then_ok(*[503] * 4)
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        assert client.request("GET", "/x", options=RequestOptions(max_retries=4)) == {"ok": True}
        assert len(captured) == 5

    handler, captured = failing_then_ok(429)
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RateLimitError):
            client.request("GET", "/x", options=RequestOptions(retry=False))
    assert len(captured) == 1


def test_error_body_code_and_message_follow_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, {"detail": {"error": "invalid_city", "message": "Unknown city"}}, 422)

    with FreeAstro(api_key="test_key", retry=None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValidationError) as caught:
            client.request("GET", "/x")

    assert str(caught.value) == "Unknown city"
    assert caught.value.code == "invalid_city"


@pytest.mark.asyncio
async def test_async_client_follows_the_same_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("freeastroapi.client.asyncio.sleep", no_sleep)
    handler, captured = failing_then_ok(503)
    async with AsyncFreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ServerError):
            await client.request("POST", "/api/v2/western/chat", json={})
        assert len(captured) == 1
        assert await client.request("POST", "/api/v2/western/chat", json={}, options=RequestOptions(retry=True)) == {
            "ok": True
        }
