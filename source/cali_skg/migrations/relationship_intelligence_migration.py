from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_normalized(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _normalize_phone(value: str) -> str:
    raw = value.strip()
    plus = raw.startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return ("+" if plus else "") + digits


def apply_relationship_intelligence_schema(
    conn: sqlite3.Connection,
    steps: Optional[List[str]] = None,
) -> List[str]:
    """Create the CALI relationship/communications intelligence substrate.

    This migration is additive. It does not drop or rewrite the legacy contacts,
    email, activity, calendar, or pipeline tables. Legacy contacts are backfilled
    into canonical Party records with versioned identity claims so the existing
    application can continue operating while the new surfaces move over.
    """

    migration_steps = steps if steps is not None else []
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")
    cur.execute("PRAGMA journal_mode = WAL;")

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS evidence (
          evidence_id TEXT PRIMARY KEY,
          source_type TEXT NOT NULL,
          source_ref TEXT,
          business_scope TEXT,
          captured_at TEXT NOT NULL,
          content_hash TEXT,
          details TEXT
        );

        CREATE TABLE IF NOT EXISTS party (
          party_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL CHECK (kind IN ('person','organization')),
          display_name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','merged','suspended','deleted')),
          merged_into TEXT REFERENCES party(party_id),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS identity_claim (
          claim_id TEXT PRIMARY KEY,
          party_id TEXT NOT NULL REFERENCES party(party_id),
          claim_type TEXT NOT NULL,
          value_raw TEXT NOT NULL,
          value_normalized TEXT NOT NULL,
          value_hash TEXT NOT NULL,
          confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
          source_type TEXT NOT NULL,
          verification_state TEXT NOT NULL DEFAULT 'unverified' CHECK (verification_state IN ('unverified','verified','rejected','superseded')),
          primary_evidence TEXT REFERENCES evidence(evidence_id),
          valid_from TEXT,
          valid_to TEXT,
          observed_from TEXT NOT NULL,
          observed_to TEXT,
          business_scope TEXT,
          superseded_by TEXT REFERENCES identity_claim(claim_id),
          created_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_claim_party_type_value_active
          ON identity_claim(party_id, claim_type, value_hash)
          WHERE superseded_by IS NULL AND valid_to IS NULL;
        CREATE INDEX IF NOT EXISTS ix_claim_normalized ON identity_claim(claim_type, value_hash);
        CREATE INDEX IF NOT EXISTS ix_claim_party ON identity_claim(party_id);

        CREATE TABLE IF NOT EXISTS identity_claim_evidence (
          claim_id TEXT NOT NULL REFERENCES identity_claim(claim_id) ON DELETE CASCADE,
          evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
          PRIMARY KEY (claim_id, evidence_id)
        );

        CREATE TABLE IF NOT EXISTS business_context (
          business_id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          isolation TEXT NOT NULL DEFAULT 'scoped' CHECK (isolation IN ('scoped','strict')),
          status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS party_business_role (
          role_id TEXT PRIMARY KEY,
          party_id TEXT NOT NULL REFERENCES party(party_id),
          business_id TEXT NOT NULL REFERENCES business_context(business_id),
          role TEXT,
          segment_tags TEXT,
          visibility TEXT NOT NULL DEFAULT 'scoped' CHECK (visibility IN ('scoped','strict','cross')),
          valid_from TEXT,
          valid_to TEXT,
          created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_role_party_business
          ON party_business_role(party_id, business_id) WHERE valid_to IS NULL;
        CREATE INDEX IF NOT EXISTS ix_role_business ON party_business_role(business_id, party_id);

        CREATE TABLE IF NOT EXISTS relationship_edge (
          edge_id TEXT PRIMARY KEY,
          from_party TEXT NOT NULL REFERENCES party(party_id),
          to_party TEXT NOT NULL REFERENCES party(party_id),
          predicate TEXT NOT NULL,
          state TEXT NOT NULL CHECK (state IN ('asserted','verified','retired')),
          confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
          business_scope TEXT,
          valid_from TEXT,
          valid_to TEXT,
          primary_evidence TEXT REFERENCES evidence(evidence_id),
          created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_edge_pair_pred_active
          ON relationship_edge(from_party, to_party, predicate)
          WHERE state IN ('asserted','verified');
        CREATE INDEX IF NOT EXISTS ix_edge_from ON relationship_edge(from_party);
        CREATE INDEX IF NOT EXISTS ix_edge_to ON relationship_edge(to_party);

        CREATE TABLE IF NOT EXISTS relationship_edge_evidence (
          edge_id TEXT NOT NULL REFERENCES relationship_edge(edge_id) ON DELETE CASCADE,
          evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
          PRIMARY KEY (edge_id, evidence_id)
        );

        CREATE TABLE IF NOT EXISTS relationship_candidate (
          candidate_id TEXT PRIMARY KEY,
          from_party TEXT NOT NULL REFERENCES party(party_id),
          to_party TEXT NOT NULL REFERENCES party(party_id),
          predicate TEXT NOT NULL,
          confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
          rationale TEXT NOT NULL,
          inference_run TEXT NOT NULL,
          review_state TEXT NOT NULL DEFAULT 'pending' CHECK (review_state IN ('pending','accepted','rejected','expired')),
          business_scope TEXT,
          discovered_at TEXT NOT NULL,
          expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_candidate_from ON relationship_candidate(from_party, review_state);
        CREATE INDEX IF NOT EXISTS ix_candidate_to ON relationship_candidate(to_party, review_state);

        CREATE TABLE IF NOT EXISTS relationship_candidate_evidence (
          candidate_id TEXT NOT NULL REFERENCES relationship_candidate(candidate_id) ON DELETE CASCADE,
          evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
          PRIMARY KEY (candidate_id, evidence_id)
        );

        CREATE TABLE IF NOT EXISTS relationship_rejection (
          rejection_id TEXT PRIMARY KEY,
          from_party TEXT NOT NULL REFERENCES party(party_id),
          to_party TEXT NOT NULL REFERENCES party(party_id),
          predicate TEXT,
          reason TEXT,
          evidence_snapshot TEXT,
          rejected_at TEXT NOT NULL,
          business_scope TEXT
        );

        CREATE TABLE IF NOT EXISTS relevance_goal (
          goal_id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          description TEXT,
          business_scope TEXT,
          weight REAL NOT NULL DEFAULT 1.0,
          status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','complete','archived')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relevance_assessment (
          assessment_id TEXT PRIMARY KEY,
          party_id TEXT NOT NULL REFERENCES party(party_id),
          business_scope TEXT,
          goal_id TEXT REFERENCES relevance_goal(goal_id),
          relevance_score REAL NOT NULL CHECK (relevance_score BETWEEN 0 AND 100),
          connection_strength REAL CHECK (connection_strength BETWEEN 0 AND 1),
          degrees INTEGER CHECK (degrees BETWEEN 0 AND 6),
          factors TEXT NOT NULL,
          rationale TEXT NOT NULL,
          source_type TEXT NOT NULL,
          model_version TEXT,
          assessed_at TEXT NOT NULL,
          expires_at TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_relevance_party ON relevance_assessment(party_id, business_scope);
        CREATE INDEX IF NOT EXISTS ix_relevance_score ON relevance_assessment(business_scope, relevance_score DESC);

        CREATE TABLE IF NOT EXISTS merge_event (
          merge_id TEXT PRIMARY KEY,
          surviving_party_id TEXT NOT NULL REFERENCES party(party_id),
          merged_party_id TEXT NOT NULL REFERENCES party(party_id),
          matching_identifiers TEXT NOT NULL,
          contradictions TEXT,
          score_components TEXT,
          model_version TEXT,
          reviewer TEXT,
          decision TEXT NOT NULL,
          reassignment_snapshot TEXT NOT NULL,
          created_at TEXT NOT NULL,
          reversed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS communication_account (
          account_id TEXT PRIMARY KEY,
          channel TEXT NOT NULL,
          provider TEXT,
          identity TEXT NOT NULL,
          business_scope TEXT,
          config_ref TEXT,
          status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS conversation_thread (
          thread_id TEXT PRIMARY KEY,
          primary_party_id TEXT REFERENCES party(party_id),
          business_scope TEXT,
          channel TEXT NOT NULL,
          title TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversation_participant (
          thread_id TEXT NOT NULL REFERENCES conversation_thread(thread_id) ON DELETE CASCADE,
          party_id TEXT NOT NULL REFERENCES party(party_id),
          role TEXT NOT NULL,
          PRIMARY KEY (thread_id, party_id, role)
        );
        CREATE INDEX IF NOT EXISTS ix_participant_party ON conversation_participant(party_id);

        CREATE TABLE IF NOT EXISTS message_event (
          message_id TEXT PRIMARY KEY,
          thread_id TEXT NOT NULL REFERENCES conversation_thread(thread_id),
          account_id TEXT NOT NULL REFERENCES communication_account(account_id),
          external_id TEXT NOT NULL,
          mailbox_id TEXT,
          direction TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
          occurred_at TEXT NOT NULL,
          raw_locator TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          processed INTEGER NOT NULL DEFAULT 0,
          UNIQUE (account_id, mailbox_id, external_id)
        );

        CREATE TABLE IF NOT EXISTS sync_state (
          sync_state_id TEXT PRIMARY KEY,
          account_id TEXT NOT NULL REFERENCES communication_account(account_id),
          provider TEXT NOT NULL,
          mailbox_id TEXT NOT NULL,
          uidvalidity TEXT NOT NULL,
          highest_uid TEXT,
          modseq TEXT,
          cursor TEXT,
          last_synced_at TEXT NOT NULL,
          last_error TEXT,
          UNIQUE (account_id, mailbox_id)
        );

        CREATE TABLE IF NOT EXISTS import_tombstone (
          tombstone_id TEXT PRIMARY KEY,
          source_type TEXT NOT NULL,
          claim_type TEXT,
          value_hash TEXT,
          party_id TEXT REFERENCES party(party_id),
          business_scope TEXT,
          deleted_at TEXT NOT NULL,
          reason TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_tombstone_hash ON import_tombstone(value_hash);

        CREATE TABLE IF NOT EXISTS escalation_event (
          escalation_id TEXT PRIMARY KEY,
          party_id TEXT REFERENCES party(party_id),
          business_scope TEXT,
          channel TEXT NOT NULL,
          thread_id TEXT REFERENCES conversation_thread(thread_id),
          trigger_reason TEXT NOT NULL,
          priority TEXT NOT NULL CHECK (priority IN ('p0','p1','p2','p3')),
          dossier_context TEXT,
          orb_actions TEXT,
          orb_stop_reason TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'created' CHECK (state IN ('created','notified','acknowledged','owned','resolved','closed')),
          sla_due_at TEXT,
          owner TEXT,
          acked_at TEXT,
          resolved_at TEXT,
          continuation_ref TEXT,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_escalation_state ON escalation_event(state, priority, created_at);

        CREATE TABLE IF NOT EXISTS audit_event (
          audit_id TEXT PRIMARY KEY,
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          target_ids TEXT NOT NULL,
          prior_state TEXT,
          new_state TEXT,
          reason TEXT,
          correlation_id TEXT,
          prev_hash TEXT,
          row_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_audit_correlation ON audit_event(correlation_id);

        CREATE TABLE IF NOT EXISTS mail_domain (
          domain_id TEXT PRIMARY KEY,
          domain TEXT NOT NULL UNIQUE,
          business_scope TEXT,
          status TEXT NOT NULL DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS mail_account (
          account_id TEXT PRIMARY KEY,
          domain_id TEXT NOT NULL REFERENCES mail_domain(domain_id),
          local_part TEXT NOT NULL,
          display_name TEXT,
          config_ref TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active',
          UNIQUE (domain_id, local_part)
        );

        CREATE TABLE IF NOT EXISTS mailbox (
          mailbox_id TEXT PRIMARY KEY,
          account_id TEXT NOT NULL REFERENCES mail_account(account_id),
          name TEXT NOT NULL,
          mailbox_type TEXT NOT NULL DEFAULT 'standard' CHECK (mailbox_type IN ('standard','custom','archive')),
          uidvalidity TEXT,
          business_scope TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_mailbox_account ON mailbox(account_id);

        CREATE TABLE IF NOT EXISTS message_mailbox_state (
          message_id TEXT NOT NULL REFERENCES message_event(message_id) ON DELETE CASCADE,
          mailbox_id TEXT NOT NULL REFERENCES mailbox(mailbox_id) ON DELETE CASCADE,
          uid TEXT,
          flags TEXT,
          PRIMARY KEY (message_id, mailbox_id)
        );

        CREATE TABLE IF NOT EXISTS connector_contract (
          connector_id TEXT PRIMARY KEY,
          channel TEXT NOT NULL,
          provider TEXT NOT NULL,
          business_scope TEXT,
          config_ref TEXT,
          capability_set TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'stub' CHECK (status IN ('stub','configured','active','disabled','error')),
          last_checked_at TEXT
        );
        """
    )

    now = _utc_now()
    for business_id, label in (
        ("personal", "Personal"),
        ("spruked", "Spruked"),
        ("truemark_mint", "TrueMark Mint"),
        ("certsig", "CertSig"),
        ("alpha_certsig", "Alpha CertSig"),
    ):
        cur.execute(
            """
            INSERT OR IGNORE INTO business_context(business_id, label, isolation, status, created_at)
            VALUES (?, ?, 'scoped', 'active', ?)
            """,
            (business_id, label, now),
        )

    # Backfill the legacy contacts table into the canonical identity layer.
    table_names = {
        str(row[0])
        for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "contacts" in table_names:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM contacts").fetchall()
        for row in rows:
            legacy_id = str(row["id"] or "").strip()
            if not legacy_id:
                continue
            party_id = f"legacy-contact:{legacy_id}"
            name = str(row["name"] or row["email"] or legacy_id).strip()
            cur.execute(
                """
                INSERT OR IGNORE INTO party(party_id, kind, display_name, status, created_at, updated_at)
                VALUES (?, 'person', ?, 'active', ?, ?)
                """,
                (party_id, name, now, now),
            )

            claim_values: list[tuple[str, str, str]] = []
            email = str(row["email"] or "").strip() if "email" in row.keys() else ""
            phone = str(row["phone"] or "").strip() if "phone" in row.keys() else ""
            address = str(row["address"] or "").strip() if "address" in row.keys() else ""
            if email:
                claim_values.append(("email", email, _normalize_email(email)))
            if phone:
                claim_values.append(("phone", phone, _normalize_phone(phone)))
            if address:
                claim_values.append(("address", address, " ".join(address.lower().split())))

            for claim_type, raw, normalized in claim_values:
                if not normalized:
                    continue
                value_hash = _hash_normalized(normalized)
                claim_id = f"legacy:{legacy_id}:{claim_type}:{value_hash[:20]}"
                evidence_id = f"legacy:{legacy_id}:{claim_type}:evidence:{value_hash[:20]}"
                cur.execute(
                    """
                    INSERT OR IGNORE INTO evidence(
                      evidence_id, source_type, source_ref, captured_at, content_hash, details
                    ) VALUES (?, 'legacy_crm', ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        f"contacts:{legacy_id}",
                        now,
                        value_hash,
                        json.dumps({"legacy_contact_id": legacy_id, "claim_type": claim_type}),
                    ),
                )
                cur.execute(
                    """
                    INSERT OR IGNORE INTO identity_claim(
                      claim_id, party_id, claim_type, value_raw, value_normalized, value_hash,
                      confidence, source_type, verification_state, primary_evidence,
                      observed_from, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1.0, 'legacy_crm', 'unverified', ?, ?, ?)
                    """,
                    (
                        claim_id,
                        party_id,
                        claim_type,
                        raw,
                        normalized,
                        value_hash,
                        evidence_id,
                        now,
                        now,
                    ),
                )
                cur.execute(
                    "INSERT OR IGNORE INTO identity_claim_evidence(claim_id, evidence_id) VALUES (?, ?)",
                    (claim_id, evidence_id),
                )

    migration_steps.append("Ensured canonical Party/IdentityClaim/Evidence tables")
    migration_steps.append("Ensured business contexts and party-business roles")
    migration_steps.append("Ensured strict/candidate relationship graphs and rejection memory")
    migration_steps.append("Ensured six-degree relevance/betterment assessment tables")
    migration_steps.append("Ensured unified communications, escalation, sync, audit, and mail substrate tables")
    migration_steps.append("Backfilled legacy contacts into canonical Party records without deleting legacy rows")
    return migration_steps


def run_migration(db_path: str) -> dict[str, Any]:
    steps: List[str] = []
    with closing(sqlite3.connect(db_path)) as conn:
        apply_relationship_intelligence_schema(conn, steps)
        conn.commit()
    return {"status": "success", "db_path": db_path, "steps": steps}
