"""Hashing, signing and encryption primitives.

* High-entropy tokens (sessions) are stored as a plain SHA-256 digest.
* Low-entropy codes (login codes, handover codes) are stored as a keyed HMAC,
  so a database leak alone cannot be brute-forced back to the code.
* Staff passwords use Argon2id (blueprint H.2).
* Sensitive columns use Fernet with a key held outside the database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from markx.core.config import get_config

_password_hasher = PasswordHasher()  # argon2-cffi defaults to Argon2id

MIN_STAFF_PASSWORD_LENGTH = 12


def new_token() -> str:
    """A URL-safe random token with 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def keyed_hash(purpose: str, *parts: str) -> bytes:
    """HMAC-SHA256 over the parts, domain-separated by purpose."""
    key = get_config().secret_key.encode()
    message = "\x1f".join((purpose, *parts)).encode()
    return hmac.new(key, message, hashlib.sha256).digest()


def sign(purpose: str, *parts: str, length: int = 22) -> str:
    """A short URL-safe signature. 22 base64 characters carry 132 bits."""
    digest = keyed_hash(purpose, *parts)
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:length]


def constant_time_equal(a: bytes | str, b: bytes | str) -> bool:
    a_bytes = a.encode() if isinstance(a, str) else a
    b_bytes = b.encode() if isinstance(b, str) else b
    return hmac.compare_digest(a_bytes, b_bytes)


def derive_numeric_code(purpose: str, *parts: str, digits: int = 6) -> str:
    """A decimal code derived from the server secret, so it never needs storing.

    Used for handover codes: the buyer's page can show the code again at any
    time, yet the database holds nothing that reveals it.
    """
    digest = keyed_hash(purpose, *parts)
    return f"{int.from_bytes(digest[:8], 'big') % 10**digits:0{digits}d}"


def hash_password(password: str) -> str:
    if len(password) < MIN_STAFF_PASSWORD_LENGTH:
        raise ValueError(f"password must have at least {MIN_STAFF_PASSWORD_LENGTH} characters")
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _fernet() -> Fernet:
    return Fernet(get_config().encryption_key.encode())


def encrypt_text(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode())


def decrypt_text(cipher: bytes) -> str:
    try:
        return _fernet().decrypt(bytes(cipher)).decode()
    except InvalidToken as exc:
        raise ValueError("stored value cannot be decrypted with the configured key") from exc
