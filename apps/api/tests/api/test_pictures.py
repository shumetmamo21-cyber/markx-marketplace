"""Product pictures and problem photos (blueprint F.6, D.5, S-06, C-16, AD-03,
P5 criterion 3; D-062): cleaned at upload, rendered by the worker to small
WebP files with no location data, shown only when ready, moderated by
staff, and evidence opened only by the people on the case.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from PIL import ExifTags, Image
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.catalog.models import ProductImage
from markx.core import settings_store
from markx.core.storage import get_private_storage
from markx.trust.models import ProblemPhoto
from markx.worker.runner import run_once
from tests.api.test_disputes import Delivered
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import make_product, make_seller, staff_client
from tests.unit.test_images import assert_bare, phone_jpeg

NO_JOBS = ()


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _upload(client: ApiClient, path: str, data: bytes, name: str = "photo.jpg") -> Any:
    return client.post(path, files={"file": (name, data, "image/jpeg")})


def _render() -> None:
    run_once(datetime.now(UTC), jobs=NO_JOBS)


def _images(bazaar: Bazaar) -> dict[str, Any]:
    response = ApiClient().get(f"/catalog/products/{bazaar.product['slug']}/images")
    assert response.status_code == 200, response.text
    return dict(response.json())


def _fetch(url: str) -> Any:
    assert url.startswith("/api/v1/media/"), url
    return ApiClient().http.get(url)


def test_a_catalogue_picture_is_cleaned_rendered_and_shown(bazaar: Bazaar, db: DbSession) -> None:
    """P5 criterion 3: served as small WebP files with no location data."""
    product_id = bazaar.product["id"]
    uploaded = _upload(bazaar.staff, f"/admin/catalog/products/{product_id}/images", phone_jpeg())
    assert uploaded.status_code == 202, uploaded.text
    image = uploaded.json()
    assert (image["status"], image["kind"], image["thumb_url"]) == ("processing", "catalogue", None)
    # Not shown until the worker has rendered it.
    assert _images(bazaar)["catalogue"] == []

    # The private source already carries no location: the camera's original
    # never reached storage.
    row = db.get(ProductImage, uuid.UUID(image["id"]))
    assert row is not None
    assert row.source_key is not None
    source = Image.open(io.BytesIO(get_private_storage().get(row.source_key)))
    assert dict(source.getexif()) == {}

    _render()
    (shown,) = _images(bazaar)["catalogue"]
    assert shown["id"] == image["id"]
    # Upright: the phone's 400 x 300 photo was taken turned.
    assert (shown["width"], shown["height"]) == (300, 400)
    for url, budget in ((shown["thumb_url"], 30_000), (shown["main_url"], 150_000)):
        served = _fetch(url)
        assert served.status_code == 200
        assert served.headers["content-type"] == "image/webp"
        assert "immutable" in served.headers["cache-control"]
        assert "set-cookie" not in served.headers
        assert len(served.content) <= budget
        picture = assert_bare(served.content)
        assert ExifTags.IFD.GPSInfo not in picture.getexif()

    detail = bazaar.staff.get(f"/admin/catalog/products/{product_id}/images").json()
    assert [(i["status"], i["thumb_bytes"] > 0, i["main_bytes"] > 0) for i in detail] == [
        ("ready", True, True)
    ]
    actions = db.scalars(select(AuditLog.action).where(AuditLog.target_id == image["id"])).all()
    assert actions == ["product_image.upload"]


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "image_empty"),
        (b"%PDF-1.7 a document, not a photo", "image_not_a_photo"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image_not_a_photo"),
    ],
)  # fmt: skip
def test_anything_but_a_photo_is_refused(bazaar: Bazaar, data: bytes, code: str) -> None:
    response = _upload(bazaar.staff, f"/admin/catalog/products/{bazaar.product['id']}/images", data)
    assert response.status_code == 422, response.text
    assert error_code(response) == code


def test_an_oversized_upload_is_refused_without_reading_it_all(
    bazaar: Bazaar, db: DbSession
) -> None:
    settings_store.set_setting(db, "images.max_upload_bytes", 100_000)
    db.commit()
    big = phone_jpeg(3000, 3000) + b"\x00" * 200_000
    response = _upload(bazaar.staff, f"/admin/catalog/products/{bazaar.product['id']}/images", big)
    assert response.status_code == 422
    assert error_code(response) == "image_too_large"


def test_who_may_add_and_remove_catalogue_pictures(bazaar: Bazaar, db: DbSession) -> None:
    """Blueprint C.4: catalogue staff add pictures; super administrator,
    operations and catalogue moderate them; support and finance do neither."""
    path = f"/admin/catalog/products/{bazaar.product['id']}/images"
    staff = {
        role: staff_client(db, f"09110003{i:02d}", role)
        for i, role in enumerate(
            (StaffRole.OPERATIONS, StaffRole.SUPPORT, StaffRole.CATALOGUE, StaffRole.FINANCE)
        )
    }
    for role in (StaffRole.OPERATIONS, StaffRole.SUPPORT, StaffRole.FINANCE):
        assert _upload(staff[role], path, phone_jpeg()).status_code == 403, role
    added = _upload(staff[StaffRole.CATALOGUE], path, phone_jpeg())
    assert added.status_code == 202
    image_id = added.json()["id"]
    # A buyer or a seller is not staff at all.
    assert _upload(bazaar.a, path, phone_jpeg()).status_code == 403
    for role in (StaffRole.SUPPORT, StaffRole.FINANCE):
        refused = staff[role].post(
            f"/admin/catalog/images/{image_id}/remove", json={"reason": "No"}
        )
        assert refused.status_code == 403
    removed = staff[StaffRole.OPERATIONS].post(
        f"/admin/catalog/images/{image_id}/remove", json={"reason": "Shows a competitor's logo"}
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "removed"
    again = staff[StaffRole.CATALOGUE].post(
        f"/admin/catalog/images/{image_id}/remove", json={"reason": "Again"}
    )
    assert error_code(again) == "image_already_removed"
    _render()  # a removed picture is never rendered or shown
    assert _images(bazaar)["catalogue"] == []
    (entry,) = db.scalars(
        select(AuditLog).where(AuditLog.target_id == image_id, AuditLog.action == "product_image.remove")
    )  # fmt: skip
    assert entry.after["reason"] == "Shows a competitor's logo"
    assert entry.before == {"status": "processing"}


def test_the_catalogue_picture_limit_holds(bazaar: Bazaar, db: DbSession) -> None:
    settings_store.set_setting(db, "images.max_catalogue_per_product", 2)
    db.commit()
    path = f"/admin/catalog/products/{bazaar.product['id']}/images"
    first = _upload(bazaar.staff, path, phone_jpeg())
    assert _upload(bazaar.staff, path, phone_jpeg()).status_code == 202
    over = _upload(bazaar.staff, path, phone_jpeg())
    assert over.status_code == 409
    assert error_code(over) == "too_many_images"
    # A removed picture no longer counts.
    bazaar.staff.post(
        f"/admin/catalog/images/{first.json()['id']}/remove", json={"reason": "Blurry"}
    )
    assert _upload(bazaar.staff, path, phone_jpeg()).status_code == 202


def test_the_product_card_shows_the_first_ready_catalogue_picture(bazaar: Bazaar) -> None:
    """D.9: the card everywhere carries a photo (D-074): the first catalogue
    picture that is ready, never a shop's own photo."""

    def card() -> dict[str, Any]:
        results = ApiClient().get("/search", params={"q": ""}).json()["results"]
        return dict(next(r for r in results if r["product_id"] == bazaar.product["id"]))

    _render()
    assert card()["thumb_url"] is None
    path = f"/admin/catalog/products/{bazaar.product['id']}/images"
    for _ in range(2):
        assert _upload(bazaar.staff, path, phone_jpeg()).status_code == 202
    assert card()["thumb_url"] is None  # not before the worker has rendered it
    _render()
    first, second = _images(bazaar)["catalogue"]
    assert card()["thumb_url"] == first["thumb_url"]
    assert _fetch(first["thumb_url"]).status_code == 200

    # Taken down: the next picture takes its place.
    removed = bazaar.staff.post(
        f"/admin/catalog/images/{first['id']}/remove", json={"reason": "Blurry"}
    )
    assert removed.status_code == 200
    assert card()["thumb_url"] == second["thumb_url"]

    # A shop's real photo is shown on the product page, never on the card.
    photos = f"/seller/{bazaar.a_id}/products/{bazaar.product['id']}/photos"
    assert _upload(bazaar.a, photos, phone_jpeg()).status_code == 202
    _render()
    assert len(_images(bazaar)["real_photos"]) == 1
    bazaar.staff.post(f"/admin/catalog/images/{second['id']}/remove", json={"reason": "Blurry"})
    assert card()["thumb_url"] is None


