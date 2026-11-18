"""Retention (D-094): never the only recovery point, never on the word of an
unsigned manifest, never a blob a kept set needs or one a running backup
may have just uploaded."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from markx.backup import crypto
from markx.backup import manifest as manifest_mod
from markx.backup.destination import LocalDestination
from markx.backup.retention import SetInfo, plan, prune

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def _set(days_ago: int, status: str = "complete", n: int = 0) -> SetInfo:
    created = NOW - timedelta(days=days_ago)
    backup_id = f"{created.strftime('%Y%m%dT%H%M%SZ')}-{n:08x}"
    return SetInfo(backup_id, created, status)


def test_the_newest_complete_set_is_kept_however_old() -> None:
    sets = [_set(400), _set(500, n=1)]
    result = plan(sets, now=NOW, retention_days=30, min_sets=1)
    assert result.keep == [sets[0].backup_id]
    assert result.delete_sets == [sets[1].backup_id]


def test_the_minimum_number_of_sets_is_kept() -> None:
    sets = [_set(d, n=d) for d in (40, 50, 60, 70)]
    result = plan(sets, now=NOW, retention_days=30, min_sets=3)
    assert result.keep == [s.backup_id for s in sets[:3]]
    assert result.delete_sets == [sets[3].backup_id]


def test_failed_sets_never_count_towards_the_minimum() -> None:
    """A run of incomplete sets must not push out the last complete one."""
    sets = [_set(1, "incomplete", 1), _set(2, "incomplete", 2), _set(90, "complete", 3)]
    result = plan(sets, now=NOW, retention_days=30, min_sets=1)
    assert sets[2].backup_id in result.keep


def test_without_a_complete_set_nothing_is_deleted() -> None:
    sets = [_set(100, "incomplete"), _set(200, "unfinished", 1)]
    result = plan(sets, now=NOW, retention_days=30, min_sets=1)
    assert result.delete_sets == []
    assert "no complete set" in result.notes[0]


def test_retention_zero_keeps_everything() -> None:
    sets = [_set(1000, n=1), _set(2000, "unfinished", 2), _set(10, n=3)]
    result = plan(sets, now=NOW, retention_days=0, min_sets=1)
    assert result.delete_sets == []


def test_an_untrusted_manifest_is_never_a_reason_to_delete() -> None:
    sets = [_set(1, n=1), _set(400, "untrusted", 2)]
    result = plan(sets, now=NOW, retention_days=30, min_sets=1)
    assert sets[1].backup_id in result.keep


def test_old_unfinished_sets_go_recent_ones_stay() -> None:
    sets = [_set(1, n=1), _set(2, "unfinished", 2), _set(60, "unfinished", 3)]
    result = plan(sets, now=NOW, retention_days=30, min_sets=1)
    assert result.delete_sets == [sets[2].backup_id]


# -- against a destination ------------------------------------------------------------------


def _put(dest: LocalDestination, key: str, data: bytes, age: timedelta) -> None:
    path = dest._root / "markx" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    stamp = (NOW - age).timestamp()
    os.utime(path, (stamp, stamp))


def _make_set(dest: LocalDestination, keys: crypto.GeneratedKeys, days_ago: int, blobs: list[str],
              n: int, *, status: str = "complete") -> str:  # fmt: skip
    import hashlib

    created = NOW - timedelta(days=days_ago)
    backup_id = f"{created.strftime('%Y%m%dT%H%M%SZ')}-{n:08x}"
    listing = "".join(f"{b}\n" for b in blobs).encode()
    prefix = manifest_mod.set_prefix(backup_id)
    _put(dest, f"{prefix}/blobs.txt", listing, timedelta(days=days_ago))
    body = {"backup_id": backup_id, "status": status, "encryption": {"format": crypto.FORMAT_NAME},
            "files": {"blobs_object": f"{prefix}/blobs.txt",
                      "blobs_sha256": hashlib.sha256(listing).hexdigest()}}  # fmt: skip
    _put(dest, manifest_mod.manifest_key(backup_id), manifest_mod.encode(body, keys.signing),
         timedelta(days=days_ago))  # fmt: skip
    return backup_id


def _blob(n: int) -> str:
    return f"{n:064x}"


@pytest.fixture
def dest(tmp_path: Path) -> LocalDestination:
    return LocalDestination(tmp_path, prefix="markx")


def test_blobs_are_collected_only_when_unneeded_and_old(dest: LocalDestination) -> None:
    keys = crypto.generate_keys()
    new = _make_set(dest, keys, 1, [_blob(1), _blob(2)], 1)
    old = _make_set(dest, keys, 90, [_blob(2), _blob(3)], 2)
    for n, age in ((1, 1), (2, 90), (3, 90), (4, 90), (5, 0)):
        _put(dest, manifest_mod.blob_key(_blob(n)), b"x", timedelta(days=age))
    result = prune(dest, [keys.signing.signer], now=NOW, retention_days=30, min_sets=1,
                   grace=timedelta(hours=48), execute=True)  # fmt: skip
    assert result.delete_sets == [old]
    remaining = {o.key.rsplit("/", 1)[-1] for o in dest.list("objects/")}
    # 1 and 2: needed by the kept set; 3 and 4: needed by nobody, old; 5: too new to judge.
    assert remaining == {_blob(1), _blob(2), _blob(5)}
    assert [o.key for o in dest.list(f"sets/{old}/")] == []
    assert dest.head(manifest_mod.manifest_key(new)) is not None


def test_an_unreadable_blob_list_stops_all_blob_deletion(dest: LocalDestination) -> None:
    keys = crypto.generate_keys()
    kept = _make_set(dest, keys, 1, [_blob(1)], 1)
    _put(dest, f"sets/{kept}/blobs.txt", b"tampered\n", timedelta(days=1))
    _put(dest, manifest_mod.blob_key(_blob(9)), b"x", timedelta(days=90))
    result = prune(dest, [keys.signing.signer], now=NOW, retention_days=30, min_sets=1,
                   grace=timedelta(hours=48), execute=True)  # fmt: skip
    assert result.delete_blobs == []
    assert any("unreadable" in note for note in result.notes)
    assert dest.head(manifest_mod.blob_key(_blob(9))) is not None


def test_a_set_signed_by_another_key_is_not_trusted(dest: LocalDestination) -> None:
    ours, theirs = crypto.generate_keys(), crypto.generate_keys()
    _make_set(dest, ours, 400, [_blob(1)], 1)
    _put(dest, manifest_mod.blob_key(_blob(1)), b"x", timedelta(days=400))
    # A newer "complete" set planted by someone else must not displace ours.
    _make_set(dest, theirs, 1, [], 2)
    result = prune(dest, [ours.signing.signer], now=NOW, retention_days=30, min_sets=1,
                   grace=timedelta(hours=48), execute=True)  # fmt: skip
    assert result.delete_sets == []
    assert result.delete_blobs == []
    assert len(list(dest.list("sets/"))) == 4
    assert dest.head(manifest_mod.blob_key(_blob(1))) is not None


def test_a_dry_run_deletes_nothing(dest: LocalDestination) -> None:
    keys = crypto.generate_keys()
    _make_set(dest, keys, 1, [], 1)
    old = _make_set(dest, keys, 90, [], 2)
    result = prune(dest, [keys.signing.signer], now=NOW, retention_days=30, min_sets=1,
                   grace=timedelta(hours=48), execute=False)  # fmt: skip
    assert result.delete_sets == [old]
    assert dest.head(manifest_mod.manifest_key(old)) is not None
