from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from markx.accounts.models import LANGUAGES, PHONE_PATTERN
from markx.core.db import Base, CreatedAt, Timestamps, UUIDPrimaryKey, in_check
from markx.sellers.models import SLUG_PATTERN

CODE_PATTERN = r"^[a-z][a-z0-9_]*$"


class ProductStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    MERGED = "merged"
    ARCHIVED = "archived"


class AttributeType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    OPTION = "option"


class ImageKind(StrEnum):
    CATALOGUE = "catalogue"
    SELLER_REAL_PHOTO = "seller_real_photo"


class Category(UUIDPrimaryKey, CreatedAt, Base):
    """The category tree. Categories and their fee rates are data, not code (B.7)."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),
        CheckConstraint("parent_id is null or parent_id <> id", name="not_own_parent"),
        CheckConstraint(
            "default_commission_bps between 0 and 10000", name="commission_bps_range"
        ),
        Index("ix_categories_parent_id", "parent_id"),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT")
    )
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Slugs from the root down, joined by "/": "electronics/phones".
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    default_commission_bps: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class CategoryTranslation(Base):
    __tablename__ = "category_translations"
    __table_args__ = (in_check("language", LANGUAGES),)

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Attribute(UUIDPrimaryKey, CreatedAt, Base):
    """A typed attribute such as storage or colour (blueprint D.6)."""

    __tablename__ = "attributes"
    __table_args__ = (
        CheckConstraint(f"code ~ '{CODE_PATTERN}'", name="code_format"),
        in_check("data_type", AttributeType),
    )

    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    data_type: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)


class AttributeTranslation(Base):
    __tablename__ = "attribute_translations"
    __table_args__ = (in_check("language", LANGUAGES),)

    attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attributes.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class AttributeOption(UUIDPrimaryKey, Base):
    __tablename__ = "attribute_options"
    __table_args__ = (
        CheckConstraint(f"code ~ '{CODE_PATTERN}' or code ~ '^[0-9][a-z0-9_]*$'", name="code_format"),
        UniqueConstraint("attribute_id", "code"),
    )

    attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attributes.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class AttributeOptionTranslation(Base):
    __tablename__ = "attribute_option_translations"
    __table_args__ = (in_check("language", LANGUAGES),)

    option_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attribute_options.id", ondelete="CASCADE"),
        primary_key=True,
    )
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)


class CategoryAttribute(Base):
    """Which attributes a category uses, and how (required, filterable, variant-defining)."""

    __tablename__ = "category_attributes"
    __table_args__ = (Index("ix_category_attributes_attribute_id", "attribute_id"),)

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attributes.id", ondelete="RESTRICT"), primary_key=True
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_filterable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_variant_defining: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Brand(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "brands"
    __table_args__ = (CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),)

    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class Product(UUIDPrimaryKey, Timestamps, Base):
    """The shared product page many sellers attach offers to (blueprint D.5, G.4).

    Products are archived or merged, never deleted. A merged product points at
    its survivor so old links keep working.
    """

    __tablename__ = "products"
    __table_args__ = (
        in_check("status", ProductStatus),
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),
        CheckConstraint(
            "(status = 'merged') = (merged_into_id is not null)", name="merged_has_survivor"
        ),
        CheckConstraint("merged_into_id is null or merged_into_id <> id", name="not_merged_into_self"),
        Index("ix_products_category_id", "category_id"),
        Index("ix_products_brand_id", "brand_id"),
        Index("ix_products_status", "status"),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="RESTRICT")
    )
    model: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # Empty means the shared catalogue, owned by MarkX. Seller-owned products
    # exist in the design for unique goods and are switched on later.
    owner_seller_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT")
    )
    proposed_by_seller_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT")
    )
    # Values of the category's non-variant attributes: {"screen_inches": 6.7}.
    specs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    review_note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )


class ProductTranslation(Base):
    __tablename__ = "product_translations"
    __table_args__ = (
        in_check("language", LANGUAGES),
        CheckConstraint("length(btrim(name)) > 0", name="name_present"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")


class ProductVariant(UUIDPrimaryKey, CreatedAt, Base):
    """A specific version, such as 128 GB in black. Offers attach here (D.6)."""

    __tablename__ = "product_variants"
    __table_args__ = (
        # A variant is unique per product and attribute set. attribute_key is the
        # canonical text of attribute_values, built by the service.
        UniqueConstraint("product_id", "attribute_key"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # Option codes of the variant-defining attributes: {"storage": "128gb"}.
    attribute_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    attribute_key: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    model_code: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class ProductImage(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        in_check("kind", ImageKind),
        # A "real photo" always names the seller who took it.
        CheckConstraint(
            "(kind = 'seller_real_photo') = (seller_id is not null)", name="real_photo_has_seller"
        ),
        CheckConstraint("width > 0 and height > 0", name="dimensions_positive"),
        Index("ix_product_images_product_position", "product_id", "position"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="catalogue")
    # Storage key without size suffix; the pipeline writes two fixed sizes.
    file_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class ProductAlias(UUIDPrimaryKey, CreatedAt, Base):
    """Search synonyms and local nicknames for one product (blueprint D.5)."""

    __tablename__ = "product_aliases"
    __table_args__ = (
        in_check("script", ("ethiopic", "latin")),
        UniqueConstraint("product_id", "normalized"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    normalized: Mapped[str] = mapped_column(Text, nullable=False)
    script: Mapped[str] = mapped_column(Text, nullable=False)


class RestrictedTerm(UUIDPrimaryKey, CreatedAt, Base):
    """The restricted-goods filter (requirement AD-03)."""

    __tablename__ = "restricted_terms"

    term: Mapped[str] = mapped_column(Text, nullable=False)
    normalized: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")


class ProductRequest(UUIDPrimaryKey, CreatedAt, Base):
    """"Request this product", offered when a search finds nothing (blueprint D.5)."""

    __tablename__ = "product_requests"
    __table_args__ = (
        in_check("status", ("open", "added", "dismissed")),
        CheckConstraint(
            f"contact_phone is null or contact_phone ~ '{PHONE_PATTERN}'",
            name="contact_phone_format",
        ),
        CheckConstraint("length(btrim(query)) > 0", name="query_present"),
    )

    query: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
