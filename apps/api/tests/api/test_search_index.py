"""Search documents stay true to the catalogue and the live offers (blueprint
F.7, F.8, P8; D-051). Every change that alters what a buyer could find queues
a rebuild in its own transaction; the worker applies it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from markx.core.ethiopic import normalize_text
from markx.notifications.models import Outbox
from markx.search import service as search
from markx.search.models import SearchDocument
from markx.worker.runner import run_once
from tests.bazaar import Bazaar
from tests.factories import add_to_cart, checkout

NO_JOBS = ()


@pytest.fixture
def bazaar(db: DbSession) -> Bazaar:
    return Bazaar(db)


def _doc(db: DbSession, bazaar: Bazaar) -> SearchDocument | None:
    run_once(datetime.now(UTC), jobs=NO_JOBS)
    db.rollback()
    return db.get(SearchDocument, uuid.UUID(bazaar.product["id"]), populate_existing=True)


def test_the_document_holds_what_a_buyer_can_find(bazaar: Bazaar, db: DbSession) -> None:
    doc = _doc(db, bazaar)
    assert doc is not None
    # Names in both languages, brand, model, model codes, category names.
    for word in ("ሳምሰንግ", "samsung", "galaxy", "a16", "sm a165f", "a16 128 bk", "ስልኮች", "phones"):
        assert normalize_text(word) in doc.search_text, word
    assert "smsng" in doc.skeleton_keys
    assert doc.category_path == "electronics/phones"
    # Alpha's two offers and Beta's one, all in stock; Beta's is cheapest.
    assert (doc.offer_count, doc.seller_count, doc.in_stock) == (3, 2, True)
    assert doc.min_price_santim == 1_790_000
    assert doc.best_seller_level == 2
    assert doc.freshest_price_at is not None
    assert doc.facets["condition"] == ["new"]
    assert doc.facets["storage"] == ["128gb", "256gb"]
    assert doc.facets["colour"] == ["black"]
    assert doc.popularity == 0
    # The full-text vector is built with the `simple` configuration.
    assert (
        db.scalar(
            select(func.count())
            .select_from(SearchDocument)
            .where(SearchDocument.tsv.op("@@")(func.to_tsquery("simple", "galax:*")))
        )
        == 1
    )


def test_stock_crossing_zero_moves_the_lowest_price(bazaar: Bazaar, db: DbSession) -> None:
    assert _doc(db, bazaar) is not None
    buyer, address_id = bazaar.buyer()
    add_to_cart(buyer, bazaar.b128["id"], 4)
    assert checkout(buyer, address_id, {"beta": "shop_collection"}).status_code == 201
    # Beta still has one unit: nothing for search to change, nothing queued.
    db.rollback()
    assert db.scalar(
        select(func.count()).select_from(Outbox).where(
            Outbox.topic == search.TOPIC_REBUILD, Outbox.status == "pending"
        )
    ) == 0  # fmt: skip

    last, address_id = bazaar.buyer()
    add_to_cart(last, bazaar.b128["id"], 1)
    order = checkout(last, address_id, {"beta": "shop_collection"}).json()
    doc = _doc(db, bazaar)
    assert doc is not None
    assert doc.min_price_santim == 1_850_000  # Beta is out of stock; Alpha is next
    assert doc.facets["condition"] == ["new"]

    part = order["seller_orders"][0]["id"]
    declined = bazaar.b.post(
        f"/seller/{bazaar.b_id}/orders/{part}/decline", json={"reason": "Counted wrong"}
    )
    assert declined.status_code == 200, declined.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert doc.min_price_santim == 1_790_000  # the unit is back on sale


def test_offer_and_seller_changes_reach_the_document(bazaar: Bazaar, db: DbSession) -> None:
    assert _doc(db, bazaar) is not None
    cheaper = bazaar.a.patch(
        f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}", json={"price_santim": 1_700_000}
    )
    assert cheaper.status_code == 200, cheaper.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert doc.min_price_santim == 1_700_000

    paused = bazaar.a.post(f"/seller/{bazaar.a_id}/offers/{bazaar.a128['id']}/pause")
    assert paused.status_code == 200, paused.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert (doc.offer_count, doc.min_price_santim) == (2, 1_790_000)

    suspended = bazaar.staff.post(
        f"/admin/sellers/{bazaar.b_id}/suspend", json={"reason": "Fake stock reported"}
    )
    assert suspended.status_code == 200, suspended.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert (doc.offer_count, doc.seller_count, doc.min_price_santim) == (1, 1, 2_100_000)


def test_the_hourly_job_marks_stale_offers_and_the_document_follows(
    bazaar: Bazaar, db: DbSession
) -> None:
    """The stale-offer job changes offers with one bulk statement, which the
    flush listener cannot see; it queues the rebuild itself."""
    assert _doc(db, bazaar) is not None
    later = datetime.now(UTC) + timedelta(days=15)
    jobs = {o.name: o.result for o in run_once(later).jobs}
    assert jobs["offers.mark_stale"] == 3
    run_once(later, jobs=NO_JOBS)
    db.rollback()
    doc = db.get(SearchDocument, uuid.UUID(bazaar.product["id"]), populate_existing=True)
    assert doc is not None
    assert (doc.offer_count, doc.in_stock, doc.min_price_santim) == (0, False, None)
    # Confirming the prices in bulk brings them back.
    confirmed = bazaar.a.post(f"/seller/{bazaar.a_id}/offers/check-in", json={})
    assert confirmed.status_code == 200, confirmed.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert (doc.offer_count, doc.min_price_santim) == (2, 1_850_000)


def test_catalogue_changes_reach_the_document(bazaar: Bazaar, db: DbSession) -> None:
    product_id = bazaar.product["id"]
    assert _doc(db, bazaar) is not None
    renamed = bazaar.staff.put(
        f"/admin/catalog/products/{product_id}/text",
        json={"name_am": "ሳምሰንግ ጋላክሲ A16 አዲስ", "name_en": "Samsung Galaxy A16 Prime"},
    )
    assert renamed.status_code == 200, renamed.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert "prime" in doc.search_text

    alias = bazaar.staff.post(
        f"/admin/catalog/products/{product_id}/aliases", json={"alias": "ኤ16"}
    )
    assert alias.status_code == 201, alias.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert "ኤ16" in doc.search_text
    removed = bazaar.staff.delete(
        f"/admin/catalog/products/{product_id}/aliases/{alias.json()['id']}"
    )
    assert removed.status_code == 200, removed.text
    doc = _doc(db, bazaar)
    assert doc is not None
    assert "ኤ16" not in doc.search_text

    archived = bazaar.staff.post(f"/admin/catalog/products/{product_id}/archive", json={})
    assert archived.status_code == 200, archived.text
    assert _doc(db, bazaar) is None  # an archived product cannot be found


def test_the_hourly_rebuild_repairs_a_missing_or_wrong_document(
    bazaar: Bazaar, db: DbSession
) -> None:
    assert _doc(db, bazaar) is not None
    db.execute(delete(SearchDocument))
    db.commit()
    assert _doc(db, bazaar) is None
    jobs = {o.name: o.result for o in run_once(datetime.now(UTC)).jobs}
    assert jobs["search.rebuild_all"] == 1
    db.rollback()
    doc = db.get(SearchDocument, uuid.UUID(bazaar.product["id"]))
    assert doc is not None
    assert doc.min_price_santim == 1_790_000
    # Safe to run twice.
    with db.begin_nested():
        assert search.rebuild_all(db) == 1
    db.commit()
    assert db.scalar(select(func.count()).select_from(SearchDocument)) == 1


def test_a_rebuild_that_read_older_offers_never_writes_last(
    bazaar: Bazaar, db: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-057. Rebuild A reads the offers, then stalls before writing. A price
    change commits and rebuild B runs for it. Without a per-product lock, B
    writes the new price, A then writes the old one over it, and search shows
    the wrong "from" price until the hourly rebuild. With the lock, B waits
    for A and writes last."""
    import threading

    from sqlalchemy import update

    from markx.core.db import get_session_factory
    from markx.offers.models import Offer

    product_id = uuid.UUID(bazaar.product["id"])
    assert _doc(db, bazaar) is not None  # the document exists, at 17,900 birr
    a_has_read = threading.Event()
    let_a_write = threading.Event()
    real_insert = search.insert

    def stalling_insert(*args: object, **kwargs: object) -> object:
        if threading.current_thread().name == "rebuild-a":
            a_has_read.set()
            assert let_a_write.wait(timeout=10)
        return real_insert(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(search, "insert", stalling_insert)

    def rebuild() -> None:
        session = get_session_factory()()
        try:
            search.rebuild_document(session, product_id)
            session.commit()
        finally:
            session.close()

    a = threading.Thread(target=rebuild, name="rebuild-a")
    a.start()
    assert a_has_read.wait(timeout=10)
    change = get_session_factory()()
    try:
        change.execute(
            update(Offer)
            .where(Offer.id == uuid.UUID(bazaar.b128["id"]))
            .values(price_santim=1_500_000)
        )
        change.commit()
    finally:
        change.close()
    b = threading.Thread(target=rebuild, name="rebuild-b")
    b.start()
    b.join(timeout=1)  # with the lock, B is waiting for A
    let_a_write.set()
    a.join(timeout=10)
    b.join(timeout=10)
    assert not a.is_alive()
    assert not b.is_alive()
    db.rollback()
    doc = db.get(SearchDocument, product_id, populate_existing=True)
    assert doc is not None
    assert doc.min_price_santim == 1_500_000
