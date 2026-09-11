import os
import sqlite3

DB_PATH = r"R:\Substrate_Vault_R\vaults\r_drive_system_records\crm\memory\cali_personal.db"


def run_migration() -> None:
    print(f"[*] Initializing Phase 1B Migration on substrate: {DB_PATH}")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute(
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
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    print("[+] Migration completed successfully. Relational substrate intact.")


if __name__ == "__main__":
    run_migration()
