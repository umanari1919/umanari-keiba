from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
CORE = ROOT / "CORE"
DATA = CORE / "data"
REPORTS = CORE / "reports"
CHECK = ROOT / "checkpoints"
LOG = ROOT / "logs" / "temporal_sample_optimizer.log"
STATE = CHECK / "temporal_sample_optimizer_state.json"
PLAN = REPORTS / "TEMPORAL_SPLIT_plan.json"
PROFILE = REPORTS / "TEMPORAL_SPLIT_profile.csv"
INTERVAL = max(60, int(os.environ.get("THE_JOCKEY_TEMPORAL_OPTIMIZER_INTERVAL", "300")))
RATIOS = {
    "TRAIN": 0.58,
    "VALIDATION": 0.12,
    "SELECTION": 0.10,
    "TEST": 0.10,
    "OOS": 0.10,
}
TARGETS = ("label_win", "label_top2", "label_top3")

for p in (REPORTS, CHECK, LOG.parent):
    p.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now().astimezone().isoformat()


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def file_signature(path: Path) -> str:
    h = hashlib.sha256()
    st = path.stat()
    h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


def _nearest_cut(daily: pd.DataFrame, cumulative_fraction: float, after: pd.Timestamp | None = None) -> pd.Timestamp:
    target = daily["race_count"].sum() * cumulative_fraction
    candidates = daily if after is None else daily[daily.index > after]
    if candidates.empty:
        return daily.index[-1]
    idx = (candidates["race_cum"] - target).abs().idxmin()
    return pd.Timestamp(idx)


def _split_bounds(df: pd.DataFrame) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    races = (
        df[["race_id", "race_date"]]
        .dropna()
        .drop_duplicates("race_id")
        .assign(race_date=lambda x: pd.to_datetime(x["race_date"]).dt.normalize())
    )
    daily = races.groupby("race_date").size().rename("race_count").to_frame()
    daily["race_cum"] = daily["race_count"].cumsum()
    start = daily.index.min()
    finish = daily.index.max()

    cumulative = []
    running = 0.0
    for name in ("TRAIN", "VALIDATION", "SELECTION", "TEST"):
        running += RATIOS[name]
        cumulative.append(running)

    cuts: list[pd.Timestamp] = []
    previous = None
    for frac in cumulative:
        cut = _nearest_cut(daily, frac, previous)
        cuts.append(cut)
        previous = cut

    # Strictly chronological and date-disjoint. The next split starts on the next available race date.
    race_dates = list(daily.index)
    pos = {d: i for i, d in enumerate(race_dates)}
    bounds: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    names = ["TRAIN", "VALIDATION", "SELECTION", "TEST", "OOS"]
    split_starts = [start]
    for cut in cuts:
        i = min(pos.get(cut, 0) + 1, len(race_dates) - 1)
        split_starts.append(pd.Timestamp(race_dates[i]))
    split_ends = cuts + [finish]
    for name, s, e in zip(names, split_starts, split_ends):
        bounds[name] = (pd.Timestamp(s), pd.Timestamp(e))
    return bounds


