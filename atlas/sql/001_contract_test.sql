-- Contract tests run only inside a disposable PostgreSQL 18 CI database.
-- No data is uploaded; every record below is synthetic and rolls back.
BEGIN;
DO $contract$
DECLARE
  source_unapproved bigint;
  source_ok bigint;
  object_unapproved bigint;
  object_ok bigint;
  id_race bigint;
  id_horse bigint;
  observed_count bigint;
BEGIN
  INSERT INTO atlas.data_source(source_code, organizer, adapter_type, provenance_description)
  VALUES ('JRA_PENDING','JRA','JV_LINK','synthetic not licensed')
  RETURNING source_id INTO source_unapproved;

  INSERT INTO atlas.import_object(
    source_id, object_sha256, object_bytes, provider_object_key,
    acquired_at, rights_status_at_ingest
  ) VALUES (
    source_unapproved, repeat('a',64), 21, 'sandbox_a',
    '2026-10-08T10:00:00+09:00', 'UNVERIFIED'
  ) RETURNING object_id INTO object_unapproved;

  BEGIN
    INSERT INTO atlas.raw_observation(
      object_id, source_id, ordinal, native_kind, native_key,
      raw_sha256, raw_payload
    ) VALUES (
      object_unapproved, source_unapproved, 1, 'RACE', '2026101005010101',
      repeat('b',64), '{"test":true}'
    );
    RAISE EXCEPTION 'RIGHTS_GATE_DID_NOT_REJECT';
  EXCEPTION WHEN check_violation THEN
    IF SQLERRM <> 'RAW_IMPORT_RIGHTS_NOT_APPROVED' THEN RAISE; END IF;
  END;

  INSERT INTO atlas.data_source(
    source_code, organizer, adapter_type,
    provenance_description, rights_status
  ) VALUES ('JRA_APPROVED','JRA','JV_LINK','approved synthetic CI fixture',
            'APPROVED_INTERNAL')
  RETURNING source_id INTO source_ok;

  INSERT INTO atlas.import_object(
    source_id, object_sha256, object_bytes, provider_object_key,
    acquired_at, rights_status_at_ingest
  ) VALUES (
    source_ok, repeat('c',64), 24, 'test_batch_001',
    '2026-10-08T10:00:00+09:00', 'APPROVED_INTERNAL'
  ) RETURNING object_id INTO object_ok;

  INSERT INTO atlas.raw_observation(
    object_id, source_id, ordinal, native_kind, native_key,
    raw_sha256, raw_payload, provider_published_at, event_time
  ) VALUES (
    object_ok, source_ok, 1, 'RACE', '2026101005010101',
    repeat('d',64), '{"test":"race_card"}',
    '2026-10-09T18:00:00+09:00',
    '2026-10-10T10:00:00+09:00'
  );

  INSERT INTO atlas.horse(display_name, identity_review)
  VALUES ('架空の競走馬','SOURCE_ID_VERIFIED')
  RETURNING horse_id INTO id_horse;

  INSERT INTO atlas.horse_identifier(source_id, native_horse_id, horse_id, verified_at)
  VALUES (source_ok, '2020000001', id_horse, CURRENT_TIMESTAMP);

  BEGIN
    INSERT INTO atlas.horse_identifier(source_id, native_horse_id, horse_id)
    VALUES (source_ok, '2020000001', id_horse);
    RAISE EXCEPTION 'HORSE_ALIAS_UNIQUENESS_NOT_ENFORCED';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;

  INSERT INTO atlas.race(organizer, race_date, venue_code, race_number)
  VALUES ('JRA','2026-10-10','TOKYO',1)
  RETURNING race_id INTO id_race;

  INSERT INTO atlas.race_identifier(source_id, native_race_id, race_id)
  VALUES (source_ok,'2026101005010101',id_race);

  INSERT INTO atlas.race_observation(
    object_id, ordinal, race_id, card_phase, scheduled_start, distance_m, surface
  ) VALUES (object_ok,1,id_race,'CONFIRMED_CARD','2026-10-10T10:00:00+09:00',1600,'TURF');

  INSERT INTO atlas.raw_observation(
    object_id, source_id, ordinal, native_kind, native_key,
    raw_sha256, raw_payload
  ) VALUES (
    object_ok, source_ok, 2, 'RUNNER', '2026101005010101|2020000001',
    repeat('e',64), '{"test":"runner"}'
  );

  INSERT INTO atlas.runner_observation(
    object_id, ordinal, race_id, horse_id, horse_number, runner_status
  ) VALUES (object_ok,2,id_race,id_horse,1,'CONFIRMED');

  INSERT INTO atlas.raw_observation(
    object_id, source_id, ordinal, native_kind, native_key,
    raw_sha256, raw_payload
  ) VALUES (
    object_ok, source_ok, 3, 'RESULT', '2026101005010101|2020000001',
    repeat('f',64), '{"test":"outcome"}'
  );

  INSERT INTO atlas.result_observation(
    object_id, ordinal, race_id, horse_id,
    result_finality, result_status, finish_position
  ) VALUES (
    object_ok,3,id_race,id_horse,'OFFICIAL','FINISHED',1
  );

  SELECT count(*) INTO observed_count FROM atlas.result_observation
  WHERE race_id = id_race;
  IF observed_count <> 1 THEN
    RAISE EXCEPTION 'RESULT_INSERT_NOT_VISIBLE';
  END IF;

  BEGIN
    INSERT INTO atlas.result_observation(
      object_id, ordinal, race_id, horse_id,
      result_finality, result_status, finish_position
    ) VALUES (
      object_ok,2,id_race,id_horse,'OFFICIAL','UNRESOLVED',1
    );
    RAISE EXCEPTION 'INVALID_OUTCOME_NOT_REJECTED';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  BEGIN
    INSERT INTO atlas.import_object(
      source_id, object_sha256, object_bytes, provider_object_key,
      acquired_at, rights_status_at_ingest
    ) VALUES (
      source_ok, repeat('c',64),24,'duplicate_reimport',
      '2026-10-08T10:00:00+09:00','APPROVED_INTERNAL'
    );
    RAISE EXCEPTION 'REIMPORT_IDEMPOTENCY_NOT_ENFORCED';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;

  BEGIN
    UPDATE atlas.raw_observation SET raw_payload = '{"tampered":true}'
    WHERE object_id = object_ok AND ordinal = 1;
    RAISE EXCEPTION 'RAW_OVERWRITE_NOT_REJECTED';
  EXCEPTION WHEN check_violation THEN
    IF SQLERRM <> 'ATLAS_APPEND_ONLY_HISTORY' THEN RAISE; END IF;
  END;

  BEGIN
    DELETE FROM atlas.result_observation WHERE object_id = object_ok AND ordinal = 3;
    RAISE EXCEPTION 'RESULT_DELETE_NOT_REJECTED';
  EXCEPTION WHEN check_violation THEN
    IF SQLERRM <> 'ATLAS_APPEND_ONLY_HISTORY' THEN RAISE; END IF;
  END;

  INSERT INTO atlas.quarantine_issue(
    object_id, ordinal, issue_code, evidence_sha256
  ) VALUES (object_ok,3,'SOURCE_TIME_UNVERIFIED',repeat('f',64));

  INSERT INTO atlas.ingest_decision(
    object_id, decision, validated_record_count, quarantined_record_count, policy_version
  ) VALUES (object_ok,'QUARANTINED',2,1,'native-v0.1');

  RAISE NOTICE 'ATLAS_NATIVE_SCHEMA_TEST_PASS: rights, IDs, append-only, outcome, dedup, quarantine';
END
$contract$;
ROLLBACK;
