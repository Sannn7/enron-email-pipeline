# Enron Email Pipeline: extraction, deduplication and MCP notifications

A Python pipeline that parses raw Enron emails, stores them in a normalized SQLite database, detects
duplicate emails with fuzzy matching, and writes or sends duplicate notices through a custom
Gmail MCP server. One command runs everything:

```bash
python main.py
```

It runs in dry-run mode by default. Live sending needs `--send-live --redirect-to <your inbox>` plus a y/N confirmation.

Built with Claude Code; see [AI_USAGE.md](AI_USAGE.md) for how.

---

## Results on the selected mailboxes

| Stage | Count |
|---|---|
| Files discovered (5 mailboxes) | 30,600 |
| Parsed successfully | 29,650 (96.9%) |
| Failed (all `missing_to`, logged to `error_log.txt`) | 950 (3.1%) |
| Unique after folder-copy collapse | 16,054 |
| Unique after timezone-shifted copy collapse | 15,678 |
| Duplicate groups | 301 |
| Emails flagged as duplicates | 436 (`duplicates_report.csv`) |
| `.eml` drafts written | 436 (`output/replies/`) |
| Live notifications sent (redirected to a test inbox) | 2 (one per MCP route, `output/send_log.csv`) |

A full run takes about 11 seconds (ingest 8 s, dedup 2.6 s, notify 0.3 s); with the NER bonus (`--ner`)
it takes about 6 minutes more. There are 243 tests (`pytest`).

---

## Setup

