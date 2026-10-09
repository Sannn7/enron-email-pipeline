-- Enron email pipeline schema (SQLite).
-- Dates are ISO-8601 UTC text ("2001-05-14T23:39:00Z"), so text order = time order.
-- Booleans are INTEGER 0/1.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS emails (
    id                 INTEGER PRIMARY KEY,
    -- mandatory fields
    message_id         TEXT    NOT NULL UNIQUE,          -- exact duplicates are rejected on insert
    date               TEXT    NOT NULL,                 -- UTC
    from_address       TEXT    NOT NULL,
    subject            TEXT    NOT NULL,                 -- as written, Re:/Fwd: kept ('' if empty)
    body               TEXT    NOT NULL,                 -- primary body only, as written
    source_file        TEXT    NOT NULL UNIQUE,          -- e.g. maildir/sager-e/inbox/12.
    -- to/cc/bcc live in email_recipients
    -- optional fields
    x_from             TEXT,
    x_to               TEXT,
    x_cc               TEXT,
    x_bcc              TEXT,
    x_folder           TEXT,
    x_origin           TEXT,
    content_type       TEXT,
    has_attachment     INTEGER NOT NULL DEFAULT 0 CHECK (has_attachment IN (0, 1)),
    forwarded_content  TEXT,
    quoted_content     TEXT,
    in_reply_to        TEXT,
    references_hdr     TEXT,
    -- derived, used by copy collapse / dedup
    normalized_subject TEXT    NOT NULL,                 -- Re:/Fw:/Fwd: stripped, lowercased
    body_hash          TEXT    NOT NULL,                 -- sha1 of the full body, whitespace collapsed
    copy_key           TEXT    NOT NULL,                 -- digest of (raw From, instant, normalized subject, body hash)
    is_copy           INTEGER NOT NULL DEFAULT 0 CHECK (is_copy IN (0, 1)),
    copy_of            TEXT    REFERENCES emails (message_id),
    copy_kind          TEXT    CHECK (copy_kind IN ('folder', 'tz_shift')),  -- why is_copy was set
    -- duplicate detection (Task 3)
    is_duplicate       INTEGER NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0, 1)),
    duplicate_of       TEXT    REFERENCES emails (message_id),
    similarity_score   REAL,
    -- notification tracking (Task 4)
    notification_sent  INTEGER NOT NULL DEFAULT 0 CHECK (notification_sent IN (0, 1)),
    notification_date  TEXT,
    -- thread reconstruction (bonus)
    thread_id          INTEGER,
    ingested_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS addresses (
    id    INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE                           -- lowercased, kept as written
);

CREATE TABLE IF NOT EXISTS email_recipients (
    email_id       INTEGER NOT NULL REFERENCES emails (id) ON DELETE CASCADE,
    address_id     INTEGER NOT NULL REFERENCES addresses (id),
    recipient_type TEXT    NOT NULL CHECK (recipient_type IN ('to', 'cc', 'bcc')),
    position       INTEGER NOT NULL,                     -- order within the header, from 0
    PRIMARY KEY (email_id, recipient_type, position)
);

CREATE TABLE IF NOT EXISTS attachments (
    email_id INTEGER NOT NULL REFERENCES emails (id) ON DELETE CASCADE,
    filename TEXT    NOT NULL,
    PRIMARY KEY (email_id, filename)
);

CREATE TABLE IF NOT EXISTS parse_failures (
    id          INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL UNIQUE,
    reason      TEXT NOT NULL,                           -- e.g. missing_to, unparseable_date
    detail      TEXT,
    logged_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS threads (
    thread_id          INTEGER PRIMARY KEY,
    root_message_id    TEXT NOT NULL,
    normalized_subject TEXT NOT NULL,
    email_count        INTEGER NOT NULL,
    first_date         TEXT NOT NULL,
    last_date          TEXT NOT NULL
);

-- named entities (bonus, filled only by `python main.py --ner`)
CREATE TABLE IF NOT EXISTS entities (
    id         INTEGER PRIMARY KEY,
    email_id   INTEGER NOT NULL REFERENCES emails (id) ON DELETE CASCADE,
    text       TEXT    NOT NULL,                          -- entity text, whitespace collapsed
    label      TEXT    NOT NULL CHECK (label IN ('PERSON', 'ORG', 'DATE', 'GPE')),
    source     TEXT    NOT NULL CHECK (source IN ('body', 'forwarded', 'quoted')),
    start_char INTEGER NOT NULL,                          -- offsets in the NER input text of that field
    end_char   INTEGER NOT NULL,
    UNIQUE (email_id, source, start_char, end_char, label)
);

-- required indexes
CREATE INDEX IF NOT EXISTS idx_emails_date         ON emails (date);
CREATE INDEX IF NOT EXISTS idx_emails_from_address ON emails (from_address);
CREATE INDEX IF NOT EXISTS idx_emails_subject      ON emails (subject);
-- supporting indexes
CREATE INDEX IF NOT EXISTS idx_emails_dedup_block  ON emails (from_address, normalized_subject);
CREATE INDEX IF NOT EXISTS idx_emails_copy_key     ON emails (copy_key);
CREATE INDEX IF NOT EXISTS idx_emails_duplicate    ON emails (is_duplicate, notification_sent);
CREATE INDEX IF NOT EXISTS idx_emails_thread       ON emails (thread_id);
CREATE INDEX IF NOT EXISTS idx_recipients_address  ON email_recipients (address_id);
CREATE INDEX IF NOT EXISTS idx_entities_label_text ON entities (label, text);
CREATE INDEX IF NOT EXISTS idx_entities_email      ON entities (email_id);
