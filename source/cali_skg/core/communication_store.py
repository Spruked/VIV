from __future__ import annotations

import hashlib
import json
import sqlite3
from email.utils import parseaddr
from typing import Any, Dict, Iterable, Optional


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def normalize_email(value: str) -> str:
    _name, parsed = parseaddr(str(value or ""))
    candidate = parsed or str(value or "")
    return candidate.strip().lower()


def _email_hash(value: str) -> str:
    return hashlib.sha256(normalize_email(value).encode("utf-8")).hexdigest()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _resolve_party(conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
    normalized = normalize_email(email)
    if not normalized:
        return None
    return conn.execute(
        """
        SELECT p.party_id, p.display_name, c.verification_state, c.confidence
        FROM identity_claim c
        JOIN party p ON p.party_id=c.party_id
        WHERE c.claim_type='email'
          AND c.value_hash=?
          AND c.superseded_by IS NULL
          AND c.valid_to IS NULL
          AND c.verification_state!='rejected'
          AND p.status='active'
        ORDER BY CASE c.verification_state WHEN 'verified' THEN 0 ELSE 1 END,
                 c.confidence DESC,
                 c.created_at ASC
        LIMIT 1
        """,
        (_email_hash(normalized),),
    ).fetchone()


def resolve_party_by_email(db_path: str, email: str) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as conn:
        row = _resolve_party(conn, email)
        return dict(row) if row else None


def _ensure_message_evidence(
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    external_id: str,
    business_scope: str,
    occurred_at: str,
    content_hash: str,
    raw_locator: str,
    channel: str,
    provider: str,
    subject: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO evidence(
          evidence_id, source_type, source_ref, business_scope, captured_at,
          content_hash, details
        ) VALUES (?, 'communication_message', ?, ?, ?, ?, ?)
        """,
        (
            evidence_id,
            external_id,
            business_scope,
            occurred_at,
            content_hash,
            json.dumps(
                {
                    "channel": channel,
                    "provider": provider,
                    "raw_locator": raw_locator,
                    "subject": subject,
                },
                sort_keys=True,
            ),
        ),
    )


def _ensure_party_for_email(
    conn: sqlite3.Connection,
    *,
    email: str,
    display_name: Optional[str],
    evidence_id: str,
    business_scope: str,
    observed_at: str,
) -> str:
    normalized = normalize_email(email)
    existing = _resolve_party(conn, normalized)
    if existing:
        return str(existing["party_id"])

    value_hash = _email_hash(normalized)
    party_id = f"mail-party:{value_hash[:32]}"
    name = (display_name or "").strip() or normalized.split("@", 1)[0] or normalized
    conn.execute(
        """
        INSERT OR IGNORE INTO party(
          party_id, kind, display_name, status, created_at, updated_at
        ) VALUES (?, 'person', ?, 'active', ?, ?)
        """,
        (party_id, name, observed_at, observed_at),
    )

    claim_id = f"mail-email:{value_hash[:32]}"
    conn.execute(
        """
        INSERT OR IGNORE INTO identity_claim(
          claim_id, party_id, claim_type, value_raw, value_normalized, value_hash,
          confidence, source_type, verification_state, primary_evidence,
          observed_from, business_scope, created_at
        ) VALUES (?, ?, 'email', ?, ?, ?, 0.95, 'prime_mail_message', 'unverified', ?, ?, ?, ?)
        """,
        (
            claim_id,
            party_id,
            email,
            normalized,
            value_hash,
            evidence_id,
            observed_at,
            business_scope,
            observed_at,
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO identity_claim_evidence(claim_id, evidence_id) VALUES (?, ?)",
        (claim_id, evidence_id),
    )

    if business_scope and business_scope != "all":
        business_exists = conn.execute(
            "SELECT 1 FROM business_context WHERE business_id=? AND status='active'",
            (business_scope,),
        ).fetchone()
        if business_exists:
            role_id = _stable_id("role", party_id, business_scope)
            conn.execute(
                """
                INSERT INTO party_business_role(
                  role_id, party_id, business_id, role, segment_tags, visibility,
                  valid_from, created_at
                ) VALUES (?, ?, ?, 'correspondent', '[\"mail\"]', 'scoped', ?, ?)
                ON CONFLICT(role_id) DO UPDATE SET
                  valid_to=NULL,
                  role=COALESCE(party_business_role.role, excluded.role)
                """,
                (role_id, party_id, business_scope, observed_at, observed_at),
            )

    return party_id


def _unique_emails(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_email(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def ingest_message(db_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    channel = str(payload.get("channel") or "email").strip().lower()
    provider = str(payload.get("provider") or "prime_mail").strip().lower()
    account_identity = normalize_email(str(payload.get("account_identity") or ""))
    business_scope = str(payload.get("business_scope") or "all").strip().lower() or "all"
    external_id = str(payload.get("external_id") or "").strip()
    mailbox_id = str(payload.get("mailbox_id") or "").strip() or None
    direction = str(payload.get("direction") or "").strip().lower()
    occurred_at = str(payload.get("occurred_at") or "").strip()
    raw_locator = str(payload.get("raw_locator") or "").strip()
    content_hash = str(payload.get("content_hash") or "").strip().lower()
    thread_external_id = str(payload.get("thread_external_id") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    sender_email = normalize_email(str(payload.get("sender_email") or ""))
    sender_name = str(payload.get("sender_name") or "").strip() or None
    recipient_emails = _unique_emails(payload.get("recipient_emails") or [])

    if not account_identity:
        raise ValueError("account_identity is required")
    if not external_id:
        raise ValueError("external_id is required")
    if direction not in {"inbound", "outbound"}:
        raise ValueError("direction must be inbound or outbound")
    if not occurred_at:
        raise ValueError("occurred_at is required")
    if not raw_locator:
        raise ValueError("raw_locator is required")
    if not content_hash:
        raise ValueError("content_hash is required")

    account_id = _stable_id("comm-account", channel, provider, account_identity, business_scope)
    message_id = _stable_id("message", account_id, mailbox_id or "", external_id)
    evidence_id = _stable_id("evidence", message_id)
    thread_basis = thread_external_id or external_id
    thread_id = _stable_id("thread", channel, account_id, thread_basis)

    with _connect(db_path) as conn:
        _ensure_message_evidence(
            conn,
            evidence_id=evidence_id,
            external_id=external_id,
            business_scope=business_scope,
            occurred_at=occurred_at,
            content_hash=content_hash,
            raw_locator=raw_locator,
            channel=channel,
            provider=provider,
            subject=subject,
        )

        conn.execute(
            """
            INSERT INTO communication_account(
              account_id, channel, provider, identity, business_scope, config_ref, status
            ) VALUES (?, ?, ?, ?, ?, 'prime-mail-registry', 'active')
            ON CONFLICT(account_id) DO UPDATE SET
              business_scope=excluded.business_scope,
              status='active'
            """,
            (account_id, channel, provider, account_identity, business_scope),
        )

        participant_ids: list[tuple[str, str]] = []
        sender_party_id: Optional[str] = None
        if sender_email and sender_email != account_identity:
            sender_party_id = _ensure_party_for_email(
                conn,
                email=sender_email,
                display_name=sender_name,
                evidence_id=evidence_id,
                business_scope=business_scope,
                observed_at=occurred_at,
            )
            participant_ids.append((sender_party_id, "sender"))

        recipient_party_ids: list[str] = []
        for recipient in recipient_emails:
            if recipient == account_identity:
                continue
            party_id = _ensure_party_for_email(
                conn,
                email=recipient,
                display_name=None,
                evidence_id=evidence_id,
                business_scope=business_scope,
                observed_at=occurred_at,
            )
            recipient_party_ids.append(party_id)
            participant_ids.append((party_id, "recipient"))

        primary_party_id = sender_party_id if direction == "inbound" else (recipient_party_ids[0] if recipient_party_ids else None)

        conn.execute(
            """
            INSERT INTO conversation_thread(
              thread_id, primary_party_id, business_scope, channel, title, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
              primary_party_id=COALESCE(conversation_thread.primary_party_id, excluded.primary_party_id),
              business_scope=COALESCE(conversation_thread.business_scope, excluded.business_scope),
              title=CASE WHEN excluded.title!='' THEN excluded.title ELSE conversation_thread.title END
            """,
            (thread_id, primary_party_id, business_scope, channel, subject, occurred_at),
        )

        for party_id, role in participant_ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO conversation_participant(thread_id, party_id, role)
                VALUES (?, ?, ?)
                """,
                (thread_id, party_id, role),
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO message_event(
              message_id, thread_id, account_id, external_id, mailbox_id, direction,
              occurred_at, raw_locator, content_hash, processed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                message_id,
                thread_id,
                account_id,
                external_id,
                mailbox_id,
                direction,
                occurred_at,
                raw_locator,
                content_hash,
            ),
        )
        conn.commit()

        stored = conn.execute("SELECT * FROM message_event WHERE message_id=?", (message_id,)).fetchone()
        if not stored:
            stored = conn.execute(
                """
                SELECT * FROM message_event
                WHERE account_id=? AND COALESCE(mailbox_id,'')=COALESCE(?, '') AND external_id=?
                LIMIT 1
                """,
                (account_id, mailbox_id, external_id),
            ).fetchone()
        return {
            "message": dict(stored) if stored else None,
            "message_id": str(stored["message_id"]) if stored else message_id,
            "thread_id": thread_id,
            "account_id": account_id,
            "primary_party_id": primary_party_id,
            "participant_party_ids": sorted({party_id for party_id, _role in participant_ids}),
            "evidence_id": evidence_id,
        }


def party_timeline(
    db_path: str,
    party_id: str,
    *,
    business_scope: str = "all",
    channel: str = "all",
    limit: int = 100,
) -> list[Dict[str, Any]]:
    clauses = ["cp.party_id=?"]
    params: list[Any] = [party_id]
    if business_scope and business_scope != "all":
        clauses.append("COALESCE(t.business_scope,'') IN ('', ?)")
        params.append(business_scope)
    if channel and channel != "all":
        clauses.append("t.channel=?")
        params.append(channel)
    params.append(max(1, min(int(limit), 500)))
    sql = f"""
        SELECT DISTINCT
          m.message_id, m.external_id, m.mailbox_id, m.direction, m.occurred_at,
          m.raw_locator, m.content_hash, m.processed,
          t.thread_id, t.channel, t.title, t.business_scope,
          a.provider, a.identity AS account_identity
        FROM conversation_participant cp
        JOIN conversation_thread t ON t.thread_id=cp.thread_id
        JOIN message_event m ON m.thread_id=t.thread_id
        JOIN communication_account a ON a.account_id=m.account_id
        WHERE {' AND '.join(clauses)}
        ORDER BY m.occurred_at DESC
        LIMIT ?
    """
    with _connect(db_path) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]
