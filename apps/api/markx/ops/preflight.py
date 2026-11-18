"""The pre-deployment check (D-091): `python -m markx.ops.preflight`.

Run inside the new release's image, with the server's real configuration,
before any container of that release takes traffic:

    docker compose ... run --rm --no-deps api python -m markx.ops.preflight

It answers, in words and never with a value:

1. Does the configuration pass every rule a real server must pass
   (`markx/core/config.py`)? Each refused setting is named.
2. Does the database answer as the application role?
3. Is the schema the one this release expects? Before the one-time
   migration step a release with new migrations is `behind`; pass
   `--allow-pending-migrations` there, then run it again afterwards
   without the flag.
4. Do both file stores answer with MarkX's keys?

Exit 0 when everything holds, 1 when a check fails, 2 when the
configuration itself is refused. It changes nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m markx.ops.preflight", description=__doc__)
    parser.add_argument(
        "--allow-pending-migrations",
        action="store_true",
        help="accept a schema that is behind this release (before the migration step)",
    )
    parser.add_argument(
        "--config-only",
        action="store_true",
        help="check the configuration only; reach no database and no file store",
    )
    arguments = parser.parse_args(argv)

    try:
        from markx.core.config import get_config

        config = get_config()
    except ValidationError as exc:
        _say("configuration: REFUSED")
        for error in exc.errors(include_input=False, include_url=False):
            # The messages name settings, never their values (hide_input_in_errors).
            _say(f"  - {error['msg'].removeprefix('Value error, ')}")
        return 2

    _say(f"configuration: accepted (MARKX_ENV={config.env})")
    for warning in config.startup_warnings():
        _say(f"  warning: {warning}")
    if not config.is_real_environment:
        _say("  note: not a real environment; staging and production rules were not applied")
    if arguments.config_only:
        return 0

    from markx.ops.health import check_database, storage_probe

    database, schema = check_database()
    storage = storage_probe.state()
    _say(f"database: {database}")
    _say(f"schema: {schema}")
    _say(f"file storage: {storage}")

    ok = database == "up" and storage != "down"
    if schema != "current":
        if schema == "behind" and arguments.allow_pending_migrations:
            _say("  note: migrations are pending; run the one-time migration step next")
        else:
            ok = False
            if schema == "ahead":
                _say("  the database is newer than this release: do not start it")
    _say("preflight: PASSED" if ok else "preflight: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
