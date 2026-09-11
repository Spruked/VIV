PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    hash_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    type TEXT,
    phone TEXT,
    email TEXT UNIQUE NOT NULL,
    address TEXT,
    notes TEXT,
    priority TEXT DEFAULT 'Medium',
    crm_stage TEXT,
    lead_source TEXT,
    owner TEXT,
    alias_names TEXT,
    company_role TEXT,
    organization_id TEXT,
    risk_score INTEGER DEFAULT 0,
    epistemic_status TEXT DEFAULT 'unverified',
    metadata_payload JSON,
    last_contacted_at DATETIME,
    next_follow_up_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

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
);

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
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    to_addr TEXT,
    subject TEXT,
    text_body TEXT,
    html_body TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financial_accounts (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT,
    balance REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'USD',
    status TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    contact_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS verification_calls (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    direction TEXT,
    duration_seconds INTEGER,
    recording_path TEXT,
    transcript TEXT,
    call_status TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    due_date DATETIME,
    status TEXT DEFAULT 'pending',
    priority TEXT DEFAULT 'Medium',
    contact_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS crm_activities (
    id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    description TEXT NOT NULL,
    operator TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS email_connectors (
    id TEXT PRIMARY KEY,
    account_email TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL,
    credentials_pointer TEXT,
    sync_state TEXT,
    last_sync_at DATETIME
);

CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    message_id UNINDEXED,
    sender,
    recipient,
    subject,
    text_body,
    html_body,
    raw_email,
    tokenize='porter'
);

CREATE TRIGGER IF NOT EXISTS after_email_insert AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(message_id, sender, recipient, subject, text_body, html_body, raw_email)
    VALUES (new.message_id, new.sender, new.recipient, new.subject, new.text_body, new.html_body, new.raw_email);
END;

CREATE TRIGGER IF NOT EXISTS after_email_delete AFTER DELETE ON emails BEGIN
    DELETE FROM emails_fts WHERE message_id = old.message_id;
END;

CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_external_links_contact ON contact_external_links(contact_id);
CREATE INDEX IF NOT EXISTS idx_external_links_platform ON contact_external_links(platform);
CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS idx_crm_activities_contact ON crm_activities(contact_id);
CREATE INDEX IF NOT EXISTS idx_verification_calls_contact ON verification_calls(contact_id);
