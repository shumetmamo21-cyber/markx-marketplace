"""The shared catalogue (blueprint D.5, D.6, G.2).

Staff own the product pages. One clean page per product is what makes offers
comparable and keeps search free of duplicates. Products are archived or
merged, never deleted.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from markx.audit.service import Actor, record_by
from markx.catalog.models import (
    Attribute,
    AttributeOption,
    AttributeOptionTranslation,
    AttributeTranslation,
    AttributeType,
    Brand,
    Category,
    CategoryAttribute,
    CategoryTranslation,
    Product,
    ProductAlias,
    ProductStatus,
    ProductTranslation,
    ProductVariant,
    RestrictedTerm,
)
from markx.core.errors import Conflict, NotFound, ValidationFailed
from markx.core.ethiopic import detect_script, normalize_text
from markx.core.slugs import slugify
from markx.offers.models import Offer
from markx.search import service as search

MAX_CATEGORY_DEPTH = 3
MAX_VARIANTS_PER_PRODUCT = 60


# ------------------------------------------------------------------ categories


def get_category(db: Session, category_id: uuid.UUID) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise NotFound("category_not_found", "That category was not found.")
    return category


def _set_category_names(db: Session, category_id: uuid.UUID, names: Mapping[str, str]) -> None:
    for language, name in names.items():
        db.execute(
            pg_insert(CategoryTranslation)
            .values(category_id=category_id, language=language, name=name)
            .on_conflict_do_update(
                index_elements=[CategoryTranslation.category_id, CategoryTranslation.language],
                set_={"name": name},
            )
        )


def create_category(
    db: Session,
    actor: Actor,
    *,
    slug: str,
    name_am: str,
    name_en: str,
    parent_id: uuid.UUID | None = None,
    position: int = 0,
    default_commission_bps: int = 0,
) -> Category:
    path = slug
    if parent_id is not None:
        parent = get_category(db, parent_id)
        if parent.path.count("/") + 2 > MAX_CATEGORY_DEPTH:
            raise ValidationFailed(
                "category_too_deep", f"Categories nest at most {MAX_CATEGORY_DEPTH} levels."
            )
        path = f"{parent.path}/{slug}"
    category = Category(
        parent_id=parent_id,
        slug=slug,
        path=path,
        position=position,
        default_commission_bps=default_commission_bps,
    )
    db.add(category)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("category_slug_taken", "A category with that link name exists.") from exc
    # Every customer-facing text exists in Amharic and English (D.23 rule 8).
    _set_category_names(db, category.id, {"am": name_am, "en": name_en})
    record_by(
        db, actor, "category.create", "category", category.id,
        after={"path": path, "name_en": name_en, "default_commission_bps": default_commission_bps},
    )  # fmt: skip
    return category


def update_category(
    db: Session,
    actor: Actor,
    category_id: uuid.UUID,
    *,
    name_am: str | None = None,
    name_en: str | None = None,
    position: int | None = None,
    is_active: bool | None = None,
) -> Category:
    category = get_category(db, category_id)
    before = {"position": category.position, "is_active": category.is_active}
    names = {k: v for k, v in (("am", name_am), ("en", name_en)) if v is not None}
    if names:
        _set_category_names(db, category.id, names)
    if position is not None:
        category.position = position
    if is_active is not None:
        category.is_active = is_active
    db.flush()
    record_by(
        db, actor, "category.update", "category", category.id, before=before,
        after={"position": category.position, "is_active": category.is_active, **names},
    )  # fmt: skip
    return category


def category_and_ancestor_ids(db: Session, category: Category) -> list[uuid.UUID]:
    """A category inherits the attributes of every category above it."""
    parts = category.path.split("/")
    paths = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return list(db.scalars(select(Category.id).where(Category.path.in_(paths))))


# ------------------------------------------------------------------ attributes


@dataclass(frozen=True, slots=True)
class OptionInput:
    code: str
    label_am: str
    label_en: str


def create_attribute(
    db: Session,
    actor: Actor,
    *,
    code: str,
    data_type: AttributeType,
    name_am: str,
    name_en: str,
    unit: str | None = None,
    options: Sequence[OptionInput] = (),
) -> Attribute:
    if data_type == AttributeType.OPTION and not options:
        raise ValidationFailed("options_required", "A list attribute needs at least one option.")
    if data_type != AttributeType.OPTION and options:
        raise ValidationFailed("options_not_allowed", "Only a list attribute has options.")
    attribute = Attribute(code=code, data_type=data_type.value, unit=unit)
    db.add(attribute)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("attribute_code_taken", "An attribute with that code exists.") from exc
    db.add_all(
        [
            AttributeTranslation(attribute_id=attribute.id, language="am", name=name_am),
            AttributeTranslation(attribute_id=attribute.id, language="en", name=name_en),
        ]
    )
    for position, option in enumerate(options):
        add_attribute_option(db, attribute, option, position=position)
    db.flush()
    record_by(
        db, actor, "attribute.create", "attribute", attribute.id,
        after={"code": code, "data_type": data_type.value, "options": [o.code for o in options]},
    )  # fmt: skip
    return attribute


def add_attribute_option(
    db: Session, attribute: Attribute, option: OptionInput, *, position: int = 0
) -> AttributeOption:
    if attribute.data_type != AttributeType.OPTION:
        raise ValidationFailed("options_not_allowed", "Only a list attribute has options.")
    row = AttributeOption(attribute_id=attribute.id, code=option.code, position=position)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("option_code_taken", "That option already exists.") from exc
    db.add_all(
        [
            AttributeOptionTranslation(option_id=row.id, language="am", label=option.label_am),
            AttributeOptionTranslation(option_id=row.id, language="en", label=option.label_en),
        ]
    )
    return row


def attach_attribute(
    db: Session,
    actor: Actor,
    category_id: uuid.UUID,
    attribute_id: uuid.UUID,
    *,
    is_required: bool = False,
    is_filterable: bool = False,
    is_variant_defining: bool = False,
    position: int = 0,
) -> CategoryAttribute:
    category = get_category(db, category_id)
    attribute = db.get(Attribute, attribute_id)
    if attribute is None:
        raise NotFound("attribute_not_found", "That attribute was not found.")
    # A variant is one choice from a fixed list, so only list attributes define variants.
    if is_variant_defining and attribute.data_type != AttributeType.OPTION:
        raise ValidationFailed(
            "variant_attribute_must_be_a_list", "Only a list attribute can define variants."
        )
    link = db.get(CategoryAttribute, (category.id, attribute.id))
    if link is None:
        link = CategoryAttribute(category_id=category.id, attribute_id=attribute.id)
        db.add(link)
    link.is_required = is_required
    link.is_filterable = is_filterable
    link.is_variant_defining = is_variant_defining
    link.position = position
    db.flush()
    record_by(
        db, actor, "category_attribute.set", "category", category.id,
        after={
            "attribute": attribute.code, "is_required": is_required,
            "is_filterable": is_filterable, "is_variant_defining": is_variant_defining,
        },
    )  # fmt: skip
    return link


@dataclass(frozen=True, slots=True)
class AttributeRule:
    attribute: Attribute
    is_required: bool
    is_filterable: bool
    is_variant_defining: bool
    position: int
    option_codes: frozenset[str]


def attribute_rules(db: Session, category: Category) -> dict[str, AttributeRule]:
    """The attribute rules a product in this category must satisfy, by code.

    Rules set on the category itself win over rules inherited from above.
    """
    ids = category_and_ancestor_ids(db, category)
    path_length = {
        cid: path.count("/")
        for cid, path in db.execute(select(Category.id, Category.path).where(Category.id.in_(ids)))
    }
    rows = db.execute(
        select(CategoryAttribute, Attribute)
        .join(Attribute, Attribute.id == CategoryAttribute.attribute_id)
        .where(CategoryAttribute.category_id.in_(ids))
    ).all()
    options: dict[uuid.UUID, set[str]] = {}
    attribute_ids = [attribute.id for _, attribute in rows]
    if attribute_ids:
        for attribute_id, code in db.execute(
            select(AttributeOption.attribute_id, AttributeOption.code).where(
                AttributeOption.attribute_id.in_(attribute_ids)
            )
        ):
            options.setdefault(attribute_id, set()).add(code)
    rules: dict[str, AttributeRule] = {}
    # Shallowest first, so a deeper category's rule overwrites an inherited one.
    for link, attribute in sorted(rows, key=lambda r: path_length[r[0].category_id]):
        rules[attribute.code] = AttributeRule(
            attribute=attribute,
            is_required=link.is_required,
            is_filterable=link.is_filterable,
            is_variant_defining=link.is_variant_defining,
            position=link.position,
            option_codes=frozenset(options.get(attribute.id, ())),
        )
    return rules


# ---------------------------------------------------------------------- brands


def create_brand(db: Session, actor: Actor, *, name: str, slug: str | None = None) -> Brand:
    brand = Brand(name=name, slug=slug or slugify(name))
    if not brand.slug:
        raise ValidationFailed("slug_required", "Give this brand a link name in Latin letters.")
    db.add(brand)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("brand_exists", "That brand already exists.") from exc
    record_by(
        db, actor, "brand.create", "brand", brand.id, after={"name": name, "slug": brand.slug}
    )
    return brand


# ------------------------------------------------------------ restricted goods


def add_restricted_term(
    db: Session, actor: Actor, *, term: str, reason: str = ""
) -> RestrictedTerm:
    normalized = normalize_text(term)
    if not normalized:
        raise ValidationFailed("term_empty", "Enter a word or phrase.")
    row = RestrictedTerm(term=term.strip(), normalized=normalized, reason=reason.strip())
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("term_exists", "That term is already on the list.") from exc
    record_by(db, actor, "restricted_term.add", "restricted_term", row.id, after={"term": row.term})
    return row


def remove_restricted_term(db: Session, actor: Actor, term_id: uuid.UUID) -> None:
    row = db.get(RestrictedTerm, term_id)
    if row is None:
        raise NotFound("term_not_found", "That term was not found.")
    record_by(
        db, actor, "restricted_term.remove", "restricted_term", row.id, before={"term": row.term}
    )
    db.delete(row)


def find_restricted_term(db: Session, *texts: str) -> RestrictedTerm | None:
    """The first restricted term that appears, as whole words, in any of the texts.

    Texts are normalised the same way search is, so ሠ/ሰ spellings and letter
    case cannot be used to slip past the list.
    """
    terms = list(db.scalars(select(RestrictedTerm)))
    if not terms:
        return None
    haystacks = [f" {normalize_text(text)} " for text in texts if text]
    for term in terms:
        needle = f" {term.normalized} "
        if any(needle in haystack for haystack in haystacks):
            return term
    return None


# -------------------------------------------------------------------- products


@dataclass(frozen=True, slots=True)
class VariantInput:
    attribute_values: Mapping[str, str]
    model_code: str | None = None


def attribute_key(values: Mapping[str, str]) -> str:
    """The canonical text of a variant's attribute set: "colour=black|storage=128gb".

    Sorted by attribute code, so the same set always gives the same key and the
    database's unique constraint can reject a duplicate variant.
    """
    return "|".join(f"{code}={values[code]}" for code in sorted(values))


def _validate_specs(rules: Mapping[str, AttributeRule], specs: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for code, value in specs.items():
        rule = rules.get(code)
        if rule is None:
            raise ValidationFailed(
                "attribute_not_in_category", f"This category has no attribute named {code}."
            )
        if rule.is_variant_defining:
            raise ValidationFailed(
                "attribute_belongs_to_variants",
                f"{code} is set on each variant, not on the product.",
            )
        kind = rule.attribute.data_type
        if kind == AttributeType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValidationFailed("attribute_value_invalid", f"{code} must be a number.")
        elif kind == AttributeType.OPTION:
            if not isinstance(value, str) or value not in rule.option_codes:
                raise ValidationFailed(
                    "attribute_value_invalid", f"{code} must be one of its options."
                )
        elif not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValidationFailed("attribute_value_invalid", f"{code} must be a short text.")
        clean[code] = value.strip() if isinstance(value, str) else value
    for code, rule in rules.items():
        if rule.is_required and not rule.is_variant_defining and code not in clean:
            raise ValidationFailed("attribute_required", f"{code} is required in this category.")
    return clean


def _validate_variants(
    rules: Mapping[str, AttributeRule], variants: Sequence[VariantInput]
) -> list[VariantInput]:
    if not variants:
        # A product with nothing to choose still has one variant for offers to attach to.
        variants = [VariantInput(attribute_values={})]
    if len(variants) > MAX_VARIANTS_PER_PRODUCT:
        raise ValidationFailed("too_many_variants", "That is too many variants for one product.")
    variant_codes = {code for code, rule in rules.items() if rule.is_variant_defining}
    required = {code for code in variant_codes if rules[code].is_required}
    key_sets = {frozenset(v.attribute_values) for v in variants}
    if len(key_sets) > 1:
        raise ValidationFailed(
            "variants_inconsistent", "Every variant of a product must set the same attributes."
        )
    seen: set[str] = set()
    for variant in variants:
        for code, value in variant.attribute_values.items():
            if code not in variant_codes:
                raise ValidationFailed(
                    "attribute_not_variant_defining",
                    f"{code} does not define variants in this category.",
                )
            if value not in rules[code].option_codes:
                raise ValidationFailed(
                    "attribute_value_invalid", f"{code} must be one of its options."
                )
        missing = required - set(variant.attribute_values)
        if missing:
            raise ValidationFailed(
                "attribute_required", f"{sorted(missing)[0]} is required on every variant."
            )
        key = attribute_key(variant.attribute_values)
        if key in seen:
            raise Conflict("variant_duplicate", "Two variants have the same attributes.")
        seen.add(key)
    return list(variants)


def _unique_product_slug(db: Session, wanted: str) -> str:
    base = slugify(wanted)
    if not base:
        raise ValidationFailed("slug_required", "Give this product a link name in Latin letters.")
    taken = set(db.scalars(select(Product.slug).where(Product.slug.like(f"{base}%"))))
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base[:74]}-{n}"
        if candidate not in taken:
            return candidate
    raise Conflict("slug_exhausted", "Choose a different link name.")


def _set_product_text(
    db: Session, product_id: uuid.UUID, language: str, name: str, description: str
) -> None:
    db.execute(
        pg_insert(ProductTranslation)
        .values(product_id=product_id, language=language, name=name, description=description)
        .on_conflict_do_update(
            index_elements=[ProductTranslation.product_id, ProductTranslation.language],
            set_={"name": name, "description": description},
        )
    )
    search.queue_rebuild(db, [product_id])  # a Core statement: the flush listener cannot see it


def get_product(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("product_not_found", "That product was not found.")
    return product


def create_product(
    db: Session,
    actor: Actor,
    *,
    category_id: uuid.UUID,
    name_am: str,
    name_en: str,
    description_am: str = "",
    description_en: str = "",
    brand_id: uuid.UUID | None = None,
    model: str | None = None,
    slug: str | None = None,
    specs: Mapping[str, Any] | None = None,
    variants: Sequence[VariantInput] = (),
    status: ProductStatus = ProductStatus.DRAFT,
    proposed_by_seller_id: uuid.UUID | None = None,
) -> Product:
    """Create a shared-catalogue product with its variants.

    Staff create products as drafts or approved. A seller's proposal arrives
    as pending_review and is shown to nobody until staff approve it.
    """
    if status not in (ProductStatus.DRAFT, ProductStatus.PENDING_REVIEW, ProductStatus.APPROVED):
        raise ValidationFailed(
            "status_invalid", "A new product is a draft, a proposal or approved."
        )
    category = get_category(db, category_id)
    if not category.is_active:
        raise ValidationFailed("category_inactive", "That category is not in use.")
    if brand_id is not None and db.get(Brand, brand_id) is None:
        raise NotFound("brand_not_found", "That brand was not found.")

    restricted = find_restricted_term(
        db, name_am, name_en, description_am, description_en, model or ""
    )
    if restricted is not None:
        raise ValidationFailed(
            "restricted_goods",
            "This item is on the restricted-goods list and cannot be listed.",
            details={"term": restricted.term},
        )

    rules = attribute_rules(db, category)
    clean_specs = _validate_specs(rules, specs or {})
    clean_variants = _validate_variants(rules, variants)

    product = Product(
        category_id=category.id,
        brand_id=brand_id,
        model=(model or "").strip() or None,
        slug=_unique_product_slug(db, slug or name_en),
        status=status.value,
        specs=clean_specs,
        proposed_by_seller_id=proposed_by_seller_id,
        created_by_user_id=actor.user_id,
    )
    db.add(product)
    db.flush()
    _set_product_text(db, product.id, "am", name_am, description_am)
    _set_product_text(db, product.id, "en", name_en, description_en)
    for position, variant in enumerate(clean_variants):
        db.add(
            ProductVariant(
                product_id=product.id,
                attribute_values=dict(variant.attribute_values),
                attribute_key=attribute_key(variant.attribute_values),
                model_code=(variant.model_code or "").strip() or None,
                position=position,
            )
        )
    db.flush()
    record_by(
        db, actor, "product.create", "product", product.id,
        after={"slug": product.slug, "status": product.status, "name_en": name_en,
               "variants": len(clean_variants)},
    )  # fmt: skip
    return product


def add_variant(
    db: Session, actor: Actor, product_id: uuid.UUID, variant: VariantInput
) -> ProductVariant:
    product = get_product(db, product_id)
    if product.status in (ProductStatus.MERGED, ProductStatus.ARCHIVED):
        raise Conflict("product_not_editable", "This product can no longer be changed.")
    rules = attribute_rules(db, get_category(db, product.category_id))
    existing = list(
        db.scalars(select(ProductVariant).where(ProductVariant.product_id == product.id))
    )
    # Validate the new variant together with the existing ones, so the
    # "same attributes on every variant" rule covers the whole product.
    _validate_variants(
        rules,
        [VariantInput(attribute_values=v.attribute_values) for v in existing] + [variant],
    )
    row = ProductVariant(
        product_id=product.id,
        attribute_values=dict(variant.attribute_values),
        attribute_key=attribute_key(variant.attribute_values),
        model_code=(variant.model_code or "").strip() or None,
        position=len(existing),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:  # the database is the referee (G.8 rule 2)
        db.rollback()
        raise Conflict("variant_duplicate", "This product already has that variant.") from exc
    record_by(
        db,
        actor,
        "product.add_variant",
        "product",
        product.id,
        after={"attribute_key": row.attribute_key},
    )
    return row


def update_product_text(
    db: Session,
    actor: Actor,
    product_id: uuid.UUID,
    *,
    name_am: str,
    name_en: str,
    description_am: str,
    description_en: str,
) -> Product:
    product = get_product(db, product_id)
    if product.status == ProductStatus.MERGED:
        raise Conflict("product_not_editable", "This product was merged into another.")
    restricted = find_restricted_term(db, name_am, name_en, description_am, description_en)
    if restricted is not None:
        raise ValidationFailed(
            "restricted_goods",
            "This item is on the restricted-goods list and cannot be listed.",
            details={"term": restricted.term},
        )
    _set_product_text(db, product.id, "am", name_am, description_am)
    _set_product_text(db, product.id, "en", name_en, description_en)
    product.updated_at = func.now()
    db.flush()
    record_by(db, actor, "product.update_text", "product", product.id, after={"name_en": name_en})
    return product


def _change_status(
    db: Session,
    actor: Actor,
    product: Product,
    new_status: ProductStatus,
    action: str,
    *,
    note: str | None = None,
) -> Product:
    before = {"status": product.status}
    product.status = new_status.value
    if note is not None:
        product.review_note = note.strip() or None
    db.flush()
    record_by(
        db, actor, action, "product", product.id, before=before,
        after={"status": new_status.value, "note": product.review_note},
    )  # fmt: skip
    return product


def approve_product(db: Session, actor: Actor, product_id: uuid.UUID) -> Product:
    product = get_product(db, product_id)
    if product.status not in (ProductStatus.DRAFT, ProductStatus.PENDING_REVIEW):
        raise Conflict("product_not_approvable", "Only a draft or a proposal can be approved.")
    return _change_status(db, actor, product, ProductStatus.APPROVED, "product.approve")


def archive_product(
    db: Session, actor: Actor, product_id: uuid.UUID, *, note: str | None = None
) -> Product:
    """Take a product out of the catalogue. Also how a proposal is rejected."""
    product = get_product(db, product_id)
    if product.status == ProductStatus.MERGED:
        raise Conflict("product_not_editable", "This product was merged into another.")
    if product.status == ProductStatus.ARCHIVED:
        return product
    return _change_status(db, actor, product, ProductStatus.ARCHIVED, "product.archive", note=note)


def merge_product(db: Session, actor: Actor, source_id: uuid.UUID, into_id: uuid.UUID) -> Product:
    """Merge a duplicate into the surviving product (blueprint D.5, AD-02).

    The duplicate keeps its row and its link name and points at the survivor,
    so old links forward instead of breaking.
    """
    if source_id == into_id:
        raise ValidationFailed("merge_into_self", "A product cannot be merged into itself.")
    # Lock both rows in a fixed order, so two opposite merges cannot deadlock.
    first, second = sorted((source_id, into_id))
    locked = {
        p.id: p
        for p in db.scalars(
            select(Product).where(Product.id.in_([first, second])).with_for_update()
        )
    }
    source, target = locked.get(source_id), locked.get(into_id)
    if source is None or target is None:
        raise NotFound("product_not_found", "That product was not found.")
    if source.status == ProductStatus.MERGED:
        raise Conflict("product_already_merged", "That product was already merged.")
    if target.status != ProductStatus.APPROVED:
        raise Conflict("merge_target_not_approved", "Merge into an approved product.")

    # Moving offers to the survivor means mapping each variant of the duplicate
    # onto a variant of the survivor, and two sellers' offers may then collide.
    # That mapping is not built, so a product that has offers cannot be merged.
    # PROVISIONAL (F-06, D-083), for when it is built: map each variant, move
    # the offers, and where one seller ends up with two offers for the same
    # variant and condition keep the one already on the survivor, remove (not
    # delete) the other, audit both prices and tell the seller.
    #   The engineer's guess at the founder's request; THE FOUNDER MUST CONFIRM
    #   OR CHANGE IT BEFORE MARKX GOES LIVE.
    has_offers = db.scalar(
        select(func.count())
        .select_from(Offer)
        .join(ProductVariant, ProductVariant.id == Offer.variant_id)
        .where(ProductVariant.product_id == source.id)
    )
    if has_offers:
        raise Conflict("product_has_offers", "This product has offers and cannot be merged yet.")

    # Keep what people searched for: the duplicate's names become aliases.
    names = list(
        db.scalars(
            select(ProductTranslation.name).where(ProductTranslation.product_id == source.id)
        )
    )
    aliases = list(
        db.scalars(select(ProductAlias.alias).where(ProductAlias.product_id == source.id))
    )
    for text in names + aliases:
        add_alias(db, actor, target.id, text, audit=False, ignore_duplicate=True)

    # Anything that already pointed at the duplicate now points at the survivor.
    for earlier in db.scalars(select(Product).where(Product.merged_into_id == source.id)):
        earlier.merged_into_id = target.id
    before = {"status": source.status}
    source.status = ProductStatus.MERGED.value
    source.merged_into_id = target.id
    db.flush()
    record_by(
        db, actor, "product.merge", "product", source.id, before=before,
        after={"status": "merged", "merged_into_id": str(target.id)},
    )  # fmt: skip
    return source


def add_alias(
    db: Session,
    actor: Actor,
    product_id: uuid.UUID,
    alias: str,
    *,
    audit: bool = True,
    ignore_duplicate: bool = False,
) -> ProductAlias | None:
    """A search synonym or local nickname for one product."""
    normalized = normalize_text(alias)
    if not normalized:
        raise ValidationFailed("alias_empty", "Enter a word or phrase.")
    existing = db.scalar(
        select(ProductAlias).where(
            ProductAlias.product_id == product_id, ProductAlias.normalized == normalized
        )
    )
    if existing is not None:
        if ignore_duplicate:
            return existing
        raise Conflict("alias_exists", "This product already has that alias.")
    row = ProductAlias(
        product_id=product_id,
        alias=alias.strip(),
        normalized=normalized,
        script=detect_script(alias),
    )
    db.add(row)
    db.flush()
    if audit:
        record_by(db, actor, "product.add_alias", "product", product_id, after={"alias": row.alias})
    return row


def remove_alias(db: Session, actor: Actor, product_id: uuid.UUID, alias_id: uuid.UUID) -> None:
    row = db.scalar(
        select(ProductAlias).where(
            ProductAlias.id == alias_id, ProductAlias.product_id == product_id
        )
    )
    if row is None:
        raise NotFound("alias_not_found", "That alias was not found.")
    record_by(db, actor, "product.remove_alias", "product", product_id, before={"alias": row.alias})
    db.delete(row)
