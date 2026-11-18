"""The tool that copies a laptop's files into object storage (D-090): a dry
run by default, every reference found, nothing deleted, nothing overwritten,
and no copy of personal documents without the founder's approval."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session as DbSession

from markx.core.config import get_config
from markx.core.storage import (
    LocalPrivateStorage,
    LocalPublicStorage,
    ObjectStorageSettings,
    ObjectStore,
    S3ObjectStore,
    StoreName,
)
from markx.worker.runner import run_once
from scripts import copy_files_to_object_storage as tool
from scripts.copy_files_to_object_storage import (
    ALREADY_THERE,
    COPIED,
    IN_THE_WAY,
    MISSING_LOCALLY,
    REFUSED,
    WOULD_COPY,
    FileRef,
    copy_files,
    file_references,
)
from tests.api.test_disputes import Delivered
from tests.bazaar import Bazaar
from tests.factories import start_application, upload_document
from tests.storage.conftest import SwitchStorage
from tests.unit.test_images import phone_jpeg


def picture(color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def laptop(tmp_path: Path) -> dict[StoreName, ObjectStore]:
    return {
        "private": LocalPrivateStorage(tmp_path / "private"),
        "public": LocalPublicStorage(tmp_path / "public"),
    }


@pytest.fixture
def buckets(stores: tuple[S3ObjectStore, S3ObjectStore]) -> dict[StoreName, ObjectStore]:
    private, public = stores
    return {"private": private, "public": public}


def _ref(key: str, store: StoreName = "private", content_type: str | None = "image/png") -> FileRef:
    return FileRef("seller_document", uuid.uuid4(), store, key, content_type)


def test_a_dry_run_reads_and_writes_nothing(
    laptop: dict[StoreName, ObjectStore], buckets: dict[StoreName, ObjectStore]
) -> None:
    key = f"copy/{uuid.uuid4().hex}"
    laptop["private"].put(key, picture(), "image/png")
    (outcome,) = copy_files([_ref(key)], laptop, buckets, execute=False)
    assert outcome.result == WOULD_COPY
    assert not buckets["private"].exists(key)


def test_a_copy_keeps_the_key_and_the_bytes_and_keeps_the_original(
    laptop: dict[StoreName, ObjectStore], buckets: dict[StoreName, ObjectStore], tmp_path: Path
) -> None:
    private_key, public_key = f"copy/{uuid.uuid4().hex}", f"copy/{uuid.uuid4().hex}-320.webp"
    laptop["private"].put(private_key, picture(), "image/png")
    webp = io.BytesIO()
    Image.new("RGB", (8, 8)).save(webp, "WEBP")
    laptop["public"].put(public_key, webp.getvalue(), "image/webp")
    refs = [_ref(private_key, content_type=None), _ref(public_key, "public", "image/webp")]

    assert [o.result for o in copy_files(refs, laptop, buckets, execute=True)] == [COPIED, COPIED]
    assert buckets["private"].get(private_key) == picture()
    assert buckets["private"].head(private_key).content_type == "image/png"
    assert buckets["public"].get(public_key) == webp.getvalue()
    assert not buckets["public"].exists(private_key)  # each to its own bucket
    # Nothing local was removed or changed.
    assert (tmp_path / "private" / private_key).read_bytes() == picture()
    assert (tmp_path / "public" / public_key).is_file()
    # A second run finds everything already there and writes nothing.
    again = copy_files(refs, laptop, buckets, execute=True)
    assert [o.result for o in again] == [ALREADY_THERE, ALREADY_THERE]


def test_an_object_already_in_the_bucket_is_never_overwritten(
    laptop: dict[StoreName, ObjectStore], buckets: dict[StoreName, ObjectStore]
) -> None:
    key = f"copy/{uuid.uuid4().hex}"
    laptop["private"].put(key, picture((1, 2, 3)), "image/png")
    buckets["private"].put(key, picture((9, 9, 9)), "image/png")
    (outcome,) = copy_files([_ref(key)], laptop, buckets, execute=True)
    assert outcome.result == IN_THE_WAY
    assert buckets["private"].get(key) == picture((9, 9, 9))


def test_missing_and_unusable_files_are_reported_not_copied(
    laptop: dict[StoreName, ObjectStore], buckets: dict[StoreName, ObjectStore], tmp_path: Path
) -> None:
    gone, lying = f"copy/{uuid.uuid4().hex}", f"copy/{uuid.uuid4().hex}"
    (tmp_path / "private" / "copy").mkdir(parents=True)
    (tmp_path / "private" / lying).write_bytes(b"\x89PNG\r\n\x1a\n but a JPEG row")
    outcomes = copy_files(
        [_ref(gone), _ref(lying, content_type="image/jpeg")], laptop, buckets, execute=True
    )
    assert [o.result for o in outcomes] == [MISSING_LOCALLY, REFUSED]
    assert not buckets["private"].exists(lying)
    report = tool.report(outcomes)
    assert str(outcomes[0].ref.row_id) in report
    # Rows by id, never by key.
    assert gone not in report
    assert lying not in report


def test_every_file_the_database_refers_to_is_found(db: DbSession, bazaar: Bazaar) -> None:
    """A document, a picture (source and both renderings) and a problem photo,
    made through the API on the laptop's disk."""
    applicant, seller_id = start_application(bazaar.staff, "0911000071", tin="0987654321")
    assert upload_document(applicant, seller_id, "owner_id").status_code == 201
    path = f"/admin/catalog/products/{bazaar.product['id']}/images"
    upload = bazaar.staff.post(path, files={"file": ("p.jpg", phone_jpeg(), "image/jpeg")})
    assert upload.status_code == 202
    run_once(datetime.now(UTC), jobs=())
    delivered = Delivered(bazaar)
    assert delivered.report().status_code == 200
    photo = delivered.buyer.post(
        f"{delivered.mine}/problem/photos", files={"file": ("p.jpg", phone_jpeg(), "image/jpeg")}
    )
    assert photo.status_code == 201

    db.rollback()
    refs = file_references(db)
    kinds = {r.kind for r in refs}
    assert kinds == {"picture_main", "picture_source", "picture_thumb", "problem_photo",
                     "seller_document"}  # fmt: skip
    root = get_config().storage_dir
    for ref in refs:
        assert (root / ref.store / ref.key).is_file(), ref.kind


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def test_the_tool_copies_nothing_without_the_founders_approval(
    minio: ObjectStorageSettings, switch: SwitchStorage, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    (tmp_path / "private").mkdir()
    switch.to(minio)
    with pytest.raises(SystemExit) as refused:
        tool.main(["--from-dir", str(tmp_path), "--execute"])
    assert refused.value.code == 2
    assert "--founder-approved" in capsys.readouterr().err


def test_the_tool_needs_object_storage_to_copy_into(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "private").mkdir()
    assert get_config().file_storage_provider == "local"
    with pytest.raises(SystemExit) as refused:
        tool.main(["--from-dir", str(tmp_path)])
    assert refused.value.code == 2
    assert "names no object storage" in capsys.readouterr().err


def test_the_tool_runs_end_to_end_as_a_dry_run_then_a_copy(
    db: DbSession, bazaar: Bazaar, minio: ObjectStorageSettings, switch: SwitchStorage,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    applicant, seller_id = start_application(bazaar.staff, "0911000072", tin="0987654322")
    document = upload_document(applicant, seller_id, "owner_id").json()
    local = get_config().storage_dir
    switch.to(minio)

    assert tool.main(["--from-dir", str(local)]) == 0
    dry = capsys.readouterr().out
    assert "Dry run, nothing written" in dry
    assert "would_copy" in dry
    assert tool.main(["--from-dir", str(local), "--execute", "--founder-approved"]) == 0
    assert "copied" in capsys.readouterr().out
    # The document now opens from the bucket, through the same personal link.
    link = applicant.post(f"/seller/{seller_id}/documents/{document['id']}/link").json()["url"]
    opened = applicant.http.get(link)
    assert opened.status_code == 200
    assert opened.content.startswith(b"\x89PNG")
