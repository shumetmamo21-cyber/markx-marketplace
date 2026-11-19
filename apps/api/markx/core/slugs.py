"""URL slugs: lowercase Latin letters and digits separated by single hyphens."""

from __future__ import annotations

import re
import unicodedata

_NOT_SLUG = re.compile(r"[^a-z0-9]+")
MAX_SLUG_LENGTH = 80


def slugify(text: str) -> str:
    """Best-effort slug from Latin text. Returns "" when nothing usable remains,
    for example when the text is entirely Amharic."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _NOT_SLUG.sub("-", ascii_text.lower()).strip("-")[:MAX_SLUG_LENGTH].strip("-")
