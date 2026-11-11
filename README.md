# `freeastroapi`

[![CI](https://github.com/GabrielRw/freeastroapi-python-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/GabrielRw/freeastroapi-python-sdk/actions/workflows/ci.yml)

Official Python client for [FreeAstroAPI](https://www.freeastroapi.com), with sync and async transports and typed methods for every public endpoint.

## Install

```sh
pip install freeastroapi
# or
uv add freeastroapi
```

## Quick start

```python
import os

from freeastroapi import FreeAstro


with FreeAstro(api_key=os.environ["FREEASTRO_API_KEY"]) as client:
    cities = client.geo.search("Paris", limit=3)
    print(cities.results[0].timezone)
```

Async usage exposes the same resources:

```python
import os

from freeastroapi import AsyncFreeAstro


async with AsyncFreeAstro(api_key=os.environ["FREEASTRO_API_KEY"]) as client:
    cities = await client.geo.search("Paris", limit=3)
```

## Resources

Every public operation in the [FreeAstroAPI OpenAPI document](spec/freeastro.json) has a typed method on both clients. Resources follow the API paths:

```python
from freeastroapi import FreeAstro, schemas

with FreeAstro(api_key="YOUR_API_KEY") as client:
    # POST /api/v1/natal/calculate?include_minor=true
    chart = client.natal.calculate(
        {"year": 1990, "month": 6, "day": 15, "hour": 14, "minute": 30, "city": "Paris"},
        include_minor=True,
    )

    # POST /api/v2/vedic/panchang
    request: schemas.PanchangRequestV2 = {"year": 2026, "month": 1, "day": 14, "hour": 6, "minute": 0, "city": "Delhi"}
    panchang = client.vedic.panchang(request)

    # POST /api/v1/western/progressions/secondary/exact-aspects
    hits = client.western.progressions.secondary_exact_aspects(progressions_request)

    # GET /api/v1/chinese/calendar/{date}
    day = client.chinese.calendar("2026-02-17", lang="en")

    # GET /api/v3/horoscope/daily/sign
    horoscope = client.horoscope.daily.sign(sign="aries")
```

Path parameters are positional, the JSON body (when there is one) comes next, and query parameters are keyword-only. Every method also takes `options=RequestOptions(...)`.

When an operation exists in several API versions, the plain method name calls the latest version and older versions carry a suffix: `client.vedic.chart` calls `/api/v2/vedic/chart` and `client.vedic.chart_v1` calls `/api/v1/vedic/chart`; `client.horoscope.daily.sign_v1` / `sign_v2` reach the older daily horoscopes.

Resource groups: `ai`, `chinese`, `ephemeris`, `geo`, `horoscope`, `moon`, `natal`, `numerology`, `sky_events`, `space`, `transits`, `vedic`, and `western` (with `astrocartography`, `directions`, `electional`, `natal`, `progressions`, `signs`, `transits` and more). `freeastroapi.OPERATIONS` lists every operation with its client method.

### Types

Request bodies and responses are typed with `TypedDict`s generated from the spec's component schemas, in `freeastroapi.schemas`. They are plain dictionaries at runtime: responses are returned as parsed JSON without validation, so additive API fields never break your code. Where the spec does not describe a response, the method returns `Any`.

Chart render endpoints (`client.vedic.kp_render`, `client.vedic.visual.chart`) return SVG as text; use `client.request_raw(...)` for PNG output.

### v0.1 methods

`client.geo.search`, `client.moon.phase`, `client.moon.month`, `client.sky_events.list` and `client.western.signs.*` keep their v0.1 signatures and return Pydantic v2 models.

Use `client.request(...)` for any other endpoint.

## Western sign example

```python
from freeastroapi import FreeAstro, RequestOptions, WesternSignRequest

birth = WesternSignRequest(
    year=1990,
    month=6,
    day=15,
    city="Paris",
)

with FreeAstro(api_key="YOUR_API_KEY") as client:
    sun = client.western.signs.sun(
        birth,
        options=RequestOptions(idempotency_key="stable-logical-request-key"),
    )
```

GET, HEAD, and OPTIONS requests retry transient network failures and HTTP 408, 429, 500, 502, 503, and 504 responses by default. Unsafe methods require an idempotency key or explicit retry opt-in. `Retry-After` is honored.

All API failures derive from `FreeAstroError`. Specific subclasses cover authentication, permission, validation, conflict, rate limit, server, network, and timeout failures.

## Development

```sh
uv sync
uv run ruff check .
uv run mypy
uv run pytest
uv run python -m build
```

`src/freeastroapi/_generated.py` and `src/freeastroapi/schemas.py` are generated from `spec/freeastro.json`. To update them, copy the API's `public-spec/openapi/freeastro.json` into `spec/` and run `uv run python scripts/generate.py`. CI runs `python scripts/generate.py --check`.

## Releasing

Bump `version` in `pyproject.toml` and `__version__` in `src/freeastroapi/__init__.py`, update `CHANGELOG.md`, then push a matching tag (`git tag v0.2.0 && git push origin v0.2.0`). The `Release` workflow runs the checks, builds, and publishes to PyPI with trusted publishing.

Issues and contributions are welcome on [GitHub](https://github.com/GabrielRw/freeastroapi-python-sdk).

Licensed under Apache License 2.0.
