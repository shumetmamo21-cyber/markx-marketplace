"""The backup encryption format and keys (D-094): authenticated encryption
that refuses every kind of damage, keys that cannot be mixed up or left
readable, and manifest signatures that refuse any change."""

from __future__ import annotations

import io
import json
import os
import struct
from pathlib import Path

import pytest

from markx.backup import crypto
from markx.backup import manifest as manifest_mod
from markx.backup.crypto import DecryptionError, SignatureError

CHUNK = 4096  # the smallest allowed, so tests cross chunk boundaries cheaply


@pytest.fixture(scope="module")
def keys() -> crypto.GeneratedKeys:
    return crypto.generate_keys()


def _encrypt(keys: crypto.GeneratedKeys, data: bytes) -> bytes:
    return crypto.encrypt_bytes(keys.recovery.recipient, data, chunk=CHUNK)


def _header_length(blob: bytes) -> int:
    (size,) = struct.unpack(">H", blob[8:10])
    return 10 + size


@pytest.mark.parametrize("size", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK, 3 * CHUNK + 17])
def test_every_size_round_trips(keys: crypto.GeneratedKeys, size: int) -> None:
    data = os.urandom(size)
    blob = _encrypt(keys, data)
    assert crypto.decrypt_bytes(blob, keys.recovery) == data
    # Nothing of the plaintext shows in the ciphertext.
    if size >= 32:
        assert data[:32] not in blob


def test_the_same_plaintext_encrypts_differently_every_time(keys: crypto.GeneratedKeys) -> None:
    data = b"same bytes" * 100
    assert _encrypt(keys, data) != _encrypt(keys, data)


def test_the_digest_describes_both_sides(keys: crypto.GeneratedKeys) -> None:
    out = io.BytesIO()
    encryptor = crypto.Encryptor(keys.recovery.recipient, out, chunk=CHUNK)
    encryptor.write(b"a" * 5000)
    encryptor.write(b"b" * 5000)
    digest = encryptor.finish()
    import hashlib

    assert digest.plaintext_bytes == 10_000
    assert digest.plaintext_sha256 == hashlib.sha256(b"a" * 5000 + b"b" * 5000).hexdigest()
    assert digest.ciphertext_sha256 == hashlib.sha256(out.getvalue()).hexdigest()
    assert digest.ciphertext_bytes == len(out.getvalue())
    with pytest.raises(ValueError, match="finished"):
        encryptor.finish()


def test_one_changed_bit_anywhere_is_refused(keys: crypto.GeneratedKeys) -> None:
    blob = _encrypt(keys, os.urandom(2 * CHUNK + 100))
    header = _header_length(blob)
    # In the magic, the header, the first chunk, its tag and the last chunk.
    for position in (3, 12, header - 2, header + 5, header + CHUNK + 15, len(blob) - 1):
        damaged = bytearray(blob)
        damaged[position] ^= 0x01
        with pytest.raises(DecryptionError):
            crypto.decrypt_bytes(bytes(damaged), keys.recovery)


def test_a_cut_short_file_is_refused_wherever_it_is_cut(keys: crypto.GeneratedKeys) -> None:
    blob = _encrypt(keys, os.urandom(3 * CHUNK))
    header = _header_length(blob)
    record = CHUNK + 16
    # Inside the header, at each chunk boundary (the hardest case), mid-chunk,
    # and one byte short.
    for length in (5, header, header + record, header + 2 * record, header + 100, len(blob) - 1):
        with pytest.raises(DecryptionError):
            crypto.decrypt_bytes(blob[:length], keys.recovery)


def test_bytes_added_after_the_end_are_refused(keys: crypto.GeneratedKeys) -> None:
    blob = _encrypt(keys, os.urandom(CHUNK + 5))
    for extra in (b"\x00", os.urandom(16), os.urandom(CHUNK + 16)):
        with pytest.raises(DecryptionError):
            crypto.decrypt_bytes(blob + extra, keys.recovery)


def test_chunks_swapped_dropped_or_repeated_are_refused(keys: crypto.GeneratedKeys) -> None:
    blob = _encrypt(keys, os.urandom(3 * CHUNK + 50))
    header = _header_length(blob)
    record = CHUNK + 16
    head, body = blob[:header], blob[header:]
    chunks = [body[i : i + record] for i in range(0, len(body), record)]
    assert len(chunks) == 4
    for arrangement in (
        [chunks[1], chunks[0], chunks[2], chunks[3]],  # swapped
        [chunks[0], chunks[2], chunks[3]],  # one dropped
        [chunks[0], chunks[0], chunks[1], chunks[2], chunks[3]],  # one repeated
        [chunks[0], chunks[1], chunks[2]],  # the last one dropped
    ):
        with pytest.raises(DecryptionError):
            crypto.decrypt_bytes(head + b"".join(arrangement), keys.recovery)


