from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import scan_relationship_candidates, verify_admin
from cali_skg.api.unified_migration import run_unified_migration
from cali_skg.core.cali_personal_skg import get_cali_skg

router = APIRouter(prefix="/cali/intelligence/automation", tags=["cali-dossier-automation"])
_sweep_lock = asyncio.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    value = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _db_path() -> str:
    return str(get_cali_skg().db_path)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class DailySweepRequest(BaseModel):
    business_scope: str = "all"
    max_entities: int = Field(default=250, ge=1, le=2500)
    run_relationship_scan: bool = True


def _local_matrix(conn: sqlite3.Connection, contact: sqlite3.Row, business_scope: str) -> Dict[str, Any]:
    """Build an auditable matrix from existing local VIV evidence only.

    This deliberately does not claim to have performed web research. A configured
    local research connector can later add separately attributed evidence.
    """
    contact_id = str(contact["id"])
    links = [
        dict(row)
        for row in conn.execute(
            """
            SELECT platform, label, url, link_type, verified_status, source,
                   confidence_score, last_checked_at
            FROM contact_external_links WHERE contact_id=? ORDER BY platform, url
            """,
            (contact_id,),
        ).fetchall()
    ]
    activities = [
        dict(row)
        for row in conn.execute(
            """
            SELECT activity_type, summary, created_at
            FROM crm_activities WHERE contact_id=? ORDER BY created_at DESC LIMIT 25
            """,
            (contact_id,),
        ).fetchall()
    ]
    fields = {key: contact[key] for key in ("id", "name", "type", "email", "phone", "address", "company_role", "organization_id", "risk_score", "epistemic_status") if key in contact.keys()}
    return {
        "schema": "viv-local-dossier-matrix:v1",
        "business_scope": business_scope,
        "contact": fields,
        "external_links": links,
        "recent_activities": activities,
    }


def _append_audit(conn: sqlite3.Connection, action: str, target_id: str, state: Dict[str, Any], run_id: str) -> None:
    prior = conn.execute("SELECT row_hash FROM audit_event ORDER BY created_at DESC LIMIT 1").fetchone()
    prev_hash = str(prior["row_hash"]) if prior else ""
    created_at = _utc_now()
    payload = _canonical_json({"action": action, "target_id": target_id, "state": state, "run_id": run_id, "prev_hash": prev_hash, "created_at": created_at})
    row_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO audit_event(audit_id, actor, action, target_ids, new_state, reason, correlation_id, prev_hash, row_hash, created_at)
        VALUES (?, 'viv_automation', ?, ?, ?, 'daily_local_matrix', ?, ?, ?, ?)
        """,
        (_stable_id("audit", run_id, target_id, row_hash), action, _canonical_json([target_id]), _canonical_json(state), run_id, prev_hash or None, row_hash, created_at),
    )


async def _run_daily_sweep(run_id: str, request: DailySweepRequest) -> None:
    async with _sweep_lock:
        try:
            with _connect() as conn:
                rows = conn.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE LIMIT ?", (request.max_entities,)).fetchall()
                conn.execute("UPDATE dossier_sweep_run SET status='running', contacts_seen=? WHERE run_id=?", (len(rows), run_id))
                conn.commit()

            processed = evidence_written = 0
            for contact in rows:
                contact_id = str(contact["id"])
                with _connect() as conn:
                    matrix = _local_matrix(conn, contact, request.business_scope)
                    serialized = _canonical_json(matrix)
                    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                    evidence_id = _stable_id("evidence", "daily_dossier_matrix", contact_id, content_hash)
                    exists = conn.execute("SELECT 1 FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
                    state = "unchanged" if exists else "written"
                    if not exists:
                        conn.execute(
                            """
                            INSERT INTO evidence(evidence_id, source_type, source_ref, business_scope, captured_at, content_hash, details)
                            VALUES (?, 'daily_dossier_matrix', ?, ?, ?, ?, ?)
                            """,
                            (evidence_id, f"contact:{contact_id}", None if request.business_scope == "all" else request.business_scope, _utc_now(), content_hash, serialized),
                        )
                        _append_audit(conn, "daily_dossier_matrix_written", contact_id, {"evidence_id": evidence_id, "content_hash": content_hash}, run_id)
                        evidence_written += 1
                    conn.execute(
                        """
                        INSERT INTO dossier_sweep_item(run_id, contact_id, content_hash, status, detail, processed_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (run_id, contact_id, content_hash, state, evidence_id, _utc_now()),
                    )
                    conn.commit()
                processed += 1

            scan = scan_relationship_candidates(request.business_scope, min(request.max_entities, 2500), "owner") if request.run_relationship_scan else None
            with _connect() as conn:
                conn.execute(
                    """
                    UPDATE dossier_sweep_run
                    SET status='completed', completed_at=?, contacts_processed=?, evidence_written=?, error_summary=?
                    WHERE run_id=?
                    """,
                    (_utc_now(), processed, evidence_written, _canonical_json({"relationship_scan": scan}) if scan else None, run_id),
                )
                conn.commit()
        except Exception as exc:
            with _connect() as conn:
                conn.execute("UPDATE dossier_sweep_run SET status='failed', completed_at=?, error_summary=? WHERE run_id=?", (_utc_now(), str(exc), run_id))
                conn.commit()


@router.post("/daily-dossier-sweep", status_code=202)
async def trigger_daily_dossier_sweep(
    request: DailySweepRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    run_unified_migration(_db_path())
    if _sweep_lock.locked():
        raise HTTPException(status_code=409, detail="A daily dossier sweep is already running")
    run_id = f"daily-dossier-sweep:{uuid.uuid4()}"
    with _connect() as conn:
        conn.execute(
            "INSERT INTO dossier_sweep_run(run_id, business_scope, max_entities, status, started_at) VALUES (?, ?, ?, 'queued', ?)",
            (run_id, request.business_scope.strip().lower() or "all", request.max_entities, _utc_now()),
        )
        conn.commit()
    background_tasks.add_task(_run_daily_sweep, run_id, request)
    return {"status": "queued", "run_id": run_id, "business_scope": request.business_scope, "max_entities": request.max_entities}


@router.get("/daily-dossier-sweep/{run_id}")
def get_daily_dossier_sweep(run_id: str, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    run_unified_migration(_db_path())
    with _connect() as conn:
        row = conn.execute("SELECT * FROM dossier_sweep_run WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sweep run not found")
        result = dict(row)
    return result
