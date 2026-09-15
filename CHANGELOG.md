# Changelog

## [Unreleased]

### Added

- Scheduled model-plaza refresh: twice daily at the configured
  `model_plaza.refresh_times` (default 00:00 and 12:00 Asia/Shanghai)
  Guardian resolves each monitored group's live model catalog the same
  way the gateway does: every enabled channel monitor's masked API key is
  matched to its plaintext via `GET /admin/groups/{id}/api-keys`, then
  `GET {endpoint}/v1/models` returns exactly what that key (and its
  group) can serve.  The result rewrites the bound Sub2API channel's
  `model_mapping`, so the model plaza mirrors the platform's real
  offer.  Refreshes are
  recorded as `MODEL_PLAZA_REFRESHED` events, only channels with a single
  model-mapping platform are rewritten, and a mapping is never emptied
  when every catalog fetch for a group failed.  Monitored groups that are
  not bound to any channel get a new channel created for them (named
  after the group, with the probed mapping) so they appear in the plaza;
  inactive groups and empty probes are skipped.  When the new group
  shares its name with an orphaned channel whose bound groups all
  disappeared upstream, that channel is rebound to the new group instead
  of creating a duplicate.

### Removed

- The 实时路由, 探测费用, and 调度说明 pages were removed: the routing
  comparison only repeated channel-pool columns, and the spend/guard
  guides added no controls.  Probe-spend and budget data remain available
  through the MCP tools and `/probe-spend`/`/probe-budget` endpoints.
- Retired writeback leftovers were deleted end to end: the
  `/rollout/advance`, `/rollout/stop`, `/restores`, and `/live-routing`
  endpoints, the `guardian_advance_rollout`, `guardian_stop_writeback`,
  `guardian_preview_restore`, and `guardian_execute_restore` MCP tools,
  and the unused `guardian_original_config` table.

### Fixed

- Group-name matching for channel binding is now token-order insensitive so
  monitors like "逆向 Claude" bind to groups like "Claude   逆向"; the groups
  list no longer shows a synthetic "ungrouped" row.
- The Guardian channel pool and group list now reconcile with the upstream
  admin list captured in each probe snapshot: channels that no longer exist
  upstream are flagged removed and hidden, reappearing channels are restored,
  and groups without a bound channel (e.g. a closed image group) are listed
  with their upstream account counts and exclusion state.
- The Guardian monitored scope is now closed under monitored channels: a group
  enters scope through a monitored (non-excluded) channel entry or by sharing
  an account with such a group. Accounts bound only to channels that were
  closed or excluded upstream (e.g. a disabled image channel) are no longer
  tested or mutated by account recovery.
- Account recovery no longer treats Sub2API model-routing test errors
  (`model_not_found` / "not supported by any configured account in this group")
  as definitive account failures; they now report `test_incomplete` so accounts
  are not disabled (or kept disabled) when the test model cannot be routed.

### Removed

- Guardian no longer writes `priority`, `load_factor`, or `schedulable` account fields. The
  per-account weight allocation, bounded priority recommendation, verified field writeback,
  write audits, and field-ownership subsystems were removed along with their policy knobs,
  channel overrides (priority/load_factor/concurrency/schedule_multiplier/boost), REST
  endpoints, MCP tools, Prometheus metrics, and UI controls. Health evaluation, circuit
  breaking, and evidence-gated account recovery are unchanged. The `guardian_write_audits`
  and `guardian_field_ownership` tables are dropped by schema migration 10.

### Added

- Guardian now has strict, backward-compatible contracts for shared sampling, evidence
  reliability, confidence gates, conditional recovery, and per-account field ownership.
- Guardian databases now migrate transactionally to the additive V2 evidence schema while
  preserving V1 policy, channel, sample, run, event, and audit data.
- Each successful existing scheduler probe now publishes one canonical rich Guardian snapshot
  from the same validated response, without making an additional upstream probe request.
- Guardian shared mode now leases and consumes each published snapshot exactly once; repeated
  scans and service restarts become local no-ops until new evidence arrives.
