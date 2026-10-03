from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
BASE = "https://raw.githubusercontent.com/umanari1919/umanari-keiba/main/tools/research_dashboard"
STATE = ROOT / "checkpoints" / "lab_updater_state.json"
LOG = ROOT / "logs" / "lab_updater.log"
INTERVAL = int(os.environ.get("THE_JOCKEY_UPDATE_INTERVAL", "300"))

FILES = [
    "dashboard_server.py",
    "research_director.py",
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
        headers={"User-Agent": "THE-JOCKEY-Research-Lab-Updater/1.0"},
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


def run_once() -> dict:
    updated = []
    unchanged = []
    errors = []

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

    state = {
        "updated_at": now(),
        "updated_files": updated,
        "unchanged_files": unchanged,
        "errors": errors,
        "interval_seconds": INTERVAL,
        "status": "PASS" if not errors else "PARTIAL",
    }
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def main() -> None:
    log("LAB UPDATER START")
    while True:
        run_once()
        time.sleep(max(60, INTERVAL))


if __name__ == "__main__":
    main()
