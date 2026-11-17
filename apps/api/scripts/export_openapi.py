"""Write the API's OpenAPI description, for the web app's generated types
(blueprint F.5). CI regenerates it and fails if the committed copy differs.

    cd apps/api && uv run python -m scripts.export_openapi ../web/src/lib/api/openapi.json
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
