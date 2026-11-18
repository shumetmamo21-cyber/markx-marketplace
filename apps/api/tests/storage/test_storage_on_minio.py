"""The marketplace on object storage (D-090): the real API and worker keep
their files in MinIO buckets, with every protection of D-020 and D-062
unchanged. Documents and problem photos stay in the private bucket and open
only through the API's personal five-minute links; rendered pictures go to
the public bucket; an outage fails cleanly and names nothing."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffMember, StaffRole
from markx.audit.models import AuditLog
from markx.catalog.models import ProductImage
from markx.core.config import get_config
from markx.core.storage import ObjectStorageSettings, make_s3_client
from markx.notifications.models import Outbox
from markx.ops import checks
from markx.sellers import service as seller_service
from markx.sellers.models import SellerDocument
from markx.trust.models import ProblemPhoto
from markx.worker.runner import run_once
from tests.api.test_disputes import Delivered
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import staff_client, start_application, submit_application, upload_document
from tests.storage.conftest import SwitchStorage
from tests.unit.test_images import assert_bare, phone_jpeg

OPS = "0911000200"
CATALOGUE = "0911000201"
ABEBE = "0911000001"
STRANGER = "0911000009"


def _status(url: str, method: str = "GET") -> int:
    request = urllib.request.Request(url, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:  # noqa: S310
            return int(answer.status)
    except urllib.error.HTTPError as refused:
        return refused.code


def _object(settings: ObjectStorageSettings, bucket: str, key: str) -> dict[str, Any] | None:
    """The object as MinIO itself has it, read with MarkX's keys, or None."""
    client = make_s3_client(settings)
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            data = body.read()
        finally:
            body.close()
    except client.exceptions.ClientError:
        return None
    finally:
        client.close()
    return {"data": data, "content_type": head["ContentType"]}


def _photo_with_location() -> bytes:
    image = Image.new("RGB", (40, 30), (10, 120, 10))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x8825] = {1: "N", 2: (9.0, 1.0, 12.0), 3: "E", 4: (38.0, 45.0, 0.0)}  # GPS
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


@pytest.fixture
def staff(db: DbSession, on_minio: ObjectStorageSettings) -> ApiClient:
    return staff_client(db, OPS, StaffRole.OPERATIONS)


# -- sellers' identity documents ------------------------------------------------------------


