from __future__ import annotations

import hashlib
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get("THE_JOCKEY_RESEARCH_ROOT", Path.home() / "Downloads" / "THE-JOCKEY-RESEARCH"))
CORE = ROOT / "CORE"
DATA = CORE / "data"
REPORTS = CORE / "reports"
MODELS = CORE / "models"
META = CORE / "meta"
LOG = ROOT / "logs" / "meta_research_director.log"
STATE = ROOT / "checkpoints" / "meta_research_director_state.json"
REGISTRY = REPORTS / "model_registry.json"
CYCLE = META / "last_cycle.json"

for p in (META, LOG.parent, STATE.parent, MODELS):
    p.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now().astimezone().isoformat()


def log(msg=""):
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_state(status, detail="", extra=None):
    payload = {"updated": now(), "status": status, "detail": detail, "pid": os.getpid()}
    if extra:
        payload.update(extra)
    save_json(STATE, payload)


def file_sig(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def auc_rank(y, p):
    t = pd.DataFrame({"y": y, "p": p}).dropna()
    if t.empty:
        return np.nan
    yv = t.y.astype(int).to_numpy()
    pv = t.p.astype(float).to_numpy()
    np_ = int((yv == 1).sum())
    nn = int((yv == 0).sum())
    if np_ == 0 or nn == 0:
        return np.nan
    ranks = pd.Series(pv).rank(method="average").to_numpy()
    return float((ranks[yv == 1].sum() - np_ * (np_ + 1) / 2) / (np_ * nn))


def logloss(y, p):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def feature_sets(df):
    baseline = [c for c in [
        "race_scope_cd", "racecourse_cd", "distance_m", "track_cd", "horse_age", "sex_cd",
        "carried_weight_kg", "frame_no", "horse_no", "jockey_cd", "trainer_cd"
    ] if c in df.columns]
    historical = baseline + [c for c in [
        "prior_start_count", "days_since_last_run", "prior_win_rate", "prior_top2_rate", "prior_top3_rate",
        "prior_avg_finish_pct", "prior_avg_time_diff", "prior_avg_last3f", "prior_avg_corner4_pct",
        "recent3_time_diff_mean", "recent5_time_diff_mean", "recent3_finish_pct_mean", "recent5_finish_pct_mean",
        "recent3_last3f_mean", "recent5_last3f_mean", "recent3_corner4_pct_mean", "recent5_corner4_pct_mean",
        "same_distance_prior_count", "same_distance_prior_avg_time_diff", "same_track_prior_count",
        "same_track_prior_avg_time_diff", "same_racecourse_prior_count", "same_racecourse_prior_avg_time_diff",
        "same_course_surface_prior_count", "same_course_surface_prior_avg_time_diff"
    ] if c in df.columns]
    field = historical + [c for c in [
        "horse_pre_ability_v1", "field_strength_v2", "field_strength_coverage", "ability_vs_field",
        "ability_percentile_in_race", "last_field_strength", "recent3_field_strength_mean",
        "recent5_field_strength_mean", "prior_avg_field_strength", "field_strength_trend"
    ] if c in df.columns]
    compact = [c for c in field if c not in {"horse_no", "frame_no"}]
    return {"BASELINE": baseline, "HISTORICAL": historical, "FIELD_STRENGTH": field, "COMPACT_FIELD": compact}


def challenger_configs():
    return [
        {"name": "BALANCED_D5", "depth": 5, "learning_rate": 0.04, "l2_leaf_reg": 5, "iterations": 800},
        {"name": "BALANCED_D7", "depth": 7, "learning_rate": 0.035, "l2_leaf_reg": 6, "iterations": 900},
        {"name": "REGULARIZED", "depth": 6, "learning_rate": 0.03, "l2_leaf_reg": 10, "iterations": 1000},
        {"name": "FAST", "depth": 6, "learning_rate": 0.05, "l2_leaf_reg": 4, "iterations": 650},
    ]


def baseline_metrics(metrics: pd.DataFrame, target: str, variant: str):
    out = {}
    for split in ("TEST_2025", "OOS_2026"):
        r = metrics[(metrics.target == target) & (metrics.variant == variant) & (metrics.split == split)]
        if not r.empty:
            out[split] = {"logloss": float(r.iloc[0].logloss), "auc": float(r.iloc[0].auc)}
    return out


def domain_metrics(part, ycol, pred):
    rows = []
    tmp = part[["race_scope_cd", ycol]].copy()
    tmp["pred"] = pred
    for domain, code in (("JRA", 1), ("NAR", 2)):
        x = tmp[tmp.race_scope_cd == code].dropna()
        if len(x) < 100:
            continue
        rows.append({"domain": domain, "logloss": logloss(x[ycol], x.pred), "auc": auc_rank(x[ycol], x.pred), "rows": int(len(x))})
    return rows


def run_cycle():
    decision_path = REPORTS / "CORE-005_decision.json"
    metrics_path = REPORTS / "CORE-005_universal_ability_metrics.csv"
    src = DATA / "CORE-004_field_strength_v2.csv"

    decision = load_json(decision_path, {})
    if decision.get("status") != "PASS" or not metrics_path.exists() or not src.exists():
        write_state("WAITING", "CORE-005 PASS / CORE-004 data required")
        return False

    signature = file_sig(src)
    previous = load_json(CYCLE, {})
    if previous.get("data_signature") == signature and previous.get("status") == "COMPLETE":
        write_state("IDLE", "No new data; last improvement cycle already complete")
        return True

    try:
        from catboost import CatBoostClassifier
    except Exception as e:
        write_state("BLOCKED", f"catboost unavailable: {e}")
        return False

    write_state("RUNNING", "Champion/Challenger self-improvement cycle")
    log("META CYCLE START")
    df = pd.read_csv(src, low_memory=False)
    df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")
    df["year"] = df["race_date"].dt.year
    df = df[df["race_scope_cd"].isin([1, 2])].copy()

    train = df[df.year.between(2017, 2022)]
    val = df[df.year == 2023]
    test = df[df.year == 2025]
    oos = df[df.year == 2026]
    metrics = pd.read_csv(metrics_path)
    sets = feature_sets(df)
    cats_all = {"race_scope_cd", "racecourse_cd", "track_cd", "sex_cd", "jockey_cd", "trainer_cd"}

    results = []
    promotions = {}
    targets = ["label_win", "label_top2", "label_top3"]

    for target in targets:
        champ = (decision.get("champion") or {}).get(target) or {}
        champ_variant = champ.get("variant", "FIELD_STRENGTH")
        base = baseline_metrics(metrics, target, champ_variant)
        best = None

        for feature_name in ("FIELD_STRENGTH", "COMPACT_FIELD"):
            feats = sets[feature_name]
            if not feats:
                continue
            cat = [c for c in feats if c in cats_all]

            for cfg in challenger_configs():
                tr = train[train[target].notna()].copy()
                va = val[val[target].notna()].copy()
                te = test[test[target].notna()].copy()
                oo = oos[oos[target].notna()].copy()
                for c in cat:
                    for part in (tr, va, te, oo):
                        part[c] = part[c].fillna("MISSING").astype(str)

                model = CatBoostClassifier(
                    loss_function="Logloss", eval_metric="Logloss", random_seed=20261004,
                    verbose=False, allow_writing_files=False, depth=cfg["depth"],
                    learning_rate=cfg["learning_rate"], l2_leaf_reg=cfg["l2_leaf_reg"],
                    iterations=cfg["iterations"]
                )
                model.fit(tr[feats], tr[target], cat_features=cat, eval_set=(va[feats], va[target]), early_stopping_rounds=100, use_best_model=True)

                pv = model.predict_proba(va[feats])[:, 1]
                pt = model.predict_proba(te[feats])[:, 1]
                po = model.predict_proba(oo[feats])[:, 1]
                row = {
                    "target": target, "feature_set": feature_name, "config": cfg["name"],
                    "val_logloss": logloss(va[target], pv), "val_auc": auc_rank(va[target], pv),
                    "test_logloss": logloss(te[target], pt), "test_auc": auc_rank(te[target], pt),
                    "oos_logloss": logloss(oo[target], po), "oos_auc": auc_rank(oo[target], po),
                    "trees": int(model.tree_count_), "features": len(feats),
                }
                row["domains_test"] = domain_metrics(te, target, pt)
                row["domains_oos"] = domain_metrics(oo, target, po)

                # Promotion gate: meaningful average gain and no material regression on either temporal holdout.
                if "TEST_2025" in base and "OOS_2026" in base:
                    gain_test = base["TEST_2025"]["logloss"] - row["test_logloss"]
                    gain_oos = base["OOS_2026"]["logloss"] - row["oos_logloss"]
                    avg_gain = (gain_test + gain_oos) / 2
                    auc_ok = row["test_auc"] >= base["TEST_2025"]["auc"] - 0.002 and row["oos_auc"] >= base["OOS_2026"]["auc"] - 0.002
                    temporal_ok = gain_test >= -0.0015 and gain_oos >= -0.0015
                    row["promotable"] = bool(avg_gain >= 0.001 and auc_ok and temporal_ok)
                    row["avg_logloss_gain"] = float(avg_gain)
                else:
                    row["promotable"] = False
                    row["avg_logloss_gain"] = np.nan

                results.append(row)
                if row["promotable"] and (best is None or row["avg_logloss_gain"] > best["avg_logloss_gain"]):
                    model_dir = MODELS / "META" / target
                    model_dir.mkdir(parents=True, exist_ok=True)
                    path = model_dir / f"{feature_name}_{cfg['name']}.cbm"
                    model.save_model(str(path))
                    best = {**row, "model_path": str(path), "features_list": feats, "cat_features": cat}

        if best:
            promotions[target] = best

    flat = []
    for r in results:
        x = {k: v for k, v in r.items() if not isinstance(v, list)}
        flat.append(x)
    pd.DataFrame(flat).to_csv(REPORTS / "META_challenger_metrics.csv", index=False, encoding="utf-8-sig")

    registry = load_json(REGISTRY, {"version": 1, "targets": {}})
    for target in targets:
        entry = registry.setdefault("targets", {}).setdefault(target, {})
        if target in promotions:
            entry.update({
                "status": "PROMOTED_CHALLENGER",
                "promoted_at": now(),
                "source": "META",
                "model_path": promotions[target]["model_path"],
                "feature_set": promotions[target]["feature_set"],
                "config": promotions[target]["config"],
                "avg_logloss_gain": promotions[target]["avg_logloss_gain"],
                "features": promotions[target]["features_list"],
                "cat_features": promotions[target]["cat_features"],
            })
        else:
            entry.setdefault("status", "KEEP_CORE005_CHAMPION")
            entry.setdefault("source", "CORE-005")
    registry["updated"] = now()
    save_json(REGISTRY, registry)

    cycle = {
        "status": "COMPLETE", "updated": now(), "data_signature": signature,
        "challengers_tested": len(results), "promotions": list(promotions.keys()),
        "registry": str(REGISTRY)
    }
    save_json(CYCLE, cycle)
    write_state("COMPLETE", f"challengers={len(results)} promotions={list(promotions.keys())}", cycle)
    log(f"META CYCLE COMPLETE challengers={len(results)} promotions={list(promotions.keys())}")
    return True


def main():
    log("Meta Research Director started")
    while True:
        try:
            run_cycle()
        except KeyboardInterrupt:
            log("Meta Research Director stopped")
            return
        except Exception:
            err = traceback.format_exc()
            log(err)
            write_state("BLOCKED", err[-1800:])
        time.sleep(600)


if __name__ == "__main__":
    main()
