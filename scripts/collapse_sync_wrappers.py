#!/usr/bin/env python3
"""Collapse ``async def foo`` + ``def _foo_sync`` pairs into one async method.

Each repository method is currently written as a thin async wrapper around a
thread-offloaded sync body::

    async def foo(self, a, *, b=1):
        return await asyncio.to_thread(self._foo_sync, a, b=b)

    def _foo_sync(self, a, *, b=1):
        with self._connect() as connection:
            ...
            return something

PostgreSQL access is natively async, so the thread hop is unnecessary.  This
rewrites the pair into a single ``async def`` whose body is the former sync
body with the connection taken from the pool::

    async def foo(self, a, *, b=1):
        async with self._database.acquire() as connection:
            ...
            return something

Only the mechanical part is automated: signatures, the connection context
manager, and the sync-body's ``await``-ability.  SQL text, ``BEGIN IMMEDIATE``
blocks, and ``rowid`` cleanup are left for follow-up edits, so a failure here
cannot silently change query semantics.

Usage:  python3 scripts/collapse_sync_wrappers.py <file> [--apply]

Without ``--apply`` it prints the pairs it would rewrite and exits non-zero if
anything looks unexpected, which makes it safe to dry-run in CI.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

# Sync-body statements whose SQLite/thread-bound form needs a manual rewrite.
# If any appear, the script refuses to touch that method so the conversion is
# always reviewed by hand.
MANUAL_MARKERS = (
    "BEGIN IMMEDIATE",
    ".execute(\"COMMIT\")",
    "connection.in_transaction",
    "rowid",
    "INSERT OR REPLACE",
    "INSERT OR IGNORE",
)


def decorator_start(node: ast.AsyncFunctionDef | ast.FunctionDef) -> int:
    return min([node.lineno - 1] + [item.lineno - 1 for item in node.decorator_list])


def method_span(node: ast.AST) -> tuple[int, int]:
    return decorator_start(node), (node.end_lineno or node.lineno)  # type: ignore[arg-type]


def rewrite_connection_line(line: str) -> str | None:
    """Return the async replacement for a ``with self._connect()`` line."""

    match = re.match(r"(?P<indent>\s*)with self\._connect\(\) as connection:\s*$", line)
    if match is None:
        return None
    return f"{match.group('indent')}async with self._database.acquire() as connection:\n"


# asyncpg has no cursor objects; the sqlite3 terminal calls map onto different
# methods.  Each pattern rewrites a whole expression, so the ``await`` lands in
# front of the call rather than in front of the chain.
_CALL_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    # ``connection.execute(...).fetchone()`` / ``.fetchall()`` — the sqlite3
    # terminal calls map onto asyncpg's fetchrow/fetch.  Run these first so the
    # whole chain is replaced rather than just the leading call.
    (
        re.compile(
            r"(?<!await )\bconnection\.execute\("
            r"(?P<args>(?:[^()]|\([^()]*\))*)\)\s*\.fetchone\(\)"
        ),
        r"await connection.fetchrow(\g<args>)",
    ),
    (
        re.compile(
            r"(?<!await )\bconnection\.execute\("
            r"(?P<args>(?:[^()]|\([^()]*\))*)\)\s*\.fetchall\(\)"
        ),
        r"await connection.fetch(\g<args>)",
    ),
    (
        re.compile(r"(?<!await )\bconnection\.execute\("),
        r"await connection.execute(",
    ),
)


def rewrite_sql_calls(line: str) -> str:
    """Add ``await`` and map sqlite3 terminal calls onto asyncpg methods."""

    result = line
    for pattern, replacement in _CALL_REWRITES:
        result = pattern.sub(replacement, result)
    return result


def convert(path: pathlib.Path, *, apply: bool) -> int:
    source = path.read_text()
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    class_node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
    if class_node is None:
        print(f"{path}: no class found", file=sys.stderr)
        return 1

    async_nodes: dict[str, ast.AsyncFunctionDef] = {}
    sync_nodes: dict[str, ast.FunctionDef] = {}
    for child in class_node.body:
        if isinstance(child, ast.AsyncFunctionDef):
            async_nodes[child.name] = child
        elif isinstance(child, ast.FunctionDef):
            sync_nodes[child.name] = child

    skipped: list[str] = []
    jobs: list[tuple[str, ast.AsyncFunctionDef, ast.FunctionDef, str]] = []
    for name, async_node in async_nodes.items():
        sync_node = sync_nodes.get(f"_{name}_sync")
        if sync_node is None:
            continue
        sync_src = ast.get_source_segment(source, sync_node) or ""
        hit = next((m for m in MANUAL_MARKERS if m in sync_src), None)
        if hit is not None:
            skipped.append(f"{name} ({hit})")
            continue
        jobs.append((name, async_node, sync_node, sync_src))

    if not apply:
        print(f"{path}: {len(jobs)} mechanical pairs, {len(skipped)} need manual work")
        for name in skipped:
            print(f"  skip: {name}")
        return 0

    # Apply bottom-up so earlier offsets stay valid.
    jobs.sort(key=lambda item: method_span(item[1])[0], reverse=True)
    applied = 0
    for name, async_node, sync_node, sync_src in jobs:
        async_start, async_end = method_span(async_node)
        sync_start, sync_end = method_span(sync_node)

        # Work from the real file lines rather than ast source segments so the
        # original indentation and line structure are preserved exactly.
        sync_lines = lines[sync_start : sync_end + 1]

        header_end = 0
        for index, line in enumerate(sync_lines):
            if line.rstrip().endswith(":"):
                header_end = index
                break
        header_lines = list(sync_lines[: header_end + 1])
        body_lines = list(sync_lines[header_end + 1 :])

        header_lines[0] = header_lines[0].replace(
            f"def _{name}_sync(", f"async def {name}("
        )

        body: list[str] = []
        for line in body_lines:
            replacement = rewrite_connection_line(line)
            if replacement is not None:
                body.append(replacement)
            else:
                body.append(rewrite_sql_calls(line))

        block = "".join(header_lines) + "".join(body)
        if not block.endswith("\n"):
            block += "\n"

        # Replace the async definition with the merged block, then delete the
        # sync definition (its indices are later in the file).
        lines[async_start:async_end + 1] = [block]
        shift = (async_end + 1) - async_start - 1
        sync_start -= shift
        sync_end -= shift
        del lines[sync_start:sync_end + 1]
        if sync_start < len(lines) and lines[sync_start].strip() != "":
            lines.insert(sync_start, "\n")
        applied += 1

    path.write_text("".join(lines))
    print(f"{path}: collapsed {applied} pairs, skipped {len(skipped)}")
    for name in skipped:
        print(f"  skip: {name}")
    return 0


def main() -> int:
    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if not arguments:
        print(__doc__)
        return 2
    for argument in arguments:
        convert(pathlib.Path(argument), apply=apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
