"""Older locked copies of a backup file (RN-1, D-105).

The server's backup key may add objects but never delete them (BK-1). It can
still WRITE AN OBJECT AGAIN under the same name: on a bucket with versioning
and an object lock (required on staging and production), the earlier version
is then kept, locked, behind the new one. Someone holding the server's key
could overwrite a set's dump, its index, its manifest or a file's blob with
garbage; the original bytes survive as an older version.

Verify, restore and the drill read each piece through `Copies`:

- a piece whose expected SHA-256 the signed manifest (or the index) records
  is read as it stands now; when it is missing or does not match, every
  older version is tried, newest first, and the first that matches is used;
- a set's manifest is written exactly once, so when the bucket holds several
  DIFFERENT versions of it, the OLDEST one that verifies is the original and
  is the one used (a later one was written by someone else);
- each object read from an older version, and each object of the set that
  has more than one different version or is hidden behind a delete marker,
  is recorded as OVERWRITTEN. The report warns, the drill report carries the
  list, and `record-drill` enters it so the watch raises `backup.overwritten`.

Reading older versions needs the recovery machine's key to list versions and
read a version (`s3:ListBucketVersions`, `s3:GetObjectVersion`). When it
cannot, the report says so and only the current versions are used. A folder
destination (a laptop) keeps one version of each file: nothing older exists.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markx.backup.destination import Destination, DestinationError, ObjectMissing, ObjectVersion

_READ = 1024 * 1024


@dataclass(slots=True)
class Copies:
    destination: Destination
    # key -> the older version id that was read instead of the current one.
    used: dict[str, str] = field(default_factory=dict)
    overwritten: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def older(self, key: str) -> list[ObjectVersion]:
        """The object's earlier versions, newest first (none on a folder)."""
        try:
            versions = self.destination.versions(key)
        except DestinationError as exc:
            self.notes.append(f"older copies could not be listed ({exc.reason})")
            return []
        return [v for v in versions if not v.is_latest and v.version_id]

    def candidates(self, key: str) -> Iterator[str | None]:
        """The current version (None), then each older one, newest first.
        Older versions are listed only when the current one did not do."""
        yield None
        for version in self.older(key):
            yield version.version_id

    def took(self, key: str, version_id: str | None) -> None:
        if version_id is not None:
            self.used[key] = version_id
            self.overwritten.add(key)

    def scan(self, prefix: str) -> None:
        """Record every object under `prefix` (a set's own pieces, each written
        once) that holds more than one DIFFERENT version, or whose newest entry
        is a delete marker. The same bytes stored twice (an upload the client
        retried) are not an overwrite."""
        try:
            found = list(self.destination.list_versions(prefix))
        except DestinationError as exc:
            self.notes.append(f"older copies could not be listed ({exc.reason})")
            return
        etags: dict[str, set[str | None]] = {}
        for version in found:
            if version.delete_marker:
                if version.is_latest:
                    self.overwritten.add(version.key)
                continue
            etags.setdefault(version.key, set()).add(version.etag)
        self.overwritten.update(k for k, tags in etags.items() if len(tags) > 1)

    def facts(self) -> dict[str, Any]:
        return {"overwritten": sorted(self.overwritten), "older_copies_used": dict(self.used)}

    def warning(self) -> str | None:
        if not self.overwritten:
            return None
        used = f"; the original locked copy was used for {len(self.used)}" if self.used else ""
        return (
            f"{len(self.overwritten)} backup file(s) were written again after the set was "
            f"made{used}. Someone may hold the server's backup key: tell the founder "
            "(docs/runbooks/backup-and-restore.md, 'A backup file was overwritten')"
        )


def download_matching(
    copies: Copies, key: str, path: Path, *, sha256: str, size: int | None
) -> str:
    """Write to `path` the first version of `key` with exactly these bytes.
    Returns "ok", or why nothing matched: "missing" (no version could be
    read) or "altered" (versions exist, none matches)."""
    read_any = False
    for version in copies.candidates(key):
        digest = hashlib.sha256()
        total = 0
        try:
            with copies.destination.reader(key, version) as stream, path.open("wb") as out:
                while chunk := stream.read(_READ):
                    digest.update(chunk)
                    total += len(chunk)
                    out.write(chunk)
        except ObjectMissing:
            continue
        read_any = True
        if digest.hexdigest() == sha256 and (size is None or total == size):
            copies.took(key, version)
            return "ok"
    path.unlink(missing_ok=True)
    return "altered" if read_any else "missing"


def first_good(
    copies: Copies, key: str, accept: Callable[[bytes], Any], *, limit: int
) -> tuple[Any, str | None]:
    """The first version of `key`, current first, that `accept` takes (it
    returns a value, or raises to refuse). Raises ObjectMissing when no
    version can be read at all, else the last refusal."""
    last: Exception | None = None
    for version in copies.candidates(key):
        try:
            data = copies.destination.read_bytes(key, limit=limit, version_id=version)
        except ObjectMissing:
            continue
        try:
            value = accept(data)
        except Exception as exc:
            last = exc
            continue
        copies.took(key, version)
        return value, version
    if last is not None:
        raise last
    raise ObjectMissing("missing")
