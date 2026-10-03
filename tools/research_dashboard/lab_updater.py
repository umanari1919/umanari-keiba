from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
BASE = "https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard"
STATE = ROOT / "checkpoints" / "lab_updater_state.json"
DIRECTOR_STATE = ROOT / "checkpoints" / "research_director_state.json"
PROBABILITY_STATE = ROOT / "checkpoints" / "probability_director_state.json"
LOG = ROOT / "logs" / "lab_updater.log"
INTERVAL = int(os.environ.get("THE_JOCKEY_UPDATE_INTERVAL", "300"))

FILES = [
    "dashboard_server.py",
    "research_director.py",
    "probability_director.py",
    "start-dashboard.ps1",
    "start-research-lab.ps1",
    "lab_updater.py",
]

for p in (STATE.parent, LOG.parent):
    p.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now().astimezone().isoformat()


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(name: str) -> bytes:
    req = urllib.request.Request(
        f"{BASE}/{name}?t={int(time.time())}",
        headers={"User-Agent": "THE-JOCKEY-Research-Lab-Updater/1.2"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def local_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def atomic_replace(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".update")
    tmp.write_bytes(data)
    tmp.replace(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def process_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def stop_process(pid: int) -> None:
    if not process_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            time.sleep(0.2)
            if not process_alive(pid):
                return
    except Exception:
        pass
    if os.name == "nt" and process_alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)


def start_worker(script_name: str) -> int:
    script = ROOT / script_name
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        env={**os.environ, "THE_JOCKEY_RESEARCH_ROOT": str(ROOT)},
    )
    return proc.pid


def restart_worker(script_name: str, state_path: Path) -> dict:
    old = read_json(state_path, {}) or {}
    old_pid = int(old.get("pid") or 0)
    if old_pid and old_pid != os.getpid():
        stop_process(old_pid)
    new_pid = start_worker(script_name)
    log(f"RESTARTED {script_name} old_pid={old_pid or '-'} new_pid={new_pid}")
    return {"script": script_name, "old_pid": old_pid or None, "new_pid": new_pid}


def run_once() -> dict:
    updated = []
    unchanged = []
    errors = []
    restarts = []

    for name in FILES:
        try:
            remote = fetch(name)
            target = ROOT / name
            local = local_bytes(target)
            if sha256(remote) == sha256(local):
                unchanged.append(name)
                continue
            atomic_replace(target, remote)
            updated.append(name)
            log(f"UPDATED {name}")
        except Exception as e:
            errors.append({"file": name, "error": repr(e)})
            log(f"ERROR {name}: {e!r}")

    restart_specs = [
        ("research_director.py", DIRECTOR_STATE),
        ("probability_director.py", PROBABILITY_STATE),
    ]
    for script_name, state_path in restart_specs:
        if script_name in updated:
            try:
                restarts.append(restart_worker(script_name, state_path))
            except Exception as e:
                errors.append({"file": script_name, "error": f"restart failed: {e!r}"})
                log(f"ERROR restarting {script_name}: {e!r}")

    # First appearance of the probability worker must start automatically.
    if "probability_director.py" not in updated and (ROOT / "probability_director.py").exists():
        pstate = read_json(PROBABILITY_STATE, {}) or {}
        ppid = int(pstate.get("pid") or 0)
        if not process_alive(ppid):
            try:
                new_pid = start_worker("probability_director.py")
                restarts.append({"script": "probability_director.py", "old_pid": None, "new_pid": new_pid})
                log(f"STARTED probability_director.py new_pid={new_pid}")
            except Exception as e:
                errors.append({"file": "probability_director.py", "error": f"start failed: {e!r}"})

    state = {
        "updated_at": now(),
        "updated_files": updated,
        "unchanged_files": unchanged,
        "restarts": restarts,
        "errors": errors,
        "interval_seconds": INTERVAL,
        "status": "PASS" if not errors else "PARTIAL",
    }
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def main() -> None:
    log("LAB UPDATER START v1.2")
    while True:
        run_once()
        time.sleep(max(60, INTERVAL))


if __name__ == "__main__":
    main()
