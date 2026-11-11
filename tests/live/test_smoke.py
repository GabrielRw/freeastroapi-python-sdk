"""Nightly smoke test against production (.github/workflows/live-smoke.yml).

Five cheap, read-only calls; retries are off so a failure never spends extra quota.

    FREEASTRO_TEST_API_KEY=... pytest -m live
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from freeastroapi import FreeAstro, MoonPhaseParams, WesternSignRequest

API_KEY = os.environ.get("FREEASTRO_TEST_API_KEY")
BASE_URL = os.environ.get("FREEASTRO_BASE_URL", "https://api.freeastroapi.com")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not API_KEY, reason="set FREEASTRO_TEST_API_KEY to call the production API"),
]


@pytest.fixture(scope="module")
def client() -> Iterator[FreeAstro]:
    with FreeAstro(api_key=API_KEY or "", base_url=BASE_URL, retry=None, timeout=60) as sdk:
        yield sdk


def test_geo_search(client: FreeAstro) -> None:
    cities = client.geo.search("Paris", limit=1)
    assert cities.results
    assert cities.results[0].timezone


def test_moon_phase(client: FreeAstro) -> None:
    phase = client.moon.phase(MoonPhaseParams(date="2026-01-15"))
    assert phase.phase.name


def test_western_sun_sign(client: FreeAstro) -> None:
    sign = client.western.signs.sun(WesternSignRequest(year=1990, month=6, day=15, city="Paris"))
    assert sign.sign_id == "gemini"


def test_natal_calculate(client: FreeAstro) -> None:
    chart = client.natal.calculate({"year": 1990, "month": 6, "day": 15, "hour": 14, "minute": 30, "city": "Paris"})
    assert isinstance(chart, dict) and chart


def test_vedic_panchang(client: FreeAstro) -> None:
    panchang = client.vedic.panchang({"year": 2026, "month": 1, "day": 14, "hour": 6, "minute": 0, "city": "Delhi"})
    assert isinstance(panchang, dict) and panchang
