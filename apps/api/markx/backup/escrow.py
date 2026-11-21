"""A safe copy of the secrets a total-loss recovery needs (BK-5, D-105).

A backup set holds the data, never the application's own secrets. Without
the original `MARKX_ENCRYPTION_KEY` the staff authenticator secrets in a
restored database cannot be decrypted, so no staff member can sign in; without
the original `MARKX_SECRET_KEY` handover codes and signed links change; the
database passwords and the site's certificate key are needed to bring a new
server up. This module makes ONE file, the **secrets copy** ("escrow"), that
holds them, so they can be kept away from the server:

- The secrets are read from the server's settings folder (`/etc/markx`) and
  certificate folder, kept in memory only, and encrypted to the backup's
  **recovery key** (MXB2, the same encryption as every backup file) before
  anything is written. The server holds only the public half: it can make a
  copy, never open one. Nothing secret is ever written in plain form, put in
  a log, printed or passed as an argument; only file NAMES and sizes are.
- The envelope (names, sizes, when, where) is signed with the backup's
  signing key, so a copy made by anyone else, or edited, is refused.
- It refuses to make a copy without `api.env` (with `MARKX_SECRET_KEY` and
  `MARKX_ENCRYPTION_KEY`) and `postgres.env` (the four database passwords),
  with a placeholder still in them, or holding a recovery key (the copy is
  encrypted TO that key: it must never be inside).
- A copy can be uploaded to the backup bucket (`escrow/`), where the object
  lock keeps it, beside the sets it belongs to. Who keeps the other copy is
  the founder's decision F-19: with the recovery key, never with the server.

Opening a copy needs the recovery key, so it happens on a recovery machine
only, never on staging or production (BK-2), exactly like a restore.

PROVISIONAL (P-105-4): the list of files in a copy, `ITEMS` below.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
import secrets
import stat
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from markx.backup import crypto
from markx.backup.crypto import (
    RECOVERY_PRIVATE,
    RecipientKey,
    RecoveryKey,
    SignatureError,
    SignerKey,
    SigningKey,
)

ESCROW_FORMAT = "markx-secrets-escrow/1"
ESCROW_PREFIX = "escrow"
ESCROW_NAME = re.compile(r"^markx-secrets-\d{8}T\d{6}Z-[0-9a-f]{8}\.json$")
MAX_ITEM_BYTES = 1024 * 1024
MAX_ESCROW_BYTES = 32 * 1024 * 1024

# What a copy holds (PROVISIONAL, P-105-4), by its name in the copy. The
# certificate files come from the certificate folder; the rest from the
# settings folder. Required items must be there; the others are kept when
# they exist (a server behind a Cloudflare origin certificate has its key too).
REQUIRED_VARIABLES: dict[str, tuple[str, ...]] = {
    "api.env": ("MARKX_SECRET_KEY", "MARKX_ENCRYPTION_KEY"),
    "postgres.env": (
        "POSTGRES_PASSWORD",
        "MARKX_DB_MIGRATOR_PASSWORD",
        "MARKX_DB_APP_PASSWORD",
        "MARKX_DB_READONLY_PASSWORD",
    ),
}
OPTIONAL_SETTINGS = (
    "migrate.env",
    "backup.env",
    "web.env",
    "compose.env",
    "backup-signing.key",
    "backup-public.key",
)
CERTIFICATE_FILES = ("privkey.pem", "fullchain.pem")
ITEMS = (
    *REQUIRED_VARIABLES,
    *OPTIONAL_SETTINGS,
    *(f"tls/{name}" for name in CERTIFICATE_FILES),
)
_PLACEHOLDER = "REPLACE_WITH"


class EscrowRefused(Exception):
    """The copy cannot be made, or cannot be trusted. Says why, never a secret."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def env_values(text: str) -> dict[str, str]:
    """KEY=VALUE lines of a settings file (the Compose env-file format, for
    the simple values MarkX uses): comments and blank lines skipped."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name.strip()] = value
    return values


# -- collecting ---------------------------------------------------------------------------


def _read_item(path: Path) -> bytes:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise EscrowRefused(f"not_a_regular_file:{path.name}")
    if info.st_size > MAX_ITEM_BYTES:
        raise EscrowRefused(f"too_large:{path.name}")
    return path.read_bytes()


def collect_from_folders(settings_dir: Path, tls_dir: Path | None) -> dict[str, bytes]:
    """The items found in the settings folder and the certificate folder."""
    items: dict[str, bytes] = {}
    for name in (*REQUIRED_VARIABLES, *OPTIONAL_SETTINGS):
        path = settings_dir / name
        if path.exists() or path.is_symlink():
            items[name] = _read_item(path)
    if tls_dir is not None:
        for name in CERTIFICATE_FILES:
            path = tls_dir / name
            if path.exists() or path.is_symlink():
                items[f"tls/{name}"] = _read_item(path)
    return items


def collect_from_tar(stream: IO[bytes]) -> dict[str, bytes]:
    """The items of a tar stream (what `deploy.sh escrow-secrets` pipes in:
    never a file on disk). Only regular files with a name from `ITEMS`."""
    items: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                name = member.name.removeprefix("./")
                if name not in ITEMS:
                    raise EscrowRefused(f"unexpected_file:{name[:60]}")
                if not member.isreg():
                    raise EscrowRefused(f"not_a_regular_file:{name}")
                if member.size > MAX_ITEM_BYTES:
                    raise EscrowRefused(f"too_large:{name}")
                handle = archive.extractfile(member)
                if handle is None:
                    raise EscrowRefused(f"unreadable:{name}")
                items[name] = handle.read()
    except tarfile.TarError:
        raise EscrowRefused("not_a_tar_stream") from None
    return items


def problems(items: dict[str, bytes]) -> list[str]:
    """Why these items are not a usable copy: names and setting NAMES only."""
    found: list[str] = []
    for name, variables in REQUIRED_VARIABLES.items():
        if name not in items:
            found.append(f"{name} is missing")
            continue
        values = env_values(items[name].decode("utf-8", errors="replace"))
        for variable in variables:
            value = values.get(variable, "")
            if not value:
                found.append(f"{name} has no {variable}")
            elif _PLACEHOLDER in value:
                found.append(f"{name} still has the example value of {variable}")
    for name, data in items.items():
        if RECOVERY_PRIVATE.encode() in data:
            found.append(f"{name} holds a recovery key, which must never be on the server")
    return found


# -- making a copy --------------------------------------------------------------------------


def escrow_name(now: datetime) -> str:
    return f"markx-secrets-{now.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}.json"


def make_escrow(
    items: dict[str, bytes], *, recipient: RecipientKey, signing: SigningKey, environment: str,
    release: str, now: datetime,
) -> bytes:  # fmt: skip
    """The signed, encrypted copy. The secrets exist in plain form only in
    this process's memory, never on disk."""
    found = problems(items)
    if found:
        raise EscrowRefused("; ".join(found))
    payload = json.dumps(
        {"format": ESCROW_FORMAT,
         "items": {name: base64.b64encode(data).decode("ascii") for name, data in sorted(items.items())}},
        sort_keys=True,
    ).encode("utf-8")  # fmt: skip
    sealed = crypto.encrypt_bytes(recipient, payload)
    del payload
    envelope = {
        "format": ESCROW_FORMAT,
        "created_at": now.astimezone(UTC).isoformat(),
        "environment": environment,
        "release": release,
        "recipient_key_id": recipient.key_id,
        # Names and sizes only: what a person needs to know the copy is whole.
        "items": [{"name": name, "bytes": len(data)} for name, data in sorted(items.items())],
        "ciphertext_sha256": hashlib.sha256(sealed).hexdigest(),
        "ciphertext": base64.b64encode(sealed).decode("ascii"),
    }
    return json.dumps(crypto.sign_document(envelope, signing), indent=1).encode("utf-8")


