"""deploy.sh and MARKX_ALLOW_NEWER_SCHEMA (D-103, the founder's rule).

Go back to an older release only when it truly accepts the database. The
setting lets an older release accept a newer database; an operator turns it
on for one compatible rollback, and it may be left on. These tests run the
real deploy.sh against a stand-in for `docker` that models what matters:

- the preflight of a release says "schema: ahead" for a database newer than
  that release, and passes only if MARKX_ALLOW_NEWER_SCHEMA is on for that
  container: `run -e` wins, otherwise api.env decides (as Compose does);
- the new release's preflight refuses `--deploying` while the setting is on;
- every other call succeeds and is written to a log, with MARKX_RELEASE.

The whole Compose stack, with real images and a real newer migration, is
rehearsed in infra/production/rehearsal/rehearse.sh ("a failed update").
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[4] / "infra" / "production" / "deploy.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
# A stand-in for docker (tests/deployment/test_deploy_newer_schema.py).
printf 'MARKX_RELEASE=%s %s\n' "${MARKX_RELEASE:-}" "$*" >> "$FAKE_LOG"
args=" $* "
if [[ "$1" == image ]]; then exit 0; fi
setting_on() {
  [[ "$args" == *" -e MARKX_ALLOW_NEWER_SCHEMA=false "* ]] && return 1
  grep -qx 'MARKX_ALLOW_NEWER_SCHEMA=true' "$FAKE_CONFIG/api.env" 2>/dev/null
}
case "$args" in
  *" run "*"markx.ops.preflight"*)
    echo "configuration: accepted (MARKX_ENV=local)"
    if [[ "$args" == *" --deploying "* ]] && setting_on; then
      echo "deployment: REFUSED"; echo "preflight: FAILED"; exit 1
    fi
    [[ "$args" == *" --config-only "* ]] && exit 0
    echo "database: up"; echo "schema: $FAKE_SCHEMA"; echo "file storage: up"
    if [[ "$FAKE_SCHEMA" == ahead ]] && ! setting_on; then echo "preflight: FAILED"; exit 1; fi
    echo "preflight: PASSED"; exit 0 ;;
  *" exec "*"print("*"healthz/ready"*) echo "${FAKE_RUNNING_SCHEMA:-$FAKE_SCHEMA}" ;;
esac
exit 0
"""


