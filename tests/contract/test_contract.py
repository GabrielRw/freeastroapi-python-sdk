"""Contract tests: every SDK method against a Stoplight Prism mock of spec/freeastro.json.

Prism validates each request (path, query, headers, JSON body) against the spec and answers 4xx
with an ``sl-violations`` header when it does not match, so a passing run means the SDK builds
requests the API accepts. Each response must then validate against the method's return type
(TypedDicts via pydantic, ``str`` or ``bytes``). The hand-written v0.1 methods must decode
Prism's spec-valid data without falling back to lenient decoding, so their models match the spec.

    python3 scripts/with_prism.py -- pytest -m contract
    PRISM_URL=http://127.0.0.1:4010 pytest -m contract    # Prism already running

Request values are the minimal valid requests from ``scripts/spec_sync.py samples``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from freeastroapi import OPERATIONS, FreeAstro, FreeAstroError, OperationInfo, _generated, schemas
from freeastroapi.models import MoonMonthParams, MoonPhaseParams, ResponseModel, SkyEventsParams, WesternSignRequest

PRISM_URL = os.environ.get("PRISM_URL")
ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "spec" / "freeastro.json").read_text(encoding="utf-8"))
# Hand-written v0.1 methods return Pydantic models; their raw responses are also checked against
# the spec's own schema type.
HAND_WRITTEN = {"v2_geo_search", "v1_moon_phase", "v1_moon_month", "v1_sky_events"} | {
    f"v1_western_signs_{point}" for point in ("sun", "moon", "rising", "midheaven")
}

pytestmark = [
    pytest.mark.contract,
    pytest.mark.skipif(not PRISM_URL, reason="set PRISM_URL (or run scripts/with_prism.py) for contract tests"),
]


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("freeastro_generate", ROOT / "scripts" / "generate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def samples() -> dict[str, Any]:
    output = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "spec_sync.py"), "samples", str(ROOT / "spec" / "freeastro.json")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    result: dict[str, Any] = json.loads(output)
    return result


@pytest.fixture(scope="module")
def recorded() -> list[httpx.Response]:
    return []


@pytest.fixture(scope="module")
def client(recorded: list[httpx.Response]) -> Iterator[FreeAstro]:
    transport = httpx.HTTPTransport()

    class Recording(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            response = transport.handle_request(request)
            response.read()
            recorded.append(response)
            return response

    with FreeAstro(api_key="contract-test-key", base_url=PRISM_URL or "", retry=None, transport=Recording()) as sdk:
        yield sdk


def _call(client: FreeAstro, info: OperationInfo, sample: dict[str, Any], py_ident: Any) -> Any:
    query = sample["query"]
    if info.operation_id == "v2_geo_search":
        return client.geo.search(query["q"])
    if info.operation_id == "v1_moon_phase":
        return client.moon.phase(MoonPhaseParams(**query))
    if info.operation_id == "v1_moon_month":
        return client.moon.month(MoonMonthParams(**query))
    if info.operation_id == "v1_sky_events":
        return client.sky_events.list(SkyEventsParams(**query))
    if info.operation_id.startswith("v1_western_signs_"):
        point = info.operation_id.rsplit("_", 1)[-1]
        return getattr(client.western.signs, point)(WesternSignRequest(**sample["body"]))
    target: Any = client
    for name in info.accessor:
        target = getattr(target, name)
    args = list(sample["path_params"].values())
    if info.has_body:
        args.append(sample["body"])
    return target(*args, **{py_ident(name): value for name, value in query.items()})


def test_every_operation_has_a_sample(samples: dict[str, Any]) -> None:
    assert sorted(samples) == sorted(info.operation_id for info in OPERATIONS)


@pytest.mark.parametrize("info", OPERATIONS, ids=lambda info: ".".join(info.accessor))
def test_operation(
    info: OperationInfo, client: FreeAstro, samples: dict[str, Any], recorded: list[httpx.Response]
) -> None:
    generator = _load_generator()
    recorded.clear()
    fallbacks: list[str] = []

    def strict(cls: type[ResponseModel], data: Any) -> Any:
        fallbacks.append(f"{cls.__name__}: {json.dumps(data)[:300]}")
        return original(data)

    original = ResponseModel._construct_leniently.__func__  # type: ignore[attr-defined]
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(ResponseModel, "_construct_leniently", classmethod(lambda cls, data: strict(cls, data)))
            result = _call(client, info, samples[info.operation_id], generator.py_ident)
    except FreeAstroError as error:
        # Prism validates the request, then cannot serialise schemaless image bodies
        # (image/svg+xml, image/png without a schema or example) and answers 500.
        if error.status == 500 and "Cannot find serializer" in json.dumps(error.details):
            return
        violations = recorded[-1].headers.get("sl-violations", "-") if recorded else "-"
        pytest.fail(f"{info.method} {info.path} failed: {error}\nviolations: {violations}\nbody: {error.details}")

    response = recorded[-1]
    # Prism also reports where its own generated mock body breaks the response schema
    # (recursive schemas are cut short); only request violations are the SDK's fault.
    violations = json.loads(response.headers.get("sl-violations", "[]"))
    assert [v for v in violations if v["location"][0] == "request"] == []
    assert response.status_code < 300

    if info.operation_id in HAND_WRITTEN:
        # Prism's mock data is spec-valid, so the models must not need lenient decoding.
        assert fallbacks == [], f"model does not match the spec: {fallbacks[:3]}"
        result = response.json()

    expected = _expected_type(client, info)
    adapter: TypeAdapter[Any] = TypeAdapter(expected)
    # Aliases such as ``dict[str, "Entry"]`` resolve their quoted names in ``schemas``.
    adapter.rebuild(_types_namespace=vars(schemas))
    try:
        adapter.validate_python(result, strict=False)
    except PydanticValidationError as exc:
        prism_broke = {
            tuple(str(p) for p in v["location"][2:]) for v in violations if v["location"][:2] == ["response", "body"]
        }
        real = [
            e
            for e in exc.errors()
            if not any(tuple(str(p) for p in e["loc"])[: len(loc)] == loc for loc in prism_broke if loc)
        ]
        assert real == [], f"response does not match {expected}: {real[:5]}"


def _expected_type(client: FreeAstro, info: OperationInfo) -> Any:
    if info.operation_id in HAND_WRITTEN:
        response = SPEC["paths"][info.path][info.method.lower()]["responses"]["200"]
        return getattr(schemas, response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1])
    method: Any = client
    for name in info.accessor:
        method = getattr(method, name)
    annotation = method.__annotations__["return"]
    return eval(annotation, vars(_generated)) if isinstance(annotation, str) else annotation
