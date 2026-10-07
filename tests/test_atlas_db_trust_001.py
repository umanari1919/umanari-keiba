"""Offline synthetic-only tests for ATLAS DB-TRUST-001 and missing-file guard."""
from __future__ import annotations

import csv
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_db_trust_001 as audit


def valid_snapshot():
    entries = []
    for name, required in {**audit.CORE_TABLES, **audit.OPTIONAL_TABLES}.items():
        entries.append({
            "table_name": name, "estimated_rows": 100,
            "columns": [{"name": c, "type": "text", "nullable": "YES"}
                        for c in sorted(required)],
            "constraints": ["PRIMARY KEY"],
        })
    return {
        "database": "mykeibadb", "version": "18",
        "transaction_read_only": "on", "default_transaction_read_only": "on",
        "public_tables_total": len(entries), "tables": entries,
    }


class TrustAuditTests(unittest.TestCase):
    def test_schema_fits_but_is_never_certified_as_healthy(self):
        report = audit.evaluate(valid_snapshot())
        self.assertEqual(report["status"], "STRUCTURE_UNVERIFIED_CONTENT")
        self.assertFalse(report["certified"])
        self.assertFalse(report["integrity_checked"])
        self.assertFalse(report["data_completeness_checked"])
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["tables"]["race_shosai"]["estimated_rows_not_exact"], 100)

    def test_missing_core_table_and_required_field_is_blocked(self):
        metadata = valid_snapshot()
        metadata["tables"] = [t for t in metadata["tables"] if t["table_name"] != "race_shosai"]
        report = audit.evaluate(metadata)
        self.assertEqual(report["status"], "STRUCTURE_BLOCKED")
        self.assertTrue(any("race_shosai" in i for i in report["issues"]))
        metadata = valid_snapshot()
        metadata["tables"][1]["columns"].clear()
        report = audit.evaluate(metadata)
        self.assertEqual(report["status"], "STRUCTURE_BLOCKED")

    def test_optional_workout_missing_is_warning_not_certification(self):
        metadata = valid_snapshot()
        metadata["tables"] = [t for t in metadata["tables"] if t["table_name"] != "hanro_chokyo"]
        report = audit.evaluate(metadata)
        self.assertEqual(report["status"], "STRUCTURE_WARN")
        self.assertFalse(report["certified"])
        self.assertIn("MISSING_TABLE:hanro_chokyo", report["warnings"])

    def test_wrong_database_or_writeable_connection_rejected(self):
        payload = valid_snapshot()
        payload["database"] = "postgres"
        self.assertEqual(audit.evaluate(payload)["issues"], ["WRONG_DATABASE"])
        payload = valid_snapshot()
        payload["transaction_read_only"] = "off"
        self.assertEqual(audit.evaluate(payload)["issues"], ["NOT_READ_ONLY"])
        payload = valid_snapshot()
        payload["default_transaction_read_only"] = "off"
        self.assertEqual(audit.evaluate(payload)["issues"], ["NOT_READ_ONLY"])

    def test_duplicate_metadata_and_missing_payload_fail_closed(self):
        payload = valid_snapshot()
        payload["tables"].append(dict(payload["tables"][0]))
        self.assertIn("DUPLICATE", audit.evaluate(payload)["issues"][0])
        payload = valid_snapshot()
        del payload["tables"]
        self.assertEqual(audit.evaluate(payload)["status"], "BLOCKED")

    def test_mock_catalog_reads_single_fixed_select(self):
        called = []
        def fake(query):
            called.append(query)
            return valid_snapshot()
        report = audit.inspect_once(fake)
        self.assertEqual(report["status"], "STRUCTURE_UNVERIFIED_CONTENT")
        self.assertEqual(len(called), 1)
        self.assertIn("information_schema.tables", called[0])
        self.assertIn("pg_stat_user_tables", called[0])
        self.assertNotIn("SELECT * FROM public", called[0])
        for verb in ("INSERT INTO ", "UPDATE public.", "DELETE FROM ", "DROP TABLE "):
            self.assertNotIn(verb, called[0])

    def test_missing_csv_artifacts_cannot_result_in_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            fake_pandas = types.SimpleNamespace()
            def headers(path, nrows):
                with Path(path).open("r", encoding="utf-8", newline="") as handle:
                    return types.SimpleNamespace(columns=next(csv.reader(handle)))
            fake_pandas.read_csv = headers
            script = str(ROOT / "tools/research_dashboard/schema_contract_director.py")
            with patch.dict(os.environ, {"THE_JOCKEY_RESEARCH_ROOT": folder}):
                with patch.dict(sys.modules, {"pandas": fake_pandas}):
                    namespace = runpy.run_path(script)
                    report = namespace["run_once"]()
                    self.assertEqual(report["status"], "BLOCKED")
                    self.assertEqual(len(report["checks"]), 3)
                    self.assertTrue(all(r["status"] == "MISSING" for r in report["checks"]))
                    data = Path(folder) / "CORE/data"
                    data.mkdir(parents=True, exist_ok=True)
                    for filename, required in namespace["REQUIRED"].items():
                        (data / filename).write_text(
                            ",".join(sorted(required)) + "\n", encoding="utf-8"
                        )
                    # CORE-010 has an independent contract, but must still exist.
                    (data / "CORE-010_calibrated_probabilities.csv").write_text(
                        "race_id,label_win,label_top2,label_top3\n", encoding="utf-8"
                    )
                    self.assertEqual(namespace["run_once"]()["status"], "PASS")
                    (data / "CORE-004_field_strength_v2.csv").unlink()
                    self.assertEqual(namespace["run_once"]()["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
