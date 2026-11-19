from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from markx.core.schemas import ApiModel

Slug = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", min_length=2, max_length=80)
]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
OptionCode = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_]{0,39}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Lang = Literal["am", "en"]


class CategoryIn(ApiModel):
    slug: Slug
    name_am: Name
    name_en: Name
    parent_id: uuid.UUID | None = None
    position: int = Field(default=0, ge=0, le=10_000)
    default_commission_bps: int = Field(default=0, ge=0, le=10_000)


class CategoryUpdateIn(ApiModel):
    name_am: Name | None = None
    name_en: Name | None = None
    position: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None


class OptionIn(ApiModel):
    code: OptionCode
    label_am: Name
    label_en: Name


class AttributeIn(ApiModel):
    code: Code
    data_type: Literal["text", "number", "option"]
    name_am: Name
    name_en: Name
    unit: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    options: list[OptionIn] = Field(default_factory=list, max_length=200)


class CategoryAttributeIn(ApiModel):
    is_required: bool = False
    is_filterable: bool = False
    is_variant_defining: bool = False
    position: int = Field(default=0, ge=0, le=10_000)


class BrandIn(ApiModel):
    name: Name
    slug: Slug | None = None


class VariantIn(ApiModel):
    attribute_values: dict[Code, OptionCode] = Field(default_factory=dict)
    model_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = (
        None
    )


class ProductIn(ApiModel):
    category_id: uuid.UUID
    name_am: Name
    name_en: Name
    description_am: Description = ""
    description_en: Description = ""
    brand_id: uuid.UUID | None = None
    model: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    slug: Slug | None = None
    specs: dict[Code, Any] = Field(default_factory=dict)
    variants: list[VariantIn] = Field(default_factory=list, max_length=60)
    status: Literal["draft", "approved"] = "draft"


class ProductTextIn(ApiModel):
    name_am: Name
    name_en: Name
    description_am: Description = ""
    description_en: Description = ""


class ArchiveIn(ApiModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class MergeIn(ApiModel):
    into_product_id: uuid.UUID


class AliasIn(ApiModel):
    alias: Name


class RestrictedTermIn(ApiModel):
    term: Name
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


# ---- responses ---------------------------------------------------------------


class CategoryBrief(ApiModel):
    id: uuid.UUID
    slug: str
    path: str
    name: str


class CategoryNode(CategoryBrief):
    position: int
    is_active: bool
    children: list[CategoryNode]


class OptionOut(ApiModel):
    code: str
    label: str


class AttributeOut(ApiModel):
    id: uuid.UUID
    code: str
    data_type: str
    unit: str | None
    name: str
    is_required: bool
    is_filterable: bool
    is_variant_defining: bool
    options: list[OptionOut]


class CategoryDetail(CategoryBrief):
    breadcrumbs: list[CategoryBrief]
    children: list[CategoryBrief]
    attributes: list[AttributeOut]


class BrandOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str


class SpecOut(ApiModel):
    code: str
    name: str
    value: Any
    display: str


class VariantOut(ApiModel):
    id: uuid.UUID
    attribute_values: dict[str, str]
    label: str
    model_code: str | None
    is_active: bool


class ProductOut(ApiModel):
    id: uuid.UUID
    slug: str
    status: str
    name: str
    description: str
    name_am: str
    name_en: str
    model: str | None
    category: CategoryBrief
    brand: BrandOut | None
    specs: list[SpecOut]
    variants: list[VariantOut]
    # Set when the requested link belonged to a product merged into this one.
    redirected_from: str | None


class AliasOut(ApiModel):
    id: uuid.UUID
    alias: str
    script: str


class StaffProductOut(ProductOut):
    description_am: str
    description_en: str
    review_note: str | None
    merged_into_id: uuid.UUID | None
    proposed_by_seller_id: uuid.UUID | None
    aliases: list[AliasOut]


class StaffProductRow(ApiModel):
    id: uuid.UUID
    slug: str
    status: str
    name: str
    proposed_by_seller_id: uuid.UUID | None
    created_at: datetime


class RestrictedTermOut(ApiModel):
    id: uuid.UUID
    term: str
    reason: str
