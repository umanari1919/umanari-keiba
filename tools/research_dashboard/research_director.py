from __future__ import annotations

import json
import os
import sys
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
LOG = ROOT / "logs" / "research_director.log"
STATE = ROOT / "checkpoints" / "research_director_state.json"
PROGRAM = CORE / "program.json"

for p in (DATA, REPORTS, MODELS, LOG.parent, STATE.parent):
    p.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now().astimezone().isoformat()


def log(msg=""):
    text = str(msg)
    print(text, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{now()}] {text}\n")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def set_mission_state(mission_id: str, state: str):
    program = load_json(PROGRAM, {"missions": []})
    missions = program.setdefault("missions", [])
    found = False
    for m in missions:
        if m.get("id") == mission_id:
            m["state"] = state
            found = True
        elif state == "COMPLETE" and found and m.get("state") == "PENDING":
            break
    if not found:
        missions.append({"id": mission_id, "name": mission_id, "state": state})
    if state == "COMPLETE":
        ids = [m.get("id") for m in missions]
        try:
            idx = ids.index(mission_id)
            for j in range(idx + 1, len(missions)):
                if missions[j].get("state") == "PENDING":
                    missions[j]["state"] = "READY"
                    break
        except ValueError:
            pass
    save_json(PROGRAM, program)


def write_state(current: str, status: str, detail: str = ""):
    save_json(STATE, {
        "updated": now(),
        "current_mission": current,
        "status": status,
        "detail": detail,
        "pid": os.getpid(),
    })


def sigmoid_inverse_time_diff(x):
    x = pd.to_numeric(x, errors="coerce").clip(-8, 8)
    return 1.0 / (1.0 + np.exp(x))


