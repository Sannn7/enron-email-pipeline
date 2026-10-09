# Enron Email Pipeline — Plan

Status: **fixture phase closed (2026-10-08). Next: build the core, one step at a time.**

## 0. Deadline scope (submission due end of day 2026-10-09). Overrides anything below.

1. **Core (must ship):** Tasks 1–4 and every deliverable in spec section 9:
   - source code
   - README.md
   - AI_USAGE.md
   - schema.sql
   - sample_queries.sql
   - mcp_config.json.example
   - output/replies/
   - output/send_log.csv
   - duplicates_report.csv
   - error_log.txt
   - requirements.txt
2. **Bonuses, only after the core works end to end:** B1 incremental processing, then B2 thread reconstruction.
3. **Dropped (listed in the README as future work):**
   - B4 NER
   - B5 dashboard
   - the full-dataset performance run (B3, `--full-dataset`, benchmark)
   - `--ner`, `--all-bonuses`, `--full-dataset` and `dashboard.py` are not built. Section 6 is kept as the documented future approach.
4. Build order: Steps 1–18 (core) → 19–23 (deliverables) → B1 → B2. Step 18 (full-mailbox robustness run) stays if time allows.

Constraints: Python 3.10+, SQLite, rapidfuzz, pytest, `python main.py` runs everything.
Workflow: I write code; you run tests and installs, using commands I hand over.

---

## 1. Decisions (locked)

| # | Decision |
|---|---|
| D1 | **Main 5 (approved): skilling-j, sager-e, arnold-j, steffes-j, farmer-d.** Full mailboxes, all folders. The evidence is in section 9. |
| D2 | Collapse folder/mailbox copies before dedup (default). Log how many were collapsed. `--dedup-mode literal` runs the spec as written. You verify the "different Message-ID" claim yourself first (Step 0.4). |
| D3 | Anchor grouping: each email is compared only to its group's earliest email. |
| D4 | Bodies under 20 characters (after whitespace normalization) are excluded from dedup. Documented in the README. |
| D5 | Custom Python MCP server (FastMCP + smtplib + Gmail App Password). |
| D6 | Both routes: (a) `main.py --send-live` as an MCP client; (b) Claude Code calls `send_email` interactively. |
| D7 | Live mode requires `--redirect-to`; every live send goes to your test inbox. The `.eml` drafts keep the real sender. |
| D8 | `.eml` drafts for every flagged duplicate; live-send only the latest of each group. |
| D9 | Missing To: is a parse failure. |
| D10 | Parse failures go to `error_log.txt` and the `parse_failures` table. |
| D11 | Incremental re-runs (bonus B1). |
| D12 | **Revised for the deadline (section 0):** incremental, then threads, only after the core works. NER, dashboard and the full-dataset performance run are dropped (future work). |
| D13 | Output paths as in the spec: `duplicates_report.csv` and `error_log.txt` at the repo root; `output/replies/` and `output/send_log.csv` under `output/`. |
| Q1 | You download the full dataset into `data/` (gitignored). The core runs on the main 5 mailboxes by default; `--full-dataset` processes everything (performance bonus). |
| Q2 | `python main.py` runs Tasks 1–4 + incremental + threads. (`--ner`, `--all-bonuses` and the dashboard are dropped for the deadline; see section 0.) |
| Q3 | Threads: In-Reply-To / References first. Otherwise group by the same normalized subject, but only if the emails are within 14 days of each other **and** share at least one participant (sender or recipient). The window is configurable (`--thread-window-days`); the choice is documented in the README. |
| Q4 | ~~NER on the main 5 / full dataset~~ Dropped for the deadline (future work). |

---

## 2. Project structure

