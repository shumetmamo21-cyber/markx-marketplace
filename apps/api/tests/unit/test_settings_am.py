"""Every setting has its description in Amharic too (blueprint I.1; D-078)."""

from __future__ import annotations

import re

from markx.core.settings_am import DESCRIPTIONS_AM
from markx.core.settings_store import SETTINGS

ETHIOPIC = re.compile(r"[ሀ-፿]")


def test_every_setting_and_only_settings_have_an_amharic_description() -> None:
    assert set(DESCRIPTIONS_AM) == set(SETTINGS)


def test_each_amharic_description_is_written_in_ethiopic_script() -> None:
    for key, text in DESCRIPTIONS_AM.items():
        assert len(ETHIOPIC.findall(text)) >= 10, key
        assert text.strip() == text, key
        assert text.endswith("።"), key