@dataclass
class Server:
    root: Path
    config: Path
    env: dict[str, str]

    @property
    def log(self) -> list[str]:
        path = self.root / "docker.log"
        return path.read_text().splitlines() if path.exists() else []

    def allow_newer_schema(self) -> None:
        with (self.config / "api.env").open("a") as f:
            f.write("MARKX_ALLOW_NEWER_SCHEMA=true\n")

    def releases(self) -> list[str]:
        path = self.config / "releases.log"
        lines = path.read_text().splitlines() if path.exists() else []
        return [line.split(" ", 1)[1] for line in lines]

    def run(self, script: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", script],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def deploy_sh(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(DEPLOY), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def recover(self, failed: str, previous: str, **env: str) -> subprocess.CompletedProcess[str]:
        """deploy.sh's recovery, as a deployment that failed after its migration calls it."""
        return self.run(f'source "$DEPLOY"; recover {failed} {previous}', **env)


@pytest.fixture
def server(tmp_path: Path) -> Server:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    config = tmp_path / "etc"
    config.mkdir()
    for name in ("api.env", "migrate.env", "postgres.env", "web.env", "backup.env"):
        (config / name).write_text("MARKX_ENV=local\n")
    compose_env = config / "compose.env"
    compose_env.write_text(f"MARKX_ENV=local\nMARKX_CONFIG_DIR={config}\n")
    (config / "releases.log").write_text("2026-11-20T10:00:00Z deploy old\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "DEPLOY": str(DEPLOY),
        "MARKX_COMPOSE_ENV": str(compose_env),
        "MARKX_DEPLOY_REHEARSAL": "1",
        "FAKE_LOG": str(tmp_path / "docker.log"),
        "FAKE_CONFIG": str(config),
        "FAKE_SCHEMA": "current",
    }
    return Server(tmp_path, config, env)


def _started(server: Server, release: str, service: str) -> bool:
    return any(
        line.startswith(f"MARKX_RELEASE={release} ") and " up " in f" {line} " and service in line
        for line in server.log
    )


# -- the automatic return after a failed deployment ----------------------------------------


def test_the_reviewers_case_recovery_refuses_a_newer_database_with_the_setting_left_on(
    server: Server,
) -> None:
    """A database carrying a later change, the setting left on in api.env: the
    old release would say yes to it. Recovery must refuse and stop safely."""
    server.allow_newer_schema()
    out = server.recover("new", "old", FAKE_SCHEMA="ahead")
    assert out.returncode != 0
    assert "forced off" in out.stdout
    assert "old refuses the migrated database" in out.stdout
    assert "DEPLOYMENT HALTED in a safe state" in out.stdout
    assert "running again, verified" not in out.stdout + out.stderr
    assert not _started(server, "old", "api")
    assert "auto-rollback old" not in server.releases()
    (check,) = [line for line in server.log if "markx.ops.preflight" in line]
    assert check.startswith("MARKX_RELEASE=old ")
    assert " -e MARKX_ALLOW_NEWER_SCHEMA=false " in f" {check} "
    assert "failed_release=new" in (server.config / "deploy-halted").read_text()


def test_recovery_still_returns_to_an_old_release_that_truly_accepts_the_database(
    server: Server,
) -> None:
    server.allow_newer_schema()  # whatever the setting says
    out = server.recover("new", "old", FAKE_SCHEMA="current")
    assert out.returncode != 0  # the deployment itself failed
    assert "old is running again, verified" in out.stderr
    assert _started(server, "old", "api worker web proxy")
    assert server.releases()[-1] == "auto-rollback old"
    assert not (server.config / "deploy-halted").exists()


def test_recovery_stops_an_old_release_that_reports_a_schema_other_than_current(
    server: Server,
) -> None:
    out = server.recover("new", "old", FAKE_SCHEMA="current", FAKE_RUNNING_SCHEMA="ahead")
    assert "reports the schema as 'ahead', not current" in out.stdout
    assert "DEPLOYMENT HALTED in a safe state" in out.stdout
    assert "auto-rollback old" not in server.releases()


def test_in_the_safe_stop_the_backup_service_runs_as_the_release_that_migrated(
    server: Server,
) -> None:
    out = server.recover("new", "old", FAKE_SCHEMA="ahead")
    assert "DEPLOYMENT HALTED" in out.stdout
    stop = next(i for i, line in enumerate(server.log) if " stop api worker web" in line)
    assert any(
        line.startswith("MARKX_RELEASE=new ") and "up -d --no-build --no-deps backup" in line
        for line in server.log[stop:]
    )
    assert "--accept-newer-schema" in out.stdout  # the documented way out names it


# -- deploy refuses while the setting is on -------------------------------------------------


def test_deploy_refuses_to_start_while_the_setting_is_on(server: Server) -> None:
    server.allow_newer_schema()
    out = server.deploy_sh("deploy", "next")
    assert out.returncode != 0
    assert "MARKX_ALLOW_NEWER_SCHEMA is on" in out.stderr
    assert "Remove that line" in out.stderr
    assert "Nothing was changed" in out.stderr
    assert server.log == []  # not one docker call: no build, no backup, no migration
    assert server.releases() == ["deploy old"]


@pytest.mark.parametrize("value", ["true", "TRUE", '"true"', "1", "yes", "on"])
def test_deploy_reads_every_spelling_of_the_setting_as_on(server: Server, value: str) -> None:
    with (server.config / "api.env").open("a") as f:
        f.write(f"MARKX_ALLOW_NEWER_SCHEMA={value}\n")
    out = server.deploy_sh("deploy", "next")
    assert "MARKX_ALLOW_NEWER_SCHEMA is on" in out.stderr
    assert server.log == []


def test_every_check_of_a_new_release_in_a_deployment_is_made_with_deploying() -> None:
    """The new release refuses the setting itself, wherever it is set."""
    body = DEPLOY.read_text().split("cmd_deploy() {", 1)[1].split("\ncmd_rollback() {", 1)[0]
    checks = [line.strip() for line in body.splitlines() if "preflight" in line.split("#")[0]]
    calls = [c for c in checks if c.startswith(("preflight", "if ! preflight"))]
    assert len(calls) == 3
    assert all("--deploying" in c for c in calls), calls


# -- a rollback by hand ----------------------------------------------------------------------


def test_a_setting_left_on_never_decides_a_rollback_by_itself(server: Server) -> None:
    server.allow_newer_schema()
    out = server.deploy_sh("rollback", "old", FAKE_SCHEMA="ahead")
    assert out.returncode != 0
    assert "the database is newer than old: nothing was started" in out.stderr
    assert "--accept-newer-schema" in out.stderr
    assert not _started(server, "old", "api")
    assert server.releases() == ["deploy old"]


def test_a_compatible_rollback_needs_the_setting_and_the_command_line(server: Server) -> None:
    out = server.deploy_sh("rollback", "old", "--accept-newer-schema", FAKE_SCHEMA="ahead")
    assert out.returncode != 0
    assert "also needs MARKX_ALLOW_NEWER_SCHEMA=true" in out.stderr
    assert not _started(server, "old", "api")

    server.allow_newer_schema()
    out = server.deploy_sh("rollback", "old", "--accept-newer-schema", FAKE_SCHEMA="ahead")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "a COMPATIBLE rollback" in out.stdout
    assert "REMEMBER: MARKX_ALLOW_NEWER_SCHEMA is on" in out.stdout
    assert _started(server, "old", "api worker web proxy")
    assert server.releases()[-1] == "rollback old"


def test_a_rollback_to_a_release_that_accepts_the_database_needs_nothing_more(
    server: Server,
) -> None:
    out = server.deploy_sh("rollback", "old", FAKE_SCHEMA="current")
    assert out.returncode == 0, out.stdout + out.stderr
    assert server.releases()[-1] == "rollback old"


# -- a backup by hand after a safe stop ------------------------------------------------------


def test_a_backup_after_a_safe_stop_uses_the_release_that_migrated(server: Server) -> None:
    (server.config / "deploy-halted").write_text("failed_release=new\nlast_working_release=old\n")
    out = server.deploy_sh("backup")
    assert out.returncode == 0, out.stdout + out.stderr
    (run,) = [line for line in server.log if "markx.backup run" in line]
    assert run.startswith("MARKX_RELEASE=new ")


def test_a_backup_otherwise_uses_the_running_release(server: Server) -> None:
    out = server.deploy_sh("backup")
    assert out.returncode == 0, out.stdout + out.stderr
    (run,) = [line for line in server.log if "markx.backup run" in line]
    assert run.startswith("MARKX_RELEASE=old ")
