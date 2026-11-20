"""Which backup sets and blobs may be deleted (D-094). Conservative by design.

How long backups are kept is the founder's decision (F-20): a real server
refuses to start without MARKX_BACKUP_RETENTION_DAYS and
MARKX_BACKUP_RETENTION_MIN_SETS, the retention job refuses to delete from
off-server storage without them, and `0` days keeps everything. A laptop
defaults to 7 days and 3 sets.

Rules, all of which must hold for anything to go:

- Only sets whose manifest is signed by THIS service's key count as sets.
  An unsigned or foreign manifest is never a reason to delete anything.
- The newest `min_sets` complete sets are kept whatever their age, and the
  newest complete set always (so there is never no recovery point). With
  no complete set at all, nothing is deleted.
- A complete set is deleted only when it is older than `retention_days`
  and is not one of those kept.
- An unfinished set (no manifest) and an incomplete set are deleted only
  when older than `retention_days` (and never with 0).
- A blob is deleted only when no kept set lists it, and it is older than the
  grace period, so the blobs of a backup running right now are safe. If any
  kept set's blob list cannot be read and checked, no blob is deleted.
- Retention only deletes inside the destination's prefix. It never touches
  the stored files themselves.

**Retention never runs on the server (BK-1).** The server's backup key
cannot delete; `python -m markx.backup prune` runs on a separate machine
with its own retention key and refuses to run on staging or production.
It trusts only the signer PUBLIC key it is given. It takes no lock: a
backup running at the same moment is protected by the blob grace period,
and its unfinished set (no manifest yet) is younger than any retention.

**Versions and object lock.** Deleting means removing every version of an
object (`Destination.purge`), so space is really freed on a versioned
bucket and no delete marker is left behind. A version still under an
object lock cannot be removed by anyone: it is left, reported as held, and
removed by a later run once its lock has passed. When a set's manifest is
held, nothing else of that set is touched, so a half-deleted set can never
look complete. Objects already hidden behind a delete marker (left by an
older plain delete) are removed the same way once they are older than the
retention period, unless a kept set needs them.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from markx.backup import manifest as manifest_mod
from markx.backup.crypto import SignerKey
from markx.backup.destination import Destination, RemoteObject

logger = logging.getLogger("markx.backup.retention")


@dataclass(slots=True)
class SetInfo:
    backup_id: str
    created: datetime
    status: str  # complete, incomplete, unfinished, untrusted
    keys: list[str] = field(default_factory=list)
    blobs_object: str | None = None
    blobs_sha256: str | None = None


@dataclass(slots=True)
class Plan:
    keep: list[str] = field(default_factory=list)
    delete_sets: list[str] = field(default_factory=list)
    delete_blobs: list[str] = field(default_factory=list)
    # Objects only a delete marker hides, to be removed in every version.
    delete_hidden: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # What an object lock still holds: left in place for a later run.
    held: list[str] = field(default_factory=list)
    # The blobs the kept sets need; None when they could not all be read.
    needed: set[str] | None = None


def survey(destination: Destination, signers: list[SignerKey]) -> list[SetInfo]:
    """Every set at the destination, newest first, by what its manifest proves."""
    pieces: dict[str, list[RemoteObject]] = {}
    for obj in destination.list("sets/"):
        parts = obj.key.split("/")
        if len(parts) >= 3 and manifest_mod.BACKUP_ID.fullmatch(parts[1]):
            pieces.setdefault(parts[1], []).append(obj)
    sets: list[SetInfo] = []
    for backup_id, objects in pieces.items():
        created = datetime.strptime(backup_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        keys = [o.key for o in objects]
        info = SetInfo(backup_id, created, "unfinished", keys)
        if manifest_mod.manifest_key(backup_id) in keys:
            try:
                data = destination.read_bytes(
                    manifest_mod.manifest_key(backup_id), limit=manifest_mod.MAX_MANIFEST_BYTES
                )
                body = manifest_mod.decode(data, signers, backup_id=backup_id)
                info.status = str(body["status"])
                info.blobs_object = body["files"]["blobs_object"]
                info.blobs_sha256 = body["files"]["blobs_sha256"]
            except manifest_mod.ManifestRefused:
                info.status = "untrusted"
        sets.append(info)
    return sorted(sets, key=lambda s: s.backup_id, reverse=True)


def plan(
    sets: list[SetInfo], *, now: datetime, retention_days: int, min_sets: int,
) -> Plan:  # fmt: skip
    result = Plan()
    complete = [s for s in sets if s.status == manifest_mod.STATUS_COMPLETE]
    if not complete:
        result.notes.append("no complete set: nothing is deleted")
        result.keep = [s.backup_id for s in sets]
        return result
    protected = {s.backup_id for s in complete[: max(min_sets, 1)]}
    cutoff = now - timedelta(days=retention_days)
    for info in sets:
        old = retention_days > 0 and info.created < cutoff
        if info.backup_id in protected or info.status == "untrusted" or not old:
            result.keep.append(info.backup_id)
        else:
            result.delete_sets.append(info.backup_id)
    if retention_days == 0:
        result.notes.append("retention 0: every set is kept")
    return result


def _blobs_of(destination: Destination, info: SetInfo) -> set[str] | None:
    if info.blobs_object is None or info.blobs_sha256 is None:
        return None
    try:
        data = destination.read_bytes(info.blobs_object, limit=256 * 1024 * 1024)
    except Exception:
        return None
    if hashlib.sha256(data).hexdigest() != info.blobs_sha256:
        return None
    return {line for line in data.decode("ascii", errors="replace").splitlines() if line}


def plan_blobs(
    destination: Destination, sets: list[SetInfo], result: Plan, *, now: datetime, grace: timedelta,
) -> None:  # fmt: skip
    kept = [s for s in sets if s.backup_id in result.keep]
    needed: set[str] = set()
    for info in kept:
        if info.status in ("unfinished", "untrusted"):
            continue  # an unfinished set's blobs are protected by the grace period
        blobs = _blobs_of(destination, info)
        if blobs is None:
            result.notes.append(f"blob list of {info.backup_id} unreadable: no blob is deleted")
            return
        needed |= blobs
    result.needed = needed
    if not needed and any(s.status == manifest_mod.STATUS_COMPLETE for s in kept):
        # A complete set with no files is possible (an empty marketplace), but
        # deleting every blob on that basis is not a risk worth taking.
        result.notes.append("kept sets list no blobs: no blob is deleted")
        return
    for obj in destination.list("objects/"):
        blob = obj.key.rsplit("/", 1)[-1]
        if blob not in needed and now - obj.last_modified > grace:
            result.delete_blobs.append(obj.key)


def plan_hidden(
    destination: Destination, result: Plan, *, now: datetime, retention_days: int,
    grace: timedelta,
) -> None:  # fmt: skip
    """Objects with no current version, only older versions behind a delete
    marker: invisible to a restore, still paid for. Removed once older than
    the retention period, never when a kept set needs them."""
    if retention_days == 0:
        return
    cutoff = now - max(timedelta(days=retention_days), grace)
    newest: dict[str, datetime] = {}
    current: set[str] = set()
    for version in destination.list_versions(""):
        if version.is_latest and not version.delete_marker:
            current.add(version.key)
        if version.key not in newest or version.last_modified > newest[version.key]:
            newest[version.key] = version.last_modified
    kept = set(result.keep)
    for key, last in sorted(newest.items()):
        if key in current or last >= cutoff:
            continue
        parts = key.split("/")
        if parts[0] == "sets":
            if len(parts) < 3 or parts[1] in kept:
                continue
        elif parts[0] == "objects":
            if result.needed is None or parts[-1] in result.needed:
                continue
        else:
            continue
        result.delete_hidden.append(key)


def apply(destination: Destination, sets: list[SetInfo], result: Plan) -> dict[str, int]:
    """Delete what the plan says, every version of each object: whole sets
    (manifest first, so a half-deleted set is never mistaken for a complete
    one; a set whose manifest a lock still holds is left whole), then blobs,
    then objects only a delete marker hides."""
    by_id = {s.backup_id: s for s in sets}
    deleted_sets = deleted_blobs = 0
    for backup_id in result.delete_sets:
        info = by_id[backup_id]
        manifest = manifest_mod.manifest_key(backup_id)
        if manifest in info.keys and not destination.purge(manifest):
            result.held.append(manifest)
            result.notes.append(f"set {backup_id} is still under its object lock: kept for now")
            continue
        for key in info.keys:
            if key != manifest and not destination.purge(key):
                result.held.append(key)
        deleted_sets += 1
    for key in [*result.delete_blobs, *result.delete_hidden]:
        if destination.purge(key):
            deleted_blobs += 1
        else:
            result.held.append(key)
    if result.held:
        result.notes.append(
            f"{len(result.held)} objects still under their object lock: a later run removes them"
        )
    return {"sets": deleted_sets, "blobs": deleted_blobs, "held": len(result.held)}


def prune(
    destination: Destination, signers: list[SignerKey], *, now: datetime, retention_days: int,
    min_sets: int, grace: timedelta, execute: bool,
) -> Plan:  # fmt: skip
    sets = survey(destination, signers)
    result = plan(sets, now=now, retention_days=retention_days, min_sets=min_sets)
    plan_blobs(destination, sets, result, now=now, grace=grace)
    plan_hidden(destination, result, now=now, retention_days=retention_days, grace=grace)
    if execute:
        counts = apply(destination, sets, result)
        logger.info("retention applied", extra=counts)
    return result
