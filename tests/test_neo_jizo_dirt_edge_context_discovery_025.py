"""Safety and failover contract for NEO JIZO context discovery."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import neo_jizo_dirt_edge_context_discovery_025 as discovery


def _fake_run(*, windows_rc: int = 0, wsl_rc: int = 0, state: str | None = None):
    calls: list[dict[str, object]] = []
    ok = state or (
        '[{"transaction_read_only":"on",'
        '"default_transaction_read_only":"on",'
        '"database_name":"mykeibadb"}]'
    )

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        wsl = command[0] == "wsl.exe"
        rc = wsl_rc if wsl else windows_rc
        calls.append({"command": command, **kwargs})
        if rc:
            return SimpleNamespace(
                returncode=rc,
                stdout="",
                stderr=("could not connect to WSL socket" if wsl else
                        "connection to server at 127.0.0.1 failed"),
            )
        return SimpleNamespace(returncode=0, stdout=ok, stderr="")

    return run, calls


def test_windows_uses_approved_login_and_explicit_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    run, calls = _fake_run()
    monkeypatch.setattr(discovery.subprocess, "run", run)

    backend, info = discovery.connect_read_only(
        "psql.exe", host="127.0.0.1", port="5433", db="mykeibadb"
    )

    assert backend == "windows_tcp"
    assert info["transaction_read_only"] == "on"
    assert len(calls) == 1
    command = calls[0]["command"]
    assert "-U" in command
    assert command[command.index("-U") + 1] == "postgres"
    assert "-w" in command
    assert "default_transaction_read_only=on" in calls[0]["env"]["PGOPTIONS"]
    assert calls[0]["input"]


def test_wsl_socket_fallback_without_db_service_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, calls = _fake_run(windows_rc=2)
    monkeypatch.setattr(discovery.subprocess, "run", run)
    monkeypatch.setattr(
        discovery.shutil, "which",
        lambda value: "wsl.exe" if value in {"wsl", "wsl.exe"} else None,
    )

    backend, state = discovery.connect_read_only(
        "psql.exe", host="127.0.0.1", port="5433", db="mykeibadb"
    )

    assert backend == "wsl_socket"
    assert state["transaction_read_only"] == "on"
    assert len(calls) == 2
    command = calls[-1]["command"]
    assert "-d" in command and "Ubuntu" in command
    shell = command[command.index("-lc") + 1]
    assert "/home/*/.keiba_ai/postgres18/bin/psql" in shell
    assert "/root/.keiba_ai/postgres18/bin/psql" in shell
    assert "default_transaction_read_only=on" in shell
    assert '/tmp /var/run/postgresql /run/postgresql' in shell
    assert "No live-looking PostgreSQL socket" not in shell
    assert "no live-looking PostgreSQL socket" in shell
    assert "pg_ctl" not in str(command)
    assert "systemctl" not in str(command)
    assert "service" not in str(command)


def test_both_connections_failed_give_errors_not_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, _ = _fake_run(windows_rc=2, wsl_rc=2)
    monkeypatch.setattr(discovery.subprocess, "run", run)
    monkeypatch.setattr(
        discovery.shutil, "which",
        lambda value: "wsl.exe" if value in {"wsl", "wsl.exe"} else None,
    )

    with pytest.raises(RuntimeError, match="READ_ONLY_DB_CONNECTION_BLOCKED") as error:
        discovery.connect_read_only(
            "psql.exe", host="127.0.0.1", port="5433", db="mykeibadb"
        )

    assert "connection to server at 127.0.0.1 failed" in str(error.value)
    assert "could not connect to WSL socket" in str(error.value)
    assert "No service was started or stopped" in str(error.value)


def test_missing_psql_can_use_wsl_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    run, calls = _fake_run()
    monkeypatch.setattr(discovery.subprocess, "run", run)
    monkeypatch.setattr(
        discovery.shutil, "which",
        lambda value: "wsl.exe" if value in {"wsl", "wsl.exe"} else None,
    )
    backend, _ = discovery.connect_read_only(
        None, host="127.0.0.1", port="5433", db="mykeibadb"
    )
    assert backend == "wsl_socket"
    assert len(calls) == 1


def test_password_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGPASSWORD", "a-very-sensitive-password")
    assert "a-very-sensitive-password" not in discovery._safe_error(
        "password=a-very-sensitive-password"
    )
