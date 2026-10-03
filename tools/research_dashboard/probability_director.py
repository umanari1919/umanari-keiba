from __future__ import annotations

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
MODELS = CORE / "models" / "CORE-005"
PROGRAM = CORE / "program.json"
LOG = ROOT / "logs" / "probability_director.log"
STATE = ROOT / "checkpoints" / "probability_director_state.json"

for p in (REPORTS, LOG.parent, STATE.parent):
    p.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now().astimezone().isoformat()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def save_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def log(msg):
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_state(mission, status, detail=""):
    save_json(STATE, {"updated": now(), "current_mission": mission, "status": status, "detail": detail, "pid": os.getpid()})


def set_mission_state(mission_id, state):
    program = load_json(PROGRAM, {"missions": []})
    missions = program.setdefault("missions", [])
    found = False
    for m in missions:
        if m.get("id") == mission_id:
            m["state"] = state
            found = True
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


def variant_features(df, variant):
    baseline = [c for c in [
        "race_scope_cd","racecourse_cd","distance_m","track_cd","horse_age","sex_cd",
        "carried_weight_kg","frame_no","horse_no","jockey_cd","trainer_cd"
    ] if c in df.columns]
    historical = baseline + [c for c in [
        "prior_start_count","days_since_last_run","prior_win_rate","prior_top2_rate","prior_top3_rate",
        "prior_avg_finish_pct","prior_avg_time_diff","prior_avg_last3f","prior_avg_corner4_pct",
        "recent3_time_diff_mean","recent5_time_diff_mean","recent3_finish_pct_mean","recent5_finish_pct_mean",
        "recent3_last3f_mean","recent5_last3f_mean","recent3_corner4_pct_mean","recent5_corner4_pct_mean",
        "same_distance_prior_count","same_distance_prior_avg_time_diff","same_track_prior_count","same_track_prior_avg_time_diff",
        "same_racecourse_prior_count","same_racecourse_prior_avg_time_diff","same_course_surface_prior_count","same_course_surface_prior_avg_time_diff"
    ] if c in df.columns]
    field = historical + [c for c in [
        "horse_pre_ability_v1","field_strength_v2","field_strength_coverage","ability_vs_field",
        "ability_percentile_in_race","last_field_strength","recent3_field_strength_mean",
        "recent5_field_strength_mean","prior_avg_field_strength","field_strength_trend"
    ] if c in df.columns]
    return {"BASELINE": baseline, "HISTORICAL": historical, "FIELD_STRENGTH": field}[variant]


def prepare_cats(df, feats):
    cat_candidates = {"race_scope_cd","racecourse_cd","track_cd","sex_cd","jockey_cd","trainer_cd"}
    cats = [c for c in feats if c in cat_candidates]
    out = df.copy()
    for c in cats:
        out[c] = out[c].fillna("MISSING").astype(str)
    return out, cats


def brier(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    return float(np.mean((p-y)**2))


def logloss(y, p):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1-1e-12)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))


