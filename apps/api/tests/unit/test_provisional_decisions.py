"""The founder's decisions F-01 to F-08 were answered provisionally, by the
engineer's guess at the founder's request (D-083). Each answer is marked in
the code with "PROVISIONAL (F-0n" so that nobody mistakes it for a confirmed
rule. When the founder confirms or changes one, record it as a D- entry,
remove its marker and its line here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

MARKX = Path(__file__).resolve().parents[2] / "markx"

WHERE = {
    "F-01": "core/storage.py",  # identity documents: a private R2 bucket
    "F-02": "accounts/permissions.py",  # transfer of ownership: back to Level 0
    "F-03": "sellers/service.py",  # a TIN has ten digits
    "F-04": "offers/service.py",  # every used item needs Level 2
    "F-05": "sellers/service.py",  # a rejected applicant needs a new invitation
    "F-06": "catalog/service.py",  # merging products: the survivor's offer stays
    "F-07": "offers/router.py",  # who may lift a takedown
    "F-08": "core/settings_store.py",  # how long search logs and counters are kept
}


@pytest.mark.parametrize(("decision", "path"), sorted(WHERE.items()))
def test_each_provisional_answer_is_marked_where_it_lives(decision: str, path: str) -> None:
    text = (MARKX / path).read_text(encoding="utf-8")
    assert f"PROVISIONAL ({decision}, D-083)" in text
    assert "BEFORE MARKX GOES LIVE" in text or "before going live" in text
