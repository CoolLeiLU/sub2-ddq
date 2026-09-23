#!/usr/bin/env python3
"""Convert the residual ``_*_sync`` transaction methods to asyncpg.

Every remaining method in the small repository matches one shape:

    async def foo(self, ...):
        return await asyncio.to_thread(self._foo_sync, a, b=c)

    def _foo_sync(self, a, b):
        <validation, possibly using locals>
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            ...
            connection.execute("COMMIT")
            return X
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        <optional tail>

The rewrite merges the pair into a single ``async def`` and replaces the
scaffolding with ``async with self._database.transaction() as connection:``.
The call surface is mapped in the same pass:

    connection.execute(SQL, args...).fetchone()  -> await connection.fetchrow(SQL, args...)
    connection.execute(SQL, args...).fetchall()  -> await connection.fetch(SQL, args...)
    connection.execute(SQL, args...)             -> await connection.execute(SQL, args...)
    result.rowcount                              -> _rowcount(result)
    ?                                            -> $n

Only these mechanical edits are applied; SQL text and ordering decisions are
preserved verbatim so the diff stays reviewable.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

METHODS = ("fetch", "fetchrow", "fetchval", "execute")


def convert_placeholders_fragment(text: str) -> str:
    """Renumber ``?`` to ``$n`` within one SQL call fragment."""

    out: list[str] = []
    counter = 0
    in_quote = False
    for character in text:
        if character == "'":
            in_quote = not in_quote
            out.append(character)
        elif character == "?" and not in_quote:
            counter += 1
            out.append(f"${counter}")
        else:
            out.append(character)
    return "".join(out)


def rewrite_calls(body: str) -> str:
    """Add ``await`` and map sqlite3 terminal calls onto asyncpg."""

    # 1. chained fetchone/fetchall (single- or multi-line)
    chained_one = re.compile(
        r"(?<!await )\bconnection\.execute\("
        r"(?P<args>(?:[^()]|\([^()]*\))*?)\)\s*\.fetchone\(\)",
        re.S,
    )
    chained_all = re.compile(
        r"(?<!await )\bconnection\.execute\("
        r"(?P<args>(?:[^()]|\([^()]*\))*?)\)\s*\.fetchall\(\)",
        re.S,
    )
    body = chained_one.sub(lambda m: f"await connection.fetchrow({m.group('args')})", body)
    body = chained_all.sub(lambda m: f"await connection.fetch({m.group('args')})", body)
    # 2. bare execute
    body = re.sub(r"(?<!await )\bconnection\.execute\(", "await connection.execute(", body)
    # 3. rowcount helper
    body = re.sub(r"\b(\w+)\.rowcount\b", r"_rowcount(\1)", body)
    return body


def convert(text: str) -> tuple[str, int]:
    tree = ast.parse(text)
    class_node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    async_nodes: dict[str, ast.AsyncFunctionDef] = {}
    sync_nodes: dict[str, ast.FunctionDef] = {}
    for child in class_node.body:
        if isinstance(child, ast.AsyncFunctionDef):
            async_nodes[child.name] = child
        elif isinstance(child, ast.FunctionDef):
            sync_nodes[child.name] = child

    lines = text.splitlines(keepends=True)
    jobs = []
    for name, async_node in async_nodes.items():
        sync_node = sync_nodes.get(f"_{name}_sync")
        if sync_node is None:
            continue
        segment = ast.get_source_segment(text, sync_node) or ""
        if "self._connect()" not in segment:
            continue
        jobs.append((name, async_node, sync_node))

    jobs.sort(key=lambda item: item[1].lineno, reverse=True)
    applied = 0
    for name, async_node, sync_node in jobs:
        a_start = async_node.lineno - 1
        s_end = sync_node.end_lineno
        block = lines[a_start:s_end]
        block_text = "".join(block)

        # Build the merged body from the sync node's source.
        sync_segment = ast.get_source_segment(text, sync_node) or ""
        if sync_segment is None:
            continue
        sync_lines = sync_segment.splitlines(keepends=True)
        header_end = next(
            i for i, line in enumerate(sync_lines) if line.rstrip().endswith(":")
        )
        header = list(sync_lines[: header_end + 1])
        header[0] = header[0].replace(f"def _{name}_sync(", f"async def {name}(")
        body_lines = sync_lines[header_end + 1 :]

        merged: list[str] = list(header)
        i = 0
        while i < len(body_lines):
            line = body_lines[i]
            stripped = line.strip()
            indent = line[: len(line) - len(line.lstrip())]

            if stripped == "connection = self._connect()":
                j = i + 1
                while j < len(body_lines) and body_lines[j].strip() == "":
                    j += 1
                if body_lines[j].strip() == "try:":
                    merged.append(f"{indent}async with self._database.transaction() as connection:\n")
                    k = j + 1
                    while k < len(body_lines) and body_lines[k].strip() == "":
                        k += 1
                    assert "BEGIN IMMEDIATE" in body_lines[k], body_lines[k]
                    i = k + 1
                    continue
            if stripped in {'connection.execute("COMMIT")', 'connection.execute("ROLLBACK")'}:
                i += 1
                continue
            if stripped == "except Exception:" and indent == "        ":
                # The scaffolding tail always sits at the method-body indent.
                # Skip everything up to the next statement at that same indent
                # (or the end of the body), which drops except/raise/finally/
                # connection.close() together.
                j = i + 1
                while j < len(body_lines):
                    current = body_lines[j]
                    if current.strip() and (
                        len(current) - len(current.lstrip())
                    ) <= len(indent):
                        break
                    j += 1
                i = j
                continue
            merged.append(line)
            i += 1

        merged_text = "".join(merged)
        merged_text = rewrite_calls(merged_text)
        merged_text = convert_placeholders_fragment(merged_text)
        if not merged_text.endswith("\n"):
            merged_text += "\n"

        lines[a_start:s_end] = [merged_text]
        applied += 1

    return "".join(lines), applied


def main() -> int:
    path = pathlib.Path(sys.argv[1])
    text = path.read_text()
    out, applied = convert(text)
    if "--apply" in sys.argv:
        path.write_text(out)
        print(f"{path}: merged {applied} transaction methods")
    else:
        print(f"{path}: would merge {applied} methods (dry run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
