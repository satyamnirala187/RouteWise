"""Password hashing, session tokens and CSRF primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id with argon2-cffi's RFC 9106 "low memory" defaults (t=3, m=64 MiB, p=4).
_hasher = PasswordHasher()
# Verified against when the username is unknown, so response time does not reveal accounts.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(24))

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> tuple[bool, str | None]:
    """Returns (ok, new_hash_if_rehash_needed). Always does one Argon2 verification."""
    try:
        _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, None
    if stored_hash is None:
        return False, None
    return True, (_hasher.hash(password) if _hasher.check_needs_rehash(stored_hash) else None)


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def token_digest(secret_key: str, token: str) -> str:
    """Only this keyed digest is stored, so a database leak does not yield usable cookies."""
    return hmac.new(secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def constant_time_equal(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode(), b.encode())
