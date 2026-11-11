from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Generic, Literal, TypeAlias, TypeVar

import httpx

from ._generated import OPERATIONS, AsyncGeneratedResources, GeneratedResources
from .errors import NetworkError, TimeoutError, error_from_response, retry_after
from .resources import (
    AsyncGeoResource,
    AsyncMoonResource,
    AsyncSkyEventsResource,
    AsyncWesternResource,
    GeoResource,
    MoonResource,
    SkyEventsResource,
    WesternResource,
)

T = TypeVar("T")

#: How to read a successful body: ``auto`` parses JSON content types and returns other bodies
#: as text, ``text`` always returns ``str`` and ``bytes`` returns ``bytes``.
ResponseType: TypeAlias = Literal["auto", "text", "bytes"]

DEFAULT_BASE_URL = "https://api.freeastroapi.com"
DEFAULT_RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Operations with side effects (a paid report job, AI generation, chat turns, stored timelines).
#: HTTP 408 and 5xx responses, network errors and timeouts are retried for them only when the
#: request carries an idempotency key (``RequestOptions(idempotency_key=...)``) or opts in with
#: ``RequestOptions(retry=True)``. Every other operation is retried on those failures, and every
#: operation, these included, is retried on HTTP 429.
SIDE_EFFECT_OPERATIONS: frozenset[str] = frozenset(
    {
        "v1_natal_calculate",
        "v1_ai_generate",
        "v2_vedic_chat",
        "v2_western_chat",
        "v2_vedic_qa",
        "v1_western_transits_timeline",
        "v1_western_transits_insights",
    }
)


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Retry settings. ``retries`` is the number of retries after the first attempt.

    Waits use exponential backoff with full jitter: a random delay between 0 and
    ``min(max_delay, base_delay * 2**attempt)``, unless the response says how long to wait
    (``Retry-After`` or ``retry_after_ms``). A suggested wait longer than ``max_retry_after``
    seconds is not waited for: the error is raised at once (``RateLimitError.retry_after``).
    """

    retries: int = 2
    base_delay: float = 0.5
    max_delay: float = 8.0
    statuses: frozenset[int] = DEFAULT_RETRY_STATUSES
    max_retry_after: float = 30.0


DEFAULT_RETRY = RetryConfig()


@dataclass(frozen=True, slots=True)
class RequestOptions:
    """Per-request options.

    ``retry=False`` disables retries; ``retry=True`` (or a :class:`RetryConfig`, which also
    replaces the client's settings) opts a side-effecting operation in to retries on 408, 5xx
    and network errors. ``max_retries`` overrides the number of retries only. An
    ``idempotency_key`` is sent as ``Idempotency-Key`` and also makes those retries safe.
    """

    headers: Mapping[str, str] = field(default_factory=dict)
    idempotency_key: str | None = None
    timeout: float | None = None
    retry: bool | RetryConfig | None = None
    max_retries: int | None = None


@dataclass(frozen=True, slots=True)
class SDKResponse(Generic[T]):
    data: T
    response: httpx.Response


@dataclass(frozen=True, slots=True)
class _RetryPlan:
    config: RetryConfig
    # Whether 408, 5xx, network errors and timeouts may be retried (429 always may).
    replay_safe: bool

    def backoff(self, attempt: int) -> float:
        return random.uniform(0, min(self.config.max_delay, self.config.base_delay * 2**attempt))

    def exception_delay(self, attempt: int) -> float | None:
        """Seconds to wait before retrying after a network error or timeout, or ``None``."""
        if not self.replay_safe or attempt >= self.config.retries:
            return None
        return self.backoff(attempt)

    def response_delay(self, response: httpx.Response, attempt: int) -> float | None:
        """Seconds to wait before retrying after an error response, or ``None`` to raise."""
        status = response.status_code
        if attempt >= self.config.retries or status not in self.config.statuses:
            return None
        if status != 429 and not self.replay_safe:
            return None
        suggested = retry_after(response)
        if suggested is None:
            return self.backoff(attempt)
        return suggested if suggested <= self.config.max_retry_after else None


@lru_cache(maxsize=1)
def _operation_patterns() -> tuple[tuple[str, re.Pattern[str], str], ...]:
    def pattern(template: str) -> re.Pattern[str]:
        return re.compile("^" + re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(template.rstrip("/"))) + "/?$")

    return tuple((info.method, pattern(info.path), info.operation_id) for info in OPERATIONS)


def is_side_effecting(method: str, path: str) -> bool:
    """Whether a request is a side-effecting operation (:data:`SIDE_EFFECT_OPERATIONS`).

    Requests that match no known operation count as side-effecting unless they use GET, HEAD
    or OPTIONS.
    """
    method = method.upper()
    path = httpx.URL(path).path
    matches = [op_id for verb, pattern, op_id in _operation_patterns() if verb == method and pattern.match(path)]
    if not matches:
        return method not in IDEMPOTENT_METHODS
    return any(op_id in SIDE_EFFECT_OPERATIONS for op_id in matches)


_TEXT_TYPE = re.compile(r"text/|image/svg\+xml|application/(xml|yaml|x-yaml|javascript)\b|[^;]*\+xml\b")


def _response_data(response: httpx.Response, response_type: ResponseType = "auto") -> Any:
    if response.status_code == 204:
        return None
    if response_type == "bytes":
        return response.content
    if response_type == "text":
        return response.text
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" in content_type or "+json" in content_type:
        return response.json()
    if not content_type or _TEXT_TYPE.match(content_type):
        return response.text
    return response.content



class _ClientSettings:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        retry: RetryConfig | None,
        headers: Mapping[str, str] | None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry = retry
        self.headers = dict(headers or {})

    def request_headers(self, options: RequestOptions, accept: str | None = None) -> dict[str, str]:
        headers = {key.lower(): value for key, value in {**self.headers, **options.headers}.items()}
        headers.update({"accept": accept or "application/json", "x-api-key": self.api_key})
        if options.idempotency_key:
            headers["idempotency-key"] = options.idempotency_key
        return headers

    def retry_plan(self, method: str, path: str, options: RequestOptions) -> _RetryPlan | None:
        if options.retry is False:
            return None
        config = options.retry if isinstance(options.retry, RetryConfig) else self.retry
        if config is None:
            return None
        if options.max_retries is not None:
            config = replace(config, retries=options.max_retries)
        opted_in = options.retry is True or isinstance(options.retry, RetryConfig) or bool(options.idempotency_key)
        return _RetryPlan(config=config, replay_safe=opted_in or not is_side_effecting(method, path))


class FreeAstro(GeneratedResources):
    """FreeAstroAPI client.

    Resources follow the API paths: ``client.western.natal.insights(...)`` calls
    ``POST /api/v1/western/natal/insights``. Where an operation exists in several API versions,
    the plain method name calls the latest one and older ones carry a suffix
    (``client.vedic.chart`` is v2, ``client.vedic.chart_v1`` is v1).
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        retry: RetryConfig | None = DEFAULT_RETRY,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = _ClientSettings(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            retry=retry,
            headers=headers,
        )
        self._http = httpx.Client(base_url=self._settings.base_url, transport=transport)
        self.geo = GeoResource(self)
        self.moon = MoonResource(self)
        self.sky_events = SkyEventsResource(self)
        self.western = WesternResource(self)
        self._init_generated_resources(self)

    def __enter__(self) -> FreeAstro:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        options: RequestOptions | None = None,
        accept: str | None = None,
        response_type: ResponseType = "auto",
    ) -> Any:
        """Send a request. ``accept`` sets the ``Accept`` header (default ``application/json``);
        ``response_type`` picks how the body is read (see :data:`ResponseType`)."""
        return self.request_raw(
            method, path, params=params, json=json, options=options, accept=accept, response_type=response_type
        ).data

    def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        options: RequestOptions | None = None,
        accept: str | None = None,
        response_type: ResponseType = "auto",
    ) -> SDKResponse[Any]:
        options = options or RequestOptions()
        method = method.upper()
        plan = self._settings.retry_plan(method, path, options)
        attempt = 0

        while True:
            try:
                response = self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._settings.request_headers(options, accept),
                    timeout=options.timeout if options.timeout is not None else self._settings.timeout,
                )
            except httpx.HTTPError as exc:
                delay = plan.exception_delay(attempt) if plan else None
                if delay is not None:
                    time.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise TimeoutError("FreeAstroAPI request timed out") from exc
                raise NetworkError("Unable to reach FreeAstroAPI") from exc

            if response.is_success:
                return SDKResponse(data=_response_data(response, response_type), response=response)
            delay = plan.response_delay(response, attempt) if plan else None
            if delay is not None:
                time.sleep(delay)
                attempt += 1
                continue
            raise error_from_response(response)


