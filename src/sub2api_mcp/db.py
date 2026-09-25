"""Async PostgreSQL connection pool and transaction helpers.

Both repositories keep their public async method signatures; this module
replaces the per-method ``sqlite3.connect`` + ``BEGIN IMMEDIATE`` pattern with
an ``asyncpg`` pool plus explicit ``transaction()`` blocks.

Placeholder style is rewritten from ``?`` to ``$1..$n`` in SQL strings by
:func:`adapt` so the existing query text stays readable and diffable.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Protocol

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

__all__ = [
    "Database",
    "TransactionProtocol",
    "adapt",
    "placeholders",
    "renumber",
    "row_to_dict",
    "rowcount",
]


class TransactionProtocol(Protocol):
    """The subset of ``asyncpg`` connection used by the repositories."""

    async def execute(self, query: str, *args: Any) -> str: ...

    async def fetch(self, query: str, *args: Any) -> Sequence[Any]: ...

    async def fetchrow(self, query: str, *args: Any) -> Any | None: ...

    async def fetchval(self, query: str, *args: Any, column: int = 0) -> Any: ...

    async def executemany(self, query: str, args: Sequence[Sequence[Any]]) -> None: ...


def adapt(query: str) -> str:
    """Rewrite ``?`` placeholders to Postgres ``$1..$n`` positional ones.

    A ``?`` inside a single-quoted literal is left untouched.  The codebase
    never places a literal ``?`` in a string argument, so a simple scan that
    tracks quote state is sufficient and avoids the pitfalls of a blind
    substitution.
    """

    out: list[str] = []
    index = 0
    in_quote = False
    position = 0
    while position < len(query):
        character = query[position]
        if character == "'":
            in_quote = not in_quote
            out.append(character)
        elif character == "?" and not in_quote:
            index += 1
            out.append(f"${index}")
        else:
            out.append(character)
        position += 1
    return "".join(out)


def placeholders(start: int, count: int) -> str:
    """Return ``$start, $start+1, ...`` for ``IN (...)`` expansions."""

    return ", ".join(f"${index}" for index in range(start, start + count))


def renumber(query: str, offset: int) -> str:
    """Shift ``$n`` references in ``query`` by ``offset``.

    Lets a caller assemble a ``WHERE`` clause from several fragments and then
    offset the placeholders once the final parameter order is known.
    """

    if offset == 0:
        return query
    return re.sub(
        r"\$(\d+)",
        lambda match: f"${int(match.group(1)) + offset}",
        query,
    )


def rowcount(status: str | None) -> int:
    """Extract the affected row count from an ``asyncpg`` command status.

    ``asyncpg`` returns strings such as ``"UPDATE 3"`` or ``"DELETE 0"`` where
    SQLite exposed ``Cursor.rowcount``.  Returning 0 for an unparsable status
    keeps callers that only log the number safe.
    """

    if not status:
        return 0
    _, _, tail = status.rpartition(" ")
    try:
        return int(tail)
    except ValueError:
        return 0


def row_to_dict(row: Any | None) -> dict[str, Any] | None:
    """Normalize an ``asyncpg.Record`` into a plain ``dict``.

    The repositories previously used ``sqlite3.Row`` and indexed rows by column
    name; ``asyncpg.Record`` supports the same access pattern, but returning a
    real dict keeps the JSON serialization paths identical.
    """

    if row is None:
        return None
    return dict(row)


class Database:
    """Owns the ``asyncpg`` pool and exposes transaction-scoped access."""

    def __init__(self, dsn: str, *, min_size: int = 2, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any = None

    @property
    def pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("the database pool has not been initialized")
        return self._pool

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(  # pyright: ignore[reportUnknownMemberType]
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=30,
        )

    async def close(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[Any]:
        """A pooled connection with no surrounding transaction.

        Used for single statements, which Postgres wraps in an implicit
        transaction on their own.
        """

        async with self.pool.acquire() as connection:
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Any]:
        """A pooled connection inside an explicit transaction.

        This replaces SQLite's ``BEGIN IMMEDIATE``.  Isolation is the Postgres
        default (READ COMMITTED); callers that need to serialize concurrent
        writers must take an explicit lock (``SELECT ... FOR UPDATE``) — see
        the lease and snapshot-claim methods.
        """

        async with self.pool.acquire() as connection, connection.transaction():
            yield connection

    async def execute(self, query: str, *args: Any) -> str:
        async with self.acquire() as connection:
            return await connection.execute(adapt(query), *args)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        async with self.acquire() as connection:
            rows = await connection.fetch(adapt(query), *args)
        return [dict(row) for row in rows]

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        async with self.acquire() as connection:
            row = await connection.fetchrow(adapt(query), *args)
        return dict(row) if row is not None else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self.acquire() as connection:
            return await connection.fetchval(adapt(query), *args)
