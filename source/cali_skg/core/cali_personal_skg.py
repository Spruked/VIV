"""
CALI Personal SKG - KayGee cognition personal assistant core.
"""

from __future__ import annotations

import hashlib
import imaplib
import json
import os
import sqlite3
import smtplib
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CaliMemory:
    timestamp: str
    category: str
    content: Dict[str, Any]
    hash_id: str
    confidence: float
    source: str


def _default_cali_base_path() -> str:
    configured = str(os.getenv("CALI_DATA_ROOT") or os.getenv("CALI_BASE_PATH") or "").strip()
    if configured:
        if os.name == "nt" and configured.lower().startswith("/mnt/"):
            # Normalize WSL-style mounts when CRM is running under Windows Python.
            parts = configured.split("/")
            if len(parts) >= 4 and parts[2]:
                drive = parts[2].upper()
                remainder = "/".join(parts[3:])
                return f"{drive}:/{remainder}".rstrip("/")
        return configured
    if Path("/mnt/r/Substrate_Vault_R/vaults/r_drive_system_records/crm").exists():
        return "/mnt/r/Substrate_Vault_R/vaults/r_drive_system_records/crm"
    if Path("R:/Substrate_Vault_R/vaults/r_drive_system_records/crm").exists():
        return "R:/Substrate_Vault_R/vaults/r_drive_system_records/crm"
    if Path("/mnt/r").exists():
        return "/mnt/r/crm"
    return "R:/crm"


