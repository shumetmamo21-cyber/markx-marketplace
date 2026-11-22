"""Where a shop's logo lives (blueprint S-03, D.4; D-106).

A shop uploads its own logo; it is drawn again as one WebP file in the public
store, the key kept in `stores.logo_key`. This module names that file, so the
service that writes it, the backup that copies it (`backup/references.py`) and
the copy tool agree on one key.
"""

from __future__ import annotations

# PROVISIONAL (P-106-5): a logo is drawn at most 256 pixels wide or high, in
# at most 40 KB.
LOGO_SIDE = 256
LOGO_MAX_BYTES = 40_000


def logo_file(logo_key: str) -> str:
    """The public file of a logo whose key is `logo_key`."""
    return f"{logo_key}-{LOGO_SIDE}.webp"