```
AISH/
├── main.py                      # entry point
├── config.py                    # defaults + CLI parsing
├── pipeline/
│   ├── models.py                # EmailRecord, ParseFailure dataclasses
│   ├── discovery.py             # walk maildir → file paths
│   ├── parsing/
│   │   ├── decode.py            # bytes → text, encoding fallbacks
│   │   ├── headers.py           # header block, unfolding, missing/duplicate headers
│   │   ├── addresses.py         # To/CC/BCC → clean address lists
│   │   ├── dates.py             # → UTC; PST/PDT/CST/CDT/EST/EDT/... table
│   │   └── body.py              # body / forwarded / quoted split; attachment detection
│   ├── extract.py               # one file → EmailRecord | ParseFailure
│   ├── db.py                    # schema init, batched inserts, queries
│   ├── stats.py                 # extraction stats, field completeness
│   ├── copies.py                # folder-copy collapse (D2)
│   ├── dedup.py                 # blocking, fuzzy match, grouping, flagging
│   ├── report.py                # duplicates_report.csv
│   ├── notify/
│   │   ├── template.py          # spec template + subject rule
│   │   ├── eml_writer.py        # dry-run drafts
│   │   ├── payloads.py          # output/pending_notifications.json (route b)
│   │   ├── mcp_client.py        # route a: stdio MCP client → send_email
│   │   └── sender.py            # cap, y/N, rate limit, send_log, idempotency
│   └── bonus/
│       ├── incremental.py       # B1
│       ├── threads.py           # B2
│       ├── parallel.py          # B3
│       └── entities.py          # B4
├── dashboard.py                 # B5 (Streamlit; streamlit run dashboard.py)
├── mcp_server/gmail_smtp_server.py
├── scripts/
│   ├── mailbox_counts.py        # Step 0.2
│   └── benchmark.py             # B3 measurement
├── tests/
│   ├── fixtures/synthetic/      # small hand-made edge cases for unit tests
│   ├── fixtures/real/           # 20–30 real messy emails from non-main mailboxes
│   ├── fixtures/expected/       # expected parsed output (JSON), verified by you
│   └── test_*.py
├── schema.sql, sample_queries.sql, mcp_config.json.example
├── requirements.txt, README.md, AI_USAGE.md, PLAN.md
├── data/                        # full maildir + enron.db (gitignored)
└── output/                      # replies/, send_log.csv, run_summary.json, pipeline.log
```

---

## 3. Pipeline architecture

```
maildir/<user>/<folder>/<file>
 │
 ├─ S1  DISCOVER     paths for the selected mailboxes
 │                   [B1: skip source_files already in the DB]
 ├─ S2  PARSE        decode → headers → addresses → date → body split → attachments
 │                   [B3: multiprocessing pool]
 ├─ S3  VALIDATE     missing mandatory field → ParseFailure(path, reason)
 │                   → error_log.txt + parse_failures table
 ├─ S4  LOAD         batched INSERT OR IGNORE on message_id; normalized recipients
 │                   [B3: WAL, big batches, indexes built after bulk load]
 ├─ S5  STATS        found / parsed / failed / inserted / skipped + field completeness %
 ├─ S6  COLLAPSE     mark folder/mailbox copies (D2); log the count   [skipped in literal mode]
 ├─ S7  DEDUP        block (from, normalized_subject) → rapidfuzz vs the group's earliest
 │                   → flag is_duplicate, duplicate_of, similarity_score
 ├─ S8  REPORT       duplicates_report.csv + dedup stats
 ├─ S9  THREADS      [B2] thread_id
 ├─ S10 ENTITIES     [B4] entities table
 ├─ S11 NOTIFY       for each flagged row: .eml draft + pending payload
 │                   live mode: summary → y/N → MCP send (cap, delay) → send_log
 │                   → notification_sent / notification_date
 └─ S12 SUMMARY      console + output/run_summary.json (counts and per-stage timings)

dashboard.py ── reads enron.db (read-only)
```

**Default run:** core (S1–S8, S11, S12) + B1 incremental + B2 threads, on the main 5 mailboxes.
**Opt-in:**
- `--ner` adds S10.
- `--full-dataset` switches S1 to every mailbox and turns on the B3 settings (parallel workers, large batches, deferred indexes).
- `--all-bonuses` = incremental + threads + NER + the B3 settings. It does **not** switch to the full dataset; combine it with `--full-dataset` for that.

**Bonus isolation.** Each bonus is its own module and its own stage, behind a flag. Bonus tables and columns live in `schema.sql` but are nullable or empty when the bonus is off. A test runs the core with every bonus off.

---

## 4. Key designs

