# THE JOCKEY Immutable Canonical Store

## Purpose

The research lab must never mutate the active historical corpus in place while ingesting or reconciling new data.

## Storage contract

- `CORE/canonical_store/versions/<version_id>/canonical.parquet`
- `CORE/canonical_store/versions/<version_id>/manifest.json`
- `CORE/canonical_store/current.json`

Every canonical version is immutable. Promotion changes only `current.json`, and only after validation succeeds.

## Promotion gates

A candidate can be promoted only when:

- required canonical columns exist;
- schema exactly matches the current canonical schema;
- `race_horse_id` is non-null and unique within the resulting corpus;
- `race_date` parses;
- scope is domestic JRA/NAR;
- WIN/TOP2/TOP3 labels are binary and monotonic;
- merged row count never regresses;
- output Parquet validates before the current pointer is changed.

Duplicate `race_horse_id` values preserve the existing canonical row. Incoming data never silently overwrites an existing canonical row.

## Failure model

Builds are created under a `.building-*` directory. A failed build is never promoted. Existing canonical versions are retained for rollback.

## Compatibility

Before the first canonical-store version exists, research may read legacy `CORE-003B_historical_features.csv`. After bootstrap, CORE-004 reads the active canonical Parquet version.

## Rollback

Rollback changes the current pointer to a previously validated version. It does not rewrite historical versions or the legacy source file.

## Next adapters

JV2AI/MySQL and PostgreSQL `mykeibadb` adapters must feed contract-gated staged data into reconciliation; they must not write directly into the active canonical store.
