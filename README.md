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

Request bodies and responses are typed with `TypedDict`s generated from the spec's component schemas, in `freeastroapi.schemas`. Every JSON operation has a typed response. They are plain dictionaries at runtime: responses are returned as parsed JSON without validation, so a response with a missing or `null` field, an unknown field or an unknown enum value never raises.

Operations with non-JSON responses send the matching `Accept` header and return `str` (SVG, Markdown) or `bytes` (PNG, PDF). The chart endpoints (`client.natal.chart`, `client.natal.chart_*` such as `chart_synastry`, `client.natal.experimental.solar_return` and `.transits`, `client.space.chart_svg`, `client.vedic.kp_render`, `client.vedic.visual.chart`) return SVG as text; for PNG output read the body as bytes:

```python
png = client.request(
    "POST", "/api/v2/vedic/kp/render", json={**birth, "format": "png"}, accept="image/png", response_type="bytes"
)
```

`client.natal.report(job_id)` returns the report job as JSON; for the finished PDF call `client.request("GET", f"/api/v1/natal/report/{job_id}", params={"format": "pdf"}, accept="application/pdf", response_type="bytes")`.

### v0.1 methods

`client.geo.search`, `client.moon.phase`, `client.moon.month`, `client.sky_events.list` and `client.western.signs.*` keep their v0.1 signatures and return Pydantic v2 models whose fields follow the spec (for example `MoonPhaseResponse.interpretation` is a `MoonInterpretationData` with `key`, `title`, `body`, `tone` and `tags`, and `next_phases` has `new_moon`, `first_quarter`, `full_moon` and `last_quarter`).

Decoding into these models never raises on a response from the API: unknown fields are kept in `model_extra`, and when a value does not match its declared type (a missing or `null` required field, an unknown enum value) the model is still built: valid fields are converted as usual, a missing required field is `None` and any other mismatched value is kept as received. `freeastroapi.models.decode(Model, data)` applies the same rules to your own data.

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

## Retries

By default a request is retried up to 2 times (`RetryConfig(retries=2)`), with exponential backoff and full jitter: before retry *n* (from 0) the client waits a random time between 0 and `min(8, 0.5 * 2**n)` seconds.

- **HTTP 429** is retried for every operation: the request was rejected before it ran. The wait is the `Retry-After` header (seconds or an HTTP date), else `retry_after_ms` from the error body, else the backoff. If the suggested wait is longer than 30 seconds (`RetryConfig.max_retry_after`), the client does not wait and raises `RateLimitError` at once, with the wait in `retry_after`.
- **HTTP 408, 500, 502, 503, 504, network errors and timeouts** are retried for every operation except the side-effecting ones in `freeastroapi.SIDE_EFFECT_OPERATIONS`: `v1_natal_calculate` (may create a paid report job), `v1_ai_generate`, `v2_vedic_chat`, `v2_western_chat`, `v2_vedic_qa`, `v1_western_transits_timeline` and `v1_western_transits_insights`. Those are retried only when the request carries an idempotency key (sent as the `Idempotency-Key` header) or opts in with `RequestOptions(retry=True)`. A `Retry-After` on these responses is honoured the same way.
- **Other 4xx responses** are never retried.

`client.request(...)` follows the same rules, matching the path against the known operations; a path that matches none is treated as side-effecting unless the method is GET, HEAD or OPTIONS.

```python
from freeastroapi import FreeAstro, RequestOptions, RetryConfig

client = FreeAstro(api_key="YOUR_API_KEY", retry=RetryConfig(retries=4))  # retry=None disables retries

client.vedic.chat(body, options=RequestOptions(idempotency_key="chat-turn-42"))  # retried on 5xx
client.natal.calculate(body, options=RequestOptions(max_retries=0))  # no retries for this call
client.geo.search("Paris", options=RequestOptions(retry=False))  # no retries, not even on 429
```

A `RetryConfig` passed in `RequestOptions(retry=...)` replaces the client's settings for that request and also opts it in.

## Errors

All API failures derive from `FreeAstroError`. Specific subclasses cover authentication, permission, validation, conflict, rate limit, server, network, and timeout failures. Each error carries `status`, `code` (the stable error code from the body's `error`, `code` or `detail.error`), `request_id` and `details` (the parsed error body, the spec's `ErrorResponse`); the message is the body's `detail` message.

## Development

```sh
uv sync
uv run python scripts/generate.py --check
uv run ruff check .
uv run mypy
uv run pytest                                              # unit tests, generator tests
uv run python scripts/with_prism.py -- uv run pytest -m contract   # needs Node.js for Prism
uv run python -m build
```

