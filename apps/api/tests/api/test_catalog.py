"""The shared catalogue (blueprint D.5, D.6, P5): one clean page per product."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from markx.accounts.models import StaffRole
from markx.audit.models import AuditLog
from markx.core.ids import uuid7
from tests.conftest import ApiClient, error_code
from tests.factories import make_catalog, make_product, phone_body, staff_client

CURATOR = "0911000300"
MISSING = "00000000-0000-7000-8000-000000000000"


@pytest.fixture
def staff(db: DbSession) -> ApiClient:
    return staff_client(db, CURATOR, StaffRole.CATALOGUE)


@pytest.fixture
def catalog(staff: ApiClient) -> dict[str, Any]:
    return make_catalog(staff)


# ---------------------------------------------------------------- categories


def test_the_category_tree_is_public_and_follows_the_language(catalog: dict[str, Any]) -> None:
    visitor = ApiClient()
    english = visitor.get("/catalog/categories", params={"lang": "en"})
    assert english.status_code == 200
    assert english.headers["cache-control"] == "public, max-age=60"
    [root] = english.json()
    assert (root["name"], root["path"]) == ("Electronics", "electronics")
    assert [(c["name"], c["path"]) for c in root["children"]] == [("Phones", "electronics/phones")]

    [amharic] = visitor.get("/catalog/categories", params={"lang": "am"}).json()
    assert amharic["name"] == "ኤሌክትሮኒክስ"
    assert amharic["children"][0]["name"] == "ስልኮች"
    # Amharic is the default language (blueprint N.32).
    assert visitor.get("/catalog/categories").json()[0]["name"] == "ኤሌክትሮኒክስ"
    assert visitor.get("/catalog/categories", params={"lang": "fr"}).status_code == 422


def test_hiding_a_category_hides_it_and_everything_under_it(
    staff: ApiClient, catalog: dict[str, Any]
) -> None:
    assert (
        staff.patch(
            f"/admin/catalog/categories/{catalog['electronics']}", json={"is_active": False}
        ).status_code
        == 200
    )
    assert ApiClient().get("/catalog/categories").json() == []
    assert (
        ApiClient().get("/catalog/categories/phones").status_code == 200
    )  # phones itself is still active
    assert ApiClient().get("/catalog/categories/electronics").status_code == 404
    # Staff still see the whole tree.
    assert len(staff.get("/admin/catalog/categories").json()) == 1


def test_category_rules(staff: ApiClient, catalog: dict[str, Any]) -> None:
    duplicate = staff.post(
        "/admin/catalog/categories", json={"slug": "phones", "name_am": "ስ", "name_en": "P"}
    )
    assert (duplicate.status_code, error_code(duplicate)) == (409, "category_slug_taken")

    third = staff.post(
        "/admin/catalog/categories",
        json={
            "slug": "smartphones",
            "name_am": "ስማርት",
            "name_en": "Smartphones",
            "parent_id": catalog["phones"],
        },
    )
    assert third.status_code == 201
    assert third.json()["path"] == "electronics/phones/smartphones"
    fourth = staff.post(
        "/admin/catalog/categories",
        json={
            "slug": "android",
            "name_am": "አንድሮይድ",
            "name_en": "Android",
            "parent_id": third.json()["id"],
        },
    )
    assert (fourth.status_code, error_code(fourth)) == (422, "category_too_deep")

    orphan = staff.post(
        "/admin/catalog/categories",
        json={"slug": "x1", "name_am": "x", "name_en": "x", "parent_id": MISSING},
    )
    assert (orphan.status_code, error_code(orphan)) == (404, "category_not_found")
    for bad in ("Phones", "two words", "-lead", "trail-", "a"):
        assert (
            staff.post(
                "/admin/catalog/categories", json={"slug": bad, "name_am": "x", "name_en": "x"}
            ).status_code
            == 422
        )


def test_category_detail_lists_inherited_attributes_with_labels(catalog: dict[str, Any]) -> None:
    detail = ApiClient().get("/catalog/categories/phones", params={"lang": "en"}).json()
    assert [b["name"] for b in detail["breadcrumbs"]] == ["Electronics", "Phones"]
    by_code = {a["code"]: a for a in detail["attributes"]}
    assert set(by_code) == {"storage", "colour", "screen_inches", "os"}
    # Colour was attached to Electronics and is inherited by Phones.
    assert by_code["colour"]["is_variant_defining"] is True
    assert [o["label"] for o in by_code["storage"]["options"]] == ["128 GB", "256 GB"]
    assert (by_code["storage"]["is_required"], by_code["storage"]["is_filterable"]) == (True, True)
    assert by_code["screen_inches"]["unit"] == "in"

    amharic = ApiClient().get("/catalog/categories/phones").json()
    assert {a["code"]: a["name"] for a in amharic["attributes"]}["colour"] == "ቀለም"
    assert [
        o["label"]
        for o in next(a for a in amharic["attributes"] if a["code"] == "colour")["options"]
    ] == ["ጥቁር", "ሰማያዊ"]

    parent = ApiClient().get("/catalog/categories/electronics", params={"lang": "en"}).json()
    assert [c["name"] for c in parent["children"]] == ["Phones"]
    assert [a["code"] for a in parent["attributes"]] == ["colour"]


def test_attribute_rules(staff: ApiClient, catalog: dict[str, Any]) -> None:
    no_options = staff.post(
        "/admin/catalog/attributes",
        json={"code": "ram", "data_type": "option", "name_am": "ራም", "name_en": "RAM"},
    )
    assert (no_options.status_code, error_code(no_options)) == (422, "options_required")
    stray_options = staff.post(
        "/admin/catalog/attributes",
        json={"code": "weight", "data_type": "number", "name_am": "ክ", "name_en": "W",
              "options": [{"code": "x", "label_am": "x", "label_en": "x"}]},
    )  # fmt: skip
    assert (stray_options.status_code, error_code(stray_options)) == (422, "options_not_allowed")
    duplicate = staff.post(
        "/admin/catalog/attributes",
        json={"code": "os", "data_type": "text", "name_am": "x", "name_en": "x"},
    )
    assert (duplicate.status_code, error_code(duplicate)) == (409, "attribute_code_taken")
    # Only a list attribute can define variants: a variant is one choice from a fixed list.
    as_variant = staff.put(
        f"/admin/catalog/categories/{catalog['phones']}/attributes/{catalog['screen']}",
        json={"is_variant_defining": True},
    )
    assert (as_variant.status_code, error_code(as_variant)) == (
        422,
        "variant_attribute_must_be_a_list",
    )


# ------------------------------------------------------------------ products


def test_an_approved_product_has_a_public_page_in_both_languages(
    staff: ApiClient, catalog: dict[str, Any]
) -> None:
    created = make_product(staff, catalog)
    assert created["slug"] == "samsung-galaxy-a16"

    english = ApiClient().get("/catalog/products/samsung-galaxy-a16", params={"lang": "en"})
    assert english.status_code == 200
    assert english.headers["cache-control"] == "public, max-age=60"
    page = english.json()
    assert page["name"] == "Samsung Galaxy A16"
    assert page["description"] == "A 6.7 inch phone."
    assert page["brand"]["name"] == "Samsung"
    assert page["category"]["path"] == "electronics/phones"
    assert page["redirected_from"] is None
    assert {s["code"]: s["display"] for s in page["specs"]} == {
        "os": "Android 14",
        "screen_inches": "6.7 in",
    }
    assert [v["label"] for v in page["variants"]] == ["Black · 128 GB", "Black · 256 GB"]
    assert page["variants"][0]["model_code"] == "A16-128-BK"
    # Staff-only fields never reach the public page.
    assert "review_note" not in page
    assert "aliases" not in page

    amharic = ApiClient().get("/catalog/products/samsung-galaxy-a16").json()
    assert amharic["name"] == "ሳምሰንግ ጋላክሲ A16"
    assert amharic["variants"][0]["label"] == "ጥቁር · 128 ጊባ"
    # No Amharic description was written, so the English one is shown rather than nothing.
    assert amharic["description"] == "A 6.7 inch phone."
    assert {s["code"]: s["name"] for s in amharic["specs"]}["screen_inches"] == "ስክሪን"


@pytest.mark.parametrize("status", ["draft"])
def test_only_approved_products_are_public(
    staff: ApiClient, catalog: dict[str, Any], status: str
) -> None:
    product = make_product(staff, catalog, status=status)
    hidden = ApiClient().get(f"/catalog/products/{product['slug']}")
    assert (hidden.status_code, error_code(hidden)) == (404, "product_not_found")

    approved = staff.post(f"/admin/catalog/products/{product['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert ApiClient().get(f"/catalog/products/{product['slug']}").status_code == 200
    # Approving twice is refused: there is nothing left to approve.
    again = staff.post(f"/admin/catalog/products/{product['id']}/approve")
    assert (again.status_code, error_code(again)) == (409, "product_not_approvable")


def test_archiving_takes_a_product_off_the_site_and_keeps_the_row(
    staff: ApiClient, catalog: dict[str, Any], db: DbSession
) -> None:
    product = make_product(staff, catalog)
    archived = staff.post(
        f"/admin/catalog/products/{product['id']}/archive", json={"note": "discontinued"}
    )
    assert archived.status_code == 200
    assert (archived.json()["status"], archived.json()["review_note"]) == (
        "archived",
        "discontinued",
    )
    assert ApiClient().get(f"/catalog/products/{product['slug']}").status_code == 404
    # Products are archived, never deleted (blueprint D.5).
    assert db.execute(text("select count(*) from products")).scalar_one() == 1
    assert (
        staff.post(f"/admin/catalog/products/{product['id']}/archive", json={}).status_code == 200
    )


def test_link_names_are_generated_and_kept_unique(
    staff: ApiClient, catalog: dict[str, Any]
) -> None:
    first = make_product(staff, catalog)
    second = make_product(staff, catalog)
    third = make_product(staff, catalog, slug="my-own-link")
    assert [first["slug"], second["slug"], third["slug"]] == [
        "samsung-galaxy-a16", "samsung-galaxy-a16-2", "my-own-link",
    ]  # fmt: skip
    no_latin = staff.post("/admin/catalog/products", json=phone_body(catalog, name_en="ሳምሰንግ"))
    assert (no_latin.status_code, error_code(no_latin)) == (422, "slug_required")


def test_a_product_with_nothing_to_choose_gets_one_default_variant(
    staff: ApiClient, catalog: dict[str, Any]
) -> None:
    accessory = staff.post(
        "/admin/catalog/products",
        json={
            "category_id": catalog["electronics"],
            "name_am": "ቻርጀር",
            "name_en": "USB-C Charger",
            "status": "approved",
        },
    )
    assert accessory.status_code == 201
    [variant] = accessory.json()["variants"]
    assert (variant["attribute_values"], variant["label"]) == ({}, "")


@pytest.mark.parametrize(
    ("specs", "code"),
    [
        ({"screen_inches": 6.7, "battery": 5000}, "attribute_not_in_category"),
        ({"screen_inches": "big"}, "attribute_value_invalid"),
        ({"screen_inches": True}, "attribute_value_invalid"),  # a boolean is not a number
        ({"screen_inches": 6.7, "os": ""}, "attribute_value_invalid"),
        ({"os": "Android"}, "attribute_required"),  # screen size is required
        ({"screen_inches": 6.7, "storage": "128gb"}, "attribute_belongs_to_variants"),
    ],
)
def test_specifications_must_satisfy_the_category(
    staff: ApiClient, catalog: dict[str, Any], specs: dict[str, Any], code: str
) -> None:
    response = staff.post("/admin/catalog/products", json=phone_body(catalog, specs=specs))
    assert (response.status_code, error_code(response)) == (422, code)


@pytest.mark.parametrize(
    ("variants", "status", "code"),
    [
        ([{"attribute_values": {"storage": "512gb"}}], 422, "attribute_value_invalid"),
        ([{"attribute_values": {"storage": "128gb", "os": "android"}}], 422, "attribute_not_variant_defining"),
        ([{"attribute_values": {"colour": "black"}}], 422, "attribute_required"),  # storage is required
        (
            [{"attribute_values": {"storage": "128gb"}}, {"attribute_values": {"storage": "256gb", "colour": "black"}}],
            422, "variants_inconsistent",
        ),
        (
            [{"attribute_values": {"storage": "128gb", "colour": "black"}},
             {"attribute_values": {"colour": "black", "storage": "128gb"}}],
            409, "variant_duplicate",
        ),
    ],
)  # fmt: skip
def test_variants_must_satisfy_the_category(
    staff: ApiClient,
    catalog: dict[str, Any],
    variants: list[dict[str, Any]],
    status: int,
    code: str,
) -> None:
    response = staff.post("/admin/catalog/products", json=phone_body(catalog, variants=variants))
    assert (response.status_code, error_code(response)) == (status, code)


def test_a_variant_can_be_added_but_not_duplicated(
    staff: ApiClient, catalog: dict[str, Any]
) -> None:
    product = make_product(staff, catalog)
    added = staff.post(
        f"/admin/catalog/products/{product['id']}/variants",
        json={"attribute_values": {"storage": "128gb", "colour": "blue"}},
    )
    assert added.status_code == 201
    assert added.json()["label"] == "Blue · 128 GB"
    duplicate = staff.post(
        f"/admin/catalog/products/{product['id']}/variants",
        json={"attribute_values": {"colour": "blue", "storage": "128gb"}},
    )
    assert (duplicate.status_code, error_code(duplicate)) == (409, "variant_duplicate")
    lopsided = staff.post(
        f"/admin/catalog/products/{product['id']}/variants",
        json={"attribute_values": {"storage": "256gb"}},
    )
    assert (lopsided.status_code, error_code(lopsided)) == (422, "variants_inconsistent")
    assert len(staff.get(f"/admin/catalog/products/{product['id']}").json()["variants"]) == 3


def test_the_database_itself_rejects_a_duplicate_variant(
    staff: ApiClient, catalog: dict[str, Any], db: DbSession
) -> None:
    """Blueprint P5 completion criterion, checked below the application."""
    product = make_product(staff, catalog)
    with pytest.raises(IntegrityError) as excinfo:
        db.execute(
            text(
                "insert into product_variants (id, product_id, attribute_values, attribute_key) "
                "values (:id, :product, '{}', 'colour=black|storage=128gb')"
            ),
            {"id": uuid7(), "product": product["id"]},
        )
    assert "uq_product_variants_product_id_attribute_key" in str(excinfo.value)


# --------------------------------------------------------------------- merge


def test_a_merged_product_forwards_to_the_survivor(
    staff: ApiClient, catalog: dict[str, Any]
) -> None:
    survivor = make_product(staff, catalog)
    duplicate = make_product(
        staff, catalog, name_en="Galaxy A16 Dual SIM", name_am="ጋላክሲ A16 ባለሁለት ሲም"
    )
    staff.post(f"/admin/catalog/products/{duplicate['id']}/aliases", json={"alias": "A16 ስልክ"})

    merged = staff.post(
        f"/admin/catalog/products/{duplicate['id']}/merge", json={"into_product_id": survivor["id"]}
    )
    assert merged.status_code == 200
    assert (merged.json()["status"], merged.json()["merged_into_id"]) == ("merged", survivor["id"])

    # The old page forwards to the surviving one (blueprint D.5).
    old_link = (
        ApiClient().get(f"/catalog/products/{duplicate['slug']}", params={"lang": "en"}).json()
    )
    assert old_link["id"] == survivor["id"]
    assert old_link["slug"] == survivor["slug"]
    assert old_link["redirected_from"] == duplicate["slug"]
    # What people searched for is not lost: the duplicate's names became aliases.
    aliases = {
        a["alias"] for a in staff.get(f"/admin/catalog/products/{survivor['id']}").json()["aliases"]
    }
    assert aliases == {"Galaxy A16 Dual SIM", "ጋላክሲ A16 ባለሁለት ሲም", "A16 ስልክ"}


def test_merges_chain_to_the_final_survivor(staff: ApiClient, catalog: dict[str, Any]) -> None:
    a = make_product(staff, catalog, name_en="Phone A")
    b = make_product(staff, catalog, name_en="Phone B")
    c = make_product(staff, catalog, name_en="Phone C")
    assert (
        staff.post(
            f"/admin/catalog/products/{a['id']}/merge", json={"into_product_id": b["id"]}
        ).status_code
        == 200
    )
    assert (
        staff.post(
            f"/admin/catalog/products/{b['id']}/merge", json={"into_product_id": c["id"]}
        ).status_code
        == 200
    )
    for old in (a, b):
        page = ApiClient().get(f"/catalog/products/{old['slug']}").json()
        assert (page["id"], page["redirected_from"]) == (c["id"], old["slug"])
    # A now points straight at C.
    assert staff.get(f"/admin/catalog/products/{a['id']}").json()["merged_into_id"] == c["id"]


def test_merge_rules(staff: ApiClient, catalog: dict[str, Any]) -> None:
    a = make_product(staff, catalog, name_en="Phone A")
    draft = make_product(staff, catalog, name_en="Phone Draft", status="draft")
    b = make_product(staff, catalog, name_en="Phone B")

    def merge(source: str, into: str) -> Any:
        return staff.post(f"/admin/catalog/products/{source}/merge", json={"into_product_id": into})

    assert error_code(merge(a["id"], a["id"])) == "merge_into_self"
    assert error_code(merge(a["id"], draft["id"])) == "merge_target_not_approved"
    assert (merge(a["id"], MISSING).status_code, error_code(merge(MISSING, a["id"]))) == (
        404,
        "product_not_found",
    )
    assert merge(a["id"], b["id"]).status_code == 200
    assert error_code(merge(a["id"], b["id"])) == "product_already_merged"
    # A merged product can no longer be edited or archived.
    edit = staff.put(
        f"/admin/catalog/products/{a['id']}/text", json={"name_am": "x", "name_en": "x"}
    )
    assert (edit.status_code, error_code(edit)) == (409, "product_not_editable")
    assert (
        error_code(staff.post(f"/admin/catalog/products/{a['id']}/archive", json={}))
        == "product_not_editable"
    )


# ------------------------------------------------------------ restricted goods


def test_the_restricted_goods_list_blocks_listings(
    db: DbSession, catalog: dict[str, Any], staff: ApiClient
) -> None:
    for term in ("rum", "ሠይፍ"):
        assert (
            staff.post(
                "/admin/catalog/restricted-terms", json={"term": term, "reason": "restricted"}
            ).status_code
            == 201
        )

    blocked = staff.post(
        "/admin/catalog/products", json=phone_body(catalog, name_en="Dark Rum 750ml")
    )
    assert (blocked.status_code, error_code(blocked)) == (422, "restricted_goods")
    assert blocked.json()["error"]["details"] == {"term": "rum"}
    # Letter case and same-sound Amharic letters cannot be used to slip past the list.
    assert (
        error_code(
            staff.post(
                "/admin/catalog/products", json=phone_body(catalog, description_en="contains RUM")
            )
        )
        == "restricted_goods"
    )
    assert (
        error_code(
            staff.post("/admin/catalog/products", json=phone_body(catalog, name_am="ትልቅ ሰይፍ"))
        )
        == "restricted_goods"
    )
    # Whole words only: "drum" is not "rum".
    assert (
        staff.post(
            "/admin/catalog/products", json=phone_body(catalog, name_en="Drum Kit")
        ).status_code
        == 201
    )

    product = make_product(staff, catalog)
    edit = staff.put(
        f"/admin/catalog/products/{product['id']}/text",
        json={"name_am": "x", "name_en": "Rum cake"},
    )
    assert error_code(edit) == "restricted_goods"

    terms = staff.get("/admin/catalog/restricted-terms").json()
    assert staff.delete(f"/admin/catalog/restricted-terms/{terms[0]['id']}").status_code == 200
    assert (
        error_code(staff.post("/admin/catalog/restricted-terms", json={"term": "ሰይፍ"}))
        == "term_exists"
    )


def test_aliases(staff: ApiClient, catalog: dict[str, Any]) -> None:
    product = make_product(staff, catalog)
    added = staff.post(
        f"/admin/catalog/products/{product['id']}/aliases", json={"alias": "ሳምሱንግ A16"}
    )
    assert added.status_code == 201
    assert added.json()["script"] == "ethiopic"
    assert (
        staff.post(
            f"/admin/catalog/products/{product['id']}/aliases", json={"alias": "a sixteen"}
        ).json()["script"]
        == "latin"
    )
    # The same alias in a different spelling of the same sounds is a duplicate.
    assert (
        error_code(
            staff.post(
                f"/admin/catalog/products/{product['id']}/aliases", json={"alias": "ሣምሱንግ  a16"}
            )
        )
        == "alias_exists"
    )
    assert (
        staff.delete(
            f"/admin/catalog/products/{product['id']}/aliases/{added.json()['id']}"
        ).status_code
        == 200
    )
    assert (
        staff.delete(
            f"/admin/catalog/products/{product['id']}/aliases/{added.json()['id']}"
        ).status_code
        == 404
    )
    assert (
        staff.post(f"/admin/catalog/products/{MISSING}/aliases", json={"alias": "x"}).status_code
        == 404
    )


# ----------------------------------------------------------------- permissions


@pytest.mark.parametrize(
    ("role", "may_curate", "may_moderate"),
    [
        # Blueprint C.4: "Curate categories, attributes, brands and products"
        # and "Moderate listings and images".
        (StaffRole.SUPER_ADMIN, True, True),
        (StaffRole.CATALOGUE, True, True),
        (StaffRole.OPERATIONS, False, True),
        (StaffRole.SUPPORT, False, False),
        (StaffRole.FINANCE, False, False),
    ],
)
def test_only_the_roles_the_blueprint_names_may_curate(
    db: DbSession, role: StaffRole, may_curate: bool, may_moderate: bool
) -> None:
    member = staff_client(db, "0911000399", role)
    create = member.post(
        "/admin/catalog/categories", json={"slug": "toys", "name_am": "አሻንጉሊት", "name_en": "Toys"}
    )
    listing = member.get("/admin/catalog/products")
    term = member.post("/admin/catalog/restricted-terms", json={"term": "contraband"})
    assert create.status_code == (201 if may_curate else 403)
    assert listing.status_code == (200 if may_curate else 403)
    assert term.status_code == (201 if may_moderate else 403)
    if not may_curate:
        assert error_code(create) == "permission_denied"


def test_customers_and_visitors_cannot_curate(catalog: dict[str, Any]) -> None:
    customer = ApiClient()
    customer.sign_in("0911234567")
    assert (
        error_code(customer.post("/admin/catalog/products", json=phone_body(catalog)))
        == "staff_only"
    )
    assert customer.get("/admin/catalog/products").status_code == 403
    assert ApiClient().post("/admin/catalog/products", json=phone_body(catalog)).status_code == 401
    assert ApiClient().get("/admin/catalog/restricted-terms").status_code == 401


def test_curation_is_audited(staff: ApiClient, catalog: dict[str, Any], db: DbSession) -> None:
    a = make_product(staff, catalog, status="draft")
    b = make_product(staff, catalog)
    staff.post(f"/admin/catalog/products/{a['id']}/approve")
    staff.post(f"/admin/catalog/products/{a['id']}/merge", json={"into_product_id": b["id"]})
    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.target_id == a["id"]).order_by(AuditLog.occurred_at)
    ).all()
    assert actions == ["product.create", "product.approve", "product.merge"]
    approve = db.scalars(select(AuditLog).where(AuditLog.action == "product.approve")).one()
    assert (approve.before, approve.after["status"]) == ({"status": "draft"}, "approved")
    assert approve.actor_type == "staff"


def test_staff_list_products_by_status(staff: ApiClient, catalog: dict[str, Any]) -> None:
    make_product(staff, catalog, name_en="Live Phone")
    make_product(staff, catalog, name_en="Draft Phone", status="draft")
    assert {r["name"] for r in staff.get("/admin/catalog/products").json()} == {
        "Live Phone",
        "Draft Phone",
    }
    assert [
        r["name"] for r in staff.get("/admin/catalog/products", params={"status": "draft"}).json()
    ] == ["Draft Phone"]
    assert staff.get("/admin/catalog/products", params={"status": "bogus"}).status_code == 422
