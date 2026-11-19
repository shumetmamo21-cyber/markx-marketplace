"""Read queries for the catalogue. Nothing here changes data."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.catalog import service
from markx.catalog.models import (
    Attribute,
    AttributeOption,
    AttributeOptionTranslation,
    AttributeTranslation,
    AttributeType,
    Brand,
    Category,
    CategoryTranslation,
    Product,
    ProductAlias,
    ProductStatus,
    ProductTranslation,
    ProductVariant,
)
from markx.core.errors import NotFound

OTHER_LANGUAGE = {"am": "en", "en": "am"}
MAX_MERGE_HOPS = 10


def _pick(texts: dict[str, str], language: str) -> str:
    """The text in the asked language, falling back to the other one."""
    return texts.get(language) or texts.get(OTHER_LANGUAGE[language]) or ""


def _category_names(db: Session, category_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, str]]:
    names: dict[uuid.UUID, dict[str, str]] = {}
    if not category_ids:
        return names
    for row in db.scalars(
        select(CategoryTranslation).where(CategoryTranslation.category_id.in_(category_ids))
    ):
        names.setdefault(row.category_id, {})[row.language] = row.name
    return names


def category_tree(db: Session, language: str, *, active_only: bool = True) -> list[dict[str, Any]]:
    query = select(Category).order_by(Category.position, Category.slug)
    if active_only:
        query = query.where(Category.is_active)
    categories = list(db.scalars(query))
    names = _category_names(db, [c.id for c in categories])
    nodes: dict[uuid.UUID, dict[str, Any]] = {
        c.id: {
            "id": c.id,
            "slug": c.slug,
            "path": c.path,
            "name": _pick(names.get(c.id, {}), language),
            "position": c.position,
            "is_active": c.is_active,
            "children": [],
        }
        for c in categories
    }
    roots: list[dict[str, Any]] = []
    for category in categories:
        parent = nodes.get(category.parent_id) if category.parent_id else None
        if parent is not None:
            parent["children"].append(nodes[category.id])
        elif category.parent_id is None:
            roots.append(nodes[category.id])
        # A child of a hidden parent is hidden with it.
    return roots


def attributes_out(
    db: Session, rules: dict[str, service.AttributeRule], language: str
) -> list[dict[str, Any]]:
    attribute_ids = [rule.attribute.id for rule in rules.values()]
    if not attribute_ids:
        return []
    names: dict[uuid.UUID, dict[str, str]] = {}
    for name_row in db.scalars(
        select(AttributeTranslation).where(AttributeTranslation.attribute_id.in_(attribute_ids))
    ):
        names.setdefault(name_row.attribute_id, {})[name_row.language] = name_row.name
    options: dict[uuid.UUID, list[AttributeOption]] = {}
    for option in db.scalars(
        select(AttributeOption)
        .where(AttributeOption.attribute_id.in_(attribute_ids))
        .order_by(AttributeOption.position, AttributeOption.code)
    ):
        options.setdefault(option.attribute_id, []).append(option)
    labels: dict[uuid.UUID, dict[str, str]] = {}
    option_ids = [o.id for group in options.values() for o in group]
    if option_ids:
        for label_row in db.scalars(
            select(AttributeOptionTranslation).where(
                AttributeOptionTranslation.option_id.in_(option_ids)
            )
        ):
            labels.setdefault(label_row.option_id, {})[label_row.language] = label_row.label
    return [
        {
            "id": rule.attribute.id,
            "code": code,
            "data_type": rule.attribute.data_type,
            "unit": rule.attribute.unit,
            "name": _pick(names.get(rule.attribute.id, {}), language),
            "is_required": rule.is_required,
            "is_filterable": rule.is_filterable,
            "is_variant_defining": rule.is_variant_defining,
            "options": [
                {"code": o.code, "label": _pick(labels.get(o.id, {}), language)}
                for o in options.get(rule.attribute.id, [])
            ],
        }
        for code, rule in sorted(rules.items(), key=lambda item: (item[1].position, item[0]))
    ]


def category_detail(db: Session, slug: str, language: str) -> dict[str, Any]:
    category = db.scalar(select(Category).where(Category.slug == slug, Category.is_active))
    if category is None:
        raise NotFound("category_not_found", "That category was not found.")
    parts = category.path.split("/")
    ancestors = list(
        db.scalars(
            select(Category)
            .where(Category.path.in_(["/".join(parts[: i + 1]) for i in range(len(parts))]))
            .order_by(Category.path)
        )
    )
    children = list(
        db.scalars(
            select(Category)
            .where(Category.parent_id == category.id, Category.is_active)
            .order_by(Category.position, Category.slug)
        )
    )
    names = _category_names(db, [c.id for c in ancestors + children])
    rules = service.attribute_rules(db, category)

    def brief(c: Category) -> dict[str, Any]:
        return {
            "id": c.id,
            "slug": c.slug,
            "path": c.path,
            "name": _pick(names.get(c.id, {}), language),
        }

    return {
        **brief(category),
        "breadcrumbs": [brief(c) for c in sorted(ancestors, key=lambda c: c.path.count("/"))],
        "children": [brief(c) for c in children],
        "attributes": attributes_out(db, rules, language),
    }


def list_brands(db: Session) -> list[Brand]:
    return list(db.scalars(select(Brand).order_by(Brand.name)))


def all_attributes(db: Session, language: str) -> list[dict[str, Any]]:
    """Every attribute, for the staff console."""
    rules = {
        a.code: service.AttributeRule(
            attribute=a, is_required=False, is_filterable=False, is_variant_defining=False,
            position=0, option_codes=frozenset(),
        )
        for a in db.scalars(select(Attribute).order_by(Attribute.code))
    }  # fmt: skip
    return attributes_out(db, rules, language)


def resolve_merged(db: Session, product: Product) -> Product:
    """Follow a merged product to its survivor."""
    hops = 0
    while product.status == ProductStatus.MERGED and product.merged_into_id is not None:
        survivor = db.get(Product, product.merged_into_id)
        if survivor is None or hops >= MAX_MERGE_HOPS:
            break
        product, hops = survivor, hops + 1
    return product


def _format_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def product_out(
    db: Session, product: Product, language: str, *, for_staff: bool = False
) -> dict[str, Any]:
    texts: dict[str, ProductTranslation] = {
        t.language: t
        for t in db.scalars(
            select(ProductTranslation).where(ProductTranslation.product_id == product.id)
        )
    }
    names = {lang: t.name for lang, t in texts.items()}
    descriptions = {lang: t.description for lang, t in texts.items()}

    category = db.get(Category, product.category_id)
    assert category is not None
    category_name = _pick(_category_names(db, [category.id]).get(category.id, {}), language)
    brand = db.get(Brand, product.brand_id) if product.brand_id else None

    rules = service.attribute_rules(db, category)
    attributes = {a["code"]: a for a in attributes_out(db, rules, language)}

    def display(code: str, value: Any) -> str:
        attribute = attributes.get(code)
        if attribute is None:
            return str(value)
        if attribute["data_type"] == AttributeType.OPTION:
            return next(
                (o["label"] for o in attribute["options"] if o["code"] == value), str(value)
            )
        if attribute["data_type"] == AttributeType.NUMBER:
            unit = f" {attribute['unit']}" if attribute["unit"] else ""
            return f"{_format_number(value)}{unit}"
        return str(value)

    variants = list(
        db.scalars(
            select(ProductVariant)
            .where(ProductVariant.product_id == product.id)
            .order_by(ProductVariant.position)
        )
    )
    out: dict[str, Any] = {
        "id": product.id,
        "slug": product.slug,
        "status": product.status,
        "name": _pick(names, language),
        "description": _pick(descriptions, language),
        "name_am": names.get("am", ""),
        "name_en": names.get("en", ""),
        "model": product.model,
        "category": {
            "id": category.id,
            "slug": category.slug,
            "path": category.path,
            "name": category_name,
        },
        "brand": {"id": brand.id, "slug": brand.slug, "name": brand.name} if brand else None,
        "specs": [
            {
                "code": code,
                "name": attributes[code]["name"] if code in attributes else code,
                "value": value,
                "display": display(code, value),
            }
            for code, value in sorted(product.specs.items())
        ],
        "variants": [
            {
                "id": v.id,
                "attribute_values": v.attribute_values,
                "label": " · ".join(
                    display(code, v.attribute_values[code]) for code in sorted(v.attribute_values)
                ),
                "model_code": v.model_code,
                "is_active": v.is_active,
            }
            for v in variants
        ],
        "redirected_from": None,
    }
    if for_staff:
        out["description_am"] = descriptions.get("am", "")
        out["description_en"] = descriptions.get("en", "")
        out["review_note"] = product.review_note
        out["merged_into_id"] = product.merged_into_id
        out["proposed_by_seller_id"] = product.proposed_by_seller_id
        out["aliases"] = [
            {"id": a.id, "alias": a.alias, "script": a.script}
            for a in db.scalars(
                select(ProductAlias)
                .where(ProductAlias.product_id == product.id)
                .order_by(ProductAlias.alias)
            )
        ]
    return out


def variant_labels(db: Session, products: Iterable[Product], language: str) -> dict[uuid.UUID, str]:
    """Each variant's label ("Black · 128 GB"), exactly as the product page
    shows it, for screens that list variants of several products."""
    labels: dict[uuid.UUID, str] = {}
    for product in {product.id: product for product in products}.values():
        for variant in product_out(db, product, language)["variants"]:
            labels[variant["id"]] = str(variant["label"])
    return labels


def public_product(db: Session, slug: str, language: str) -> dict[str, Any]:
    """An approved product by its link name. A merged product forwards to its
    survivor. Drafts, proposals and archived products are not found."""
    not_found = NotFound("product_not_found", "That product was not found.")
    product = db.scalar(select(Product).where(Product.slug == slug))
    if product is None:
        raise not_found
    survivor = resolve_merged(db, product)
    if survivor.status != ProductStatus.APPROVED:
        raise not_found
    out = product_out(db, survivor, language)
    if survivor.id != product.id:
        out["redirected_from"] = slug
    return out


def staff_products(
    db: Session, language: str, *, status: str | None, limit: int
) -> list[dict[str, Any]]:
    query = select(Product).order_by(Product.created_at.desc(), Product.id.desc()).limit(limit)
    if status is not None:
        query = query.where(Product.status == status)
    products = list(db.scalars(query))
    names: dict[uuid.UUID, dict[str, str]] = {}
    if products:
        for t in db.scalars(
            select(ProductTranslation).where(
                ProductTranslation.product_id.in_([p.id for p in products])
            )
        ):
            names.setdefault(t.product_id, {})[t.language] = t.name
    return [
        {
            "id": p.id,
            "slug": p.slug,
            "status": p.status,
            "name": _pick(names.get(p.id, {}), language),
            "proposed_by_seller_id": p.proposed_by_seller_id,
            "created_at": p.created_at,
        }
        for p in products
    ]
