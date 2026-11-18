"""The worker's loop (blueprint F.8). Start it with `python -m markx.worker`.

One pass (`run_once`) runs every scheduled job that is due and then drains
the outbox. The process repeats that pass until it is told to stop. Any number
of workers may run side by side; the database decides who does what.

The running worker drains at most one batch (100 messages) per pass, so under
a backlog the scheduled jobs still run every few seconds; when a batch was
full it starts the next pass at once. `--once` drains everything that is due
(D-082).
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from markx.core.config import get_config
from markx.core.logging import configure_logging
from markx.worker import jobs as scheduled
from markx.worker import outbox

logger = logging.getLogger("markx.worker")


@dataclass(frozen=True, slots=True)
class PassReport:
    jobs: list[scheduled.JobOutcome]
    outbox: outbox.DrainReport
    # Why the outbox could not be drained at all, if it could not (D-079).
    drain_error: str | None = None

    @property
    def ok(self) -> bool:
        """Every due job ran and the outbox was drained. A message that failed
        and will be retried is the outbox working, not the pass failing."""
        return self.drain_error is None and all(job.ok for job in self.jobs)


def run_once(
    now: datetime | None = None,
    *,
    jobs: Sequence[scheduled.Job] = scheduled.JOBS,
    handlers: Mapping[str, outbox.Handler] = outbox.HANDLERS,
    outbox_limit: int | None = outbox.DEFAULT_BATCH,
) -> PassReport:
    """One pass. `now` is passed in, so tests move time instead of sleeping.

    Without it, the outbox is drained as of the moment the jobs finished: a
    message a job queued in this pass (an alert, say) is stamped with the
    database's time inside the job, after the pass began, and still goes out
    in this pass (D-082). `outbox_limit=None` drains everything due."""
    outcomes = scheduled.run_due_jobs(now or datetime.now(UTC), jobs)
    try:
        drained = outbox.drain(now or datetime.now(UTC), limit=outbox_limit, handlers=handlers)
    except Exception as exc:
        # Only the dispatcher's own bookkeeping can raise here (the database
        # went away). A failing handler is caught per row.
        logger.exception("could not drain the outbox")
        return PassReport(
            jobs=outcomes, outbox=outbox.DrainReport(), drain_error=f"{type(exc).__name__}: {exc}"
        )
    return PassReport(jobs=outcomes, outbox=drained)


# A pass that has not finished for this long means the loop is hung (D-091).
# Generous on purpose: one pass may render pictures or rebuild search.
HEARTBEAT_STALE_AFTER_SECONDS = 300.0


def touch_heartbeat(path: Path | None) -> None:
    """Record that a pass just finished. Never stops the worker: a full or
    read-only disk is reported by the container check, not by a crash."""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except OSError:
        logger.warning("could not write the worker heartbeat file", exc_info=True)


def heartbeat_is_fresh(path: Path, *, now: float | None = None) -> bool:
    """Whether the last pass finished within HEARTBEAT_STALE_AFTER_SECONDS."""
    try:
        modified = path.stat().st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - modified <= HEARTBEAT_STALE_AFTER_SECONDS


def run_forever(stop: threading.Event | None = None) -> None:
    config = get_config()
    stop = stop or threading.Event()
    logger.info("worker started", extra={"poll_seconds": config.worker_poll_seconds})
    touch_heartbeat(config.worker_heartbeat_file)
    while not stop.is_set():
        report = run_once()
        touch_heartbeat(config.worker_heartbeat_file)
        # A full batch means more is waiting: go again without the pause.
        if report.outbox.handled < outbox.DEFAULT_BATCH:
            stop.wait(config.worker_poll_seconds)
    logger.info("worker stopped")


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m markx.worker", description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="run the due jobs, handle every due outbox message, and exit",
    )
    parser.add_argument(
        "--check-heartbeat",
        action="store_true",
        help="exit 0 if the running worker finished a pass recently (a container "
        "health check; needs MARKX_WORKER_HEARTBEAT_FILE), else 1",
    )
    arguments = parser.parse_args(argv)

    if arguments.check_heartbeat:
        path = get_config().worker_heartbeat_file
        return 0 if path is not None and heartbeat_is_fresh(path) else 1

    configure_logging(get_config().log_level)
    for warning in get_config().startup_warnings():
        logger.warning(warning)
    if arguments.once:
        # Everything that is due, however many batches that is (D-082).
        report = run_once(outbox_limit=None)
        logger.info(
            "worker pass finished",
            extra={
                "jobs": [o.name for o in report.jobs],
                "outbox_done": report.outbox.done,
                "outbox_retried": report.outbox.retried,
                "outbox_failed": report.outbox.failed,
                "failed_jobs": [o.name for o in report.jobs if not o.ok],
                "drain_error": report.drain_error,
            },
        )
        # A pass that could not do its work says so to whoever started it (a
        # script, a scheduler, a container check): exit 1 (D-079).
        return 0 if report.ok else 1
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        # Finish the row in hand, then leave: nothing is cut off mid-transaction.
        signal.signal(signum, lambda *_: stop.set())
    run_forever(stop)
    return 0
