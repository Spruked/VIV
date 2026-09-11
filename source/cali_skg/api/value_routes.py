from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import _db_path, _ensure_schema, verify_admin

router = APIRouter(prefix="/cali/intelligence", tags=["cali-dossier-value"])


VALUE_CALCULATION_VERSION = "viv-value-profile-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _business_scope(value: str) -> str:
    normalized = str(value or "all").strip().lower()
    return normalized or "all"


def _dollars_to_cents(value: Decimal) -> int:
    amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _cents_to_dollars(value: int) -> float:
    return float((Decimal(int(value or 0)) / Decimal(100)).quantize(Decimal("0.01")))


def _require_contact(conn: sqlite3.Connection, contact_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, name FROM contacts WHERE id=?", (contact_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return row


def _profile_payload(contact_id: str, business_scope: str, row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if row:
        real_cents = int(row["real_value_cents"] or 0)
        cost_cents = int(row["cost_cents"] or 0)
        intrinsic_cents = int(row["intrinsic_value_cents"] or 0)
        future_cents = int(row["future_potential_value_cents"] or 0)
        confidence = int(row["confidence"] or 0)
        notes = row["notes"]
        source = str(row["source"] or "operator")
        updated_at = row["updated_at"]
        calculation_version = str(row["calculation_version"] or VALUE_CALCULATION_VERSION)
    else:
        real_cents = cost_cents = intrinsic_cents = future_cents = 0
        confidence = 0
        notes = None
        source = "unscored"
        updated_at = None
        calculation_version = VALUE_CALCULATION_VERSION

    net_real_cents = real_cents - cost_cents
    net_total_cents = net_real_cents + intrinsic_cents + future_cents

    return {
        "contact_id": contact_id,
        "party_id": f"legacy-contact:{contact_id}",
        "business_scope": business_scope,
        "real_value": _cents_to_dollars(real_cents),
        "cost": _cents_to_dollars(cost_cents),
        "net_real_contribution": _cents_to_dollars(net_real_cents),
        "intrinsic_value": _cents_to_dollars(intrinsic_cents),
        "future_potential_value": _cents_to_dollars(future_cents),
        "net_total_value": _cents_to_dollars(net_total_cents),
        "confidence": confidence,
        "notes": notes,
        "source": source,
        "calculation_version": calculation_version,
        "updated_at": updated_at,
    }


class ValueProfileUpdate(BaseModel):
    real_value: Decimal = Field(default=Decimal("0"), ge=0)
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    intrinsic_value: Decimal = Field(default=Decimal("0"), ge=0)
    future_potential_value: Decimal = Field(default=Decimal("0"), ge=0)
    confidence: int = Field(default=50, ge=0, le=100)
    notes: Optional[str] = Field(default=None, max_length=4000)
    source: str = Field(default="operator", max_length=80)


@router.get("/contacts/{contact_id}/value-profile")
def get_value_profile(
    contact_id: str,
    business_scope: str = Query("all"),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    scope = _business_scope(business_scope)
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        _require_contact(conn, contact_id)
        row = conn.execute(
            """
            SELECT contact_id, party_id, business_scope, real_value_cents, cost_cents,
                   intrinsic_value_cents, future_potential_value_cents, confidence,
                   notes, source, calculation_version, created_at, updated_at
            FROM dossier_value_profile
            WHERE contact_id=? AND business_scope=?
            """,
            (contact_id, scope),
        ).fetchone()
    return _profile_payload(contact_id, scope, row)


@router.put("/contacts/{contact_id}/value-profile")
def update_value_profile(
    contact_id: str,
    payload: ValueProfileUpdate,
    business_scope: str = Query("all"),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    scope = _business_scope(business_scope)
    now = _utc_now()
    party_id = f"legacy-contact:{contact_id}"
    real_cents = _dollars_to_cents(payload.real_value)
    cost_cents = _dollars_to_cents(payload.cost)
    intrinsic_cents = _dollars_to_cents(payload.intrinsic_value)
    future_cents = _dollars_to_cents(payload.future_potential_value)
    source = str(payload.source or "operator").strip() or "operator"
    notes = str(payload.notes or "").strip() or None

    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _require_contact(conn, contact_id)
        conn.execute(
            """
            INSERT INTO dossier_value_profile(
                contact_id, party_id, business_scope, real_value_cents, cost_cents,
                intrinsic_value_cents, future_potential_value_cents, confidence,
                notes, source, calculation_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(contact_id, business_scope) DO UPDATE SET
                party_id=excluded.party_id,
                real_value_cents=excluded.real_value_cents,
                cost_cents=excluded.cost_cents,
                intrinsic_value_cents=excluded.intrinsic_value_cents,
                future_potential_value_cents=excluded.future_potential_value_cents,
                confidence=excluded.confidence,
                notes=excluded.notes,
                source=excluded.source,
                calculation_version=excluded.calculation_version,
                updated_at=excluded.updated_at
            """,
            (
                contact_id,
                party_id,
                scope,
                real_cents,
                cost_cents,
                intrinsic_cents,
                future_cents,
                payload.confidence,
                notes,
                source,
                VALUE_CALCULATION_VERSION,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM dossier_value_profile WHERE contact_id=? AND business_scope=?",
            (contact_id, scope),
        ).fetchone()

    return _profile_payload(contact_id, scope, row)
