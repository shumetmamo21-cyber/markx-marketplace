"""Keys, the MXB2 encryption format and manifest signatures (D-094).

**Why public-key encryption.** The server that takes the backups must not be
able to read them: if the server is taken over, or lost together with its
disk, the backups must neither leak nor depend on anything that lived on it.
So the server holds only the *recipient public key*; the matching *recovery
key* (the private half) is kept off the server by the founder, and only a
restore needs it. Encrypting is possible without it, decrypting is not.

**MXB2, one file:**

    magic        8 bytes   b"MARKXBK" + b"\\x02"
    header len   2 bytes   big-endian
    header       JSON      {"alg", "chunk", "kid", "epk", "salt"}
    records      ...       each chunk of plaintext (`chunk` bytes, the last
                           one shorter or empty) as AES-256-GCM ciphertext
                           followed by its 16-byte tag

The file key is HKDF-SHA256 over an X25519 agreement between a fresh
ephemeral key (`epk`, in the header) and the recipient key (`kid` names it),
salted with 16 random bytes. Every file has its own key, so the nonces can
be a counter: 8 bytes of chunk number, 3 zero bytes, and 1 byte that is 1 on
the last chunk only (the STREAM construction). Every chunk authenticates the
whole header as associated data. So a changed byte anywhere, a changed
header, chunks swapped, dropped, repeated, a file cut short at any point or
extended after its end, and a wrong recovery key are all refused before a
single byte of plaintext is released for that chunk; a restore treats any
of them as "this backup cannot be trusted".

**Who wrote it.** Anyone holding the public key can encrypt, so MXB2 alone
proves secrecy and integrity, not authorship. Authorship comes from the
signed manifest, which records every file's ciphertext SHA-256: a restore
downloads a file, checks its hash against the signed manifest, then
decrypts all of it once without using the output, and only then restores.

**Signatures.** Manifests are signed with Ed25519 by a *signing key* the
backup service holds. Anyone may hold the matching *signer* (public) key;
a restore checks the manifest against it, so a manifest changed in the
bucket, or one planted there, is refused. The signing key also derives the
key that names file blobs (an HMAC of the content), so blob names reveal
nothing about the files to someone who can list the bucket.

The application's MARKX_SECRET_KEY and MARKX_ENCRYPTION_KEY are never used
here: the backup keys are separate files, made by `keygen`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import stat
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"MARKXBK\x02"
ALGORITHM = "X25519-HKDF-SHA256/AES-256-GCM-STREAM"
FORMAT_NAME = "MXB2"
DEFAULT_CHUNK = 1024 * 1024
_MIN_CHUNK, _MAX_CHUNK = 4096, 16 * 1024 * 1024
_TAG = 16
_MAX_HEADER = 1024

# One line per key file: "<label>:<base64 of 32 bytes>". The label says what
# the key is, so a public key can never be loaded where a private one belongs.
RECIPIENT_PUBLIC = "MARKX-BACKUP-PUBLIC-KEY-1"
RECOVERY_PRIVATE = "MARKX-BACKUP-RECOVERY-KEY-1"
SIGNING_PRIVATE = "MARKX-BACKUP-SIGNING-KEY-1"
SIGNER_PUBLIC = "MARKX-BACKUP-SIGNER-1"
_SECRET_LABELS = frozenset({RECOVERY_PRIVATE, SIGNING_PRIVATE})


class BackupKeyError(Exception):
    """A key file is missing, malformed, of the wrong kind or readable by others."""


class DecryptionError(Exception):
    """The ciphertext is altered, truncated, extended, not MXB2, or for another key.
    The message never contains key material or plaintext."""


class SignatureError(Exception):
    """A manifest is unsigned, altered, or signed by a key that is not trusted."""


# -- keys ------------------------------------------------------------------------------


def _key_id(kind: str, raw: bytes) -> str:
    return hashlib.sha256(kind.encode() + b"\x00" + raw).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RecipientKey:
    """The public half; the backup server encrypts to it."""

    public: X25519PublicKey

    @property
    def raw(self) -> bytes:
        return self.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @property
    def key_id(self) -> str:
        return _key_id("recipient", self.raw)


@dataclass(frozen=True, slots=True)
class RecoveryKey:
    """The private half, kept OFF the server; only a restore needs it."""

    private: X25519PrivateKey

    @property
    def recipient(self) -> RecipientKey:
        return RecipientKey(self.private.public_key())

    @property
    def key_id(self) -> str:
        return self.recipient.key_id

    def __repr__(self) -> str:
        return f"RecoveryKey(key_id={self.key_id!r})"


@dataclass(frozen=True, slots=True)
class SigningKey:
    """Held by the backup service: signs manifests and names blobs."""

    private: Ed25519PrivateKey

    @property
    def signer(self) -> SignerKey:
        return SignerKey(self.private.public_key())

    @property
    def key_id(self) -> str:
        return self.signer.key_id

    def blob_key(self) -> bytes:
        seed = self.private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        return HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"markx-backup v2 blob id"
        ).derive(seed)

    def sign(self, message: bytes) -> bytes:
        return self.private.sign(message)

    def __repr__(self) -> str:
        return f"SigningKey(key_id={self.key_id!r})"


@dataclass(frozen=True, slots=True)
class SignerKey:
    """The public half of a signing key: checks manifests."""

    public: Ed25519PublicKey

    @property
    def raw(self) -> bytes:
        return self.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @property
    def key_id(self) -> str:
        return _key_id("signer", self.raw)

    def verify(self, signature: bytes, message: bytes) -> None:
        try:
            self.public.verify(signature, message)
        except InvalidSignature:
            raise SignatureError("the manifest signature does not verify") from None


@dataclass(frozen=True, slots=True)
class GeneratedKeys:
    recovery: RecoveryKey
    signing: SigningKey


def generate_keys() -> GeneratedKeys:
    return GeneratedKeys(
        recovery=RecoveryKey(X25519PrivateKey.generate()),
        signing=SigningKey(Ed25519PrivateKey.generate()),
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def encode_recipient(key: RecipientKey) -> str:
    return f"{RECIPIENT_PUBLIC}:{_b64(key.raw)}\n"


def encode_recovery(key: RecoveryKey) -> str:
    raw = key.private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return f"{RECOVERY_PRIVATE}:{_b64(raw)}\n"


def encode_signing(key: SigningKey) -> str:
    raw = key.private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return f"{SIGNING_PRIVATE}:{_b64(raw)}\n"


def encode_signer(key: SignerKey) -> str:
    return f"{SIGNER_PUBLIC}:{_b64(key.raw)}\n"


def _parse(text: str, label: str) -> bytes:
    line = text.strip()
    prefix, sep, body = line.partition(":")
    if not sep or prefix != label:
        found = prefix if sep and prefix.startswith("MARKX-BACKUP-") else "something else"
        raise BackupKeyError(f"expected a {label} key, found {found}")
    try:
        raw = base64.b64decode(body.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        raise BackupKeyError(f"the {label} key is not valid base64") from None
    if len(raw) != 32:
        raise BackupKeyError(f"the {label} key must be 32 bytes")
    return raw


def _read_key_file(path: Path, label: str) -> bytes:
    try:
        info = path.stat()
        text = path.read_text(encoding="ascii")
    except FileNotFoundError:
        raise BackupKeyError(f"key file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise BackupKeyError(f"key file unreadable: {path} ({type(exc).__name__})") from None
    if label in _SECRET_LABELS and info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        # Like ssh: a private key that others can read is refused, not used.
        raise BackupKeyError(
            f"{path} is readable by other users; make it mode 600 or 400 (chmod 600 {path})"
        )
    return _parse(text, label)


def load_recipient(path: Path) -> RecipientKey:
    return RecipientKey(X25519PublicKey.from_public_bytes(_read_key_file(path, RECIPIENT_PUBLIC)))


def load_recovery(path: Path) -> RecoveryKey:
    return RecoveryKey(X25519PrivateKey.from_private_bytes(_read_key_file(path, RECOVERY_PRIVATE)))


def load_signing(path: Path) -> SigningKey:
    return SigningKey(Ed25519PrivateKey.from_private_bytes(_read_key_file(path, SIGNING_PRIVATE)))


def load_signer(path: Path) -> SignerKey:
    return SignerKey(Ed25519PublicKey.from_public_bytes(_read_key_file(path, SIGNER_PUBLIC)))


def write_key_file(path: Path, content: str, *, secret: bool) -> None:
    """Create a key file; never overwrite one (a lost key loses its backups)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600 if secret else 0o644)
    except FileExistsError:
        raise BackupKeyError(f"{path} already exists; keygen never overwrites a key") from None
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(content)


