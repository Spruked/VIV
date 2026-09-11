from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from cali_skg.api.unified_migration import run_unified_migration
from cali_skg.core.cali_personal_skg import get_cali_skg

router = APIRouter(prefix="/cali/intelligence", tags=["cali-relationship-intelligence"])
security = HTTPBearer(auto_error=False)

COMMON_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "aol.com",
    "msn.com",
    "proton.me",
    "protonmail.com",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _admin_token_value() -> str:
    return str(os.getenv("CALI_ADMIN_TOKEN") or os.getenv("ADMIN_ACCESS_TOKEN") or "").strip()


def verify_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials if credentials else ""
    allowed = _admin_token_value()
    if not allowed:
        raise HTTPException(status_code=503, detail="Admin token is not configured")
    if token != allowed:
        raise HTTPException(status_code=403, detail="Admin access required")
    return token


def _db_path() -> str:
    return str(get_cali_skg().db_path)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_schema() -> None:
    run_unified_migration(_db_path())


def _json_load(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return fallback


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def _party_id_for_contact(contact_id: str) -> str:
    return f"legacy-contact:{contact_id}"


def _contact_id_from_party(party_id: str) -> Optional[str]:
    prefix = "legacy-contact:"
    return party_id[len(prefix):] if party_id.startswith(prefix) else None


def _domain(email: str) -> str:
    value = str(email or "").strip().lower()
    return value.split("@", 1)[1] if "@" in value else ""


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _area_code(phone: str) -> str:
    digits = _digits(phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits[:3] if len(digits) >= 10 else ""


def _zip_code(address: str) -> str:
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", str(address or ""))
    return match.group(1) if match else ""


def _city_key(address: str) -> str:
    parts = [part.strip().lower() for part in str(address or "").split(",") if part.strip()]
    if len(parts) < 2:
        return ""
    # For common US address forms the city is usually the penultimate component.
    candidate = parts[-2]
    candidate = re.sub(r"\b[a-z]{2}\s+\d{5}(?:-\d{4})?\b", "", candidate).strip()
    return candidate


def _pair_key(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a < b else (b, a)


class BusinessCreate(BaseModel):
    business_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    isolation: str = "scoped"


class BusinessRoleUpsert(BaseModel):
    business_id: str
    role: Optional[str] = None
    segment_tags: List[str] = Field(default_factory=list)
    visibility: str = "scoped"


class GoalCreate(BaseModel):
    label: str
    description: Optional[str] = None
    business_scope: Optional[str] = None
    weight: float = 1.0


class RelevanceRequest(BaseModel):
    business_scope: Optional[str] = None
    goal_id: Optional[str] = None


class CandidateReview(BaseModel):
    decision: str
    reason: Optional[str] = None


class DossierMediaCreate(BaseModel):
    media_kind: str = "person"
    label: Optional[str] = None
    image_url: str = Field(min_length=1)
    notes: Optional[str] = None
    is_primary: bool = False


def _normal_media_kind(value: str) -> str:
    candidate = str(value or "person").strip().lower()
    return candidate if candidate in {"person", "place", "building", "other"} else "other"


def _media_record(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["is_primary"] = bool(item.get("is_primary"))
    return item


def _require_contact(conn: sqlite3.Connection, contact_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return row


@router.get("/businesses")
def list_businesses(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT business_id, label, isolation, status, created_at
            FROM business_context
            WHERE status = 'active'
            ORDER BY CASE WHEN business_id='personal' THEN 1 ELSE 0 END, label COLLATE NOCASE
            """
        ).fetchall()
    return {"businesses": [dict(row) for row in rows]}


@router.post("/businesses")
def create_business(payload: BusinessCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    business_id = re.sub(r"[^a-z0-9_]+", "_", payload.business_id.strip().lower()).strip("_")
    if not business_id:
        raise HTTPException(status_code=400, detail="Business id is invalid")
    isolation = payload.isolation if payload.isolation in {"scoped", "strict"} else "scoped"
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO business_context(business_id, label, isolation, status, created_at)
            VALUES (?, ?, ?, 'active', ?)
            ON CONFLICT(business_id) DO UPDATE SET label=excluded.label, isolation=excluded.isolation, status='active'
            """,
            (business_id, payload.label.strip(), isolation, _utc_now()),
        )
        conn.commit()
    return {"business_id": business_id, "label": payload.label.strip(), "isolation": isolation}


@router.get("/contacts")
def intelligence_contacts(
    query: str = "",
    business_scope: str = "all",
    segment: str = "",
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    q = query.strip().lower()
    business = business_scope.strip().lower() or "all"
    segment_value = segment.strip().lower()

    with _connect() as conn:
        rows = conn.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE").fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            contact = dict(row)
            contact_id = str(contact.get("id") or "")
            party_id = _party_id_for_contact(contact_id)
            role_rows = conn.execute(
                """
                SELECT role_id, business_id, role, segment_tags, visibility, valid_from, valid_to
                FROM party_business_role
                WHERE party_id=? AND valid_to IS NULL
                ORDER BY business_id
                """,
                (party_id,),
            ).fetchall()
            roles = []
            all_segments: set[str] = set()
            for role_row in role_rows:
                item = dict(role_row)
                tags = [str(x) for x in _json_load(item.get("segment_tags"), []) if str(x).strip()]
                item["segment_tags"] = tags
                all_segments.update(tag.lower() for tag in tags)
                roles.append(item)

            if business != "all" and not any(str(role["business_id"]).lower() == business for role in roles):
                continue
            if segment_value and segment_value not in all_segments:
                continue

            haystack = " ".join(
                str(contact.get(key) or "")
                for key in ("name", "email", "phone", "address", "notes", "type", "company_role")
            ).lower()
            if q and q not in haystack:
                continue

            relevance = conn.execute(
                """
                SELECT relevance_score, connection_strength, degrees, factors, rationale, assessed_at
                FROM relevance_assessment
                WHERE party_id=? AND (?='all' OR COALESCE(business_scope,'') IN ('',?))
                ORDER BY assessed_at DESC LIMIT 1
                """,
                (party_id, business, business),
            ).fetchone()
            contact["party_id"] = party_id
            contact["business_roles"] = roles
            contact["segments"] = sorted(all_segments)
            contact["relevance"] = dict(relevance) if relevance else None
            result.append(contact)

    return {"contacts": result, "count": len(result), "business_scope": business}


@router.post("/contacts/{contact_id}/business-role")
def upsert_contact_business_role(
    contact_id: str,
    payload: BusinessRoleUpsert,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    party_id = _party_id_for_contact(contact_id)
    now = _utc_now()
    tags = sorted({str(tag).strip() for tag in payload.segment_tags if str(tag).strip()})
    role_id = _stable_id("role", party_id, payload.business_id)
    visibility = payload.visibility if payload.visibility in {"scoped", "strict", "cross"} else "scoped"
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM party WHERE party_id=?", (party_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Contact party not found")
        if not conn.execute("SELECT 1 FROM business_context WHERE business_id=? AND status='active'", (payload.business_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Business context not found")
        conn.execute(
            """
            INSERT INTO party_business_role(role_id, party_id, business_id, role, segment_tags, visibility, valid_from, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(role_id) DO UPDATE SET
              role=excluded.role,
              segment_tags=excluded.segment_tags,
              visibility=excluded.visibility,
              valid_to=NULL
            """,
            (role_id, party_id, payload.business_id, payload.role, json.dumps(tags), visibility, now, now),
        )
        conn.commit()
    return {
        "role_id": role_id,
        "party_id": party_id,
        "business_id": payload.business_id,
        "role": payload.role,
        "segment_tags": tags,
        "visibility": visibility,
    }


@router.get("/contacts/{contact_id}/media")
def list_contact_media(
    contact_id: str,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        _require_contact(conn, contact_id)
        rows = conn.execute(
            """
            SELECT media_id, contact_id, party_id, media_kind, label, image_url, notes,
                   is_primary, source, created_at, updated_at
            FROM dossier_media
            WHERE contact_id=?
            ORDER BY is_primary DESC, created_at DESC
            """,
            (contact_id,),
        ).fetchall()
    media = [_media_record(row) for row in rows]
    return {"contact_id": contact_id, "media": media, "count": len(media)}


@router.post("/contacts/{contact_id}/media")
def add_contact_media(
    contact_id: str,
    payload: DossierMediaCreate,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    image_url = payload.image_url.strip()
    if not image_url:
        raise HTTPException(status_code=400, detail="Image URL or data URL is required")
    now = _utc_now()
    media_kind = _normal_media_kind(payload.media_kind)
    with _connect() as conn:
        _require_contact(conn, contact_id)
        party_id = _party_id_for_contact(contact_id)
        media_id = _stable_id("media", contact_id, media_kind, image_url, now)
        if payload.is_primary:
            conn.execute("UPDATE dossier_media SET is_primary=0, updated_at=? WHERE contact_id=?", (now, contact_id))
        conn.execute(
            """
            INSERT INTO dossier_media(
                media_id, contact_id, party_id, media_kind, label, image_url,
                notes, is_primary, source, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'operator', ?, ?)
            """,
            (
                media_id,
                contact_id,
                party_id,
                media_kind,
                (payload.label or "").strip() or None,
                image_url,
                (payload.notes or "").strip() or None,
                1 if payload.is_primary else 0,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM dossier_media WHERE media_id=?", (media_id,)).fetchone()
    return _media_record(row)


@router.post("/contacts/{contact_id}/media/{media_id}/primary")
def set_primary_contact_media(
    contact_id: str,
    media_id: str,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    now = _utc_now()
    with _connect() as conn:
        _require_contact(conn, contact_id)
        row = conn.execute("SELECT * FROM dossier_media WHERE contact_id=? AND media_id=?", (contact_id, media_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image vault item not found")
        conn.execute("UPDATE dossier_media SET is_primary=0, updated_at=? WHERE contact_id=?", (now, contact_id))
        conn.execute("UPDATE dossier_media SET is_primary=1, updated_at=? WHERE contact_id=? AND media_id=?", (now, contact_id, media_id))
        conn.commit()
        updated = conn.execute("SELECT * FROM dossier_media WHERE contact_id=? AND media_id=?", (contact_id, media_id)).fetchone()
    return _media_record(updated)


@router.delete("/contacts/{contact_id}/media/{media_id}")
def delete_contact_media(
    contact_id: str,
    media_id: str,
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        _require_contact(conn, contact_id)
        row = conn.execute("SELECT is_primary FROM dossier_media WHERE contact_id=? AND media_id=?", (contact_id, media_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image vault item not found")
        conn.execute("DELETE FROM dossier_media WHERE contact_id=? AND media_id=?", (contact_id, media_id))
        if bool(row["is_primary"]):
            replacement = conn.execute(
                "SELECT media_id FROM dossier_media WHERE contact_id=? ORDER BY created_at DESC LIMIT 1",
                (contact_id,),
            ).fetchone()
            if replacement:
                conn.execute("UPDATE dossier_media SET is_primary=1, updated_at=? WHERE media_id=?", (_utc_now(), replacement["media_id"]))
        conn.commit()
    return {"deleted": True, "media_id": media_id}


@router.get("/segments")
def list_segments(
    business_scope: str = "all",
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    business = business_scope.strip().lower() or "all"
    counts: Dict[str, int] = defaultdict(int)
    with _connect() as conn:
        params: Tuple[Any, ...] = ()
        sql = "SELECT segment_tags FROM party_business_role WHERE valid_to IS NULL"
        if business != "all":
            sql += " AND business_id=?"
            params = (business,)
        for row in conn.execute(sql, params).fetchall():
            for tag in _json_load(row["segment_tags"], []):
                value = str(tag).strip()
                if value:
                    counts[value] += 1
    return {"segments": [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: item[0].lower())]}


@router.post("/goals")
def create_goal(payload: GoalCreate, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    now = _utc_now()
    goal_id = _stable_id("goal", payload.business_scope or "all", payload.label, now)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO relevance_goal(goal_id, label, description, business_scope, weight, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (goal_id, payload.label.strip(), payload.description, payload.business_scope, float(payload.weight), now, now),
        )
        conn.commit()
    return {"goal_id": goal_id, **payload.model_dump()}


@router.get("/goals")
def list_goals(business_scope: str = "all", _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    business = business_scope.strip().lower() or "all"
    with _connect() as conn:
        if business == "all":
            rows = conn.execute("SELECT * FROM relevance_goal WHERE status='active' ORDER BY weight DESC, label").fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM relevance_goal
                WHERE status='active' AND (business_scope IS NULL OR business_scope='' OR business_scope=?)
                ORDER BY weight DESC, label
                """,
                (business,),
            ).fetchall()
    return {"goals": [dict(row) for row in rows]}


def _candidate_groups(conn: sqlite3.Connection) -> Dict[Tuple[str, str], List[str]]:
    groups: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    contacts = conn.execute("SELECT id, email, phone, address, organization_id FROM contacts").fetchall()
    for row in contacts:
        party_id = _party_id_for_contact(str(row["id"]))
        email_domain = _domain(str(row["email"] or ""))
        if email_domain and email_domain not in COMMON_EMAIL_DOMAINS:
            groups[("same_email_domain", email_domain)].append(party_id)
        area = _area_code(str(row["phone"] or ""))
        if area:
            groups[("same_area_code", area)].append(party_id)
        address = str(row["address"] or "")
        zip_code = _zip_code(address)
        if zip_code:
            groups[("same_zip", zip_code)].append(party_id)
        city = _city_key(address)
        if city:
            groups[("same_city", city)].append(party_id)
        organization = str(row["organization_id"] or "").strip().lower()
        if organization:
            groups[("shared_organization", organization)].append(party_id)
    return groups


CANDIDATE_SIGNAL_WEIGHT = {
    "shared_organization": 0.62,
    "same_zip": 0.20,
    "same_city": 0.12,
    "same_email_domain": 0.24,
    "same_area_code": 0.06,
}


@router.post("/scan")
def scan_relationship_candidates(
    business_scope: str = "all",
    max_new: int = Query(default=2500, ge=1, le=10000),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    """Discover weak-to-strong possible associations from existing local evidence.

    Geographic coincidence is intentionally retained at low confidence. It is a
    discovery clue, not proof that two people know one another.
    """

    _ensure_schema()
    now_dt = datetime.now(timezone.utc)
    expires = (now_dt + timedelta(days=90)).isoformat()
    inference_run = f"local-association-scan:v1:{now_dt.isoformat()}"
    created = 0
    seen_pairs: set[Tuple[str, str, str]] = set()

    with _connect() as conn:
        groups = _candidate_groups(conn)
        for (predicate, signal_value), parties in groups.items():
            unique_parties = sorted(set(parties))
            if len(unique_parties) < 2:
                continue
            # Avoid pathological explosion from broad signals such as area code.
            if predicate == "same_area_code" and len(unique_parties) > 40:
                continue
            if predicate == "same_city" and len(unique_parties) > 80:
                continue
            for left, right in combinations(unique_parties, 2):
                pair = (*_pair_key(left, right), predicate)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if conn.execute(
                    """
                    SELECT 1 FROM relationship_rejection
                    WHERE ((from_party=? AND to_party=?) OR (from_party=? AND to_party=?))
                      AND (predicate=? OR predicate IS NULL)
                    LIMIT 1
                    """,
                    (left, right, right, left, predicate),
                ).fetchone():
                    continue
                if conn.execute(
                    """
                    SELECT 1 FROM relationship_edge
                    WHERE ((from_party=? AND to_party=?) OR (from_party=? AND to_party=?))
                      AND predicate=? AND state IN ('asserted','verified')
                    LIMIT 1
                    """,
                    (left, right, right, left, predicate),
                ).fetchone():
                    continue

                confidence = CANDIDATE_SIGNAL_WEIGHT[predicate]
                candidate_id = _stable_id("candidate", left, right, predicate, business_scope)
                rationale = f"Possible association detected from {predicate.replace('_', ' ')}: {signal_value}. This is not a verified relationship."
                conn.execute(
                    """
                    INSERT INTO relationship_candidate(
                      candidate_id, from_party, to_party, predicate, confidence, rationale,
                      inference_run, review_state, business_scope, discovered_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                      confidence=MAX(relationship_candidate.confidence, excluded.confidence),
                      rationale=excluded.rationale,
                      inference_run=excluded.inference_run,
                      discovered_at=excluded.discovered_at,
                      expires_at=excluded.expires_at,
                      review_state=CASE WHEN relationship_candidate.review_state='rejected' THEN 'rejected' ELSE 'pending' END
                    """,
                    (
                        candidate_id,
                        left,
                        right,
                        predicate,
                        confidence,
                        rationale,
                        inference_run,
                        None if business_scope == "all" else business_scope,
                        now_dt.isoformat(),
                        expires,
                    ),
                )
                evidence_id = _stable_id("evidence", candidate_id, predicate, signal_value)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO evidence(evidence_id, source_type, source_ref, business_scope, captured_at, details)
                    VALUES (?, 'local_scan', ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        f"signal:{predicate}",
                        None if business_scope == "all" else business_scope,
                        now_dt.isoformat(),
                        json.dumps({"predicate": predicate, "signal": signal_value}),
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO relationship_candidate_evidence(candidate_id, evidence_id) VALUES (?, ?)",
                    (candidate_id, evidence_id),
                )
                created += 1
                if created >= max_new:
                    break
            if created >= max_new:
                break
        conn.commit()

    return {
        "status": "success",
        "candidates_scanned": len(seen_pairs),
        "candidates_written": created,
        "inference_run": inference_run,
        "note": "Geographic/domain proximity remains candidate evidence only; it is never promoted to fact by this scan.",
    }


@router.post("/candidates/{candidate_id}/review")
def review_candidate(candidate_id: str, payload: CandidateReview, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    decision = payload.decision.strip().lower()
    if decision not in {"accept", "reject"}:
        raise HTTPException(status_code=400, detail="decision must be accept or reject")
    now = _utc_now()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM relationship_candidate WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")
        candidate = dict(row)
        if decision == "accept":
            edge_id = _stable_id("edge", candidate["from_party"], candidate["to_party"], candidate["predicate"])
            conn.execute(
                """
                INSERT INTO relationship_edge(
                  edge_id, from_party, to_party, predicate, state, confidence, business_scope, created_at
                ) VALUES (?, ?, ?, ?, 'verified', 1.0, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET state='verified', confidence=1.0, valid_to=NULL
                """,
                (
                    edge_id,
                    candidate["from_party"],
                    candidate["to_party"],
                    candidate["predicate"],
                    candidate["business_scope"],
                    now,
                ),
            )
            conn.execute("UPDATE relationship_candidate SET review_state='accepted' WHERE candidate_id=?", (candidate_id,))
            result = {"candidate_id": candidate_id, "decision": "accepted", "edge_id": edge_id}
        else:
            rejection_id = _stable_id("rejection", candidate["from_party"], candidate["to_party"], candidate["predicate"])
            conn.execute(
                """
                INSERT OR REPLACE INTO relationship_rejection(
                  rejection_id, from_party, to_party, predicate, reason, evidence_snapshot, rejected_at, business_scope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rejection_id,
                    candidate["from_party"],
                    candidate["to_party"],
                    candidate["predicate"],
                    payload.reason,
                    json.dumps(candidate),
                    now,
                    candidate["business_scope"],
                ),
            )
            conn.execute("UPDATE relationship_candidate SET review_state='rejected' WHERE candidate_id=?", (candidate_id,))
            result = {"candidate_id": candidate_id, "decision": "rejected", "rejection_id": rejection_id}
        conn.commit()
    return result


def _iter_graph_edges(
    conn: sqlite3.Connection,
    include_candidates: bool,
    business_scope: str,
) -> Iterable[Dict[str, Any]]:
    if business_scope == "all":
        strict_rows = conn.execute(
            "SELECT edge_id, from_party, to_party, predicate, confidence, business_scope FROM relationship_edge WHERE state IN ('asserted','verified') AND valid_to IS NULL"
        ).fetchall()
    else:
        strict_rows = conn.execute(
            """
            SELECT edge_id, from_party, to_party, predicate, confidence, business_scope
            FROM relationship_edge
            WHERE state IN ('asserted','verified') AND valid_to IS NULL
              AND (business_scope IS NULL OR business_scope='' OR business_scope=?)
            """,
            (business_scope,),
        ).fetchall()
    for row in strict_rows:
        item = dict(row)
        item["edge_kind"] = "verified"
        yield item

    if include_candidates:
        if business_scope == "all":
            candidate_rows = conn.execute(
                "SELECT candidate_id AS edge_id, from_party, to_party, predicate, confidence, business_scope, rationale FROM relationship_candidate WHERE review_state='pending' AND expires_at>?",
                (_utc_now(),),
            ).fetchall()
        else:
            candidate_rows = conn.execute(
                """
                SELECT candidate_id AS edge_id, from_party, to_party, predicate, confidence, business_scope, rationale
                FROM relationship_candidate
                WHERE review_state='pending' AND expires_at>?
                  AND (business_scope IS NULL OR business_scope='' OR business_scope=?)
                """,
                (_utc_now(), business_scope),
            ).fetchall()
        for row in candidate_rows:
            item = dict(row)
            item["edge_kind"] = "candidate"
            yield item


def _party_name(conn: sqlite3.Connection, party_id: str) -> str:
    row = conn.execute("SELECT display_name FROM party WHERE party_id=?", (party_id,)).fetchone()
    return str(row["display_name"] if row else party_id)


def _shortest_path(
    conn: sqlite3.Connection,
    start: str,
    target: str,
    include_candidates: bool,
    business_scope: str,
    max_depth: int = 6,
) -> Optional[Dict[str, Any]]:
    adjacency: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    for edge in _iter_graph_edges(conn, include_candidates, business_scope):
        left = str(edge["from_party"])
        right = str(edge["to_party"])
        adjacency[left].append((right, edge))
        adjacency[right].append((left, edge))

    queue = deque([(start, [])])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        for neighbor, edge in adjacency.get(node, []):
            next_path = path + [(node, neighbor, edge)]
            if neighbor == target:
                confidence = 1.0
                steps: List[Dict[str, Any]] = []
                has_candidate = False
                for from_party, to_party, path_edge in next_path:
                    edge_conf = float(path_edge.get("confidence") or 0.0)
                    if path_edge.get("edge_kind") == "candidate":
                        edge_conf *= 0.65
                        has_candidate = True
                    confidence *= max(0.0, min(1.0, edge_conf))
                    steps.append(
                        {
                            "from_party": from_party,
                            "from_name": _party_name(conn, from_party),
                            "to_party": to_party,
                            "to_name": _party_name(conn, to_party),
                            "predicate": path_edge.get("predicate"),
                            "edge_kind": path_edge.get("edge_kind"),
                            "edge_confidence": path_edge.get("confidence"),
                            "rationale": path_edge.get("rationale"),
                        }
                    )
                return {
                    "degrees": len(next_path),
                    "path_confidence": round(confidence, 6),
                    "contains_unverified": has_candidate,
                    "steps": steps,
                }
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, next_path))
    return None


@router.get("/parties/{party_id}/path/{target_party_id}")
def six_degree_path(
    party_id: str,
    target_party_id: str,
    business_scope: str = "all",
    include_candidates: bool = True,
    max_depth: int = Query(default=6, ge=1, le=6),
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        path = _shortest_path(conn, party_id, target_party_id, include_candidates, business_scope, max_depth)
    if not path:
        return {
            "connected": False,
            "degrees": None,
            "business_scope": business_scope,
            "include_candidates": include_candidates,
        }
    return {
        "connected": True,
        "business_scope": business_scope,
        "include_candidates": include_candidates,
        **path,
    }


def _direct_connection_strength(conn: sqlite3.Connection, party_id: str, business_scope: str) -> Tuple[float, List[str]]:
    factors: List[str] = []
    strict_query = """
      SELECT confidence, predicate FROM relationship_edge
      WHERE (from_party=? OR to_party=?) AND state IN ('asserted','verified') AND valid_to IS NULL
    """
    params: List[Any] = [party_id, party_id]
    if business_scope != "all":
        strict_query += " AND (business_scope IS NULL OR business_scope='' OR business_scope=?)"
        params.append(business_scope)
    strict = conn.execute(strict_query, tuple(params)).fetchall()
    strength = max([float(row["confidence"] or 0.0) for row in strict], default=0.0)
    if strict:
        factors.append(f"{len(strict)} verified/asserted direct relationship edge(s)")

    candidate_query = """
      SELECT confidence, predicate FROM relationship_candidate
      WHERE (from_party=? OR to_party=?) AND review_state='pending' AND expires_at>?
    """
    candidate_params: List[Any] = [party_id, party_id, _utc_now()]
    if business_scope != "all":
        candidate_query += " AND (business_scope IS NULL OR business_scope='' OR business_scope=?)"
        candidate_params.append(business_scope)
    candidates = conn.execute(candidate_query, tuple(candidate_params)).fetchall()
    if candidates:
        candidate_strength = max(float(row["confidence"] or 0.0) * 0.65 for row in candidates)
        strength = max(strength, candidate_strength)
        factors.append(f"{len(candidates)} unverified association candidate(s)")
    return min(1.0, strength), factors


def _relevance_for_party(conn: sqlite3.Connection, party_id: str, business_scope: str, goal_id: Optional[str]) -> Dict[str, Any]:
    score = 0.0
    factors: List[Dict[str, Any]] = []
    strength, connection_factors = _direct_connection_strength(conn, party_id, business_scope)
    if strength:
        points = 28.0 * strength
        score += points
        factors.append({"factor": "relationship_strength", "points": round(points, 2), "detail": "; ".join(connection_factors)})

    if business_scope != "all":
        role = conn.execute(
            "SELECT role, segment_tags FROM party_business_role WHERE party_id=? AND business_id=? AND valid_to IS NULL",
            (party_id, business_scope),
        ).fetchone()
        if role:
            score += 18.0
            factors.append({"factor": "business_context", "points": 18.0, "detail": f"Associated with {business_scope}; role={role['role'] or 'unspecified'}"})

    contact_id = _contact_id_from_party(party_id)
    if contact_id:
        row = conn.execute(
            "SELECT email, phone, address, last_contacted_at, next_follow_up_at, notes FROM contacts WHERE id=?",
            (contact_id,),
        ).fetchone()
        if row:
            if row["email"]:
                score += 3.0
                factors.append({"factor": "reachable_email", "points": 3.0, "detail": "Email channel available"})
            if row["phone"]:
                score += 4.0
                factors.append({"factor": "reachable_phone", "points": 4.0, "detail": "Phone/SMS channel available"})
            if row["address"]:
                score += 2.0
                factors.append({"factor": "known_location", "points": 2.0, "detail": "Address/proximity evidence available"})
            if row["last_contacted_at"]:
                score += 8.0
                factors.append({"factor": "existing_history", "points": 8.0, "detail": "Prior contact history exists"})
            if row["next_follow_up_at"]:
                score += 5.0
                factors.append({"factor": "active_follow_up", "points": 5.0, "detail": "A follow-up is scheduled"})
            if row["notes"]:
                score += 2.0
                factors.append({"factor": "known_context", "points": 2.0, "detail": "Relationship notes exist"})

    signal_rows = conn.execute(
        """
        SELECT predicate, confidence, rationale
        FROM relationship_candidate
        WHERE (from_party=? OR to_party=?) AND review_state='pending' AND expires_at>?
        ORDER BY confidence DESC LIMIT 20
        """,
        (party_id, party_id, _utc_now()),
    ).fetchall()
    signal_points = 0.0
    for row in signal_rows:
        predicate = str(row["predicate"])
        if predicate == "same_zip":
            signal_points += 4.0
        elif predicate == "same_city":
            signal_points += 2.0
        elif predicate == "shared_organization":
            signal_points += 9.0
        elif predicate == "same_email_domain":
            signal_points += 4.0
        elif predicate == "same_area_code":
            signal_points += 0.5
    if signal_points:
        signal_points = min(14.0, signal_points)
        score += signal_points
        factors.append({"factor": "association_discovery", "points": round(signal_points, 2), "detail": "Includes weak geographic/domain clues; these do not prove a relationship"})

    goal = None
    if goal_id:
        goal = conn.execute("SELECT * FROM relevance_goal WHERE goal_id=? AND status='active'", (goal_id,)).fetchone()
    elif business_scope != "all":
        goal = conn.execute(
            "SELECT * FROM relevance_goal WHERE status='active' AND business_scope=? ORDER BY weight DESC, updated_at DESC LIMIT 1",
            (business_scope,),
        ).fetchone()
    if goal:
        goal_points = min(20.0, max(0.0, float(goal["weight"] or 1.0) * 10.0))
        score += goal_points
        factors.append({"factor": "active_goal", "points": round(goal_points, 2), "detail": str(goal["label"])})

    score = round(min(100.0, max(0.0, score)), 2)
    rationale = "Contextual relevance to the user's current relationship/business world. It is not a rating of human worth."
    return {
        "relevance_score": score,
        "connection_strength": round(strength, 4),
        "degrees": 1 if strength > 0 else None,
        "factors": factors,
        "rationale": rationale,
        "goal_id": str(goal["goal_id"]) if goal else None,
    }


@router.post("/parties/{party_id}/relevance/recalculate")
def recalculate_relevance(party_id: str, payload: RelevanceRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    business = (payload.business_scope or "all").strip().lower()
    now = _utc_now()
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM party WHERE party_id=?", (party_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Party not found")
        result = _relevance_for_party(conn, party_id, business, payload.goal_id)
        assessment_id = _stable_id("relevance", party_id, business, result.get("goal_id") or "general", now)
        conn.execute(
            """
            INSERT INTO relevance_assessment(
              assessment_id, party_id, business_scope, goal_id, relevance_score,
              connection_strength, degrees, factors, rationale, source_type,
              model_version, assessed_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'deterministic', 'relevance-v1', ?, ?)
            """,
            (
                assessment_id,
                party_id,
                None if business == "all" else business,
                result.get("goal_id"),
                result["relevance_score"],
                result["connection_strength"],
                result["degrees"],
                json.dumps(result["factors"]),
                result["rationale"],
                now,
                (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            ),
        )
        conn.commit()
    return {"assessment_id": assessment_id, "business_scope": business, **result}


@router.get("/parties/{party_id}/connections")
def party_connections(
    party_id: str,
    business_scope: str = "all",
    _: str = Depends(verify_admin),
) -> Dict[str, Any]:
    _ensure_schema()
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM party WHERE party_id=?", (party_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Party not found")
        strict = []
        candidates = []
        for edge in _iter_graph_edges(conn, True, business_scope):
            if party_id not in {str(edge["from_party"]), str(edge["to_party"])}:
                continue
            other = str(edge["to_party"] if str(edge["from_party"]) == party_id else edge["from_party"])
            item = dict(edge)
            item["other_party"] = other
            item["other_name"] = _party_name(conn, other)
            if edge["edge_kind"] == "candidate":
                candidates.append(item)
            else:
                strict.append(item)
        relevance = conn.execute(
            """
            SELECT * FROM relevance_assessment
            WHERE party_id=? AND (?='all' OR COALESCE(business_scope,'') IN ('',?))
            ORDER BY assessed_at DESC LIMIT 1
            """,
            (party_id, business_scope, business_scope),
        ).fetchone()
    return {
        "party_id": party_id,
        "business_scope": business_scope,
        "verified": strict,
        "candidates": candidates,
        "latest_relevance": dict(relevance) if relevance else None,
    }
