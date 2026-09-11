from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import _db_path, _ensure_schema, verify_admin
from cali_skg.core.cali_personal_skg import get_cali_skg

router = APIRouter(prefix="/cali/intelligence", tags=["cali-operations"])

ESCALATION_TRANSITIONS = {
    "created": {"notified", "acknowledged", "closed"},
    "notified": {"acknowledged", "closed"},
    "acknowledged": {"owned", "resolved", "closed"},
    "owned": {"resolved", "closed"},
    "resolved": {"closed"},
    "closed": set(),
}

DEFAULT_CONNECTORS = [
    ("sms", "provider", ["send", "receive", "escalation_delivery"]),
    ("messenger", "meta", ["send", "receive", "page_webhook", "escalation_delivery"]),
    ("iphone", "companion", ["vcard", "contact_sync", "sms_handoff", "escalation_delivery"]),
    ("orb", "desktop_runtime", ["receive", "respond", "escalate", "context_handoff"]),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _audit_checkpoint_path() -> Path:
    cali = get_cali_skg()
    path = Path(cali.vault_path) / "audit"
    path.mkdir(parents=True, exist_ok=True)
    return path / "audit_chain_checkpoint.json"


def _write_checkpoint(row_hash: str, audit_id: str, created_at: str) -> Dict[str, Any]:
    key = str(os.getenv("CALI_AUDIT_HMAC_KEY") or "").encode("utf-8")
    signature = hmac.new(key, row_hash.encode("utf-8"), hashlib.sha256).hexdigest() if key else None
    payload = {
        "audit_id": audit_id,
        "row_hash": row_hash,
        "created_at": created_at,
        "signed": bool(signature),
        "signature": signature,
    }
    _audit_checkpoint_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def append_audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    target_ids: List[str],
    prior_state: Any = None,
    new_state: Any = None,
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None,
    checkpoint: bool = True,
) -> Dict[str, Any]:
    previous = conn.execute("SELECT row_hash FROM audit_event ORDER BY created_at DESC, audit_id DESC LIMIT 1").fetchone()
    prev_hash = str(previous["row_hash"] or "") if previous else ""
    created_at = _utc_now()
    audit_id = _stable_id("audit", action, created_at, *target_ids)
    material = {
        "audit_id": audit_id,
        "actor": actor,
        "action": action,
        "target_ids": target_ids,
        "prior_state": prior_state,
        "new_state": new_state,
        "reason": reason,
        "correlation_id": correlation_id,
        "prev_hash": prev_hash,
        "created_at": created_at,
    }
    row_hash = hashlib.sha256((prev_hash + _canonical(material)).encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO audit_event(
          audit_id, actor, action, target_ids, prior_state, new_state, reason,
          correlation_id, prev_hash, row_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            actor,
            action,
            json.dumps(target_ids),
            json.dumps(prior_state) if prior_state is not None else None,
            json.dumps(new_state) if new_state is not None else None,
            reason,
            correlation_id,
            prev_hash or None,
            row_hash,
            created_at,
        ),
    )
    checkpoint_payload = _write_checkpoint(row_hash, audit_id, created_at) if checkpoint else None
    return {"audit_id": audit_id, "row_hash": row_hash, "checkpoint": checkpoint_payload}


def seed_connector_contracts(conn: sqlite3.Connection) -> None:
    for channel, provider, capabilities in DEFAULT_CONNECTORS:
        connector_id = f"connector:{channel}:{provider}"
        conn.execute(
            """
            INSERT OR IGNORE INTO connector_contract(
              connector_id, channel, provider, business_scope, config_ref,
              capability_set, status, last_checked_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, 'stub', ?)
            """,
            (connector_id, channel, provider, json.dumps(capabilities), _utc_now()),
        )


class ConnectorUpdate(BaseModel):
    business_scope: Optional[str] = None
    config_ref: Optional[str] = None
    status: str = "configured"
    capabilities: Optional[List[str]] = None


class EscalationCreate(BaseModel):
    party_id: Optional[str] = None
    business_scope: str
    channel: str
    thread_id: Optional[str] = None
    trigger_reason: str
    priority: str = "p2"
    dossier_context: Dict[str, Any] = Field(default_factory=dict)
    orb_actions: List[Dict[str, Any]] = Field(default_factory=list)
    orb_stop_reason: str
    sla_minutes: Optional[int] = Field(default=None, ge=1, le=10080)
    continuation_ref: Optional[str] = None


