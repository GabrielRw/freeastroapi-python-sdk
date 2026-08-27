from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from .models import (
    CitySearchResponse,
    GeoSearchParams,
    MoonMonthParams,
    MoonMonthResponse,
    MoonPhaseParams,
    MoonPhaseResponse,
    SkyEventsParams,
    SkyEventsResponse,
    WesternSignRequest,
    WesternSignResponse,
)

if TYPE_CHECKING:
    from .client import AsyncFreeAstro, FreeAstro, RequestOptions


def _params(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


class GeoResource:
    def __init__(self, client: FreeAstro) -> None:
        self._client = client

    def search(
        self,
        q: str,
        *,
        limit: int = 10,
        country: str | None = None,
        options: RequestOptions | None = None,
    ) -> CitySearchResponse:
        params = GeoSearchParams(q=q, limit=limit, country=country)
        return CitySearchResponse.model_validate(
            self._client.request("GET", "/api/v2/geo/search", params=_params(params), options=options)
        )


class MoonResource:
    def __init__(self, client: FreeAstro) -> None:
        self._client = client

    def phase(
        self, params: MoonPhaseParams | None = None, *, options: RequestOptions | None = None
    ) -> MoonPhaseResponse:
        query = params or MoonPhaseParams()
        return MoonPhaseResponse.model_validate(
            self._client.request("GET", "/api/v1/moon/phase", params=_params(query), options=options)
        )

    def month(self, params: MoonMonthParams, *, options: RequestOptions | None = None) -> MoonMonthResponse:
        return MoonMonthResponse.model_validate(
            self._client.request("GET", "/api/v1/moon/month", params=_params(params), options=options)
        )


class SkyEventsResource:
    def __init__(self, client: FreeAstro) -> None:
        self._client = client

    def list(self, params: SkyEventsParams, *, options: RequestOptions | None = None) -> SkyEventsResponse:
        return SkyEventsResponse.model_validate(
            self._client.request("GET", "/api/v1/sky-events", params=_params(params), options=options)
        )


class WesternSignsResource:
    def __init__(self, client: FreeAstro) -> None:
        self._client = client

    def sun(self, request: WesternSignRequest, *, options: RequestOptions | None = None) -> WesternSignResponse:
        return self._calculate("sun", request, options)

    def moon(self, request: WesternSignRequest, *, options: RequestOptions | None = None) -> WesternSignResponse:
        return self._calculate("moon", request, options)

    def rising(self, request: WesternSignRequest, *, options: RequestOptions | None = None) -> WesternSignResponse:
        return self._calculate("rising", request, options)

    def midheaven(self, request: WesternSignRequest, *, options: RequestOptions | None = None) -> WesternSignResponse:
        return self._calculate("midheaven", request, options)

    def _calculate(
        self,
        point: str,
        request: WesternSignRequest,
        options: RequestOptions | None,
    ) -> WesternSignResponse:
        return WesternSignResponse.model_validate(
            self._client.request(
                "POST",
                f"/api/v1/western/signs/{point}",
                json=_params(request),
                options=options,
            )
        )


class WesternResource:
    def __init__(self, client: FreeAstro) -> None:
        self.signs = WesternSignsResource(client)


class AsyncGeoResource:
    def __init__(self, client: AsyncFreeAstro) -> None:
        self._client = client

    async def search(
        self,
        q: str,
        *,
        limit: int = 10,
        country: str | None = None,
        options: RequestOptions | None = None,
    ) -> CitySearchResponse:
        params = GeoSearchParams(q=q, limit=limit, country=country)
        data = await self._client.request("GET", "/api/v2/geo/search", params=_params(params), options=options)
        return CitySearchResponse.model_validate(data)


class AsyncMoonResource:
    def __init__(self, client: AsyncFreeAstro) -> None:
        self._client = client

    async def phase(
        self, params: MoonPhaseParams | None = None, *, options: RequestOptions | None = None
    ) -> MoonPhaseResponse:
        query = params or MoonPhaseParams()
        data = await self._client.request("GET", "/api/v1/moon/phase", params=_params(query), options=options)
        return MoonPhaseResponse.model_validate(data)

    async def month(self, params: MoonMonthParams, *, options: RequestOptions | None = None) -> MoonMonthResponse:
        data = await self._client.request("GET", "/api/v1/moon/month", params=_params(params), options=options)
        return MoonMonthResponse.model_validate(data)


class AsyncSkyEventsResource:
    def __init__(self, client: AsyncFreeAstro) -> None:
        self._client = client

    async def list(self, params: SkyEventsParams, *, options: RequestOptions | None = None) -> SkyEventsResponse:
        data = await self._client.request("GET", "/api/v1/sky-events", params=_params(params), options=options)
        return SkyEventsResponse.model_validate(data)


class AsyncWesternSignsResource:
    def __init__(self, client: AsyncFreeAstro) -> None:
        self._client = client

    async def sun(self, request: WesternSignRequest, *, options: RequestOptions | None = None) -> WesternSignResponse:
        return await self._calculate("sun", request, options)

    async def moon(self, request: WesternSignRequest, *, options: RequestOptions | None = None) -> WesternSignResponse:
        return await self._calculate("moon", request, options)

    async def rising(
        self, request: WesternSignRequest, *, options: RequestOptions | None = None
    ) -> WesternSignResponse:
        return await self._calculate("rising", request, options)

    async def midheaven(
        self, request: WesternSignRequest, *, options: RequestOptions | None = None
    ) -> WesternSignResponse:
        return await self._calculate("midheaven", request, options)

    async def _calculate(
        self,
        point: str,
        request: WesternSignRequest,
        options: RequestOptions | None,
    ) -> WesternSignResponse:
        data = await self._client.request(
            "POST",
            f"/api/v1/western/signs/{point}",
            json=_params(request),
            options=options,
        )
        return WesternSignResponse.model_validate(data)


class AsyncWesternResource:
    def __init__(self, client: AsyncFreeAstro) -> None:
        self.signs = AsyncWesternSignsResource(client)