def _mask(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    d = pd.to_datetime(df["race_date"], errors="coerce").dt.normalize()
    return d.between(start, end, inclusive="both")


def _segment_stats(df: pd.DataFrame, name: str, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    part = df[_mask(df, start, end)].copy()
    domains = {}
    for code, label in ((1, "JRA"), (2, "NAR")):
        x = part[pd.to_numeric(part["race_scope_cd"], errors="coerce") == code]
        domains[label] = {
            "rows": int(len(x)),
            "races": int(x["race_id"].nunique()),
        }
    targets = {}
    for target in TARGETS:
        if target not in part.columns:
            continue
        y = pd.to_numeric(part[target], errors="coerce")
        labeled = y.notna()
        targets[target] = {
            "labeled_rows": int(labeled.sum()),
            "positives": int((y == 1).sum()),
            "positive_rate": float((y == 1).mean()) if labeled.any() else None,
        }
    history = {}
    if "prior_start_count" in part.columns:
        h = pd.to_numeric(part["prior_start_count"], errors="coerce")
        history = {
            "rows": int(h.notna().sum()),
            "prior_1plus_rate": float((h >= 1).mean()),
            "prior_3plus_rate": float((h >= 3).mean()),
            "prior_6plus_rate": float((h >= 6).mean()),
        }
    return {
        "name": name,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "days": int((end - start).days + 1),
        "rows": int(len(part)),
        "races": int(part["race_id"].nunique()),
        "horses": int(part["horse_id"].nunique()) if "horse_id" in part.columns else None,
        "domains": domains,
        "targets": targets,
        "history": history,
    }


def _walk_forward_folds(df: pd.DataFrame) -> list[dict]:
    races = (
        df[["race_id", "race_date"]]
        .dropna()
        .drop_duplicates("race_id")
        .assign(race_date=lambda x: pd.to_datetime(x["race_date"]).dt.normalize())
        .sort_values(["race_date", "race_id"])
    )
    daily = races.groupby("race_date").size().rename("race_count").to_frame()
    daily["race_cum"] = daily["race_count"].cumsum()
    dates = list(daily.index)
    total = int(daily["race_count"].sum())
    if total == 0 or len(dates) < 10:
        return []

    def at(frac: float) -> pd.Timestamp:
        idx = (daily["race_cum"] - total * frac).abs().idxmin()
        return pd.Timestamp(idx)

    start = pd.Timestamp(dates[0])
    folds = []
    # Expanding-window stability checks. Final 10% remains untouched OOS.
    for i, train_frac in enumerate((0.45, 0.55, 0.65, 0.75), start=1):
        train_end = at(train_frac)
        val_end = at(min(train_frac + 0.10, 0.90))
        val_dates = [d for d in dates if train_end < d <= val_end]
        if not val_dates:
            continue
        val_start = pd.Timestamp(val_dates[0])
        folds.append({
            "fold": i,
            "train_start": start.date().isoformat(),
            "train_end": train_end.date().isoformat(),
            "validation_start": val_start.date().isoformat(),
            "validation_end": val_end.date().isoformat(),
        })
    return folds


def build_plan(df: pd.DataFrame, source_signature: str) -> dict:
    df = df.copy()
    df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")
    df = df[df["race_date"].notna()].copy()
    scope = pd.to_numeric(df["race_scope_cd"], errors="coerce")
    df = df[scope.isin([1, 2])].copy()
    if df.empty:
        return {"status": "BLOCKED", "updated": now(), "detail": "No domestic dated rows"}

    bounds = _split_bounds(df)
    stats = {name: _segment_stats(df, name, *bounds[name]) for name in bounds}
    total_races = int(df["race_id"].nunique())
    total_rows = int(len(df))
    date_min = pd.Timestamp(df["race_date"].min()).normalize()
    date_max = pd.Timestamp(df["race_date"].max()).normalize()
    span_days = int((date_max - date_min).days + 1)

    warnings: list[str] = []
    blockers: list[str] = []
    if total_races < 3000:
        blockers.append(f"total_races<{3000}: {total_races}")
    elif total_races < 8000:
        warnings.append(f"limited_total_races: {total_races}")
    if span_days < 365:
        warnings.append(f"short_time_span_days: {span_days}")

    for name in ("VALIDATION", "SELECTION", "TEST", "OOS"):
        s = stats[name]
        if s["races"] < 250:
            blockers.append(f"{name}_races<250: {s['races']}")
        for target in TARGETS:
            t = s["targets"].get(target, {})
            if t.get("positives", 0) < 100:
                blockers.append(f"{name}_{target}_positives<100: {t.get('positives', 0)}")
        for domain in ("JRA", "NAR"):
            if s["domains"].get(domain, {}).get("races", 0) < 100:
                warnings.append(f"{name}_{domain}_races<100")

    train_hist = stats["TRAIN"].get("history", {})
    if train_hist and train_hist.get("prior_3plus_rate", 0.0) < 0.35:
        warnings.append(f"low_train_prior_3plus_rate: {train_hist.get('prior_3plus_rate', 0.0):.3f}")

    status = "BLOCKED" if blockers else ("WARN" if warnings else "PASS")
    return {
        "version": 1,
        "status": status,
        "updated": now(),
        "source_signature": source_signature,
        "strategy": "chronological_race_count_balanced",
        "ratios": RATIOS,
        "date_range": {
            "start": date_min.date().isoformat(),
            "end": date_max.date().isoformat(),
            "span_days": span_days,
        },
        "population": {
            "rows": total_rows,
            "races": total_races,
            "horses": int(df["horse_id"].nunique()) if "horse_id" in df.columns else None,
            "jra_races": int(df[pd.to_numeric(df["race_scope_cd"], errors="coerce") == 1]["race_id"].nunique()),
            "nar_races": int(df[pd.to_numeric(df["race_scope_cd"], errors="coerce") == 2]["race_id"].nunique()),
        },
        "splits": stats,
        "walk_forward_folds": _walk_forward_folds(df),
        "gates": {
            "blockers": blockers,
            "warnings": warnings,
            "universal_model_allowed": not blockers,
            "domain_specialist_allowed": not blockers,
        },
        "oos_policy": "OOS split is report-only and never used for model selection",
    }


def write_profile(plan: dict) -> None:
    rows = []
    for split, s in (plan.get("splits") or {}).items():
        base = {
            "split": split,
            "start_date": s.get("start_date"),
            "end_date": s.get("end_date"),
            "days": s.get("days"),
            "rows": s.get("rows"),
            "races": s.get("races"),
            "horses": s.get("horses"),
            "jra_races": (s.get("domains") or {}).get("JRA", {}).get("races"),
            "nar_races": (s.get("domains") or {}).get("NAR", {}).get("races"),
            "prior_1plus_rate": (s.get("history") or {}).get("prior_1plus_rate"),
            "prior_3plus_rate": (s.get("history") or {}).get("prior_3plus_rate"),
            "prior_6plus_rate": (s.get("history") or {}).get("prior_6plus_rate"),
        }
        for target in TARGETS:
            t = (s.get("targets") or {}).get(target, {})
            base[f"{target}_labeled"] = t.get("labeled_rows")
            base[f"{target}_positives"] = t.get("positives")
        rows.append(base)
    pd.DataFrame(rows).to_csv(PROFILE, index=False, encoding="utf-8-sig")


def run_once() -> bool:
    src = DATA / "CORE-004_field_strength_v2.csv"
    if not src.exists():
        write_json(STATE, {"pid": os.getpid(), "updated": now(), "status": "WAITING", "detail": "CORE-004 missing"})
        return False
    sig = file_signature(src)
    old = read_json(PLAN, {}) or {}
    if old.get("source_signature") == sig and old.get("status") in {"PASS", "WARN", "BLOCKED"}:
        write_json(STATE, {
            "pid": os.getpid(), "updated": now(), "status": old.get("status"),
            "detail": "Temporal plan current", "races": (old.get("population") or {}).get("races"),
            "date_range": old.get("date_range"),
        })
        return old.get("status") != "BLOCKED"

    usecols = [
        "race_id", "race_horse_id", "horse_id", "race_date", "race_scope_cd",
        "label_win", "label_top2", "label_top3", "prior_start_count",
    ]
    df = pd.read_csv(src, usecols=lambda c: c in usecols, low_memory=False)
    plan = build_plan(df, sig)
    write_json(PLAN, plan)
    write_profile(plan)
    write_json(STATE, {
        "pid": os.getpid(), "updated": now(), "status": plan.get("status"),
        "detail": "Temporal/sample optimization complete",
        "races": (plan.get("population") or {}).get("races"),
        "date_range": plan.get("date_range"),
        "warnings": (plan.get("gates") or {}).get("warnings", []),
        "blockers": (plan.get("gates") or {}).get("blockers", []),
    })
    log(f"TEMPORAL PLAN {plan.get('status')} races={(plan.get('population') or {}).get('races')} range={plan.get('date_range')}")
    return plan.get("status") != "BLOCKED"


def main() -> None:
    log("TEMPORAL SAMPLE OPTIMIZER START")
    while True:
        try:
            run_once()
        except Exception as e:
            log(f"ERROR {e!r}")
            write_json(STATE, {"pid": os.getpid(), "updated": now(), "status": "BLOCKED", "detail": repr(e)})
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
