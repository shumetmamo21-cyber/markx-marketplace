"""D-105 in the shell scripts, against a stand-in for `docker`:

- deploy.sh `watch` (BK-4): a container that stays unhealthy, stopped or
  missing for MARKX_CONTAINER_ALERT_MINUTES alerts the staff group once
  through the bot, and once more when it is fine again; `alert-test` sends a
  test alert and fails when nobody was told; `escrow-secrets` (BK-5) pipes
  the secrets as a tar stream into the backup image, never printing them.
- infra/backup/recovery-host.sh (RN-2, RN-3, RN-4): it deletes only its own
  marked socket folder, stops only its own labelled container, keeps the
  socket folder private, and refuses a socket path too long for Linux.

The real stack with real containers is rehearsed in
infra/production/rehearsal/rehearse.sh, and the recovery script runs for real
in CI's off-server drill.
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DEPLOY = ROOT / "infra" / "production" / "deploy.sh"
RECOVERY = ROOT / "infra" / "backup" / "recovery-host.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
# A stand-in for docker (tests/deployment/test_d105_scripts.py).
printf '%s\n' "$*" >> "$FAKE_LOG"
args=" $* "
case "$args" in
  *" ps -a --format "*) cat "$FAKE_PS" 2>/dev/null; exit 0 ;;
  *" markx.ops.notify send "*) exit "${FAKE_NOTIFY_EXIT:-0}" ;;
  *" markx.ops.notify test "*) echo "fake: test alert"; exit "${FAKE_NOTIFY_EXIT:-0}" ;;
  *" markx.backup heartbeat"*) echo "outside heartbeat: OFF"; exit 0 ;;
  *" markx.backup escrow-secrets "*) cat > "$FAKE_TAR"; echo "secrets copy written"; exit 0 ;;
esac
exit 0
"""


@dataclass
class Server:
    root: Path
    config: Path
    tls: Path
    env: dict[str, str]

    @property
    def log(self) -> list[str]:
        path = self.root / "docker.log"
        return path.read_text().splitlines() if path.exists() else []

    def notifications(self) -> list[str]:
        return [line for line in self.log if "markx.ops.notify send" in line]

    def containers(self, **states: str) -> None:
        lines = []
        for service in ("postgres", "api", "worker", "web", "proxy", "backup"):
            state = states.get(service, "running healthy")
            if state != "absent":
                lines.append(f"{service} markx-production-{service}-1 {state}")
        (self.root / "ps.txt").write_text("\n".join(lines) + "\n")

    def deploy_sh(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(DEPLOY), *args], env={**self.env, **env},
                              capture_output=True, text=True, timeout=60, check=False)  # fmt: skip

    def age_state(self, minutes: int) -> None:
        """As if every problem had been seen `minutes` ago."""
        state = self.root / "watch" / "containers"
        rows = [line.split() for line in state.read_text().splitlines() if line]
        then = int(time.time()) - minutes * 60
        state.write_text("".join(f"{s} {then} {a}\n" for s, _, a in rows))


@pytest.fixture
def server(tmp_path: Path) -> Server:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    config, tls = tmp_path / "etc", tmp_path / "tls"
    config.mkdir()
    tls.mkdir()
    compose_env = config / "compose.env"
    compose_env.write_text(
        f"MARKX_ENV=local\nMARKX_CONFIG_DIR={config}\nMARKX_TLS_DIR={tls}\n"
        f"MARKX_BACKUP_HOST_DIR={tmp_path / 'backups'}\n"
    )
    (config / "releases.log").write_text("2026-11-20T10:00:00Z deploy rel1\n")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path),
        "MARKX_COMPOSE_ENV": str(compose_env), "MARKX_DEPLOY_REHEARSAL": "1",
        "MARKX_WATCH_STATE_DIR": str(tmp_path / "watch"),
        "FAKE_LOG": str(tmp_path / "docker.log"), "FAKE_PS": str(tmp_path / "ps.txt"),
        "FAKE_TAR": str(tmp_path / "piped.tar"),
    }  # fmt: skip
    return Server(tmp_path, config, tls, env)


# -- BK-4: the container watch -----------------------------------------------------------------


def test_a_healthy_server_alerts_nobody(server: Server) -> None:
    server.containers()
    result = server.deploy_sh("watch")
    assert result.returncode == 0, result.stderr
    assert "every container is running and healthy" in result.stdout
    assert server.notifications() == []


def test_a_container_that_stays_unhealthy_alerts_the_group_once_then_says_it_is_fine(
    server: Server,
) -> None:
    server.containers(worker="running unhealthy")
    first = server.deploy_sh("watch")
    assert first.returncode == 1  # the systemd unit shows as failed
    assert "worker: unhealthy for 0 minute(s)" in first.stdout
    assert server.notifications() == []  # not yet: it may recover by itself
    server.age_state(16)
    assert server.deploy_sh("watch").returncode == 1
    (sent,) = server.notifications()
    assert "--key container.worker" in sent
    assert "--state opened" in sent
    assert "worker container" in sent
    assert "unhealthy for 16 minutes" in sent
    assert server.deploy_sh("watch").returncode == 1
    assert len(server.notifications()) == 1  # once, not every five minutes
    server.containers()
    assert server.deploy_sh("watch").returncode == 0
    assert len(server.notifications()) == 2
    assert "--state resolved" in server.notifications()[-1]
    assert server.deploy_sh("watch").returncode == 0
    assert len(server.notifications()) == 2


