"""Text tools for Amharic search (blueprint F.7).

Amharic has several letters for one sound, and people also type Amharic in
Latin letters with free spelling. Two tools make those forms meet:

* normalisation merges same-sound letters, so ሰላም and ሠላም index identically;
* skeleton keys keep only the consonants, so "silk", "selk", "slk" and ስልክ
  all reduce to "slk".

The letter rules are a starting point. A native speaker reviews them before
launch (blueprint P8, founder inputs).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

Script = Literal["ethiopic", "latin"]

ETHIOPIC_START = 0x1200
ETHIOPIC_END = 0x137F

# Source A also merges the ኸ series into ሀ. The blueprint asks a native speaker
# to confirm that rule first, so it stays off until they do.
MERGE_KH_SERIES = False


def _series(source_base: int, target_base: int, orders: int) -> dict[int, int]:
    return {source_base + i: target_base + i for i in range(orders)}


def _build_merge_table() -> dict[int, int]:
    table: dict[int, int] = {}
    table |= _series(0x1210, 0x1200, 8)  # ሐ series -> ሀ series
    table |= _series(0x1280, 0x1200, 8)  # ኀ series -> ሀ series
    table |= _series(0x1220, 0x1230, 8)  # ሠ series -> ሰ series
    table |= _series(0x12D0, 0x12A0, 7)  # ዐ series -> አ series
    table |= _series(0x1340, 0x1338, 7)  # ፀ series -> ጸ series
    if MERGE_KH_SERIES:
        table |= _series(0x12B8, 0x1200, 7)  # ኸ series -> ሀ series
    # ሃ and ሀ, and ኣ and አ, are pronounced alike in Amharic.
    single = {0x1203: 0x1200, 0x12A3: 0x12A0}
    # Compose, so that ኃ -> ሃ -> ሀ and ዓ -> ኣ -> አ happen in one pass.
    return {src: single.get(dst, dst) for src, dst in table.items()} | single


_MERGE_TABLE = _build_merge_table()
_NOT_WORD = re.compile(r"[^\w]+", re.UNICODE)
_SPACES = re.compile(r"\s+")


def is_ethiopic_char(char: str) -> bool:
    return ETHIOPIC_START <= ord(char) <= ETHIOPIC_END


def detect_script(text: str) -> Script:
    return "ethiopic" if any(is_ethiopic_char(c) for c in text) else "latin"


def merge_same_sound_letters(text: str) -> str:
    return text.translate(_MERGE_TABLE)


def normalize_text(text: str) -> str:
    """The canonical form stored in search documents and applied to queries.

    NFC, lower-cased Latin, same-sound Ethiopic letters merged, every run of
    punctuation (Ethiopic ፡ ። ፣ included) turned into one space.
    """
    text = unicodedata.normalize("NFC", text).lower()
    text = merge_same_sound_letters(text)
    text = _NOT_WORD.sub(" ", text).replace("_", " ")
    return _SPACES.sub(" ", text).strip()


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return normalized.split(" ") if normalized else []


# One Latin consonant code per Ethiopic row of eight code points, indexed by
# (code point - 0x1200) // 8. Ejectives fold into their plain partners, because
# Latin spellings do not distinguish them. Vowel carriers (አ, ዐ) contribute
# nothing, and neither do the glides ወ and የ: in loanwords they usually spell a
# vowel sound (ራውተር "router", ኖኪያ "nokia"), which Latin typing drops.
# "C" is the ች sound; it is written as "c" only once plain Latin c is resolved.
_ROW_CONSONANTS = (
    "h", "l", "h", "m", "s", "r", "s", "sh",  # ሀ ለ ሐ መ ሠ ረ ሰ ሸ
    "k", "k", "k", "k", "b", "v", "t", "C",  # ቀ ቈ ቐ ቘ በ ቨ ተ ቸ
    "h", "h", "n", "n", "", "k", "k", "h",  # ኀ ኈ ነ ኘ አ ከ ኰ ኸ
    "h", "", "", "z", "z", "", "d", "d",  # ዀ ወ ዐ ዘ ዠ የ ደ ዸ
    "j", "g", "g", "g", "t", "C", "p", "s",  # ጀ ገ ጐ ጘ ጠ ጨ ጰ ጸ
    "s", "f", "p",  # ፀ ፈ ፐ
)  # fmt: skip

# Applied in order to Latin text before vowels are dropped.
_LATIN_UNIFY: tuple[tuple[str, str], ...] = (
    ("tch", "C"),
    ("ch", "C"),
    ("ck", "k"),
    ("ph", "f"),
    ("ts", "s"),
    ("tz", "s"),
    ("ny", "n"),
    ("gn", "n"),
    ("zh", "z"),
    ("q", "k"),
    ("x", "ks"),
)
# A plain Latin c is /s/ before e, i or y ("cell") and /k/ otherwise ("tecno").
_SOFT_C = re.compile(r"c(?=[eiy])")
# Vowels, plus the glides w and y, carry no skeleton information.
_DROPPED = frozenset("aeiouwy")
MIN_SKELETON_LENGTH = 2


def _collapse_doubles(text: str) -> str:
    out: list[str] = []
    for char in text:
        if not out or out[-1] != char:
            out.append(char)
    return "".join(out)


def skeleton_key(word: str) -> str | None:
    """Consonant skeleton of one word, or None when it is too short to be useful.

    Words containing digits (model codes such as "a16") have no skeleton: they
    are matched exactly or by prefix instead.
    """
    word = normalize_text(word)
    if not word or " " in word or any(c.isdigit() for c in word):
        return None

    latin_parts: list[str] = []
    for char in word:
        if is_ethiopic_char(char):
            row = (ord(char) - ETHIOPIC_START) // 8
            latin_parts.append(_ROW_CONSONANTS[row] if row < len(_ROW_CONSONANTS) else "")
        elif "a" <= char <= "z":
            latin_parts.append(char)
        # anything else (other scripts) carries no skeleton information

    if detect_script(word) == "latin":
        latin = "".join(latin_parts)
        for source, target in _LATIN_UNIFY:
            latin = latin.replace(source, target)
        latin = _SOFT_C.sub("s", latin).replace("c", "k")
        latin = "".join(c for c in latin if c not in _DROPPED)
    else:
        # Ethiopic syllables already map to bare consonants.
        latin = "".join(latin_parts)

    key = _collapse_doubles(latin.replace("C", "c"))
    return key if len(key) >= MIN_SKELETON_LENGTH else None


def skeleton_keys(text: str) -> list[str]:
    """Distinct skeleton keys for every word in the text, in first-seen order."""
    seen: dict[str, None] = {}
    for token in tokenize(text):
        key = skeleton_key(token)
        if key is not None:
            seen.setdefault(key, None)
    return list(seen)
