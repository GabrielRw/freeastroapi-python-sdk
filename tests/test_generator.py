"""Generator tests on a small synthetic spec (tests/fixtures/synthetic-spec.json) covering cases
the production spec does not have yet: component names that are not identifiers, error response
schemas, 201 and ``+json`` responses, and non-JSON bodies (SVG, PNG, Markdown, PDF)."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from freeastroapi import AuthenticationError, ConflictError, FreeAstro, ValidationError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "synthetic-spec.json").read_text(encoding="utf-8"))


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("freeastro_generate", ROOT / "scripts" / "generate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = _load_generator()
FILES: dict[str, str] = generator.generate(copy.deepcopy(FIXTURE))
SCHEMAS = FILES["schemas.py"]
RESOURCES = FILES["_generated.py"]


@pytest.fixture(scope="module")
def package(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    root = tmp_path_factory.mktemp("generated")
    pkg = root / "fixture_sdk"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "client.py").write_text(
        "from freeastroapi.client import AsyncFreeAstro, FreeAstro, RequestOptions\n\n"
        '__all__ = ["AsyncFreeAstro", "FreeAstro", "RequestOptions"]\n',
        encoding="utf-8",
    )
    for name, text in FILES.items():
        (pkg / name).write_text(text, encoding="utf-8")
    sys.path.insert(0, str(root))
    try:
        yield importlib.import_module("fixture_sdk._generated")
    finally:
        sys.path.remove(str(root))
        for name in [n for n in sys.modules if n.startswith("fixture_sdk")]:
            del sys.modules[name]


def _client(handler: Any) -> FreeAstro:
    return FreeAstro(api_key="k", retry=None, transport=httpx.MockTransport(handler))


def test_generated_code_passes_mypy_strict(package: ModuleType) -> None:
    mypy_api = pytest.importorskip("mypy.api")
    pkg_dir = Path(package.__file__).parent
    stdout, stderr, status = mypy_api.run(
        ["--strict", "--no-incremental", "--follow-imports=silent", "--python-version", "3.11", str(pkg_dir)]
    )
    assert status == 0, stdout + stderr


def test_component_names_become_identifiers() -> None:
    assert "class Thing_Input(TypedDict):" in SCHEMAS
    assert "class Thing_Output(TypedDict):" in SCHEMAS
    assert "Schema ``Thing-Input`` in the OpenAPI document." in SCHEMAS
    assert 'owner: NotRequired[Union["Record", None]]' in SCHEMAS
    assert "class ErrorResponse(TypedDict):" in SCHEMAS
    assert "def create_v1(\n        self,\n        body: schemas.Thing_Input," in RESOURCES
    assert ") -> schemas.Thing_Output:" in RESOURCES


def test_names_clashing_with_typing_are_renamed() -> None:
    spec = copy.deepcopy(FIXTURE)
    spec["components"]["schemas"]["Any"] = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert "class AnySchema(TypedDict):" in generator.generate(spec)["schemas.py"]


def test_201_and_vendor_json_responses_are_typed() -> None:
    assert ") -> schemas.Record:" in RESOURCES
    item = RESOURCES[RESOURCES.index("    def create(") :]
    assert ") -> schemas.Thing_Output:" in item[:400]


def test_non_json_bodies_are_text_or_bytes() -> None:
    for name, returns in (("svg", "str"), ("markdown", "str"), ("mixed", "str"), ("png", "bytes"), ("pdf", "bytes")):
        method = RESOURCES[RESOURCES.index(f"    def {name}(") :]
        assert f") -> {returns}:" in method[:400], name
    assert 'accept="application/pdf", response_type="bytes"' in RESOURCES
    assert 'accept="image/svg+xml, image/png", response_type="text"' in RESOURCES


def test_unsupported_request_bodies_fail() -> None:
    spec = copy.deepcopy(FIXTURE)
    spec["paths"]["/api/v1/render/svg"]["post"]["requestBody"] = {
        "content": {"multipart/form-data": {"schema": {"type": "object"}}}
    }
    with pytest.raises(SystemExit, match="multipart/form-data are not supported"):
        generator.generate(spec)


def test_accept_header_and_body_decoding(package: ModuleType) -> None:
    seen: list[httpx.Request] = []
    bodies = {
        "/api/v1/render/svg": ("<svg/>", "image/svg+xml"),
        "/api/v1/docs/pdf": (b"%PDF", "application/pdf"),
        "/api/v1/docs/markdown": ("# Title", "text/markdown; charset=utf-8"),
        "/api/v1/render/png": (b"\x89PNG", "image/png"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path in bodies:
            content, content_type = bodies[request.url.path]
            return httpx.Response(200, content=content, headers={"content-type": content_type})
        return httpx.Response(201, json={"thing_id": "a/b"})

    with _client(handler) as client:
        render = package.RenderResource(client)
        docs = package.DocsResource(client)
        things = package.ThingsResource(client)
        assert render.svg({"size": 100}) == "<svg/>"
        assert docs.pdf(job_id="j") == b"%PDF"
        assert docs.markdown() == "# Title"
        assert render.png() == b"\x89PNG"
        assert things.item("a/b", lang="fr") == {"thing_id": "a/b"}

    assert [r.headers["accept"] for r in seen] == [
        "image/svg+xml",
        "application/pdf",
        "text/markdown",
        "image/png",
        "application/json",
    ]
    assert str(seen[-1].url) == "https://api.freeastroapi.com/api/v1/things/item/a%2Fb?lang=fr"


async def test_async_resources_decode_bytes(package: ModuleType) -> None:
    from freeastroapi import AsyncFreeAstro

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})

    async with AsyncFreeAstro(api_key="k", retry=None, transport=httpx.MockTransport(handler)) as client:
        assert await package.AsyncDocsResource(client).pdf(job_id="j") == b"%PDF"


def test_documented_errors_map_to_typed_errors(package: ModuleType) -> None:
    def conflict(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Report not ready", "code": "not_ready", "trace_id": "t-1"})

    with _client(conflict) as client, pytest.raises(ConflictError) as info:
        package.DocsResource(client).pdf(job_id="j")
    assert (info.value.status, info.value.code, str(info.value)) == (409, "not_ready", "Report not ready")
    assert info.value.details["trace_id"] == "t-1"

    def problem(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "bad size"}, headers={"content-type": "application/problem+json"})

    with _client(problem) as client, pytest.raises(ValidationError):
        package.ThingsResource(client).create_v1({"name": "a"})

    def unauthorized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad key"})

    with _client(unauthorized) as client, pytest.raises(AuthenticationError):
        package.RenderResource(client).png()
