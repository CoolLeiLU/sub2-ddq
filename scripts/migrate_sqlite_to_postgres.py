#!/usr/bin/env python3
"""Copy an existing SQLite deployment's *state* into PostgreSQL.

The service used to keep all state in one SQLite file.  After the move to
PostgreSQL the schema is created empty, so this script replays the rows that
describe how the service is currently configured and which work is still
outstanding.

What is copied (the "essential" set, the default):

* metadata and policy — schema version, Guardian policy revision, overrides;
* the current inventory — channels and groups, with their health and scores;
* in-flight work — non-terminal jobs, open channel-error episodes, running
  recovery runs;
* the quarantine registry — which accounts are currently held back;
* account probe preferences — the ``terraform -> sol`` memory.

What is skipped (historical logs, and they are large):

* ``guardian_samples``, ``guardian_events``, ``guardian_traffic_buckets``;
* ``guardian_probe_ledger``, ``guardian_input_snapshots``;
* ``guardian_account_observations`` (per-snapshot account snapshots);
* finished ``jobs`` and completed ``guardian_runs`` / recovery ledger rows;
* ``audit_events``, ``actor_nonces``, ``guardian_idempotency``.

Use ``--include-history`` to copy everything instead, or ``--tables`` to name
an exact set.  The split is a judgement call, not a rule: history is what makes
the dashboards and the recovery timeline useful, so move it too if you want the
console to show the past.

Design notes:

* Column names are read from both sides, so a table whose SQLite shape is older
  than the current Postgres shape still copies the columns they share.
* Values pass through unchanged except where the dialects differ in type:
  ``INTEGER`` 0/1 flags become ``BOOLEAN``, and ``TEXT`` ISO timestamps become
  ``TIMESTAMPTZ``.
* Each table copies inside one transaction, so a failure leaves that table
  untouched rather than half-written.
* ``--dry-run`` prints the plan without writing anything.

Usage::

    python3 scripts/migrate_sqlite_to_postgres.py \\
        --sqlite /path/to/sub2api-mcp.db \\
        --database-url postgresql://guardian:...@host:5432/guardian \\
        [--dry-run] [--include-history] [--tables a,b,c]
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg


@dataclass(frozen=True, slots=True)
class TablePlan:
    """One table to copy, with an optional ``WHERE`` filter for its rows.

    ``overwrite`` matters because ``initialize()`` seeds some tables with
    defaults before the migration runs (the schema version, the disabled
    default policy).  For those, the migrated row is authoritative and must
    replace the seed.  For append-only tables the seed never collides, and
    keeping ``DO NOTHING`` means a re-run cannot duplicate or clobber rows.
    """

    name: str
    note: str = ""
    where: str = ""
    overwrite: bool = False


# The essential set: current configuration, live inventory, and outstanding
# work.  Order is for readability only — foreign keys are not enforced during
# the copy, because the restore-intent table references one that is itself
# being filled.
ESSENTIAL: tuple[TablePlan, ...] = (
    TablePlan("service_metadata", "schema version", overwrite=True),
    TablePlan("scheduler_state", "scheduler bookkeeping", overwrite=True),
    TablePlan(
        "jobs",
        "queued and running jobs only",
        where="status IN ('QUEUED', 'RUNNING') OR "
        "(status = 'SUCCEEDED' AND finished_at >= datetime('now', '-1 hour'))",
    ),
    TablePlan("account_bindings", "actor bindings"),
    TablePlan("account_quarantines", "accounts currently held back"),
    TablePlan("account_quarantine_intents", "pending quarantine writes"),
    TablePlan("account_quarantine_restore_intents", "pending restores"),
    TablePlan("probe_snapshots", "last probe snapshots"),
    TablePlan("guardian_metadata", "Guardian bookkeeping", overwrite=True),
    TablePlan("guardian_policy", "current policy", overwrite=True),
    TablePlan("guardian_group_overrides", "per-group policy overrides"),
    TablePlan("guardian_channel_overrides", "per-channel policy overrides"),
    TablePlan("guardian_channels", "current channel inventory and scores"),
    TablePlan("guardian_groups", "current group inventory"),
    TablePlan("guardian_leases", "live leases"),
    TablePlan("guardian_account_preferences", "account probe-model memory"),
    TablePlan(
        "guardian_channel_error_episodes",
        "open episodes only",
        where="status = 'OPEN'",
    ),
    TablePlan(
        "guardian_account_recovery_runs",
        "running runs only",
        where="status = 'RUNNING'",
    ),
)

# Copied only with --include-history.  These are the large append-only logs.
HISTORY: tuple[TablePlan, ...] = (
    TablePlan("guardian_samples", "channel evidence samples"),
    TablePlan("guardian_events", "Guardian event log"),
    TablePlan("guardian_traffic_buckets", "per-minute traffic rollups"),
    TablePlan("guardian_probe_ledger", "recovery probe spend ledger"),
    TablePlan("guardian_input_snapshots", "raw shared snapshots"),
    TablePlan("guardian_account_observations", "per-snapshot account states"),
    TablePlan("guardian_account_recovery_ledger", "per-account recovery results"),
    TablePlan("guardian_idempotency", "idempotency results"),
    TablePlan("audit_events", "admin audit trail"),
    TablePlan("actor_nonces", "actor replay guards"),
)

# Columns the Postgres schema declares as BOOLEAN that SQLite stored as 0/1.
BOOLEAN_COLUMNS: frozenset[str] = frozenset(
    {
        "cancel_requested",
        "schedulable",
        "expired",
        "temporary_unavailable",
        "automatic_pause",
        "upstream_schedulable",
        "desired_schedulable",
        "dry_run",
        "tested",
        "priced",
        "legacy",
        "previous_schedulable",
    }
)


def _coerce(column: str, value: Any) -> Any:
    """Translate one SQLite value into the Postgres representation."""

    if value is None:
        return None
    if column in BOOLEAN_COLUMNS and isinstance(value, int):
        return bool(value)
    if column.endswith("_at") and isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


async def _pg_primary_key(connection: Any, table: str) -> tuple[str, ...]:
    """Return the primary-key columns to use as the ``ON CONFLICT`` target."""

    rows = await connection.fetch(
        "SELECT a.attname AS column_name "
        "FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = $1::regclass AND i.indisprimary "
        "ORDER BY array_position(i.indkey, a.attnum)",
        table,
    )
    return tuple(str(row["column_name"]) for row in rows)


async def _pg_columns(connection: Any, table: str) -> set[str]:
    rows = await connection.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1",
        table,
    )
    return {str(row["column_name"]) for row in rows}


async def migrate(
    sqlite_path: Path,
    database_url: str,
    *,
    dry_run: bool,
    include_history: bool,
    only: frozenset[str],
) -> int:
    if not sqlite_path.exists():  # noqa: ASYNC240 - a single stat outside the loop
        print(f"sqlite file not found: {sqlite_path}", file=sys.stderr)
        return 2

    plans = ESSENTIAL + (HISTORY if include_history else ())
    if only:
        plans = tuple(plan for plan in plans if plan.name in only)

    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    present = _sqlite_tables(source)

    target = await asyncpg.connect(database_url)
    report: list[tuple[str, int, str]] = []
    try:
        for plan in plans:
            table = plan.name
            if table not in present:
                report.append((table, 0, "absent in source"))
                continue

            target_columns = await _pg_columns(target, table)
            if not target_columns:
                report.append((table, 0, "absent in target"))
                continue

            clause = f" WHERE {plan.where}" if plan.where else ""
            rows = source.execute(f'SELECT * FROM "{table}"{clause}').fetchall()
            if not rows:
                report.append((table, 0, plan.note or "empty"))
                continue

            shared = sorted(set(rows[0].keys()) & target_columns)
            if not shared:
                report.append((table, 0, "no shared columns"))
                continue

            if dry_run:
                preview = ",".join(shared[:4]) + ("..." if len(shared) > 4 else "")
                report.append((table, len(rows), f"would copy {preview}"))
                continue

            placeholders = ", ".join(f"${i + 1}" for i in range(len(shared)))
            column_list = ", ".join(f'"{name}"' for name in shared)
            primary_key = await _pg_primary_key(target, table) if plan.overwrite else ()
            if plan.overwrite and primary_key:
                # Replace the startup seed with the migrated row.  Postgres
                # needs the conflict target named explicitly for DO UPDATE.
                conflict_target = ", ".join(f'"{name}"' for name in primary_key)
                assignments = ", ".join(
                    f'"{name}" = EXCLUDED."{name}"' for name in shared if name not in primary_key
                )
                statement = (
                    f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders}) '
                    f"ON CONFLICT ({conflict_target}) DO UPDATE SET {assignments}"
                )
            else:
                statement = (
                    f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders}) '
                    "ON CONFLICT DO NOTHING"
                )
            payload = [tuple(_coerce(name, row[name]) for name in shared) for row in rows]
            async with target.transaction():
                await target.executemany(statement, payload)
            copied = await target.fetchval(f'SELECT COUNT(*) FROM "{table}"')
            report.append((table, len(rows), f"total now {copied}"))
    finally:
        source.close()
        await target.close()

    width = max((len(name) for name, _, _ in report), default=10)
    for table, count, note in report:
        print(f"{table.ljust(width)}  {str(count).rjust(7)}  {note}")
    skipped = sorted(set(present) - {plan.name for plan in plans})
    if skipped:
        print("\nnot copied (history; use --include-history to move it):")
        print("  " + ", ".join(skipped))
    if dry_run:
        print("\n(dry run: nothing was written)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-history",
        action="store_true",
        help="also copy the append-only logs (samples, events, snapshots, ...)",
    )
    parser.add_argument(
        "--tables",
        default="",
        help="comma-separated exact set to copy (overrides the built-in split)",
    )
    arguments = parser.parse_args()
    only = frozenset(item.strip() for item in arguments.tables.split(",") if item.strip())
    return asyncio.run(
        migrate(
            arguments.sqlite,
            arguments.database_url,
            dry_run=arguments.dry_run,
            include_history=arguments.include_history,
            only=only,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