def test_a_seller_adds_real_photos_only_for_what_it_sells(bazaar: Bazaar, db: DbSession) -> None:
    """D.5, S-06: a "Real photo" names its store; only for a product the store
    has an offer on; one store cannot touch another's photos."""
    product_id = bazaar.product["id"]
    alpha = f"/seller/{bazaar.a_id}/products/{product_id}/photos"
    added = _upload(bazaar.a, alpha, phone_jpeg())
    assert added.status_code == 202, added.text
    assert (added.json()["kind"], added.json()["seller_id"]) == ("seller_real_photo", bazaar.a_id)
    _render()
    (real,) = _images(bazaar)["real_photos"]
    assert real["store_slug"] == "alpha"
    assert _fetch(real["main_url"]).status_code == 200

    # A store with no offer on the product may not add photos of it.
    gamma, gamma_id = make_seller(bazaar.staff, "0911000003", tin="0000000003", trade_name="Gamma")
    refused = _upload(gamma, f"/seller/{gamma_id}/products/{product_id}/photos", phone_jpeg())
    assert refused.status_code == 409
    assert error_code(refused) == "no_offer_for_product"
    # Beta cannot see or withdraw Alpha's photo through its own store.
    assert bazaar.b.get(f"/seller/{bazaar.b_id}/products/{product_id}/photos").json() == []
    stolen = bazaar.b.post(f"/seller/{bazaar.b_id}/photos/{real['id']}/withdraw")
    assert stolen.status_code == 404
    # Nor through Alpha's id: the seller in the path is checked first.
    assert bazaar.b.post(f"/seller/{bazaar.a_id}/photos/{real['id']}/withdraw").status_code == 404
    # Alpha withdraws its own: gone from the page at once.
    withdrawn = bazaar.a.post(f"/seller/{bazaar.a_id}/photos/{real['id']}/withdraw")
    assert withdrawn.status_code == 200
    assert withdrawn.json()["removed_reason"] == "withdrawn by the seller"
    assert _images(bazaar)["real_photos"] == []


