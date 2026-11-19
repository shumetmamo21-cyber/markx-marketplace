"""Write the API's OpenAPI description (blueprint F.5).

The back end keeps its own copy, `apps/api/openapi.json`, which CI checks
exactly; the web app keeps another, from which it generates its types, and
CI checks that it is still true (D-061, `scripts/check_openapi_copy.py`).

    cd apps/api && uv run python -m scripts.export_openapi openapi.json
    cd apps/api && uv run python -m scripts.export_openapi ../web/src/lib/api/openapi.json  # web owner
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from markx.main import app


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: python -m scripts.export_openapi PATH\n")
        return 2
    text = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    Path(argv[0]).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
