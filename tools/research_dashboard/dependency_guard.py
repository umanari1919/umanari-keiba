from __future__ import annotations

import importlib.metadata as md
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home()/"Downloads"/"THE-JOCKEY-RESEARCH"))
REPORTS = ROOT/"CORE"/"reports"; CHECK = ROOT/"checkpoints"; LOG = ROOT/"logs"/"dependency_guard.log"; STATE = CHECK/"dependency_guard_state.json"; REPORT = REPORTS/"DEPENDENCY_GUARD_report.json"
INTERVAL = max(300, int(os.environ.get("THE_JOCKEY_DEPENDENCY_GUARD_INTERVAL", "1800")))
for p in (REPORTS, CHECK, LOG.parent): p.mkdir(parents=True, exist_ok=True)

# Stable targets verified on 2026-10-04. Detection only: this worker never upgrades packages.
TARGETS = {
    "numpy": {"target": "2.5.3", "tier": "CORE"},
    "pandas": {"target": "3.0.6", "tier": "CORE"},
    "duckdb": {"target": "1.5.6", "tier": "CORE"},
    "polars": {"target": "1.44.2", "tier": "CORE"},
    "pyarrow": {"target": "25.0.1", "tier": "CORE"},
    "pydantic": {"target": "2.13.5", "tier": "CORE"},
    "pandera": {"target": "0.33.1", "tier": "CORE"},
    "scikit-learn": {"target": "1.9.1", "tier": "RESEARCH"},
    "optuna": {"target": "5.0.0", "tier": "RESEARCH"},
    "catboost": {"target": "1.2.10", "tier": "MODEL"},
    "mlflow": {"target": "3.16.0", "tier": "MLOPS"},
    "ruff": {"target": "0.16.8", "tier": "DEV"},
    "pytest": {"target": "9.1.0", "tier": "DEV"},
    "pytest-xdist": {"target": "3.8.0", "tier": "DEV"},
}
UV_TARGET="0.12.21"

def now(): return datetime.now().astimezone().isoformat()
def writej(path, obj):
    tmp = path.with_suffix(path.suffix+".tmp"); tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(path)
def log(msg):
    line=f"[{now()}] {msg}"; print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(line+"\n")
def parse(v):
    nums=[int(x) for x in re.findall(r"\d+", str(v))[:3]]
    return tuple(nums+[0]*(3-len(nums)))
def preview(v):return bool(re.search(r"(?:^|[.\-])(a|b|rc|alpha|beta|dev)\d*",str(v).lower()))
def uv_version():
    if not shutil.which("uv"):return None
    try:
        s=subprocess.run(["uv","--version"],capture_output=True,text=True,timeout=8,check=False).stdout.strip()
        m=re.search(r"(\d+\.\d+\.\d+)",s);return m.group(1) if m else None
    except Exception:return None
def run_once():
    rows=[];warnings=[]
    uv=uv_version();uv_status="MISSING_OPTIONAL" if uv is None else ("PREVIEW_INSTALLED" if preview(uv) else ("PASS" if parse(uv)>=parse(UV_TARGET) else "OUTDATED"))
    rows.append({"package":"uv","tier":"TOOLCHAIN","target":UV_TARGET,"installed":uv,"status":uv_status})
    if uv_status in {"OUTDATED","PREVIEW_INSTALLED"}:warnings.append(f"uv:{uv}->{UV_TARGET}:{uv_status}")
    for pkg, meta in TARGETS.items():
        try: installed=md.version(pkg)
        except md.PackageNotFoundError: installed=None
        if installed is None:status="MISSING_OPTIONAL"
        elif preview(installed):status="PREVIEW_INSTALLED"
        else:status="PASS" if parse(installed)>=parse(meta["target"]) else "OUTDATED"
        rows.append({"package":pkg,"tier":meta["tier"],"target":meta["target"],"installed":installed,"status":status})
        if status in {"OUTDATED","PREVIEW_INSTALLED"}:warnings.append(f"{pkg}:{installed}->{meta['target']}:{status}")
    py=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}";py_ok=(3,11)<=sys.version_info[:2]<(3,15)
    status="WARN" if warnings or not py_ok else "PASS"
    out={"updated":now(),"status":status,"python":py,"python_supported":py_ok,"platform":platform.platform(),"packages":rows,"warnings":warnings,"missing_optional":sum(x['status']=='MISSING_OPTIONAL' for x in rows),"policy":"Detect only. Never auto-upgrade production dependencies. Reject preview versions for governed runtime; upgrade through uv + CI + self-test + regression test."}
    writej(REPORT,out);writej(STATE,{"pid":os.getpid(),"updated":now(),"status":status,"warning_count":len(warnings),"missing_optional":out['missing_optional'],"python_supported":py_ok});log(f"DEPENDENCY GUARD {status} warnings={len(warnings)} missing_optional={out['missing_optional']}");return out

def main():
    log("DEPENDENCY GUARD START")
    while True:
        try: run_once()
        except Exception:
            err=traceback.format_exc();log(err);writej(STATE,{"pid":os.getpid(),"updated":now(),"status":"BLOCKED","detail":err[-1800:]})
        time.sleep(INTERVAL)
if __name__=="__main__":main()
