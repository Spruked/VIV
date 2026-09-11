from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import _db_path, verify_admin
from cali_skg.api.unified_migration import run_unified_migration
from cali_skg.core.dossier_package_store import ensure_all_dossier_packages

router = APIRouter(prefix="/cali/intelligence/dossiers", tags=["cali-dossier-backfill"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_role_id(party_id: str, business_id: str) -> str:
    raw = f"{party_id}|{business_id}"
    return f"role:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def _normalize_business_scope(value: str) -> str:
    scope = re.sub(r"[^a-z0-9_]+", "_", str(value or "personal").strip().lower()).strip("_")
    return scope or "personal"


class DossierBackfillRequest(BaseModel):
    business_scope: str = "personal"
    contact_ids: List[str] = Field(default_factory=list)
    only_unscoped: bool = True


@router.post("/backfill")
def backfill_dossiers(
    payload: DossierBackfillRequest,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    """Promote legacy/imported contact rows into canonical VIV dossiers.

    The unified migration is rerun first so every selected contact has a Party and
    identity claims. Contacts with no active business-context role are assigned to
    the requested context. Existing active roles are preserved by default. Every
    selected dossier also receives its durable VIV package and image folder.
    """

    db_path = _db_path()
    migration = run_unified_migration(db_path)
    business_scope = _normalize_business_scope(payload.business_scope)
    requested_ids = [str(item).strip() for item in payload.contact_ids if str(item).strip()]
    now = _utc_now()

    selected = 0
    parties_ready = 0
    roles_assigned = 0
    already_scoped = 0
    missing_contacts: List[str] = []
    selected_ids: List[str] = []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            """
            INSERT INTO business_context(business_id, label, isolation, status, created_at)
            VALUES (?, ?, 'scoped', 'active', ?)
            ON CONFLICT(business_id) DO UPDATE SET status='active'
            """,
            (business_scope, business_scope.replace("_", " ").title(), now),
        )

        if requested_ids:
            placeholders = ",".join("?" for _ in requested_ids)
            rows = conn.execute(
                f"SELECT id, name, email FROM contacts WHERE id IN ({placeholders}) ORDER BY name COLLATE NOCASE",
                tuple(requested_ids),
            ).fetchall()
            found_ids = {str(row["id"]) for row in rows}
            missing_contacts = [item for item in requested_ids if item not in found_ids]
        else:
            rows = conn.execute("SELECT id, name, email FROM contacts ORDER BY name COLLATE NOCASE").fetchall()

        for row in rows:
            selected += 1
            contact_id = str(row["id"] or "").strip()
            if not contact_id:
                continue
            selected_ids.append(contact_id)
            party_id = f"legacy-contact:{contact_id}"

            party = conn.execute("SELECT party_id FROM party WHERE party_id=?", (party_id,)).fetchone()
            if not party:
                raise HTTPException(status_code=500, detail=f"Canonical Party backfill missing for contact {contact_id}")
            parties_ready += 1

            if payload.only_unscoped:
                existing = conn.execute(
                    "SELECT role_id FROM party_business_role WHERE party_id=? AND valid_to IS NULL LIMIT 1",
                    (party_id,),
                ).fetchone()
            else:
                existing = conn.execute(
                    """
                    SELECT role_id FROM party_business_role
                    WHERE party_id=? AND business_id=? AND valid_to IS NULL LIMIT 1
                    """,
                    (party_id, business_scope),
                ).fetchone()

            if existing:
                already_scoped += 1
                continue

            role_id = _stable_role_id(party_id, business_scope)
            conn.execute(
                """
                INSERT INTO party_business_role(
                    role_id, party_id, business_id, role, segment_tags,
                    visibility, valid_from, valid_to, created_at
                ) VALUES (?, ?, ?, ?, ?, 'scoped', ?, NULL, ?)
                ON CONFLICT(role_id) DO UPDATE SET
                    valid_to=NULL,
                    visibility='scoped'
                """,
                (
                    role_id,
                    party_id,
                    business_scope,
                    "personal" if business_scope == "personal" else None,
                    json.dumps([]),
                    now,
                    now,
                ),
            )
            roles_assigned += 1

        conn.commit()

    package_result = ensure_all_dossier_packages(db_path, selected_ids)

    return {
        "status": "success",
        "business_scope": business_scope,
        "selected": selected,
        "parties_ready": parties_ready,
        "roles_assigned": roles_assigned,
        "already_scoped": already_scoped,
        "packages_ready": package_result.get("created_or_verified", 0),
        "missing_contacts": missing_contacts,
        "migration_steps": migration.get("steps", []),
    }
