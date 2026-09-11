from __future__ import annotations

import csv
import hashlib
import io
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

router = APIRouter(prefix="/cali/intelligence/csv", tags=["cali-contact-io"])


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


def _header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _row_map(row: Dict[str, Any]) -> Dict[str, str]:
    mapped: Dict[str, str] = {}
    for key, value in row.items():
        normalized = _header_key(str(key or ""))
        if normalized:
            mapped[normalized] = str(value or "").strip()
    return mapped


def _first(row: Dict[str, str], *aliases: str) -> str:
    for alias in aliases:
        value = row.get(_header_key(alias), "").strip()
        if value:
            return value
    return ""


def _split_tags(value: str) -> List[str]:
    if not value:
        return []
    return list(dict.fromkeys(part.strip() for part in re.split(r"[,;|]", value) if part.strip()))


def _collect_emails(row: Dict[str, str]) -> List[str]:
    values: List[str] = []
    for key, value in row.items():
        compact = key.replace(" ", "")
        if value and "email" in compact and "type" not in compact:
            normalized = _normalize_email(value)
            if normalized and normalized not in values:
                values.append(normalized)
    return values


def _collect_phones(row: Dict[str, str]) -> List[str]:
    values: List[str] = []
    for key, value in row.items():
        compact = key.replace(" ", "")
        is_phone = "phone" in compact or compact in {"mobile", "cell", "cellphone", "telephone", "tel"}
        if value and is_phone and "type" not in compact:
            if value not in values:
                values.append(value)
    return values


def _compose_address(row: Dict[str, str]) -> str:
    formatted = _first(
        row,
        "Address",
        "Formatted Address",
        "Address 1 Formatted",
        "Business Address",
        "Home Address",
        "Mailing Address",
    )
    if formatted:
        return formatted

    street = _first(
        row,
        "Street",
        "Street Address",
        "Address 1 Street",
        "Business Street",
        "Home Street",
    )
    city = _first(row, "City", "Address 1 City", "Business City", "Home City")
    state = _first(
        row,
        "State",
        "Region",
        "Address 1 Region",
        "Business State",
        "Home State",
    )
    postal = _first(
        row,
        "Postal Code",
        "Zip",
        "ZIP Code",
        "Address 1 Postal Code",
        "Business Postal Code",
        "Home Postal Code",
    )
    country = _first(
        row,
        "Country",
        "Country Region",
        "Address 1 Country",
        "Business Country Region",
        "Home Country Region",
    )
    return ", ".join(part for part in [street, city, state, postal, country] if part)


def _parse_priority(value: str) -> int:
    try:
        return int(float(str(value or "0").strip() or "0"))
    except (TypeError, ValueError):
        return 0


