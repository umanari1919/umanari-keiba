from __future__ import annotations

import re
from typing import Any

CANONICAL_REQUIRED = {
    "race_id",
    "race_horse_id",
    "horse_id",
    "race_date",
    "race_scope_cd",
    "label_win",
    "label_top2",
    "label_top3",
}

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_identifier(name: str) -> str:
    value = str(name or "")
    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return value


def quote_ident(engine: str, name: str) -> str:
    value = validate_identifier(name)
    if engine.upper() == "MYSQL":
        return f"`{value}`"
    if engine.upper() == "POSTGRES":
        return f'"{value}"'
    raise ValueError(f"unsupported engine: {engine}")


def qualified_table(engine: str, schema: str, table: str) -> str:
    return f"{quote_ident(engine, schema)}.{quote_ident(engine, table)}"


def canonical_mapping_from_contract(contract: dict[str, Any]) -> dict[str, str]:
    """Return canonical_field -> source_column. No inference is performed."""
    raw = contract.get("column_map") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for source, canonical in raw.items():
        source_name = str(source)
        canonical_name = str(canonical)
        if canonical_name in out:
            raise ValueError(f"duplicate canonical target in column_map: {canonical_name}")
        out[canonical_name] = source_name
    return out


def assess_table(columns: list[str], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assess exact compatibility only; unknown naming is never guessed."""
    colset = {str(c) for c in columns}
    exact = sorted(CANONICAL_REQUIRED & colset)
    result: dict[str, Any] = {
        "column_count": len(columns),
        "exact_canonical_fields": exact,
        "exact_required_coverage": len(exact) / len(CANONICAL_REQUIRED),
        "status": "NEEDS_CONTRACT",
        "missing_required": sorted(CANONICAL_REQUIRED - colset),
        "contract_mapped_fields": [],
        "contract_missing_source_columns": [],
    }
    if CANONICAL_REQUIRED.issubset(colset):
        result["status"] = "EXACT_CANONICAL_CANDIDATE"
    if not contract:
        return result

    mapping = canonical_mapping_from_contract(contract)
    mapped_required = sorted(CANONICAL_REQUIRED & set(mapping))
    missing_source = sorted(mapping[c] for c in mapped_required if mapping[c] not in colset)
    missing_targets = sorted(CANONICAL_REQUIRED - set(mapping))
    result["contract_mapped_fields"] = mapped_required
    result["contract_missing_source_columns"] = missing_source
    result["contract_missing_required_targets"] = missing_targets
    if not missing_source and not missing_targets:
        result["status"] = "CONTRACT_READY"
    else:
        result["status"] = "CONTRACT_INCOMPLETE"
    return result


def build_year_coverage_query(
    engine: str,
    schema: str,
    table: str,
    contract: dict[str, Any],
) -> tuple[str, list[str]]:
    """Build a read-only year coverage query strictly from an explicit column_map."""
    mapping = canonical_mapping_from_contract(contract)
    required = ["race_date", "race_id", "race_horse_id"]
    missing = [c for c in required if c not in mapping]
    if missing:
        raise ValueError(f"contract missing coverage targets: {missing}")

    eng = engine.upper()
    qtable = qualified_table(eng, schema, table)
    date_col = quote_ident(eng, mapping["race_date"])
    race_col = quote_ident(eng, mapping["race_id"])
    runner_col = quote_ident(eng, mapping["race_horse_id"])
    label_expr = "0"
    selected = [mapping[x] for x in required]
    if "label_win" in mapping:
        label_col = quote_ident(eng, mapping["label_win"])
        label_expr = f"sum(case when {label_col} is not null then 1 else 0 end)"
        selected.append(mapping["label_win"])

    if eng == "POSTGRES":
        year_expr = f"extract(year from cast({date_col} as date))::int"
    elif eng == "MYSQL":
        year_expr = f"year(cast({date_col} as date))"
    else:
        raise ValueError(f"unsupported engine: {engine}")

    query = f"""
SELECT {year_expr} AS race_year,
       count(*) AS runner_rows,
       count(distinct cast({race_col} as char)) AS race_count,
       count(distinct cast({runner_col} as char)) AS runner_key_count,
       {label_expr} AS labeled_rows
FROM {qtable}
WHERE {date_col} IS NOT NULL
GROUP BY 1
ORDER BY 1
""".strip()
    return query, selected


def contract_table_binding(contract: dict[str, Any]) -> tuple[str, str] | None:
    """Read an explicit schema/table binding. No table-name inference."""
    source = contract.get("source") or {}
    if not isinstance(source, dict):
        return None
    schema = source.get("schema")
    table = source.get("table")
    if not schema or not table:
        return None
    return validate_identifier(str(schema)), validate_identifier(str(table))
