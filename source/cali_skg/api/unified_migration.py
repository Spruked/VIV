from __future__ import annotations

import sqlite3
from typing import Any, Dict, List

from cali_skg.migrations.relationship_intelligence_migration import apply_relationship_intelligence_schema


def _existing_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cur.fetchall()}


def run_unified_migration(db_path: str) -> Dict[str, Any]:
    steps: List[str] = []
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("PRAGMA journal_mode = WAL;")
        steps.append("Applied PRAGMA foreign_keys=ON and journal_mode=WAL")

        # Contacts expansion without rewriting existing shape.
        contact_cols = _existing_columns(cur, "contacts")
        add_contact_cols = [
            ("alias_names", "TEXT"),
            ("company_role", "TEXT"),
            ("organization_id", "TEXT"),
            ("risk_score", "INTEGER DEFAULT 0"),
            ("epistemic_status", "TEXT DEFAULT 'unverified'"),
            ("metadata_payload", "TEXT"),
        ]
        for col, col_type in add_contact_cols:
            if col not in contact_cols:
                cur.execute(f"ALTER TABLE contacts ADD COLUMN {col} {col_type}")
                steps.append(f"Added contacts.{col}")

        # Prime Mail + unified support tables.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_external_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                label TEXT NOT NULL,
                url TEXT NOT NULL,
                link_type TEXT NOT NULL,
                verified_status TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence_score REAL DEFAULT 0.0,
                last_checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                UNIQUE(contact_id, platform, url)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dossier_media (
                media_id TEXT PRIMARY KEY,
                contact_id TEXT NOT NULL,
                party_id TEXT,
                media_kind TEXT NOT NULL DEFAULT 'person',
                label TEXT,
                image_url TEXT NOT NULL,
                notes TEXT,
                is_primary INTEGER DEFAULT 0,
                source TEXT DEFAULT 'operator',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dossier_media_contact ON dossier_media(contact_id, is_primary DESC, created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_dossier_media_party ON dossier_media(party_id)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                message_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT,
                date TEXT,
                text_body TEXT,
                html_body TEXT,
                raw_email TEXT,
                folder TEXT DEFAULT 'INBOX',
                source TEXT,
                has_attachments INTEGER DEFAULT 0,
                attachment_paths TEXT,
                read INTEGER DEFAULT 0,
                starred INTEGER DEFAULT 0,
                archived INTEGER DEFAULT 0,
                received_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_emails (
                message_id TEXT PRIMARY KEY,
                from_addr TEXT NOT NULL,
                to_addr TEXT NOT NULL,
                subject TEXT,
                text_body TEXT,
                html_body TEXT,
                status TEXT DEFAULT 'pending',
                cloudflare_response TEXT,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT NOT NULL,
                to_addr TEXT,
                subject TEXT,
                text_body TEXT,
                html_body TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        steps.append("Ensured emails/sent_emails/drafts tables")

        # Add optional linkage columns when missing.
        fa_cols = _existing_columns(cur, "financial_accounts")
        if "contact_id" not in fa_cols:
            cur.execute("ALTER TABLE financial_accounts ADD COLUMN contact_id TEXT")
            steps.append("Added financial_accounts.contact_id")
        if "account_name" not in fa_cols:
            cur.execute("ALTER TABLE financial_accounts ADD COLUMN account_name TEXT")
            steps.append("Added financial_accounts.account_name")
        if "status" not in fa_cols:
            cur.execute("ALTER TABLE financial_accounts ADD COLUMN status TEXT")
            steps.append("Added financial_accounts.status")

        # FTS and triggers
        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
                message_id UNINDEXED,
                sender,
                recipient,
                subject,
                text_body,
                html_body,
                raw_email,
                tokenize='porter'
            )
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS after_email_insert AFTER INSERT ON emails BEGIN
                INSERT INTO emails_fts(message_id, sender, recipient, subject, text_body, html_body, raw_email)
                VALUES (new.message_id, new.sender, new.recipient, new.subject, new.text_body, new.html_body, new.raw_email);
            END;
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS after_email_delete AFTER DELETE ON emails BEGIN
                DELETE FROM emails_fts WHERE message_id = old.message_id;
            END;
            """
        )
        steps.append("Ensured emails_fts and email triggers")

        # Indices
        tables = {str(r[0]) for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "contacts" in tables:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)")
        if "contact_external_links" in tables:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_external_links_contact ON contact_external_links(contact_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_external_links_platform ON contact_external_links(platform)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS contact_external_link_governance (
                  node_key TEXT PRIMARY KEY,
                  contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                  platform TEXT NOT NULL,
                  url TEXT NOT NULL,
                  risk_level TEXT NOT NULL,
                  record_type TEXT NOT NULL,
                  query_mode TEXT NOT NULL,
                  confidence_score REAL NOT NULL,
                  requires_review INTEGER NOT NULL DEFAULT 0,
                  classifier_version TEXT NOT NULL,
                  generated_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(contact_id, platform, url)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_external_link_governance_contact ON contact_external_link_governance(contact_id, risk_level)")
        if "emails" in tables:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender)")
        if "crm_activities" in tables:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_activities_contact ON crm_activities(contact_id)")
        if "verification_calls" in tables:
            cols = _existing_columns(cur, "verification_calls")
            if "contact_id" in cols:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_verification_calls_contact ON verification_calls(contact_id)")
            elif "caller_number" in cols:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_verification_calls_contact ON verification_calls(caller_number)")
        steps.append("Ensured unified indices")

        # Additive relationship/communications intelligence substrate. This keeps
        # the legacy tables intact while backfilling them into canonical Party
        # records so the UI can migrate without a destructive cutover.
        apply_relationship_intelligence_schema(conn, steps)

        # Durable local-first automation runs. Evidence stays in the existing
        # evidence/audit substrate; these tables only retain resumable job state.
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS dossier_sweep_run (
              run_id TEXT PRIMARY KEY,
              business_scope TEXT NOT NULL,
              max_entities INTEGER NOT NULL,
              status TEXT NOT NULL,
              started_at TEXT NOT NULL,
              completed_at TEXT,
              contacts_seen INTEGER NOT NULL DEFAULT 0,
              contacts_processed INTEGER NOT NULL DEFAULT 0,
              evidence_written INTEGER NOT NULL DEFAULT 0,
              error_summary TEXT
            );
            CREATE TABLE IF NOT EXISTS dossier_sweep_item (
              run_id TEXT NOT NULL REFERENCES dossier_sweep_run(run_id) ON DELETE CASCADE,
              contact_id TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
              content_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              detail TEXT,
              processed_at TEXT NOT NULL,
              PRIMARY KEY (run_id, contact_id)
            );
            CREATE INDEX IF NOT EXISTS ix_dossier_sweep_run_status ON dossier_sweep_run(status, started_at DESC);
            CREATE INDEX IF NOT EXISTS ix_dossier_sweep_item_hash ON dossier_sweep_item(contact_id, content_hash);
            """
        )
        steps.append("Ensured dossier sweep automation tables")

        conn.commit()

    return {"status": "success", "db_path": db_path, "steps": steps}