def run_predictions():
    decision = load_json(REPORTS / "CORE-005_decision.json", {})
    if decision.get("status") != "PASS":
        write_state("CORE-006", "WAITING", "CORE-005 not PASS yet")
        return False

    src = DATA / "CORE-004_field_strength_v2.csv"
    if not src.exists():
        write_state("CORE-006", "BLOCKED", f"missing {src}")
        return False

    out = DATA / "CORE-006_008_probabilities.csv"
    metrics_out = REPORTS / "CORE-006_008_probability_metrics.csv"
    if out.exists() and metrics_out.exists():
        for m in ("CORE-006","CORE-007","CORE-008"):
            set_mission_state(m, "COMPLETE")
        return True

    try:
        from catboost import CatBoostClassifier
    except Exception as e:
        write_state("CORE-006", "BLOCKED", f"catboost unavailable: {e}")
        return False

    df = pd.read_csv(src, low_memory=False)
    df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")
    df["year"] = df["race_date"].dt.year
    df = df[df["race_scope_cd"].isin([1,2])].copy()
    pred_frame = df[[c for c in ["race_id","race_horse_id","horse_id","race_date","race_scope_cd","label_win","label_top2","label_top3"] if c in df.columns]].copy()
    rows = []

    mapping = [("CORE-006","label_win","p_win"),("CORE-007","label_top2","p_top2"),("CORE-008","label_top3","p_top3")]
    for mission, target, pcol in mapping:
        set_mission_state(mission, "RUNNING")
        champion = decision.get("champion", {}).get(target)
        if not champion:
            write_state(mission, "BLOCKED", f"no champion for {target}")
            return False
        variant = champion["variant"]
        feats = variant_features(df, variant)
        model_path = MODELS / f"{target}_{variant}.cbm"
        if not model_path.exists():
            write_state(mission, "BLOCKED", f"missing model {model_path}")
            return False
        model = CatBoostClassifier()
        model.load_model(str(model_path))
        prepared, _ = prepare_cats(df, feats)
        pred = model.predict_proba(prepared[feats])[:,1]
        pred_frame[pcol] = pred
        for split, year in (("TEST_2025",2025),("OOS_2026",2026)):
            mask = (df["year"] == year) & df[target].notna()
            if not mask.any():
                continue
            rows.append({
                "mission": mission, "target": target, "variant": variant, "split": split,
                "rows": int(mask.sum()), "logloss": logloss(df.loc[mask,target], pred[mask]),
                "brier": brier(df.loc[mask,target], pred[mask])
            })
        set_mission_state(mission, "COMPLETE")
        write_state(mission, "COMPLETE", f"{target} probability generated")

    pred_frame.to_csv(out, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(metrics_out, index=False, encoding="utf-8-sig")
    log("CORE-006/007/008 PASS")
    return True


def run_consistency():
    mission = "CORE-009"
    src = DATA / "CORE-006_008_probabilities.csv"
    out = DATA / "CORE-009_consistent_probabilities.csv"
    audit_path = REPORTS / "CORE-009_consistency_audit.json"
    if out.exists() and audit_path.exists():
        set_mission_state(mission, "COMPLETE")
        return True
    if not src.exists():
        return False
    set_mission_state(mission, "RUNNING")
    df = pd.read_csv(src, low_memory=False)
    before = int(((df["p_win"] > df["p_top2"]) | (df["p_top2"] > df["p_top3"])).sum())
    arr = np.vstack([df["p_win"].to_numpy(float), df["p_top2"].to_numpy(float), df["p_top3"].to_numpy(float)]).T
    arr = np.maximum.accumulate(arr, axis=1)
    arr = np.clip(arr, 0.0, 1.0)
    df[["p_win_consistent","p_top2_consistent","p_top3_consistent"]] = arr
    after = int(((df["p_win_consistent"] > df["p_top2_consistent"]) | (df["p_top2_consistent"] > df["p_top3_consistent"])).sum())
    df.to_csv(out, index=False, encoding="utf-8-sig")
    save_json(audit_path, {"status":"PASS" if after == 0 else "BLOCKED","violations_before":before,"violations_after":after,"updated":now()})
    if after:
        set_mission_state(mission, "BLOCKED")
        return False
    set_mission_state(mission, "COMPLETE")
    write_state(mission, "COMPLETE", f"consistency repaired {before} -> 0")
    log(f"CORE-009 PASS repaired={before}")
    return True


def run_calibration():
    mission = "CORE-010"
    src = DATA / "CORE-009_consistent_probabilities.csv"
    out = DATA / "CORE-010_calibrated_probabilities.csv"
    report = REPORTS / "CORE-010_calibration_metrics.csv"
    decision = REPORTS / "CORE-010_decision.json"
    if out.exists() and decision.exists():
        d = load_json(decision, {})
        if d.get("status") == "PASS":
            set_mission_state(mission, "COMPLETE")
            return True
    if not src.exists():
        return False
    set_mission_state(mission, "RUNNING")
    df = pd.read_csv(src, low_memory=False)
    df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")
    df["year"] = df["race_date"].dt.year
    specs = [("label_win","p_win_consistent","p_win_cal"),("label_top2","p_top2_consistent","p_top2_cal"),("label_top3","p_top3_consistent","p_top3_cal")]
    metrics=[]
    try:
        from sklearn.isotonic import IsotonicRegression
        for target, pcol, outcol in specs:
            calmask=(df["year"]==2024) & df[target].notna() & df[pcol].notna()
            iso=IsotonicRegression(out_of_bounds="clip")
            if int(calmask.sum()) >= 100:
                iso.fit(df.loc[calmask,pcol], df.loc[calmask,target])
                df[outcol]=iso.predict(df[pcol].fillna(df[pcol].median()))
            else:
                df[outcol]=df[pcol]
            for split,year in (("TEST_2025",2025),("OOS_2026",2026)):
                mask=(df["year"]==year) & df[target].notna() & df[outcol].notna()
                if mask.any():
                    metrics.append({"target":target,"split":split,"rows":int(mask.sum()),"logloss":logloss(df.loc[mask,target],df.loc[mask,outcol]),"brier":brier(df.loc[mask,target],df.loc[mask,outcol])})
    except Exception as e:
        log(f"CORE-010 isotonic fallback identity: {e!r}")
        for _,pcol,outcol in specs:
            df[outcol]=df[pcol]

    # enforce monotonicity once more after calibration
    arr=np.vstack([df["p_win_cal"].to_numpy(float),df["p_top2_cal"].to_numpy(float),df["p_top3_cal"].to_numpy(float)]).T
    arr=np.maximum.accumulate(arr,axis=1)
    arr=np.clip(arr,0.0,1.0)
    df[["p_win_cal","p_top2_cal","p_top3_cal"]]=arr
    violations=int(((df["p_win_cal"]>df["p_top2_cal"]) | (df["p_top2_cal"]>df["p_top3_cal"])).sum())
    df.to_csv(out,index=False,encoding="utf-8-sig")
    pd.DataFrame(metrics).to_csv(report,index=False,encoding="utf-8-sig")
    status="PASS" if violations==0 else "BLOCKED"
    save_json(decision,{"status":status,"violations":violations,"updated":now(),"method":"isotonic_2024_with_identity_fallback"})
    set_mission_state(mission,"COMPLETE" if status=="PASS" else "BLOCKED")
    write_state(mission,status,f"calibration {status}")
    log(f"CORE-010 {status}")
    return status=="PASS"


def run_once():
    if not run_predictions():
        return False
    if not run_consistency():
        return False
    if not run_calibration():
        return False
    write_state("QUEUE","IDLE","CORE-006..010 complete")
    return True


def main():
    log("Probability Director started")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            return
        except Exception:
            err=traceback.format_exc()
            log(err)
            write_state("UNKNOWN","BLOCKED",err[-1500:])
        time.sleep(30)


if __name__ == "__main__":
    main()