`src/freeastroapi/_generated.py` and `src/freeastroapi/schemas.py` are generated from `spec/freeastro.json` by `scripts/generate.py` (`uv run python scripts/generate.py`); `--check` fails when they are out of date. The generator's own tests (`tests/test_generator.py`) run it on a small synthetic spec (`tests/fixtures/synthetic-spec.json`) covering component names that are not identifiers, error response schemas, 201 responses and non-JSON bodies, and type-check the output with `mypy --strict`.

### Tests

| Command | What it runs |
| --- | --- |
| `pytest` | Unit tests with a mocked transport, including the generator tests. Contract and live tests are skipped. |
| `python scripts/with_prism.py -- pytest -m contract` | Starts [Prism](https://github.com/stoplightio/prism) (pinned version, via `npx`) in mock mode on `spec/freeastro.json` and calls every operation through the SDK (`tests/contract/`). Prism rejects any request that does not match the spec, and each response must validate against the method's return type. With Prism already running: `PRISM_URL=http://127.0.0.1:4010 pytest -m contract`. |
| `FREEASTRO_TEST_API_KEY=... pytest -m live` | Five read-only calls against production (`tests/live/`). |
| `python3 -m unittest discover -s scripts -p "test_*.py"` | Tests for `scripts/spec_sync.py`. |

Request values for the contract tests come from `python3 scripts/spec_sync.py samples spec/freeastro.json`, which builds a minimal valid request for every operation from its schema. For the hand-written v0.1 methods the contract tests also check that Prism's spec-valid data decodes into the Pydantic models without falling back to lenient decoding, so the models stay in line with the spec.

## Maintaining

### How the spec stays in sync

Production (`https://api.freeastroapi.com/openapi.json`) is the source of truth: the API is deployed by hand, so the live document is what customers call.

1. **`Sync spec` workflow** (`.github/workflows/sync-spec.yml`, daily and on demand) fetches the live spec with `scripts/spec_sync.py fetch`, which validates it and writes it normalised (sorted keys except schema `properties`, which keep the API's field order; 2-space indent) so diffs only show real changes.
2. If it differs from `spec/freeastro.json`, the workflow regenerates the SDK, runs the full check (generate `--check`, ruff, mypy, pytest, build) and the Prism contract tests, and opens or updates a pull request from the `spec-sync/auto` branch, labelled `spec-sync`. If generation or a check fails, the workflow run fails and no pull request is opened.
3. The pull request body is the output of `scripts/spec_sync.py diff`: added, removed and changed operations and schemas. Breaking changes (removed operations, parameters or request fields, newly required request fields or parameters, removed request enum values, removed response fields or content types, removed schemas) are listed first and the title starts with `BREAKING:`. The script never picks the version; you do.
4. If production goes back to matching `main`, the next run closes the stale pull request.

Pull requests opened with `GITHUB_TOKEN` do not trigger other workflows, so CI does not start on its own for `spec-sync/auto`; the sync run already ran the same checks. To get CI status on the pull request, run **Actions → CI → Run workflow** on the `spec-sync/auto` branch, or close and reopen the pull request.

Run the same steps locally:

```sh
cp spec/freeastro.json /tmp/previous-spec.json
python3 scripts/spec_sync.py fetch
python3 scripts/spec_sync.py diff /tmp/previous-spec.json spec/freeastro.json
uv run python scripts/generate.py && uv run pytest && uv run python scripts/with_prism.py -- uv run pytest -m contract
```

The **`Live smoke test` workflow** (`.github/workflows/live-smoke.yml`, daily and on demand) runs `pytest -m live` with the `FREEASTRO_TEST_API_KEY` repository secret: geo search, moon phase, western sun sign, a natal chart and a vedic panchang, without retries (5 requests a day). Without the secret it is skipped with a notice.

`scripts/spec_sync.py` and `scripts/with_prism.py` are standard-library Python and identical in every FreeAstroAPI SDK repository; copy them, `tests/fixtures/synthetic-spec.json` and the three workflows when starting a new SDK, then swap in that language's generate, check and test commands.

### Releasing

After merging a spec-sync pull request (or any release-worthy change):

1. Pick the version: breaking changes need a major bump (a minor bump while the SDK is 0.x), new operations or types a minor bump, anything else a patch.
2. Bump `version` in `pyproject.toml` and `__version__` in `src/freeastroapi/__init__.py`, and add a `CHANGELOG.md` entry.
3. Commit, then push a matching tag: `git tag v0.3.0 && git push origin v0.3.0`.

The `Release` workflow checks that the tag matches `pyproject.toml`, runs the checks, builds, and publishes to PyPI with trusted publishing.

Issues and contributions are welcome on [GitHub](https://github.com/GabrielRw/freeastroapi-python-sdk).

Licensed under Apache License 2.0.
