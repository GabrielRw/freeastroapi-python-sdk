"""Responses that break the declared types (a missing required field, a null in a non-null
field, unknown fields, unknown enum values) decode without raising."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from freeastroapi import (
    AsyncFreeAstro,
    FreeAstro,
    MoonMonthParams,
    MoonPhaseParams,
    MoonPhaseResponse,
    SkyEventsParams,
    WesternSignRequest,
)
from freeastroapi.models import CitySearchResponse, decode

BIRTH = WesternSignRequest(year=1990, month=6, day=15, city="Paris")

MOON_PHASE: dict[str, Any] = {
    # "timestamp" (required) is missing.
    "phase": {
        "name": "Super Blue Moon",  # unknown enum value
        "phase_angle_deg": None,  # null in a non-null field
        "illumination": 0.99,
        "age_days": 14.2,
        "distance_km": 384_400,
        "is_waxing": False,
        "brightness": "high",  # unknown field
    },
    "interpretation": {"key": "full_moon", "title": "Full Moon", "body": "Culmination.", "tags": ["release"]},
    "eclipse": {"is_eclipse": True, "type_at_location": "ring"},
    "next_phases": {"new_moon": "2026-09-11T00:00:00Z", "full_moon": None, "first_quarter": "2026-09-18T00:00:00Z"},
    "unknown_section": {"a": 1},
}


def _bodies() -> dict[str, Any]:
    return {
        "/api/v2/geo/search": {
            "results": [
                {"name": "Paris", "country": "FR", "lat": None, "lng": 2.35, "timezone": "Europe/Paris", "x": 1}
            ],
            # "count" missing
        },
        "/api/v1/moon/phase": MOON_PHASE,
        "/api/v1/moon/month": {
            "year": 2026,
            "month": None,
            "calendar_basis": "sidereal",
            "days": [{**MOON_PHASE, "calendar_date": "2026-08-27"}],
            "sign_timeline": [{"sign": "Leo", "duration_minutes": "many"}],
            "new_top_level": True,
        },
        "/api/v1/sky-events": {
            "date": "2026-08-27",
            "timezone": None,
            "events": [{"id": "e1", "type": "eclipse", "importance": "cosmic", "angle": 45, "extra": [1]}],
        },
        "/api/v1/western/signs/sun": {
            "point": "Sun",
            "sign": "Ophiuchus",
            "sign_id": "ophiuchus",
            "degree": None,
            "interpretation": {"title": "Sun in Gemini", "body": "Curious."},
            "resolved_time": {"hour": 12},
            "extra": "kept",
        },
        "/api/v1/natal/calculate": {"planets": None, "surprise": 1},
    }


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_bodies()[request.url.path], request=request)


def test_hand_written_models_never_raise_on_off_spec_responses() -> None:
    with FreeAstro(api_key="test_key", transport=httpx.MockTransport(_handler)) as client:
        cities = client.geo.search("Paris")
        phase = client.moon.phase(MoonPhaseParams())
        month = client.moon.month(MoonMonthParams(year=2026, month=8))
        events = client.sky_events.list(SkyEventsParams(date="2026-08-27"))
        sun = client.western.signs.sun(BIRTH)
        natal = client.natal.calculate({"year": 1990, "month": 6, "day": 15, "city": "Paris"})

    assert cities.count is None
    assert cities.results[0].lat is None
    assert cities.results[0].model_extra == {"x": 1}

    assert phase.timestamp is None
    assert phase.phase.name == "Super Blue Moon"
    assert phase.phase.phase_angle_deg is None
    assert phase.phase.illumination == 0.99
    assert phase.phase.model_extra == {"brightness": "high"}
    assert phase.interpretation is not None
    assert phase.interpretation.tags == ["release"]
    assert phase.interpretation.tone is None
    assert phase.eclipse is not None and phase.eclipse.type_at_location == "ring"
    assert phase.next_phases.new_moon == "2026-09-11T00:00:00Z"
    assert phase.next_phases.full_moon is None
    assert phase.next_phases.last_quarter is None
    assert phase.model_extra == {"unknown_section": {"a": 1}}

    assert month.month is None
    assert month.calendar_basis == "sidereal"
    assert month.days[0].calendar_date == "2026-08-27"
    assert month.days[0].phase.name == "Super Blue Moon"
    assert month.sign_timeline is not None and month.sign_timeline[0].duration_minutes == "many"
    assert month.model_extra == {"new_top_level": True}

    assert events.timezone is None
    assert events.events[0].type == "eclipse"
    assert events.events[0].importance == "cosmic"
    assert events.events[0].angle == 45
    assert events.events[0].title is None

    assert sun.sign_id == "ophiuchus"
    assert sun.interpretation == {"title": "Sun in Gemini", "body": "Curious."}
    assert sun.resolved_time == {"hour": 12}
    assert sun.house is None
    assert sun.model_extra == {"extra": "kept"}

    # Generated operations return the parsed JSON unchanged.
    assert natal == {"planets": None, "surprise": 1}


@pytest.mark.asyncio
async def test_async_hand_written_models_never_raise() -> None:
    async with AsyncFreeAstro(api_key="test_key", transport=httpx.MockTransport(_handler)) as client:
        phase = await client.moon.phase()
        sun = await client.western.signs.sun(BIRTH)

    assert phase.phase.name == "Super Blue Moon"
    assert sun.sign_id == "ophiuchus"


@pytest.mark.parametrize("body", [None, [], "not json", 42])
def test_a_body_that_is_not_an_object_still_decodes(body: object) -> None:
    result = decode(CitySearchResponse, body)
    assert result.results is None
    assert result.count is None


def test_spec_valid_data_validates_normally() -> None:
    phase = MoonPhaseResponse.model_validate(
        {
            "timestamp": "2026-08-27T10:00:00Z",
            "phase": {
                "name": "Full Moon",
                "phase_angle_deg": 180,
                "illumination": 1,
                "age_days": 14.8,
                "distance_km": 384400,
                "is_waxing": False,
            },
            "zodiac": {"sign": "Pisces", "sign_id": "pisces", "degree": 4.2},
            "rise_set": {"rise": None, "set": "2026-08-27T06:00:00Z"},
            "eclipse": None,
            "next_phases": {
                "new_moon": "2026-09-11T00:00:00Z",
                "first_quarter": "2026-09-18T00:00:00Z",
                "full_moon": "2026-10-02T00:00:00Z",
                "last_quarter": "2026-09-04T00:00:00Z",
            },
        }
    )
    assert phase.phase.phase_angle_deg == 180.0
    assert isinstance(phase.phase.phase_angle_deg, float)
    assert phase.zodiac is not None and phase.zodiac.zodiac_type == "tropical"
    assert phase.rise_set is not None and phase.rise_set.timezone == "UTC"
    assert phase.eclipse is None
