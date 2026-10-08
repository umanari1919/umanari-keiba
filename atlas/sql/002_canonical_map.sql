-- ATLAS-JVDATA-MAP-003. NEW isolated neo_jizo_atlas ONLY, after 001_init.sql.
-- Observations are append-only. Historical imports do not prove prospective availability.
BEGIN;
CREATE SCHEMA IF NOT EXISTS atlas;
CREATE TABLE IF NOT EXISTS atlas.canonicalization_batch (
  object_id bigint PRIMARY KEY REFERENCES atlas.import_object(object_id),
  mapping_version text NOT NULL CHECK (length(mapping_version) > 0),
  accepted_records bigint NOT NULL CHECK (accepted_records >= 0),
  ignored_records bigint NOT NULL CHECK (ignored_records >= 0),
  results_withheld bigint NOT NULL CHECK (results_withheld >= 0),
  completed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (accepted_records + ignored_records > 0)
);
DROP TRIGGER IF EXISTS trg_atlas_map_batch_append_only ON atlas.canonicalization_batch;
CREATE TRIGGER trg_atlas_map_batch_append_only
BEFORE UPDATE OR DELETE ON atlas.canonicalization_batch
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();
COMMIT;
