-- NEO JIZO ATLAS native data store v0.1
-- PostgreSQL 18. Greenfield ONLY: apply to a newly created, isolated database.
-- Never execute this file against mykeibadb or any other existing user database.
-- No implicit adapter promotion and no license to redistribute source records.
BEGIN;
CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.data_source (
  source_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_code text NOT NULL UNIQUE
    CHECK (source_code ~ '^[A-Z][A-Z0-9_-]{1,63}$'),
  organizer text NOT NULL CHECK (organizer IN ('JRA','NAR','OTHER')),
  adapter_type text NOT NULL
    CHECK (adapter_type IN ('JV_LINK','OFFICIAL_NAR','LOCAL_ARCHIVE','OTHER')),
  provenance_description text NOT NULL CHECK (length(provenance_description) > 0),
  rights_status text NOT NULL DEFAULT 'UNVERIFIED'
    CHECK (rights_status IN ('UNVERIFIED','APPROVED_INTERNAL','APPROVED','DENIED')),
  redistribution_allowed boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS atlas.import_object (
  object_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id bigint NOT NULL REFERENCES atlas.data_source(source_id),
  object_sha256 text NOT NULL CHECK (object_sha256 ~ '^[0-9a-f]{64}$'),
  object_bytes bigint NOT NULL CHECK (object_bytes >= 0),
  provider_object_key text NOT NULL CHECK (length(provider_object_key) > 0),
  acquired_at timestamptz NOT NULL,
  source_modified_at timestamptz,
  declared_from date,
  declared_to date,
  rights_status_at_ingest text NOT NULL DEFAULT 'UNVERIFIED'
    CHECK (rights_status_at_ingest IN ('UNVERIFIED','APPROVED_INTERNAL','APPROVED','DENIED')),
  received_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (source_id, object_sha256),
  UNIQUE (object_id, source_id),
  CHECK (declared_from IS NULL OR declared_to IS NULL OR declared_from <= declared_to)
);

CREATE TABLE IF NOT EXISTS atlas.raw_observation (
  object_id bigint NOT NULL,
  source_id bigint NOT NULL,
  ordinal bigint NOT NULL CHECK (ordinal > 0),
  native_kind text NOT NULL CHECK (native_kind ~ '^[A-Z][A-Z0-9_]{1,63}$'),
  native_key text NOT NULL CHECK (length(native_key) > 0),
  raw_sha256 text NOT NULL CHECK (raw_sha256 ~ '^[0-9a-f]{64}$'),
  -- For bulk workouts use a verified immutable object locator, not huge JSONB copies.
  raw_payload jsonb,
  payload_locator text,
  captured_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  provider_published_at timestamptz,
  event_time timestamptz,
  PRIMARY KEY (object_id, ordinal),
  FOREIGN KEY (object_id, source_id)
    REFERENCES atlas.import_object(object_id, source_id),
  UNIQUE (object_id, native_kind, native_key),
  CHECK (
    (raw_payload IS NOT NULL AND jsonb_typeof(raw_payload) = 'object'
      AND payload_locator IS NULL)
    OR (raw_payload IS NULL AND payload_locator IS NOT NULL
      AND payload_locator ~ '^[A-Za-z0-9_.:/#=-]{1,256}

CREATE TABLE IF NOT EXISTS atlas.horse (
  horse_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  display_name text,
  identity_review text NOT NULL DEFAULT 'UNRESOLVED'
    CHECK (identity_review IN ('UNRESOLVED','SOURCE_ID_VERIFIED','CROSS_SOURCE_VERIFIED')),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Neither horse name nor birth date is accepted as an official identifier.
CREATE TABLE IF NOT EXISTS atlas.horse_identifier (
  source_id bigint NOT NULL REFERENCES atlas.data_source(source_id),
  native_horse_id text NOT NULL CHECK (length(native_horse_id) > 0),
  horse_id bigint NOT NULL REFERENCES atlas.horse(horse_id),
  verified_at timestamptz,
  PRIMARY KEY (source_id, native_horse_id)
);

CREATE TABLE IF NOT EXISTS atlas.race (
  race_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  organizer text NOT NULL CHECK (organizer IN ('JRA','NAR')),
  race_date date NOT NULL,
  venue_code text NOT NULL CHECK (length(venue_code) BETWEEN 1 AND 32),
  race_number smallint NOT NULL CHECK (race_number BETWEEN 1 AND 99),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (organizer, race_date, venue_code, race_number)
);
CREATE TABLE IF NOT EXISTS atlas.race_identifier (
  source_id bigint NOT NULL REFERENCES atlas.data_source(source_id),
  native_race_id text NOT NULL CHECK (length(native_race_id) > 0),
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  PRIMARY KEY (source_id, native_race_id)
);

-- Distinct versions are appended; they never overwrite earlier source truth.
CREATE TABLE IF NOT EXISTS atlas.race_observation (
  object_id bigint NOT NULL,
  ordinal bigint NOT NULL,
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  card_phase text NOT NULL
    CHECK (card_phase IN ('REGISTRATION','CONFIRMED_CARD','PRELIMINARY_RESULT','OFFICIAL_RESULT')),
  scheduled_start timestamptz,
  distance_m integer CHECK (distance_m > 0 AND distance_m <= 10000),
  surface text CHECK (surface IN ('TURF','DIRT','OBSTACLE','OTHER')),
  PRIMARY KEY (object_id, ordinal),
  FOREIGN KEY (object_id, ordinal)
    REFERENCES atlas.raw_observation(object_id, ordinal)
);

CREATE TABLE IF NOT EXISTS atlas.runner_observation (
  object_id bigint NOT NULL,
  ordinal bigint NOT NULL,
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  horse_id bigint NOT NULL REFERENCES atlas.horse(horse_id),
  horse_number smallint CHECK (horse_number BETWEEN 1 AND 30),
  runner_status text NOT NULL
    CHECK (runner_status IN ('REGISTERED','CONFIRMED','SCRATCHED','EXCLUDED','STARTED','UNKNOWN')),
  PRIMARY KEY (object_id, ordinal),
  FOREIGN KEY (object_id, ordinal)
    REFERENCES atlas.raw_observation(object_id, ordinal)
);

CREATE TABLE IF NOT EXISTS atlas.result_observation (
  object_id bigint NOT NULL,
  ordinal bigint NOT NULL,
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  horse_id bigint NOT NULL REFERENCES atlas.horse(horse_id),
  result_finality text NOT NULL DEFAULT 'UNKNOWN'
    CHECK (result_finality IN ('UNKNOWN','PRELIMINARY','OFFICIAL')),
  result_status text NOT NULL
    CHECK (result_status IN ('FINISHED','DID_NOT_FINISH','NON_STARTER','UNRESOLVED')),
  finish_position smallint CHECK (finish_position > 0 AND finish_position <= 30),
  PRIMARY KEY (object_id, ordinal),
  FOREIGN KEY (object_id, ordinal)
    REFERENCES atlas.raw_observation(object_id, ordinal),
  CHECK (
    (result_status = 'FINISHED' AND finish_position IS NOT NULL)
    OR (result_status <> 'FINISHED' AND finish_position IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS atlas.quarantine_issue (
  issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  object_id bigint REFERENCES atlas.import_object(object_id),
  ordinal bigint,
  issue_code text NOT NULL CHECK (issue_code ~ '^[A-Z][A-Z0-9_]{2,127}$'),
  evidence_sha256 text CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (ordinal IS NULL OR (ordinal > 0 AND object_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS atlas.ingest_decision (
  decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  object_id bigint NOT NULL REFERENCES atlas.import_object(object_id),
  decision text NOT NULL CHECK (decision IN ('VALIDATED','QUARANTINED','REJECTED')),
  validated_record_count bigint NOT NULL CHECK (validated_record_count >= 0),
  quarantined_record_count bigint NOT NULL CHECK (quarantined_record_count >= 0),
  policy_version text NOT NULL CHECK (length(policy_version) > 0),
  decided_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- No automatic promotion column exists. Promotion to immutable Parquet
-- is an independent gate, not a side effect of receiving an import.

-- Enforce rights at time of insertion. UNVERIFIED is NOT implicit consent.
CREATE OR REPLACE FUNCTION atlas.require_approved_raw_source()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rights_snapshot text;
DECLARE current_rights text;
BEGIN
  SELECT io.rights_status_at_ingest, ds.rights_status
  INTO rights_snapshot, current_rights
  FROM atlas.import_object AS io
  JOIN atlas.data_source AS ds ON ds.source_id = io.source_id
  WHERE io.object_id = NEW.object_id AND io.source_id = NEW.source_id;
  IF rights_snapshot NOT IN ('APPROVED_INTERNAL','APPROVED')
     OR current_rights NOT IN ('APPROVED_INTERNAL','APPROVED')
     OR rights_snapshot IS NULL OR current_rights IS NULL THEN
    RAISE EXCEPTION 'RAW_IMPORT_RIGHTS_NOT_APPROVED'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION atlas.reject_immutable_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ATLAS_APPEND_ONLY_HISTORY'
    USING ERRCODE = '23514';
END $$;

DROP TRIGGER IF EXISTS trg_atlas_raw_rights ON atlas.raw_observation;
CREATE TRIGGER trg_atlas_raw_rights
BEFORE INSERT ON atlas.raw_observation
FOR EACH ROW EXECUTE FUNCTION atlas.require_approved_raw_source();

-- Source provenance and observations are append-only. No silent updates.
DROP TRIGGER IF EXISTS trg_atlas_raw_append_only ON atlas.raw_observation;
CREATE TRIGGER trg_atlas_raw_append_only
BEFORE UPDATE OR DELETE ON atlas.raw_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_object_append_only ON atlas.import_object;
CREATE TRIGGER trg_atlas_object_append_only
BEFORE UPDATE OR DELETE ON atlas.import_object
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_race_observation_append_only ON atlas.race_observation;
CREATE TRIGGER trg_atlas_race_observation_append_only
BEFORE UPDATE OR DELETE ON atlas.race_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_runner_observation_append_only ON atlas.runner_observation;
CREATE TRIGGER trg_atlas_runner_observation_append_only
BEFORE UPDATE OR DELETE ON atlas.runner_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_result_observation_append_only ON atlas.result_observation;
CREATE TRIGGER trg_atlas_result_observation_append_only
BEFORE UPDATE OR DELETE ON atlas.result_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_decision_append_only ON atlas.ingest_decision;
CREATE TRIGGER trg_atlas_decision_append_only
BEFORE UPDATE OR DELETE ON atlas.ingest_decision
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

CREATE INDEX IF NOT EXISTS ix_atlas_raw_source_time
  ON atlas.raw_observation(source_id, native_kind, captured_at);
CREATE INDEX IF NOT EXISTS ix_atlas_race_day
  ON atlas.race(organizer, race_date);
CREATE INDEX IF NOT EXISTS ix_atlas_runner_race_horse
  ON atlas.runner_observation(race_id, horse_id);
CREATE INDEX IF NOT EXISTS ix_atlas_result_race_horse
  ON atlas.result_observation(race_id, horse_id);
CREATE INDEX IF NOT EXISTS ix_atlas_issues_object
  ON atlas.quarantine_issue(object_id);

-- Explicit temporal availability: observation time and provider publish time
-- can differ from race date, and are NOT interchangeable.
COMMIT;
)
  )
);

CREATE TABLE IF NOT EXISTS atlas.horse (
  horse_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  display_name text,
  identity_review text NOT NULL DEFAULT 'UNRESOLVED'
    CHECK (identity_review IN ('UNRESOLVED','SOURCE_ID_VERIFIED','CROSS_SOURCE_VERIFIED')),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Neither horse name nor birth date is accepted as an official identifier.
CREATE TABLE IF NOT EXISTS atlas.horse_identifier (
  source_id bigint NOT NULL REFERENCES atlas.data_source(source_id),
  native_horse_id text NOT NULL CHECK (length(native_horse_id) > 0),
  horse_id bigint NOT NULL REFERENCES atlas.horse(horse_id),
  verified_at timestamptz,
  PRIMARY KEY (source_id, native_horse_id)
);

CREATE TABLE IF NOT EXISTS atlas.race (
  race_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  organizer text NOT NULL CHECK (organizer IN ('JRA','NAR')),
  race_date date NOT NULL,
  venue_code text NOT NULL CHECK (length(venue_code) BETWEEN 1 AND 32),
  race_number smallint NOT NULL CHECK (race_number BETWEEN 1 AND 99),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (organizer, race_date, venue_code, race_number)
);
CREATE TABLE IF NOT EXISTS atlas.race_identifier (
  source_id bigint NOT NULL REFERENCES atlas.data_source(source_id),
  native_race_id text NOT NULL CHECK (length(native_race_id) > 0),
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  PRIMARY KEY (source_id, native_race_id)
);

-- Distinct versions are appended; they never overwrite earlier source truth.
CREATE TABLE IF NOT EXISTS atlas.race_observation (
  object_id bigint NOT NULL,
  ordinal bigint NOT NULL,
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  card_phase text NOT NULL
    CHECK (card_phase IN ('REGISTRATION','CONFIRMED_CARD','PRELIMINARY_RESULT','OFFICIAL_RESULT')),
  scheduled_start timestamptz,
  distance_m integer CHECK (distance_m > 0 AND distance_m <= 10000),
  surface text CHECK (surface IN ('TURF','DIRT','OBSTACLE','OTHER')),
  PRIMARY KEY (object_id, ordinal),
  FOREIGN KEY (object_id, ordinal)
    REFERENCES atlas.raw_observation(object_id, ordinal)
);

CREATE TABLE IF NOT EXISTS atlas.runner_observation (
  object_id bigint NOT NULL,
  ordinal bigint NOT NULL,
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  horse_id bigint NOT NULL REFERENCES atlas.horse(horse_id),
  horse_number smallint CHECK (horse_number BETWEEN 1 AND 30),
  runner_status text NOT NULL
    CHECK (runner_status IN ('REGISTERED','CONFIRMED','SCRATCHED','EXCLUDED','STARTED','UNKNOWN')),
  PRIMARY KEY (object_id, ordinal),
  FOREIGN KEY (object_id, ordinal)
    REFERENCES atlas.raw_observation(object_id, ordinal)
);

CREATE TABLE IF NOT EXISTS atlas.result_observation (
  object_id bigint NOT NULL,
  ordinal bigint NOT NULL,
  race_id bigint NOT NULL REFERENCES atlas.race(race_id),
  horse_id bigint NOT NULL REFERENCES atlas.horse(horse_id),
  result_finality text NOT NULL DEFAULT 'UNKNOWN'
    CHECK (result_finality IN ('UNKNOWN','PRELIMINARY','OFFICIAL')),
  result_status text NOT NULL
    CHECK (result_status IN ('FINISHED','DID_NOT_FINISH','NON_STARTER','UNRESOLVED')),
  finish_position smallint CHECK (finish_position > 0 AND finish_position <= 30),
  PRIMARY KEY (object_id, ordinal),
  FOREIGN KEY (object_id, ordinal)
    REFERENCES atlas.raw_observation(object_id, ordinal),
  CHECK (
    (result_status = 'FINISHED' AND finish_position IS NOT NULL)
    OR (result_status <> 'FINISHED' AND finish_position IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS atlas.quarantine_issue (
  issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  object_id bigint REFERENCES atlas.import_object(object_id),
  ordinal bigint,
  issue_code text NOT NULL CHECK (issue_code ~ '^[A-Z][A-Z0-9_]{2,127}$'),
  evidence_sha256 text CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (ordinal IS NULL OR (ordinal > 0 AND object_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS atlas.ingest_decision (
  decision_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  object_id bigint NOT NULL REFERENCES atlas.import_object(object_id),
  decision text NOT NULL CHECK (decision IN ('VALIDATED','QUARANTINED','REJECTED')),
  validated_record_count bigint NOT NULL CHECK (validated_record_count >= 0),
  quarantined_record_count bigint NOT NULL CHECK (quarantined_record_count >= 0),
  policy_version text NOT NULL CHECK (length(policy_version) > 0),
  decided_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- No automatic promotion column exists. Promotion to immutable Parquet
-- is an independent gate, not a side effect of receiving an import.

-- Enforce rights at time of insertion. UNVERIFIED is NOT implicit consent.
CREATE OR REPLACE FUNCTION atlas.require_approved_raw_source()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rights_snapshot text;
DECLARE current_rights text;
BEGIN
  SELECT io.rights_status_at_ingest, ds.rights_status
  INTO rights_snapshot, current_rights
  FROM atlas.import_object AS io
  JOIN atlas.data_source AS ds ON ds.source_id = io.source_id
  WHERE io.object_id = NEW.object_id AND io.source_id = NEW.source_id;
  IF rights_snapshot NOT IN ('APPROVED_INTERNAL','APPROVED')
     OR current_rights NOT IN ('APPROVED_INTERNAL','APPROVED')
     OR rights_snapshot IS NULL OR current_rights IS NULL THEN
    RAISE EXCEPTION 'RAW_IMPORT_RIGHTS_NOT_APPROVED'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION atlas.reject_immutable_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'ATLAS_APPEND_ONLY_HISTORY'
    USING ERRCODE = '23514';
END $$;

DROP TRIGGER IF EXISTS trg_atlas_raw_rights ON atlas.raw_observation;
CREATE TRIGGER trg_atlas_raw_rights
BEFORE INSERT ON atlas.raw_observation
FOR EACH ROW EXECUTE FUNCTION atlas.require_approved_raw_source();

-- Source provenance and observations are append-only. No silent updates.
DROP TRIGGER IF EXISTS trg_atlas_raw_append_only ON atlas.raw_observation;
CREATE TRIGGER trg_atlas_raw_append_only
BEFORE UPDATE OR DELETE ON atlas.raw_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_object_append_only ON atlas.import_object;
CREATE TRIGGER trg_atlas_object_append_only
BEFORE UPDATE OR DELETE ON atlas.import_object
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_race_observation_append_only ON atlas.race_observation;
CREATE TRIGGER trg_atlas_race_observation_append_only
BEFORE UPDATE OR DELETE ON atlas.race_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_runner_observation_append_only ON atlas.runner_observation;
CREATE TRIGGER trg_atlas_runner_observation_append_only
BEFORE UPDATE OR DELETE ON atlas.runner_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_result_observation_append_only ON atlas.result_observation;
CREATE TRIGGER trg_atlas_result_observation_append_only
BEFORE UPDATE OR DELETE ON atlas.result_observation
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_atlas_decision_append_only ON atlas.ingest_decision;
CREATE TRIGGER trg_atlas_decision_append_only
BEFORE UPDATE OR DELETE ON atlas.ingest_decision
FOR EACH ROW EXECUTE FUNCTION atlas.reject_immutable_mutation();

CREATE INDEX IF NOT EXISTS ix_atlas_raw_source_time
  ON atlas.raw_observation(source_id, native_kind, captured_at);
CREATE INDEX IF NOT EXISTS ix_atlas_race_day
  ON atlas.race(organizer, race_date);
CREATE INDEX IF NOT EXISTS ix_atlas_runner_race_horse
  ON atlas.runner_observation(race_id, horse_id);
CREATE INDEX IF NOT EXISTS ix_atlas_result_race_horse
  ON atlas.result_observation(race_id, horse_id);
CREATE INDEX IF NOT EXISTS ix_atlas_issues_object
  ON atlas.quarantine_issue(object_id);

-- Explicit temporal availability: observation time and provider publish time
-- can differ from race date, and are NOT interchangeable.
COMMIT;
