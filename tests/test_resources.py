from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError

from freeastroapi import (
    AsyncFreeAstro,
    FreeAstro,
    GeoSearchParams,
    MoonMonthParams,
    MoonPhaseParams,
    SkyEventsParams,
    WesternSignRequest,
)


def _moon_phase() -> dict[str, object]:
    return {
        "timestamp": "2026-08-27T10:00:00Z",
        "phase": {
            "name": "Full Moon",
            "phase_angle_deg": 180,
            "illumination": 1,
            "age_days": 14.8,
            "distance_km": 384_400,
            "is_waxing": False,
        },
        "next_phases": {
            "new_moon": "2026-09-11T00:00:00Z",
            "first_quarter": "2026-09-18T00:00:00Z",
            "full_moon": "2026-10-02T00:00:00Z",
            "last_quarter": "2026-09-04T00:00:00Z",
        },
    }


def _response_for(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/v2/geo/search":
        payload: object = {"results": [], "count": 0}
    elif path == "/api/v1/moon/phase":
        payload = _moon_phase()
    elif path == "/api/v1/moon/month":
        payload = {
            "year": 2026,
            "month": 8,
            "month_name": "August",
            "days_in_month": 31,
            "calendar_basis": "local",
            "calendar_timezone": "Europe/Paris",
            "days": [{"calendar_date": "2026-08-27", **_moon_phase()}],
        }
    elif path == "/api/v1/sky-events":
        payload = {"date": "2026-08-27", "timezone": "Europe/Paris", "events": []}
    elif path.startswith("/api/v1/western/signs/"):
        payload = {
            "point": path.rsplit("/", 1)[-1].title(),
            "sign": "Gemini",
            "sign_id": "gemini",
            "degree": 12,
            "abs_pos": 72,
            "house": 10,
            "interpretation": None,
        }
    else:
        raise AssertionError(f"unexpected path: {path}")
    return httpx.Response(200, json=payload, request=request)


def test_sync_resources_match_every_reviewed_openapi_operation() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _response_for(request)

    birth = WesternSignRequest(year=1990, month=6, day=15, city="Paris")
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        assert client.geo.search("Paris", limit=3, country="FR").count == 0
        assert client.moon.phase(MoonPhaseParams(date="2026-08-27T10:00:00Z", include_eclipse=True)).phase.name
        assert client.moon.month(MoonMonthParams(year=2026, month=8, city="Paris")).days_in_month == 31
        assert client.sky_events.list(SkyEventsParams(date="2026-08-27", timezone="Europe/Paris")).events == []
        assert client.western.signs.sun(birth).point == "Sun"
        assert client.western.signs.moon(birth).point == "Moon"
        assert client.western.signs.rising(birth).point == "Rising"
        assert client.western.signs.midheaven(birth).point == "Midheaven"

    assert [(request.method, request.url.path) for request in captured] == [
        ("GET", "/api/v2/geo/search"),
        ("GET", "/api/v1/moon/phase"),
        ("GET", "/api/v1/moon/month"),
        ("GET", "/api/v1/sky-events"),
        ("POST", "/api/v1/western/signs/sun"),
        ("POST", "/api/v1/western/signs/moon"),
        ("POST", "/api/v1/western/signs/rising"),
        ("POST", "/api/v1/western/signs/midheaven"),
    ]
    assert str(captured[0].url.params) == "q=Paris&limit=3&country=FR"
    assert captured[1].url.params["include_eclipse"] == "true"
    assert json.loads(captured[4].content)["city"] == "Paris"


@pytest.mark.asyncio
async def test_async_resources_match_every_reviewed_openapi_operation() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _response_for(request)

    birth = WesternSignRequest(year=1990, month=6, day=15, lat=48.8566, lng=2.3522)
    async with AsyncFreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        await client.geo.search("Paris")
        await client.moon.phase()
        await client.moon.month(MoonMonthParams(year=2026, month=8))
        await client.sky_events.list(SkyEventsParams(date="2026-08-27"))
        await client.western.signs.sun(birth)
        await client.western.signs.moon(birth)
        await client.western.signs.rising(birth)
        await client.western.signs.midheaven(birth)

    assert len(captured) == 8
    assert json.loads(captured[-1].content)["lat"] == 48.8566


@pytest.mark.parametrize(
    "factory",
    [
        lambda: GeoSearchParams(q="x"),
        lambda: GeoSearchParams(q="Paris", country="fr"),
        lambda: MoonMonthParams(year=2026, month=13),
        lambda: MoonPhaseParams(lat=91),
        lambda: SkyEventsParams.model_validate({"date": "2026-08-27", "extra": True}),
        lambda: WesternSignRequest(year=1990, month=6, day=15),
        lambda: WesternSignRequest(year=1990, month=6, day=15, lat=48.8),
    ],
)
def test_request_models_reject_values_outside_the_public_contract(factory: Callable[[], object]) -> None:
    with pytest.raises(PydanticValidationError):
        factory()


def test_response_models_preserve_additive_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "count": 0, "contract_version": "next"}, request=request)

    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        result = client.geo.search("Paris")

    assert result.model_extra == {"contract_version": "next"}
