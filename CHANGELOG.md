# Changelog

## 0.1.0

- Add synchronous `FreeAstro` and asynchronous `AsyncFreeAstro` clients.
- Add Pydantic v2 models for Geo Search, Moon Phase, Moon Month, Sky Events, and four Western sign operations.
- Add a generic request escape hatch for additional documented endpoints.
- Add capped exponential retries with `Retry-After` and idempotency-aware POST behavior.
- Add typed API, network, timeout, validation, authentication, permission, conflict, rate-limit, and server errors.
