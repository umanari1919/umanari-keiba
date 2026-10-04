from __future__ import annotations

import importlib.metadata as md
import json
import os
import platform
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home()/"Downloads"/"THE-JOCKEY-RESEARCH"))
REPORTS = ROOT/"CORE"/"reports"
CHECK = ROOT/"checkpoints"
LOG = ROOT/"logs"/"dependency_guard.log"
STATE = CHECK/"dependency_guard_state.json"
REPORT = REPORTS/"DEPENDENCY_GUARD_report.json"
INTERVAL = max(300, int(os.environ.get("THE_JOCKEY_DEPENDENCY_GUARD_INTERVAL", "1800")))
for p in (REPORTS, CHECK, LOG.parent): p.mkdir(parents=True, exist_ok=True)

# 2026-10-04 validated stable targets. Missing optional packages do not stop the lab.
TARGETS = {
    "duckdb": {"target": "1.5.6", "tier": "CORE", "required": False},
    "polars": {"target": "1.44.2", "tier": "CORE", "required": False},
    "pyarrow": {"target": "25.0.1", "tier": "CORE", "required": False},
    "pydantic": {"target": "2.13.5", "tier": "CORE", "required": False},
    "pandera": {"target": "0.33.1", "tier": "CORE", "required": False},
    "scikit-learn": {"target": "1.9.1", "tier": "RESEARCH", "required": False},
    "optuna": {"target": "5.0.0", "tier": "RESEARCH", "required": False},
    "mlflow": {"target": "3.16.0", "tier": "MLOPS", "required": False},
    "ruff": {"target": "0.16.8", "tier": "DEV", "required": False},
    "pytest": {"target": "9.1.0", "tier": "DEV", "required": False},
    "pytest-xdist": {"target": "3.8.0", "tier": "DEV", "required": False},
}

def now(): return datetime.now().astimezone().isoformat()
def writej(path, obj):
    tmp = path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
def log(msg):
    line=f"[{now()}] {msg}"; print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(line+"\n")
def parse(v):
    nums=[int(x) for x in re.findall(r"\d+", str(v))[:3]]
    return tuple(nums+[0]*(3-len(nums)))
def run_once():
    rows=[]; warnings=[]
    for pkg, meta in TARGETS.items():
        try: installed=md.version(pkg)
        except md.PackageNotFoundError: installed=None
        status="MISSING_OPTIONAL" if installed is None else ("PASS" if parse(installed)>=parse(meta["target"]) else "OUTDATED")
        row={"package":pkg,"tier":meta["tier"],"target":meta["target"],"installed":installed,"status":status}
        rows.append(row)
        if status=="OUTDATED": warnings.append(f"{pkg}:{installed}->{meta['target']}")
    py=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok=(3,11)<=sys.version_info[:2]<(3,15)
    status="WARN" if warnings or not py_ok else "PASS"
    out={"updated":now(),"status":status,"python":py,"python_supported":py_ok,"platform":platform.platform(),"packages":rows,"warnings":warnings,"policy":"Detect only. Never auto-upgrade production dependencies. Upgrade through uv + self-test + regression test."}
    writej(REPORT,out);writej(STATE,{"pid":os.getpid(),"updated":now(),"status":status,"warning_count":len(warnings),"python_supported":py_ok});log(f"DEPENDENCY GUARD {status} outdated={len(warnings)}")
    return out

def main():
    log("DEPENDENCY GUARD START")
    while True:
        try: run_once()
        except Exception:
            err=traceback.format_exc();log(err);writej(STATE,{"pid":os.getpid(),"updated":now(),"status":"BLOCKED","detail":err[-1800:]})
        time.sleep(INTERVAL)
if __name__=="__main__":main()