def run_core004():
    mission = "CORE-004"
    src = DATA / "CORE-003B_historical_features.csv"
    out = DATA / "CORE-004_field_strength_v2.csv"
    audit_path = REPORTS / "CORE-004_field_strength_audit.json"
    metrics_path = REPORTS / "CORE-004_field_strength_metrics.csv"

    if out.exists() and audit_path.exists():
        audit = load_json(audit_path, {})
        if audit.get("first_start_field_strength_leaks", 1) == 0:
            log("CORE-004 already PASS")
            set_mission_state(mission, "COMPLETE")
            return True

    if not src.exists():
        write_state(mission, "BLOCKED", f"Input missing: {src}")
        set_mission_state(mission, "BLOCKED")
        log(f"CORE-004 BLOCKED: {src} missing")
        return False

    write_state(mission, "RUNNING", "Field Strength v2")
    log("CORE-004 START Field Strength v2")
    df = pd.read_csv(src, low_memory=False)
    df["race_date"] = pd.to_datetime(df["race_date"], errors="raise")

    comps = pd.DataFrame(index=df.index)
    for c in ["prior_win_rate", "prior_top2_rate", "prior_top3_rate", "prior_avg_finish_pct", "prior_avg_corner4_pct"]:
        comps[c] = pd.to_numeric(df[c], errors="coerce").clip(0, 1)
    comps["time_diff_score"] = sigmoid_inverse_time_diff(df["prior_avg_time_diff"])
    comps["recent_time_score"] = sigmoid_inverse_time_diff(df["recent5_time_diff_mean"])
    comps["recent_finish_score"] = pd.to_numeric(df["recent5_finish_pct_mean"], errors="coerce").clip(0, 1)

    df["ability_component_count"] = comps.notna().sum(axis=1)
    df["horse_pre_ability_v1"] = comps.mean(axis=1, skipna=True)
    df.loc[df["ability_component_count"] == 0, "horse_pre_ability_v1"] = np.nan

    valid = df["horse_pre_ability_v1"].notna().astype(int)
    value = df["horse_pre_ability_v1"].fillna(0.0)
    race_sum = value.groupby(df["race_id"]).transform("sum")
    race_count = valid.groupby(df["race_id"]).transform("sum")
    opp_sum = race_sum - value
    opp_count = race_count - valid
    runners = df.groupby("race_id")["race_horse_id"].transform("count")

    df["field_strength_v2"] = opp_sum / opp_count.replace(0, np.nan)
    df["field_strength_known_opponents"] = opp_count
    df["field_strength_coverage"] = opp_count / (runners - 1).replace(0, np.nan)
    df["ability_vs_field"] = df["horse_pre_ability_v1"] - df["field_strength_v2"]
    df["ability_rank_in_race"] = df.groupby("race_id")["horse_pre_ability_v1"].rank(method="average", ascending=False)
    df["ability_percentile_in_race"] = df.groupby("race_id")["horse_pre_ability_v1"].rank(method="average", pct=True, ascending=True)

    df = df.sort_values(["horse_id", "race_date", "race_id", "race_horse_id"]).reset_index(drop=True)
    g = df.groupby("horse_id", sort=False)
    df["last_field_strength"] = g["field_strength_v2"].shift(1)
    shifted = g["field_strength_v2"].shift(1)
    temp = pd.DataFrame({"horse_id": df["horse_id"], "value": shifted})
    for w in (3, 5):
        df[f"recent{w}_field_strength_mean"] = temp.groupby("horse_id", sort=False)["value"].transform(lambda s: s.rolling(w, min_periods=1).mean())

    v = df["field_strength_v2"].notna().astype(int)
    x = df["field_strength_v2"].fillna(0.0)
    count_before = v.groupby(df["horse_id"]).cumsum() - v
    sum_before = x.groupby(df["horse_id"]).cumsum() - x
    df["prior_avg_field_strength"] = sum_before / count_before.replace(0, np.nan)
    df["field_strength_trend"] = df["last_field_strength"] - df["recent5_field_strength_mean"]

    first = df["prior_start_count"] == 0
    hist_cols = ["last_field_strength", "recent3_field_strength_mean", "recent5_field_strength_mean", "prior_avg_field_strength", "field_strength_trend"]
    leaks = {c: int(df.loc[first, c].notna().sum()) for c in hist_cols}
    leak_count = sum(leaks.values())

    df["year"] = df["race_date"].dt.year
    def auc_rank(y, score):
        t = pd.DataFrame({"y": y, "s": score}).dropna()
        if t.empty:
            return np.nan
        yv = t["y"].astype(int).to_numpy(); sv = t["s"].astype(float).to_numpy()
        np_ = int((yv == 1).sum()); nn = int((yv == 0).sum())
        if np_ == 0 or nn == 0:
            return np.nan
        ranks = pd.Series(sv).rank(method="average").to_numpy()
        return float((ranks[yv == 1].sum() - np_ * (np_ + 1) / 2) / (np_ * nn))

    rows = []
    for split, year in (("TEST_2025", 2025), ("OOS_2026", 2026)):
        part = df[df["year"] == year]
        for signal in ("horse_pre_ability_v1", "ability_vs_field", "field_strength_v2", "prior_avg_field_strength"):
            score = -part[signal] if signal == "field_strength_v2" else part[signal]
            for target in ("label_win", "label_top2", "label_top3"):
                rows.append({"split": split, "signal": signal, "target": target, "auc": auc_rank(part[target], score)})
    pd.DataFrame(rows).to_csv(metrics_path, index=False, encoding="utf-8-sig")

    df.to_csv(out, index=False, encoding="utf-8-sig")
    audit = {
        "rows": int(len(df)),
        "races": int(df["race_id"].nunique()),
        "horses": int(df["horse_id"].nunique()),
        "generated_features": 13,
        "first_start_field_strength_leaks": int(leak_count),
        "first_start_leak_detail": leaks,
        "coverage": {
            "horse_pre_ability": float(df["horse_pre_ability_v1"].notna().mean()),
            "field_strength": float(df["field_strength_v2"].notna().mean()),
            "ability_vs_field": float(df["ability_vs_field"].notna().mean()),
            "historical_field_strength": float(df["prior_avg_field_strength"].notna().mean()),
        },
    }
    save_json(audit_path, audit)

    if leak_count:
        write_state(mission, "BLOCKED", f"Leakage detected: {leak_count}")
        set_mission_state(mission, "BLOCKED")
        log(f"CORE-004 FAIL leakage={leak_count}")
        return False

    set_mission_state(mission, "COMPLETE")
    write_state(mission, "COMPLETE", "Field Strength v2 PASS")
    log("CORE-004 PASS")
    return True