@pytest.mark.parametrize(
    ("states", "words"),
    [
        ({"backup": "absent"}, "backup: missing (no container)"),
        ({"postgres": "exited -"}, "postgres: exited"),
        ({"api": "restarting -"}, "api: restarting"),
    ],
)
def test_a_stopped_missing_or_restarting_container_is_a_problem(
    server: Server, states: dict[str, str], words: str
) -> None:
    server.containers(**states)
    result = server.deploy_sh("watch")
    assert result.returncode == 1
    assert words in result.stdout


def test_an_alert_that_could_not_be_delivered_is_tried_again(server: Server) -> None:
    server.containers(proxy="running unhealthy")
    server.deploy_sh("watch")
    server.age_state(30)
    assert "could not be delivered" in server.deploy_sh("watch", FAKE_NOTIFY_EXIT="1").stdout
    server.deploy_sh("watch")
    assert len(server.notifications()) == 2  # the failed try, then the delivered one
    assert server.deploy_sh("watch").returncode == 1
    assert len(server.notifications()) == 2


def test_a_one_off_compose_run_container_is_not_the_service(server: Server) -> None:
    server.containers()
    with (server.root / "ps.txt").open("a") as f:
        f.write("backup markx-production-backup-run-1a2b3c exited -\n")
    assert server.deploy_sh("watch").returncode == 0


def test_the_watch_timer_is_written_with_this_servers_paths(server: Server) -> None:
    units = server.root / "units"
    result = server.deploy_sh("watch", "install-timer", MARKX_SYSTEMD_DIR=str(units))
    assert result.returncode == 0, result.stderr
    service = (units / "markx-watch.service").read_text()
    assert f"ExecStart={DEPLOY} watch" in service
    assert "OnUnitActiveSec=5min" in (units / "markx-watch.timer").read_text()


def test_alert_test_fails_when_the_test_alert_reached_nobody(server: Server) -> None:
    ok = server.deploy_sh("alert-test")
    assert ok.returncode == 0, ok.stderr
    assert "alert-test: PASSED" in ok.stdout
    assert any("markx.ops.notify test" in line for line in server.log)
    assert any("markx.backup heartbeat" in line for line in server.log)
    refused = server.deploy_sh("alert-test", FAKE_NOTIFY_EXIT="1")
    assert refused.returncode == 1
    assert "did not reach the staff Telegram group" in refused.stderr


# -- BK-5: the secrets copy from the server ------------------------------------------------------


def test_escrow_secrets_pipes_the_secrets_and_prints_none(server: Server) -> None:
    secrets_ = {"api.env": "MARKX_SECRET_KEY=test-only-a\nMARKX_ENCRYPTION_KEY=test-only-b\n",
                "postgres.env": "POSTGRES_PASSWORD=test-only-c\n",
                "backup-signing.key": "test-only-d\n"}  # fmt: skip
    for name, text in secrets_.items():
        (server.config / name).write_text(text)
    (server.config / "web.env").symlink_to("/etc/hostname")  # never followed
    (server.tls / "privkey.pem").write_text("test-only-e\n")
    (server.tls / "fullchain.pem").write_text("chain\n")
    result = server.deploy_sh("escrow-secrets")
    assert result.returncode == 0, result.stderr
    with tarfile.open(fileobj=io.BytesIO((server.root / "piped.tar").read_bytes())) as archive:
        members = {m.name: archive.extractfile(m).read().decode() for m in archive.getmembers()}  # type: ignore[union-attr]
    assert members == {**secrets_, "compose.env": (server.config / "compose.env").read_text(),
                       "tls/privkey.pem": "test-only-e\n", "tls/fullchain.pem": "chain\n"}  # fmt: skip
    (run,) = [line for line in server.log if "escrow-secrets" in line]
    assert "--from-tar --out-dir /backups/escrow --upload" in run
    assert "test-only" not in result.stdout + result.stderr + run


# -- RN-2, RN-3, RN-4: the recovery machine's PostgreSQL ------------------------------------------