### 4.1 Folder-copy collapse (D2)
- **Copy key:** exactly the definition used for mailbox selection (section 9), so the README numbers match the pipeline output:
  - **sender:** the `From` header, lowercased and trimmed
  - **timestamp:** the parsed instant (equal instants are equal regardless of timezone); the raw `Date` string if unparseable
  - **normalized subject:** leading `re:|fw:|fwd:` stripped repeatedly, whitespace collapsed, lowercased
  - **body:** the hash of the *full* body (not the primary body) with whitespace collapsed and trimmed
  - Exact match only.
- **Single source of truth:** the key is defined in one function (`pipeline/copies.py: copy_key`). At Step 11, `scripts/mailbox_profile.py` switches to importing it, and the profile table in section 9 and the README is regenerated from the shared code. A test asserts that the script's collapsed counts equal the pipeline's for the main 5. The current section 9 numbers are provisional until then.
- **Scope:** this also catches the same email in two people's mailboxes (the sender's `sent/` and the recipient's `inbox/`).
- **Canonical row:** the lexicographically smallest `source_file`. The others get `is_copy=1` and `copy_of=<canonical message_id>`. They stay in the DB for traceability; they are not deleted.
- **Dedup:** runs on canonical rows only. `--dedup-mode literal` skips collapsing and dedups everything; timestamp ties are then broken by `source_file`.
- **Logging:** collapsed count, the number of copy groups, and the top folders involved.

### 4.2 Dedup (D3, D4)
- **Subject normalization:** strip repeated leading `re:|fw:|fwd:` (case-insensitive), collapse whitespace, lowercase.
- **Bodies compared:** the normalized primary body (forwarded and quoted parts removed; quoted-printable artifacts `=20`, `=3D`, `=09` and soft line breaks cleaned; whitespace collapsed).
  - If that is under 20 characters, compare the normalized `forwarded_content` instead.
  - If that is also under 20 characters, the email is excluded from dedup.
  - Consequence (fixture F13c): two copies of a recurring forwarded report score 97.6 and are flagged.

### 4.2b Body split and storage (decided at fixture review)
- **First marker wins.** Everything from the first Outlook or Lotus marker onward goes into one field:
  - Lotus `Forwarded by` → `forwarded_content`
  - Outlook `-----Original Message-----` → `quoted_content`, unless the subject starts with `FW:`/`Fwd:`, in which case → `forwarded_content`
  - `>` lines before the first marker → `quoted_content`
- **Storage:**
  - Bodies are stored exactly as written. Quoted-printable is cleaned only in the normalized text used for similarity (and NER, if it is ever built).
  - Malformed addresses are kept exactly as written, lowercased.
- **Line endings:** headers end in CRLF and bodies in LF. Parsing must use the email parser (or normalize CRLF) and never split on a raw `\n\n`.
- **Grouping:** within a block, sort by `(date_utc, source_file)`. Each email joins the first group whose anchor (earliest email) it matches at ≥ 90 (`rapidfuzz.fuzz.ratio`); otherwise it starts a new group.
- **Flagging:** every email in a group except the anchor gets `is_duplicate=1`, `duplicate_of=<anchor message_id>` and its score against the anchor.
- **Scorer:** `fuzz.ratio`, not a token-based scorer, because word order matters for a re-send. This is documented in the README.

### 4.3 Notification subject (point 1)
- **Rule:** start from the original email's subject (as the spec says). If it already starts with `re:` (case-insensitive, after trimming), use it as-is; otherwise prepend `Re: `.
  - `Forecast` → `[Duplicate Notice] Re: Forecast`
  - `RE: Forecast` → `[Duplicate Notice] RE: Forecast` (preserved, not doubled)
  - `Fwd: Forecast` → `[Duplicate Notice] Re: Fwd: Forecast`
  - empty subject → `[Duplicate Notice] Re: (no subject)`
- **Other headers:** `References: <duplicate message_id>`, `Date:` set to the current timestamp.
- **Draft filename:** `reply_<sha256(message_id)[:16]>.eml`

### 4.4 Attachments (point 2)
- **`has_attachment = true` if any of the following:**
  - `Content-Type` is multipart, or contains `name=` or `filename=`
  - the body contains an Enron `<<filename.ext>>` reference, matched by the regex `<<\s*[^<>\n]+?\.[A-Za-z0-9]{2,5}\s*>>`
  - an `- filename.ext` line directly follows an "attached" mention (conservative, to avoid false positives)
