"""The outside heartbeat (BK-4, D-105): a dead man's switch.

Every alert MarkX raises is raised ON the server. If the server is lost, its
database stops or its backup service dies, nothing on it can say so. So,
after each VERIFIED backup set, the backup service calls one web address at
an outside monitoring service (`MARKX_BACKUP_HEARTBEAT_URL`). That service
expects the call about once a day; when it stops coming, IT alerts the
founder, whatever happened to the server.

- **Off until the founder chooses a monitor (F-18).** Unset means no call is
  ever made; the service says so when it starts, and `deploy.sh alert-test`
  reports it.
- The address usually holds a secret token, so it is treated as a secret:
  never logged, printed or recorded; only its host name is ever shown.
- On staging and production it must be https. A failed call never fails the
  backup (the set is good): it is logged and recorded in the run as
  `heartbeat: failed:...`, and the outside monitor alerts if calls stop.
- A call carries nothing: no body, no data, a plain GET.

PROVISIONAL (P-105-1): one call per verified set, the monitor expecting one a
day with a grace of a few hours (the runbook says how to set it up).
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from urllib.parse import urlsplit

logger = logging.getLogger("markx.backup.heartbeat")
ATTEMPTS = 2


def host_of(url: str) -> str:
    return urlsplit(url).hostname or "?"


def ping(url: str | None, *, timeout: float) -> str:
    """Call the heartbeat address. Returns "off", "sent" or "failed:<why>"
    (the why is an HTTP status or an error type, never the address)."""
    if not url:
        return "off"
    why = "unknown"
    for _ in range(ATTEMPTS):
        request = urllib.request.Request(  # noqa: S310  (https enforced on real servers)
            url, method="GET", headers={"User-Agent": "markx-backup-heartbeat"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
                if 200 <= answer.status < 300:
                    logger.info("outside heartbeat sent", extra={"host": host_of(url)})
                    return "sent"
                why = f"http_{answer.status}"
        except urllib.error.HTTPError as exc:
            why = f"http_{exc.code}"
        except (OSError, ValueError) as exc:
            why = type(exc).__name__
    logger.error("the outside heartbeat could not be sent", extra={"host": host_of(url),
                                                                   "error_code": why})  # fmt: skip
    return f"failed:{why}"
