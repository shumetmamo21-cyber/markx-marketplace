"""Alerts sent straight to the staff Telegram group, without the database
(BK-4, D-105).

    python -m markx.ops.notify test
        A test alert. Exit 0 only when the Telegram group accepted it; exit 1
        when alerts are switched off (the alert went to the log only, so NO
        PERSON WAS TOLD) or Telegram refused it.
    python -m markx.ops.notify send --key KEY --severity critical|warning \\
            --state opened|resolved --text TEXT
        One operational alert, for what runs outside the application: the
        server's container watch (`deploy.sh watch`), which sees a container
        that stays unhealthy or stopped even when the database or the worker
        is the one that is down.

The worker's watch sends its alerts through the outbox (`ops.service`),
which needs the database. These do not: they go to the same group through
the same bot, at once (`ops.alerts.get_alert_sender`). The group is the
founder's choice (F-18): until `MARKX_ALERT_TELEGRAM_CHAT_ID` is set, alerts
reach the log only and this command says so. Texts name containers, keys and
counts, never a person, a phone number or an address.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from markx.core.config import get_config
from markx.ops.alerts import TelegramAlertSender, get_alert_sender

MAX_TEXT = 500
EXIT_NOT_DELIVERED = 1


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _deliver(*, text: str, severity: str, state: str, key: str) -> int:
    sender = get_alert_sender()
    one_line = " ".join(text.split())[:MAX_TEXT]
    try:
        sender.send(text=one_line, severity=severity, state=state, key=key)
    except Exception as exc:  # what Telegram or the network answered; never the token
        _say(f"NOT DELIVERED: the Telegram alert group did not accept it ({type(exc).__name__})")
        return EXIT_NOT_DELIVERED
    if isinstance(sender, TelegramAlertSender):
        _say("delivered to the staff Telegram alert group")
        return 0
    _say(
        "NOT DELIVERED TO ANY PERSON: alerts are switched off, so this went to the log only. "
        "Set MARKX_TELEGRAM_BOT_TOKEN and MARKX_ALERT_TELEGRAM_CHAT_ID once the founder's "
        "alert group exists (F-18; docs/runbooks/backup-and-restore.md, 'Alerts')."
    )
    return EXIT_NOT_DELIVERED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m markx.ops.notify", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("test", help="send a test alert to the staff Telegram group")
    send = sub.add_parser("send", help="send one operational alert")
    send.add_argument("--key", required=True)
    send.add_argument("--severity", choices=["critical", "warning"], default="critical")
    send.add_argument("--state", choices=["opened", "resolved"], default="opened")
    send.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    if args.command == "test":
        env = get_config().env
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        return _deliver(
            text=f"TEST ALERT from MarkX {env}, {stamp}. If you can read this on your phone, "
            "alerts reach you. Nothing is wrong.",
            severity="warning", state="opened", key="ops.test_alert",
        )  # fmt: skip
    text = args.text if args.state == "opened" else f"Resolved: {args.text}"
    return _deliver(text=text, severity=args.severity, state=args.state, key=args.key)


if __name__ == "__main__":
    sys.exit(main())
