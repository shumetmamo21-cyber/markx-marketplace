"""Finding products (blueprint D.8, F.7, C-02, C-03; D-052).

One box takes Amharic script, Amharic in Latin letters and English. The
query is normalised exactly as documents are, expanded by staff synonyms,
then matched three ways, strongest first:

1. **words**: every word of the query is a prefix of a word in the document
   (the `simple` full-text vector);
2. **sound**: the query's consonant skeletons are all in the document, so
   "samsang", "ሳምሱንግ" and "smsng" meet "Samsung";
3. **letters**: every word of the query is close, by trigrams, to some
   stretch of the document, for typos the first two miss.

Ranking: the match tier first, then in stock, a fresh price, the best
seller's level, the lowest price and popularity (F.7 step 6). Results are
products, never listings. Every first-page query is logged with its count.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, and_, case, false, func, or_, select
from sqlalchemy.orm import Session

from markx.catalog.models import Brand, Category, Product, ProductTranslation
from markx.core import settings_store
from markx.core.errors import NotFound
from markx.core.ethiopic import detect_script, normalize_text, skeleton_key
from markx.search.models import SearchDocument, SearchQuery, SearchSynonym

Sort = Literal["relevance", "price", "freshness"]

MAX_QUERY_LENGTH = 100
MAX_WORDS = 8
# word_similarity() at or above this counts as a typo-level match. Chosen on
# the test catalogue; the golden set of real queries (P8) will tune it.
LETTER_MATCH = 0.45


def _sink_before(db: Session) -> datetime:
    """A price confirmed before this has sunk (the product page's rule, D-029)."""
    return datetime.now(UTC) - timedelta(days=settings_store.get_int(db, "offers.sink_after_days"))


def _variants(db: Session, normalized: str) -> list[str]:
    """The query, and the query with each staff synonym applied (AD-07)."""
    words = normalized.split(" ")[:MAX_WORDS]
    base = " ".join(words)
    variants = [base]
    for term, expansion in db.execute(
        select(SearchSynonym.term_normalized, SearchSynonym.expansion_normalized)
        .where(SearchSynonym.term_normalized.in_([*words, base]))
        .order_by(SearchSynonym.term_normalized)
    ).all():
        if term == base:
            variants.append(expansion)
        else:
            variants.append(" ".join(expansion if word == term else word for word in words))
    return list(dict.fromkeys(variants))


def _prefix_query(words: list[str]) -> Any:
    # Normalised words hold letters and digits only: nothing to escape.
    return func.to_tsquery("simple", " & ".join(f"'{word}':*" for word in words))


def _closeness(word: str) -> Any:
    """How close one query word is to the closest stretch of the document."""
    return func.word_similarity(word, SearchDocument.search_text)


def _match(variant: str) -> tuple[Any, Any, Any]:
    """The three match conditions for one wording of the query."""
    words = variant.split(" ")
    by_words = SearchDocument.tsv.op("@@")(_prefix_query(words))
    keys = [key for key in (skeleton_key(word) for word in words) if key]
    rest = [word for word in words if not skeleton_key(word)]
    if keys:
        by_sound = SearchDocument.skeleton_keys.contains(keys)
        if rest:  # model numbers and the like still have to be there
            by_sound = and_(by_sound, SearchDocument.tsv.op("@@")(_prefix_query(rest)))
    else:
        by_sound = false()
    # Every word must be close to some word of the document: one word of two
    # matching is not a match.
    by_letters = and_(*(_closeness(word) >= LETTER_MATCH for word in words))
    return by_words, by_sound, by_letters


def _category_path(db: Session, slug: str | None) -> str | None:
    if slug is None:
        return None
    path = db.scalar(select(Category.path).where(Category.slug == slug, Category.is_active))
    if path is None:
        raise NotFound("category_not_found", "That category was not found.")
    return path


def _brand_id(db: Session, slug: str | None) -> uuid.UUID | None:
    if slug is None:
        return None
    found = db.scalar(select(Brand.id).where(Brand.slug == slug))
    if found is None:
        raise NotFound("brand_not_found", "That brand was not found.")
    return found


def _cards(db: Session, docs: list[SearchDocument], language: str) -> list[dict[str, Any]]:
    """The product card used everywhere (D.9): name, "from" price, sellers,
    best seller level, freshness."""
    if not docs:
        return []
    ids = [doc.product_id for doc in docs]
    names: dict[uuid.UUID, dict[str, str]] = {}
    for product_id, lang, name in db.execute(
        select(
            ProductTranslation.product_id, ProductTranslation.language, ProductTranslation.name
        ).where(ProductTranslation.product_id.in_(ids))
    ).all():
        names.setdefault(product_id, {})[lang] = name
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))}
    brand_ids = {doc.brand_id for doc in docs if doc.brand_id}
    brands = dict(
        db.execute(select(Brand.id, Brand.name).where(Brand.id.in_(brand_ids))).all()
    ) if brand_ids else {}  # fmt: skip
    other = "en" if language == "am" else "am"
    sink_before = _sink_before(db)
    return [
        {
            "product_id": doc.product_id,
            "slug": products[doc.product_id].slug,
            "name": names.get(doc.product_id, {}).get(language)
            or names.get(doc.product_id, {}).get(other, ""),
            "brand": brands.get(doc.brand_id) if doc.brand_id else None,
            "category_path": doc.category_path,
            "min_price_santim": doc.min_price_santim,
            "offer_count": doc.offer_count,
            "seller_count": doc.seller_count,
            "best_seller_level": doc.best_seller_level,
            "in_stock": doc.in_stock,
            "price_is_fresh": doc.freshest_price_at is not None
            and doc.freshest_price_at >= sink_before,
        }
        for doc in docs
    ]