# -- opening a copy (a recovery machine only) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpenedEscrow:
    envelope: dict[str, Any]
    items: dict[str, bytes]

    def __repr__(self) -> str:  # never the secrets
        return f"OpenedEscrow(items={sorted(self.items)!r})"

    def value(self, item: str, variable: str) -> str | None:
        data = self.items.get(item)
        if data is None:
            return None
        return env_values(data.decode("utf-8", errors="replace")).get(variable)


def read_envelope(data: bytes, signers: list[SignerKey]) -> dict[str, Any]:
    """The signed envelope, checked; nothing decrypted."""
    if len(data) > MAX_ESCROW_BYTES:
        raise EscrowRefused("escrow_too_large")
    try:
        document = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise EscrowRefused("not_a_secrets_copy") from None
    if not isinstance(document, dict):
        raise EscrowRefused("not_a_secrets_copy")
    try:
        body = crypto.verify_document(document, signers)
    except SignatureError as exc:
        raise EscrowRefused(f"signature:{exc}") from None
    if body.get("format") != ESCROW_FORMAT:
        raise EscrowRefused("not_a_secrets_copy")
    return body


def open_escrow(
    data: bytes, *, keys: dict[str, RecoveryKey], signers: list[SignerKey]
) -> OpenedEscrow:
    body = read_envelope(data, signers)
    try:
        sealed = base64.b64decode(str(body["ciphertext"]), validate=True)
    except (KeyError, ValueError, binascii.Error):
        raise EscrowRefused("ciphertext_malformed") from None
    if hashlib.sha256(sealed).hexdigest() != body.get("ciphertext_sha256"):
        raise EscrowRefused("ciphertext_altered")
    try:
        payload = json.loads(crypto.decrypt_bytes(sealed, keys))
        items = {
            str(name): base64.b64decode(value, validate=True)
            for name, value in payload["items"].items()
        }
    except crypto.DecryptionError as exc:
        raise EscrowRefused(f"does_not_decrypt: {exc}") from None
    except (ValueError, KeyError, TypeError, AttributeError, binascii.Error):
        raise EscrowRefused("contents_malformed") from None
    listed = {(i["name"], i["bytes"]) for i in body.get("items", [])}
    if listed != {(name, len(data)) for name, data in items.items()}:
        raise EscrowRefused("contents_do_not_match_the_signed_list")
    return OpenedEscrow(body, items)