- Guardian V2 traffic sampling now filters monitor requests, rejects conflicting duplicate
  request hashes, keeps unattributed evidence out of decisions, and aggregates traffic into
  deterministic minute buckets with volume-neutral cross-time weight.
- Guardian V2 now computes time-decayed short/long health, independent evidence confidence,
  deterministic freshness, and cold-start state; missing evidence preserves the prior health
  score while confidence falls to zero.
- Guardian runs now persist de-duplicated shared-monitor evidence, fuse matching traffic
  buckets by source reliability, exclude legacy samples from V2 scoring, and expose each
  channel's confidence, freshness, evidence age, warm-up count, and source mix.
- Guardian state decisions now freeze on stale or low-confidence evidence, require trusted
  fatal confirmation, prohibit probes or recovery for human-controlled channels, and allow
  recovery only for Guardian-owned fuses meeting the recovery confidence gate.
- Guardian V2 weight recommendations now use dimensionless price/speed signals, reserve low-
  confidence channel budget, penalize missing signals, enforce integer caps and explicit
  unallocated budget, bound load changes, and keep priority tied only to health tiers.
- Guardian now tracks per-account field baselines and ownership, detects sticky human takeover,
  audits every decision, replays idempotent results, and applies direct writes only while the
  single `enabled` switch and verified account writer both permit them.
- Guardian recovery probing now selects only uniquely mapped Guardian-owned fuses and enforces
  interval, concurrency, per-channel hourly, global daily request, and daily Token budgets with
  durable request, cost, Token, and blocked-attempt accounting.

- Guardian REST and MCP surfaces now expose direct scheduling status/start/stop, sampling status,
  channel score explanations, write ownership, open recovery episodes, and confirmed pending
  recovery submission. Legacy rollout endpoints return a stable deprecation error.
- Conditional recovery reuses the existing inventory, tests only abnormal accounts per new
  snapshot, broadens once for a new failed-channel episode, protects manual pauses, and persists
  verified enable/disable/indeterminate outcomes.
- Normal schedulable accounts now receive one durable active health check per hour. The check is
  de-duplicated across fast Guardian scans and restarts, skips human pauses and protected states,
  and keeps ordinary successful checks silent.
- System-owned account tests now use the matching channel monitor's primary model with prompt `hi`
  and default text mode; durable shared snapshots preserve the model selection across restarts, while
  ambiguous shared accounts safely fall back to the Sub2API account default. Explicit channel or
  group probe-model overrides remain available for deliberate exceptions.
- Direct scheduling resolves unique monitor→group→account mappings and applies bounded
  `load_factor` plus baseline-relative `priority` through current-read, one-field write, exact
  read-back verification. A failed verification stops the remaining run.
- Monitor-to-group binding now consults the probe API-key usage record even when a channel exposes a
  stale display group name, so account tests still use the correct channel monitor model.
- The Guardian console is now a light, responsive operations dashboard with explicit scheduling
  controls and redacted recovery status.
- SQLite retention now runs every ten minutes even when direct scheduling is stopped. It removes
  bounded batches of expired observations, runs, events, recovery history, terminal jobs, and
  successfully delivered notifications while preserving live recovery state, queued/failed
  deliveries, human ownership, current channel state, and recent audit history.

### Changed

- Notification payloads are now validated before persistence. Retryable LangBot failures use
  bounded exponential backoff, while non-retryable payload failures stop immediately and remain
  visible in a rollback-safe `DISCARDED` state until retention removes their history.
- Guardian account-recovery notices now coalesce to the latest pending summary per target, so a
  temporary messaging outage cannot release a stale notification burst after recovery.
- Slow-first-token protection now counts only the latest three minutes of Sub2API usage logs and
  quarantines after exactly three over-30-second observations. Recovery now requires two
  consecutive at-or-below-30-second successful probes, with a restart-safe persisted streak.
- Error accounts whose dispatch switch is off are now probed; a successful probe restores both
  account status and dispatch, while non-error paused accounts remain excluded.
- Equal recovery-window start and end times now represent a true 24-hour window.
- Status reports and Guardian transition notifications now show their trigger time in the
  Asia/Shanghai timezone.
