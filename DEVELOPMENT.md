# Local development stack

Runs the service in Docker with live reload, alongside the Postgres it needs.
Nothing here changes the production `compose.yaml` or `Dockerfile`; this is an
overlay that re-opens the app container for development.

## Start

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

The first build needs its base images in the local store. Pull them once:

```bash
docker pull node:22-alpine
docker pull python:3.12.7-slim
docker pull ghcr.io/astral-sh/uv:0.11.1
docker pull postgres:16-alpine
```

This matters on networks whose resolver answers Docker Hub hostnames
incorrectly. `docker pull` succeeds there while BuildKit's own registry lookup
fails, because the builder resolves names separately from the daemon.

## What the overlay changes

| | production | `compose.dev.yaml` |
|---|---|---|
| entrypoint | `python -m sub2api_mcp` | `uvicorn sub2api_mcp.dev:app --reload` |
| source | baked into the image | `./src` and `./core` bind-mounted |
| root filesystem | read-only | writable |
| console | prebuilt into the image | not built; run Vite on the host |

`src/sub2api_mcp/dev.py` exists only to give `--reload` an importable app.
`__main__.py` builds its runtime inside `main()`, which a reloader cannot
import.

Edits to `src/` and `core/` restart the worker within a few seconds. Dependency
changes do not: rebuild the image instead, since the venv is locked by
`uv.lock`.

## Console with hot reload

```bash
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173/guardian/. Vite proxies `/api` and `/guardian` to
the container on port 5310, so the console talks to the live service while
React fast-refreshes on save.

Set `SUB2API_MCP_CONSOLE_USERNAME` and `SUB2API_MCP_CONSOLE_PASSWORD_HASH` in
`.env` to enable console sign-in; without them the console has no login and the
REST API stays API-key only.

## Configuration

`.env` holds the local credentials and is git-ignored. The scheduler is off by
default so the container does not write to the live Sub2API deployment. To
exercise Guardian against the real upstream, set
`SUB2API_MCP_SUB2API_ADMIN_KEY` to a working key and turn
`SUB2API_MCP_SCHEDULER_ENABLED` on deliberately.

## Stop

```bash
docker compose -f compose.yaml -f compose.dev.yaml down
```

Add `-v` to also drop the Postgres volume.
