from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
CORE = ROOT / "CORE"
DATA = CORE / "data"
REPORTS = CORE / "reports"
STATE = ROOT / "checkpoints" / "feature_research_director_state.json"
LOG = ROOT / "logs" / "feature_research_director.log"
SRC = DATA / "CORE-004_field_strength_v2.csv"
OUT = DATA / "FEATURE-RESEARCH_candidates.csv"
CATALOG = REPORTS / "feature_research_catalog.csv"
DECISION = REPORTS / "feature_research_decision.json"
PROMOTED = REPORTS / "promoted_feature_contract.json"

for p in (DATA, REPORTS, STATE.parent, LOG.parent):
    p.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now().astimezone().isoformat()


def log(msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def signature(path: Path) -> str:
    h = hashlib.sha256()
    st = path.stat()
    h.update(str(st.st_size).encode())
    h.update(str(int(st.st_mtime)).encode())
    return h.hexdigest()


def auc_rank(y, score) -> float:
    t = pd.DataFrame({"y": y, "s": score}).dropna()
    if t.empty:
        return float("nan")
    yv = t["y"].astype(int).to_numpy()
    sv = t["s"].astype(float).to_numpy()
    pos = int((yv == 1).sum())
    neg = int((yv == 0).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    ranks = pd.Series(sv).rank(method="average").to_numpy()
    return float((ranks[yv == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def safe_div(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce").replace(0, np.nan)
    return a / b


def generate_candidates(df: pd.DataFrame) -> dict[str, pd.Series]:
    c: dict[str, pd.Series] = {}
    def has(*cols):
        return all(x in df.columns for x in cols)

    if has("recent3_time_diff_mean", "recent5_time_diff_mean"):
        c["form_time_momentum_3v5"] = pd.to_numeric(df["recent5_time_diff_mean"], errors="coerce") - pd.to_numeric(df["recent3_time_diff_mean"], errors="coerce")
    if has("recent3_finish_pct_mean", "recent5_finish_pct_mean"):
        c["form_finish_momentum_3v5"] = pd.to_numeric(df["recent5_finish_pct_mean"], errors="coerce") - pd.to_numeric(df["recent3_finish_pct_mean"], errors="coerce")
    if has("recent3_last3f_mean", "recent5_last3f_mean"):
        c["last3f_momentum_3v5"] = pd.to_numeric(df["recent5_last3f_mean"], errors="coerce") - pd.to_numeric(df["recent3_last3f_mean"], errors="coerce")
    if has("prior_start_count"):
        c["experience_log1p"] = np.log1p(pd.to_numeric(df["prior_start_count"], errors="coerce").clip(lower=0))
    if has("days_since_last_run"):
        c["rest_log1p"] = np.log1p(pd.to_numeric(df["days_since_last_run"], errors="coerce").clip(lower=0))
        c["rest_ideal_band"] = ((pd.to_numeric(df["days_since_last_run"], errors="coerce") >= 14) & (pd.to_numeric(df["days_since_last_run"], errors="coerce") <= 70)).astype(float)
    if has("prior_win_rate", "prior_top3_rate"):
        c["conversion_win_given_top3_proxy"] = safe_div(df["prior_win_rate"], df["prior_top3_rate"])
    if has("prior_top2_rate", "prior_top3_rate"):
        c["conversion_top2_given_top3_proxy"] = safe_div(df["prior_top2_rate"], df["prior_top3_rate"])
    if has("same_distance_prior_count", "prior_start_count"):
        c["distance_experience_share"] = safe_div(df["same_distance_prior_count"], df["prior_start_count"])
    if has("same_track_prior_count", "prior_start_count"):
        c["track_experience_share"] = safe_div(df["same_track_prior_count"], df["prior_start_count"])
    if has("same_racecourse_prior_count", "prior_start_count"):
        c["racecourse_experience_share"] = safe_div(df["same_racecourse_prior_count"], df["prior_start_count"])
    if has("same_course_surface_prior_count", "prior_start_count"):
        c["course_surface_experience_share"] = safe_div(df["same_course_surface_prior_count"], df["prior_start_count"])
    if has("prior_avg_time_diff", "same_distance_prior_avg_time_diff"):
        c["distance_time_diff_edge"] = pd.to_numeric(df["prior_avg_time_diff"], errors="coerce") - pd.to_numeric(df["same_distance_prior_avg_time_diff"], errors="coerce")
    if has("prior_avg_time_diff", "same_track_prior_avg_time_diff"):
        c["track_time_diff_edge"] = pd.to_numeric(df["prior_avg_time_diff"], errors="coerce") - pd.to_numeric(df["same_track_prior_avg_time_diff"], errors="coerce")
    if has("prior_avg_time_diff", "same_racecourse_prior_avg_time_diff"):
        c["racecourse_time_diff_edge"] = pd.to_numeric(df["prior_avg_time_diff"], errors="coerce") - pd.to_numeric(df["same_racecourse_prior_avg_time_diff"], errors="coerce")
    if has("horse_pre_ability_v1", "field_strength_v2"):
        c["ability_field_ratio"] = safe_div(df["horse_pre_ability_v1"], df["field_strength_v2"])
    if has("ability_vs_field", "field_strength_coverage"):
        c["ability_edge_coverage_weighted"] = pd.to_numeric(df["ability_vs_field"], errors="coerce") * pd.to_numeric(df["field_strength_coverage"], errors="coerce")
    if has("prior_avg_field_strength", "field_strength_v2"):
        c["field_step_up"] = pd.to_numeric(df["field_strength_v2"], errors="coerce") - pd.to_numeric(df["prior_avg_field_strength"], errors="coerce")
    if has("last_field_strength", "recent5_field_strength_mean"):
        c["field_strength_short_term_shift"] = pd.to_numeric(df["last_field_strength"], errors="coerce") - pd.to_numeric(df["recent5_field_strength_mean"], errors="coerce")
    return c


def redundancy_score(df: pd.DataFrame, candidate: pd.Series, existing: list[str]) -> float:
    vals = []
    c = pd.to_numeric(candidate, errors="coerce")
    for col in existing:
        if col not in df.columns:
            continue
        x = pd.to_numeric(df[col], errors="coerce")
        pair = pd.concat([c, x], axis=1).dropna()
        if len(pair) < 500:
            continue
        corr = pair.corr(method="spearman").iloc[0, 1]
        if pd.notna(corr):
            vals.append(abs(float(corr)))
    return max(vals) if vals else 0.0


def run_once() -> bool:
    if not SRC.exists():
        save_json(STATE, {"updated": now(), "status": "WAITING", "reason": f"missing {SRC}"})
        return False

    sig = signature(SRC)
    old = {}
    if DECISION.exists():
        try:
            old = json.loads(DECISION.read_text(encoding="utf-8-sig"))
        except Exception:
            old = {}
    if old.get("data_signature") == sig and old.get("status") == "PASS":
        save_json(STATE, {"updated": now(), "status": "IDLE", "detail": "same data signature; no rerun", "pid": os.getpid()})
        return True

    save_json(STATE, {"updated": now(), "status": "RUNNING", "pid": os.getpid()})
    log("FEATURE RESEARCH START")
    df = pd.read_csv(SRC, low_memory=False)
    df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")
    df["year"] = df["race_date"].dt.year

    # Conservative safe race mask: every runner labeled and exactly one winner.
    labeled = df["finish_order"].notna() if "finish_order" in df.columns else df["label_win"].notna()
    winner = pd.to_numeric(df.get("label_win"), errors="coerce").fillna(0)
    race_all_labeled = labeled.groupby(df["race_id"]).transform("all")
    race_one_winner = winner.groupby(df["race_id"]).transform("sum").eq(1)
    safe = race_all_labeled & race_one_winner & df["race_scope_cd"].isin([1, 2])
    work = df.loc[safe].copy()

    candidates = generate_candidates(work)
    if not candidates:
        save_json(STATE, {"updated": now(), "status": "BLOCKED", "detail": "no candidate formulas available", "pid": os.getpid()})
        return False

    existing_numeric = [c for c in [
        "prior_win_rate", "prior_top2_rate", "prior_top3_rate", "prior_avg_finish_pct", "prior_avg_time_diff",
        "recent3_time_diff_mean", "recent5_time_diff_mean", "recent3_finish_pct_mean", "recent5_finish_pct_mean",
        "horse_pre_ability_v1", "field_strength_v2", "ability_vs_field", "ability_percentile_in_race",
        "prior_avg_field_strength", "field_strength_trend"
    ] if c in work.columns]

    rows = []
    promoted = []
    for name, series in candidates.items():
        s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        coverage = float(s.notna().mean())
        unique = int(s.nunique(dropna=True))
        redundancy = redundancy_score(work, s, existing_numeric)
        metrics = {}
        aucs = []
        for year in (2023, 2025, 2026):
            part = work["year"].eq(year)
            if int(part.sum()) == 0:
                continue
            for target in ("label_win", "label_top2", "label_top3"):
                if target not in work.columns:
                    continue
                auc = auc_rank(work.loc[part, target], s.loc[part])
                if pd.notna(auc):
                    auc = max(float(auc), 1.0 - float(auc))
                    metrics[f"auc_{target}_{year}"] = auc
                    aucs.append(auc)
        mean_auc = float(np.mean(aucs)) if aucs else float("nan")
        min_auc = float(np.min(aucs)) if aucs else float("nan")
        decision = "REJECT"
        reason = []
        if coverage < 0.55:
            reason.append("LOW_COVERAGE")
        if unique < 5:
            reason.append("LOW_VARIANCE")
        if redundancy >= 0.98:
            reason.append("REDUNDANT")
        if not aucs or mean_auc < 0.515:
            reason.append("WEAK_SIGNAL")
        if aucs and min_auc < 0.505:
            reason.append("UNSTABLE")
        if not reason:
            decision = "PROMOTE_CANDIDATE"
            promoted.append(name)
        rows.append({
            "feature": name,
            "coverage": coverage,
            "unique": unique,
            "max_abs_spearman_existing": redundancy,
            "mean_abs_auc": mean_auc,
            "min_abs_auc": min_auc,
            "decision": decision,
            "reason": "|".join(reason) if reason else "PASS_TRIAGE",
            **metrics,
        })
        work[name] = s

    catalog = pd.DataFrame(rows).sort_values(["decision", "mean_abs_auc"], ascending=[True, False])
    catalog.to_csv(CATALOG, index=False, encoding="utf-8-sig")

    # Persist only IDs plus promoted candidate columns to keep artifact compact.
    keep = [c for c in ["race_id", "race_horse_id", "horse_id", "race_date", "race_scope_cd", "label_win", "label_top2", "label_top3"] if c in work.columns] + promoted
    work[keep].to_csv(OUT, index=False, encoding="utf-8-sig")

    contract = {
        "updated": now(),
        "data_signature": sig,
        "source": str(SRC),
        "safe_rows": int(len(work)),
        "safe_races": int(work["race_id"].nunique()),
        "candidate_count": int(len(rows)),
        "promoted_candidate_count": int(len(promoted)),
        "promoted_candidates": promoted,
        "policy": {
            "coverage_min": 0.55,
            "unique_min": 5,
            "max_abs_spearman_existing_lt": 0.98,
            "mean_abs_auc_min": 0.515,
            "min_abs_auc_min": 0.505,
            "evaluation_years": [2023, 2025, 2026],
            "targets": ["WIN", "TOP2", "TOP3"],
            "note": "PROMOTE_CANDIDATE means eligible for incremental model challenge; not direct production promotion."
        }
    }
    save_json(PROMOTED, contract)
    save_json(DECISION, {"status": "PASS", **contract})
    save_json(STATE, {"updated": now(), "status": "IDLE", "pid": os.getpid(), "promoted_candidate_count": len(promoted)})
    log(f"FEATURE RESEARCH PASS candidates={len(rows)} promoted={len(promoted)}")
    return True


def main() -> None:
    continuous = "--once" not in sys.argv
    log("Feature Research Director started")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            return
        except Exception as e:
            log(f"ERROR {e!r}")
            save_json(STATE, {"updated": now(), "status": "BLOCKED", "detail": repr(e), "pid": os.getpid()})
        if not continuous:
            return
        time.sleep(300)


if __name__ == "__main__":
    main()
