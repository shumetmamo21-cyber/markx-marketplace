from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from markx.accounts.deps import Principal, require_staff
from markx.accounts.permissions import StaffCapability
from markx.catalog import selectors, service
from markx.catalog.models import Attribute, AttributeType, ProductStatus, RestrictedTerm
from markx.catalog.schemas import (
    AliasIn,
    AliasOut,
    ArchiveIn,
    AttributeIn,
    AttributeOut,
    BrandIn,
    BrandOut,
    CategoryAttributeIn,
    CategoryDetail,
    CategoryIn,
    CategoryNode,
    CategoryUpdateIn,
    Lang,
    MergeIn,
    OptionIn,
    ProductIn,
    ProductOut,
    ProductTextIn,
    RestrictedTermIn,
    RestrictedTermOut,
    StaffProductOut,
    StaffProductRow,
    VariantIn,
    VariantOut,
)
from markx.core.errors import NotFound
from markx.core.http import Db
from markx.core.schemas import Ok

router = APIRouter(prefix="/catalog", tags=["catalog"])
admin_router = APIRouter(prefix="/admin/catalog", tags=["admin: catalog"])

# Blueprint C.4.
Curator = Annotated[Principal, Depends(require_staff(StaffCapability.CURATE_CATALOGUE))]
Moderator = Annotated[Principal, Depends(require_staff(StaffCapability.MODERATE_LISTINGS))]
LangQuery = Annotated[Lang, Query()]

PUBLIC_CACHE = "public, max-age=60"  # blueprint F.1: catalogue pages may be cached briefly


# ---- public ------------------------------------------------------------------


@router.get("/categories", response_model=list[CategoryNode])
def category_tree(db: Db, response: Response, lang: LangQuery = "am") -> list[CategoryNode]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return [CategoryNode.model_validate(n) for n in selectors.category_tree(db, lang)]


@router.get("/categories/{slug}", response_model=CategoryDetail)
def category_detail(
    slug: str, db: Db, response: Response, lang: LangQuery = "am"
) -> CategoryDetail:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return CategoryDetail.model_validate(selectors.category_detail(db, slug, lang))


@router.get("/brands", response_model=list[BrandOut])
def brands(db: Db, response: Response) -> list[BrandOut]:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return [BrandOut.model_validate(b) for b in selectors.list_brands(db)]


@router.get("/products/{slug}", response_model=ProductOut)
def product(slug: str, db: Db, response: Response, lang: LangQuery = "am") -> ProductOut:
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return ProductOut.model_validate(selectors.public_product(db, slug, lang))


# ---- staff: categories, attributes, brands -------------------------------------


@admin_router.get("/categories", response_model=list[CategoryNode])
def all_categories(_: Curator, db: Db, lang: LangQuery = "en") -> list[CategoryNode]:
    return [
        CategoryNode.model_validate(n) for n in selectors.category_tree(db, lang, active_only=False)
    ]


@admin_router.post("/categories", response_model=CategoryNode, status_code=201)
def create_category(body: CategoryIn, staff: Curator, request: Request, db: Db) -> CategoryNode:
    category = service.create_category(
        db, staff.actor(request), slug=body.slug, name_am=body.name_am, name_en=body.name_en,
        parent_id=body.parent_id, position=body.position,
        default_commission_bps=body.default_commission_bps,
    )  # fmt: skip
    return CategoryNode(
        id=category.id, slug=category.slug, path=category.path, name=body.name_en,
        position=category.position, is_active=category.is_active, children=[],
    )  # fmt: skip


@admin_router.patch("/categories/{category_id}", response_model=Ok)
def update_category(
    category_id: uuid.UUID, body: CategoryUpdateIn, staff: Curator, request: Request, db: Db
) -> Ok:
    service.update_category(
        db, staff.actor(request), category_id, name_am=body.name_am, name_en=body.name_en,
        position=body.position, is_active=body.is_active,
    )  # fmt: skip
    return Ok()


@admin_router.get("/attributes", response_model=list[AttributeOut])
def all_attributes(_: Curator, db: Db, lang: LangQuery = "en") -> list[AttributeOut]:
    return [AttributeOut.model_validate(a) for a in selectors.all_attributes(db, lang)]


@admin_router.post("/attributes", response_model=AttributeOut, status_code=201)
def create_attribute(body: AttributeIn, staff: Curator, request: Request, db: Db) -> AttributeOut:
    attribute = service.create_attribute(
        db, staff.actor(request), code=body.code, data_type=AttributeType(body.data_type),
        name_am=body.name_am, name_en=body.name_en, unit=body.unit,
        options=[service.OptionInput(o.code, o.label_am, o.label_en) for o in body.options],
    )  # fmt: skip
    return next(
        AttributeOut.model_validate(a)
        for a in selectors.all_attributes(db, "en")
        if a["id"] == attribute.id
    )


@admin_router.post("/attributes/{attribute_id}/options", response_model=Ok, status_code=201)
def add_option(attribute_id: uuid.UUID, body: OptionIn, _: Curator, db: Db) -> Ok:
    attribute = db.get(Attribute, attribute_id)
    if attribute is None:
        raise NotFound("attribute_not_found", "That attribute was not found.")
    service.add_attribute_option(
        db, attribute, service.OptionInput(body.code, body.label_am, body.label_en)
    )
    return Ok()


@admin_router.put("/categories/{category_id}/attributes/{attribute_id}", response_model=Ok)
def attach_attribute(
    category_id: uuid.UUID,
    attribute_id: uuid.UUID,
    body: CategoryAttributeIn,
    staff: Curator,
    request: Request,
    db: Db,
) -> Ok:
    service.attach_attribute(
        db, staff.actor(request), category_id, attribute_id, is_required=body.is_required,
        is_filterable=body.is_filterable, is_variant_defining=body.is_variant_defining,
        position=body.position,
    )  # fmt: skip
    return Ok()


