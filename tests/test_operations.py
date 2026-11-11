from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest

from freeastroapi import OPERATIONS, AsyncFreeAstro, FreeAstro, OperationInfo, schemas

SPEC = json.loads((Path(__file__).resolve().parents[1] / "spec" / "freeastro.json").read_text(encoding="utf-8"))
SPEC_OPERATIONS = {
    op["operationId"]: (method.upper(), path)
    for path, item in SPEC["paths"].items()
    for method, op in item.items()
}
PATH_VALUE = "p 1"
# Hand-written v0.1 methods keep their own signatures.
HAND_WRITTEN_ARGS: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {
    "v2_geo_search": (("Paris",), {}),
    "v1_moon_month": ((), {}),
    "v1_sky_events": ((), {}),
}


def _resolve(client: object, accessor: tuple[str, ...]) -> Any:
    target: Any = client
    for name in accessor:
        target = getattr(target, name)
    return target


def _call_args(info: OperationInfo) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if info.operation_id in ("v1_moon_month",):
        from freeastroapi import MoonMonthParams

        return (MoonMonthParams(year=2026, month=1, city="Paris"),), {}
    if info.operation_id == "v1_sky_events":
        from freeastroapi import SkyEventsParams

        return (SkyEventsParams(date="2026-01-01"),), {}
    if info.operation_id.startswith("v1_western_signs_"):
        from freeastroapi import WesternSignRequest

        return (WesternSignRequest(year=1990, month=1, day=1, city="Paris"),), {}
    if info.operation_id in HAND_WRITTEN_ARGS:
        return HAND_WRITTEN_ARGS[info.operation_id]
    args: list[Any] = [PATH_VALUE for _ in info.path_params]
    if info.has_body:
        args.append({"year": 1990})
    kwargs = {name: "x" for name in info.required_query}
    return tuple(args), kwargs


def _empty_ok(captured: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={}, request=request)

    return httpx.MockTransport(handler)


def test_every_spec_operation_has_exactly_one_method() -> None:
    assert sorted(info.operation_id for info in OPERATIONS) == sorted(SPEC_OPERATIONS)
    accessors = [info.accessor for info in OPERATIONS]
    assert len(set(accessors)) == len(accessors)
    for info in OPERATIONS:
        assert (info.method, info.path) == SPEC_OPERATIONS[info.operation_id]


@pytest.mark.parametrize("info", OPERATIONS, ids=lambda info: ".".join(info.accessor))
def test_sync_method_calls_its_endpoint(info: OperationInfo, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[httpx.Request] = []
    client = FreeAstro(api_key="test_key", transport=_empty_ok(captured), retry=None)
    # Responses are validated only for the hand-written v0.1 methods; skip that here.
    monkeypatch.setattr("pydantic.BaseModel.model_validate", classmethod(lambda cls, data: data))
    args, kwargs = _call_args(info)

    _resolve(client, info.accessor)(*args, **kwargs)

    request = captured[0]
    expected_path = info.path.replace("{", "").replace("}", "")
    for name in info.path_params:
        expected_path = expected_path.replace(name, quote(PATH_VALUE, safe=""), 1)
    assert request.method == info.method
    assert request.url.raw_path.decode().split("?")[0] == expected_path
    if info.has_body and not info.operation_id.startswith("v1_western_signs_"):
        assert json.loads(request.content) == {"year": 1990}


async def test_async_methods_mirror_sync_methods() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={}, request=request)

    async with AsyncFreeAstro(api_key="test_key", transport=httpx.MockTransport(handler)) as client:
        for info in OPERATIONS:
            assert callable(_resolve(client, info.accessor)), info.accessor
        body: schemas.PanchangRequestV2 = {"year": 2026, "month": 1, "day": 1, "hour": 6, "minute": 0, "city": "Delhi"}
        await client.vedic.panchang(body)
        await client.natal.report("abc/1", format="json")
        await client.horoscope.daily.sign_v1(sign="aries")

    assert [str(r.url) for r in captured] == [
        "https://api.freeastroapi.com/api/v2/vedic/panchang",
        "https://api.freeastroapi.com/api/v1/natal/report/abc%2F1?format=json",
        "https://api.freeastroapi.com/api/v1/horoscope/daily/sign?sign=aries",
    ]


def test_latest_version_is_the_default_name() -> None:
    client = FreeAstro(api_key="test_key")
    by_accessor = {info.accessor: info for info in OPERATIONS}
    assert by_accessor[("vedic", "chart")].path == "/api/v2/vedic/chart"
    assert by_accessor[("vedic", "chart_v1")].path == "/api/v1/vedic/chart"
    assert by_accessor[("horoscope", "daily", "sign")].path == "/api/v3/horoscope/daily/sign"
    assert callable(client.western.progressions.secondary_exact_aspects)
    client.close()
