"""Check that a copy of the API's OpenAPI description is still true (D-061).

The web app keeps its own copy (`apps/web/src/lib/api/openapi.json`) and
generates its types from it. While the back end and the web app are built by
separate sessions, the back end may add routes and schemas before the web app
regenerates its copy. This check therefore allows *additions* and refuses
every *change*:

* every path and method in the copy exists in the API with exactly the same
  definition (parameters, request body, responses, description);
* every schema in the copy exists in the API, unchanged;
* `openapi`, `info` and every other top-level section of the copy match.

Anything the API has and the copy lacks is listed, so the web app's owner
knows what to regenerate. The back end's own description,
`apps/api/openapi.json`, is checked strictly by `--exact` in CI: every API
change shows up there in review.

    uv run python -m scripts.check_openapi_copy ../web/src/lib/api/openapi.json
    uv run python -m scripts.check_openapi_copy --exact openapi.json

Exit status 0 when the copy is true (with or without additions), 1 when it
is not, 2 on a usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def compare(copy: dict[str, Any], current: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (problems, additions). A problem is anything in the copy that the
    current description changed or dropped; an addition is something new."""
    problems: list[str] = []
    additions: list[str] = []

    for key in sorted(set(copy) - {"paths", "components"}):
        if copy[key] != current.get(key):
            problems.append(f"top-level '{key}' differs")

    copy_paths: dict[str, Any] = copy.get("paths", {})
    current_paths: dict[str, Any] = current.get("paths", {})
    for path in sorted(copy_paths):
        if path not in current_paths:
            problems.append(f"path {path} is gone")
            continue
        for method, operation in sorted(copy_paths[path].items()):
            if method not in METHODS:
                if operation != current_paths[path].get(method):
                    problems.append(f"{path} '{method}' differs")
                continue
            now = current_paths[path].get(method)
            if now is None:
                problems.append(f"{method.upper()} {path} is gone")
            elif now != operation:
                problems.append(f"{method.upper()} {path} changed")
    for path in sorted(current_paths):
        for method in sorted(current_paths[path]):
            if method in METHODS and method not in copy_paths.get(path, {}):
                additions.append(f"{method.upper()} {path}")

    copy_components: dict[str, Any] = copy.get("components", {})
    current_components: dict[str, Any] = current.get("components", {})
    for section in sorted(copy_components):
        mine, theirs = copy_components[section], current_components.get(section, {})
        for name in sorted(mine):
            if name not in theirs:
                problems.append(f"components.{section}.{name} is gone")
            elif mine[name] != theirs[name]:
                problems.append(f"components.{section}.{name} changed")
    for section in sorted(current_components):
        for name in sorted(current_components[section]):
            if name not in copy_components.get(section, {}):
                additions.append(f"components.{section}.{name}")
    return problems, additions


def main(argv: list[str]) -> int:
    exact = "--exact" in argv
    paths = [arg for arg in argv if arg != "--exact"]
    if len(paths) != 1:
        sys.stderr.write("usage: python -m scripts.check_openapi_copy [--exact] PATH\n")
        return 2
    from markx.main import app

    current = json.loads(json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True))
    copy = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
    problems, additions = compare(copy, current)
    if exact and additions:
        problems += [f"not in {paths[0]}: {item}" for item in additions]
        additions = []
    for problem in problems:
        sys.stdout.write(f"DIFFERS  {problem}\n")
    if additions:
        sys.stdout.write(
            f"{paths[0]} is true for everything it has. The API has {len(additions)} "
            "addition(s) it lacks; regenerate it to use them:\n"
        )
        for item in additions:
            sys.stdout.write(f"  new  {item}\n")
    if problems:
        sys.stdout.write(
            f"{paths[0]} no longer matches the API. Regenerate it with "
            "`uv run python -m scripts.export_openapi PATH`.\n"
        )
        return 1
    if not additions:
        sys.stdout.write(f"{paths[0]} matches the API exactly.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
