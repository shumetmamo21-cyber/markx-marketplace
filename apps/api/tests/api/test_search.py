"""Search (blueprint D.8, F.7, C-02, C-03, AD-07, P8; D-052).

One box for Amharic script, Latin-letter Amharic and English, tolerant of
typos; results are products, never listings; filters and sorting; every
query logged; the zero-result report and the synonym tool for staff; the
product-request form.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.catalog.models import ProductRequest
from markx.search.models import SearchQuery
from markx.worker.runner import run_once
from tests.bazaar import Bazaar
from tests.conftest import ApiClient, error_code
from tests.factories import make_offer, make_product, staff_client


class Shelf:
    """The bazaar's Samsung Galaxy A16 (Alpha and Beta, from 17,900 birr) and
    a Tecno Spark 20 (Alpha only, 12,000 birr), plus a draft Nokia."""

    def __init__(self, db: DbSession) -> None:
        self.bazaar = Bazaar(db)
        staff = self.bazaar.staff
        tecno_brand = staff.post("/admin/catalog/brands", json={"name": "Tecno"})
        assert tecno_brand.status_code == 201, tecno_brand.text
        self.tecno = make_product(
            staff, self.bazaar.catalog, brand_id=tecno_brand.json()["id"], model="KJ5",
            name_am="ቴክኖ ስፓርክ 20", name_en="Tecno Spark 20",
            variants=[{"attribute_values": {"storage": "128gb", "colour": "blue"}}],
        )  # fmt: skip
        self.tecno_offer = make_offer(
            self.bazaar.a, self.bazaar.a_id, self.tecno["variants"][0]["id"],
            price_santim=1_200_000,
        )  # fmt: skip
        make_product(
            staff, self.bazaar.catalog, model="3310", name_am="ኖኪያ 3310", name_en="Nokia 3310",
            status="draft", brand_id=None,
        )  # fmt: skip
        self.samsung = self.bazaar.product
        self.visitor = ApiClient()
        self.refresh()

    def refresh(self) -> None:
        run_once(datetime.now(UTC), jobs=())

    def find(self, q: str, **params: Any) -> dict[str, Any]:
        response = self.visitor.get("/search", params={"q": q, **params})
        assert response.status_code == 200, response.text
        return dict(response.json())

    def slugs(self, q: str, **params: Any) -> list[str]:
        return [card["slug"] for card in self.find(q, **params)["results"]]


@pytest.fixture
def shelf(db: DbSession) -> Shelf:
    return Shelf(db)


@pytest.mark.parametrize(
    "query",
    [
        "samsung", "Samsung Galaxy", "SAMSUNG galaxy a16", "gala", "a16", "SM-A165F",
        "ሳምሰንግ", "ጋላክሲ", "ሳምሱንግ",  # Amharic script, and a second spelling of the vowel
        "samsang", "galaksi", "smsng",  # Latin-letter Amharic and vowel-free typing
        "samsunk",  # a typo the sound rule misses: trigrams catch it
    ],
)  # fmt: skip
def test_one_box_finds_the_product_however_it_is_typed(shelf: Shelf, query: str) -> None:
    assert shelf.slugs(query)[:1] == [shelf.samsung["slug"]]


@pytest.mark.parametrize("query", ["tecno", "Tecno Spark", "ቴክኖ", "tekno", "spark 20", "kj5"])
def test_the_other_product_by_its_own_words(shelf: Shelf, query: str) -> None:
    assert shelf.slugs(query)[:1] == [shelf.tecno["slug"]]


def test_results_are_products_with_the_card_facts(shelf: Shelf) -> None:
    found = shelf.find("samsung galaxy", lang="en")
    assert found["total"] == 1
    (card,) = found["results"]
    assert card == {
        "product_id": shelf.samsung["id"],
        "slug": shelf.samsung["slug"],
        "name": "Samsung Galaxy A16",
        "brand": "Samsung",
        "category_path": "electronics/phones",
        "min_price_santim": 1_790_000,
        "offer_count": 3,
        "seller_count": 2,
        "best_seller_level": 2,
        "in_stock": True,
        "price_is_fresh": True,
    }
    assert shelf.find("samsung galaxy", lang="am")["results"][0]["name"] == "ሳምሰንግ ጋላክሲ A16"
    # A draft product is never found, nor anything that is not there at all.
    assert shelf.find("nokia")["total"] == 0
    assert shelf.find("laptop")["total"] == 0


def test_filters(shelf: Shelf) -> None:
    both = {shelf.samsung["slug"], shelf.tecno["slug"]}
    assert set(shelf.slugs("", category="electronics")) == both  # a parent covers its children
    assert set(shelf.slugs("", category="phones")) == both
    assert shelf.slugs("", brand="samsung") == [shelf.samsung["slug"]]
    assert shelf.slugs("", max_price=1_500_000) == [shelf.tecno["slug"]]
    assert shelf.slugs("", min_price=1_500_000) == [shelf.samsung["slug"]]
    assert shelf.slugs("", condition="used") == []
    assert set(shelf.slugs("", condition="new")) == both
    assert set(shelf.slugs("", min_level=2)) == both
    assert shelf.slugs("", min_level=3) == []
    for params in ({"category": "laptops"}, {"brand": "apple"}):
        response = shelf.visitor.get("/search", params={"q": "", **params})
        assert response.status_code == 404
    assert shelf.visitor.get("/search", params={"limit": 51}).status_code == 422

    # The Tecno sells out: it drops out of "in stock only" and sinks below
    # the Samsung, but it is still found.
    emptied = shelf.bazaar.a.put(
        f"/seller/{shelf.bazaar.a_id}/offers/{shelf.tecno_offer['id']}/stock", json={"on_hand": 0}
    )
    assert emptied.status_code == 200, emptied.text
    shelf.refresh()
    assert set(shelf.slugs("", in_stock="true")) == {shelf.samsung["slug"]}
    assert shelf.slugs("", category="phones") == [shelf.samsung["slug"], shelf.tecno["slug"]]
    card = shelf.find("tecno")["results"][0]
    assert (card["in_stock"], card["min_price_santim"], card["offer_count"]) == (False, None, 1)


def test_ranking_and_sorting(shelf: Shelf) -> None:
    samsung, tecno = shelf.samsung["slug"], shelf.tecno["slug"]
    # Both match "phones" (their category) equally well: the cheaper comes first.
    assert shelf.slugs("phones") == [tecno, samsung]
    assert shelf.slugs("", category="phones", sort="price") == [tecno, samsung]
    # A whole-word match outranks a fuzzy one, whatever the price.
    assert shelf.slugs("galaxy")[:1] == [samsung]
    # Freshness: the most recently confirmed price first.
    confirmed = shelf.bazaar.b.post(f"/seller/{shelf.bazaar.b_id}/offers/check-in", json={})
    assert confirmed.status_code == 200, confirmed.text
    shelf.refresh()
    assert shelf.slugs("", category="phones", sort="freshness") == [samsung, tecno]


def test_every_query_is_logged_and_staff_see_what_was_not_found(
    shelf: Shelf, db: DbSession
) -> None:
    shelf.find("Samsung")
    shelf.find("ሳምሰንግ")
    shelf.find("samsung", offset=20)  # a later page is the same search: not logged again
    shelf.visitor.get("/search/suggest", params={"q": "sams"})  # typing is not searching
    for _ in range(2):
        shelf.find("Laptop  Pro")
    shelf.find("laptop pro")
    shelf.find("router")
    db.rollback()
    logged = [
        (row.query, row.normalized, row.script, row.result_count)
        for row in db.scalars(select(SearchQuery).order_by(SearchQuery.created_at, SearchQuery.id))
    ]
    assert logged == [
        ("Samsung", "samsung", "latin", 1),
        ("ሳምሰንግ", "ሳምሰንግ", "ethiopic", 1),
        ("Laptop  Pro", "laptop pro", "latin", 0),
        ("Laptop  Pro", "laptop pro", "latin", 0),
        ("laptop pro", "laptop pro", "latin", 0),
        ("router", "router", "latin", 0),
    ]

    tuner = staff_client(db, "0911000300", StaffRole.CATALOGUE)
    report = tuner.get("/admin/search/zero-results")
    assert report.status_code == 200, report.text
    assert [(r["normalized"], r["searches"]) for r in report.json()] == [
        ("laptop pro", 3),
        ("router", 1),
    ]
    assert report.json()[0]["example"] == "Laptop  Pro"
    operations = staff_client(db, "0911000301", StaffRole.OPERATIONS)
    assert operations.get("/admin/search/zero-results").status_code == 403
    assert shelf.visitor.get("/admin/search/zero-results").status_code == 401


def test_did_you_mean_and_suggestions(shelf: Shelf) -> None:
    found = shelf.find("galaksi pro max ultra")
    assert found["total"] == 0
    assert [card["slug"] for card in found["did_you_mean"]][:1] == [shelf.samsung["slug"]]
    suggestions = shelf.visitor.get("/search/suggest", params={"q": "tec", "lang": "en"})
    assert suggestions.status_code == 200, suggestions.text
    assert suggestions.json() == [{"slug": shelf.tecno["slug"], "name": "Tecno Spark 20"}]
    assert shelf.visitor.get("/search/suggest", params={"q": "  "}).json() == []


def test_staff_synonyms_widen_a_search(shelf: Shelf, db: DbSession) -> None:
    assert shelf.find("ሞባይል")["total"] == 0  # "mobile", in Amharic
    tuner = staff_client(db, "0911000300", StaffRole.CATALOGUE)
    added = tuner.post("/admin/search/synonyms", json={"term": "ሞባይል", "expansion": "Phones"})
    assert added.status_code == 201, added.text
    assert (added.json()["term_normalized"], added.json()["expansion_normalized"]) == (
        "ሞባይል",
        "phones",
    )
    assert set(shelf.slugs("ሞባይል")) == {shelf.samsung["slug"], shelf.tecno["slug"]}
    # A synonym for one word of a longer query.
    assert shelf.slugs("ሞባይል samsung") == [shelf.samsung["slug"]]

    again = tuner.post("/admin/search/synonyms", json={"term": "ሞባይል", "expansion": "mobile"})
    assert error_code(again) == "synonym_exists"
    same = tuner.post("/admin/search/synonyms", json={"term": "Phones", "expansion": "phones"})
    assert error_code(same) == "synonym_same"
    assert [s["term"] for s in tuner.get("/admin/search/synonyms").json()] == ["ሞባይል"]
    operations = staff_client(db, "0911000301", StaffRole.OPERATIONS)
    assert operations.post(
        "/admin/search/synonyms", json={"term": "x1", "expansion": "y1"}
    ).status_code == 403  # fmt: skip

    removed = tuner.delete(f"/admin/search/synonyms/{added.json()['id']}")
    assert removed.status_code == 200, removed.text
    assert shelf.find("ሞባይል")["total"] == 0
    assert tuner.delete(f"/admin/search/synonyms/{uuid.uuid4()}").status_code == 404
    db.rollback()
    actions = list(
        db.scalars(
            select(AuditLog.action)
            .where(AuditLog.action.like("search.%"))
            .order_by(AuditLog.occurred_at, AuditLog.id)
        )
    )
    assert actions == ["search.add_synonym", "search.remove_synonym"]


def test_a_visitor_can_ask_for_a_product_nobody_sells(shelf: Shelf, db: DbSession) -> None:
    asked = shelf.visitor.post(
        "/product-requests",
        json={"query": "iPhone 15", "note": "128 GB", "contact_phone": "0911223344"},
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["status"] == "open"
    db.rollback()
    request = db.get(ProductRequest, uuid.UUID(asked.json()["id"]))
    assert request is not None
    assert (request.query, request.note, request.contact_phone, request.user_id) == (
        "iPhone 15",
        "128 GB",
        "+251911223344",
        None,
    )
    bad = shelf.visitor.post("/product-requests", json={"query": "x", "contact_phone": "12345678"})
    assert error_code(bad) in ("phone_invalid", "validation_failed")
    assert shelf.visitor.post("/product-requests", json={"query": " "}).status_code == 422
    # Ten an hour from one address.
    for _ in range(9):
        assert shelf.visitor.post("/product-requests", json={"query": "Pixel"}).status_code == 201
    assert shelf.visitor.post("/product-requests", json={"query": "Pixel"}).status_code == 429
    db.rollback()
    assert db.scalar(select(func.count()).select_from(ProductRequest)) == 10


def test_a_withdrawn_product_disappears_before_the_worker_runs(shelf: Shelf) -> None:
    """Staff archive a product (a restricted item, say): it must not be found
    in the minutes before the worker rebuilds its document. Found in the
    sixth session's review: search read the document alone."""
    assert shelf.slugs("tecno") == [shelf.tecno["slug"]]
    archived = shelf.bazaar.staff.post(
        f"/admin/catalog/products/{shelf.tecno['id']}/archive", json={"note": "Withdrawn"}
    )
    assert archived.status_code == 200, archived.text
    # No worker pass yet: the stale document is still in the table.
    assert shelf.find("tecno")["total"] == 0
    assert shelf.slugs("", category="phones") == [shelf.samsung["slug"]]
    assert shelf.visitor.get("/search/suggest", params={"q": "tec"}).json() == []
    assert shelf.find("tecno spark")["did_you_mean"] == []