class AsyncFreeAstro(AsyncGeneratedResources):
    """Async FreeAstroAPI client with the same resources as :class:`FreeAstro`."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        retry: RetryConfig | None = DEFAULT_RETRY,
        headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = _ClientSettings(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            retry=retry,
            headers=headers,
        )
        self._http = httpx.AsyncClient(base_url=self._settings.base_url, transport=transport)
        self.geo = AsyncGeoResource(self)
        self.moon = AsyncMoonResource(self)
        self.sky_events = AsyncSkyEventsResource(self)
        self.western = AsyncWesternResource(self)
        self._init_generated_resources(self)

    async def __aenter__(self) -> AsyncFreeAstro:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        options: RequestOptions | None = None,
        accept: str | None = None,
        response_type: ResponseType = "auto",
    ) -> Any:
        """Send a request. ``accept`` sets the ``Accept`` header (default ``application/json``);
        ``response_type`` picks how the body is read (see :data:`ResponseType`)."""
        raw = await self.request_raw(
            method, path, params=params, json=json, options=options, accept=accept, response_type=response_type
        )
        return raw.data

    async def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        options: RequestOptions | None = None,
        accept: str | None = None,
        response_type: ResponseType = "auto",
    ) -> SDKResponse[Any]:
        options = options or RequestOptions()
        method = method.upper()
        plan = self._settings.retry_plan(method, path, options)
        attempt = 0

        while True:
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._settings.request_headers(options, accept),
                    timeout=options.timeout if options.timeout is not None else self._settings.timeout,
                )
            except httpx.HTTPError as exc:
                delay = plan.exception_delay(attempt) if plan else None
                if delay is not None:
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise TimeoutError("FreeAstroAPI request timed out") from exc
                raise NetworkError("Unable to reach FreeAstroAPI") from exc

            if response.is_success:
                return SDKResponse(data=_response_data(response, response_type), response=response)
            delay = plan.response_delay(response, attempt) if plan else None
            if delay is not None:
                await asyncio.sleep(delay)
                attempt += 1
                continue
            raise error_from_response(response)
