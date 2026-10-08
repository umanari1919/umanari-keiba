"""ATLAS-JVDATA-MAP-003: official-layout JRA RA/SE -> append-only ATLAS.

Fixed byte offsets are from JRA-VAN JV-Data 4.9.0.1, 2024-08-07,
https://jra-van.jp/dlb/sdv/sdk/JV-Data4901.pdf pages 10-11 (0-index).
Works on local raw JV-Link envelopes after ATLAS-INBOX-001 validated import.
Always scoped to organizer=JRA, approved JV_LINK source, isolated ATLAS DB.
Nothing here establishes proof of actual pre-race availability or trains a model.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import atlas_inbox as inbox

MAP_VERSION = "JV-DATA4901_RA_SE_ATLAS_V1"
JRA_VENUES = {f"{i:02d}" for i in range(1, 11)}
JST = timezone(timedelta(hours=9))
SUPPORTED = {"RA": 1272, "SE": 555}
MAX_BATCH_ROWS = 20_000


class MappingBlocked(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def field(data: bytes, pos: int, size: int) -> str:
    """1-indexed BYTE offsets, never character slicing (JVData is CP932)."""
    piece = data[pos - 1 : pos - 1 + size]
    if len(piece) != size:
        raise MappingBlocked("FIELD_TRUNCATED")
    try:
        return piece.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MappingBlocked("ASCII_FIELD_INVALID") from exc


def numeric(data: bytes, pos: int, size: int, lo: int, hi: int) -> int:
    value = field(data, pos, size)
    if len(value) != size or not value.isascii() or not value.isdigit():
        raise MappingBlocked("NUMBER_FIELD_INVALID")
    result = int(value)
    if result < lo or result > hi:
        raise MappingBlocked("NUMBER_FIELD_OUT_OF_RANGE")
    return result


def parsed(raw: dict, outer_sha256: str | None = None) -> dict | None:
    """Returns None ONLY for irrelevant record kinds/phases, never malformed RA/SE."""
    if not isinstance(raw, dict) or raw.get("jv_dataspec") != "RACE":
        raise MappingBlocked("JVDATA_SOURCE_SPEC_MISMATCH")
    if outer_sha256 is not None:
        if hashlib.sha256(inbox.json_bytes(raw)).hexdigest() != outer_sha256:
            raise MappingBlocked("RAW_PAYLOAD_HASH_MISMATCH")
    declared = raw.get("record_spec")
    if declared not in SUPPORTED:
        return None  # RACE includes HR, H1 and other independent record kinds.
    if raw.get("encoding") != "cp932":
        raise MappingBlocked("UNSUPPORTED_RECORD_ENCODING")
    try:
        data = base64.b64decode(raw["raw_base64"], validate=True)
    except (KeyError, ValueError, TypeError, binascii.Error) as exc:
        raise MappingBlocked("RAW_BASE64_INVALID") from exc
    if hashlib.sha256(data).hexdigest() != raw.get("raw_sha256"):
        raise MappingBlocked("SOURCE_RECORD_HASH_MISMATCH")
    if len(data) != SUPPORTED[declared] or data[:2] != declared.encode() or not data.endswith(b"\r\n"):
        raise MappingBlocked("JVDATA_LENGTH_OR_DELIMITER_MISMATCH")
    phase = field(data, 3, 1)
    if phase in {"0", "9"}:
        raise MappingBlocked("SOURCE_DELETE_OR_CANCEL_NEEDS_RECONCILIATION")
    if phase in {"A", "B"}:
        return None  # JV-Link contains NAR/overseas race records; never silently call those JRA.
    if phase not in {"2", "7"}:
        return None  # Thursday registrations and fast results are not official labels.
    creation_date = field(data, 4, 8)
    year = field(data, 12, 4)
    month_day = field(data, 16, 4)
    if not creation_date.isascii() or not creation_date.isdigit():
        raise MappingBlocked("CREATION_DATE_INVALID")
    try:
        datetime.strptime(creation_date, "%Y%m%d")
        race_date = datetime.strptime(year + month_day, "%Y%m%d").date()
    except ValueError as exc:
        raise MappingBlocked("RACE_OR_CREATION_DATE_INVALID") from exc
    venue = field(data, 20, 2)
    if venue not in JRA_VENUES:
        raise MappingBlocked("UNRECOGNIZED_JRA_VENUE")
    kaiji = numeric(data, 22, 2, 1, 99)
    nichiji = numeric(data, 24, 2, 1, 99)
    race_no = numeric(data, 26, 2, 1, 99)
    native_key = f"JRA:{race_date:%Y%m%d}:{venue}:{kaiji:02d}:{nichiji:02d}:{race_no:02d}"
    common = {
        "kind": declared, "phase": phase, "race_date": race_date,
        "venue_code": venue, "race_number": race_no, "native_race_id": native_key,
        "source_creation_date": creation_date,
        "pre_race_certified": False,
    }
    if declared == "RA":
        distance = numeric(data, 698, 4, 1, 10000)
        clock = field(data, 874, 4)
        if not clock.isdigit() or len(clock) != 4:
            raise MappingBlocked("START_TIME_INVALID")
        try:
            scheduled = datetime.combine(
                race_date,
                datetime.strptime(clock, "%H%M").time(),
                tzinfo=JST,
            )
        except ValueError as exc:
            raise MappingBlocked("START_TIME_INVALID") from exc
        return {
            **common, "scheduled_start": scheduled,
            "distance_m": distance,
            "track_code": field(data, 706, 2),
            # Track-to-surface map must be separately audited before population.
            "surface": None,
            "card_phase": "CONFIRMED_CARD" if phase == "2" else "OFFICIAL_RESULT",
        }
    official_horse = field(data, 31, 10)
    if not re.fullmatch(r"[0-9]{10}", official_horse) or official_horse == "0000000000":
        raise MappingBlocked("OFFICIAL_HORSE_ID_INVALID")
    try:
        horse_name = data[40:76].decode("cp932").strip(" \u3000")
    except UnicodeDecodeError as exc:
        raise MappingBlocked("HORSE_NAME_CP932_INVALID") from exc
    if not horse_name:
        raise MappingBlocked("HORSE_NAME_EMPTY")
    horse_number = numeric(data, 29, 2, 1, 30)
    if phase == "2":
        return {
            **common, "official_horse_id": official_horse,
            "horse_name": horse_name, "horse_number": horse_number,
            "runner_status": "CONFIRMED", "result_status": None, "finish_position": None,
            "results_withheld": False,
        }
    abnormal = field(data, 332, 1)
    if abnormal not in "01234567":
        raise MappingBlocked("UNKNOWN_ABNORMAL_CODE")
    if abnormal == "0":
        finish = numeric(data, 335, 2, 1, 30)
        status, withheld = "FINISHED", False
    elif abnormal in "123":
        finish, status, withheld = None, "NON_STARTER", True
    elif abnormal == "4":
        finish, status, withheld = None, "DID_NOT_FINISH", True
    else:
        # DQ, remount and demotion demand a verified outcome contract.
        finish, status, withheld = None, "UNRESOLVED", True
    runner_status = (
        "SCRATCHED" if abnormal == "1" else
        "EXCLUDED" if abnormal in "23" else
        "STARTED"
    )
    return {
        **common, "official_horse_id": official_horse,
        "horse_name": horse_name, "horse_number": horse_number,
        "runner_status": runner_status, "result_status": status,
        "finish_position": finish, "results_withheld": withheld,
    }


def source_ready(con, source_code: str):
    row = con.execute(
        "SELECT s.source_id FROM atlas.data_source s "
        "WHERE s.source_code=%s AND s.organizer='JRA' AND s.adapter_type='JV_LINK' "
        "AND s.rights_status IN ('APPROVED_INTERNAL','APPROVED')",
        (source_code,),
    ).fetchone()
    if not row:
        raise MappingBlocked("JRA_SOURCE_NOT_APPROVED")
    return row[0]


def pending_objects(con, source_id: int, limit: int):
    return [
        row[0]
        for row in con.execute(
            "SELECT o.object_id FROM atlas.import_object o "
            "WHERE o.source_id=%s "
            "AND o.rights_status_at_ingest IN ('APPROVED_INTERNAL','APPROVED') "
            "AND (SELECT d.decision FROM atlas.ingest_decision d "
            "     WHERE d.object_id=o.object_id "
            "     ORDER BY d.decision_id DESC LIMIT 1)='VALIDATED' "
            "AND NOT EXISTS(SELECT 1 FROM atlas.canonicalization_batch b WHERE b.object_id=o.object_id) "
            "ORDER BY CASE WHEN EXISTS ("
            "  SELECT 1 FROM atlas.raw_observation r "
            "  WHERE r.object_id=o.object_id AND r.native_kind='JVDATA' "
            "    AND r.raw_payload->>'record_spec'='RA'"
            ") THEN 0 ELSE 1 END, o.object_id LIMIT %s",
            (source_id, limit),
        ).fetchall()
    ]


def assert_latest_raw_approval(con, source_id: int, object_id: int):
    """Defense-in-depth: prevent a later rejection bypassing the pending queue."""
    row = con.execute(
        "SELECT o.rights_status_at_ingest, "
        "  (SELECT d.decision FROM atlas.ingest_decision d "
        "   WHERE d.object_id=o.object_id "
        "   ORDER BY d.decision_id DESC LIMIT 1) "
        "FROM atlas.import_object o "
        "WHERE o.object_id=%s AND o.source_id=%s FOR SHARE",
        (object_id, source_id),
    ).fetchone()
    if (not row or row[0] not in inbox.APPROVED or row[1] != "VALIDATED"):
        raise MappingBlocked("LATEST_INGEST_DECISION_NOT_VALIDATED")


def read_object(con, object_id: int):
    rows = con.execute(
        "SELECT ordinal,native_kind,raw_payload,raw_sha256 "
        "FROM atlas.raw_observation WHERE object_id=%s ORDER BY ordinal LIMIT %s",
        (object_id, MAX_BATCH_ROWS + 1),
    ).fetchall()
    if not rows or len(rows) > MAX_BATCH_ROWS:
        raise MappingBlocked("OBJECT_EMPTY_OR_TOO_LARGE")
    parsed_rows = []
    for ordinal, kind, payload, payload_sha in rows:
        if kind != "JVDATA":
            raise MappingBlocked("MIXED_OR_NON_JVDATA_SOURCE")
        result = parsed(payload, payload_sha)
        parsed_rows.append((ordinal, result))
    return parsed_rows


def _race(con, source_id: int, rec: dict, *, create: bool):
    source_key = rec["native_race_id"]
    row = con.execute(
        "SELECT i.race_id,r.race_date,r.venue_code,r.race_number "
        "FROM atlas.race_identifier i JOIN atlas.race r ON r.race_id=i.race_id "
        "WHERE i.source_id=%s AND i.native_race_id=%s",
        (source_id, source_key),
    ).fetchone()
    if row:
        if tuple(row[1:]) != (rec["race_date"], rec["venue_code"], rec["race_number"]):
            raise MappingBlocked("RACE_IDENTITY_CONFLICT")
        return row[0]
    if not create:
        raise MappingBlocked("RACE_HEADER_NOT_YET_AVAILABLE")
    con.execute(
        "INSERT INTO atlas.race(organizer,race_date,venue_code,race_number) "
        "VALUES ('JRA',%s,%s,%s) ON CONFLICT DO NOTHING",
        (rec["race_date"], rec["venue_code"], rec["race_number"]),
    )
    race_id = con.execute(
        "SELECT race_id FROM atlas.race "
        "WHERE organizer='JRA' AND race_date=%s AND venue_code=%s AND race_number=%s",
        (rec["race_date"], rec["venue_code"], rec["race_number"]),
    ).fetchone()[0]
    con.execute(
        "INSERT INTO atlas.race_identifier(source_id,native_race_id,race_id) "
        "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
        (source_id, source_key, race_id),
    )
    check = con.execute(
        "SELECT race_id FROM atlas.race_identifier "
        "WHERE source_id=%s AND native_race_id=%s",
        (source_id, source_key),
    ).fetchone()
    if check is None or check[0] != race_id:
        raise MappingBlocked("RACE_KEY_CONFLICT")
    return race_id


def _horse(con, source_id: int, rec: dict):
    native = rec["official_horse_id"]
    row = con.execute(
        "SELECT horse_id FROM atlas.horse_identifier "
        "WHERE source_id=%s AND native_horse_id=%s",
        (source_id, native),
    ).fetchone()
    if row:
        return row[0]
    horse_id = con.execute(
        "INSERT INTO atlas.horse(display_name,identity_review) "
        "VALUES (%s,'SOURCE_ID_VERIFIED') RETURNING horse_id",
        (rec["horse_name"],),
    ).fetchone()[0]
    con.execute(
        "INSERT INTO atlas.horse_identifier(source_id,native_horse_id,horse_id,verified_at) "
        "VALUES (%s,%s,%s,CURRENT_TIMESTAMP)",
        (source_id, native, horse_id),
    )
    return horse_id


def apply_object(con, source_id: int, object_id: int, *, apply: bool):
    # Re-check on every object, even if the queue was prepared earlier.
    # No old VALIDATED event can override a newer QUARANTINED/REJECTED decision.
    assert_latest_raw_approval(con, source_id, object_id)
    items = read_object(con, object_id)  # Validate the WHOLE input before ANY DB writes.
    active = [(ordinal, obj) for ordinal, obj in items if obj is not None]
    ignored = len(items) - len(active)
    withheld = sum(bool(v["results_withheld"]) for _, v in active if v["kind"] == "SE")
    outcome = {"object_id": object_id, "records": len(items),
               "accepted": len(active), "ignored": ignored, "results_withheld": withheld,
               "status": "PREVIEW"}
    if not apply:
        return outcome
    for ordinal, rec in sorted(active, key=lambda it: (it[1]["kind"] != "RA", it[0])):
        if rec["kind"] == "RA":
            race_id = _race(con, source_id, rec, create=True)
            con.execute(
                "INSERT INTO atlas.race_observation "
                "(object_id,ordinal,race_id,card_phase,scheduled_start,distance_m,surface) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (object_id, ordinal, race_id, rec["card_phase"], rec["scheduled_start"],
                 rec["distance_m"], rec["surface"]),
            )
            continue
        race_id = _race(con, source_id, rec, create=False)
        horse_id = _horse(con, source_id, rec)
        con.execute(
            "INSERT INTO atlas.runner_observation "
            "(object_id,ordinal,race_id,horse_id,horse_number,runner_status) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (object_id, ordinal, race_id, horse_id, rec["horse_number"], rec["runner_status"]),
        )
        if rec["phase"] == "7":
            con.execute(
                "INSERT INTO atlas.result_observation "
                "(object_id,ordinal,race_id,horse_id,result_finality,result_status,finish_position) "
                "VALUES (%s,%s,%s,%s,'OFFICIAL',%s,%s)",
                (object_id, ordinal, race_id, horse_id,
                 rec["result_status"], rec["finish_position"]),
            )
            if rec["results_withheld"]:
                con.execute(
                    "INSERT INTO atlas.quarantine_issue "
                    "(object_id,ordinal,issue_code) VALUES (%s,%s,'NONSTANDARD_RESULT_NEEDS_REVIEW')",
                    (object_id, ordinal),
                )
    con.execute(
        "INSERT INTO atlas.canonicalization_batch "
        "(object_id,mapping_version,accepted_records,ignored_records,results_withheld) "
        "VALUES (%s,%s,%s,%s,%s)",
        (object_id, MAP_VERSION, len(active), ignored, withheld),
    )
    outcome["status"] = "MAPPED"
    return outcome


def run(source_code: str, *, apply: bool = False, limit: int = 3):
    if not isinstance(source_code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,63}", source_code):
        raise MappingBlocked("SOURCE_CODE_INVALID")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise MappingBlocked("OBJECT_LIMIT_INVALID")
    reports = []
    # Explicit database name guard is in atlas_inbox.connect_db().
    try:
        with inbox.connect_db() as con:
            if not apply:
                con.execute("SET TRANSACTION READ ONLY")
            source_id = source_ready(con, source_code)
            pending = pending_objects(con, source_id, limit)
            # psycopg connection transaction scope; object failures roll back as savepoints.
            for object_id in pending:
                try:
                    with con.transaction():
                        # Recheck source and object rights inside the transaction.
                        if source_ready(con, source_code) != source_id:
                            raise MappingBlocked("SOURCE_CHANGED")
                        result = apply_object(con, source_id, object_id, apply=apply)
                        reports.append(result)
                except MappingBlocked as exc:
                    reports.append({"object_id": object_id, "status": "BLOCKED",
                                    "reason": exc.reason})
                except Exception:
                    # Never include source records or database credentials in logs.
                    reports.append({"object_id": object_id, "status": "BLOCKED",
                                    "reason": "DB_MAPPING_FAILURE"})
            return {
                "status": "BLOCKED" if any(x["status"] == "BLOCKED" for x in reports) else "PASS",
                "source": source_code, "mode": "APPLY" if apply else "PREVIEW",
                "objects": len(reports), "mapped": sum(x["status"] == "MAPPED" for x in reports),
                "withheld": sum(x.get("results_withheld", 0) for x in reports),
                "reports": reports, "production_approved": False,
            }
    except inbox.ImportBlocked as exc:
        raise MappingBlocked(exc.code) from exc


def local_jra_source(root: Path) -> str:
    inbox.setup(root)
    try:
        items = inbox.load_authorizations(root)
    except inbox.ImportBlocked as exc:
        raise MappingBlocked(exc.code) from exc
    jra = items["JRA"]
    if (jra["enabled"] is not True or jra["rights_status"] not in inbox.APPROVED
            or jra["adapter_type"] != "JV_LINK"
            or len(jra.get("authorization_reference", "").strip()) < 8):
        raise MappingBlocked("JRA_SOURCE_NOT_APPROVED")
    return jra["source_code"]


def main(argv=None):
    p = argparse.ArgumentParser(description="ATLAS JRA JVData layout mapper; preview by default")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--source-code", help="Registered approved local source code")
    g.add_argument("--local-jra", action="store_true", help="Use approved local JRA source settings")
    p.add_argument("--root", type=Path,
                   default=Path.home() / "Documents" / "NEO-JIZO-ATLAS-DATA")
    p.add_argument("--apply", action="store_true", help="Write into ONLY isolated neo_jizo_atlas")
    p.add_argument("--limit", type=int, default=3)
    args = p.parse_args(argv)
    try:
        code = local_jra_source(args.root) if args.local_jra else args.source_code
        result = run(code, apply=args.apply, limit=args.limit)
    except MappingBlocked as exc:
        print(f"ATLASマッピング保留: {exc.reason}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