class EscalationTransition(BaseModel):
    state: str
    owner: Optional[str] = None
    reason: Optional[str] = None


class CommunicationAccountCreate(BaseModel):
    channel: str
    provider: str
    identity: str
    business_scope: str
    config_ref: Optional[str] = None
    status: str = "active"


@router.get("/connectors")
def list_connectors(business_scope: str = "all", _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        seed_connector_contracts(conn)
        conn.commit()
        if business_scope == "all":
            rows = conn.execute("SELECT * FROM connector_contract ORDER BY channel, provider").fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM connector_contract
                WHERE business_scope IS NULL OR business_scope='' OR business_scope=?
                ORDER BY channel, provider
                """,
                (business_scope,),
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["capability_set"] = json.loads(str(item.get("capability_set") or "[]"))
        item["credential_required"] = item.get("channel") in {"sms", "messenger", "iphone"}
        item["live"] = item.get("status") == "active"
        result.append(item)
    return {"connectors": result, "business_scope": business_scope}


@router.patch("/connectors/{connector_id:path}")
def update_connector(connector_id: str, payload: ConnectorUpdate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    allowed_status = {"stub", "configured", "active", "disabled", "error"}
    if payload.status not in allowed_status:
        raise HTTPException(status_code=400, detail="Invalid connector status")
    with _connect() as conn:
        seed_connector_contracts(conn)
        row = conn.execute("SELECT * FROM connector_contract WHERE connector_id=?", (connector_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Connector not found")
        prior = dict(row)
        capabilities = payload.capabilities if payload.capabilities is not None else json.loads(str(row["capability_set"] or "[]"))
        conn.execute(
            """
            UPDATE connector_contract
            SET business_scope=?, config_ref=?, capability_set=?, status=?, last_checked_at=?
            WHERE connector_id=?
            """,
            (
                payload.business_scope,
                payload.config_ref,
                json.dumps(capabilities),
                payload.status,
                _utc_now(),
                connector_id,
            ),
        )
        new_state = dict(conn.execute("SELECT * FROM connector_contract WHERE connector_id=?", (connector_id,)).fetchone())
        audit = append_audit(
            conn,
            actor="user",
            action="connector_update",
            target_ids=[connector_id],
            prior_state=prior,
            new_state=new_state,
        )
        conn.commit()
    new_state["capability_set"] = capabilities
    return {"connector": new_state, "audit": audit}


@router.post("/communication-accounts")
def create_communication_account(payload: CommunicationAccountCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    account_id = _stable_id("comm-account", payload.channel, payload.provider, payload.identity, payload.business_scope)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO communication_account(account_id, channel, provider, identity, business_scope, config_ref, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
              config_ref=excluded.config_ref,
              status=excluded.status,
              business_scope=excluded.business_scope
            """,
            (
                account_id,
                payload.channel,
                payload.provider,
                payload.identity,
                payload.business_scope,
                payload.config_ref,
                payload.status,
            ),
        )
        audit = append_audit(
            conn,
            actor="user",
            action="communication_account_upsert",
            target_ids=[account_id],
            new_state=payload.model_dump(),
        )
        conn.commit()
    return {"account_id": account_id, "audit": audit}


