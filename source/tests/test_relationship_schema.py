from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from cali_skg.core.communication_store import ingest_message, party_timeline
from cali_skg.migrations.relationship_intelligence_migration import run_migration


class RelationshipIntelligenceSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "cali-test.db")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE contacts (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  email TEXT,
                  phone TEXT,
                  address TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO contacts(id, name, email, phone, address)
                VALUES ('contact-1', 'Ada Example', 'Ada@Example.com', '(417) 555-0101', '101 Main St, Joplin, MO 64801')
                """
            )
            conn.commit()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_migration_is_idempotent_and_backfill_is_single_identity(self) -> None:
        first = run_migration(self.db_path)
        second = run_migration(self.db_path)
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "success")

        with closing(sqlite3.connect(self.db_path)) as conn:
            party_count = conn.execute("SELECT COUNT(*) FROM party").fetchone()[0]
            claim_count = conn.execute("SELECT COUNT(*) FROM identity_claim").fetchone()[0]
            evidence_count = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            party = conn.execute(
                "SELECT party_id, display_name, status FROM party WHERE party_id='legacy-contact:contact-1'"
            ).fetchone()
            email_claim = conn.execute(
                """
                SELECT value_normalized, source_type, verification_state
                FROM identity_claim
                WHERE party_id='legacy-contact:contact-1' AND claim_type='email'
                """
            ).fetchone()

        self.assertEqual(party_count, 1)
        self.assertEqual(claim_count, 3)
        self.assertEqual(evidence_count, 3)
        self.assertEqual(party, ("legacy-contact:contact-1", "Ada Example", "active"))
        self.assertEqual(email_claim[0], "ada@example.com")
        self.assertEqual(email_claim[1], "legacy_crm")
        self.assertEqual(email_claim[2], "unverified")

    def test_strict_and_candidate_relationships_are_physically_separate(self) -> None:
        run_migration(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        self.assertIn("relationship_edge", tables)
        self.assertIn("relationship_candidate", tables)
        self.assertIn("relationship_rejection", tables)
        self.assertNotEqual("relationship_edge", "relationship_candidate")

    def test_required_business_contexts_are_seeded_once(self) -> None:
        run_migration(self.db_path)
        run_migration(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute("SELECT business_id FROM business_context ORDER BY business_id").fetchall()
        business_ids = [row[0] for row in rows]
        self.assertEqual(
            business_ids,
            ["alpha_certsig", "certsig", "personal", "spruked", "truemark_mint"],
        )

    def test_active_claim_uniqueness_blocks_duplicate_current_claim(self) -> None:
        run_migration(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            claim = conn.execute(
                """
                SELECT claim_type, value_raw, value_normalized, value_hash, observed_from, created_at
                FROM identity_claim
                WHERE party_id='legacy-contact:contact-1' AND claim_type='email'
                """
            ).fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO identity_claim(
                      claim_id, party_id, claim_type, value_raw, value_normalized, value_hash,
                      confidence, source_type, verification_state, observed_from, created_at
                    ) VALUES ('duplicate-email', 'legacy-contact:contact-1', ?, ?, ?, ?, 1.0, 'test', 'unverified', ?, ?)
                    """,
                    claim,
                )

    def test_prime_mail_message_ingest_is_idempotent_and_links_known_party(self) -> None:
        run_migration(self.db_path)
        payload = {
            "channel": "email",
            "provider": "prime_mail",
            "account_identity": "bryan@spruked.com",
            "business_scope": "spruked",
            "external_id": "<msg-1@example.com>",
            "mailbox_id": "inbox",
            "direction": "inbound",
            "occurred_at": "2026-08-11T20:00:00-05:00",
            "raw_locator": "R:/email_client/vault/raw_email/aa/message.eml",
            "content_hash": "a" * 64,
            "thread_external_id": "thread-1",
            "subject": "Hello CALI",
            "sender_email": "Ada@Example.com",
            "sender_name": "Ada Example",
            "recipient_emails": ["bryan@spruked.com"],
        }

        first = ingest_message(self.db_path, payload)
        second = ingest_message(self.db_path, payload)

        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(first["primary_party_id"], "legacy-contact:contact-1")

        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM message_event").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversation_thread").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM communication_account").fetchone()[0], 1)

        timeline = party_timeline(
            self.db_path,
            "legacy-contact:contact-1",
            business_scope="spruked",
            channel="email",
        )
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["external_id"], "<msg-1@example.com>")
        self.assertEqual(timeline[0]["direction"], "inbound")
        self.assertEqual(timeline[0]["raw_locator"], payload["raw_locator"])


if __name__ == "__main__":
    unittest.main()
