from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Generic, TypeVar

import httpx

from ._generated import AsyncGeneratedResources, GeneratedResources
from .errors import NetworkError, TimeoutError, error_from_response
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

DEFAULT_BASE_URL = "https://api.freeastroapi.com"
DEFAULT_RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class RetryConfig:
    retries: int = 2
    base_delay: float = 0.25
    max_delay: float = 5.0
    statuses: frozenset[int] = DEFAULT_RETRY_STATUSES


DEFAULT_RETRY = RetryConfig()


@dataclass(frozen=True, slots=True)
class RequestOptions:
    headers: Mapping[str, str] = field(default_factory=dict)
    idempotency_key: str | None = None
    timeout: float | None = None
    retry: bool | RetryConfig | None = None


@dataclass(frozen=True, slots=True)
class SDKResponse(Generic[T]):
    data: T
    response: httpx.Response


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
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


def _response_data(response: httpx.Response) -> Any:
    if response.status_code == 204:
        return None
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type or "+json" in content_type:
        return response.json()
    return response.text


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

    def request_headers(self, options: RequestOptions) -> dict[str, str]:
        headers = {key.lower(): value for key, value in {**self.headers, **options.headers}.items()}
        headers.update({"accept": "application/json", "x-api-key": self.api_key})
        if options.idempotency_key:
            headers["idempotency-key"] = options.idempotency_key
        return headers

    def retry_config(self, method: str, options: RequestOptions) -> RetryConfig | None:
        if self.retry is None or options.retry is False:
            return None
        explicitly_enabled = options.retry is True or isinstance(options.retry, RetryConfig)
        replay_safe = method in IDEMPOTENT_METHODS or bool(options.idempotency_key)
        if not explicitly_enabled and not replay_safe:
            return None
        return options.retry if isinstance(options.retry, RetryConfig) else self.retry


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
    ) -> Any:
        return self.request_raw(method, path, params=params, json=json, options=options).data

    def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        options: RequestOptions | None = None,
    ) -> SDKResponse[Any]:
        options = options or RequestOptions()
        method = method.upper()
        retry = self._settings.retry_config(method, options)
        attempt = 0

        while True:
            try:
                response = self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._settings.request_headers(options),
                    timeout=options.timeout if options.timeout is not None else self._settings.timeout,
                )
            except httpx.TimeoutException as exc:
                if retry and attempt < retry.retries:
                    time.sleep(min(retry.base_delay * 2**attempt, retry.max_delay))
                    attempt += 1
                    continue
                raise TimeoutError("FreeAstroAPI request timed out") from exc
            except httpx.HTTPError as exc:
                if retry and attempt < retry.retries:
                    time.sleep(min(retry.base_delay * 2**attempt, retry.max_delay))
                    attempt += 1
                    continue
                raise NetworkError("Unable to reach FreeAstroAPI") from exc

            if response.is_success:
                return SDKResponse(data=_response_data(response), response=response)
            if retry and response.status_code in retry.statuses and attempt < retry.retries:
                delay = _retry_after_seconds(response)
                time.sleep(min(delay if delay is not None else retry.base_delay * 2**attempt, retry.max_delay))
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
    ) -> Any:
        return (await self.request_raw(method, path, params=params, json=json, options=options)).data

    async def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        options: RequestOptions | None = None,
    ) -> SDKResponse[Any]:
        options = options or RequestOptions()
        method = method.upper()
        retry = self._settings.retry_config(method, options)
        attempt = 0

        while True:
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._settings.request_headers(options),
                    timeout=options.timeout if options.timeout is not None else self._settings.timeout,
                )
            except httpx.TimeoutException as exc:
                if retry and attempt < retry.retries:
                    await asyncio.sleep(min(retry.base_delay * 2**attempt, retry.max_delay))
                    attempt += 1
                    continue
                raise TimeoutError("FreeAstroAPI request timed out") from exc
            except httpx.HTTPError as exc:
                if retry and attempt < retry.retries:
                    await asyncio.sleep(min(retry.base_delay * 2**attempt, retry.max_delay))
                    attempt += 1
                    continue
                raise NetworkError("Unable to reach FreeAstroAPI") from exc

            if response.is_success:
                return SDKResponse(data=_response_data(response), response=response)
            if retry and response.status_code in retry.statuses and attempt < retry.retries:
                delay = _retry_after_seconds(response)
                await asyncio.sleep(min(delay if delay is not None else retry.base_delay * 2**attempt, retry.max_delay))
                attempt += 1
                continue
            raise error_from_response(response)