@router.post("/escalations")
def create_escalation(payload: EscalationCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    if payload.priority not in {"p0", "p1", "p2", "p3"}:
        raise HTTPException(status_code=400, detail="priority must be p0, p1, p2, or p3")
    now = datetime.now(timezone.utc)
    escalation_id = _stable_id(
        "escalation",
        payload.business_scope,
        payload.channel,
        payload.thread_id or "",
        payload.trigger_reason,
        now.isoformat(),
    )
    sla_due = (now + timedelta(minutes=payload.sla_minutes)).isoformat() if payload.sla_minutes else None
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO escalation_event(
              escalation_id, party_id, business_scope, channel, thread_id,
              trigger_reason, priority, dossier_context, orb_actions, orb_stop_reason,
              state, sla_due_at, continuation_ref, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?)
            """,
            (
                escalation_id,
                payload.party_id,
                payload.business_scope,
                payload.channel,
                payload.thread_id,
                payload.trigger_reason,
                payload.priority,
                json.dumps(payload.dossier_context),
                json.dumps(payload.orb_actions),
                payload.orb_stop_reason,
                sla_due,
                payload.continuation_ref,
                now.isoformat(),
            ),
        )
        audit = append_audit(
            conn,
            actor="orb" if payload.orb_actions else "system",
            action="escalate",
            target_ids=[escalation_id],
            new_state=payload.model_dump(),
            reason=payload.trigger_reason,
            correlation_id=escalation_id,
        )
        conn.commit()
    return {
        "escalation_id": escalation_id,
        "state": "created",
        "priority": payload.priority,
        "sla_due_at": sla_due,
        "continuation_ref": payload.continuation_ref,
        "audit": audit,
    }


@router.get("/escalations")
def list_escalations(
    business_scope: str = "all",
    state: str = "open",
    limit: int = Query(default=100, ge=1, le=500),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    clauses: List[str] = []
    params: List[Any] = []
    if business_scope != "all":
        clauses.append("business_scope=?")
        params.append(business_scope)
    if state == "open":
        clauses.append("state NOT IN ('resolved','closed')")
    elif state != "all":
        clauses.append("state=?")
        params.append(state)
    sql = "SELECT * FROM escalation_event"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY CASE priority WHEN 'p0' THEN 0 WHEN 'p1' THEN 1 WHEN 'p2' THEN 2 ELSE 3 END, created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["dossier_context"] = json.loads(str(item.get("dossier_context") or "{}"))
        item["orb_actions"] = json.loads(str(item.get("orb_actions") or "[]"))
        items.append(item)
    return {"escalations": items, "count": len(items)}


@router.post("/escalations/{escalation_id}/transition")
def transition_escalation(
    escalation_id: str,
    payload: EscalationTransition,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    target_state = payload.state.strip().lower()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM escalation_event WHERE escalation_id=?", (escalation_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Escalation not found")
        prior = dict(row)
        current_state = str(row["state"])
        if target_state not in ESCALATION_TRANSITIONS.get(current_state, set()):
            raise HTTPException(status_code=409, detail=f"Invalid escalation transition: {current_state} -> {target_state}")
        now = _utc_now()
        owner = payload.owner or row["owner"]
        acked_at = row["acked_at"]
        resolved_at = row["resolved_at"]
        if target_state in {"acknowledged", "owned"} and not acked_at:
            acked_at = now
        if target_state in {"resolved", "closed"} and not resolved_at:
            resolved_at = now
        conn.execute(
            """
            UPDATE escalation_event
            SET state=?, owner=?, acked_at=?, resolved_at=?
            WHERE escalation_id=?
            """,
            (target_state, owner, acked_at, resolved_at, escalation_id),
        )
        new_state = dict(conn.execute("SELECT * FROM escalation_event WHERE escalation_id=?", (escalation_id,)).fetchone())
        audit = append_audit(
            conn,
            actor=payload.owner or "user",
            action="escalation_transition",
            target_ids=[escalation_id],
            prior_state=prior,
            new_state=new_state,
            reason=payload.reason,
            correlation_id=escalation_id,
        )
        conn.commit()
    return {"escalation": new_state, "audit": audit}


@router.get("/audit/verify")
def verify_audit_chain(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM audit_event ORDER BY created_at, audit_id").fetchall()
    previous_hash = ""
    checked = 0
    for row in rows:
        target_ids = json.loads(str(row["target_ids"] or "[]"))
        prior_state = json.loads(str(row["prior_state"])) if row["prior_state"] else None
        new_state = json.loads(str(row["new_state"])) if row["new_state"] else None
        material = {
            "audit_id": row["audit_id"],
            "actor": row["actor"],
            "action": row["action"],
            "target_ids": target_ids,
            "prior_state": prior_state,
            "new_state": new_state,
            "reason": row["reason"],
            "correlation_id": row["correlation_id"],
            "prev_hash": previous_hash,
            "created_at": row["created_at"],
        }
        expected = hashlib.sha256((previous_hash + _canonical(material)).encode("utf-8")).hexdigest()
        if str(row["prev_hash"] or "") != previous_hash or str(row["row_hash"]) != expected:
            return {
                "valid": False,
                "checked": checked,
                "failed_audit_id": row["audit_id"],
                "expected": expected,
                "actual": row["row_hash"],
            }
        previous_hash = expected
        checked += 1

    checkpoint = None
    path = _audit_checkpoint_path()
    if path.exists():
        try:
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            checkpoint = {"error": "checkpoint unreadable"}
    checkpoint_matches = not checkpoint or checkpoint.get("row_hash") == previous_hash
    return {
        "valid": bool(checkpoint_matches),
        "checked": checked,
        "head_hash": previous_hash or None,
        "checkpoint": checkpoint,
        "checkpoint_matches": checkpoint_matches,
    }
