from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _legacy_contact_id(party_id: str) -> Optional[str]:
    prefix = "legacy-contact:"
    return party_id[len(prefix):] if str(party_id).startswith(prefix) else None


def party_dossier(db_path: str, party_id: str, *, business_scope: str = "all") -> Optional[Dict[str, Any]]:
    """Return the compact canonical dossier PRIME MAIL needs.

    The canonical Party/identity layer is authoritative. Legacy contact fields are
    only used as additive presentation data when the Party was backfilled from an
    existing CALI contact; they do not replace Party identity.
    """
    with _connect(db_path) as conn:
        party = conn.execute(
            "SELECT party_id, kind, display_name, status, created_at, updated_at FROM party WHERE party_id=?",
            (party_id,),
        ).fetchone()
        if not party:
            return None

        claims = conn.execute(
            """
            SELECT claim_type, value_raw, value_normalized, confidence,
                   verification_state, source_type, business_scope, created_at
            FROM identity_claim
            WHERE party_id=? AND superseded_by IS NULL AND valid_to IS NULL
              AND verification_state!='rejected'
            ORDER BY CASE verification_state WHEN 'verified' THEN 0 ELSE 1 END,
                     confidence DESC, created_at ASC
            """,
            (party_id,),
        ).fetchall()

        identities: Dict[str, list[Dict[str, Any]]] = {}
        for row in claims:
            item = dict(row)
            identities.setdefault(str(row["claim_type"]), []).append(item)

        role_params: list[Any] = [party_id]
        role_scope = ""
        if business_scope and business_scope != "all":
            role_scope = " AND r.business_id=?"
            role_params.append(business_scope)
        roles = conn.execute(
            f"""
            SELECT r.business_id, b.label AS business_label, r.role, r.segment_tags,
                   r.visibility, r.valid_from, r.created_at
            FROM party_business_role r
            LEFT JOIN business_context b ON b.business_id=r.business_id
            WHERE r.party_id=? AND r.valid_to IS NULL{role_scope}
            ORDER BY r.created_at DESC
            """,
            tuple(role_params),
        ).fetchall()

        legacy: Dict[str, Any] = {}
        legacy_id = _legacy_contact_id(party_id)
        if legacy_id:
            row = conn.execute("SELECT * FROM contacts WHERE id=?", (legacy_id,)).fetchone()
            if row:
                legacy = dict(row)

        latest_message = conn.execute(
            """
            SELECT m.occurred_at, m.direction, t.title, t.business_scope, t.channel
            FROM conversation_participant cp
            JOIN conversation_thread t ON t.thread_id=cp.thread_id
            JOIN message_event m ON m.thread_id=t.thread_id
            WHERE cp.party_id=?
            ORDER BY m.occurred_at DESC
            LIMIT 1
            """,
            (party_id,),
        ).fetchone()

        return {
            "party": dict(party),
            "identities": identities,
            "roles": [dict(row) for row in roles],
            "legacy_contact": legacy,
            "latest_message": dict(latest_message) if latest_message else None,
        }