def test_a_document_lives_only_in_the_private_bucket_without_its_metadata(
    staff: ApiClient, db: DbSession, on_minio: ObjectStorageSettings
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    response = upload_document(seller, seller_id, "owner_id", data=_photo_with_location())
    assert response.status_code == 201, response.text
    body = response.json()
    assert "file_key" not in body
    assert on_minio.private_bucket not in response.text
    assert on_minio.endpoint_url is not None
    assert on_minio.endpoint_url not in response.text

    document = db.get(SellerDocument, body["id"])
    assert document is not None
    stored = _object(on_minio, on_minio.private_bucket, document.file_key)
    assert stored is not None
    assert stored["content_type"] == "image/jpeg"
    assert b"PhoneMaker" not in stored["data"]
    assert len(Image.open(io.BytesIO(stored["data"])).getexif()) == 0
    # Nowhere else: not in the public bucket, not on the API's own disk.
    assert _object(on_minio, on_minio.public_bucket, document.file_key) is None
    assert not (get_config().storage_dir / "private" / document.file_key).exists()
    # And never to a reader without MarkX's keys, by any address.
    for url in (
        f"{on_minio.endpoint_url}/{on_minio.private_bucket}/{document.file_key}",
        f"{on_minio.endpoint_url}/{on_minio.private_bucket}",
        f"{on_minio.endpoint_url}/{on_minio.private_bucket}?list-type=2",
    ):
        assert _status(url) == 403, url


def test_a_document_opens_only_through_its_personal_link_and_every_view_is_logged(
    staff: ApiClient, db: DbSession, on_minio: ObjectStorageSettings
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    submit_application(seller, seller_id)
    document = staff.get(f"/admin/sellers/{seller_id}").json()["documents"][0]

    link = staff.post(f"/admin/sellers/{seller_id}/documents/{document['id']}/link").json()
    # The link is the API's own, never a bucket address.
    assert link["url"].startswith("/api/v1/documents/")
    assert on_minio.endpoint_url is not None
    assert on_minio.endpoint_url not in json.dumps(link)
    assert "X-Amz" not in link["url"]

    opened = staff.http.get(link["url"])
    assert opened.status_code == 200
    assert opened.headers["content-type"] == "image/png"
    assert opened.headers["cache-control"] == "private, no-store"
    assert opened.content.startswith(b"\x89PNG")

    # Another person with the same link: refused, the same answer as a forgery.
    stranger = ApiClient()
    stranger.sign_in(STRANGER)
    refused = stranger.http.get(link["url"])
    assert refused.status_code == 403
    assert error_code(refused) == "document_link_invalid"
    assert ApiClient().http.get(link["url"]).status_code == 401
    # Staff whose role does not look at documents: refused.
    catalogue = staff_client(db, CATALOGUE, StaffRole.CATALOGUE)
    assert catalogue.http.get(link["url"]).status_code == 403

    db.rollback()
    views = list(db.scalars(select(AuditLog).where(AuditLog.action == "seller_document.viewed")))
    assert len(views) == 1
    assert views[0].target_id == document["id"]

    # Permission is checked again at every opening (D-020): the same person,
    # with the same unexpired link, is refused once their role no longer
    # looks at documents.
    member = db.scalar(select(StaffMember).where(StaffMember.role == StaffRole.OPERATIONS.value))
    assert member is not None
    member.role = StaffRole.SUPPORT.value
    db.commit()
    demoted = staff.http.get(link["url"])
    assert demoted.status_code == 403
    assert error_code(demoted) == "document_link_invalid"


def test_a_document_link_still_expires_after_five_minutes(
    staff: ApiClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    document_id = upload_document(seller, seller_id, "owner_id").json()["id"]
    link = seller.post(f"/seller/{seller_id}/documents/{document_id}/link").json()["url"]
    assert seller.http.get(link).status_code == 200
    later = datetime.now(UTC) + timedelta(seconds=seller_service.DOCUMENT_LINK_SECONDS + 1)
    monkeypatch.setattr(seller_service, "_now", lambda: later)
    expired = seller.http.get(link)
    assert expired.status_code == 403
    assert error_code(expired) == "document_link_invalid"


def test_another_shop_cannot_reach_a_document_on_object_storage(
    staff: ApiClient, on_minio: ObjectStorageSettings
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    document_id = upload_document(seller, seller_id, "owner_id").json()["id"]
    other, other_id = start_application(staff, STRANGER, tin="0000000009")
    assert other.post(f"/seller/{seller_id}/documents/{document_id}/link").status_code == 404
    assert other.post(f"/seller/{other_id}/documents/{document_id}/link").status_code == 404
    assert other.get(f"/seller/{seller_id}/documents").status_code == 404


def test_a_document_that_is_not_a_picture_never_reaches_the_bucket(
    staff: ApiClient, db: DbSession, on_minio: ObjectStorageSettings
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    for data in (b"<html><script>alert(1)</script></html>", b"%PDF-1.7", b"GIF89a" + b"\0" * 64):
        refused = upload_document(seller, seller_id, "owner_id", data=data)
        assert refused.status_code == 422
        assert error_code(refused) == "document_not_an_image"
    client = make_s3_client(on_minio)
    try:
        listed = client.list_objects_v2(
            Bucket=on_minio.private_bucket, Prefix=f"seller-documents/{seller_id}/"
        )
    finally:
        client.close()
    assert listed.get("KeyCount", 0) == 0


# -- product pictures -----------------------------------------------------------------------


@pytest.fixture
def bazaar(db: DbSession, on_minio: ObjectStorageSettings) -> Bazaar:
    return Bazaar(db)


def _upload(client: ApiClient, path: str, data: bytes) -> Any:
    return client.post(path, files={"file": ("photo.jpg", data, "image/jpeg")})


def _render(now: datetime | None = None) -> None:
    run_once(now or datetime.now(UTC), jobs=())


def test_a_picture_is_kept_privately_rendered_by_the_worker_and_served_publicly(
    bazaar: Bazaar, db: DbSession, on_minio: ObjectStorageSettings
) -> None:
    product = bazaar.product
    uploaded = _upload(
        bazaar.staff, f"/admin/catalog/products/{product['id']}/images", phone_jpeg()
    )
    assert uploaded.status_code == 202, uploaded.text
    row = db.get(ProductImage, uuid.UUID(uploaded.json()["id"]))
    assert row is not None
    assert row.source_key is not None
    source = _object(on_minio, on_minio.private_bucket, row.source_key)
    assert source is not None
    assert dict(Image.open(io.BytesIO(source["data"])).getexif()) == {}
    assert _object(on_minio, on_minio.public_bucket, row.source_key) is None

    _render()
    shown = ApiClient().get(f"/catalog/products/{product['slug']}/images").json()["catalogue"]
    assert len(shown) == 1
    for url, budget in ((shown[0]["thumb_url"], 30_000), (shown[0]["main_url"], 150_000)):
        key = url.removeprefix("/api/v1/media/")
        stored = _object(on_minio, on_minio.public_bucket, key)
        assert stored is not None
        assert stored["content_type"] == "image/webp"
        assert len(stored["data"]) <= budget
        assert_bare(stored["data"])
        assert _object(on_minio, on_minio.private_bucket, key) is None
        # On a laptop the API serves them from the bucket; a real server's CDN does.
        served = ApiClient().http.get(url)
        assert served.status_code == 200
        assert served.content == stored["data"]
        assert "set-cookie" not in served.headers


def test_a_render_waits_for_the_store_and_finishes_once_it_is_back(
    bazaar: Bazaar, db: DbSession, on_minio: ObjectStorageSettings, switch: SwitchStorage
) -> None:
    uploaded = _upload(
        bazaar.staff, f"/admin/catalog/products/{bazaar.product['id']}/images", phone_jpeg()
    )
    image_id = uuid.UUID(uploaded.json()["id"])

    switch.to_unreachable(on_minio)
    _render()
    db.rollback()
    image = db.get(ProductImage, image_id)
    assert image is not None
    assert image.status == "processing"  # not failed: the source is fine, the store is away
    (message,) = db.scalars(select(Outbox).where(Outbox.topic == "images.render"))
    assert (message.status, message.attempts) == ("pending", 1)
    assert message.last_error is not None
    assert "127.0.0.1" not in message.last_error

    switch.to(on_minio)
    _render(datetime.now(UTC) + timedelta(hours=1))
    db.rollback()
    image = db.get(ProductImage, image_id)
    assert image is not None
    assert image.status == "ready"


# -- problem photos -----------------------------------------------------------------------


def test_problem_photos_stay_private_and_open_only_for_the_case(
    bazaar: Bazaar, db: DbSession, on_minio: ObjectStorageSettings
) -> None:
    d = Delivered(bazaar)
    assert d.report().status_code == 200
    added = _upload(d.buyer, f"{d.mine}/problem/photos", phone_jpeg())
    assert added.status_code == 201, added.text
    photo = added.json()
    assert "file_key" not in photo
    assert photo["url"].startswith("/api/v1/")

    row = db.get(ProblemPhoto, uuid.UUID(photo["id"]))
    assert row is not None
    stored = _object(on_minio, on_minio.private_bucket, row.file_key)
    assert stored is not None
    assert stored["content_type"] == "image/webp"
    assert _object(on_minio, on_minio.public_bucket, row.file_key) is None
    assert _status(f"{on_minio.endpoint_url}/{on_minio.private_bucket}/{row.file_key}") == 403

    served = d.buyer.get(photo["url"].removeprefix("/api/v1"))
    assert served.status_code == 200
    assert served.content == stored["data"]
    assert bazaar.b.get(photo["url"].removeprefix("/api/v1")).status_code == 403
    assert ApiClient().get(photo["url"].removeprefix("/api/v1")).status_code == 401


# -- when the store is away -----------------------------------------------------------------


def test_an_upload_while_the_store_is_away_fails_cleanly_and_leaves_no_row(
    staff: ApiClient, db: DbSession, on_minio: ObjectStorageSettings, switch: SwitchStorage
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    switch.to_unreachable(on_minio)
    response = upload_document(seller, seller_id, "owner_id")
    assert response.status_code == 503
    assert error_code(response) == "storage_unavailable"
    for leak in ("127.0.0.1", on_minio.private_bucket, "seller-documents", "botocore"):
        assert leak not in response.text
    db.rollback()
    assert db.scalar(select(func.count()).select_from(SellerDocument)) == 0
    uploads = select(func.count()).select_from(AuditLog)
    assert db.scalar(uploads.where(AuditLog.action == "seller_document.upload")) == 0


def test_opening_a_document_while_the_store_is_away_says_so(
    staff: ApiClient, on_minio: ObjectStorageSettings, switch: SwitchStorage
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    document_id = upload_document(seller, seller_id, "owner_id").json()["id"]
    link = seller.post(f"/seller/{seller_id}/documents/{document_id}/link").json()["url"]
    switch.to_unreachable(on_minio)
    response = seller.http.get(link)
    assert response.status_code == 503
    assert error_code(response) == "storage_unavailable"


# -- the watch (D-064) ----------------------------------------------------------------------


def test_the_watch_is_quiet_while_both_buckets_answer(
    db: DbSession, on_minio: ObjectStorageSettings
) -> None:
    assert checks.file_storage(db, datetime.now(UTC)) == []


def test_the_watch_raises_an_alert_when_the_store_is_away(
    db: DbSession, on_minio: ObjectStorageSettings, switch: SwitchStorage
) -> None:
    switch.to_unreachable(on_minio)
    findings = checks.file_storage(db, datetime.now(UTC))
    assert {f.key for f in findings} == {
        "storage.unreachable:private",
        "storage.unreachable:public",
    }
    assert all(f.severity == "critical" for f in findings)
    for finding in findings:
        assert on_minio.private_bucket not in finding.summary + str(finding.details)


def test_the_watch_raises_an_alert_when_the_private_bucket_turns_public(
    db: DbSession, minio: ObjectStorageSettings, scratch_bucket: str, switch: SwitchStorage
) -> None:
    """Someone made the document bucket readable by anyone: critical at once."""
    from dataclasses import replace

    exposed = replace(minio, private_bucket=scratch_bucket)
    switch.to(exposed)
    assert checks.file_storage(db, datetime.now(UTC)) == []

    client = make_s3_client(minio)
    try:
        client.put_bucket_policy(
            Bucket=scratch_bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{scratch_bucket}/*"],
                        }
                    ],
                }
            ),
        )
    finally:
        client.close()
    (finding,) = checks.file_storage(db, datetime.now(UTC))
    assert (finding.key, finding.severity) == ("storage.private_bucket_public", "critical")


def test_the_watch_has_nothing_to_check_on_a_laptops_disk(db: DbSession) -> None:
    assert get_config().file_storage_provider == "local"
    assert checks.file_storage(db, datetime.now(UTC)) == []