def search(
    db: Session,
    query: str,
    *,
    language: str,
    category: str | None = None,
    brand: str | None = None,
    condition: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    min_level: int | None = None,
    in_stock_only: bool = False,
    sort: Sort = "relevance",
    limit: int = 20,
    offset: int = 0,
    user_id: uuid.UUID | None = None,
    log: bool = True,
) -> dict[str, Any]:
    raw = query.strip()[:MAX_QUERY_LENGTH]
    normalized = " ".join(normalize_text(raw).split(" ")[:MAX_WORDS])

    statement: Select[Any] = select(SearchDocument)
    tier: Any = 0
    closeness: Any = 0
    if normalized:
        conditions = [_match(variant) for variant in _variants(db, normalized)]
        by_words = or_(*(c[0] for c in conditions))
        by_sound = or_(*(c[1] for c in conditions))
        by_letters = or_(*(c[2] for c in conditions))
        statement = statement.where(or_(by_words, by_sound, by_letters))
        tier = case((by_words, 3), (by_sound, 2), else_=1)
        closeness = sum(
            (_closeness(word) for word in normalized.split(" ")[1:]),
            _closeness(normalized.split(" ")[0]),
        )

    path = _category_path(db, category)
    if path is not None:
        statement = statement.where(
            or_(SearchDocument.category_path == path, SearchDocument.category_path.startswith(f"{path}/"))
        )  # fmt: skip
    brand_id = _brand_id(db, brand)
    if brand_id is not None:
        statement = statement.where(SearchDocument.brand_id == brand_id)
    if condition is not None:
        statement = statement.where(SearchDocument.facets.contains({"condition": [condition]}))
    if min_price is not None:
        statement = statement.where(SearchDocument.min_price_santim >= min_price)
    if max_price is not None:
        statement = statement.where(SearchDocument.min_price_santim <= max_price)
    if min_level is not None:
        statement = statement.where(SearchDocument.best_seller_level >= min_level)
    if in_stock_only:
        statement = statement.where(SearchDocument.in_stock)

    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)

    fresh = SearchDocument.freshest_price_at >= _sink_before(db)
    relevance = (
        tier.desc() if normalized else SearchDocument.popularity.desc(),
        SearchDocument.in_stock.desc(),
        fresh.desc().nulls_last(),
        SearchDocument.best_seller_level.desc(),
        SearchDocument.min_price_santim.asc().nulls_last(),
        SearchDocument.popularity.desc(),
        closeness.desc() if normalized else SearchDocument.product_id,
    )
    if sort == "price":
        order: tuple[Any, ...] = (
            SearchDocument.in_stock.desc(),
            SearchDocument.min_price_santim.asc().nulls_last(),
            *relevance,
        )
    elif sort == "freshness":
        order = (SearchDocument.freshest_price_at.desc().nulls_last(), *relevance)
    else:
        order = relevance
    docs = list(
        db.scalars(
            statement.order_by(*order, SearchDocument.product_id).limit(limit).offset(offset)
        )
    )

    did_you_mean: list[dict[str, Any]] = []
    if total == 0 and normalized:
        # Nothing has every word: offer what has some of them, closest first.
        words = normalized.split(" ")
        did_you_mean = _cards(
            db,
            list(
                db.scalars(
                    select(SearchDocument)
                    .where(or_(*(_closeness(word) >= LETTER_MATCH for word in words)))
                    .order_by(closeness.desc(), SearchDocument.product_id)
                    .limit(3)
                )
            ),
            language,
        )

    if log and raw and offset == 0:
        db.add(
            SearchQuery(
                query=raw,
                normalized=normalized,
                script=detect_script(raw),
                result_count=total,
                user_id=user_id,
            )
        )
        db.flush()
    return {
        "query": raw,
        "total": total,
        "results": _cards(db, docs, language),
        "did_you_mean": did_you_mean,
    }


def suggest(db: Session, query: str, *, language: str, limit: int = 8) -> list[dict[str, Any]]:
    """Names as the buyer types: the same matching, nothing logged."""
    if not normalize_text(query.strip()[:MAX_QUERY_LENGTH]):
        return []
    found = search(db, query, language=language, limit=limit, log=False)
    return [{"slug": card["slug"], "name": card["name"]} for card in found["results"]]


def zero_result_queries(db: Session, *, since: Any, limit: int) -> list[dict[str, Any]]:
    """What buyers searched for and did not find, most frequent first (AD-07)."""
    rows = db.execute(
        select(
            SearchQuery.normalized,
            func.count().label("searches"),
            func.max(SearchQuery.created_at).label("last_searched_at"),
            func.min(SearchQuery.query).label("example"),
        )
        .where(SearchQuery.result_count == 0, SearchQuery.created_at >= since)
        .group_by(SearchQuery.normalized)
        .order_by(func.count().desc(), SearchQuery.normalized)
        .limit(limit)
    ).all()
    return [dict(row._mapping) for row in rows]
