# Changelog

## 0.3.0

- Vendor the new spec (142 operations, 975 component schemas): every JSON operation now has a typed response (`TypedDict`s in `freeastroapi.schemas`) instead of `Any`; chart endpoints declare SVG and PNG, and `client.natal.report` documents its PDF form.
- Typed errors follow the spec's `ErrorResponse`: `code` also comes from the body's `error` or `detail.error`, the message from `detail.message`, and validation errors (`HTTPValidationError`) name the first failing field. `RateLimitError.retry_after` falls back to `retry_after_ms` from the body.
- One retry policy, shared by every FreeAstroAPI SDK: up to 2 retries with exponential backoff (0.5 s, factor 2, full jitter, 8 s cap). HTTP 429 is retried for every operation, honouring `Retry-After` and `retry_after_ms`; a suggested wait over 30 s raises `RateLimitError` at once. HTTP 408/5xx, network errors and timeouts are retried for every operation except those in the new `SIDE_EFFECT_OPERATIONS` (`v1_natal_calculate`, `v1_ai_generate`, `v2_vedic_chat`, `v2_western_chat`, `v2_vedic_qa`, `v1_western_transits_timeline`, `v1_western_transits_insights`), which need an idempotency key or `RequestOptions(retry=True)`. Calculation POSTs are now retried by default; other 4xx never are. `RetryConfig` defaults change (`base_delay=0.5`, `max_delay=8.0`, new `max_retry_after=30.0`) and `RequestOptions` gains `max_retries`.
- Lenient response decoding: the v0.1 Pydantic models (geo, Moon, sky events, Western signs) follow the spec (new Moon fields such as `zodiac`, `rise_set`, `interpretation` with `key`/`title`/`body`/`tone`/`tags`, `traditional_moon`, `sign_timeline`; open `calendar_basis` and `angle`; sign `interpretation` and `resolved_time` objects) and never raise on a response: missing or `null` required fields, unknown fields and unknown enum values decode. `freeastroapi.models.decode` is exported.
- `request()` with the default `response_type="auto"` returns `bytes` for binary content types (PDF, PNG) instead of decoding them as text.
- Operations with non-JSON responses send the matching `Accept` header and return `str` (SVG, Markdown, other `text/*`) or `bytes` (PNG, PDF and other binary types). `request` and `request_raw` take new `accept` and `response_type` arguments (`response_type="bytes"` reads PNG chart renders); `ResponseType` is exported.
- The generator handles component names that are not identifiers (`Model-Input` becomes `schemas.Model_Input`), names that clash with `typing`, 2xx responses other than 200 and `+json` content types, and fails on request bodies it cannot encode.
- Add the daily `Sync spec` workflow, `scripts/spec_sync.py` (fetch, normalise, diff, request samples), Prism contract tests (`pytest -m contract`) and a nightly live smoke test (`pytest -m live`).
- `spec/freeastro.json` is stored normalised (sorted keys); generated files are reordered accordingly.

## 0.2.0

- Cover every operation in the public FreeAstroAPI OpenAPI document (142 operations) on both `FreeAstro` and `AsyncFreeAstro`: Western, Vedic (v1 and v2), Chinese BaZi, numerology, natal charts and reports, transits, ephemeris, horoscopes (v1-v3), AI reports, space charts, geo, Moon and sky events.
- Generate resources and `TypedDict` request/response types (`freeastroapi.schemas`) from the vendored spec (`spec/freeastro.json`) with `scripts/generate.py`.
- The plain method name calls the latest API version; older versions are available with a `_v1`/`_v2` suffix.
- Export `OPERATIONS`, a list of every operation and its client method.
- Add a tag-triggered release workflow that publishes to PyPI with trusted publishing.
- v0.1 methods and Pydantic models are unchanged.

## 0.1.0

- Add synchronous `FreeAstro` and asynchronous `AsyncFreeAstro` clients.
- Add Pydantic v2 models for Geo Search, Moon Phase, Moon Month, Sky Events, and four Western sign operations.
- Add a generic request escape hatch for additional documented endpoints.
- Add capped exponential retries with `Retry-After` and idempotency-aware POST behavior.
- Add typed API, network, timeout, validation, authentication, permission, conflict, rate-limit, and server errors.
