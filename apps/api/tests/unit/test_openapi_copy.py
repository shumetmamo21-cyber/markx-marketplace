"""The OpenAPI copy check (D-061): additions pass, every change fails."""

from __future__ import annotations

import copy as copying
import json
from pathlib import Path
from typing import Any

from scripts.check_openapi_copy import compare, main

API_ROOT = Path(__file__).parent.parent.parent
WEB_COPY = API_ROOT.parent / "web" / "src" / "lib" / "api" / "openapi.json"
BACKEND_COPY = API_ROOT / "openapi.json"


def _description() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "MarkX API", "version": "0.1.0"},
        "paths": {
            "/api/v1/search": {
                "get": {"operationId": "search", "responses": {"200": {"description": "OK"}}}
            }
        },
        "components": {"schemas": {"SearchOut": {"type": "object", "properties": {}}}},
    }


def test_an_identical_copy_has_no_problems_and_no_additions() -> None:
    assert compare(_description(), _description()) == ([], [])


def test_new_routes_methods_and_schemas_are_additions_not_problems() -> None:
    current = _description()
    current["paths"]["/api/v1/admin/ops"] = {"get": {"responses": {}}}
    current["paths"]["/api/v1/search"]["post"] = {"responses": {}}
    current["components"]["schemas"]["OpsOut"] = {"type": "object"}
    problems, additions = compare(_description(), current)
    assert problems == []
    assert additions == [
        "GET /api/v1/admin/ops",
        "POST /api/v1/search",
        "components.schemas.OpsOut",
    ]


def test_every_change_to_what_the_copy_has_is_a_problem() -> None:
    copy = _description()
    changed = copying.deepcopy(copy)
    changed["paths"]["/api/v1/search"]["get"]["responses"]["429"] = {"description": "Busy"}
    changed["components"]["schemas"]["SearchOut"]["properties"]["extra"] = {"type": "string"}
    changed["info"]["version"] = "0.2.0"
    problems, _ = compare(copy, changed)
    assert problems == [
        "top-level 'info' differs",
        "GET /api/v1/search changed",
        "components.schemas.SearchOut changed",
    ]
    gone = copying.deepcopy(copy)
    del gone["paths"]["/api/v1/search"]
    del gone["components"]["schemas"]["SearchOut"]
    problems, _ = compare(copy, gone)
    assert problems == ["path /api/v1/search is gone", "components.schemas.SearchOut is gone"]


def test_exact_mode_refuses_additions(tmp_path: Path, capsys: Any) -> None:
    stale = tmp_path / "openapi.json"
    description = json.loads(BACKEND_COPY.read_text(encoding="utf-8"))
    removed = sorted(description["paths"])[0]
    del description["paths"][removed]
    stale.write_text(json.dumps(description), encoding="utf-8")
    assert main([str(stale)]) == 0  # an older copy is still true
    assert main(["--exact", str(stale)]) == 1  # but not the back end's own
    assert f"not in {stale}" in capsys.readouterr().out


def test_the_back_end_description_is_current() -> None:
    """`apps/api/openapi.json` must equal the API exactly. After an API change:
    `uv run python -m scripts.export_openapi openapi.json`."""
    assert main(["--exact", str(BACKEND_COPY)]) == 0


def test_the_web_app_copy_is_still_true() -> None:
    """The web app's copy may lag behind additions, never behind changes."""
    assert main([str(WEB_COPY)]) == 0
