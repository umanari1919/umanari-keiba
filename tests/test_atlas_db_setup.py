"""ATLAS-DB-SETUP-001: local-only and disposable PostgreSQL tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import atlas_db_setup as setup


class SetupSafetyTests(unittest.TestCase):
    ADMIN = "postgresql://atlas_user:fake@127.0.0.1:5433/postgres"
    TARGET = "postgresql://atlas_user:fake@127.0.0.1:5433/neo_jizo_atlas"

    def test_requires_both_explicit_local_postgres_urls(self):
        with self.assertRaisesRegex(setup.SetupBlocked, "BOTH_LOCAL"):
            setup.connection_settings(None, self.TARGET)
        with self.assertRaisesRegex(setup.SetupBlocked, "BOTH_LOCAL"):
            setup.connection_settings(self.ADMIN, None)

    def test_mykeibadb_is_never_accepted_as_target_or_maintenance(self):
        for url in (
            self.TARGET.replace("neo_jizo_atlas", "mykeibadb"),
            self.TARGET.replace("neo_jizo_atlas", "postgres"),
        ):
            with self.assertRaisesRegex(setup.SetupBlocked, "MISMATCH"):
                setup.connection_settings(self.ADMIN, url)
        bad_admin = self.ADMIN.replace("/postgres", "/mykeibadb")
        with self.assertRaisesRegex(setup.SetupBlocked, "MISMATCH"):
            setup.connection_settings(bad_admin, self.TARGET)

    def test_only_explicit_localhost_same_user_and_port(self):
        for admin, target in (
            (self.ADMIN, self.TARGET.replace(":5433/", ":5432/")),
            (self.ADMIN, self.TARGET.replace("atlas_user:", "other_user:")),
            (self.ADMIN, self.TARGET.replace("127.0.0.1", "db.remote")),
            (self.ADMIN.replace("127.0.0.1", "db.remote"), self.TARGET),
        ):
            with self.assertRaises(setup.SetupBlocked):
                setup.connection_settings(admin, target)
        good = setup.connection_settings(self.ADMIN, self.TARGET)
        self.assertEqual(good["target_database"], "neo_jizo_atlas")
        self.assertNotIn("fake", str(good))

    def test_wrong_schema_files_never_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            file = Path(t) / "not_guarded.sql"
            file.write_text("BEGIN; CREATE TABLE anything (id int); COMMIT;", encoding="utf-8")
            with self.assertRaisesRegex(setup.SetupBlocked, "MIGRATION_HAS_NO_DATABASE_GUARD"):
                setup._read_schema(file)

    def test_sources_are_guaranteed_guards_and_do_not_delete(self):
        for migration in setup.SCHEMAS:
            source = setup._read_schema(ROOT / migration)
            self.assertIn("current_database() <> 'neo_jizo_atlas'", source)
            self.assertNotIn("DROP DATABASE", source.upper())
            self.assertNotIn("DROP SCHEMA", source.upper())

    def test_default_without_credentials_is_non_destructive(self):
        with patch.dict(os.environ, {"ATLAS_PG_ADMIN_DSN": "", "ATLAS_PG_DSN": ""}):
            self.assertEqual(setup.main([]), 2)


@unittest.skipUnless(os.environ.get("ATLAS_TEST_BOOTSTRAP"), "Disposable isolated DB CI only")
class EphemeralBootstrapIntegration(unittest.TestCase):
    def test_new_database_created_only_once_and_maintenance_db_untouched(self):
        import psycopg
        result_preview = setup.bootstrap(apply=False)
        self.assertEqual(result_preview["status"], "READY_TO_CREATE")
        done = setup.bootstrap(apply=True)
        self.assertEqual(done["status"], "CREATED_AND_INITIALIZED")
        self.assertEqual(done["tables_verified"], len(setup.REQUIRED_TABLES))
        again = setup.bootstrap(apply=True)
        self.assertEqual(again["status"], "ALREADY_READY_NO_CHANGES")
        with psycopg.connect(os.environ["ATLAS_PG_ADMIN_DSN"]) as maintenance:
            name, atlas_schema = maintenance.execute(
                "SELECT current_database(), to_regnamespace('atlas')"
            ).fetchone()
            self.assertEqual(name, "postgres")
            self.assertIsNone(atlas_schema)
        with psycopg.connect(os.environ["ATLAS_PG_DSN"]) as atlas:
            self.assertEqual(atlas.execute(
                "SELECT count(*) FROM atlas.raw_observation"
            ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
