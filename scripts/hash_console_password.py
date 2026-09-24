#!/usr/bin/env python3
"""Print a console password hash for SUB2API_MCP_CONSOLE_PASSWORD_HASH.

The console stores only a scrypt hash of the admin password, so the plaintext
never lands in a config file or an image layer.

Usage::

    python3 scripts/hash_console_password.py 'admin@123'
    python3 scripts/hash_console_password.py        # prompts, input hidden
"""

from __future__ import annotations

import getpass
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from sub2api_mcp.session import hash_password  # noqa: E402


def main() -> int:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("console password: ")
        if password != getpass.getpass("confirm: "):
            print("passwords do not match", file=sys.stderr)
            return 2
    if not password:
        print("password must not be empty", file=sys.stderr)
        return 2
    print(f"SUB2API_MCP_CONSOLE_PASSWORD_HASH={hash_password(password)}")
    print(f"SUB2API_MCP_SESSION_SECRET={__import__('secrets').token_urlsafe(48)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
