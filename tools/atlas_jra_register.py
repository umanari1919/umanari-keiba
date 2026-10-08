"""ATLAS-JRA-REGISTER-001: explicitly register only authorized JRA source.

No network/JV-Link calls or local source-data reads. Default = read-only.
Database changes require --apply plus the operator's explicit confirmation in
ATLAS-JRA-REGISTER.cmd. Never mutates existing source registrations.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import atlas_inbox as inbox

JRA = "JRA"


class RegistrationBlocked(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def reviewed_jra(root: Path):
    # Do not call setup() here: missing config is a hard stop, not a template.
    try:
        source = inbox.load_authorizations(root)[JRA]
    except (inbox.ImportBlocked, KeyError) as exc:
        raise RegistrationBlocked("SOURCE_CONFIG_NOT_REVIEWED") from exc
    if (source["enabled"] is not True
            or source["rights_status"] not in inbox.APPROVED
            or source["adapter_type"] != "JV_LINK"
            or not isinstance(source.get("authorization_reference"), str)
            or len(source["authorization_reference"].strip()) < 8):
        raise RegistrationBlocked("JRA_RIGHTS_NOT_APPROVED")
    return source


def register(root: Path, *, apply=False):
    source = reviewed_jra(root)
    try:
        if apply:
            # Scoped to JRA. NAR approval/registration is not implied.
            inbox.enroll_sources(root, organizers=(JRA,))
            return {"status": "REGISTERED_OR_ALREADY_MATCHED", "modified_requested": True}
        # Preview only. Cannot create tables, sources or other files.
        with inbox.connect_db() as con:
            con.execute("SET TRANSACTION READ ONLY")
            row = con.execute(
                "SELECT organizer,adapter_type,rights_status "
                "FROM atlas.data_source WHERE source_code=%s",
                (source["source_code"],),
            ).fetchone()
        if row is None:
            return {"status": "JRA_REVIEWED_READY_TO_REGISTER", "modified_requested": False}
        if row != (JRA, "JV_LINK", source["rights_status"]):
            raise RegistrationBlocked("DB_JRA_SOURCE_REGISTRY_MISMATCH")
        return {"status": "JRA_ALREADY_REGISTERED", "modified_requested": False}
    except inbox.ImportBlocked as exc:
        raise RegistrationBlocked(exc.code) from exc
    except RegistrationBlocked:
        raise
    except Exception as exc:
        # Driver/SQL errors can contain user DSNs; no values or repr logged.
        raise RegistrationBlocked("JRA_DB_REGISTRY_UNAVAILABLE") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit JRA-only source enrollment")
    parser.add_argument(
        "--root", type=Path,
        default=Path.home() / "Documents" / "NEO-JIZO-ATLAS-DATA",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        outcome = register(args.root, apply=args.apply)
    except RegistrationBlocked as exc:
        print("ATLAS JRA登録: 保留 / " + exc.reason, file=sys.stderr)
        return 2
    print("ATLAS JRA登録: " + outcome["status"])
    print("対象: 新DB neo_jizo_atlas / JRAのみ。NAR・旧DBは変更しません。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
