"""The backup set's manifest (D-094): what the set holds, signed.

The manifest is written last; its presence, a valid signature from a
trusted signer and `status == "complete"` are what make a set a recovery
point. It holds no secret and no file content or file key: counts, sizes,
hashes, the release, table names and the destination's identity. The file
list itself is in the encrypted `files.index.mxb`.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from markx.backup.crypto import (
    FORMAT_NAME,
    SignatureError,
    SignerKey,
    SigningKey,
    sign_document,
    verify_document,
)

MANIFEST_FORMAT = "markx-backup-set/2"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
BACKUP_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"  # written, signed, but must not be restored by default


def set_prefix(backup_id: str) -> str:
    if not BACKUP_ID.fullmatch(backup_id):
        raise ValueError("not a backup id")
    return f"sets/{backup_id}"


def manifest_key(backup_id: str) -> str:
    return f"{set_prefix(backup_id)}/manifest.json"


def blob_key(blob_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", blob_id):
        raise ValueError("not a blob id")
    return f"objects/{blob_id[:2]}/{blob_id}"


def new_backup_id(now: datetime, token: str) -> str:
    return f"{now.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-{token}"


def encode(manifest: dict[str, Any], signing: SigningKey) -> bytes:
    signed = sign_document({"format": MANIFEST_FORMAT, **manifest}, signing)
    return json.dumps(signed, sort_keys=True, indent=2).encode("utf-8")


class ManifestRefused(Exception):
    """The manifest cannot be trusted or does not describe a restorable set."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def decode(data: bytes, signers: list[SignerKey], *, backup_id: str) -> dict[str, Any]:
    """The verified manifest of `backup_id`. Refuses anything unsigned, signed
    by an untrusted key, altered, of another format, or of another set."""
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestRefused("manifest_too_large")
    try:
        document = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise ManifestRefused("manifest_not_json") from None
    if not isinstance(document, dict):
        raise ManifestRefused("manifest_not_json")
    try:
        body = verify_document(document, signers)
    except SignatureError as exc:
        raise ManifestRefused(f"signature:{exc}") from None
    if body.get("format") != MANIFEST_FORMAT:
        raise ManifestRefused("unknown_manifest_format")
    if body.get("backup_id") != backup_id:
        # A valid manifest copied under another set's name.
        raise ManifestRefused("manifest_belongs_to_another_set")
    if body.get("encryption", {}).get("format") != FORMAT_NAME:
        raise ManifestRefused("unknown_encryption_format")
    return body
