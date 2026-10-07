"""Leakage-controlled replay for 2026-10-03 and 2026-10-04.

Predictions are computed before any same-day outcomes are applied.
The replay reconstructs jockey-25 histories from frozen local research artifacts.
Current DB access is optional and used only to attach display metadata
(horse number/name) after probabilities have been frozen.
"""
import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import build_prospective_history as history
import training_three_targets as t
from personnel_experiments import History
from sample_extract import query

ROOT = t.ROOT
OUT = ROOT / "artifacts/jwk-weekend-replay-v1"
TARGET_DAYS = ("20261003", "20261004")
JRA_VENUES = tuple(f"{n:02}" for n in range(1, 11))
READONLY = {"transaction_read_only": "on", "default_transaction_read_only": "on"}


def valid_conditions(c):
    return bool(
        c
        and (c.get("distance") or "").isdigit()
        and int(c["distance"]) > 0
        and (c.get("track") or "").isdigit()
        and len(c["track"]) == 2
        and c["track"] != "00"
        and c.get("race_class")
    )


def load_year(year):
    if year < 2026:
        base = ROOT / "artifacts/decade-2016-2025"
        condition_rows = t.load(base / "conditions" / f"{year}.json")["rows"]
        raw = [
            row
            for month in range(1, 13)
            for row in t.load(base / "raw-cache" / f"{year}-{month:02}.json")["rows"]
        ]
        personnel = t.load(ROOT / "datasets/rider-trainer-v1" / f"{year}.json")["rows"]
        ids = {(r["race_id"], r["horse_id"]): r["jockey_id"] for r in personnel}
    else:
        base = ROOT / "datasets/oos-2026-training-v1"
        condition_rows = t.load(base / "conditions-2026.json")["rows"]
        raw = t.load(base / "runners-2026.json")["rows"]
        ids = {(r["race_id"], r["horse_id"]): r["jockey_id"] for r in raw}
    return condition_rows, raw, ids


def make_stores():
    return {
        "general": History({"kind": "window", "days": 1095}),
        "local": History({"kind": "window", "days": 1095}),
        "jockey": History({"kind": "window", "days": 1095}),
    }


def set_day(stores, day):
    for store in stores.values():
        store.set_day(day)


def strength_for(record, condition, jockey_id, stores):
    return history.strength(
        record["horse_id"],
        condition,
        jockey_id,
        stores["general"],
        stores["local"],
        stores["jockey"],
    )


def evaluate_prediction(prediction, records):
    # Results are consulted only after the probability vector has been frozen.
    active = [r for r in records if r.get("abnormal") not in ("1", "2", "3")]
    predicted_ids = [r["horse_id"] for r in prediction["runners"]]
    active_ids = [r["horse_id"] for r in active]
    if set(active_ids) != set(predicted_ids):
        return {"state": "final_roster_changed", "metrics": None}
    if any(
        not isinstance(r.get("finish"), str)
        or not r["finish"].isdigit()
        or (int(r["finish"]) < 1 and r.get("abnormal") != "4")
        for r in active
    ):
        return {"state": "unresolved_results", "metrics": None}
    if sum(int(r["finish"]) == 1 for r in active) != 1:
        return {"state": "winner_tie_or_unresolved", "metrics": None}

    finish = {r["horse_id"]: int(r["finish"]) for r in active}
    rows = [[r["horse_id"], finish[r["horse_id"]], 1.0] for r in prediction["runners"]]
    probs = [
        [r["jockey_25"][k] for r in prediction["runners"]]
        for k in range(3)
    ]
    return {"state": "scored", "metrics": t.metrics(rows, probs)}


