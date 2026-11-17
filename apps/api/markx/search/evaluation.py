"""Scoring search against real queries (blueprint P8 completion criteria; D-054).

The P8 criteria: on a golden set of 100 real queries in Amharic, English and
Latin-letter Amharic, the right product is in the top three for 85%, and
search takes under 300 ms for 95% of queries. This module measures both
against whatever catalogue the configured database holds. It never writes:
queries are not logged and the session is rolled back.

The file is CSV, UTF-8, with a header row; lines starting with `#` are notes:

    query,expected,kind,source
    ሳምሰንግ ጋላክሲ,samsung-galaxy-a16,amharic,shop owner interview

* `query`    exactly what the person typed
* `expected` the slug of the product they meant; several slugs separated by
             `|` when any of them is a right answer
* `kind`     `amharic` (Ethiopic script), `english`, or `latin_amharic`
* `source`   where the query came from (who, when, how). Required: the
             criterion is about real queries, and the file must say whose.

    uv run python -m markx.search.evaluation path/to/queries.csv [--top 3] [--json]

Exit status: 0 when the criteria are met on a valid set, 1 when they are not
(or the set is too small to judge), 2 when the file cannot be read.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from markx.catalog.models import Product, ProductStatus
from markx.core.ethiopic import normalize_text
from markx.search import selectors

KINDS = ("amharic", "english", "latin_amharic")
COLUMNS = ("query", "expected", "kind", "source")
REQUIRED_CASES = 100
TARGET_HIT_RATE = 0.85
TARGET_P95_MS = 300.0


class EvaluationFileError(ValueError):
    """The file cannot be scored; the message names the line."""


@dataclass(frozen=True, slots=True)
class Case:
    line: int
    query: str
    expected: tuple[str, ...]
    kind: str
    source: str


@dataclass(slots=True)
class Outcome:
    line: int
    query: str
    kind: str
    expected: list[str]
    # 1-based position of the first right answer within `top`, or None.
    rank: int | None
    got: list[str]
    milliseconds: float


@dataclass(slots=True)
class Report:
    cases: int
    distinct_queries: int
    top: int
    hits: int
    hit_rate: float
    by_kind: dict[str, dict[str, float]]
    p95_ms: float
    max_ms: float
    # Expected slugs that name no searchable product: fix the file or the
    # catalogue; these cases count as misses.
    unknown_products: list[dict[str, Any]]
    misses: list[Outcome]
    valid_set: bool
    criteria_met: bool
    notes: list[str] = field(default_factory=list)


def load_cases(path: Path) -> list[Case]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvaluationFileError(f"{path}: cannot be read as UTF-8 text ({exc})") from exc
    rows = [
        (number, line)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not rows:
        raise EvaluationFileError(f"{path}: no header row")
    header_line = rows[0][0]
    reader = csv.reader([line for _, line in rows])
    parsed = list(reader)
    if tuple(column.strip() for column in parsed[0]) != COLUMNS:
        raise EvaluationFileError(
            f"{path}, line {header_line}: the header must be {','.join(COLUMNS)}"
        )
    cases = []
    for (number, _), values in zip(rows[1:], parsed[1:], strict=True):
        if len(values) != len(COLUMNS):
            raise EvaluationFileError(f"{path}, line {number}: expected {len(COLUMNS)} columns")
        query, expected, kind, source = (value.strip() for value in values)
        slugs = tuple(slug.strip() for slug in expected.split("|") if slug.strip())
        if not query:
            raise EvaluationFileError(f"{path}, line {number}: the query is empty")
        if not slugs:
            raise EvaluationFileError(f"{path}, line {number}: no expected product")
        if kind not in KINDS:
            raise EvaluationFileError(
                f"{path}, line {number}: kind must be one of {', '.join(KINDS)}"
            )
        if not source:
            raise EvaluationFileError(f"{path}, line {number}: say where the query came from")
        cases.append(Case(line=number, query=query, expected=slugs, kind=kind, source=source))
    return cases


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]


def evaluate(db: Session, cases: Sequence[Case], *, top: int = 3, language: str = "am") -> Report:
    """Run every case through the real search, as a buyer would, and score it.
    Nothing is written: the caller's session is rolled back afterwards."""
    searchable = set(
        db.scalars(select(Product.slug).where(Product.status == ProductStatus.APPROVED))
    )
    outcomes: list[Outcome] = []
    unknown: list[dict[str, Any]] = []
    for case in cases:
        missing = [slug for slug in case.expected if slug not in searchable]
        if missing:
            unknown.append({"line": case.line, "query": case.query, "slugs": missing})
        started = time.perf_counter()
        found = selectors.search(db, case.query, language=language, limit=top, log=False)
        elapsed = (time.perf_counter() - started) * 1000
        got = [card["slug"] for card in found["results"]]
        rank = next((i for i, slug in enumerate(got, start=1) if slug in case.expected), None)
        outcomes.append(
            Outcome(
                line=case.line, query=case.query, kind=case.kind, expected=list(case.expected),
                rank=rank, got=got, milliseconds=round(elapsed, 2),
            )
        )  # fmt: skip
    db.rollback()

    hits = sum(1 for outcome in outcomes if outcome.rank is not None)
    by_kind: dict[str, dict[str, float]] = {}
    for kind in KINDS:
        mine = [o for o in outcomes if o.kind == kind]
        if mine:
            kind_hits = sum(1 for o in mine if o.rank is not None)
            by_kind[kind] = {
                "cases": len(mine),
                "hits": kind_hits,
                "hit_rate": round(kind_hits / len(mine), 4),
            }
    times = [o.milliseconds for o in outcomes]
    hit_rate = round(hits / len(outcomes), 4) if outcomes else 0.0
    p95 = round(_p95(times), 2)
    notes = []
    # Two rows whose queries normalise alike run the same search: they are
    # one measurement, not two, and do not count twice towards the 100 (D-057).
    first_line: dict[str, int] = {}
    duplicates: list[tuple[int, int]] = []
    for case in cases:
        key = normalize_text(case.query)
        if key in first_line:
            duplicates.append((case.line, first_line[key]))
        else:
            first_line[key] = case.line
    distinct = len(first_line)
    for line, original in duplicates:
        notes.append(f"Line {line} searches the same as line {original}; it is counted once.")
    valid = distinct >= REQUIRED_CASES
    if not valid:
        notes.append(
            f"Not a valid P8 measurement: {distinct} of the {REQUIRED_CASES} real queries "
            "the criterion needs (a repeated query counts once)."
        )
    missing_kinds = [kind for kind in KINDS if kind not in by_kind]
    if missing_kinds:
        notes.append(f"No queries of kind: {', '.join(missing_kinds)}.")
    notes.append(
        "Times are measured around the whole search call (database and API code), "
        "so they are an upper bound on database time."
    )
    return Report(
        cases=len(outcomes),
        distinct_queries=distinct,
        top=top,
        hits=hits,
        hit_rate=hit_rate,
        by_kind=by_kind,
        p95_ms=p95,
        max_ms=round(max(times), 2) if times else 0.0,
        unknown_products=unknown,
        misses=[o for o in outcomes if o.rank is None],
        valid_set=valid,
        criteria_met=valid
        and not missing_kinds
        and hit_rate >= TARGET_HIT_RATE
        and p95 <= TARGET_P95_MS,
        notes=notes,
    )