- A new status event now supersedes older undelivered status events for the same target to
  prevent stale notification bursts after a delivery outage.
- Automatic media delivery now uses an atomic media-only first attempt and retries as text
  when a LangBot adapter reports an internal media-send failure; ordinary transient upstream
  failures remain queued for retry.
- Account maintenance and recovery notifications now use structured Chinese copy with a
  Beijing trigger time, account identity, localized reason, and explicit result.
- Retention migrations add time-oriented indexes, checkpoint the WAL after each bounded cleanup,
  and expose cleanup outcome, deleted-row, and database-size metrics.
- The Guardian policy page now exposes the hourly account-check switch and interval instead of
  claiming that all normal active probes are disabled.

### Fixed

- Legacy Guardian recovery notifications containing unsupported persistence metadata are
  terminalized by an idempotent startup repair instead of being retried indefinitely. The
  supported deduplication key is now part of the strict outbox contract.
- A transient monitor-to-group remapping no longer aborts every Guardian cycle or expands
  recovery into the wrong group; the conflict is recorded and the existing episode is kept.
- Guardian now supersedes expired shared snapshots during backlog recovery while retaining the
  newest pending snapshot, preventing stale head-of-line data from blocking current scheduling.

- Conditional account recovery now carries the tested pre-mutation state through verified
  enablement, so an upstream `active + schedulable=false` transition created during a successful
  error recovery is completed instead of being misclassified as a human pause. True pre-test
  manual pauses remain immutable.
- Bad-state account tests now use a durable 15-minute cross-snapshot cooldown, preventing the
  same disabled account from being tested and disabled again every scheduler snapshot.
- A validated `error`, `disabled`, or `inactive` account snapshot now remains sufficient evidence
  to run the system account test when the redundant detail re-read is unavailable. A successful
  test immediately completes verified enablement instead of waiting for another state cycle.
- Direct-write limits now count accounts that actually received a verified write. Accounts with
  no change or a cooldown-blocked proposal no longer starve later accounts and groups.
- Guardian now tests abnormal accounts that belong to a monitored group even when the same
  account is also shared with an unmonitored group; account-level enable/disable writes remain
  blocked and the recovery ledger records the test-only outcome.
- Scoring cycles no longer fail when retention has redacted an old evidence `source_event_id`.
- Guardian's managed group scope is now derived from every group present in the snapshot —
  channel bindings plus account bindings — instead of only usage-log channel bindings.
  Accounts shared with vip variant groups or groups without a bound channel are now tested
  and restored instead of being skipped as shared with unmonitored scope. Explicit
  `managed_group_ids`/`excluded_group_ids` policy scope is still honored.
- Sub2API account runtime timestamps returned as RFC3339 text instead of Unix epoch numbers
  no longer make the whole account state read fail closed; both encodings are normalized.
- Account restore now clears Sub2API's server-owned runtime protection (`recover-state`)
  before re-enabling, and a stale or future runtime deadline no longer hides a non-active
  account status from the recovery pass. A leftover `error_message` no longer marks Guardian
  ownership of a human pause; only `temp_unschedulable_reason` does.

## [0.1.0] - 2026-08-23

### Added

- Deployment-neutral Streamable HTTP MCP service with scoped API-key authentication.
- Durable SQLite scheduler, jobs, leases, bindings, notification outbox, and audit events.
- Channel probing plus existing Sub2API recovery and account-maintenance invariants.
- Durable video generation with queue count, polling, cancellation, and restart safety.
- Platform-neutral delivery through every bot adapter registered in LangBot.
- Signed actor bridge for identity-sensitive bind/unbind/account commands.
- Structured JSON logging, Prometheus metrics, health checks, tests, and hardened Docker files.
- GitHub Actions quality gates, local-only image deployment, immutable server releases, and manual rollback.

### Security

- Secrets are environment-only and excluded from tool results and structured logs.
- Administrator details cannot target group delivery destinations.
- Actor requests use HMAC signatures, a bounded timestamp window, and one-time nonces.
- Credential-bearing upstream HTTP redirects remain disabled.