def score_day(day, races, conditions, ids, stores):
    """Freeze all predictions for a day without applying that day's outcomes."""
    set_day(stores, day)
    predictions = []
    for rid, records in sorted(races.items()):
        c = conditions.get(rid)
        if not valid_conditions(c):
            continue
        if len({r["horse_id"] for r in records}) != len(records):
            continue
        if any(
            not r.get("horse_id")
            or not (ids.get((rid, r["horse_id"])) or "").isdigit()
            or int(ids[(rid, r["horse_id"])]) <= 0
            for r in records
        ):
            continue

        # Deliberately ignore finish/abnormal when building model inputs.
        strengths = [
            strength_for(r, c, ids[(rid, r["horse_id"])], stores)
            for r in records
        ]
        probabilities = t.marginals(strengths)
        runners = [
            {
                "horse_id": r["horse_id"],
                "jockey_id": ids[(rid, r["horse_id"])],
                "jockey_25": [probabilities[k][i] for k in range(3)],
            }
            for i, r in enumerate(records)
        ]
        prediction = {
            "race_id": rid,
            "venue": rid[8:10],
            "distance": c["distance"],
            "track": c["track"],
            "grade": c.get("grade") or "",
            "race_class": c["race_class"],
            "runners": runners,
        }
        result = evaluate_prediction(prediction, records)
        prediction["result_state"] = result["state"]
        prediction["_metrics"] = result["metrics"]
        if result["state"] == "scored":
            finish = {r["horse_id"]: int(r["finish"]) for r in records if r.get("abnormal") not in ("1", "2", "3")}
            for runner in prediction["runners"]:
                runner["finish_order"] = finish.get(runner["horse_id"])
        predictions.append(prediction)
    return predictions


def update_day(day, races, conditions, ids, stores):
    """Apply valid outcomes only after every prediction for the day is frozen."""
    set_day(stores, day)
    updates = []
    for rid, records in sorted(races.items()):
        c = conditions.get(rid)
        if not valid_conditions(c):
            continue
        if len({r["horse_id"] for r in records}) != len(records):
            continue
        active = [r for r in records if r.get("abnormal") not in ("1", "2", "3")]
        if not active:
            continue
        if any(
            not r.get("horse_id")
            or not (ids.get((rid, r["horse_id"])) or "").isdigit()
            or not isinstance(r.get("finish"), str)
            or not r["finish"].isdigit()
            or (int(r["finish"]) < 1 and r.get("abnormal") != "4")
            for r in active
        ):
            continue
        if not any(int(r["finish"]) == 1 for r in active):
            continue
        updates.extend(
            (
                r["horse_id"],
                history.context(r["horse_id"], c),
                ids[(rid, r["horse_id"])],
                int(r["finish"]) == 1,
            )
            for r in active
        )

    for horse, context_key, rider, won in updates:
        stores["general"].add(horse, int(won))
        stores["local"].add(context_key, int(won))
        stores["jockey"].add(rider, int(won))
    return len(updates)


def attach_display_metadata(predictions, query_fn=query):
    ids = sorted(p["race_id"] for p in predictions)
    if not ids:
        return {"attached": False, "reason": "no_predictions", "rows": 0}

    state = query_fn(
        "SELECT json_build_object("
        "'transaction_read_only',current_setting('transaction_read_only'),"
        "'default_transaction_read_only',current_setting('default_transaction_read_only'))"
    )
    if state != READONLY:
        raise ValueError("Read-only DB connection required for replay metadata")

    safe = [rid for rid in ids if len(rid) == 16 and rid.isdigit()]
    if safe != ids:
        raise ValueError("Unsafe replay race identifier")
    race_list = ",".join("'" + rid + "'" for rid in safe)
    sql = f"""SELECT coalesce(json_agg(t),'[]'::json) FROM (
      SELECT trim(race_code) AS race_id,trim(ketto_toroku_bango) AS horse_id,
             trim(umaban) AS horse_number,trim(bamei) AS horse_name
      FROM public.umagoto_race_joho
      WHERE race_code IN ({race_list})
      ORDER BY race_code,umaban) t"""
    rows = query_fn(sql)
    mapping = {(r["race_id"], r["horse_id"]): r for r in rows}
    matched = 0
    for race in predictions:
        for runner in race["runners"]:
            row = mapping.get((race["race_id"], runner["horse_id"]))
            if row:
                runner["horse_number"] = row.get("horse_number") or ""
                runner["horse_name"] = row.get("horse_name") or ""
                matched += 1
            else:
                runner["horse_number"] = ""
                runner["horse_name"] = ""
    return {
        "attached": True,
        "rows": len(rows),
        "matched_runners": matched,
        "read_only": state,
        "model_input": False,
    }


