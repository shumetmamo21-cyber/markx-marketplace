"""Private documents: upload checks, five-minute links, a log of every view
(blueprint D.3, F.6, P6 completion criterion three)."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.core import settings_store
from markx.core.config import get_config
from markx.core.storage import LocalPrivateStorage, get_private_storage
from markx.sellers import service
from markx.sellers.models import SellerDocument
from tests.conftest import ApiClient, error_code
from tests.factories import (
    image_bytes,
    staff_client,
    start_application,
    submit_application,
    upload_document,
)

OPS = "0911000200"
ABEBE = "0911000001"


@pytest.fixture
def staff(db: DbSession) -> ApiClient:
    return staff_client(db, OPS, StaffRole.OPERATIONS)


def _views(db: DbSession, action: str) -> list[AuditLog]:
    db.rollback()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def _photo_with_location() -> bytes:
    image = Image.new("RGB", (40, 30), (10, 120, 10))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x8825] = {1: "N", 2: (9.0, 1.0, 12.0), 3: "E", 4: (38.0, 45.0, 0.0)}  # GPS
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


# -- upload ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "content_type"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_a_photo_is_stored_privately(
    staff: ApiClient, db: DbSession, fmt: str, content_type: str
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    response = upload_document(seller, seller_id, "owner_id", data=image_bytes(fmt))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_type"] == content_type
    assert body["review_status"] == "pending"
    # Where the file lives is the server's business.
    assert "file_key" not in body

    document = db.get(SellerDocument, body["id"])
    assert document is not None
    assert document.file_key.startswith(f"seller-documents/{seller_id}/")
    stored = Path(get_config().storage_dir) / "private" / document.file_key
    assert stored.is_file()
    assert stored.stat().st_mode & 0o077 == 0
    with Image.open(stored) as saved:
        assert saved.format == fmt


def test_the_declared_type_is_ignored_and_the_bytes_decide(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    for data in (
        b"<html><script>alert(1)</script></html>",
        b"%PDF-1.7 not a picture",
        image_bytes()[:40],  # a truncated picture
        b"GIF89a" + b"\x00" * 64,
    ):
        response = upload_document(seller, seller_id, "owner_id", data=data)
        assert response.status_code == 422, data[:12]
        assert error_code(response) == "document_not_an_image"
    assert error_code(upload_document(seller, seller_id, "owner_id", data=b"")) == "document_empty"
    assert seller.get(f"/seller/{seller_id}/documents").json() == []


def test_location_data_is_stripped_from_a_document_photo(staff: ApiClient, db: DbSession) -> None:
    original = _photo_with_location()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(0x8825)
    seller, seller_id = start_application(staff, ABEBE)
    document_id = upload_document(seller, seller_id, "shop_photo", data=original).json()["id"]
    document = db.get(SellerDocument, document_id)
    assert document is not None
    cleaned = Image.open(io.BytesIO(get_private_storage().get(document.file_key)))
    assert len(cleaned.getexif()) == 0
    assert b"PhoneMaker" not in get_private_storage().get(document.file_key)


def test_an_oversized_file_or_an_unknown_type_is_refused(staff: ApiClient, db: DbSession) -> None:
    settings_store.set_setting(db, "sellers.document_max_bytes", 10_000)
    db.commit()
    seller, seller_id = start_application(staff, ABEBE)
    noisy = Image.effect_noise((400, 400), 90).convert("RGB")
    buffer = io.BytesIO()
    noisy.save(buffer, "PNG")
    assert len(buffer.getvalue()) > 10_000
    too_large = upload_document(seller, seller_id, "owner_id", data=buffer.getvalue())
    assert error_code(too_large) == "document_too_large"
    assert upload_document(seller, seller_id, "passport_of_a_friend").status_code == 422


def test_storage_keys_cannot_escape_the_private_folder(tmp_path: Path) -> None:
    storage = LocalPrivateStorage(tmp_path)
    for key in ("../outside", "/etc/passwd", "a/../../b", "a//b", "A/B", ""):
        with pytest.raises(ValueError, match="unsafe storage key"):
            storage.put(key, b"x")


def test_real_servers_refuse_the_development_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    from markx.core import storage

    class Real:
        is_real_environment = True

    monkeypatch.setattr(storage, "get_config", lambda: Real())
    with pytest.raises(RuntimeError, match="development only"):
        storage.get_private_storage()


# -- links -----------------------------------------------------------------------


def test_staff_open_a_document_through_a_link_and_every_view_is_logged(
    staff: ApiClient, db: DbSession
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    submit_application(seller, seller_id)
    document = staff.get(f"/admin/sellers/{seller_id}").json()["documents"][0]

    issued = staff.post(f"/admin/sellers/{seller_id}/documents/{document['id']}/link")
    assert issued.status_code == 200
    link = issued.json()
    lifetime = datetime.fromisoformat(link["expires_at"]) - datetime.now(UTC)
    assert timedelta(minutes=4) < lifetime <= timedelta(minutes=5)

    opened = staff.http.get(link["url"])
    assert opened.status_code == 200
    assert opened.headers["content-type"] == "image/png"
    assert opened.headers["cache-control"] == "private, no-store"
    assert opened.headers["x-content-type-options"] == "nosniff"
    assert opened.content.startswith(b"\x89PNG")
    staff.http.get(link["url"])

    [issue] = _views(db, "seller_document.link_issued")
    views = _views(db, "seller_document.viewed")
    assert len(views) == 2
    for entry in (issue, *views):
        assert entry.actor_type == "staff"
        assert entry.actor_user_id is not None
        assert entry.target_id == document["id"]
        assert str(entry.ip) == "203.0.113.10"
    assert views[0].after == {"seller_id": seller_id, "doc_type": document["doc_type"]}


def test_a_link_stops_working_after_five_minutes(
    staff: ApiClient, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    document_id = upload_document(seller, seller_id, "owner_id").json()["id"]
    link = seller.post(f"/seller/{seller_id}/documents/{document_id}/link").json()["url"]

    almost = datetime.now(UTC) + timedelta(seconds=service.DOCUMENT_LINK_SECONDS - 5)
    monkeypatch.setattr(service, "_now", lambda: almost)
    assert seller.http.get(link).status_code == 200

    after = datetime.now(UTC) + timedelta(seconds=service.DOCUMENT_LINK_SECONDS + 1)
    monkeypatch.setattr(service, "_now", lambda: after)
    expired = seller.http.get(link)
    assert expired.status_code == 403
    assert error_code(expired) == "document_link_invalid"
    assert len(_views(db, "seller_document.viewed")) == 1


def _altered(signature: str, position: int) -> str:
    """The signature with one character replaced by a different one."""
    replacement = "B" if signature[position] == "A" else "A"
    return signature[:position] + replacement + signature[position + 1 :]


def test_a_link_cannot_be_extended_or_forged(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    document_id = upload_document(seller, seller_id, "owner_id").json()["id"]
    link = seller.post(f"/seller/{seller_id}/documents/{document_id}/link").json()["url"]
    path, query = link.split("?")
    params = dict(part.split("=") for part in query.split("&"))

    far_future = str(int(params["expires"]) + 86_400)
    genuine = params["signature"]
    made_up = "A" * len(genuine) if genuine != "A" * len(genuine) else "B" * len(genuine)
    for tampered in (
        {**params, "expires": far_future},
        {**params, "signature": _altered(genuine, 0)},
        {**params, "signature": _altered(genuine, len(genuine) - 2)},
        {**params, "signature": made_up},
    ):
        # Every forgery really differs from the genuine link. (Replacing the
        # last two characters with "AA" left it unchanged about once in a
        # thousand runs, when the real signature already ended in "AA".)
        assert tampered != params
        response = seller.http.get(path, params=tampered)
        assert response.status_code == 403
        assert error_code(response) == "document_link_invalid"
    assert seller.http.get(path).status_code == 422
    assert seller.http.get(path, params=params).status_code == 200


def test_a_staff_link_dies_with_the_staff_members_permission(
    staff: ApiClient, db: DbSession
) -> None:
    """Permission is checked again when the link is opened, not only when issued."""
    from markx.accounts.models import StaffMember

    seller, seller_id = start_application(staff, ABEBE)
    submit_application(seller, seller_id)
    document = staff.get(f"/admin/sellers/{seller_id}").json()["documents"][0]
    link = staff.post(f"/admin/sellers/{seller_id}/documents/{document['id']}/link").json()["url"]

    member = db.scalar(select(StaffMember))
    assert member is not None
    member.role = StaffRole.SUPPORT.value
    db.commit()
    response = staff.http.get(link)
    assert response.status_code == 403
    assert error_code(response) == "document_link_invalid"


def test_a_managers_link_request_is_refused(staff: ApiClient) -> None:
    from tests.factories import make_seller

    owner, seller_id = make_seller(staff, ABEBE)
    owner.post(f"/seller/{seller_id}/members", json={"phone": "0911000050"})
    manager = ApiClient()
    manager.sign_in("0911000050")
    document_id = owner.get(f"/seller/{seller_id}/documents").json()[0]["id"]
    assert manager.get(f"/seller/{seller_id}/documents").status_code == 403
    assert manager.post(f"/seller/{seller_id}/documents/{document_id}/link").status_code == 403
    assert upload_document(manager, seller_id, "other").status_code == 403
    # Even holding the owner's link, the manager is not the person it was signed for.
    link = owner.post(f"/seller/{seller_id}/documents/{document_id}/link").json()["url"]
    assert manager.http.get(link).status_code == 403


def test_staff_cannot_open_documents_of_a_draft_application(staff: ApiClient) -> None:
    seller, seller_id = start_application(staff, ABEBE)
    document_id = upload_document(seller, seller_id, "owner_id").json()["id"]
    response = staff.post(f"/admin/sellers/{seller_id}/documents/{document_id}/link")
    assert response.status_code == 404
