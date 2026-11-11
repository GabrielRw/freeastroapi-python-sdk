# Changelog

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