def replay():
    stores = make_stores()
    predictions = []
    metrics = t.empty()
    states = Counter()
    verified_rows = 0
    update_rows = 0

    for year in range(2011, 2027):
        condition_rows, raw, ids = load_year(year)
        conditions = {r["race_id"]: r for r in condition_rows}
        condition_counts = Counter(r["race_id"] for r in condition_rows)
        day_races = defaultdict(lambda: defaultdict(list))
        for row in raw:
            day_races[row["race_id"][:8]][row["race_id"]].append(row)

        handle = (
            gzip.open(t.OUT / f"{year}-scores.jsonl.gz", "rt", encoding="utf-8")
            if 2016 <= year <= 2025
            else None
        )
        try:
            for day, races in sorted(day_races.items()):
                if day > TARGET_DAYS[-1]:
                    break

                if day in TARGET_DAYS:
                    frozen = score_day(day, races, conditions, ids, stores)
                    for race in frozen:
                        states[race["result_state"]] += 1
                        if race["_metrics"] is not None:
                            t.add(metrics, race["_metrics"])
                        predictions.append(race)

                # Historical verification for the frozen jockey-25 baseline.
                if handle:
                    set_day(stores, day)
                    for rid, records in sorted(races.items()):
                        c = conditions.get(rid)
                        if c is None or condition_counts[rid] != 1 or not valid_conditions(c):
                            continue
                        if len({r["horse_id"] for r in records}) != len(records):
                            continue
                        active = [r for r in records if r.get("abnormal") not in ("1", "2", "3")]
                        if not active or any(
                            not r.get("horse_id")
                            or not (ids.get((rid, r["horse_id"])) or "").isdigit()
                            or not isinstance(r.get("finish"), str)
                            or not r["finish"].isdigit()
                            or (int(r["finish"]) < 1 and r.get("abnormal") != "4")
                            for r in active
                        ):
                            continue
                        if sum(int(r["finish"]) == 1 for r in active) != 1:
                            continue
                        values = [
                            strength_for(r, c, ids[(rid, r["horse_id"])], stores)
                            for r in active
                        ]
                        for r, value in zip(active, values):
                            expected = json.loads(next(handle))
                            actual = [rid, r["horse_id"], int(r["finish"]), value]
                            if expected != actual:
                                raise ValueError("Frozen jockey-25 replay mismatch: " + rid)
                            verified_rows += 1

                update_rows += update_day(day, races, conditions, ids, stores)

            if handle and handle.readline():
                raise ValueError("Frozen jockey-25 score stream has extra rows")
        finally:
            if handle:
                handle.close()

    if not predictions:
        raise ValueError("No target replay races found in frozen 2026 population")

    for race in predictions:
        race.pop("_metrics", None)

    metadata = {}
    try:
        metadata = attach_display_metadata(predictions)
    except Exception as exc:
        metadata = {
            "attached": False,
            "reason": type(exc).__name__ + ": " + str(exc),
            "model_input": False,
        }
        for race in predictions:
            for i, runner in enumerate(race["runners"], 1):
                runner.setdefault("horse_number", "")
                runner.setdefault("horse_name", "")

    result = {
        "created_at": datetime.now().astimezone().isoformat(),
        "state": "replay_completed",
        "days": list(TARGET_DAYS),
        "model": "jockey-25",
        "targets": ["win", "top2", "top3"],
        "predicted_races": len(predictions),
        "predicted_runners": sum(len(r["runners"]) for r in predictions),
        "result_states": dict(states),
        "metrics": t.finalize(metrics),
        "predictions": predictions,
        "frozen_2016_2025_score_rows_verified": verified_rows,
        "history_update_rows": update_rows,
        "same_day_outcomes_excluded_from_predictions": True,
        "target_day_results_applied_only_after_all_same_day_predictions": True,
        "display_metadata": metadata,
        "replay_evidence_scope": (
            "Model history is reconstructed chronologically from frozen local research "
            "artifacts. Target-day finish/abnormal fields are excluded from model inputs. "
            "This does not prove the exact official pre-race delivery snapshot or late "
            "roster revisions available at the historical timestamp."
        ),
        "research_evidence": False,
        "automatic_betting": False,
        "production_promotion": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_bytes(t.json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    (OUT / "report.md").write_text(
        "# 10/3・10/4 事前情報限定再現\n\n"
        f"jockey-25で{result['predicted_races']}レース・{result['predicted_runners']}頭を再現。"
        "同日結果は全レースの予測を凍結した後にのみ履歴へ反映。"
        "現在DBから取得する馬番・馬名は表示専用でモデル入力には不使用。"
        "元時点の公式配信スナップショットそのものを証明するものではない。\n",
        encoding="utf-8",
    )
    return result


def main():
    result = replay()
    print(
        json.dumps(
            {
                "state": result["state"],
                "days": result["days"],
                "predicted_races": result["predicted_races"],
                "predicted_runners": result["predicted_runners"],
                "result_states": result["result_states"],
                "metadata_attached": result["display_metadata"].get("attached", False),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