FAKE_RECOVERY_DOCKER = r"""#!/usr/bin/env bash
# A stand-in for docker for recovery-host.sh: one container, in a file.
printf '%s\n' "$*" >> "$FAKE_LOG"
case "$1" in
  container)  # inspect [--format LABEL] NAME
    [[ -f "$FAKE_STATE" ]] || exit 1
    [[ "$*" == *"--format"* ]] && cat "$FAKE_STATE"; exit 0 ;;
  run)
    [[ "$*" == *" -d "* ]] || exit 0
    if [[ "$*" == *"--label markx.recovery=1"* ]]; then echo 1 > "$FAKE_STATE"; else : > "$FAKE_STATE"; fi
    exit 0 ;;
  logs) echo "PostgreSQL init process complete; ready for start up." ;;
  exec) exit 0 ;;
  stop|rm) rm -f "$FAKE_STATE" ;;
esac
exit 0
"""


@dataclass
class Machine:
    root: Path
    env: dict[str, str]

    def run(self, command: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(RECOVERY), command], env={**self.env, **env},
                              capture_output=True, text=True, timeout=60, check=False)  # fmt: skip

    @property
    def log(self) -> list[str]:
        path = self.root / "docker.log"
        return path.read_text().splitlines() if path.exists() else []

    def another_container(self) -> None:
        """A container of the same name that this script did not start."""
        (self.root / "container").write_text("\n")


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_RECOVERY_DOCKER)
    docker.chmod(0o755)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path),
           "FAKE_LOG": str(tmp_path / "docker.log"), "FAKE_STATE": str(tmp_path / "container"),
           "MARKX_RECOVERY_SOCKET_DIR": str(tmp_path / "sock")}  # fmt: skip
    return Machine(tmp_path, env)


def test_the_socket_folder_is_private_and_marked_and_the_container_labelled(
    machine: Machine,
) -> None:
    started = machine.run("start")
    assert started.returncode == 0, started.stderr
    folder = machine.root / "sock"
    assert folder.stat().st_mode & 0o777 == 0o700
    assert (folder / ".markx-recovery-socket").exists()
    assert f"PGHOST='{folder}/run'" in started.stdout
    (run,) = [line for line in machine.log if line.startswith("run -d")]
    assert "--network none" in run
    assert "--label markx.recovery=1" in run
    assert f"{folder}/run:/var/run/postgresql" in run
    stopped = machine.run("stop")
    assert stopped.returncode == 0, stopped.stderr
    assert not folder.exists()
    assert any(line.startswith("stop ") for line in machine.log)


def test_start_never_deletes_a_folder_that_is_not_its_own(machine: Machine) -> None:
    folder = machine.root / "sock"
    folder.mkdir()
    (folder / "precious.txt").write_text("someone's file")
    result = machine.run("start")
    assert result.returncode == 2
    assert "left alone" in result.stderr
    assert (folder / "precious.txt").read_text() == "someone's file"
    assert not [line for line in machine.log if line.startswith("run ")]


def test_stop_never_deletes_a_folder_that_is_not_its_own(machine: Machine, tmp_path: Path) -> None:
    for name in ("sock", "home"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "precious.txt").write_text("someone's file")
    result = machine.run("stop")
    assert result.returncode == 2
    assert (tmp_path / "sock" / "precious.txt").exists()
    # A link to another folder is not followed either.
    (tmp_path / "sock" / "precious.txt").unlink()
    (tmp_path / "sock").rmdir()
    (tmp_path / "sock").symlink_to(tmp_path / "home")
    assert machine.run("stop").returncode == 2
    assert (tmp_path / "home" / "precious.txt").exists()


def test_stop_never_stops_a_container_it_did_not_start(machine: Machine) -> None:
    machine.another_container()
    result = machine.run("stop")
    assert result.returncode == 2
    assert "was not started by this script" in result.stderr
    assert not [line for line in machine.log if line.split()[0] in ("stop", "rm")]
    assert (machine.root / "container").exists()


@pytest.mark.parametrize("folder", ["relative", "dotdot"])
def test_an_unsafe_socket_folder_setting_is_refused(
    machine: Machine, tmp_path: Path, folder: str
) -> None:
    """Every path here stays inside this test's own folder, so even the old
    script, which deleted whatever folder it was given, harms nothing else."""
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("someone's file")
    (tmp_path / "x").mkdir()
    setting = "relative/sock" if folder == "relative" else f"{tmp_path}/x/../victim"
    for command in ("start", "stop"):
        result = subprocess.run(["bash", str(RECOVERY), command], cwd=tmp_path,
                                env={**machine.env, "MARKX_RECOVERY_SOCKET_DIR": setting},
                                capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
        assert result.returncode == 2, (command, result.stdout)
    assert (victim / "precious.txt").read_text() == "someone's file"
    assert victim.stat().st_mode & 0o777 != 0o777
    assert not (tmp_path / "relative").exists()
    assert not [line for line in machine.log if line.split()[0] in ("run", "stop", "rm")]


def test_a_socket_path_too_long_for_linux_is_refused_before_anything_starts(
    machine: Machine,
) -> None:
    folder = machine.root / ("x" * 100)
    result = machine.run("start", MARKX_RECOVERY_SOCKET_DIR=str(folder))
    assert result.returncode == 2
    assert "at most 107" in result.stderr
    assert not folder.exists()
    assert machine.log == []
