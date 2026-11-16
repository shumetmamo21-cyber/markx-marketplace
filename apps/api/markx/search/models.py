from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.core.db import Base, CreatedAt, UUIDPrimaryKey, in_check


class SearchDocument(Base):
    """One search document per product (blueprint F.7). Results are products,
    never duplicate listings.

    Everything here is derived from the catalogue and the live offers, and can
    be rebuilt at any time.
    """

    __tablename__ = "search_documents"
    __table_args__ = (
        CheckConstraint("offer_count >= 0", name="offer_count_non_negative"),
        Index("ix_search_documents_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_search_documents_trigram",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
        Index("ix_search_documents_skeleton_keys", "skeleton_keys", postgresql_using="gin"),
        Index("ix_search_documents_facets", "facets", postgresql_using="gin"),
        Index("ix_search_documents_category_path", "category_path", postgresql_ops={"category_path": "text_pattern_ops"}),
        Index("ix_search_documents_brand_id", "brand_id"),
        Index("ix_search_documents_min_price", "min_price_santim"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    # Normalised names, brand, model and aliases in every language.
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=False)
    skeleton_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category_path: Mapped[str] = mapped_column(Text, nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Filter values: {"condition": ["new"], "storage": ["128gb", "256gb"]}.
    facets: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    min_price_santim: Mapped[int | None] = mapped_column(BigInteger)
    offer_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    seller_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    best_seller_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    freshest_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    popularity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SearchQuery(UUIDPrimaryKey, CreatedAt, Base):
    """Every query with its result count (blueprint D.8). Feeds the zero-result report."""

    __tablename__ = "search_queries"
    __table_args__ = (
        in_check("script", ("ethiopic", "latin")),
        Index("ix_search_queries_zero_results", "created_at", postgresql_where=text("result_count = 0")),
    )

    query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized: Mapped[str] = mapped_column(Text, nullable=False)
    script: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class SearchSynonym(UUIDPrimaryKey, CreatedAt, Base):
    """A staff-tuned synonym: searching the term also searches its expansion (AD-07)."""

    __tablename__ = "search_synonyms"
    __table_args__ = (
        CheckConstraint("term_normalized <> expansion_normalized", name="not_self_synonym"),
    )

    term: Mapped[str] = mapped_column(Text, nullable=False)
    term_normalized: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expansion: Mapped[str] = mapped_column(Text, nullable=False)
    expansion_normalized: Mapped[str] = mapped_column(Text, nullable=False)
