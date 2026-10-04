from __future__ import annotations

from typing import Any


def validate_adapter_contract(obj: dict[str, Any]) -> tuple[list[str], str]:
    """Optional Pydantic validation. Manual canonicalization gates remain authoritative fallback."""
    try:
        from typing import Literal
        from pydantic import BaseModel, ConfigDict, Field, ValidationError

        class AdapterContract(BaseModel):
            model_config = ConfigDict(extra="allow")
            source_id: str = Field(min_length=1)
            enabled: bool
            domain: Literal["JRA", "NAR", "MIXED"]
            provenance: str = Field(min_length=1)
            rights_status: Literal["APPROVED_INTERNAL", "APPROVED"]
            column_map: dict[str, str]
            defaults: dict[str, Any] = {}

        try:
            AdapterContract.model_validate(obj)
            return [], "PYDANTIC"
        except ValidationError as e:
            issues=[]
            for x in e.errors(include_url=False):
                loc=".".join(map(str,x.get("loc",())))
                issues.append(f"pydantic:{loc}:{x.get('type','invalid')}")
            return issues, "PYDANTIC"
    except Exception:
        return [], "MANUAL_FALLBACK"


def validate_core003b_frame(df) -> tuple[list[str], str]:
    """Optional Pandera validation for canonical invariants."""
    try:
        import pandera.pandas as pa
        from pandera import Check
        schema=pa.DataFrameSchema({
            "race_id": pa.Column(object, nullable=False),
            "race_horse_id": pa.Column(object, nullable=False, unique=True),
            "horse_id": pa.Column(object, nullable=False),
            "race_date": pa.Column(object, nullable=False),
            "race_scope_cd": pa.Column(object, checks=Check(lambda s: s.astype(str).isin(["1","1.0","2","2.0"]).all())),
            "label_win": pa.Column(object, checks=Check(lambda s: s.astype(float).isin([0.0,1.0]).all())),
            "label_top2": pa.Column(object, checks=Check(lambda s: s.astype(float).isin([0.0,1.0]).all())),
            "label_top3": pa.Column(object, checks=Check(lambda s: s.astype(float).isin([0.0,1.0]).all())),
        }, strict=False, coerce=False)
        schema.validate(df, lazy=True)
        return [], "PANDERA"
    except ImportError:
        return [], "MANUAL_FALLBACK"
    except Exception as e:
        return [f"pandera:{type(e).__name__}:{str(e)[:500]}"], "PANDERA"