- **Filenames:** stored in an `attachments` table (`email_id`, `filename`, `source` = header | body_ref).

### 4.5 MCP (D5, D6, D7)
- **Server:** `mcp_server/gmail_smtp_server.py`, built with FastMCP. It exposes one tool, `send_email(to, subject, body, references?)`, and sends through smtplib with STARTTLS to smtp.gmail.com:587. Credentials come from environment variables only.
- **Route a:** `main.py --send-live` spawns the server over stdio using the `mcp` Python SDK client and calls `send_email` for each payload.
- **Route b:** the server is registered in Claude Code (`.mcp.json`). You prompt me to read `output/pending_notifications.json` and call `send_email`. The results are appended to `send_log.csv`. Then `python main.py --sync-send-log` updates `notification_sent` / `notification_date` from that log, so idempotency holds for both routes.
- **Safety:**
  - Live mode refuses to run without `--redirect-to` and prints the recipient as "redirected from X".
  - It shows a summary and waits for y/N.
  - `--max-send` defaults to 10 and `--send-delay` to 2 seconds.
  - Already-notified rows are skipped.

### 4.6 Schema
- **`emails`**
  - Core: `id`, `message_id` UNIQUE, `date_utc`, `from_address`, `subject`, `normalized_subject`, `body`, `forwarded_content`, `quoted_content`, `source_file` UNIQUE
  - Optional headers: `x_from`, `x_to`, `x_cc`, `x_bcc`, `x_folder`, `x_origin`, `content_type`, `has_attachment`
  - Threading: `in_reply_to`, `references_hdr`, `thread_id`
  - Copies: `body_hash`, `is_copy`, `copy_of`
  - Dedup: `is_duplicate`, `duplicate_of`, `similarity_score`
  - Notification: `notification_sent`, `notification_date`, `ingested_at`
- **Other tables:**
  - `addresses`(`id`, `email` UNIQUE)
  - `email_recipients`(`email_id`, `address_id`, `recipient_type` to|cc|bcc, `position`)
  - `attachments`(`email_id`, `filename`, `source`)
  - `parse_failures`(`source_file`, `reason`, `detail`, `logged_at`)
  - `threads`(`thread_id`, `root_message_id`, `normalized_subject`, `email_count`, `first_date`, `last_date`)
  - `entities`(`email_id`, `text`, `label`, `start_char`, `end_char`)
- **Indexes:**
  - `date_utc`
  - `from_address`
  - `subject`
  - `(from_address, normalized_subject)` for dedup blocking
  - `body_hash` for the copy collapse
  - `thread_id`
  - `entities(label, text)`

---

## 5. Build steps (each one testable on its own)

**Testing gate after every step:** I hand you the `pytest` command, you run it and report back, and we move on only when it passes.

### Phase 0 — Data and setup
| # | Step | Done when |
|---|---|---|
| 0.1 | You create the venv and install requirements (commands from me) | `python --version` ≥ 3.10; the imports work |
| 0.2 | **You** download and extract the full dataset into `data/maildir/` (commands from me); `scripts/mailbox_counts.py` prints the email count per mailbox | You pick the 5 main mailboxes |
| 0.3 | Choose 1 robustness mailbox and 2–3 fixture-source mailboxes (none of them in the main 5); record the choices in `config.py` | The choices are recorded |
| 0.4 | **You verify D2:** I give you a command that finds the same email in `sent/`, `all_documents/` and `discussion_threads/` and prints the Message-IDs side by side | You confirm or refute. If refuted, we revisit D2 before Step 6 |
| 0.5 | **Fixtures:** I pick 20–30 genuinely messy emails from the non-main mailboxes (folded headers, odd addresses, odd timezones, nested forwards, `<<attachments>>`, encoding issues, missing To, empty bodies). I write the expected output to `tests/fixtures/expected/<name>.json` | **DONE.** 38 real files in `tests/fixtures/real/maildir/` + 1 synthetic re-send in `tests/fixtures/synthetic/maildir/`; 25 expected files + `tests/fixtures/expected/INDEX.md`. Status: AI drafted, reviewed by flags, not manually verified line by line |