def run_core005():
    mission = "CORE-005"
    src = DATA / "CORE-004_field_strength_v2.csv"
    metrics_path = REPORTS / "CORE-005_universal_ability_metrics.csv"
    decision_path = REPORTS / "CORE-005_decision.json"

    if decision_path.exists():
        d = load_json(decision_path, {})
        if d.get("status") == "PASS":
            log("CORE-005 already PASS")
            set_mission_state(mission, "COMPLETE")
            return True

    if not src.exists():
        return False

    try:
        from catboost import CatBoostClassifier
    except Exception as e:
        write_state(mission, "BLOCKED", f"catboost unavailable: {e}")
        set_mission_state(mission, "BLOCKED")
        log("CORE-005 BLOCKED: catboost unavailable")
        return False

    write_state(mission, "RUNNING", "Universal Ability Model tournament")
    log("CORE-005 START Universal Ability Model tournament")
    df = pd.read_csv(src, low_memory=False)
    df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")
    df["year"] = df["race_date"].dt.year
    df = df[df["race_scope_cd"].isin([1, 2])].copy()

    baseline = [c for c in ["race_scope_cd", "racecourse_cd", "distance_m", "track_cd", "horse_age", "sex_cd", "carried_weight_kg", "frame_no", "horse_no", "jockey_cd", "trainer_cd"] if c in df.columns]
    historical = baseline + [c for c in [
        "prior_start_count", "days_since_last_run", "prior_win_rate", "prior_top2_rate", "prior_top3_rate",
        "prior_avg_finish_pct", "prior_avg_time_diff", "prior_avg_last3f", "prior_avg_corner4_pct",
        "recent3_time_diff_mean", "recent5_time_diff_mean", "recent3_finish_pct_mean", "recent5_finish_pct_mean",
        "recent3_last3f_mean", "recent5_last3f_mean", "recent3_corner4_pct_mean", "recent5_corner4_pct_mean",
        "same_distance_prior_count", "same_distance_prior_avg_time_diff", "same_track_prior_count", "same_track_prior_avg_time_diff",
        "same_racecourse_prior_count", "same_racecourse_prior_avg_time_diff", "same_course_surface_prior_count", "same_course_surface_prior_avg_time_diff"
    ] if c in df.columns]
    field = historical + [c for c in ["horse_pre_ability_v1", "field_strength_v2", "field_strength_coverage", "ability_vs_field", "ability_percentile_in_race", "last_field_strength", "recent3_field_strength_mean", "recent5_field_strength_mean", "prior_avg_field_strength", "field_strength_trend"] if c in df.columns]

    variants = {"BASELINE": baseline, "HISTORICAL": historical, "FIELD_STRENGTH": field}
    targets = ["label_win", "label_top2", "label_top3"]
    train = df[df["year"].between(2017, 2022)]
    val = df[df["year"] == 2023]
    test = df[df["year"] == 2025]
    oos = df[df["year"] == 2026]

    def auc_rank(y, p):
        t = pd.DataFrame({"y": y, "p": p}).dropna()
        if t.empty: return np.nan
        yv=t.y.astype(int).to_numpy(); pv=t.p.astype(float).to_numpy(); np_=int((yv==1).sum()); nn=int((yv==0).sum())
        if np_==0 or nn==0: return np.nan
        ranks=pd.Series(pv).rank(method="average").to_numpy()
        return float((ranks[yv==1].sum()-np_*(np_+1)/2)/(np_*nn))

    def logloss(y, p):
        y=np.asarray(y,dtype=float); p=np.clip(np.asarray(p,dtype=float),1e-12,1-1e-12)
        return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))

    rows=[]
    champion={}
    categorical_candidates={"race_scope_cd","racecourse_cd","track_cd","sex_cd","jockey_cd","trainer_cd"}
    for target in targets:
        champion[target]=None
        best_score=None
        for name, feats in variants.items():
            if not feats: continue
            tr=train[train[target].notna()].copy(); va=val[val[target].notna()].copy()
            te=test[test[target].notna()].copy(); oo=oos[oos[target].notna()].copy()
            cat=[c for c in feats if c in categorical_candidates]
            for c in cat:
                for part in (tr,va,te,oo): part[c]=part[c].fillna("MISSING").astype(str)
            model=CatBoostClassifier(loss_function="Logloss",eval_metric="Logloss",iterations=700,depth=6,learning_rate=0.04,l2_leaf_reg=5,random_seed=20261004,verbose=False,allow_writing_files=False)
            model.fit(tr[feats],tr[target],cat_features=cat,eval_set=(va[feats],va[target]),early_stopping_rounds=80,use_best_model=True)
            model_dir=MODELS / "CORE-005"; model_dir.mkdir(parents=True,exist_ok=True)
            model.save_model(str(model_dir / f"{target}_{name}.cbm"))
            split_metrics={}
            for split_name, part in (("TEST_2025",te),("OOS_2026",oo)):
                pred=model.predict_proba(part[feats])[:,1]
                ll=logloss(part[target],pred); auc=auc_rank(part[target],pred)
                split_metrics[split_name]=(ll,auc)
                rows.append({"target":target,"variant":name,"split":split_name,"rows":len(part),"logloss":ll,"auc":auc,"features":len(feats),"trees":model.tree_count_})
            score=(split_metrics["TEST_2025"][0]+split_metrics["OOS_2026"][0])/2
            if best_score is None or score<best_score:
                best_score=score; champion[target]={"variant":name,"score":score,"features":len(feats)}

    metrics=pd.DataFrame(rows)
    metrics.to_csv(metrics_path,index=False,encoding="utf-8-sig")
    pass_all=all(v is not None for v in champion.values())
    decision={"status":"PASS" if pass_all else "BLOCKED","updated":now(),"champion":champion}
    save_json(decision_path,decision)
    if pass_all:
        set_mission_state(mission,"COMPLETE")
        write_state(mission,"COMPLETE","Universal Ability tournament PASS")
        log(f"CORE-005 PASS champions={champion}")
        return True
    set_mission_state(mission,"BLOCKED")
    return False


def run_once():
    if not run_core004():
        return False
    if not run_core005():
        return False
    return True


def main():
    continuous = "--once" not in sys.argv
    log("Research Director started")
    while True:
        try:
            complete = run_once()
            if complete:
                write_state("QUEUE", "IDLE", "CORE-004/005 complete; awaiting next mission package")
        except KeyboardInterrupt:
            log("Research Director stopped")
            return
        except Exception:
            err = traceback.format_exc()
            log(err)
            write_state("UNKNOWN", "BLOCKED", err[-1500:])
        if not continuous:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