class CaliPersonalSKG:
    def __init__(self, base_path: Optional[str] = None):
        base_path = base_path or _default_cali_base_path()
        self.base_path = Path(base_path)
        self.vault_path = self.base_path / "vault"
        self.memory_path = self.base_path / "memory"
        self.temp_path = self.base_path / "temp"

        for path in [self.vault_path, self.memory_path, self.temp_path]:
            path.mkdir(parents=True, exist_ok=True)

        self.db_path = self.memory_path / "cali_personal.db"
        self._init_database()
        self.identity = self._load_identity()
        self.kaygee_config = {
            "endpoint": "http://127.0.0.1:8011",
            "timeout": 30,
            "confidence_threshold": 0.75,
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS contacts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT,
                    phone TEXT,
                    email TEXT,
                    address TEXT,
                    notes TEXT,
                    priority INTEGER DEFAULT 0,
                    crm_stage TEXT DEFAULT 'prospect',
                    lead_source TEXT,
                    owner TEXT,
                    last_contacted_at TEXT,
                    next_follow_up_at TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    hash_id TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_accounts (
                    id TEXT PRIMARY KEY,
                    institution TEXT,
                    account_type TEXT,
                    account_number_hash TEXT,
                    balance REAL,
                    currency TEXT DEFAULT 'USD',
                    notes TEXT,
                    alert_threshold REAL,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    event_type TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    location TEXT,
                    attendees TEXT,
                    notes TEXT,
                    attendee_notes TEXT,
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    cali_notified INTEGER DEFAULT 0,
                    created_at TEXT
                )
                """
            )
            cur.execute("PRAGMA table_info(events)")
            event_columns = {row[1] for row in cur.fetchall()}
            if "notes" not in event_columns:
                cur.execute("ALTER TABLE events ADD COLUMN notes TEXT")
            if "attendee_notes" not in event_columns:
                cur.execute("ALTER TABLE events ADD COLUMN attendee_notes TEXT")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_calls (
                    id TEXT PRIMARY KEY,
                    caller_number TEXT,
                    caller_name TEXT,
                    claimed_identity TEXT,
                    verification_status TEXT,
                    verification_method TEXT,
                    notes TEXT,
                    timestamp TEXT,
                    cali_assisted INTEGER DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    due_date TEXT,
                    priority INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'active',
                    category TEXT,
                    cali_suggested INTEGER DEFAULT 0,
                    completed_at TEXT,
                    created_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS unanswered (
                    id TEXT PRIMARY KEY,
                    question TEXT,
                    context TEXT,
                    timestamp TEXT,
                    priority INTEGER DEFAULT 1
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS crm_activities (
                    id TEXT PRIMARY KEY,
                    contact_id TEXT NOT NULL,
                    activity_type TEXT,
                    summary TEXT,
                    metadata TEXT,
                    created_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS email_connectors (
                    id TEXT PRIMARY KEY,
                    provider TEXT,
                    email TEXT,
                    imap_host TEXT,
                    imap_port INTEGER,
                    smtp_host TEXT,
                    smtp_port INTEGER,
                    calendar_provider TEXT,
                    status TEXT,
                    notes TEXT,
                    last_sync_at TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS mail_inbound_index (
                    message_id TEXT PRIMARY KEY,
                    contact_id TEXT,
                    from_email TEXT,
                    subject TEXT,
                    received_at TEXT,
                    ingested_at TEXT
                )
                """
            )
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
                    last_checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                    UNIQUE(contact_id, platform, url)
                )
                """
            )

            # Backward-compatible migrations for existing local databases.
            cur.execute("PRAGMA table_info(contacts)")
            existing = {str(row[1]) for row in cur.fetchall()}
            if "crm_stage" not in existing:
                cur.execute("ALTER TABLE contacts ADD COLUMN crm_stage TEXT DEFAULT 'prospect'")
            if "lead_source" not in existing:
                cur.execute("ALTER TABLE contacts ADD COLUMN lead_source TEXT")
            if "owner" not in existing:
                cur.execute("ALTER TABLE contacts ADD COLUMN owner TEXT")
            if "last_contacted_at" not in existing:
                cur.execute("ALTER TABLE contacts ADD COLUMN last_contacted_at TEXT")
            if "next_follow_up_at" not in existing:
                cur.execute("ALTER TABLE contacts ADD COLUMN next_follow_up_at TEXT")
            conn.commit()

    def _load_identity(self) -> Dict[str, Any]:
        identity_file = self.vault_path / "cali_identity.json"
        if identity_file.exists():
            return json.loads(identity_file.read_text(encoding="utf-8"))

        identity = {
            "name": "Cali",
            "full_name": "Cognitively Aligned Linear Intelligence",
            "version": "1.0.0-Personal",
            "cognition_provider": "KayGee-1.0",
            "purpose": "Personal administrative assistant for Bryan Spruk",
            "domain": "spruked.com admin",
            "created": datetime.utcnow().isoformat(),
            "principles": [
                "Restricted learning - no self-modification",
                "Immutable memory - append-only records",
                "KayGee cognition routing",
                "Admin-only data isolation",
            ],
            "capabilities": [
                "contact_management",
                "financial_tracking",
                "calendar_management",
                "phone_verification",
                "task_assistance",
                "site_navigation",
                "life_planning",
            ],
        }
        identity_file.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        return identity

    def _generate_hash(self, content: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def _next_id(self, prefix: str, content: Dict[str, Any]) -> str:
        return f"{prefix}_{self._generate_hash({**content, 'ts': datetime.utcnow().isoformat()})}"

    def _log_memory(self, category: str, content: Dict[str, Any], confidence: float = 0.9, source: str = "system") -> None:
        entry = CaliMemory(
            timestamp=datetime.utcnow().isoformat(),
            category=category,
            content=content,
            hash_id=self._generate_hash(content),
            confidence=confidence,
            source=source,
        )
        out_file = self.memory_path / f"memory_{datetime.utcnow().strftime('%Y-%m-%d')}.jsonl"
        with out_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry)) + "\n")

    def _rows(self, cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        return [dict(row) for row in cursor.fetchall()]

    def prune_knowledge_graph(self, retention_days: int = 90) -> None:
        cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM tasks WHERE status='completed' AND completed_at < ?", (cutoff,))
            cur.execute("DELETE FROM unanswered WHERE timestamp < ?", (cutoff,))
            cur.execute("DELETE FROM verification_calls WHERE timestamp < ?", (cutoff,))
            conn.commit()

    # Contacts
    def add_contact(
        self,
        name: str,
        contact_type: str = "personal",
        phone: Optional[str] = None,
        email: Optional[str] = None,
        address: Optional[str] = None,
        notes: Optional[str] = None,
        priority: int = 0,
        crm_stage: Optional[str] = None,
        lead_source: Optional[str] = None,
        owner: Optional[str] = None,
        next_follow_up_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        contact_id = self._next_id("contact", {"name": name, "type": contact_type})
        now = datetime.utcnow().isoformat()
        hash_id = self._generate_hash({"name": name, "type": contact_type, "phone": phone, "email": email})
        normalized_type = str(contact_type or "personal").strip().lower()
        lead_types = {"promoter", "investor", "marketing", "business"}
        resolved_stage = str(crm_stage or ("prospect" if normalized_type in lead_types else "active")).strip().lower()

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO contacts (
                    id, name, type, phone, email, address, notes, priority,
                    crm_stage, lead_source, owner, next_follow_up_at,
                    created_at, updated_at, hash_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact_id,
                    name,
                    contact_type,
                    phone,
                    email,
                    address,
                    notes,
                    priority,
                    resolved_stage,
                    lead_source,
                    owner,
                    next_follow_up_at,
                    now,
                    now,
                    hash_id,
                ),
            )
            conn.commit()

        self._log_memory("contact", {"action": "add", "contact_id": contact_id, "name": name, "type": contact_type})
        self.log_crm_activity(contact_id, "contact_created", f"Contact created as {resolved_stage} stage.")
        return {"success": True, "contact_id": contact_id, "message": f"Added {name} to your {contact_type} contacts."}

    def _append_notes(self, original: Optional[str], extra: Optional[str]) -> Optional[str]:
        a = str(original or "").strip()
        b = str(extra or "").strip()
        if not a:
            return b or None
        if not b:
            return a
        return f"{a}\n{b}"

    def update_contact_stage(
        self,
        contact_id: str,
        stage: str,
        next_follow_up_at: Optional[str] = None,
        owner: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_stage = str(stage or "prospect").strip().lower()
        now = datetime.utcnow().isoformat()

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
            row = cur.fetchone()
            if not row:
                return {"success": False, "message": "Contact not found."}

            current = dict(row)
            merged_notes = self._append_notes(current.get("notes"), notes)
            cur.execute(
                """
                UPDATE contacts
                SET crm_stage = ?,
                    next_follow_up_at = COALESCE(?, next_follow_up_at),
                    owner = COALESCE(?, owner),
                    last_contacted_at = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (normalized_stage, next_follow_up_at, owner, now, merged_notes, now, contact_id),
            )
            conn.commit()

        self.log_crm_activity(contact_id, "stage_change", f"Stage updated to {normalized_stage}.")
        return {"success": True, "contact_id": contact_id, "stage": normalized_stage}

    def log_crm_activity(
        self,
        contact_id: str,
        activity_type: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        activity_id = self._next_id("crm", {"contact_id": contact_id, "activity_type": activity_type, "summary": summary})
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO crm_activities (id, contact_id, activity_type, summary, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (activity_id, contact_id, activity_type, summary, json.dumps(metadata or {}), now),
            )
            conn.commit()
        return {"success": True, "activity_id": activity_id}

    def get_contact_activities(self, contact_id: str, limit: int = 40) -> List[Dict[str, Any]]:
        safe_limit = min(200, max(1, int(limit or 40)))
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM crm_activities
                WHERE contact_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (contact_id, safe_limit),
            )
            items = self._rows(cur)

        for item in items:
            raw = item.get("metadata")
            if raw:
                try:
                    item["metadata"] = json.loads(raw)
                except json.JSONDecodeError:
                    item["metadata"] = {"raw": str(raw)}
            else:
                item["metadata"] = {}
        return items

    def get_crm_pipeline(self) -> Dict[str, Any]:
        stages = [
            "prospect",
            "qualified",
            "contacted",
            "meeting_scheduled",
            "proposal",
            "won",
            "lost",
        ]
        lead_types = ("promoter", "investor", "marketing", "business")

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM contacts
                WHERE type IN (?, ?, ?, ?)
                ORDER BY priority DESC, COALESCE(next_follow_up_at, '9999-12-31T00:00:00') ASC, updated_at DESC
                """,
                lead_types,
            )
            leads = self._rows(cur)

        counts = {stage: 0 for stage in stages}
        for lead in leads:
            stage = str(lead.get("crm_stage") or "prospect").strip().lower()
            if stage not in counts:
                counts[stage] = 0
            counts[stage] += 1

        return {
            "stages": counts,
            "total": len(leads),
            "leads": leads,
        }

    def schedule_contact_appointment(
        self,
        contact_id: str,
        title: str,
        start_time: str,
        end_time: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
            row = cur.fetchone()
            if not row:
                return {"success": False, "message": "Contact not found."}
            contact = dict(row)

        attendees = [contact["email"]] if contact.get("email") else []
        event = self.add_event(
            title=title,
            event_type="appointment",
            start_time=start_time,
            end_time=end_time,
            location=location,
            attendees=attendees,
            priority=4,
        )

        self.update_contact_stage(
            contact_id=contact_id,
            stage="meeting_scheduled",
            next_follow_up_at=end_time or start_time,
            notes=notes,
        )
        self.log_crm_activity(
            contact_id,
            "appointment_scheduled",
            f"Appointment scheduled: {title}",
            metadata={
                "event_id": event.get("event_id"),
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
            },
        )

        self.add_task(
            title=f"Follow up after appointment: {contact.get('name', 'Contact')}",
            due_date=end_time or start_time,
            priority=4,
            category="crm",
            cali_suggested=True,
        )

        return {"success": True, "event": event, "contact_id": contact_id}

    def configure_email_connector(
        self,
        provider: str,
        email: str,
        imap_host: Optional[str],
        imap_port: int,
        smtp_host: Optional[str],
        smtp_port: int,
        calendar_provider: str = "local",
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        connector_id = "primary"
        status = "configured"
        password = str((
            os.environ.get("BUSINESS_EMAIL_APP_PASSWORD")
            or os.environ.get("EMAIL_APP_PASSWORD")
            or ""
        )).strip()

        if imap_host and password:
            try:
                imap = imaplib.IMAP4_SSL(imap_host, int(imap_port))
                imap.login(email, password)
                imap.logout()
                status = "imap_connected"
            except Exception:
                status = "imap_unverified"

        if smtp_host and password:
            try:
                smtp = smtplib.SMTP(smtp_host, int(smtp_port), timeout=8)
                smtp.starttls()
                smtp.login(email, password)
                smtp.quit()
                status = "connected"
            except Exception:
                if status == "connected":
                    status = "smtp_unverified"

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO email_connectors (
                    id, provider, email, imap_host, imap_port, smtp_host, smtp_port,
                    calendar_provider, status, notes, last_sync_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider=excluded.provider,
                    email=excluded.email,
                    imap_host=excluded.imap_host,
                    imap_port=excluded.imap_port,
                    smtp_host=excluded.smtp_host,
                    smtp_port=excluded.smtp_port,
                    calendar_provider=excluded.calendar_provider,
                    status=excluded.status,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    connector_id,
                    provider,
                    email,
                    imap_host,
                    int(imap_port),
                    smtp_host,
                    int(smtp_port),
                    calendar_provider,
                    status,
                    notes,
                    now,
                    now,
                    now,
                ),
            )
            conn.commit()

        return {
            "success": True,
            "status": status,
            "email": email,
            "password_env_detected": bool(password),
            "message": "Connector saved. Set BUSINESS_EMAIL_APP_PASSWORD to enable authenticated mail access.",
        }

    def get_email_connector_status(self) -> Dict[str, Any]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM email_connectors WHERE id = 'primary' LIMIT 1")
            row = cur.fetchone()

        password = str((
            os.environ.get("BUSINESS_EMAIL_APP_PASSWORD")
            or os.environ.get("EMAIL_APP_PASSWORD")
            or ""
        )).strip()
        if not row:
            return {
                "configured": False,
                "status": "not_configured",
                "password_env_detected": bool(password),
            }

        data = dict(row)
        return {
            "configured": True,
            "status": data.get("status") or "configured",
            "connector": data,
            "password_env_detected": bool(password),
        }

    def _get_primary_email_connector(self) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM email_connectors WHERE id = 'primary' LIMIT 1")
            row = cur.fetchone()
        return dict(row) if row else None

    def _find_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return None
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM contacts WHERE lower(email) = ? LIMIT 1", (normalized_email,))
            row = cur.fetchone()
        return dict(row) if row else None

    def _create_contact_from_inbound_email(self, sender_name: str, sender_email: str) -> Dict[str, Any]:
        local = sender_email.split("@")[0] if "@" in sender_email else sender_email
        display_name = str(sender_name or "").strip() or f"Email Lead: {local}"
        created = self.add_contact(
            name=display_name,
            contact_type="marketing",
            email=sender_email,
            notes="Auto-created from inbound mailbox poll.",
            priority=1,
            crm_stage="prospect",
            lead_source="email_inbound",
            owner="bryan@spruked.com",
        )
        contact_id = str(created.get("contact_id") or "").strip()
        if not contact_id:
            existing = self._find_contact_by_email(sender_email)
            return existing or {}
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM contacts WHERE id = ? LIMIT 1", (contact_id,))
            row = cur.fetchone()
        return dict(row) if row else {}

    def _mail_already_ingested(self, message_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM mail_inbound_index WHERE message_id = ? LIMIT 1", (message_id,))
            return cur.fetchone() is not None

    def _mark_mail_ingested(
        self,
        message_id: str,
        contact_id: Optional[str],
        from_email: str,
        subject: str,
        received_at: str,
    ) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO mail_inbound_index
                (message_id, contact_id, from_email, subject, received_at, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, contact_id, from_email, subject, received_at, datetime.utcnow().isoformat()),
            )
            conn.commit()

    def poll_inbound_mailbox(
        self,
        mailbox: str = "INBOX",
        limit: int = 25,
        since_hours: int = 72,
        unseen_only: bool = True,
    ) -> Dict[str, Any]:
        connector = self._get_primary_email_connector()
        if not connector:
            return {"success": False, "status": "not_configured", "message": "Email connector is not configured."}

        imap_host = str(connector.get("imap_host") or "").strip()
        imap_port = int(connector.get("imap_port") or 993)
        email_address = str(connector.get("email") or "").strip()
        password = str((os.environ.get("BUSINESS_EMAIL_APP_PASSWORD") or os.environ.get("EMAIL_APP_PASSWORD") or "")).strip()

        if not imap_host or not email_address:
            return {"success": False, "status": "connector_incomplete", "message": "Connector missing IMAP host or email."}
        if not password:
            return {
                "success": False,
                "status": "password_missing",
                "message": "Set BUSINESS_EMAIL_APP_PASSWORD (or EMAIL_APP_PASSWORD) to enable mailbox polling.",
            }

        safe_limit = min(200, max(1, int(limit or 25)))
        safe_hours = min(24 * 365, max(1, int(since_hours or 72)))
        since_date = (datetime.utcnow() - timedelta(hours=safe_hours)).strftime("%d-%b-%Y")

        processed = 0
        created_activities = 0
        created_contacts = 0
        duplicates = 0
        errors: List[str] = []

        try:
            imap = imaplib.IMAP4_SSL(imap_host, imap_port)
            imap.login(email_address, password)
            select_status, _ = imap.select(mailbox, readonly=True)
            if select_status != "OK":
                imap.logout()
                return {"success": False, "status": "mailbox_error", "message": f"Unable to open mailbox: {mailbox}"}

            if unseen_only:
                search_status, data = imap.search(None, "UNSEEN", "SINCE", since_date)
            else:
                search_status, data = imap.search(None, "SINCE", since_date)

            if search_status != "OK":
                imap.logout()
                return {"success": False, "status": "search_error", "message": "Failed to search mailbox."}

            message_ids = (data[0] or b"").split()
            target_ids = message_ids[-safe_limit:]

            for message_ref in target_ids:
                fetch_status, fetched = imap.fetch(message_ref, "(RFC822)")
                if fetch_status != "OK":
                    errors.append(f"fetch_failed:{message_ref.decode('utf-8', errors='ignore')}")
                    continue

                raw_bytes = b""
                for item in fetched:
                    if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], (bytes, bytearray)):
                        raw_bytes = bytes(item[1])
                        break
                if not raw_bytes:
                    continue

                message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
                from_header = str(message.get("from") or "").strip()
                sender_name, sender_email = parseaddr(from_header)
                sender_email = str(sender_email or "").strip().lower()
                if not sender_email:
                    continue

                subject = str(message.get("subject") or "(no subject)").strip()[:320]
                raw_msg_id = str(message.get("message-id") or "").strip().strip("<>")
                date_header = str(message.get("date") or "").strip()
                try:
                    received_at = parsedate_to_datetime(date_header).astimezone().isoformat() if date_header else datetime.utcnow().isoformat()
                except Exception:
                    received_at = datetime.utcnow().isoformat()

                message_id = raw_msg_id or self._generate_hash(
                    {
                        "from": sender_email,
                        "subject": subject,
                        "date": date_header,
                    }
                )

                if self._mail_already_ingested(message_id):
                    duplicates += 1
                    continue

                contact = self._find_contact_by_email(sender_email)
                if not contact:
                    contact = self._create_contact_from_inbound_email(sender_name, sender_email)
                    if contact:
                        created_contacts += 1
                if not contact:
                    errors.append(f"contact_failed:{sender_email}")
                    continue

                self.log_crm_activity(
                    str(contact.get("id")),
                    "email_inbound",
                    f"Inbound email: {subject}",
                    metadata={
                        "message_id": message_id,
                        "from_email": sender_email,
                        "from_name": sender_name,
                        "received_at": received_at,
                        "mailbox": mailbox,
                        "subject": subject,
                    },
                )
                self._mark_mail_ingested(message_id, str(contact.get("id")), sender_email, subject, received_at)
                created_activities += 1
                processed += 1

            imap.logout()

            with self._connect() as conn:
                cur = conn.cursor()
                now = datetime.utcnow().isoformat()
                cur.execute(
                    "UPDATE email_connectors SET status = ?, last_sync_at = ?, updated_at = ? WHERE id = 'primary'",
                    ("imap_connected", now, now),
                )
                conn.commit()

            return {
                "success": True,
                "status": "polled",
                "mailbox": mailbox,
                "searched_since": since_date,
                "considered_messages": len(target_ids),
                "processed": processed,
                "created_activities": created_activities,
                "created_contacts": created_contacts,
                "duplicates": duplicates,
                "errors": errors,
            }
        except Exception as exc:
            with self._connect() as conn:
                cur = conn.cursor()
                now = datetime.utcnow().isoformat()
                cur.execute(
                    "UPDATE email_connectors SET status = ?, updated_at = ? WHERE id = 'primary'",
                    ("imap_poll_error", now),
                )
                conn.commit()
            return {
                "success": False,
                "status": "imap_poll_error",
                "message": str(exc),
                "processed": processed,
                "created_activities": created_activities,
                "created_contacts": created_contacts,
                "duplicates": duplicates,
                "errors": errors,
            }

    def search_contacts(self, query: Optional[str] = None, contact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            if query:
                q = f"%{query}%"
                cur.execute(
                    """
                    SELECT * FROM contacts
                    WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? OR notes LIKE ?
                    ORDER BY priority DESC, name ASC
                    """,
                    (q, q, q, q),
                )
            elif contact_type:
                cur.execute("SELECT * FROM contacts WHERE type = ? ORDER BY priority DESC, name ASC", (contact_type,))
            else:
                cur.execute("SELECT * FROM contacts ORDER BY priority DESC, name ASC")
            return self._rows(cur)

    def get_financial_contacts(self) -> List[Dict[str, Any]]:
        return self.search_contacts(contact_type="financial")

    # Financial
    def add_financial_account(
        self,
        institution: str,
        account_type: str,
        account_number: str,
        balance: float = 0.0,
        alert_threshold: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        account_id = self._next_id("fin", {"institution": institution, "account_type": account_type})
        account_hash = hashlib.sha256(account_number.encode("utf-8")).hexdigest()[:32]
        now = datetime.utcnow().isoformat()

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO financial_accounts
                (id, institution, account_type, account_number_hash, balance, alert_threshold, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, institution, account_type, account_hash, balance, alert_threshold, notes, now, now),
            )
            conn.commit()

        self._log_memory("financial", {"action": "add_account", "account_id": account_id, "institution": institution})
        return {"success": True, "account_id": account_id, "message": f"Added {account_type} account at {institution}."}

    def get_financial_summary(self) -> Dict[str, Any]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT institution, account_type, balance, alert_threshold, currency FROM financial_accounts ORDER BY balance DESC")
            rows = cur.fetchall()

        accounts: List[Dict[str, Any]] = []
        alerts: List[str] = []
        total_balance = 0.0
        currency = "USD"

        for row in rows:
            institution, account_type, balance, threshold, row_currency = row
            balance = float(balance or 0)
            total_balance += balance
            currency = row_currency or currency
            accounts.append({"institution": institution, "type": account_type, "balance": balance})
            if threshold is not None and balance < float(threshold):
                alerts.append(f"{institution} {account_type} below threshold (${balance:.2f} < ${float(threshold):.2f})")

        return {
            "total_balance": total_balance,
            "account_count": len(accounts),
            "accounts": accounts,
            "alerts": alerts,
            "currency": currency,
        }

    # Calendar
    def add_event(
        self,
        title: str,
        event_type: str = "meeting",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        notes: Optional[str] = None,
        attendee_notes: Optional[Dict[str, str]] = None,
        priority: int = 0,
    ) -> Dict[str, Any]:
        event_id = self._next_id("evt", {"title": title, "event_type": event_type})
        now = datetime.utcnow().isoformat()

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO events (
                    id, title, event_type, start_time, end_time, location,
                    attendees, notes, attendee_notes, priority, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    title,
                    event_type,
                    start_time,
                    end_time,
                    location,
                    json.dumps(attendees or []),
                    notes,
                    json.dumps(attendee_notes or {}),
                    priority,
                    now,
                ),
            )
            conn.commit()

        self._log_memory("calendar", {"action": "add_event", "event_id": event_id, "title": title})
        return {"success": True, "event_id": event_id, "message": f"Added '{title}' to your calendar."}

    def get_upcoming_events(self, days: int = 7) -> List[Dict[str, Any]]:
        now = datetime.utcnow().isoformat()
        future = (datetime.utcnow() + timedelta(days=days)).isoformat()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM events
                WHERE status != 'cancelled'
                  AND start_time IS NOT NULL
                  AND start_time BETWEEN ? AND ?
                ORDER BY start_time ASC
                """,
                (now, future),
            )
            events = self._rows(cur)

        for event in events:
            raw_attendees = event.get("attendees")
            if raw_attendees:
                try:
                    event["attendees"] = json.loads(raw_attendees)
                except json.JSONDecodeError:
                    event["attendees"] = []
            else:
                event["attendees"] = []
            raw_attendee_notes = event.get("attendee_notes")
            if raw_attendee_notes:
                try:
                    event["attendee_notes"] = json.loads(raw_attendee_notes)
                except json.JSONDecodeError:
                    event["attendee_notes"] = {}
            else:
                event["attendee_notes"] = {}

        return events

    def _generate_briefing_text(
        self,
        events: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]],
        financial: Dict[str, Any],
    ) -> str:
        lines = [f"Good morning. Today is {datetime.utcnow().strftime('%A, %B %d')}." ]

        if events:
            lines.append(f"You have {len(events)} event{'s' if len(events) != 1 else ''} today.")
            for event in events[:3]:
                lines.append(f"- {event.get('title', 'Untitled')} at {event.get('start_time', 'TBD')}")
        else:
            lines.append("Your calendar is clear today.")

        urgent_tasks = [task for task in tasks if int(task.get("priority", 0)) >= 4]
        if urgent_tasks:
            lines.append(f"You have {len(urgent_tasks)} high-priority tasks.")

        alerts = financial.get("alerts", [])
        if alerts:
            lines.append("Financial alerts: " + "; ".join(alerts))

        return "\n".join(lines)

    def get_today_briefing(self) -> Dict[str, Any]:
        events = self.get_upcoming_events(days=1)
        tasks = self.get_active_tasks()
        financial = self.get_financial_summary()
        urgent_events = [event for event in events if int(event.get("priority", 0)) >= 3]
        urgent_tasks = [task for task in tasks if int(task.get("priority", 0)) >= 4]

        return {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "events_today": len(events),
            "urgent_events": urgent_events,
            "active_tasks": len(tasks),
            "urgent_tasks": urgent_tasks,
            "financial_alerts": financial.get("alerts", []),
            "briefing_text": self._generate_briefing_text(events, tasks, financial),
        }

    # Verification
    def _get_caller_context(self, caller_number: str) -> Dict[str, Any]:
        contacts = self.search_contacts(query=caller_number)
        if not contacts:
            return {"known": False}

        contact = contacts[0]
        return {
            "known": True,
            "contact": contact,
            "financial_associated": any(c.get("type") == "financial" for c in contacts),
        }

    def _generate_verification_advice(self, status: str, context: Dict[str, Any]) -> str:
        if status == "likely_verified" and context.get("known"):
            return f"This appears to be {context['contact']['name']} from your contacts."
        if status == "suspicious" and context.get("known"):
            return f"Warning: number matches {context['contact']['name']} but identity claim is inconsistent."
        return "Unknown caller. Consider callback verification before sharing private information."

    def log_verification_call(
        self,
        caller_number: str,
        caller_name: Optional[str] = None,
        claimed_identity: Optional[str] = None,
    ) -> Dict[str, Any]:
        call_id = self._next_id("call", {"caller_number": caller_number})
        now = datetime.utcnow().isoformat()
        verification_status = "pending"
        verification_method: Optional[str] = None

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name, type FROM contacts WHERE phone LIKE ?", (f"%{caller_number}%",))
            match = cur.fetchone()

            if match:
                contact_name = match[0]
                if caller_name and caller_name.strip().lower() == str(contact_name).strip().lower():
                    verification_status = "likely_verified"
                    verification_method = "known_contact"
                else:
                    verification_status = "suspicious"
                    verification_method = "identity_mismatch"

            cur.execute(
                """
                INSERT INTO verification_calls
                (id, caller_number, caller_name, claimed_identity, verification_status, verification_method, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (call_id, caller_number, caller_name, claimed_identity, verification_status, verification_method, now),
            )
            conn.commit()

        context = self._get_caller_context(caller_number)
        return {
            "call_id": call_id,
            "status": verification_status,
            "method": verification_method,
            "context": context,
            "cali_suggestion": self._generate_verification_advice(verification_status, context),
        }

    def get_verification_queue(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM verification_calls
                WHERE verification_status IN ('pending', 'suspicious')
                ORDER BY timestamp DESC
                LIMIT 25
                """
            )
            return self._rows(cur)

    # Tasks
    def add_task(
        self,
        title: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: int = 1,
        category: str = "personal",
        cali_suggested: bool = False,
    ) -> Dict[str, Any]:
        task_id = self._next_id("task", {"title": title, "category": category})
        now = datetime.utcnow().isoformat()

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO tasks (id, title, description, due_date, priority, category, cali_suggested, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, title, description, due_date, priority, category, int(cali_suggested), now),
            )
            conn.commit()

        self._log_memory("task", {"action": "add_task", "task_id": task_id, "title": title})
        return {"success": True, "task_id": task_id, "message": f"Added task: {title}"}

    def get_active_tasks(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            if category:
                cur.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'active' AND category = ?
                    ORDER BY priority DESC, COALESCE(due_date, '9999-12-31T00:00:00') ASC
                    """,
                    (category,),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'active'
                    ORDER BY priority DESC, COALESCE(due_date, '9999-12-31T00:00:00') ASC
                    """
                )
            return self._rows(cur)

    def complete_task(self, task_id: str) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE tasks SET status='completed', completed_at=? WHERE id=?", (now, task_id))
            conn.commit()
        self._log_memory("task", {"action": "complete_task", "task_id": task_id})
        return {"success": True, "message": "Task marked complete."}

    # Site context
    def get_site_context(self, current_path: str = "/") -> Dict[str, Any]:
        pages = {
            "/": {"title": "Home", "description": "Spruked landing"},
            "/products/truemark-mint": {"title": "TrueMark Mint", "description": "K-NFT minting workflow"},
            "/goat": {"title": "The GOAT", "description": "Audiobook platform"},
            "/admin": {"title": "Admin", "description": "Operations hub"},
        }
        current = pages.get(current_path, {"title": "Unknown", "description": ""})
        actions = ["Go to Admin", "Open TrueMark Mint", "Check ORB status"]
        if current_path == "/admin":
            actions = ["Check daily briefing", "Review verification queue", "Add contact"]
        return {
            "current_page": current,
            "current_path": current_path,
            "available_pages": pages,
            "suggested_actions": actions,
        }

    # Learning queue
    def save_unanswered(self, question: str, context: Optional[str] = None) -> Dict[str, Any]:
        record_id = self._next_id("q", {"question": question})
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO unanswered (id, question, context, timestamp) VALUES (?, ?, ?, ?)",
                (record_id, question, context, datetime.utcnow().isoformat()),
            )
            conn.commit()
        return {"saved": True, "id": record_id}

    def get_stats(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        with self._connect() as conn:
            cur = conn.cursor()
            for table in ["contacts", "financial_accounts", "events", "tasks", "verification_calls"]:
                cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                counts[table] = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM tasks WHERE status='active'")
            counts["active_tasks"] = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM unanswered")
            counts["unanswered_questions"] = int(cur.fetchone()[0])

        return {**counts, "identity": self.identity, "last_pruned": datetime.utcnow().isoformat()}

    # Query routing
    def _parse_intent(self, query: str) -> Dict[str, Any]:
        q = query.lower().strip()

        if any(token in q for token in ["verification", "who called", "incoming call", "caller"]):
            return {"type": "verification_queue"}
        if any(token in q for token in ["poll inbox", "sync inbox", "check inbox", "poll mailbox", "sync mailbox"]):
            return {"type": "email_poll"}
        if any(token in q for token in ["crm", "pipeline", "lead pipeline", "lead status", "sales funnel"]):
            return {"type": "crm_pipeline"}
        if any(token in q for token in ["email status", "mail status", "mailbox status", "inbox status"]):
            return {"type": "email_status"}
        if any(token in q for token in ["schedule appointment", "book appointment", "set appointment"]):
            return {"type": "crm_appointment_request", "params": {"request": query}}
        if any(token in q for token in ["connect my bank", "connect bank", "link my bank", "link bank", "connect institution", "link institution"]):
            return {"type": "connect_bank", "params": {"request": query}}
        if any(token in q for token in ["remember this", "remember that", "note this", "note that", "add this", "add that"]):
            cleaned = (
                query.replace("remember this", "")
                .replace("remember that", "")
                .replace("note this", "")
                .replace("note that", "")
                .replace("add this", "")
                .replace("add that", "")
                .strip()
            ) or query.strip()
            return {"type": "add_task", "params": {"title": cleaned, "category": "personal", "priority": 3}}
        if q.startswith("add task") or q.startswith("remind me to") or " task " in f" {q} ":
            title = query.replace("add task", "").replace("remind me to", "").strip() or "New Task"
            return {"type": "add_task", "params": {"title": title, "category": "personal", "priority": 3}}
        if any(token in q for token in ["balance", "financial", "bank", "account", "money"]):
            return {"type": "financial_summary"}
        if any(token in q for token in ["today", "schedule", "calendar", "briefing"]):
            return {"type": "daily_briefing"}
        if any(token in q for token in ["contact", "phone", "email"]):
            return {"type": "contact_query", "params": {"name": query}}
        if any(token in q for token in ["go to", "navigate", "where am i", "page"]):
            return {"type": "site_nav"}
        return {"type": "unknown"}

    def _format_contact_results(self, contacts: List[Dict[str, Any]]) -> str:
        if not contacts:
            return "I could not find matching contacts."
        if len(contacts) == 1:
            contact = contacts[0]
            return f"Found {contact['name']} ({contact['type']}): {contact.get('phone') or 'No phone'} | {contact.get('email') or 'No email'}"
        return f"Found {len(contacts)} contacts: " + ", ".join(c["name"] for c in contacts[:6])

    def process_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        intent = self._parse_intent(query)
        intent_type = intent["type"]

        if intent_type == "contact_query":
            contacts = self.search_contacts(query=intent.get("params", {}).get("name", ""))
            return {"response": self._format_contact_results(contacts), "data": contacts, "intent": intent}

        if intent_type == "financial_summary":
            summary = self.get_financial_summary()
            response = (
                f"Your total balance across {summary['account_count']} accounts is "
                f"${summary['total_balance']:.2f}."
            )
            return {"response": response, "data": summary, "intent": intent}

        if intent_type == "daily_briefing":
            briefing = self.get_today_briefing()
            return {"response": briefing["briefing_text"], "data": briefing, "intent": intent}

        if intent_type == "add_task":
            params = intent.get("params", {})
            task = self.add_task(
                title=params.get("title", "New Task"),
                priority=int(params.get("priority", 3)),
                category=str(params.get("category", "personal")),
            )
            return {"response": task["message"], "data": task, "intent": intent}

        if intent_type == "connect_bank":
            bank_task = self.add_task(
                title=f"Bank connection requested: {intent.get('params', {}).get('request', 'Bank link')}",
                priority=5,
                category="financial",
                cali_suggested=True,
            )
            return {
                "response": (
                    "I queued your bank-link setup request. Next step is secure institution linking so I can track balances "
                    "and support checkout routing for your business accounts."
                ),
                "data": bank_task,
                "intent": intent,
            }

        if intent_type == "crm_pipeline":
            pipeline = self.get_crm_pipeline()
            s = pipeline.get("stages", {})
            return {
                "response": (
                    "CRM pipeline loaded. "
                    f"Prospect: {s.get('prospect', 0)}, Qualified: {s.get('qualified', 0)}, "
                    f"Contacted: {s.get('contacted', 0)}, Meeting Scheduled: {s.get('meeting_scheduled', 0)}, "
                    f"Proposal: {s.get('proposal', 0)}, Won: {s.get('won', 0)}, Lost: {s.get('lost', 0)}."
                ),
                "data": pipeline,
                "intent": intent,
            }

        if intent_type == "email_status":
            status = self.get_email_connector_status()
            if not status.get("configured"):
                return {
                    "response": "Email connector is not configured yet. Add bryan@spruked.com in CRM Email settings.",
                    "data": status,
                    "intent": intent,
                }
            return {
                "response": f"Email connector status: {status.get('status', 'configured')}.",
                "data": status,
                "intent": intent,
            }

        if intent_type == "email_poll":
            poll = self.poll_inbound_mailbox(mailbox="INBOX", limit=25, since_hours=72, unseen_only=True)
            if not poll.get("success"):
                return {
                    "response": f"Mailbox poll failed: {poll.get('message') or poll.get('status', 'unknown error')}",
                    "data": poll,
                    "intent": intent,
                }
            return {
                "response": (
                    f"Mailbox sync complete. Created {poll.get('created_activities', 0)} CRM email activities, "
                    f"new contacts: {poll.get('created_contacts', 0)}, duplicates skipped: {poll.get('duplicates', 0)}."
                ),
                "data": poll,
                "intent": intent,
            }

        if intent_type == "crm_appointment_request":
            task = self.add_task(
                title=f"CRM appointment requested: {intent.get('params', {}).get('request', 'appointment')}",
                priority=4,
                category="crm",
                cali_suggested=True,
            )
            return {
                "response": "I queued that appointment request in CRM tasks. You can schedule it directly in the Leads tab.",
                "data": task,
                "intent": intent,
            }

        if intent_type == "verification_queue":
            queue = self.get_verification_queue()
            return {"response": f"You have {len(queue)} calls requiring verification attention.", "data": queue, "intent": intent}

        if intent_type == "site_nav":
            nav = self.get_site_context((context or {}).get("current_path", "/admin"))
            return {
                "response": f"You are on {nav['current_page']['title']}. {nav['current_page']['description']}",
                "data": nav,
                "intent": intent,
            }

        self.save_unanswered(query, json.dumps(context or {}))
        return {
            "response": "I do not have a dedicated function for that yet. I saved it in the learning queue.",
            "data": None,
            "intent": {"type": "unknown"},
        }


_cali_skg: Optional[CaliPersonalSKG] = None


def get_cali_skg(base_path: Optional[str] = None) -> CaliPersonalSKG:
    global _cali_skg
    if _cali_skg is None:
        _cali_skg = CaliPersonalSKG(base_path=base_path)
    return _cali_skg