def test_a_suspended_stores_photos_disappear(bazaar: Bazaar, db: DbSession) -> None:
    alpha = f"/seller/{bazaar.a_id}/products/{bazaar.product['id']}/photos"
    assert _upload(bazaar.a, alpha, phone_jpeg()).status_code == 202
    _render()
    assert len(_images(bazaar)["real_photos"]) == 1
    suspended = bazaar.staff.post(
        f"/admin/sellers/{bazaar.a_id}/suspend", json={"reason": "Fake documents"}
    )
    assert suspended.status_code == 200, suspended.text
    assert _images(bazaar)["real_photos"] == []


def test_a_source_that_cannot_be_rendered_is_marked_failed(bazaar: Bazaar, db: DbSession) -> None:
    """The worker's failure path: the picture is marked failed, never shown,
    and the outbox message is done rather than retried for ever."""
    uploaded = _upload(
        bazaar.staff, f"/admin/catalog/products/{bazaar.product['id']}/images", phone_jpeg()
    )
    row = db.get(ProductImage, uuid.UUID(uploaded.json()["id"]))
    assert row is not None
    assert row.source_key is not None
    get_private_storage().put(row.source_key, b"damaged on disk")
    _render()
    (detail,) = bazaar.staff.get(f"/admin/catalog/products/{bazaar.product['id']}/images").json()
    assert detail["status"] == "failed"
    assert detail["failure_reason"]
    assert _images(bazaar)["catalogue"] == []


def test_a_draft_or_unknown_product_has_no_public_pictures(bazaar: Bazaar) -> None:
    draft = make_product(
        bazaar.staff, bazaar.catalog, model="3310", name_am="ኖኪያ 3310", name_en="Nokia 3310",
        status="draft", brand_id=None,
    )  # fmt: skip
    path = f"/admin/catalog/products/{draft['id']}/images"
    assert _upload(bazaar.staff, path, phone_jpeg()).status_code == 202  # staff prepare it
    _render()
    assert ApiClient().get(f"/catalog/products/{draft['slug']}/images").status_code == 404
    assert ApiClient().get("/catalog/products/no-such-thing/images").status_code == 404


# -- problem photos (C-16) --------------------------------------------------------------


@pytest.fixture
def reported(bazaar: Bazaar) -> Delivered:
    delivered = Delivered(bazaar)
    assert delivered.report().status_code == 200
    return delivered