### Phase 1 — Core (Tasks 1–4)
| # | Step | Test focus |
|---|---|---|
| 1 | config + CLI | defaults: dry-run, max-send 10, delay 2s, threshold 90, min body 20; live mode without `--redirect-to` errors |
| 2 | discovery | synthetic tree → expected paths; non-files and hidden files skipped |
| 3 | decode | latin-1, cp1252, invalid bytes → text, no crash |
| 4 | headers | folded headers, missing headers, duplicate headers, header-only files |
| 5 | addresses | display names, `<a@b>`, continuations, `IMCEANOTES-…`, empty values; lowercasing |
| 6 | dates | `-0700 (PDT)`, bare abbreviations, malformed dates → UTC or failure |
| 7 | body | Original Message / Forwarded by / `>` quotes / nested forwards; `<<file>>` detection |
| 8 | extract + validate | **all real fixtures match the verified expected JSON**; failure reasons are correct |
| 9 | db | schema creation; recipient normalization; duplicate message_id ignored; parse_failures rows |
| 10 | stats | exact counts and completeness on a fixture set |
| 11 | copies (S6) | identical copies collapse; near-identical ones don't; literal mode skips it; count logged |
| 12 | dedup | subject normalization; 89 vs 91; under-20-character exclusion; groups of 2 and 3+; anchor is the earliest; deterministic ties |
| 13 | report | CSV columns and rows match the flagged records |
| 14 | template + eml | exact spec text; subject rule cases (4.3); stable hash filename |
| 15 | sender (fake MCP) | cap; "N" aborts; delay; send_log; idempotent re-run; route b `--sync-send-log` |
| 16 | MCP server + client | the server lists `send_email`; client round-trip against a stub SMTP; **one manual live send to your inbox** |
| 17 | main.py end to end | fixture maildir → every output file produced; second run sends 0 and re-flags consistently |
| 18 | Robustness run | the whole unused mailbox: no crash; failure rate and top failure reasons recorded for the README |

### Phase 2 — Bonuses (each behind a flag; core tests re-run with all bonuses off)

**Deadline scope:** only B1 and B2 are built. B3 (full-dataset run), B4 and B5 are dropped and become README future work.
| # | Bonus | Approach | Test |
|---|---|---|---|
| B1 | Incremental | skip a `source_file` already in `emails` or `parse_failures`; `--full-reingest` to override | second run parses 0 files; a newly added file is the only one ingested |
| B2 | Threads | (1) In-Reply-To / References when present (rare in Enron). (2) Otherwise: same normalized subject **and** within 14 days of the previous email in the thread **and** at least one shared participant (sender or recipient). `--thread-window-days` (default 14) | a reply joins its parent via its headers; the same subject 20 days later does not join; the same subject with no shared participant (e.g. "Meeting") does not join; a custom window is honored |
| B3 | Performance | see section 6 | `test_parallel_matches_sequential`: the same fixture maildir run with `--workers 1` and `--workers 4` gives identical emails, recipients, failures, copy/duplicate flags and report CSV (rows compared order-independently); speed: benchmark table |
| B4 | NER | spaCy `en_core_web_sm`, `nlp.pipe` in batches, primary body only (truncated), labels PERSON / ORG / DATE. Only with `--ner`; main 5 by default, full set with `--full-dataset`. Runtime and emails/sec are logged | known sentences → expected entities; without `--ner` the table stays empty |
| B5 | Dashboard | `dashboard.py`, Streamlit, read-only: extraction stats, duplicate counts, top senders, search by sender / subject / date (+ SQLite FTS5 on the body) | smoke test: the app imports and its query functions return the expected data from the fixture DB |

### Phase 3 — Deliverables
| # | Item |
|---|---|
| 19 | `schema.sql` (final), `sample_queries.sql` with 3+ queries and expected output descriptions, run against the real DB |
| 20 | `mcp_config.json.example` with placeholder credentials; Claude Code registration snippet |
| 21 | README: setup, MCP setup, how to run, architecture, mailbox choice and why, threshold choices (90 / 20 characters), copy collapse + literal mode, robustness failure rate, benchmark table |
| 22 | AI_USAGE.md: tool, prompting strategy, 3–5 prompts, 2+ debugging stories, split of your code vs AI code, lessons learned, MCP section with route a and b prompts and a live send log excerpt or screenshot |
| 23 | Final run: regenerate `output/replies/`, `duplicates_report.csv`, `error_log.txt`, and capture `send_log.csv` from a capped live send |

