"""Signed session cookies for the Guardian console.

The console used to ask the operator to paste an MCP API token into the page.
Now it takes a username and password once and keeps a signed, expiring cookie,
so the raw token never has to be handled in the browser.

The cookie is a compact ``base64(payload).base64(hmac)`` envelope, signed with
``SUB2API_MCP_SESSION_SECRET``.  There is no server-side session table: the
signature and the embedded expiry are the whole state, which keeps the console
working across restarts and replicas without another store to run.

The password is verified against a scrypt hash, so the plaintext is never read
back out of configuration.  ``scripts/hash_console_password.py`` produces one.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

__all__ = [
    "COOKIE_NAME",
    "SessionCodec",
    "hash_password",
    "verify_password",
]

COOKIE_NAME = "sub2api_guardian_session"
_VERSION = 1

# scrypt parameters.  n=2**14 keeps the hash well above a second on a normal
# machine while staying cheap enough for an interactive login.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 32
_SALT_BYTES = 16


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Return a ``scrypt$<params>$<salt>$<hash>`` string for ``password``."""

    if not password:
        raise ValueError("password must not be empty")
    material = salt if salt is not None else secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=material,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LENGTH,
    )
    encoded_salt = base64.b64encode(material).decode("ascii")
    encoded_hash = base64.b64encode(derived).decode("ascii")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${encoded_salt}${encoded_hash}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of ``password`` against a stored hash."""

    if not password or not encoded:
        return False
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = (int(parts[1]), int(parts[2]), int(parts[3]))
        salt = base64.b64decode(parts[4], validate=True)
        expected = base64.b64decode(parts[5], validate=True)
    except (ValueError, binascii.Error):
        return False
    if n < 2 or r < 1 or p < 1:
        return False
    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(derived, expected)


@dataclass(frozen=True, slots=True)
class Session:
    username: str
    issued_at: datetime
    expires_at: datetime


class SessionCodec:
    """Issue and verify the console session cookie."""

    def __init__(
        self,
        secret: str,
        *,
        password_hash: str,
        username: str,
        ttl_seconds: int,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        self._key = secret.encode("utf-8")
        self._password_hash = password_hash
        self._username = username
        self._ttl = timedelta(seconds=ttl_seconds)

    @property
    def username(self) -> str:
        return self._username

    def check_credentials(self, username: str, password: str) -> bool:
        """Verify a login attempt without leaking which half was wrong."""

        username_ok = hmac.compare_digest(username.strip().casefold(), self._username.casefold())
        password_ok = verify_password(password, self._password_hash)
        return username_ok and password_ok

    @staticmethod
    def _b64encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _b64decode(text: str) -> bytes:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    def _sign(self, payload: bytes) -> str:
        return self._b64encode(hmac.new(self._key, payload, hashlib.sha256).digest())

    def issue(self, username: str, *, now: datetime | None = None) -> tuple[str, Session]:
        issued = (now or datetime.now(UTC)).astimezone(UTC)
        expires = issued + self._ttl
        payload = json.dumps(
            {
                "v": _VERSION,
                "u": username,
                "iat": int(issued.timestamp()),
                "exp": int(expires.timestamp()),
                # A random nonce keeps two sessions issued in the same second
                # from producing byte-identical cookies.
                "n": secrets.token_urlsafe(12),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        token = f"{self._b64encode(payload)}.{self._sign(payload)}"
        return token, Session(username=username, issued_at=issued, expires_at=expires)

    def verify(self, token: str, *, now: datetime | None = None) -> Session | None:
        """Return the session a cookie represents, or ``None`` when invalid."""

        if not token or token.count(".") != 1:
            return None
        encoded_payload, encoded_signature = token.split(".", 1)
        try:
            payload = self._b64decode(encoded_payload)
            supplied = self._b64decode(encoded_signature)
        except (ValueError, binascii.Error):
            return None
        expected = hmac.new(self._key, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            return None
        try:
            data = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or data.get("v") != _VERSION:
            return None
        username = data.get("u")
        issued = data.get("iat")
        expires = data.get("exp")
        if not isinstance(username, str) or not username:
            return None
        if isinstance(issued, bool) or not isinstance(issued, int):
            return None
        if isinstance(expires, bool) or not isinstance(expires, int):
            return None
        if not hmac.compare_digest(username.casefold(), self._username.casefold()):
            return None
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        if moment.timestamp() >= expires:
            return None
        return Session(
            username=username,
            issued_at=datetime.fromtimestamp(issued, tz=UTC),
            expires_at=datetime.fromtimestamp(expires, tz=UTC),
        )