# -- the MXB2 stream -----------------------------------------------------------------


def _file_key(shared: bytes, salt: bytes, epk: bytes, recipient: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"markx-backup v2 file key" + epk + recipient,
    ).derive(shared)


def _nonce(counter: int, last: bool) -> bytes:
    return struct.pack(">Q", counter) + b"\x00\x00\x00" + (b"\x01" if last else b"\x00")


def _read_exactly(source: IO[bytes], size: int) -> bytes:
    parts: list[bytes] = []
    remaining = size
    while remaining > 0:
        part = source.read(remaining)
        if not part:
            break
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)


@dataclass(slots=True)
class StreamDigest:
    """What an encryption saw: the plaintext's and ciphertext's size and SHA-256."""

    plaintext_bytes: int = 0
    plaintext_sha256: str = ""
    ciphertext_bytes: int = 0
    ciphertext_sha256: str = ""


class Encryptor:
    """Encrypts one stream to a recipient, writing MXB2 to `out` as it goes.

    Use `write()` for every piece of plaintext, then `finish()` exactly once.
    The plaintext is never written anywhere; only ciphertext reaches `out`.
    """

    def __init__(self, recipient: RecipientKey, out: IO[bytes], *, chunk: int = DEFAULT_CHUNK):
        if not _MIN_CHUNK <= chunk <= _MAX_CHUNK:
            raise ValueError("chunk size out of range")
        ephemeral = X25519PrivateKey.generate()
        epk = ephemeral.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        salt = os.urandom(16)
        key = _file_key(ephemeral.exchange(recipient.public), salt, epk, recipient.raw)
        header_json = json.dumps(
            {"alg": ALGORITHM, "chunk": chunk, "epk": _b64(epk), "kid": recipient.key_id,
             "salt": _b64(salt)},
            sort_keys=True, separators=(",", ":"),
        ).encode("ascii")  # fmt: skip
        self._header = MAGIC + struct.pack(">H", len(header_json)) + header_json
        self._aead = AESGCM(key)
        self._chunk = chunk
        self._out = out
        self._buffer = bytearray()
        self._counter = 0
        self._plain = hashlib.sha256()
        self._cipher = hashlib.sha256()
        self.digest = StreamDigest()
        self._finished = False
        self._emit(self._header)

    def _emit(self, data: bytes) -> None:
        self._out.write(data)
        self._cipher.update(data)
        self.digest.ciphertext_bytes += len(data)

    def write(self, data: bytes) -> None:
        if self._finished:
            raise ValueError("the stream is finished")
        self._plain.update(data)
        self.digest.plaintext_bytes += len(data)
        self._buffer += data
        # Keep at least one byte back: the last chunk is only known at finish().
        while len(self._buffer) > self._chunk:
            piece = bytes(self._buffer[: self._chunk])
            del self._buffer[: self._chunk]
            self._emit(self._aead.encrypt(_nonce(self._counter, False), piece, self._header))
            self._counter += 1

    def finish(self) -> StreamDigest:
        if self._finished:
            raise ValueError("the stream is already finished")
        self._finished = True
        self._emit(
            self._aead.encrypt(_nonce(self._counter, True), bytes(self._buffer), self._header)
        )
        self._buffer.clear()
        self.digest.plaintext_sha256 = self._plain.hexdigest()
        self.digest.ciphertext_sha256 = self._cipher.hexdigest()
        return self.digest