def write_items(opened: OpenedEscrow, out: Path) -> list[str]:
    """Write the secrets into a NEW private folder (mode 700, files 600), for
    copying onto a new server. Refuses a folder that holds anything."""
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise EscrowRefused("the output folder must be new or empty")
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    out.chmod(0o700)
    written = []
    for name, data in sorted(opened.items.items()):
        target = out / name
        if target.parent != out:
            target.parent.mkdir(mode=0o700, exist_ok=True)
        fd = target.open("xb")
        with fd:
            target.chmod(0o600)
            fd.write(data)
        written.append(name)
    return written


def decrypts_with(key: str, tokens: list[bytes]) -> tuple[int, int]:
    """How many of these Fernet tokens (the database's encrypted columns)
    decrypt with `key`: (decrypted, total). The plaintext is discarded."""
    from cryptography.fernet import Fernet, InvalidToken

    try:
        fernet = Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return 0, len(tokens)
    ok = 0
    for token in tokens:
        try:
            fernet.decrypt(bytes(token))
            ok += 1
        except InvalidToken:
            continue
    return ok, len(tokens)


def escrow_key(name: str) -> str:
    if not ESCROW_NAME.fullmatch(name):
        raise EscrowRefused("not_a_secrets_copy_name")
    return f"{ESCROW_PREFIX}/{name}"


def read_from_destination(
    destination: Any, signers: list[SignerKey], name: str | None = None
) -> tuple[str, bytes]:
    """The newest secrets copy at the destination (or `name`), as first
    written: a copy is written once, so when a later, different version
    exists the OLDEST one whose signature verifies is used (RN-1)."""
    if name is None:
        names = sorted(
            obj.key.rsplit("/", 1)[-1] for obj in destination.list(f"{ESCROW_PREFIX}/")
            if ESCROW_NAME.fullmatch(obj.key.rsplit("/", 1)[-1])
        )  # fmt: skip
        if not names:
            raise EscrowRefused("no secrets copy at the destination")
        name = names[-1]
    key = escrow_key(name)
    try:
        versions = sorted(destination.versions(key), key=lambda v: v.last_modified)
    except Exception:  # the key may not list versions: the current one only
        versions = []
    for version in versions or [None]:
        version_id = None if version is None or version.is_latest else version.version_id
        try:
            data = destination.read_bytes(key, limit=MAX_ESCROW_BYTES, version_id=version_id)
            read_envelope(data, signers)
        except EscrowRefused:
            continue
        except Exception as exc:
            if type(exc).__name__ == "ObjectMissing":
                continue
            raise
        return name, data
    raise EscrowRefused("no version of the secrets copy is signed by a trusted key")


def read_stdin_tar(stream: IO[bytes]) -> dict[str, bytes]:
    """`collect_from_tar` over a non-seekable stream, read into memory."""
    return collect_from_tar(io.BytesIO(stream.read(MAX_ESCROW_BYTES + 1)))