Requirements: Python 3.10+ (developed on 3.13) and about 2.5 GB of disk for the extracted dataset.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # rapidfuzz, mcp (<2), pytest, spacy
python -m spacy download en_core_web_sm  # only needed for the NER bonus (--ner)
```

Download the dataset (423 MB) and extract it into `data/` (gitignored):

```bash
curl -L -o data/enron_mail_20150507.tar.gz https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz
tar -xzf data/enron_mail_20150507.tar.gz -C data      # creates data/maildir/
```

## Running

```bash
python main.py                                    # full pipeline, dry-run (default)
python main.py --send-live --redirect-to you@gmail.com --max-send 1   # live: summary, then y/N
python main.py --sync-send-log                    # record sends made from Claude Code (route b)
python main.py --ner                              # + named-entity extraction bonus (~6 min)
python main.py --dedup-mode literal               # no copy collapse: spec applied literally
python main.py --no-tz-collapse                   # keep folder-copy collapse, skip timezone stage
python main.py --mailboxes all --maildir tests/fixtures/real/maildir --db /tmp/fx.db   # any maildir
pytest                                            # 243 tests
```

Other flags (see `python main.py --help`):
- `--threshold` (default 90) and `--min-body-chars` (default 20)
- `--max-send` (default 10) and `--send-delay` (default 2 s)
- `--reset-db`, `--skip-ingest`, `--mcp-config`

Re-runs are safe: existing `message_id`s are skipped at insert, duplicate flags are recomputed
identically, and `notification_sent` is preserved, so nothing is notified twice.

---

## MCP server setup (Gmail)

The pipeline uses a **custom Python MCP server** ([mcp_server/gmail_smtp_server.py](mcp_server/gmail_smtp_server.py)),
built with the official MCP Python SDK. It exposes one tool, `send_email(to, subject, body, references,
original_to)`, and sends through Gmail SMTP (STARTTLS, port 587) with a Gmail App Password.
This is the "Custom MCP server (smtplib wrapper)" option in the assignment. Why we chose it, and
how it was built, is in [AI_USAGE.md](AI_USAGE.md#mcp-integration).

1. Turn on 2-Step Verification for the Gmail account and create an App Password at
   https://myaccount.google.com/apppasswords.
2. **Route (a), the pipeline calls the server through the MCP client SDK:**
   ```bash
   cp mcp_config.json.example mcp_config.json      # gitignored; fill in SMTP_USER / SMTP_PASS / SMTP_FROM
   python main.py --send-live --redirect-to you@gmail.com --max-send 1
   ```
   `pipeline/notify/mcp_client.py` starts the server over stdio and calls `send_email`. The pipeline
   refuses to send if any `<placeholder>` is still in the config.
3. **Route (b), Claude Code calls the tool:** create a project `.mcp.json` (gitignored) with the same
   `mcpServers.gmail` block as `mcp_config.json.example`, using absolute paths to `.venv/bin/python`
   and to the server script. Start a Claude Code session in the project folder and approve the `gmail`
   server. Then ask Claude to read `output/pending_notifications.json` and call `send_email`, and
   afterwards run `python main.py --sync-send-log`, which marks the send in the database.

Credentials are read from environment variables only (`SMTP_USER`, `SMTP_PASS`, `SMTP_HOST`,
`SMTP_PORT`, `SMTP_FROM`) and are never committed. `mcp_config.json`, `.mcp.json` and `.env` are in `.gitignore`.

---

## Architecture

```
data/maildir/<mailbox>/<folder>/<file>
  S1  discover      pipeline/discovery.py        selected mailboxes -> file list (filenames kept exactly, e.g. "45.")
  S2  parse         pipeline/parsing/*           decode -> headers -> addresses -> UTC date -> body split -> attachments
  S3  validate      pipeline/extract.py          missing mandatory field -> ParseFailure(reason)
  S4  load          pipeline/db.py               SQLite; INSERT OR IGNORE on message_id; normalized recipients
  S5  stats         pipeline/stats.py            counts + field completeness -> output/extraction_stats.json
  S6  copies        pipeline/copies.py           folder copies, then timezone-shifted copies -> is_copy = 1
  S7  dedup         pipeline/dedup.py            block -> fuzzy match vs anchor -> is_duplicate, duplicate_of, score
  S8  report        pipeline/report.py           duplicates_report.csv (generated from the DB flags)
  S10 entities      pipeline/entities.py         --ner only: spaCy PERSON/ORG/DATE/GPE -> entities table
  S11 notify        pipeline/notify/*            .eml drafts; live: summary -> y/N -> MCP send_email -> send_log.csv
  S12 summary       main.py                      console + output/run_summary.json
```

```
pipeline (main.py) --route a--> MCP client SDK --stdio--> gmail-smtp MCP server --SMTP--> Gmail -> test inbox
Claude Code        --route b--> MCP tool call  --stdio--> (same server)
```

### Project layout
```
main.py, config.py              entry point, flags and defaults
pipeline/                       discovery, parsing/, extract, db, stats, copies, dedup, report, ingest, notify/
mcp_server/                     gmail_smtp_server.py (MCP), smtp_send.py (SMTP, testable without MCP)
scripts/                        mailbox_counts.py, mailbox_profile.py (mailbox selection evidence)
tests/                          243 tests; fixtures/real (38 real emails), fixtures/synthetic, fixtures/expected
schema.sql, sample_queries.sql, mcp_config.json.example, requirements.txt
docs/                           live-send screenshots
```

---

## Mailbox selection

The assignment asks for 5+ mailboxes and 10k+ emails. Rather than picking by job title, we measured
11 candidates across 5 roles with `scripts/mailbox_profile.py` (read-only; results in
`output/mailbox_profile.csv`). All metrics except `raw` are computed after collapsing folder copies.

| mailbox | role | raw | unique | CC | fwd | `>` quoted | `<<att>>` refs | ≥90% matches | no To | 10+ recipients |
|---|---|---|---|---|---|---|---|---|---|---|
| **skilling-j** | executive | 4,139 | 2,585 | 20.3% | 13.5% | 5.3% | 118 | 85 | 14.0% | 15.1% |
| **sager-e** | legal | 5,200 | 3,255 | 26.0% | 42.0% | 3.5% | 348 | 153 | 3.7% | 8.8% |
| **arnold-j** | trader | 4,898 | 2,643 | 7.7% | 37.1% | 3.2% | 122 | 141 | 4.6% | 4.4% |
| **steffes-j** | policy | 3,331 | 3,274 | 31.1% | 59.0% | 4.2% | 799 | 40 | 3.7% | 12.2% |
| **farmer-d** | operations | 13,032 | 5,234 | 29.1% | 31.6% | 1.6% | 210 | 277 | 2.8% | 15.7% |

Why each mailbox was chosen:
- **skilling-j:** the most large recipient lists and the most quoting, plus 14% missing-To (exercises the failure path).
- **sager-e:** many forwarded chains and attachment references.
- **arnold-j:** short trader emails with many fuzzy matches.
- **steffes-j:** the heaviest forwarding, and almost no folder copies (a contrast case).
- **farmer-d:** repetitive logistics mail, which produces the most real duplicates.

Together: 30,600 raw files and 16,764 unique emails (target 12k–25k).

The other candidates measured were lay-k, haedicke-m, allen-p, grigsby-m, shapiro-r and beck-s (full table in `output/mailbox_profile.csv`).

**Why the pipeline shows 16,054 unique emails rather than 16,764.** The profile counts every readable
file, including 950 with no To header. 710 unique emails exist only in those files, and the pipeline
rejects them as `missing_to` (the spec makes To mandatory): 16,764 − 710 = 16,054. Both numbers come from
the same shared `pipeline.copies.copy_key()` function.

---

## Database

`schema.sql` creates:
- **`emails`:** every spec field; `message_id` UNIQUE; `is_duplicate`, `duplicate_of`, `similarity_score`, `notification_sent`, `notification_date`; plus `is_copy`, `copy_of`, `copy_kind` (copy collapse) and `thread_id` (reserved).
- **`addresses` + `email_recipients`:** To/Cc/Bcc are normalized, one row per address and one row per (email, address, type, position).
- **`attachments`**, **`parse_failures`** (mirrored to `error_log.txt`), and **`threads`** (reserved).
- **`entities`** (NER bonus): `email_id`, `text`, `label` (PERSON/ORG/DATE/GPE), `source` (body/forwarded/quoted)
  and character offsets; UNIQUE on (email, source, offsets, label).

Indexes: the required ones on `date`, `from_address` and `subject`, plus `(from_address, normalized_subject)`, `copy_key` and duplicate status.

`sample_queries.sql` has 10 queries, each with its expected output and the actual result on this database: emails per sender, a date range, emails with CC, the largest CC lists, top recipients, failures by reason, emails per year, duplicates with their originals, and two NER queries (top organizations/places in body text; search for every email that mentions FERC).

---

## Design decisions

### Parsing
- **Line endings.** Enron header lines end in CRLF and body lines in LF. Headers are read with the stdlib
  parser; we never split on a raw `"\n\n"`, which would read body lines as headers.
- **Addresses.** A small custom splitter instead of `getaddresses`, because Enron has many non-RFC forms
  (Lotus `Name/Org/Enron@ENRON`, `terry'.'ed@enron.com`, `'/o=enron/...'@enron.com`). They are kept as
  written, lowercased. Group syntax such as `undisclosed-recipients:;` yields no address.
- **Dates.** Converted to ISO-8601 UTC. `parsedate_tz` silently treats unknown zone abbreviations as UTC,
  so our own table (BST, CET, ...) is checked first.
- **Body split.** The first marker wins:
  - Lotus `---- Forwarded by` → `forwarded_content`
  - Outlook `-----Original Message-----` → `quoted_content`, or `forwarded_content` when the subject starts with `FW:`/`Fwd:`
  - `>` lines before the first marker → `quoted_content`

  Bodies are stored exactly as written; quoted-printable leftovers (`=20`, `=3D`) are cleaned only in
  the text used for similarity.
- **Attachments.** Detected from multipart/`name=` content types, Lotus `<<file.doc>>`, Outlook
  `<< File: x.xls >>` and Lotus ` - report.pdf` listings. `mailto:`/email-address `<< >>` entries are excluded.
- **Mandatory fields.** A missing Message-ID, Date (or an unparseable one), From, To or Subject header is a
  logged failure. An empty subject or empty body is accepted.

### Duplicate detection
- **Folder copies first.** The same email stored in several folders (`all_documents`, `discussion_threads`,
  `sent`, ...) has a *different* Message-ID in each file, so `message_id` uniqueness cannot catch it. A copy
  means the same raw From, same instant, same normalized subject and same whole-body hash. The canonical
  row is the smallest `source_file`; the others get `is_copy = 1`. This removes 13,596 copies.
- **Timezone-shifted copies.** Some emails appear in two exports with the timestamp shifted by whole hours
  (mostly 10 or 11). Rows with the same sender, normalized subject and identical body, in different folders,
  shifted by 1–12 whole hours with identical minutes:seconds, are marked `copy_kind = 'tz_shift'`. This
  merges 376 rows and reduces flagged duplicates from 798 to 436 (`--no-tz-collapse` gives the 798).
  48 whole-hour pairs with score 100 stay flagged because a condition fails: 31 are in the same folder
  (e.g. the ybarbo-p fixture) and 23 differ in the full body (some fail both). That is a deliberate,
  conservative choice: the rule only merges pairs that meet every condition.
- **Definition (spec).** Same `from_address`, same subject after stripping repeated `Re:`/`Fw:`/`Fwd:`
  prefixes, and body similarity ≥ 90 with `rapidfuzz.fuzz.ratio`. We use `fuzz.ratio` rather than a
  token-sorted scorer because word order matters for a re-send. 90 is the spec's minimum.
- **Comparison text.** The primary body, normalized. If it is under 20 characters (e.g. "FYI" or "yes"),
  `forwarded_content` is used instead; if that is also short, the email is excluded (520 excluded). The
  20-character floor stops near-empty bodies from scoring 100 against each other.
- **Anchor grouping.** Within each (sender, subject) block, emails are ordered by date. Each email joins
  the group whose earliest member (the anchor) it matches best at ≥ 90; otherwise it starts a new group.
  The anchor is the original and every other member is flagged with `duplicate_of = anchor`. Matching is
  against the anchor only, never chained through other members.
- **Determinism and ties.** Ordering is `(bogus_date, date, source_file)`. Equal scores go to the earlier
  anchor. Re-runs produce a byte-identical report.
- **Bogus dates.** 17 files carry `Mon, 31 Dec 1979 16:00:00 -0800`, a "zero date" placeholder
  (11 after collapse). Dates outside 1997-01-01 to 2003-01-01 sort after all real dates, so they are never
  chosen as the original. This affected one email, which is now flagged against its June 2001 copy.
- **Recurring automated emails are flagged, as the spec defines.** Daily or weekly messages with a fixed
  template meet the definition even though they are not accidental re-sends. Examples are
  `rickya@calpine.com` "Calpine Daily Gas Nomination" (23 flagged in one group) and marketing mail from
  `_corolla@response.etracks.com`. We keep them flagged rather than add a rule the spec does not ask for.

### Named-entity extraction (bonus, `--ner`)
- **What runs.** spaCy `en_core_web_sm` with every component except `tok2vec` and `ner` disabled, over
  `nlp.pipe` batches of 64. It processes the body, forwarded content and quoted content of the 15,678
  emails left after copy collapse, and keeps PERSON, ORG, DATE and GPE.
- **Where results go.** Results go to the `entities` table with a `source` column. Statistics use
  `source = 'body'` only, so quoted and forwarded copies of the same text aren't counted twice; search can
  use all three sources.
- **Input cleaning.** The input is the stored text with quoted-printable leftovers removed and line breaks
  kept, capped at 10,000 characters per field.
- **Isolation and re-runs.** The stage is isolated: if spaCy or the model is missing, or NER fails, the
  pipeline prints "NER skipped" and carries on. A re-run first deletes each email's old entity rows in the
  same transaction, so no duplicates are created.
- **List fix.** spaCy merges consecutive lines of a list into one entity (e.g. `CMS Marketing, Services and
  Trading Company` + `Calpine Energy Services`). Entities are split at line breaks **only when every piece
  has 2 or more words**, which fixes lists while keeping hard-wrapped names like `Kenneth\nLay` whole.
- **Full-run results:**
  - **Runtime:** 368 s (~6 min, 42.6 emails/s).
  - **Volume:** 343,291 entities in 14,732 emails. By label: PERSON 143,992, ORG 109,498, DATE 57,859,
    GPE 31,942. By source: body 142,153, forwarded 102,953, quoted 98,185.
  - **Top body ORGs:** Enron, FERC, HPL, EES, PG&E (with errors, see below).
  - **Top body PERSONs:** first names (Jim, Jeff, John), then `Daren J Farmer/HOU` and Elizabeth Sager.

### Notifications
- **Template.** The text follows the spec template exactly (a test compares it word for word).
- **Subject rule (no "Re: Re:").** The notice subject is built from the original email's subject. If it
  already starts with `Re:` (any case) it is used as written; otherwise `Re: ` is prepended.
  `Forecast` → `[Duplicate Notice] Re: Forecast`; `RE: Forecast` → `[Duplicate Notice] RE: Forecast`;
  an empty subject becomes `(no subject)`.
- **Drafts vs sends.** A `.eml` draft (`output/replies/reply_<sha256(message_id)[:16]>.eml`) is written
  for every flagged duplicate. Live mode sends only the latest duplicate of each group (spec 4.2).
- **Redirect.** Live sends go to a test inbox, as confirmed by the AISH team ("You can redirect to your
  own test inbox." from Ali). `--send-live` refuses to run without `--redirect-to`. Drafts keep the real
  Enron sender in `To:`. Live emails carry the real recipient in an `X-Original-To` header, and
  `send_log.csv` adds an `original_recipient` column after the spec's columns.
- **Safeguards.** Dry-run by default; a summary and y/N before sending; `--max-send` 10; `--send-delay` 2 s;
  every attempt logged; `notification_sent`/`notification_date` set only after a successful send; failed
  sends are retried on the next run.

---

## Testing

There are 243 `pytest` tests. They cover:
- every parser module, using small string cases (timezones, bogus years, stacked subject prefixes, group syntax, Lotus names, repeated or malformed headers, encodings)
- the database layer and statistics
- copy collapse and the timezone stage
- duplicate detection: the 90 threshold edge, the forwarded fallback, anchor-vs-chain, bogus dates, ties
- report-to-database consistency
- the notification sender against a fake MCP client: cap, abort on N, delay, logging, idempotency
- SMTP sending against a fake SMTP server
- real MCP round trips with the bundled server (no email sent)
- `main.py` end to end, run twice

**Real-email fixtures.** 38 emails from mailboxes *outside* the main 5, plus 1 synthetic re-send. Their
expected values are in `tests/fixtures/expected/` (see `INDEX.md`). They were AI-drafted and reviewed
through review flags, not manually verified line by line.

---

## Data facts worth knowing

- **Pure ASCII.** The CMU copy has 0 non-ASCII bytes in 517,401 files. Encoding junk is only
  quoted-printable or HTML leftovers, so decoding is covered by unit tests.
- **Bcc mirrors Cc** in every Enron file seen. `X-bcc`, `In-Reply-To` and `References` are never filled in (0%).
- **Aliases.** The same person appears under several addresses (e.g. `daren.farmer@` and `daren.j.farmer@`).
  Addresses are stored as written; there is no alias resolution.

## Known limitations and future work

- **Bonus challenges: one of five implemented.**

  | Bonus | Status | What exists / next step |
  |---|---|---|
  | Named-entity extraction | **Done** (`--ner`) | See "Named-entity extraction" above and its limitations below. |
  | Thread reconstruction | Not done | The `thread_id` column and `threads` table exist but stay empty. Since In-Reply-To and References are always empty, the planned rule is the same normalized subject, within 14 days, with at least one shared participant. Fixtures are written (F14a/b). |
  | Dashboard | Not done | Nothing built. |
  | Incremental processing | Not done | Re-runs are safe (existing `message_id`s are skipped and notification state is kept), but every file is re-parsed. Next step: skip known `source_file`s before parsing. |
  | Performance (full 517k dataset) | Not done | Only basic efficiency: 1,000-row batched inserts, dedup blocking by sender and subject, and a length pre-filter before fuzzy matching. Planned: a multiprocessing parse pool with a single SQLite writer, WAL mode, indexes built after load, and a serial-vs-parallel benchmark with an identical-output check. |

  `--no-incremental` and `--full-reingest` appear in `--help` but are reserved for incremental processing
  and currently have **no effect**.
- **NER limitations on messy email text** (spaCy's small model was trained on news and web text, not email):
  - **Fragments mislabelled.** Common words and fragments are mislabelled: `FYI` and `Daren` as ORG, `TX` as
    ORG (not GPE), `MMBtu` and `Subject` as PERSON, `Password` as PERSON, and URLs absorbed into ORG spans.
  - **Lotus routing suffixes.** Names keep their Lotus Notes routing suffix (`Daren J Farmer/HOU`,
    `John Arnold/HOU`), and first names alone (`Jim`, `Jeff`) dominate the PERSON counts. No name
    normalization or alias resolution is done.
  - **Legal suffixes.** These are often mislabelled: in `Calpine Energy Services, L.P.` the company is found
    as ORG but `L.P.` is tagged GPE.
  - **Line merging.** This is fixed only when every line has 2+ words; a one-word line (e.g. `Enron`)
    next to another entity can still be merged into it.
  - **Long fields.** Fields over 10,000 characters are truncated before NER.
  - **No accuracy figure.** There is no precision or recall measurement; quality was checked by spot-checking
    emails and by the F15 fixtures (which must find at least their listed entities).
- **Robustness run** on a whole unused mailbox was planned but not run.
- **No alias resolution**, so the same person under two addresses counts as two senders or participants.