def test_a_header_from_another_file_is_refused(keys: crypto.GeneratedKeys) -> None:
    first = _encrypt(keys, os.urandom(1000))
    second = _encrypt(keys, os.urandom(1000))
    mixed = first[: _header_length(first)] + second[_header_length(second) :]
    with pytest.raises(DecryptionError):
        crypto.decrypt_bytes(mixed, keys.recovery)


def test_the_wrong_recovery_key_cannot_decrypt(keys: crypto.GeneratedKeys) -> None:
    blob = _encrypt(keys, b"secret dump")
    stranger = crypto.generate_keys().recovery
    with pytest.raises(DecryptionError, match="was not given"):
        crypto.decrypt_bytes(blob, stranger)
    # Even a key ring that claims the right id, holding the wrong key, fails.
    with pytest.raises(DecryptionError, match="altered"):
        crypto.decrypt_bytes(blob, {keys.recovery.key_id: stranger})


def test_the_right_key_is_found_in_a_ring_of_old_and_new_keys(keys: crypto.GeneratedKeys) -> None:
    older = crypto.generate_keys().recovery
    ring = {older.key_id: older, keys.recovery.key_id: keys.recovery}
    old_blob = crypto.encrypt_bytes(older.recipient, b"made before the rotation", chunk=CHUNK)
    assert crypto.decrypt_bytes(old_blob, ring) == b"made before the rotation"
    assert crypto.peek_key_id(old_blob) == older.key_id


def test_a_legacy_cbc_backup_is_named_not_misread(keys: crypto.GeneratedKeys) -> None:
    with pytest.raises(DecryptionError, match="restore-legacy-cbc"):
        crypto.decrypt_bytes(b"Salted__" + os.urandom(64), keys.recovery)
    with pytest.raises(DecryptionError, match="not an MXB2"):
        crypto.decrypt_bytes(b"PGDMP" + os.urandom(64), keys.recovery)


def test_the_key_does_not_come_from_the_application_secrets(keys: crypto.GeneratedKeys) -> None:
    """D-094: never MARKX_SECRET_KEY or MARKX_ENCRYPTION_KEY."""
    source = Path(crypto.__file__).read_text(encoding="utf-8")
    assert "get_config" not in source
    assert "secret_key" not in source
    assert "encryption_key" not in source


# -- key files ----------------------------------------------------------------------------


def test_keys_written_and_read_back(tmp_path: Path, keys: crypto.GeneratedKeys) -> None:
    files = {
        "recovery.key": (crypto.encode_recovery(keys.recovery), True),
        "public.key": (crypto.encode_recipient(keys.recovery.recipient), False),
        "signing.key": (crypto.encode_signing(keys.signing), True),
        "signer.key": (crypto.encode_signer(keys.signing.signer), False),
    }
    for name, (content, secret) in files.items():
        crypto.write_key_file(tmp_path / name, content, secret=secret)
    assert (tmp_path / "recovery.key").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "signing.key").stat().st_mode & 0o777 == 0o600
    assert crypto.load_recovery(tmp_path / "recovery.key").key_id == keys.recovery.key_id
    assert crypto.load_recipient(tmp_path / "public.key").key_id == keys.recovery.key_id
    assert crypto.load_signing(tmp_path / "signing.key").key_id == keys.signing.key_id
    assert crypto.load_signer(tmp_path / "signer.key").key_id == keys.signing.key_id
    # A key is never overwritten: losing it would lose its backups.
    with pytest.raises(crypto.BackupKeyError, match="never overwrites"):
        crypto.write_key_file(tmp_path / "recovery.key", "x", secret=True)


def test_a_key_of_the_wrong_kind_is_refused(tmp_path: Path, keys: crypto.GeneratedKeys) -> None:
    path = tmp_path / "public.key"
    crypto.write_key_file(path, crypto.encode_recipient(keys.recovery.recipient), secret=True)
    with pytest.raises(crypto.BackupKeyError, match="expected a MARKX-BACKUP-RECOVERY-KEY-1"):
        crypto.load_recovery(path)
    with pytest.raises(crypto.BackupKeyError, match="expected a MARKX-BACKUP-SIGNING-KEY-1"):
        crypto.load_signing(path)


@pytest.mark.parametrize("content", ["", "garbage", "MARKX-BACKUP-PUBLIC-KEY-1:not base64!",
                                     "MARKX-BACKUP-PUBLIC-KEY-1:AAAA"])  # fmt: skip
def test_a_malformed_key_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "public.key"
    path.write_text(content)
    with pytest.raises(crypto.BackupKeyError):
        crypto.load_recipient(path)


