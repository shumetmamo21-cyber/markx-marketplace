"""The backup command line (D-094). Read docs/runbooks/backup-and-restore.md.

    python -m markx.backup keygen --out DIR        make the keys (once, off the server)
    python -m markx.backup run                     one backup set now
    python -m markx.backup serve                   the service: daily, with retries and retention
    python -m markx.backup check                   exit 0 if a verified set is fresh enough
    python -m markx.backup list                    the sets at the destination
    python -m markx.backup verify --set ID ...     check a set without writing anywhere
    python -m markx.backup restore --set ID ...    restore into a NEW database and empty stores
    python -m markx.backup prune [--execute]       retention (a dry run without --execute)
    python -m markx.backup drill ...               the recovery drill

Exit status: 0 success; 1 a failed, incomplete or refused operation;
2 a usage or settings error; 3 skipped because another backup is running.
Nothing secret is ever printed.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Any

from pydantic import ValidationError

from markx.backup import crypto
from markx.backup.config import BackupConfig
from markx.backup.database import PgServer
from markx.backup.destination import DestinationError, make_destination
from markx.backup.records import Recorder
from markx.backup.restore import FileTargets, list_sets, read_manifest, restore_set, verify_set
from markx.backup.retention import prune
from markx.backup.runner import (
    BackupContext,
    BackupOutcome,
    health,
    run_backup,
    run_with_retries,
    seconds_until,
)
from markx.backup.sources import make_source

logger = logging.getLogger("markx.backup")
EXIT_FAILED, EXIT_USAGE, EXIT_SKIPPED = 1, 2, 3


def say(text: str, *, file: Any = None, flush: bool = True) -> None:
    stream = file or sys.stdout
    stream.write(f"{text}\n")
    if flush:
        stream.flush()


def _default_bootstrap() -> Path:
    candidates = [
        Path(os.environ.get("MARKX_BACKUP_BOOTSTRAP_SCRIPT", "")),
        Path("/postgres/bootstrap.sh"),
    ]
    # In a checkout of the repository: infra/postgres/bootstrap.sh at its root.
    candidates += [
        parent / "infra" / "postgres" / "bootstrap.sh"
        for parent in Path(__file__).resolve().parents
    ]
    for candidate in candidates:
        if str(candidate) not in ("", ".") and candidate.is_file():
            return candidate
    raise SystemExit("cannot find infra/postgres/bootstrap.sh; set MARKX_BACKUP_BOOTSTRAP_SCRIPT")


def _config(*, service: bool) -> BackupConfig:
    try:
        config = BackupConfig()
    except ValidationError as exc:
        messages = "; ".join(str(e.get("msg", "")) for e in exc.errors())
        raise SystemExit(f"backup settings refused: {messages}") from None
    if service:
        problems = config.service_problems()
        if problems:
            raise SystemExit("backup settings refused: " + "; ".join(problems))
    return config


def _context(config: BackupConfig) -> BackupContext:
    if config.public_key_file is None or config.signing_key_file is None:
        raise SystemExit(
            "MARKX_BACKUP_PUBLIC_KEY_FILE and MARKX_BACKUP_SIGNING_KEY_FILE must be set"
        )
    try:
        recipient = crypto.load_recipient(config.public_key_file)
        signing = crypto.load_signing(config.signing_key_file)
    except crypto.BackupKeyError as exc:
        raise SystemExit(f"backup key refused: {exc}") from None
    server = PgServer.from_environment()
    return BackupContext(
        config=config, server=server, destination=make_destination(config),
        source=make_source(config), recipient=recipient, signing=signing,
        recorder=Recorder(server, config.database),
    )  # fmt: skip


def _keys(paths: list[str]) -> dict[str, crypto.RecoveryKey]:
    keys = {}
    for path in paths:
        key = crypto.load_recovery(Path(path))
        keys[key.key_id] = key
    return keys


def _signers(paths: list[str], config: BackupConfig | None = None) -> list[crypto.SignerKey]:
    signers = [crypto.load_signer(Path(p)) for p in paths]
    if not signers and config is not None and config.signing_key_file is not None:
        signers = [crypto.load_signing(config.signing_key_file).signer]
    if not signers:
        raise SystemExit("give --signer FILE (the signer public key kept with the recovery key)")
    return signers


# -- commands ---------------------------------------------------------------------------------


def cmd_keygen(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    keys = crypto.generate_keys()
    crypto.write_key_file(out / "recovery.key", crypto.encode_recovery(keys.recovery), secret=True)
    crypto.write_key_file(
        out / "backup-public.key", crypto.encode_recipient(keys.recovery.recipient), secret=False
    )
    crypto.write_key_file(out / "signing.key", crypto.encode_signing(keys.signing), secret=True)
    crypto.write_key_file(
        out / "signer-public.key", crypto.encode_signer(keys.signing.signer), secret=False
    )
    say(f"""keys written to {out}:
  recovery.key        SECRET. Keep OFF the server, in two separate safe places. Without it
                      no backup made with this key can ever be restored. (key {keys.recovery.key_id})
  backup-public.key   the server's: MARKX_BACKUP_PUBLIC_KEY_FILE. Not secret.
  signing.key         SECRET, the server's: MARKX_BACKUP_SIGNING_KEY_FILE (owner 999, mode 400).
  signer-public.key   not secret; keep a copy with recovery.key: a restore checks manifests
                      with it. (signer {keys.signing.key_id})
