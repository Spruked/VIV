from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from cali_skg.api.relationship_routes import (
    _db_path,
    _ensure_schema,
    _party_id_for_contact,
    scan_relationship_candidates,
    verify_admin,
)
from cali_skg.core.cali_personal_skg import get_cali_skg

router = APIRouter(prefix="/cali/intelligence/vcard", tags=["cali-contact-io"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_phone(value: str) -> str:
    raw = str(value or "").strip()
    plus = raw.startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return ("+" if plus else "") + digits


def _unfold(text: str) -> List[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: List[str] = []
    for raw in normalized.split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape_vcard(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _escape_vcard(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold_line(line: str, width: int = 72) -> str:
    if len(line.encode("utf-8")) <= 75:
        return line
    chunks: List[str] = []
    current = ""
    current_bytes = 0
    for char in line:
        char_bytes = len(char.encode("utf-8"))
        limit = width if not chunks else width - 1
        if current and current_bytes + char_bytes > limit:
            chunks.append(current)
            current = char
            current_bytes = char_bytes
        else:
            current += char
            current_bytes += char_bytes
    if current:
        chunks.append(current)
    return "\r\n ".join(chunks)


def _parse_card(lines: List[str]) -> Dict[str, Any]:
    card: Dict[str, Any] = {
        "emails": [],
        "phones": [],
        "addresses": [],
        "segments": [],
    }
    for line in lines:
        if ":" not in line:
            continue
        lhs, rhs = line.split(":", 1)
        name = lhs.split(";", 1)[0].upper()
        value = _unescape_vcard(rhs.strip())
        if name == "FN":
            card["name"] = value
        elif name == "N" and not card.get("name"):
            parts = [_unescape_vcard(part) for part in rhs.split(";")]
            card["name"] = " ".join(part for part in [parts[1] if len(parts) > 1 else "", parts[0] if parts else ""] if part).strip()
        elif name == "EMAIL" and value:
            card["emails"].append(value)
        elif name == "TEL" and value:
            card["phones"].append(value)
        elif name == "ADR" and value:
            parts = [_unescape_vcard(part) for part in rhs.split(";")]
            card["addresses"].append(", ".join(part for part in parts if part))
        elif name == "ORG":
            card["organization"] = value
        elif name == "TITLE":
            card["title"] = value
        elif name == "NOTE":
            card["notes"] = value
        elif name == "UID":
            card["uid"] = value
        elif name == "REV":
            card["rev"] = value
        elif name == "X-CALI-BUSINESS-SCOPE":
            card["business_scope"] = value
        elif name == "X-CALI-SEGMENT":
            card["segments"].extend(item.strip() for item in value.split(",") if item.strip())
        elif name == "X-CALI-RELATIONSHIP":
            card["relationship"] = value
    card["emails"] = list(dict.fromkeys(_normalize_email(item) for item in card["emails"] if _normalize_email(item)))
    card["phones"] = list(dict.fromkeys(item.strip() for item in card["phones"] if item.strip()))
    card["segments"] = list(dict.fromkeys(card["segments"]))
    return card


def parse_vcards(text: str) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    active: List[str] = []
    inside = False
    for line in _unfold(text):
        upper = line.strip().upper()
        if upper == "BEGIN:VCARD":
            active = []
            inside = True
            continue
        if upper == "END:VCARD":
            if inside:
                cards.append(_parse_card(active))
            active = []
            inside = False
            continue
        if inside:
            active.append(line)
    return cards


def _ensure_io_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS vcard_import_index (
          import_key TEXT PRIMARY KEY,
          card_uid TEXT,
          revision TEXT,
          content_hash TEXT NOT NULL,
          party_id TEXT,
          business_scope TEXT,
          imported_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS identity_review_queue (
          review_id TEXT PRIMARY KEY,
          incoming_name TEXT,
          incoming_email TEXT,
          incoming_phone TEXT,
          possible_party_id TEXT,
          reason TEXT NOT NULL,
          score REAL NOT NULL,
          source_type TEXT NOT NULL,
          source_ref TEXT,
          review_state TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL,
          resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_identity_review_state
          ON identity_review_queue(review_state, created_at);
        """
    )


class VCardImportRequest(BaseModel):
    content: str = Field(min_length=1)
    business_scope: str = "personal"
    run_relationship_scan: bool = True


class VCardExportRequest(BaseModel):
    contact_ids: List[str] = Field(default_factory=list)
    business_scope: str = "all"


def _find_email_contact(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    if not email:
        return None
    return conn.execute("SELECT * FROM contacts WHERE lower(email)=? LIMIT 1", (_normalize_email(email),)).fetchone()


def _find_phone_contacts(conn: sqlite3.Connection, phone: str) -> List[sqlite3.Row]:
    normalized = _normalize_phone(phone)
    if not normalized:
        return []
    rows = conn.execute("SELECT * FROM contacts WHERE phone IS NOT NULL AND trim(phone)<>''").fetchall()
    return [row for row in rows if _normalize_phone(str(row["phone"] or "")) == normalized]


def _is_tombstoned(conn: sqlite3.Connection, claim_type: str, normalized: str, business_scope: str) -> bool:
    if not normalized:
        return False
    value_hash = _sha(normalized)
    row = conn.execute(
        """
        SELECT 1 FROM import_tombstone
        WHERE value_hash=? AND (claim_type IS NULL OR claim_type=?)
          AND (business_scope IS NULL OR business_scope='' OR business_scope=?)
        LIMIT 1
        """,
        (value_hash, claim_type, business_scope),
    ).fetchone()
    return bool(row)


def _queue_phone_review(
    conn: sqlite3.Connection,
    card: Dict[str, Any],
    phone: str,
    existing_contact_id: str,
    source_ref: str,
) -> None:
    possible_party = _party_id_for_contact(existing_contact_id)
    review_id = "review:" + _sha(f"{source_ref}|{_normalize_phone(phone)}|{possible_party}")[:32]
    conn.execute(
        """
        INSERT OR IGNORE INTO identity_review_queue(
          review_id, incoming_name, incoming_email, incoming_phone,
          possible_party_id, reason, score, source_type, source_ref,
          review_state, created_at
        ) VALUES (?, ?, ?, ?, ?, 'same_phone', 0.88, 'vcard', ?, 'pending', ?)
        """,
        (
            review_id,
            str(card.get("name") or ""),
            str((card.get("emails") or [""])[0] or ""),
            phone,
            possible_party,
            source_ref,
            _utc_now(),
        ),
    )


@router.post("/import")
def import_vcards(payload: VCardImportRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    cards = parse_vcards(payload.content)
    if not cards:
        raise HTTPException(status_code=400, detail="No vCard records found")

    cali = get_cali_skg()
    created = 0
    existing = 0
    skipped_tombstone = 0
    review_queued = 0
    idempotent_noop = 0
    errors: List[str] = []
    imported_ids: List[str] = []

    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_io_tables(conn)

        for index, card in enumerate(cards):
            card_json = json.dumps(card, sort_keys=True, ensure_ascii=False)
            content_hash = _sha(card_json)
            uid = str(card.get("uid") or "").strip()
            rev = str(card.get("rev") or "").strip()
            import_key = _sha(f"{uid}|{rev}|{content_hash}")
            source_ref = f"vcard:{uid or content_hash[:16]}"

            if conn.execute("SELECT 1 FROM vcard_import_index WHERE import_key=?", (import_key,)).fetchone():
                idempotent_noop += 1
                continue

            emails = list(card.get("emails") or [])
            phones = list(card.get("phones") or [])
            business_scope = str(card.get("business_scope") or payload.business_scope or "personal").strip() or "personal"

            blocked = False
            for email in emails:
                if _is_tombstoned(conn, "email", _normalize_email(email), business_scope):
                    blocked = True
                    break
            if not blocked:
                for phone in phones:
                    if _is_tombstoned(conn, "phone", _normalize_phone(phone), business_scope):
                        blocked = True
                        break
            if blocked:
                skipped_tombstone += 1
                continue

            match = None
            for email in emails:
                match = _find_email_contact(conn, email)
                if match:
                    break

            if match:
                contact_id = str(match["id"])
                party_id = _party_id_for_contact(contact_id)
                existing += 1
            else:
                for phone in phones:
                    phone_matches = _find_phone_contacts(conn, phone)
                    for phone_match in phone_matches:
                        _queue_phone_review(conn, card, phone, str(phone_match["id"]), source_ref)
                        review_queued += 1

                name = str(card.get("name") or (emails[0].split("@", 1)[0] if emails else "Imported Contact")).strip()
                notes_parts = [str(card.get("notes") or "").strip()]
                if card.get("organization"):
                    notes_parts.append(f"Organization: {card['organization']}")
                if card.get("title"):
                    notes_parts.append(f"Title: {card['title']}")
                notes = "\n".join(part for part in notes_parts if part) or None
                try:
                    created_result = cali.add_contact(
                        name=name,
                        contact_type="personal" if business_scope == "personal" else "professional",
                        phone=phones[0] if phones else None,
                        email=emails[0] if emails else None,
                        address=(card.get("addresses") or [None])[0],
                        notes=notes,
                        priority=0,
                        crm_stage="active",
                        lead_source="vcard_import",
                        owner="bryan@spruked.com",
                    )
                    contact_id = str(created_result.get("contact_id") or "")
                    if not contact_id:
                        raise RuntimeError("contact id missing after import")
                    party_id = _party_id_for_contact(contact_id)
                    created += 1
                except Exception as exc:
                    errors.append(f"card_{index}:{exc}")
                    continue

            imported_ids.append(contact_id)
            role_id = "role:" + _sha(f"{party_id}|{business_scope}")[:32]
            tags = list(card.get("segments") or [])
            conn.execute(
                """
                INSERT OR IGNORE INTO business_context(business_id, label, isolation, status, created_at)
                VALUES (?, ?, 'scoped', 'active', ?)
                """,
                (business_scope, business_scope.replace("_", " ").title(), _utc_now()),
            )
            conn.execute(
                """
                INSERT INTO party_business_role(
                  role_id, party_id, business_id, role, segment_tags, visibility, valid_from, created_at
                ) VALUES (?, ?, ?, ?, ?, 'scoped', ?, ?)
                ON CONFLICT(role_id) DO UPDATE SET
                  role=COALESCE(excluded.role, party_business_role.role),
                  segment_tags=excluded.segment_tags,
                  valid_to=NULL
                """,
                (
                    role_id,
                    party_id,
                    business_scope,
                    card.get("relationship"),
                    json.dumps(tags),
                    _utc_now(),
                    _utc_now(),
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO vcard_import_index(
                  import_key, card_uid, revision, content_hash, party_id, business_scope, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (import_key, uid or None, rev or None, content_hash, party_id, business_scope, _utc_now()),
            )
        conn.commit()

    # The canonical Party backfill and claims are idempotent; rerun after legacy
    # contact insertion so newly-created contacts immediately join the identity graph.
    _ensure_schema()
    scan_result = None
    if payload.run_relationship_scan:
        scan_result = scan_relationship_candidates(
            business_scope=payload.business_scope or "all",
            max_new=2500,
            _="internal-vcard-import",
        )

    return {
        "status": "success",
        "cards_seen": len(cards),
        "created": created,
        "existing_exact_email": existing,
        "phone_review_queued": review_queued,
        "tombstone_skipped": skipped_tombstone,
        "idempotent_noop": idempotent_noop,
        "contact_ids": imported_ids,
        "relationship_scan": scan_result,
        "errors": errors,
    }


def _card_for_contact(row: sqlite3.Row, roles: List[sqlite3.Row]) -> str:
    contact_id = str(row["id"])
    uid = f"urn:uuid:cali-{contact_id}"
    lines = [
        "BEGIN:VCARD",
        "VERSION:4.0",
        f"UID:{_escape_vcard(uid)}",
        f"FN:{_escape_vcard(row['name'])}",
    ]
    if row["email"]:
        lines.append(f"EMAIL:{_escape_vcard(row['email'])}")
    if row["phone"]:
        lines.append(f"TEL:{_escape_vcard(row['phone'])}")
    if row["address"]:
        lines.append(f"ADR:;;{_escape_vcard(row['address'])};;;;")
    if row["notes"]:
        lines.append(f"NOTE:{_escape_vcard(row['notes'])}")
    for role in roles:
        lines.append(f"X-CALI-BUSINESS-SCOPE:{_escape_vcard(role['business_id'])}")
        if role["role"]:
            lines.append(f"X-CALI-RELATIONSHIP:{_escape_vcard(role['role'])}")
        tags = json.loads(str(role["segment_tags"] or "[]")) if role["segment_tags"] else []
        if tags:
            lines.append(f"X-CALI-SEGMENT:{_escape_vcard(','.join(str(tag) for tag in tags))}")
    revision = str(row["updated_at"] or row["created_at"] or _utc_now()).replace("-", "").replace(":", "").replace(".", "")
    lines.append(f"REV:{_escape_vcard(revision)}")
    lines.append("END:VCARD")
    return "\r\n".join(_fold_line(line) for line in lines) + "\r\n"


@router.post("/export")
def export_vcards(payload: VCardExportRequest, _: str = Depends(verify_admin)) -> Response:
    _ensure_schema()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        params: List[Any] = []
        where: List[str] = []
        if payload.contact_ids:
            placeholders = ",".join("?" for _ in payload.contact_ids)
            where.append(f"id IN ({placeholders})")
            params.extend(payload.contact_ids)
        if payload.business_scope != "all":
            where.append(
                "EXISTS (SELECT 1 FROM party_business_role pbr WHERE pbr.party_id=('legacy-contact:' || contacts.id) AND pbr.business_id=? AND pbr.valid_to IS NULL)"
            )
            params.append(payload.business_scope)
        sql = "SELECT * FROM contacts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY name COLLATE NOCASE"
        rows = conn.execute(sql, tuple(params)).fetchall()
        cards: List[str] = []
        for row in rows:
            roles = conn.execute(
                "SELECT business_id, role, segment_tags FROM party_business_role WHERE party_id=? AND valid_to IS NULL",
                (_party_id_for_contact(str(row["id"])),),
            ).fetchall()
            cards.append(_card_for_contact(row, roles))

    filename = "cali-contacts.vcf" if payload.business_scope == "all" else f"cali-{payload.business_scope}-contacts.vcf"
    return Response(
        content="".join(cards),
        media_type="text/vcard; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/review-queue")
def identity_review_queue(_: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_io_tables(conn)
        rows = conn.execute(
            "SELECT * FROM identity_review_queue WHERE review_state='pending' ORDER BY score DESC, created_at DESC"
        ).fetchall()
    return {"items": [dict(row) for row in rows], "count": len(rows)}
