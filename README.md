# `freeastroapi`

[![CI](https://github.com/GabrielRw/freeastroapi-python-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/GabrielRw/freeastroapi-python-sdk/actions/workflows/ci.yml)

Official Python client for [FreeAstroAPI](https://www.freeastroapi.com), with sync and async transports and Pydantic v2 response models.

> v0.1.0 is source-ready but has not been published to PyPI yet.

## Install

After the first registry release:

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

## Typed resources in v0.1.0

```python
client.geo.search(...)
client.moon.phase(...)
client.moon.month(...)
client.sky_events.list(...)
client.western.signs.sun(...)
client.western.signs.moon(...)
client.western.signs.rising(...)
client.western.signs.midheaven(...)
```

These methods match the reviewed operations in `public-spec/openapi/freeastro.yaml`. Use `client.request(...)` for another documented endpoint and keep its response behind an application-owned model.

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

Issues and contributions are welcome on [GitHub](https://github.com/GabrielRw/freeastroapi-python-sdk).

Licensed under Apache License 2.0.
