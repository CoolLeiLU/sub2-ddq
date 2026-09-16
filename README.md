# Sub2API Scheduler MCP

Independent MCP service for the complete Sub2API scheduling system. It reuses
the existing hardened channel/account clients and persists scheduling state,
jobs, and Guardian events in SQLite. The service schedules directly; it does
not depend on or push to any external messaging platform.

This repository contains code and portable container artifacts only. No target
server, domain, public port, or reverse proxy is assumed.

## Capabilities

- All Sub2API channel/provider values are treated as data; no provider allowlist.
- Channel/group-account probing with latency-only change suppression.
- The existing 60-second inventory read is reused by Guardian for scoring and account discovery;
  normal schedulable accounts receive one durable low-token health check per hour rather than a
  test on every inventory scan.
- Each new snapshot tests only error/disabled/inactive accounts; a new failed channel episode
  tests its uniquely mapped group once. `active + schedulable=false` is always protected as a
  human pause.
- Explicit test success enables with exact read-back; definitive failure disables with exact
  read-back; indeterminate results preserve state and stop unsafe follow-up writes.
- Slow-first-token protection reads Sub2API usage logs directly: three responses above 30 seconds
  within the latest three minutes quarantine the account immediately, subject to the minimum-pool
  guard. Recovery requires two consecutive successful probes at or below 30 seconds.
- Every Guardian-managed account test uses the matching channel monitor's primary model, prompt `hi`,
  and default text mode. The model is carried in the durable shared snapshot, so recovery after a
  restart uses the same monitor model. If one account is shared by channels with different
  models and no channel-specific trigger identifies the target, Guardian safely falls back to the
  Sub2API account default instead of guessing. An explicit channel/group probe-model override is
  still honored. Manual pauses, expiry, and temporary unavailability are filtered before any test
  request.
- Durable video jobs with user-selected length, steps, and resolution.
- Signed platform-neutral actor bridge for bind, unbind, and account queries.
- Scoped MCP API keys, audit records, structured logs, metrics, and health checks.
- Guardian health scoring, group/channel overrides, minimum-pool protection,
  fuse/recovery state, candidate weights, and a responsive management console.

## Guardian management console

Open the same-origin console after the service starts:

```text
http://127.0.0.1:5310/guardian/
```

Enter an access token carrying `sub2api:admin`. The browser keeps it only in
page memory and clears it on refresh. The console contains eleven sections:
overview, group scheduling, channel pool, account recovery, live routing, probe spend,
scheduling guide, events, policy, connections, and information.

Guardian has one direct scheduling switch and no observe/rollout mode. Start and emergency stop
require confirmation, policy revision, and an idempotency key. When enabled, Guardian resolves a
unique monitor→group→account mapping (stable API-key usage bindings take precedence over display
names), applies bounded `load_factor` and baseline-relative
`priority` changes one field at a time, then performs an independent exact read-back. Account
`schedulable` changes remain tied to explicit conditional account tests.
The policy page exposes the hourly health-check switch and interval. Its durable recovery ledger
prevents repeat tests across the 15-second Guardian scan loop and across service restarts; routine
successful checks are silent, while failures and state changes remain auditable through the
console events page and the Guardian API.

The authenticated REST API is rooted at `/api/guardian/v1`. Policy updates
require an `If-Match` revision; run and action requests accept an
`Idempotency-Key`.

## MCP transport and authentication

Default endpoint:

```text
http://127.0.0.1:5310/mcp
```

Transport is stateless Streamable HTTP with JSON responses. Supply either:

```text
X-API-Key: <token>
Authorization: Bearer <token>
```

Scopes are `sub2api:read`, `sub2api:write`, `sub2api:admin`, and
`sub2api:actor`. An admin token satisfies the read/write/admin tools. The actor
scope is isolated from administrator tools.

## Tools

- Status/read: `sub2api_get_status`, `sub2api_probe_channels`,
  `sub2api_get_job`, `sub2api_list_jobs`, `sub2api_get_bound_account`,
  `sub2api_list_account_quarantines`.
- Scheduler/admin: `sub2api_set_scheduler_enabled`,
  `sub2api_submit_recovery`, `sub2api_submit_maintenance`.
- Bindings: `sub2api_bind_account`, `sub2api_unbind_account`.
- Video/jobs: `sub2api_submit_video`, `sub2api_cancel_job`.
- Guardian/read: `guardian_get_policy`, `guardian_get_status`,
  `guardian_get_recovery_status`, `guardian_get_overview`,
  `guardian_list_groups`, `guardian_list_channels`, `guardian_get_channel`,
  `guardian_list_events`, `guardian_get_probe_spend`.
- Guardian/admin: `guardian_set_scheduling_enabled`, `guardian_update_policy`, `guardian_run_once`,
  `guardian_cancel_run`, `guardian_channel_action`,
  `guardian_preview_restore`, `guardian_execute_restore`.

Every tool returns a compact JSON string with an `ok`, `requestId`, and `data`
or stable `error` object.

## Local development

```bash
cd bot-mcp
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/macOS

uv sync --frozen --all-extras
uv run ruff check .
uv run pyright
uv run python -m sub2api_mcp
```

The local-only `tests/` directory is ignored by Git. When it is available in
your development workspace, run `uv run pytest -q` before pushing.

Replace all placeholder secrets in `.env`. `SUB2API_MCP_ACCESS_TOKENS` is a
JSON array, for example:

```json
[
  {
    "name": "admin",
    "token": "generate-at-least-32-random-characters",
    "scopes": ["sub2api:read", "sub2api:write", "sub2api:admin"]
  }
]
```

## Container build

The Compose file intentionally binds the published port to loopback. It is a
template, not a deployment action.

```bash
cd bot-mcp
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
```

The image runs as UID/GID `10001`, drops all Linux capabilities, uses a
read-only root filesystem in Compose, and writes only to `/data` and temporary
memory.

## Automatic deployment

Pushes to `main` run lint, type checking, all tests, dependency audit, and a
Docker build. After every gate passes, GitHub Actions transfers an immutable
source archive over SSH and builds the image locally on the selected server.
No container image is pushed to any registry.

Production releases are stored under `/opt/bot-mcp/releases/<commit-sha>` with
shared secrets/data outside the release directory. Activation is atomic, and
the `Rollback Production` workflow can reactivate any retained commit SHA.

The deployment workflow uses repository variables `DEPLOY_HOST`,
`DEPLOY_PORT`, and `DEPLOY_USER`, plus encrypted Actions secrets
`DEPLOY_PASSWORD` and `DEPLOY_KNOWN_HOSTS`. Runtime credentials stay only in
`/opt/bot-mcp/shared/.env` on the server.

## Actor bridge

Identity-sensitive commands cannot trust an LLM-supplied user ID. An external
command bridge can send the Workspace UUID, bot UUID, adapter, launcher type,
and launcher ID to `/bridge/v1/actor`. Requests are signed over:

```text
<unix-timestamp>.<nonce>.<raw-request-body>
```

with HMAC-SHA256 and headers `X-Sub2API-Timestamp`, `X-Sub2API-Nonce`, and
`X-Sub2API-Signature`. Raw platform IDs are converted to a versioned HMAC actor
key before persistence.

## Operations

See [RUNBOOK.md](RUNBOOK.md).