def _parse_csv_row(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = _row_map(raw)
    if not any(row.values()):
        return None

    name = _first(row, "Name", "Full Name", "Display Name", "Contact Name")
    if not name:
        first = _first(row, "First Name", "Given Name")
        middle = _first(row, "Middle Name", "Additional Name")
        last = _first(row, "Last Name", "Family Name", "Surname")
        name = " ".join(part for part in [first, middle, last] if part).strip()

    emails = _collect_emails(row)
    phones = _collect_phones(row)
    address = _compose_address(row)
    organization = _first(row, "Company", "Company Name", "Organization", "Organization 1 Name")
    title = _first(row, "Job Title", "Title", "Organization 1 Title")
    notes = _first(row, "Notes", "Note", "Comments")
    business_scope = _first(row, "Business Scope", "Scope", "VIV Business Scope")
    relationship = _first(row, "Relationship", "Role", "VIV Relationship")
    segments = _split_tags(_first(row, "Segment Tags", "Segments", "Tags", "Labels", "Categories"))

    return {
        "name": name,
        "emails": emails,
        "phones": phones,
        "addresses": [address] if address else [],
        "organization": organization,
        "title": title,
        "notes": notes,
        "uid": _first(row, "Contact ID", "UID", "ID"),
        "rev": _first(row, "Updated At", "Modified At", "Last Modified", "Revision"),
        "business_scope": business_scope,
        "relationship": relationship,
        "segments": segments,
        "contact_type": _first(row, "Type", "Contact Type"),
        "priority": _parse_priority(_first(row, "Priority")),
        "crm_stage": _first(row, "CRM Stage", "Stage"),
        "lead_source": _first(row, "Lead Source", "Source"),
        "owner": _first(row, "Owner"),
        "next_follow_up_at": _first(row, "Next Follow Up At", "Next Follow Up", "Follow Up"),
    }


def parse_csv_contacts(text: str) -> List[Dict[str, Any]]:
    content = str(text or "").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return []
    cards: List[Dict[str, Any]] = []
    for raw in reader:
        card = _parse_csv_row(raw)
        if card:
            cards.append(card)
    return cards


def _ensure_csv_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS csv_import_index (
          import_key TEXT PRIMARY KEY,
          row_uid TEXT,
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


class CsvImportRequest(BaseModel):
    content: str = Field(min_length=1)
    business_scope: str = "personal"
    run_relationship_scan: bool = True


class CsvExportRequest(BaseModel):
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
    review_id = "review:" + _sha(f"csv|{source_ref}|{_normalize_phone(phone)}|{possible_party}")[:32]
    conn.execute(
        """
        INSERT OR IGNORE INTO identity_review_queue(
          review_id, incoming_name, incoming_email, incoming_phone,
          possible_party_id, reason, score, source_type, source_ref,
          review_state, created_at
        ) VALUES (?, ?, ?, ?, ?, 'same_phone', 0.88, 'csv', ?, 'pending', ?)
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
def import_csv_contacts(payload: CsvImportRequest, _: str = Depends(verify_admin)) -> Dict[str, Any]:
    _ensure_schema()
    cards = parse_csv_contacts(payload.content)
    if not cards:
        raise HTTPException(status_code=400, detail="No CSV contact records found")

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
        _ensure_csv_tables(conn)

        for index, card in enumerate(cards):
            card_json = json.dumps(card, sort_keys=True, ensure_ascii=False)
            content_hash = _sha(card_json)
            uid = str(card.get("uid") or "").strip()
            rev = str(card.get("rev") or "").strip()
            import_key = _sha(f"csv|{uid}|{rev}|{content_hash}")
            source_ref = f"csv:{uid or content_hash[:16]}"

            if conn.execute("SELECT 1 FROM csv_import_index WHERE import_key=?", (import_key,)).fetchone():
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
                    for phone_match in _find_phone_contacts(conn, phone):
                        _queue_phone_review(conn, card, phone, str(phone_match["id"]), source_ref)
                        review_queued += 1

                name = str(card.get("name") or (emails[0].split("@", 1)[0] if emails else "Imported Contact")).strip()
                notes_parts = [str(card.get("notes") or "").strip()]
                if card.get("organization"):
                    notes_parts.append(f"Organization: {card['organization']}")
                if card.get("title"):
                    notes_parts.append(f"Title: {card['title']}")
                notes = "\n".join(part for part in notes_parts if part) or None
                contact_type = str(card.get("contact_type") or "").strip().lower()
                if not contact_type:
                    contact_type = "personal" if business_scope == "personal" else "professional"
                try:
                    created_result = cali.add_contact(
                        name=name,
                        contact_type=contact_type,
                        phone=phones[0] if phones else None,
                        email=emails[0] if emails else None,
                        address=(card.get("addresses") or [None])[0],
                        notes=notes,
                        priority=int(card.get("priority") or 0),
                        crm_stage=str(card.get("crm_stage") or "active").strip() or "active",
                        lead_source=str(card.get("lead_source") or "csv_import").strip() or "csv_import",
                        owner=str(card.get("owner") or "bryan@spruked.com").strip() or "bryan@spruked.com",
                        next_follow_up_at=str(card.get("next_follow_up_at") or "").strip() or None,
                    )
                    contact_id = str(created_result.get("contact_id") or "")
                    if not contact_id:
                        raise RuntimeError("contact id missing after import")
                    party_id = _party_id_for_contact(contact_id)
                    created += 1
                except Exception as exc:
                    errors.append(f"row_{index}:{exc}")
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
                INSERT OR IGNORE INTO csv_import_index(
                  import_key, row_uid, revision, content_hash, party_id, business_scope, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (import_key, uid or None, rev or None, content_hash, party_id, business_scope, _utc_now()),
            )
        conn.commit()

    _ensure_schema()
    scan_result = None
    if payload.run_relationship_scan:
        scan_result = scan_relationship_candidates(
            business_scope=payload.business_scope or "all",
            max_new=2500,
            _="internal-csv-import",
        )

    return {
        "status": "success",
        "rows_seen": len(cards),
        "created": created,
        "existing_exact_email": existing,
        "phone_review_queued": review_queued,
        "tombstone_skipped": skipped_tombstone,
        "idempotent_noop": idempotent_noop,
        "contact_ids": imported_ids,
        "relationship_scan": scan_result,
        "errors": errors,
    }


CSV_FIELDS = [
    "Contact ID",
    "Name",
    "Type",
    "Email",
    "Phone",
    "Address",
    "Notes",
    "Priority",
    "CRM Stage",
    "Lead Source",
    "Owner",
    "Last Contacted At",
    "Next Follow Up At",
    "Business Scope",
    "Relationship",
    "Segment Tags",
    "Created At",
    "Updated At",
]


def _csv_row_for_contact(row: sqlite3.Row, role: Optional[sqlite3.Row]) -> Dict[str, Any]:
    tags: List[str] = []
    if role is not None and role["segment_tags"]:
        try:
            parsed = json.loads(str(role["segment_tags"] or "[]"))
            if isinstance(parsed, list):
                tags = [str(item) for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            tags = _split_tags(str(role["segment_tags"] or ""))
    return {
        "Contact ID": row["id"],
        "Name": row["name"],
        "Type": row["type"],
        "Email": row["email"],
        "Phone": row["phone"],
        "Address": row["address"],
        "Notes": row["notes"],
        "Priority": row["priority"],
        "CRM Stage": row["crm_stage"],
        "Lead Source": row["lead_source"],
        "Owner": row["owner"],
        "Last Contacted At": row["last_contacted_at"],
        "Next Follow Up At": row["next_follow_up_at"],
        "Business Scope": role["business_id"] if role is not None else "",
        "Relationship": role["role"] if role is not None else "",
        "Segment Tags": "; ".join(tags),
        "Created At": row["created_at"],
        "Updated At": row["updated_at"],
    }


@router.post("/export")
def export_csv_contacts(payload: CsvExportRequest, _: str = Depends(verify_admin)) -> Response:
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
        contacts = conn.execute(sql, tuple(params)).fetchall()

        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\r\n")
        writer.writeheader()
        for row in contacts:
            role_params: List[Any] = [_party_id_for_contact(str(row["id"]))]
            role_sql = (
                "SELECT business_id, role, segment_tags FROM party_business_role "
                "WHERE party_id=? AND valid_to IS NULL"
            )
            if payload.business_scope != "all":
                role_sql += " AND business_id=?"
                role_params.append(payload.business_scope)
            role_sql += " ORDER BY business_id"
            roles = conn.execute(role_sql, tuple(role_params)).fetchall()
            if roles:
                for role in roles:
                    writer.writerow(_csv_row_for_contact(row, role))
            else:
                writer.writerow(_csv_row_for_contact(row, None))

    filename = "viv-dossiers.csv" if payload.business_scope == "all" else f"viv-{payload.business_scope}-dossiers.csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