def test_a_private_key_others_can_read_is_refused(
    tmp_path: Path, keys: crypto.GeneratedKeys
) -> None:
    path = tmp_path / "recovery.key"
    crypto.write_key_file(path, crypto.encode_recovery(keys.recovery), secret=True)
    path.chmod(0o644)
    with pytest.raises(crypto.BackupKeyError, match="readable by other users"):
        crypto.load_recovery(path)


def test_no_key_material_in_a_repr(keys: crypto.GeneratedKeys) -> None:
    secret = crypto.encode_recovery(keys.recovery).split(":")[1].strip()
    assert secret not in repr(keys.recovery)
    assert secret not in repr(keys.signing)


# -- names and signatures --------------------------------------------------------------------


def test_blob_names_are_stable_but_reveal_nothing(keys: crypto.GeneratedKeys) -> None:
    import hashlib

    sha = hashlib.sha256(b"a picture").hexdigest()
    first = crypto.blob_id(keys.signing, keys.recovery.recipient, sha)
    assert first == crypto.blob_id(keys.signing, keys.recovery.recipient, sha)
    assert first != sha
    other = crypto.generate_keys()
    # Another signing key, or a new recipient after a rotation: another name.
    assert crypto.blob_id(other.signing, keys.recovery.recipient, sha) != first
    assert crypto.blob_id(keys.signing, other.recovery.recipient, sha) != first


def _signed(keys: crypto.GeneratedKeys) -> dict[str, object]:
    body = {"backup_id": "20261118T020000Z-0123abcd", "status": "complete",
            "encryption": {"format": crypto.FORMAT_NAME}, "database": {"rows": 5}}  # fmt: skip
    return json.loads(manifest_mod.encode(body, keys.signing))  # type: ignore[no-any-return]


def test_a_signed_manifest_verifies(keys: crypto.GeneratedKeys) -> None:
    document = _signed(keys)
    body = manifest_mod.decode(
        json.dumps(document).encode(), [keys.signing.signer], backup_id="20261118T020000Z-0123abcd"
    )
    assert body["database"] == {"rows": 5}


def test_a_changed_manifest_is_refused(keys: crypto.GeneratedKeys) -> None:
    document = _signed(keys)
    document["database"] = {"rows": 6}
    with pytest.raises(manifest_mod.ManifestRefused, match="signature"):
        manifest_mod.decode(json.dumps(document).encode(), [keys.signing.signer],
                            backup_id="20261118T020000Z-0123abcd")  # fmt: skip


def test_an_unsigned_or_foreign_manifest_is_refused(keys: crypto.GeneratedKeys) -> None:
    document = _signed(keys)
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    with pytest.raises(manifest_mod.ManifestRefused, match="not signed"):
        manifest_mod.decode(json.dumps(unsigned).encode(), [keys.signing.signer],
                            backup_id="20261118T020000Z-0123abcd")  # fmt: skip
    stranger = crypto.generate_keys().signing
    with pytest.raises(manifest_mod.ManifestRefused, match="not trusted"):
        manifest_mod.decode(json.dumps(document).encode(), [stranger.signer],
                            backup_id="20261118T020000Z-0123abcd")  # fmt: skip
    # Someone else's key can sign, but it is not on the trusted list.
    forged = json.loads(manifest_mod.encode({**unsigned, "status": "complete"}, stranger))
    with pytest.raises(manifest_mod.ManifestRefused, match="not trusted"):
        manifest_mod.decode(json.dumps(forged).encode(), [keys.signing.signer],
                            backup_id="20261118T020000Z-0123abcd")  # fmt: skip


def test_a_manifest_copied_under_another_sets_name_is_refused(keys: crypto.GeneratedKeys) -> None:
    document = _signed(keys)
    with pytest.raises(manifest_mod.ManifestRefused, match="another_set"):
        manifest_mod.decode(json.dumps(document).encode(), [keys.signing.signer],
                            backup_id="20261119T020000Z-0123abcd")  # fmt: skip


def test_signature_errors_name_no_key() -> None:
    with pytest.raises(SignatureError) as caught:
        crypto.verify_document({"signature": "AAAA", "signer_key_id": "x"}, [])
    assert "AAAA" not in str(caught.value)


def test_backup_ids_and_keys_are_strict() -> None:
    assert manifest_mod.set_prefix("20261118T020000Z-0123abcd") == "sets/20261118T020000Z-0123abcd"
    for bad in ("../etc", "20261118T020000Z-0123abcd/..", "x", ""):
        with pytest.raises(ValueError, match="not a backup id"):
            manifest_mod.set_prefix(bad)
    with pytest.raises(ValueError, match="not a blob id"):
        manifest_mod.blob_key("../../" + "a" * 58)