@admin_router.post("/brands", response_model=BrandOut, status_code=201)
def create_brand(body: BrandIn, staff: Curator, request: Request, db: Db) -> BrandOut:
    return BrandOut.model_validate(
        service.create_brand(db, staff.actor(request), name=body.name, slug=body.slug)
    )


# ---- staff: products -----------------------------------------------------------


def _staff_product(db: Db, product_id: uuid.UUID, lang: str = "en") -> StaffProductOut:
    product = service.get_product(db, product_id)
    return StaffProductOut.model_validate(selectors.product_out(db, product, lang, for_staff=True))


@admin_router.get("/products", response_model=list[StaffProductRow])
def list_products(
    _: Curator,
    db: Db,
    status: Literal["draft", "pending_review", "approved", "merged", "archived"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    lang: LangQuery = "en",
) -> list[StaffProductRow]:
    return [
        StaffProductRow.model_validate(r)
        for r in selectors.staff_products(db, lang, status=status, limit=limit)
    ]


@admin_router.post("/products", response_model=StaffProductOut, status_code=201)
def create_product(body: ProductIn, staff: Curator, request: Request, db: Db) -> StaffProductOut:
    product = service.create_product(
        db, staff.actor(request), category_id=body.category_id, name_am=body.name_am,
        name_en=body.name_en, description_am=body.description_am,
        description_en=body.description_en, brand_id=body.brand_id, model=body.model,
        slug=body.slug, specs=body.specs,
        variants=[service.VariantInput(v.attribute_values, v.model_code) for v in body.variants],
        status=ProductStatus(body.status),
    )  # fmt: skip
    return _staff_product(db, product.id)


@admin_router.get("/products/{product_id}", response_model=StaffProductOut)
def read_product(
    product_id: uuid.UUID, _: Curator, db: Db, lang: LangQuery = "en"
) -> StaffProductOut:
    return _staff_product(db, product_id, lang)


@admin_router.put("/products/{product_id}/text", response_model=StaffProductOut)
def update_text(
    product_id: uuid.UUID, body: ProductTextIn, staff: Curator, request: Request, db: Db
) -> StaffProductOut:
    service.update_product_text(
        db, staff.actor(request), product_id, name_am=body.name_am, name_en=body.name_en,
        description_am=body.description_am, description_en=body.description_en,
    )  # fmt: skip
    return _staff_product(db, product_id)


@admin_router.post("/products/{product_id}/variants", response_model=VariantOut, status_code=201)
def add_variant(
    product_id: uuid.UUID, body: VariantIn, staff: Curator, request: Request, db: Db
) -> VariantOut:
    variant = service.add_variant(
        db, staff.actor(request), product_id,
        service.VariantInput(body.attribute_values, body.model_code),
    )  # fmt: skip
    detail = _staff_product(db, product_id)
    return next(v for v in detail.variants if v.id == variant.id)


@admin_router.post("/products/{product_id}/approve", response_model=StaffProductOut)
def approve(product_id: uuid.UUID, staff: Curator, request: Request, db: Db) -> StaffProductOut:
    service.approve_product(db, staff.actor(request), product_id)
    return _staff_product(db, product_id)


@admin_router.post("/products/{product_id}/archive", response_model=StaffProductOut)
def archive(
    product_id: uuid.UUID, body: ArchiveIn, staff: Curator, request: Request, db: Db
) -> StaffProductOut:
    service.archive_product(db, staff.actor(request), product_id, note=body.note)
    return _staff_product(db, product_id)


@admin_router.post("/products/{product_id}/merge", response_model=StaffProductOut)
def merge(
    product_id: uuid.UUID, body: MergeIn, staff: Curator, request: Request, db: Db
) -> StaffProductOut:
    service.merge_product(db, staff.actor(request), product_id, body.into_product_id)
    return _staff_product(db, product_id)


@admin_router.post("/products/{product_id}/aliases", response_model=AliasOut, status_code=201)
def add_alias(
    product_id: uuid.UUID, body: AliasIn, staff: Curator, request: Request, db: Db
) -> AliasOut:
    service.get_product(db, product_id)
    alias = service.add_alias(db, staff.actor(request), product_id, body.alias)
    assert alias is not None
    return AliasOut.model_validate(alias)


@admin_router.delete("/products/{product_id}/aliases/{alias_id}", response_model=Ok)
def remove_alias(
    product_id: uuid.UUID, alias_id: uuid.UUID, staff: Curator, request: Request, db: Db
) -> Ok:
    service.remove_alias(db, staff.actor(request), product_id, alias_id)
    return Ok()


# ---- staff: restricted goods ---------------------------------------------------


@admin_router.get("/restricted-terms", response_model=list[RestrictedTermOut])
def restricted_terms(_: Moderator, db: Db) -> list[RestrictedTermOut]:
    return [
        RestrictedTermOut.model_validate(t)
        for t in db.scalars(select(RestrictedTerm).order_by(RestrictedTerm.term))
    ]


@admin_router.post("/restricted-terms", response_model=RestrictedTermOut, status_code=201)
def add_restricted_term(
    body: RestrictedTermIn, staff: Moderator, request: Request, db: Db
) -> RestrictedTermOut:
    return RestrictedTermOut.model_validate(
        service.add_restricted_term(db, staff.actor(request), term=body.term, reason=body.reason)
    )


@admin_router.delete("/restricted-terms/{term_id}", response_model=Ok)
def remove_restricted_term(term_id: uuid.UUID, staff: Moderator, request: Request, db: Db) -> Ok:
    service.remove_restricted_term(db, staff.actor(request), term_id)
    return Ok()