def test_a_typo_match_is_answered_by_the_trigram_index(shelf: Shelf, db: DbSession) -> None:
    """The typo tier ("letters") must be indexable: written as
    `word_similarity(...) >= x` it scanned every document on every search
    (D-057; 322 ms against 41 ms on 50,000 synthetic documents). With
    sequential scans priced out, the plan must use the trigram index."""
    from sqlalchemy import text

    from markx.search import selectors
    from markx.search.models import SearchDocument

    selectors._use_letter_threshold(db)
    db.execute(text("set local enable_seqscan = off"))
    _, _, by_letters = selectors._match("samsunk")
    statement = select(SearchDocument.product_id).where(by_letters)
    compiled = statement.compile(db.get_bind())
    plan = "\n".join(
        row[0] for row in db.connection().exec_driver_sql(f"explain {compiled}", compiled.params)
    )
    assert "ix_search_documents_trigram" in plan, plan
    # And the operator keeps the threshold: the typo is found, a stranger is not.
    assert shelf.slugs("samsunk") == [shelf.samsung["slug"]]
    assert db.scalars(statement).all() == [uuid.UUID(shelf.samsung["id"])]
    _, _, far = selectors._match("zzqxw")
    assert db.scalars(select(SearchDocument.product_id).where(far)).all() == []