def encrypt_bytes(recipient: RecipientKey, data: bytes, *, chunk: int = DEFAULT_CHUNK) -> bytes:
    import io

    out = io.BytesIO()
    encryptor = Encryptor(recipient, out, chunk=chunk)
    encryptor.write(data)
    encryptor.finish()
    return out.getvalue()


@dataclass(frozen=True, slots=True)
class Header:
    raw: bytes
    key_id: str
    chunk: int
    epk: bytes
    salt: bytes


def read_header(source: IO[bytes]) -> Header:
    magic = _read_exactly(source, len(MAGIC))
    if magic != MAGIC:
        if magic.startswith(b"Salted__"):
            raise DecryptionError(
                "this is a legacy AES-256-CBC backup (openssl enc); restore it with "
                "infra/backup/restore-legacy-cbc.sh"
            )
        raise DecryptionError("not an MXB2 backup file")
    size_raw = _read_exactly(source, 2)
    if len(size_raw) != 2:
        raise DecryptionError("the file is truncated in its header")
    (size,) = struct.unpack(">H", size_raw)
    if not 0 < size <= _MAX_HEADER:
        raise DecryptionError("the header has an impossible length")
    header_json = _read_exactly(source, size)
    if len(header_json) != size:
        raise DecryptionError("the file is truncated in its header")
    try:
        fields: dict[str, Any] = json.loads(header_json)
        if fields["alg"] != ALGORITHM:
            raise DecryptionError(f"unknown algorithm {str(fields['alg'])[:40]!r}")
        chunk = int(fields["chunk"])
        epk = base64.b64decode(fields["epk"], validate=True)
        salt = base64.b64decode(fields["salt"], validate=True)
        key_id = str(fields["kid"])
    except DecryptionError:
        raise
    except (ValueError, KeyError, TypeError):
        raise DecryptionError("the header is malformed") from None
    if not _MIN_CHUNK <= chunk <= _MAX_CHUNK or len(epk) != 32 or len(salt) != 16:
        raise DecryptionError("the header is malformed")
    return Header(MAGIC + size_raw + header_json, key_id, chunk, epk, salt)


