"""The worker's loop (blueprint F.8). Start it with `python -m markx.worker`.

One pass (`run_once`) runs every scheduled job that is due and then drains
the outbox. The process repeats that pass until it is told to stop. Any number
of workers may run side by side; the database decides who does what.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from markx.core.config import get_config
from markx.core.logging import configure_logging
from markx.worker import jobs as scheduled
from markx.worker import outbox

logger = logging.getLogger("markx.worker")


@dataclass(frozen=True, slots=True)
class PassReport:
    jobs: list[scheduled.JobOutcome]
    outbox: outbox.DrainReport


def run_once(
    now: datetime | None = None,
    *,
    jobs: Sequence[scheduled.Job] = scheduled.JOBS,
    handlers: Mapping[str, outbox.Handler] = outbox.HANDLERS,
    outbox_limit: int = outbox.DEFAULT_BATCH,
) -> PassReport:
    """One pass. `now` is passed in, so tests move time instead of sleeping."""
    now = now or datetime.now(UTC)
    outcomes = scheduled.run_due_jobs(now, jobs)
    try:
        drained = outbox.drain(now, limit=outbox_limit, handlers=handlers)
    except Exception:
        # Only the dispatcher's own bookkeeping can raise here (the database
        # went away). A failing handler is caught per row.
        logger.exception("could not drain the outbox")
        drained = outbox.DrainReport()
    return PassReport(jobs=outcomes, outbox=drained)


def run_forever(stop: threading.Event | None = None) -> None:
    config = get_config()
    stop = stop or threading.Event()
    logger.info("worker started", extra={"poll_seconds": config.worker_poll_seconds})
    while not stop.is_set():
        report = run_once()
        # A full batch means more is waiting: go again without the pause.
        if report.outbox.handled < outbox.DEFAULT_BATCH:
            stop.wait(config.worker_poll_seconds)
    logger.info("worker stopped")


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m markx.worker", description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    arguments = parser.parse_args(argv)

    configure_logging(get_config().log_level)
    if arguments.once:
        report = run_once()
        logger.info(
            "worker pass finished",
            extra={
                "jobs": [o.name for o in report.jobs],
                "outbox_done": report.outbox.done,
                "outbox_retried": report.outbox.retried,
                "outbox_failed": report.outbox.failed,
            },
        )
        return 0
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        # Finish the row in hand, then leave: nothing is cut off mid-transaction.
        signal.signal(signum, lambda *_: stop.set())
    run_forever(stop)
    return 0