---

## 6. Performance plan (B3)

**Where time goes:**
- parsing is CPU-bound
- inserts are I/O-bound and limited to a single writer in SQLite
- dedup is CPU-bound, but only inside blocks

**Approach:**
1. **Parallel parsing:** `multiprocessing.Pool(workers)` with `imap_unordered(chunksize≈500)`. Workers return plain tuples; the main process is the only DB writer. Files are streamed, never all held in memory.
2. **Batched inserts:** `executemany` with about 5,000 rows per transaction, plus:
   - `PRAGMA journal_mode=WAL`
   - `PRAGMA synchronous=NORMAL`
   - `PRAGMA temp_store=MEMORY`
   - secondary indexes created after the bulk load on a fresh DB
3. **Address cache:** an in-memory dict mapping email → address_id, to avoid a SELECT per recipient.
4. **Dedup:**
   - exact `body_hash` matches short-circuit to a score of 100
   - a length-ratio pre-filter skips pairs that can't reach 90 (`ratio ≤ 2·min/(a+b)`)
   - very large blocks use `rapidfuzz.process.cdist(workers=-1)`
5. **Incremental (B1)** makes re-runs on the full dataset near-instant.

**Measurement (`scripts/benchmark.py`):**
- **Configurations:**
  - serial baseline: `--workers 1`, batch size 1, indexes present during load
  - optimized: `--workers N`, batch size 5,000, deferred indexes
- **Datasets:** the same fixed inputs every time: 10k (main 5), about 50k, and the full ~517k
- **Metrics per stage:** wall time (`perf_counter`), files/sec, peak memory (`resource.getrusage`), DB size
- **Runs:** 3 per configuration; report the median
- **Output:** a table in the README with the speedup per stage and overall
- **Correctness check:** both configurations must produce identical row counts and identical duplicate flags

---

## 7. Output examples

```
[S1]  Discovered 14,212 files (5 mailboxes)
[S2-4] Parsed 14,180 | Failed 32 → error_log.txt | Inserted 14,180 | Skipped 0
[S5]  Completeness: cc 18.2% | bcc 17.9% | forwarded 9.4% | has_attachment 6.1% ...
[S6]  Collapsed 4,903 folder copies into 2,211 canonical emails
[S7-8] Duplicate groups: 112 | Flagged: 140 | Avg group size 2.25 → duplicates_report.csv
[S11] DRY-RUN: 140 drafts → output/replies/ ; 112 pending live sends (latest per group)
```
These numbers are illustrative only.

**Files:**
- `duplicates_report.csv`: `duplicate_message_id,original_message_id,subject,from_address,duplicate_date,original_date,similarity_score`
- `output/send_log.csv`: `timestamp,recipient,subject,message_id_referenced,status,error_message`
- `error_log.txt`: `<timestamp> | maildir/x/inbox/12 | missing_to | To header absent`

---

## 8. Specs

- **Runtime and libraries:**
  - Python 3.10+
  - stdlib: `email` (compat32 policy), `sqlite3`, `csv`, `hashlib`, `multiprocessing`
  - `rapidfuzz`, `mcp`, `pytest` (spaCy and Streamlit dropped with NER/dashboard)
- **Data formats:**
  - **Dates:** ISO-8601 UTC text.
  - **Addresses:** lowercase and trimmed. Internal Enron forms are kept, normalized rather than dropped.
  - **Thresholds:** similarity ≥ 90 (`fuzz.ratio`); minimum body length 20 characters.
- **CLI flags:**
  - **Paths and stage control:** `--maildir --mailboxes --db --reset-db --skip-ingest`
  - **Dedup:** `--dedup-mode {collapse,literal} --threshold --min-body-chars`
  - **Sending:** `--send-live --redirect-to --max-send --send-delay --sync-send-log`
  - **Bonuses:** `--full-reingest --no-incremental --no-threads --thread-window-days 14 --ner --full-dataset --workers --batch-size --all-bonuses`