def decrypt_stream(
    source: IO[bytes], keys: dict[str, RecoveryKey] | RecoveryKey
) -> Iterator[bytes]:
    """Yield the plaintext chunk by chunk; raise `DecryptionError` at the first
    sign of damage. A chunk is yielded only after its tag checked, and the
    stream is accepted as complete only when its final chunk checks with the
    "last" flag. Callers must treat output as unconfirmed until the iterator
    ends without an exception (a restore runs inside one transaction)."""
    header = read_header(source)
    ring = {keys.key_id: keys} if isinstance(keys, RecoveryKey) else keys
    recovery = ring.get(header.key_id)
    if recovery is None:
        raise DecryptionError(f"encrypted for recovery key {header.key_id}, which was not given")
    try:
        shared = recovery.private.exchange(X25519PublicKey.from_public_bytes(header.epk))
    except ValueError:
        raise DecryptionError("the header is malformed") from None
    aead = AESGCM(_file_key(shared, header.salt, header.epk, recovery.recipient.raw))
    record = header.chunk + _TAG
    counter = 0
    current = _read_exactly(source, record)
    while True:
        if len(current) < _TAG:
            raise DecryptionError("the file is truncated")
        following = _read_exactly(source, record) if len(current) == record else b""
        last = not following
        try:
            plain = aead.decrypt(_nonce(counter, last), current, header.raw)
        except InvalidTag:
            raise DecryptionError(
                "the file was altered, cut short, extended, or is not for this key"
            ) from None
        yield plain
        if last:
            return
        counter += 1
        current = following


def decrypt_bytes(data: bytes, keys: dict[str, RecoveryKey] | RecoveryKey) -> bytes:
    import io

    return b"".join(decrypt_stream(io.BytesIO(data), keys))


def peek_key_id(data: bytes) -> str:
    import io

    return read_header(io.BytesIO(data)).key_id


# -- names and signatures -------------------------------------------------------------


def blob_id(signing: SigningKey, recipient: RecipientKey, plaintext_sha256: str) -> str:
    """The name of a file's blob. Equal files share one blob while the recipient
    key stays the same; the name says nothing about the file without the key."""
    message = f"{recipient.key_id}:{plaintext_sha256}".encode("ascii")
    return hmac.new(signing.blob_key(), message, hashlib.sha256).hexdigest()


def canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def sign_document(document: dict[str, Any], signing: SigningKey) -> dict[str, Any]:
    body = {k: v for k, v in document.items() if k != "signature"}
    body["signer_key_id"] = signing.key_id
    signature = signing.sign(b"markx-backup-manifest/2\x00" + canonical(body))
    return {**body, "signature": _b64(signature)}


def verify_document(document: dict[str, Any], signers: list[SignerKey]) -> dict[str, Any]:
    """The document without its signature, if a trusted signer signed it."""
    signature_b64 = document.get("signature")
    if not isinstance(signature_b64, str):
        raise SignatureError("the manifest is not signed")
    body = {k: v for k, v in document.items() if k != "signature"}
    trusted = {signer.key_id: signer for signer in signers}
    signer = trusted.get(str(body.get("signer_key_id")))
    if signer is None:
        raise SignatureError("the manifest was signed by a key that is not trusted")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except ValueError:
        raise SignatureError("the manifest signature is malformed") from None
    signer.verify(signature, b"markx-backup-manifest/2\x00" + canonical(body))
    return body