def format_report(report: Report) -> str:
    lines = [
        f"Queries: {report.cases} ({report.distinct_queries} distinct)    right product in the top {report.top}: "
        f"{report.hits} ({report.hit_rate:.1%}; target {TARGET_HIT_RATE:.0%})",
        f"Time per search: 95% under {report.p95_ms:.1f} ms, slowest {report.max_ms:.1f} ms "
        f"(target {TARGET_P95_MS:.0f} ms)",
    ]
    for kind, figures in report.by_kind.items():
        lines.append(
            f"  {kind:<14} {int(figures['hits'])}/{int(figures['cases'])} "
            f"({figures['hit_rate']:.1%})"
        )
    for problem in report.unknown_products:
        lines.append(f"Line {problem['line']}: no searchable product {', '.join(problem['slugs'])}")
    for miss in report.misses:
        lines.append(
            f"Miss, line {miss.line} [{miss.kind}]: {miss.query!r} wanted "
            f"{'|'.join(miss.expected)}; got {', '.join(miss.got) or 'nothing'}"
        )
    lines += report.notes
    lines.append("CRITERIA MET" if report.criteria_met else "CRITERIA NOT MET")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score search against real queries (P8).")
    parser.add_argument("path", type=Path)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--lang", choices=("am", "en"), default="am")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.path)
    except EvaluationFileError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    from markx.core.db import session_scope

    with session_scope() as db:
        report = evaluate(db, cases, top=args.top, language=args.lang)
    if args.json:
        sys.stdout.write(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(format_report(report) + "\n")
    return 0 if report.criteria_met else 1


if __name__ == "__main__":
    raise SystemExit(main())
