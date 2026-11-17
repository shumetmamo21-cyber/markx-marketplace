"""The search evaluator (blueprint P8 criteria, D-054).

Every case here is SYNTHETIC, written to test the evaluator itself. None is a
real customer query, and no result here says how well search works.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from markx.search import evaluation
from markx.search.evaluation import Case, EvaluationFileError, evaluate, load_cases
from markx.search.models import SearchQuery
from tests.api.test_search import Shelf

SYNTHETIC = Path(__file__).parent.parent / "fixtures" / "search_eval_synthetic.csv"
TEMPLATE = Path(__file__).parent.parent.parent / "search_eval" / "golden_queries.template.csv"


@pytest.fixture
def shelf(db: DbSession) -> Shelf:
    return Shelf(db)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "queries.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_template_is_empty_and_valid() -> None:
    assert load_cases(TEMPLATE) == []


def test_the_file_is_checked_line_by_line(tmp_path: Path) -> None:
    cases = load_cases(SYNTHETIC)
    assert [(c.query, c.kind) for c in cases][:2] == [
        ("ሳምሰንግ", "amharic"),
        ("samsang", "latin_amharic"),
    ]
    assert cases[2].expected == ("samsung-galaxy-a16", "samsung-galaxy-a16-5g")
    assert cases[0].line == 5  # notes count as lines, so errors point at the right one

    header = "query,expected,kind,source\n"
    bad = {
        "": "no header row",
        "q,e,k,s\n": "the header must be",
        header + "phone,x,english\n": "expected 4 columns",
        header + " ,x,english,shop\n": "the query is empty",
        header + "phone, | ,english,shop\n": "no expected product",
        header + "phone,x,french,shop\n": "kind must be one of",
        header + "phone,x,english, \n": "say where the query came from",
    }
    for text, message in bad.items():
        with pytest.raises(EvaluationFileError, match=message):
            load_cases(_write(tmp_path, text))
    with pytest.raises(EvaluationFileError, match="line 3"):
        load_cases(_write(tmp_path, "# a note\n" + header + "phone,x,french,shop\n"))


def test_the_evaluator_scores_hits_misses_and_unknown_products(shelf: Shelf, db: DbSession) -> None:
    report = evaluate(db, load_cases(SYNTHETIC))
    assert (report.cases, report.hits, report.top) == (6, 4, 3)
    assert report.hit_rate == round(4 / 6, 4)
    assert report.by_kind == {
        "amharic": {"cases": 2, "hits": 2, "hit_rate": 1.0},
        "english": {"cases": 3, "hits": 1, "hit_rate": round(1 / 3, 4)},
        "latin_amharic": {"cases": 1, "hits": 1, "hit_rate": 1.0},
    }
    assert [(m.query, m.got) for m in report.misses] == [("iphone 15", []), ("laptop", [])]
    # A slug that names no searchable product is reported, not silently a miss.
    assert [p["slugs"] for p in report.unknown_products] == [
        ["samsung-galaxy-a16-5g"],
        ["apple-iphone-15"],
    ]
    assert report.valid_set is False
    assert report.criteria_met is False
    assert any("6 of the 100" in note for note in report.notes)
    assert report.p95_ms > 0
    # Scoring writes nothing: no query reaches the search log.
    assert db.scalar(select(func.count()).select_from(SearchQuery)) == 0
    text = evaluation.format_report(report)
    assert "CRITERIA NOT MET" in text
    assert "Miss, line 9 [english]: 'iphone 15'" in text


def test_a_full_set_can_meet_the_criteria(shelf: Shelf, db: DbSession) -> None:
    """A hundred SYNTHETIC cases (four queries repeated) only to show the
    arithmetic: a valid set at or above 85% in time passes; below, it fails."""
    good = [
        Case(line=i, query=q, expected=(slug,), kind=kind, source="synthetic")
        for i, (q, slug, kind) in enumerate(
            [
                ("ሳምሰንግ", shelf.samsung["slug"], "amharic"),
                ("samsung", shelf.samsung["slug"], "english"),
                ("tekno", shelf.tecno["slug"], "latin_amharic"),
                ("ቴክኖ", shelf.tecno["slug"], "amharic"),
            ]
            * 25
        )
    ]
    report = evaluate(db, good)
    assert (report.cases, report.hits, report.valid_set) == (100, 100, True)
    assert report.criteria_met is (report.p95_ms <= evaluation.TARGET_P95_MS)
    misses = [
        Case(line=200 + i, query="laptop", expected=(shelf.samsung["slug"],), kind="english",
             source="synthetic")
        for i in range(16)
    ]  # fmt: skip
    report = evaluate(db, good[:84] + misses)
    assert (report.cases, report.hits, report.hit_rate) == (100, 84, 0.84)
    assert report.criteria_met is False


def test_the_command_line(shelf: Shelf, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert evaluation.main([str(_write(tmp_path, "nope\n"))]) == 2
    assert "header must be" in capsys.readouterr().err
    assert evaluation.main([str(SYNTHETIC)]) == 1  # six cases: never a valid measurement
    out = capsys.readouterr().out
    assert "Queries: 6" in out
    assert "CRITERIA NOT MET" in out
    assert evaluation.main([str(SYNTHETIC), "--json"]) == 1
    assert '"valid_set": false' in capsys.readouterr().out