def test_both_sides_add_evidence_and_only_the_case_can_open_it(
    bazaar: Bazaar, reported: Delivered, db: DbSession
) -> None:
    d = reported
    added = _upload(d.buyer, f"{d.mine}/problem/photos", phone_jpeg())
    assert added.status_code == 201, added.text
    photo = added.json()
    assert photo["author_type"] == "buyer"
    # The buyer opens it through their own link: a bare WebP, upright.
    served = d.buyer.get(photo["url"].removeprefix("/api/v1"))
    assert served.status_code == 200
    assert served.headers["cache-control"] == "private, no-store"
    assert (assert_bare(served.content).size) == (photo["width"], photo["height"])
    assert photo["width"] < photo["height"]

    seller_added = _upload(bazaar.a, f"{d.seller}/problem/photos", phone_jpeg(orientation=1))
    assert seller_added.status_code == 201, seller_added.text
    seller_view = bazaar.a.get(f"{d.seller}/problem/photos").json()
    assert [p["author_type"] for p in seller_view] == ["buyer", "seller"]
    assert bazaar.a.get(seller_view[0]["url"].removeprefix("/api/v1")).status_code == 200

    # A link is for the person it was issued to: the seller cannot use the
    # buyer's, another seller cannot use either, nor see the list.
    assert bazaar.a.get(photo["url"].removeprefix("/api/v1")).status_code == 403
    assert bazaar.b.get(seller_view[0]["url"].removeprefix("/api/v1")).status_code == 403
    assert bazaar.b.get(f"/seller/{bazaar.b_id}/orders/{d.so_id}/problem/photos").status_code == 404
    stranger, _ = bazaar.buyer()
    assert stranger.get(f"{d.mine}/problem/photos").status_code == 404
    assert stranger.get(photo["url"].removeprefix("/api/v1")).status_code == 403
    assert ApiClient().get(photo["url"].removeprefix("/api/v1")).status_code == 401

    # Staff who handle cases see both sides; every staff view is logged.
    support = staff_client(db, "0911000300", StaffRole.SUPPORT)
    staff_view = support.get(f"{d.admin}/problem/photos").json()
    assert len(staff_view) == 2
    assert support.get(staff_view[1]["url"].removeprefix("/api/v1")).status_code == 200
    viewed = db.scalars(select(AuditLog.action).where(AuditLog.action == "problem_photo.viewed"))
    assert list(viewed) == ["problem_photo.viewed"]
    catalogue = staff_client(db, "0911000301", StaffRole.CATALOGUE)
    assert catalogue.get(f"{d.admin}/problem/photos").status_code == 403


def test_evidence_is_limited_closed_with_the_case_and_never_edited(
    bazaar: Bazaar, reported: Delivered, db: DbSession
) -> None:
    d = reported
    settings_store.set_setting(db, "images.max_problem_photos_per_side", 1)
    db.commit()
    assert _upload(d.buyer, f"{d.mine}/problem/photos", phone_jpeg()).status_code == 201
    over = _upload(d.buyer, f"{d.mine}/problem/photos", phone_jpeg())
    assert error_code(over) == "too_many_photos"
    # The seller's allowance is separate.
    assert _upload(bazaar.a, f"{d.seller}/problem/photos", phone_jpeg()).status_code == 201

    decided = bazaar.staff.post(
        f"{d.admin}/resolve-problem",
        json={"decision": "no_action", "reason": "The photos show the right model."},
    )
    assert decided.status_code == 200, decided.text
    settings_store.set_setting(db, "images.max_problem_photos_per_side", 5)
    db.commit()
    late = _upload(d.buyer, f"{d.mine}/problem/photos", phone_jpeg())
    assert error_code(late) == "problem_already_resolved"

    # Evidence is append-only for the application's own database role.
    photo_id = db.scalars(select(ProblemPhoto.id)).first()
    with pytest.raises(DBAPIError):
        db.execute(text("update problem_photos set width = 1 where id = :id"), {"id": photo_id})
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("delete from problem_photos where id = :id"), {"id": photo_id})
    db.rollback()


def test_no_photo_without_a_reported_problem(bazaar: Bazaar) -> None:
    d = Delivered(bazaar)
    response = _upload(d.buyer, f"{d.mine}/problem/photos", phone_jpeg())
    assert response.status_code == 404
    assert error_code(response) == "problem_not_found"