Remove recovery.key from this machine once it is stored safely.""")
    return 0


def _report_outcome(outcome: BackupOutcome) -> int:
    say(
        f"backup {outcome.status}: {outcome.backup_id}"
        + (f" ({outcome.error_code})" if outcome.error_code else "")
    )
    if outcome.status == "succeeded":
        return 0
    return EXIT_SKIPPED if outcome.status == "skipped" else EXIT_FAILED


def cmd_run(args: argparse.Namespace) -> int:
    config = _config(service=True)
    return _report_outcome(run_backup(_context(config)))


def _prune(config: BackupConfig, ctx: BackupContext, *, execute: bool) -> int:
    from markx.backup.runner import backup_lock

    with backup_lock(ctx.server, config.database, config.work_dir.resolve()) as held:
        if not held:
            say("retention skipped: a backup is running")
            return EXIT_SKIPPED
        plan = prune(
            ctx.destination, [ctx.signing.signer], now=datetime.now(UTC),
            retention_days=config.effective_retention_days,
            min_sets=config.effective_retention_min_sets,
            grace=timedelta(hours=config.blob_grace_hours), execute=execute,
        )  # fmt: skip
    verb = "deleted" if execute else "would delete"
    say(f"retention: keep {len(plan.keep)} sets; {verb} {len(plan.delete_sets)} sets and "
          f"{len(plan.delete_blobs)} blobs")  # fmt: skip
    for note in plan.notes:
        say(f"  note: {note}")
    for backup_id in plan.delete_sets:
        say(f"  {verb}: {backup_id}")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    config = _config(service=True)
    return _prune(config, _context(config), execute=args.execute)


_stop = False


def _on_term(signum: int, frame: FrameType | None) -> None:
    global _stop
    _stop = True
    say("backup service stopping after the current step", flush=True)


def _sleep(seconds: float) -> None:
    end = time.monotonic() + seconds
    while not _stop and time.monotonic() < end:
        time.sleep(min(5.0, max(0.0, end - time.monotonic())))


def cmd_serve(args: argparse.Namespace) -> int:
    config = _config(service=True)
    ctx = _context(config)
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    say(f"backup service: a set now, then daily at {config.hour_utc}:00 UTC, to "
          f"{ctx.destination.identity} ({'off-server' if ctx.destination.offsite else 'NOT off-server'})",
          flush=True)  # fmt: skip
    while not _stop:
        attempts = run_with_retries(
            lambda: run_backup(ctx), attempts=config.retry_attempts,
            delay_seconds=config.retry_delay_seconds, sleep=_sleep,
        )  # fmt: skip
        last = attempts.outcomes[-1]
        _report_outcome(last)
        if last.status == "succeeded":
            try:
                _prune(config, ctx, execute=True)
            except DestinationError as exc:
                logger.error(
                    "retention failed; nothing more was deleted", extra={"error_code": exc.reason}
                )
        _sleep(seconds_until(config.hour_utc, datetime.now(UTC)))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = _config(service=False)
    ok, why = health(config, datetime.now(UTC))
    say(why)
    return 0 if ok else EXIT_FAILED


def cmd_list(args: argparse.Namespace) -> int:
    config = _config(service=False)
    destination = make_destination(config)
    signers = _signers(args.signer, config)
    for backup_id in list_sets(destination):
        try:
            body = read_manifest(destination, backup_id, signers)
            files = body["files"]
            say(f"{backup_id}  {body['status']:<10}  release {body['application']['release']}  "
                  f"{body['database']['rows']} rows  {files['object_count']} files "
                  f"({files['total_bytes']} bytes)")  # fmt: skip
        except Exception as exc:
            say(f"{backup_id}  REFUSED     {getattr(exc, 'reason', type(exc).__name__)}")
    return 0


def _write_report(path: str | None, data: dict[str, Any]) -> None:
    if path:
        Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def cmd_verify(args: argparse.Namespace) -> int:
    config = _config(service=False)
    report = verify_set(
        destination=make_destination(config), backup_id=args.set, signers=_signers(args.signer),
        keys=_keys(args.recovery_key), deep=args.deep,
    )  # fmt: skip
    say(report.text())
    _write_report(args.report, report.as_dict())
    return 0 if report.passed else EXIT_FAILED


def _target_files(args: argparse.Namespace, config: BackupConfig) -> FileTargets | None:
    from markx.core.storage import (
        LocalPrivateStorage,
        LocalPublicStorage,
        ObjectStorageSettings,
        S3ObjectStore,
        make_s3_client,
    )

    forbidden = frozenset(
        n for n in (config.source_private_bucket, config.source_public_bucket) if n
    )
    if args.no_files:
        return None
    if args.target_files_dir:
        root = Path(args.target_files_dir).resolve()
        stores = {
            "private": LocalPrivateStorage(root / "private"),
            "public": LocalPublicStorage(root / "public"),
        }
        return FileTargets(stores, f"folder {root}", forbidden)  # type: ignore[arg-type]
    if not (args.target_provider and args.target_private_bucket and args.target_public_bucket):
        raise SystemExit(
            "choose the file targets: --target-files-dir DIR, or --target-provider with "
            "--target-private-bucket and --target-public-bucket, or --no-files"
        )
    key_id = os.environ.get("MARKX_RESTORE_TARGET_ACCESS_KEY_ID")
    secret = os.environ.get("MARKX_RESTORE_TARGET_SECRET_ACCESS_KEY")
    if not (key_id and secret):
        raise SystemExit(
            "set MARKX_RESTORE_TARGET_ACCESS_KEY_ID and _SECRET_ACCESS_KEY for the target buckets"
        )
    if args.target_provider != "minio" and not (args.target_endpoint or "https://").startswith(
        "https://"
    ):
        raise SystemExit("the target endpoint must be https://")
    settings = ObjectStorageSettings(
        provider=args.target_provider, endpoint_url=args.target_endpoint,
        region=args.target_region or ("auto" if args.target_provider == "r2" else "us-east-1"),
        access_key_id=key_id, secret_access_key=secret,
        private_bucket=args.target_private_bucket, public_bucket=args.target_public_bucket,
    )  # fmt: skip
    client = make_s3_client(settings)
    stores_s3 = {
        "private": S3ObjectStore(
            client, settings.private_bucket, name="private", settings=settings
        ),
        "public": S3ObjectStore(client, settings.public_bucket, name="public", settings=settings),
    }
    return FileTargets(stores_s3, f"{args.target_provider} buckets {settings.private_bucket}, "  # type: ignore[arg-type]
                       f"{settings.public_bucket}", forbidden)  # fmt: skip


def cmd_restore(args: argparse.Namespace) -> int:
    config = _config(service=False)
    report = restore_set(
        destination=make_destination(config), backup_id=args.set, signers=_signers(args.signer),
        keys=_keys(args.recovery_key), server=PgServer.from_environment(),
        target_db=args.target_db, confirm=args.confirm_target, files=_target_files(args, config),
        bootstrap_script=_default_bootstrap(), psql_command=config.psql_command,
        pg_restore_command=config.pg_restore_command, accept_incomplete=args.accept_incomplete,
    )  # fmt: skip
    say(report.text())
    _write_report(args.report, report.as_dict())
    return 0 if report.passed else EXIT_FAILED


def cmd_drill(args: argparse.Namespace) -> int:
    from markx.backup.drill import run_drill

    config = _config(service=False)
    ctx = _context(config)
    if args.seed_sample_files:
        if config.is_real_environment:
            raise SystemExit("--seed-sample-files is for a laptop and CI only")
        _seed_samples(config)
    inject = (
        args.inject_failures if args.inject_failures is not None else not config.is_real_environment
    )
    result = run_drill(
        ctx, superuser=PgServer.from_environment(), keys=_keys(args.recovery_key),
        signers=_signers(args.signer, config), bootstrap_script=_default_bootstrap(), inject=inject,
    )  # fmt: skip
    say(result.text())
    _write_report(args.report, result.as_dict())
    return 0 if result.passed else EXIT_FAILED


# A 1x1 PNG and a 1x1 WebP: representative, and nobody's data.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2d5b2f40000000049454e44ae426082"
)
_WEBP = bytes.fromhex(
    "52494646240000005745425056503820180000003001009d012a0100010002003425a40003700000fefb94000000"
)


def _seed_samples(config: BackupConfig) -> None:
    from markx.core.storage import (
        LocalPrivateStorage,
        LocalPublicStorage,
        ObjectStore,
        S3ObjectStore,
        make_s3_client,
    )

    stores: dict[str, ObjectStore]
    if config.source_provider == "local":
        stores = {"private": LocalPrivateStorage(config.source_dir / "private"),
                  "public": LocalPublicStorage(config.source_dir / "public")}  # fmt: skip
    else:
        settings = config.source_settings()
        client = make_s3_client(settings)
        stores = {"private": S3ObjectStore(client, settings.private_bucket, name="private", settings=settings),
                  "public": S3ObjectStore(client, settings.public_bucket, name="public", settings=settings)}  # fmt: skip
    # Distinct bytes per file (trailing bytes after the image end), so each has its own blob.
    for n in range(3):
        stores["private"].put(f"drill-samples/document-{n}.png", _PNG + bytes([n]), "image/png")
        stores["public"].put(
            f"drill-samples/picture-{n}-320.webp", _WEBP + bytes([n]), "image/webp"
        )
    say("seeded 3 private and 3 public sample files under drill-samples/")


def main(argv: list[str] | None = None) -> int:
    # Every file the backup writes (pieces, evidence, local copies, keys) is
    # readable by its own user only.
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m markx.backup", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("keygen", help="make a recovery key pair and a signing key pair")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_keygen)
    sub.add_parser("run", help="one backup set now").set_defaults(func=cmd_run)
    sub.add_parser("serve", help="the scheduled service").set_defaults(func=cmd_serve)
    sub.add_parser("check", help="health: a fresh verified set").set_defaults(func=cmd_check)
    p = sub.add_parser("list", help="the sets at the destination")
    p.add_argument("--signer", action="append", default=[])
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("prune", help="apply retention (dry run without --execute)")
    p.add_argument("--execute", action="store_true")
    p.set_defaults(func=cmd_prune)
    for name, func in (("verify", cmd_verify), ("restore", cmd_restore)):
        p = sub.add_parser(name)
        p.add_argument("--set", required=True, help="the backup id")
        p.add_argument(
            "--recovery-key", action="append", required=True, help="recovery key file (repeatable)"
        )
        p.add_argument(
            "--signer", action="append", required=True, help="trusted signer key file (repeatable)"
        )
        p.add_argument("--report", help="write the JSON report here")
        p.set_defaults(func=func)
        if name == "verify":
            p.add_argument("--deep", action="store_true", help="decrypt and hash every file")
        else:
            p.add_argument("--target-db", required=True)
            p.add_argument("--confirm-target", required=True, help="repeat --target-db")
            p.add_argument("--target-files-dir")
            p.add_argument("--target-provider", choices=["minio", "s3", "r2"])
            p.add_argument("--target-endpoint")
            p.add_argument("--target-region")
            p.add_argument("--target-private-bucket")
            p.add_argument("--target-public-bucket")
            p.add_argument("--no-files", action="store_true", help="restore the database only")
            p.add_argument("--accept-incomplete", action="store_true")
    p = sub.add_parser("drill", help="the recovery drill")
    p.add_argument("--recovery-key", action="append", required=True)
    p.add_argument("--signer", action="append", default=[])
    p.add_argument("--report")
    p.add_argument("--seed-sample-files", action="store_true")
    p.add_argument("--inject-failures", dest="inject_failures", action="store_true", default=None)
    p.add_argument("--no-inject-failures", dest="inject_failures", action="store_false")
    p.set_defaults(func=cmd_drill)
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except crypto.BackupKeyError as exc:
        say(f"key refused: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except SystemExit as exc:
        if isinstance(exc.code, str):
            say(exc.code, file=sys.stderr)
            return EXIT_USAGE
        raise


if __name__ == "__main__":
    sys.exit(main())
