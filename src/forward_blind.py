"""Fail-closed LOCAL freeze and outcome reconciliation for jockey-25 forecasts.

Receipts are stored only on the user's machine. Hashes protect against accidental
changes but do not constitute an independently timestamped public attestation.
No PostgreSQL connection, model training, wagering, or result acquisition here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
READONLY = {"transaction_read_only": "on", "default_transaction_read_only": "on"}
OUT = ROOT / "artifacts/neo-jizo-forward-blind-v1"
PERSONAL = "artifacts/jwk-weekend-personal-v1"
RACE_INPUTS = {"race_id", "venue", "distance", "track", "grade", "race_class",
               "start_time", "registered", "created"}
RUNNER_INPUTS = {"race_id", "horse_id", "horse_number", "jockey_id", "trainer_id", "created"}
STATUS_INPUTS = {"race_id", "horse_id", "horse_name", "abnormal_code"}
TARGETS = ("win", "top2", "top3")


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Expected a JSON object")
    return obj


def jst_time(raw):
    value = datetime.fromisoformat(raw)
    if value.utcoffset() != timedelta(hours=9):
        raise ValueError("A timezone-aware +09:00 timestamp is required")
    return value


def ensure_inside(path, parent):
    resolved = Path(path).resolve()
    if resolved.parent != Path(parent).resolve():
        raise ValueError("File must be directly inside its designated artifact folder")
    return resolved


def race_start(race):
    rid, hhmm = race["race_id"], race["start_time"]
    if (not isinstance(rid, str) or len(rid) != 16 or not rid.isascii() or
            not rid.isdigit() or not isinstance(hhmm, str) or
            len(hhmm) != 4 or not hhmm.isascii() or not hhmm.isdigit() or
            hhmm == "0000"):
        raise ValueError("Invalid race identity or start time")
    return datetime.strptime(rid[:8] + hhmm, "%Y%m%d%H%M").replace(tzinfo=JST)


def ensure_predictions(run, source, sealed_at):
    captured = jst_time(run["captured_at"])
    generated = jst_time(run["created_at"])
    if not captured <= generated <= sealed_at:
        raise ValueError("Capture, computation and seal timestamps are inconsistent")
    # Allow bounded computation time but require prompt sealing after output.
    if (generated - captured).total_seconds() > 600 or (sealed_at - generated).total_seconds() > 120:
        raise ValueError("Historical or stale runs cannot be retroactively sealed")
    if (run.get("state") != "personal_predictions_saved" or
            run.get("model") != "jockey_25" or
            run.get("automatic_betting") is not False or
            run.get("production_promotion") is not False or
            run.get("database_modified") is not False or
            run.get("read_only_connection") != READONLY):
        raise ValueError("This is not an eligible read-only jockey-25 personal run")
    if not all(isinstance(run.get(name), str) and len(run[name]) == 64
               and all(c in "0123456789abcdef" for c in run[name])
               for name in ("source_sha256", "history_sha256", "model_seal_sha256")):
        raise ValueError("Mandatory lineage hashes missing")
    if set(source) != {"payload", "metadata"}:
        raise ValueError("Unexpected source sections")
    payload, metadata = source["payload"], source["metadata"]
    if set(payload) != {"races", "runners", "workouts"} or payload["workouts"] != []:
        raise ValueError("Prediction source contains unexpected input sections")
    if set(metadata) != {"runner_status"}:
        raise ValueError("Missing roster status input")
    for name, allowed in (("races", RACE_INPUTS), ("runners", RUNNER_INPUTS)):
        if any(set(r) != allowed for r in payload[name]):
            raise ValueError("Outcome, betting or unexpected data in prediction inputs")
    if any(set(r) != STATUS_INPUTS for r in metadata["runner_status"]):
        raise ValueError("Unexpected metadata fields (possibly result data)")
    races = {r["race_id"]: r for r in payload["races"]}
    if len(races) != len(payload["races"]):
        raise ValueError("Duplicate source race")
    predicted = run.get("predictions")
    if not isinstance(predicted, list) or not predicted:
        raise ValueError("No predictions to seal")
    if run.get("predicted_races") != len(predicted):
        raise ValueError("Race count mismatch")
    if run.get("predicted_runners") != sum(len(r["runners"]) for r in predicted):
        raise ValueError("Runner count mismatch")
    checks = run.get("input_checks", {}).get("races", [])
    passing = {r["race_id"] for r in checks if r.get("input_checks_passed") is True}
    if len({r.get("race_id") for r in predicted}) != len(predicted):
        raise ValueError("Duplicate predicted race")
    if run.get("input_checks", {}).get("capture_finished_at") != run["captured_at"]:
        raise ValueError("Capture timestamp disagrees with checks")
    for race in predicted:
        if set(race) != {"race_id", "venue", "start_time", "distance", "runners"}:
            raise ValueError("Unexpected prediction fields")
        rid = race["race_id"]
        if rid not in races or rid not in passing:
            raise ValueError("Predicted race has no verified input gate")
        source_race = races[rid]
        if any(race[k] != source_race[k] for k in ("race_id", "venue", "start_time", "distance")):
            raise ValueError("Prediction/source race metadata disagree")
        started = race_start(race)
        if not captured < started or not generated < started or not sealed_at < started:
            raise ValueError("Cannot freeze at or after the start")
        source_runners = {(r["horse_id"], r["horse_number"])
                          for r in payload["runners"] if r["race_id"] == rid}
        actual = race["runners"]
        if not 2 <= len(actual) <= 30 or len(actual) != len(source_runners):
            raise ValueError("Invalid or incomplete runner roster")
        keys = []
        for row in actual:
            if set(row) not in ({"horse_id", "horse_number", "jockey_25"},
                                {"horse_id", "horse_number", "horse_name", "jockey_25"}):
                raise ValueError("Unexpected runner field: outcome leakage suspected")
            keys.append((row["horse_id"], row["horse_number"]))
            probs = row["jockey_25"]
            if (not isinstance(probs, list) or len(probs) != 3 or
                    any(isinstance(v, bool) or not isinstance(v, (float, int)) or
                        not math.isfinite(v) or v < 0 or v > 1 for v in probs) or
                    probs != sorted(probs)):
                raise ValueError("Invalid probability vector")
        if len(set(keys)) != len(keys) or set(keys) != source_runners:
            raise ValueError("Prediction and pre-start roster differ")
        registered = source_race["registered"]
        if not str(registered).isdigit() or int(registered) != len(actual):
            raise ValueError("Source registered count differs from roster")
        status = [r for r in metadata["runner_status"] if r["race_id"] == rid]
        if (len(status) != len(actual) or
                {r["horse_id"] for r in status} != {r["horse_id"] for r in actual} or
                any(r["abnormal_code"] != "0" for r in status)):
            raise ValueError("Missing/changed/cancelled pre-race roster status")
        for i in range(3):
            expected = min(i + 1, len(actual))
            if abs(sum(r["jockey_25"][i] for r in actual) - expected) > 1e-8:
                raise ValueError("Race-level target probability mass invalid")
    return True


def _write_once(path, value):
    raw = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("Immutable artifact exists but differs")
    return path


def freeze_run(run_path, *, root=ROOT, store=None, now=None):
    root = Path(root).resolve()
    store = Path(store) if store is not None else root / "artifacts/neo-jizo-forward-blind-v1"
    run_path = ensure_inside(run_path, root / PERSONAL / "runs")
    raw = run_path.read_bytes()
    snapshot_sha = digest(raw)
    if run_path.name != snapshot_sha + ".json":
        raise ValueError("Existing personal run is not content addressed")
    run = json.loads(raw)
    if raw != encoded(run):
        raise ValueError("Personal run must use canonical encoding")
    source_path = run.get("source_path")
    if not isinstance(source_path, str) or not source_path.startswith(PERSONAL + "/assets/"):
        raise ValueError("Frozen source asset path missing")
    source_file = (root / source_path).resolve()
    ensure_inside(source_file, root / PERSONAL / "assets")
    source_raw = source_file.read_bytes()
    if digest(source_raw) != run["source_sha256"]:
        raise ValueError("Frozen source asset hash mismatch")
    if digest(encoded(json.loads(source_raw))) != run["source_sha256"]:
        raise ValueError("Frozen source is not canonical")
    sealed_at = now if now is not None else datetime.now(JST)
    if sealed_at.utcoffset() != timedelta(hours=9):
        raise ValueError("Seal clock must be JST-aware")
    ensure_predictions(run, json.loads(source_raw), sealed_at)
    receipt = {"version": 1, "status": "LOCAL_PRESTART_SEALED_UNATTESTED",
               "sealed_at": sealed_at.isoformat(),
               "prediction_sha256": snapshot_sha,
               "source_sha256": run["source_sha256"],
               "prediction_path": run_path.relative_to(root).as_posix(),
               "source_path": source_path,
               "run": run,
               "independent_timestamp_attestation": False,
               "production_approved": False}
    envelope = {"receipt": receipt, "sha256": digest(encoded(receipt))}
    saved = store / "receipts" / (snapshot_sha + ".json")
    # Never silently mutate a receipt; one immutable receipt per source run.
    if saved.exists():
        prior = read(saved)
        if prior["sha256"] != digest(encoded(prior["receipt"])):
            raise ValueError("Existing receipt was modified")
        if prior["receipt"]["prediction_sha256"] != snapshot_sha:
            raise ValueError("Existing receipt targets another prediction")
        return saved
    return _write_once(saved, envelope)


def verify_receipt(receipt_path, *, root=ROOT):
    root = Path(root).resolve()
    envelope = read(receipt_path)
    if set(envelope) != {"receipt", "sha256"}:
        raise ValueError("Bad freeze envelope")
    receipt = envelope["receipt"]
    if digest(encoded(receipt)) != envelope["sha256"]:
        raise ValueError("Tampered freeze receipt")
    if (receipt["status"] != "LOCAL_PRESTART_SEALED_UNATTESTED" or
            receipt["independent_timestamp_attestation"] is not False or
            receipt["production_approved"] is not False):
        raise ValueError("Unexpected attestation or production flag")
    run_file = ensure_inside(root / receipt["prediction_path"], root / PERSONAL / "runs")
    raw = run_file.read_bytes()
    if digest(raw) != receipt["prediction_sha256"] or encoded(receipt["run"]) != raw:
        raise ValueError("Sealed forecast no longer agrees with original run")
    source_file = ensure_inside(root / receipt["source_path"], root / PERSONAL / "assets")
    source_raw = source_file.read_bytes()
    if digest(source_raw) != receipt["source_sha256"]:
        raise ValueError("Sealed source changed")
    ensure_predictions(receipt["run"], json.loads(source_raw), jst_time(receipt["sealed_at"]))
    return receipt


def _one_race_result(race, rows):
    runners = race["runners"]
    ids = {r["horse_id"] for r in runners}
    if len(rows) != len(runners) or {r["horse_id"] for r in rows} != ids:
        return None, "MISSING_OR_CHANGED_FINAL_ROSTER"
    finished = []
    for row in rows:
        if set(row) != {"race_id", "horse_id", "finish_position", "result_status"}:
            return None, "UNEXPECTED_RESULT_FIELDS"
        if row["result_status"] == "FINISHED":
            position = row["finish_position"]
            if (isinstance(position, bool) or not isinstance(position, int) or
                    position < 1 or position > len(runners)):
                return None, "MISSING_OR_INVALID_OUTCOME"
            finished.append(position)
        elif row["result_status"] == "DID_NOT_FINISH" and row["finish_position"] is None:
            continue
        else:
            return None, "MISSING_OR_INVALID_OUTCOME"
    if (len(set(finished)) != len(finished) or
            sum(v == 1 for v in finished) != 1 or
            sum(v <= 2 for v in finished) != min(2, len(runners)) or
            sum(v <= 3 for v in finished) != min(3, len(runners))):
        return None, "TIE_OR_INCOMPLETE_PODIUM"
    finish = {r["horse_id"]: r["finish_position"] for r in rows}
    labels = {horse: [int(finish[horse] is not None and finish[horse] <= k)
                       for k in (1, 2, 3)] for horse in ids}
    return labels, None


def _summarize(pairs, picks):
    if not pairs:
        return {"races": 0, "runners": 0, "targets": {}}
    n = len(pairs)
    out = {}
    for index, name in enumerate(TARGETS):
        truth = sum(label[index] for _, label in pairs)
        expectation = sum(prob[index] for prob, _ in pairs)
        out[name] = {
            "actual_rate": truth / n,
            "mean_probability": expectation / n,
            "calibration_gap": abs(expectation - truth) / n,
            "brier": sum((prob[index] - label[index]) ** 2 for prob, label in pairs) / n,
            "top1_accuracy": sum(x[index] for x in picks) / len(picks),
        }
    return {"races": len(picks), "runners": n, "targets": out}


def score_receipt(receipt_path, results_path, *, root=ROOT, store=None, now=None):
    receipt = verify_receipt(receipt_path, root=root)
    root = Path(root).resolve()
    store = Path(store) if store is not None else root / "artifacts/neo-jizo-forward-blind-v1"
    raw = Path(results_path).read_bytes()
    results = json.loads(raw)
    if set(results) != {"observed_at", "read_only_connection", "source", "rows"}:
        raise ValueError("Results input schema mismatch")
    if results["read_only_connection"] != READONLY or not results["source"]:
        raise ValueError("Read-only provenance of results is absent")
    observed = jst_time(results["observed_at"])
    clock = now if now is not None else datetime.now(JST)
    if clock.utcoffset() != timedelta(hours=9) or not jst_time(receipt["sealed_at"]) < observed <= clock:
        raise ValueError("Results observation must follow the saved freeze")
    rows = results["rows"]
    if not isinstance(rows, list):
        raise ValueError("Result rows must be a list")
    keys = [(r["race_id"], r["horse_id"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate final-result race/runner identity")
    indexed = defaultdict(list)
    for row in rows:
        indexed[row["race_id"]].append(row)
    known = {r["race_id"] for r in receipt["run"]["predictions"]}
    if any(rid not in known for rid in indexed):
        raise ValueError("Results contain an unknown race")
    grouped = defaultdict(lambda: {"pairs": [], "picks": []})
    quarantined = []
    scored = 0
    for race in receipt["run"]["predictions"]:
        rid = race["race_id"]
        if observed <= race_start(race):
            quarantined.append({"race_id": rid, "reason": "RESULTS_NOT_AFTER_START"})
            continue
        labels, reason = _one_race_result(race, indexed[rid])
        if reason:
            quarantined.append({"race_id": rid, "reason": reason})
            continue
        scored += 1
        key = (rid[:4], "JRA" if race["venue"] in {f"{i:02}" for i in range(1, 11)} else "NAR")
        pairs = [(r["jockey_25"], labels[r["horse_id"]]) for r in race["runners"]]
        picked = sorted(race["runners"], key=lambda r: (-r["jockey_25"][0], r["horse_id"]))[0]
        for group in ("all", key):
            grouped[group]["pairs"].extend(pairs)
            grouped[group]["picks"].append(labels[picked["horse_id"]])
    aggregates = {"all": _summarize(**grouped["all"])}
    for group, content in grouped.items():
        if group != "all":
            aggregates[group[0] + "_" + group[1]] = _summarize(**content)
    summary = {
        "status": "QUARANTINED" if scored == 0 else
                  ("PARTIAL_QUARANTINE" if quarantined else "SCORED_LOCAL_ONLY"),
        "provenance": "LOCAL_PRESTART_SEALED_UNATTESTED",
        "prospective_verified": False,
        "production_approved": False,
        "prediction_sha256": receipt["prediction_sha256"],
        "freeze_receipt_sha256": digest(Path(receipt_path).read_bytes()),
        "results_sha256": digest(raw),
        "scored_races": scored,
        "quarantined_races": quarantined,
        "metrics": aggregates,
        "caveat": "Local clocks and hashes are not independent pre-race timestamp attestation.",
    }
    destination = store / "scores" / (receipt["prediction_sha256"] + "-" + digest(raw) + ".json")
    return _write_once(destination, summary)


def main():
    parser = argparse.ArgumentParser(description="Local-only pre-start freeze and audit")
    sub = parser.add_subparsers(dest="command", required=True)
    free = sub.add_parser("freeze")
    free.add_argument("--run", required=True, type=Path)
    free.add_argument("--root", type=Path, default=ROOT)
    audit = sub.add_parser("verify")
    audit.add_argument("--receipt", required=True, type=Path)
    audit.add_argument("--root", type=Path, default=ROOT)
    scored = sub.add_parser("score")
    scored.add_argument("--receipt", required=True, type=Path)
    scored.add_argument("--results", required=True, type=Path)
    scored.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_run(args.run, root=args.root)
        print(json.dumps({"receipt_path": str(result), "state": "LOCAL_PRESTART_SEALED_UNATTESTED"}))
    elif args.command == "verify":
        result = verify_receipt(args.receipt, root=args.root)
        print(json.dumps({"verified_hashes": True, "status": result["status"],
                          "independent_attestation": False}))
    else:
        result = score_receipt(args.receipt, args.results, root=args.root)
        summary = read(result)
        print(json.dumps({"score_path": str(result), "status": summary["status"],
                          "scored_races": summary["scored_races"],
                          "quarantined_races": len(summary["quarantined_races"])}))


if __name__ == "__main__":
    main()