- **Errors:**
  - one try/except per file and per stage
  - nothing escapes a single file
  - a bad group is logged and skipped

---

## 9. Main mailbox selection (D1)

**Method:** `scripts/mailbox_profile.py` (read-only; no tests by decision; kept as evidence along with `output/mailbox_profile.csv`).
- 11 candidates across 5 roles.
- All metrics except `raw` are after collapsing copies within each mailbox.
- Sanity check: 3 forwarded + 3 copy groups sampled each for steffes-j and farmer-d. All were correct, and every copy had a distinct Message-ID.

| mailbox | role | raw | unique | copies | CC | fwd | `>` quoted | `<<att>>` | shared subject | re-send candidates | ≥90% match | no To | 10+ recipients |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lay-k | exec | 5,937 | 3,651 | 38.5% | 23.0% | 9.3% | 3.2% | 194 | 1,662 | 267 | 49 | 5.8% | 10.6% |
| **skilling-j** | exec | 4,139 | 2,585 | 37.5% | 20.3% | 13.5% | 5.3% | 118 | 997 | 485 | 85 | 14.0% | 15.1% |
| haedicke-m | legal | 5,246 | 3,193 | 39.1% | 25.6% | 27.9% | 2.8% | 256 | 1,065 | 535 | 57 | 10.6% | 13.9% |
| **sager-e** | legal | 5,200 | 3,255 | 37.4% | 26.0% | 42.0% | 3.5% | 348 | 1,611 | 1,067 | 153 | 3.7% | 8.8% |
| **arnold-j** | trader | 4,898 | 2,643 | 46.0% | 7.7% | 37.1% | 3.2% | 122 | 864 | 725 | 141 | 4.6% | 4.4% |
| allen-p | trader | 3,034 | 1,397 | 54.0% | 7.4% | 32.9% | 3.5% | 84 | 435 | 365 | 89 | 3.9% | 4.7% |
| grigsby-m | trader | 2,237 | 1,166 | 47.9% | 9.1% | 28.6% | 3.8% | 95 | 458 | 352 | 36 | 3.8% | 9.3% |
| **steffes-j** | policy | 3,331 | 3,274 | 1.7% | 31.1% | 59.0% | 4.2% | 799 | 1,756 | 1,002 | 40 | 3.7% | 12.2% |
| shapiro-r | policy | 6,071 | 3,369 | 44.5% | 32.3% | 36.5% | 2.7% | 237 | 1,130 | 643 | 119 | 3.7% | 20.3% |
| beck-s | ops | 11,830 | 4,926 | 58.4% | 36.0% | 34.0% | 0.9% | 143 | 2,409 | 1,383 | 251 | 4.2% | 17.2% |
| **farmer-d** | ops | 13,032 | 5,234 | 59.8% | 29.1% | 31.6% | 1.6% | 210 | 2,713 | 1,576 | 277 | 2.8% | 15.7% |

**Selected 5:** raw 30,600 → **16,764 unique** after cross-mailbox collapse (target 12k–25k).
- **skilling-j (executive):** the most large recipient lists, the most `>` quoting, and 14% missing-To (exercises the D9 failure path).
- **sager-e (legal):** a high share of forwarded chains (42%), 348 attachment references, and many fuzzy matches.
- **arnold-j (trader):** short, low-CC emails with many fuzzy matches.
- **steffes-j (policy):** the heaviest forwarding (59%), the most attachment references, and almost no folder copies (a contrast case).
- **farmer-d (operations):** the most fuzzy matches and shared subjects; repetitive logistics mail.

**Findings to carry forward:**
- Filenames end in a dot (`289.`); `source_file` keeps it exactly (Step 2 tests).
- Outlook `-----Original Message-----` chains are usually replies, while Lotus `Forwarded by` blocks are forwards. Where each goes (`forwarded_content` vs `quoted_content`) is decided at Step 7.

---

## 10. Open questions

None. Q1–Q4 are resolved in section 1.

**Interpretation to confirm:** parallel parsing (B3) is off in the default run (`--workers 1`). It turns on with `--full-dataset`, `--all-bonuses`, or an explicit `--workers N`. The results are identical either way; only speed differs.
