-- Sample queries for data/enron.db
-- "Result" lines are from the main-5 database (skilling-j, sager-e, arnold-j,
-- steffes-j, farmer-d) after a full `python main.py --ner` run (2026-10-09), re-checked
-- against the database. Queries 1-7 count every stored row (29,650 emails), so folder copies
-- (is_copy = 1) are included; add `WHERE is_copy = 0` to count unique emails (15,678).

-- 1. Emails per sender (top 5).
-- Expected: one row per from_address with its count, largest first.
-- Result: john.arnold@enron.com 3481 | daren.farmer@enron.com 2812 |
--         elizabeth.sager@enron.com 2526 | d..steffes@enron.com 1383 | mjones7@txu.com 1063
SELECT from_address, COUNT(*) AS emails
FROM emails
GROUP BY from_address
ORDER BY emails DESC, from_address
LIMIT 5;

-- 2. Emails in a date range (October 2001, UTC). Uses idx_emails_date;
--    ISO-8601 text sorts chronologically, so plain string comparison works.
-- Expected: a single row with the count and the first/last timestamp inside the range.
-- Result: 2434 | 2001-10-01T02:14:35Z | 2001-10-31T23:55:52Z
SELECT COUNT(*) AS emails_oct_2001, MIN(date) AS first, MAX(date) AS last
FROM emails
WHERE date >= '2001-10-01T00:00:00Z' AND date < '2001-11-01T00:00:00Z';

-- 3. Emails that have CC recipients, via the normalized recipient table.
-- Expected: the number of distinct emails with at least one 'cc' row.
-- Result: 7340 (24.8% of parsed emails, matching the cc_addresses completeness)
SELECT COUNT(DISTINCT e.id) AS emails_with_cc
FROM emails e
JOIN email_recipients r ON r.email_id = e.id
WHERE r.recipient_type = 'cc';

-- 4. Emails with the largest CC lists.
-- Expected: source_file and number of CC recipients, largest first.
-- Result: maildir/skilling-j/inbox/1010. 174 | maildir/steffes-j/california_issues/western_gas/7. 108 |
--         maildir/sager-e/all_documents/1891. 92
SELECT e.source_file, COUNT(*) AS cc_count
FROM emails e
JOIN email_recipients r ON r.email_id = e.id
WHERE r.recipient_type = 'cc'
GROUP BY e.id
ORDER BY cc_count DESC, e.source_file
LIMIT 3;

-- 5. Most frequent To recipients (one address row shared by every email it appears in).
-- Expected: address and number of emails it was sent to, largest first.
-- Result: daren.farmer@enron.com 4855 | elizabeth.sager@enron.com 1750 | jeff.skilling@enron.com 1743 |
--         earl.tisdale@enron.com 1661 | daren.j.farmer@enron.com 1514
--         (note the two aliases of Daren Farmer: addresses are stored as written)
SELECT a.email, COUNT(*) AS received
FROM email_recipients r
JOIN addresses a ON a.id = r.address_id
WHERE r.recipient_type = 'to'
GROUP BY a.id
ORDER BY received DESC, a.email
LIMIT 5;

-- 6. Parse failures by reason (mirrors error_log.txt).
-- Expected: one row per failure reason.
-- Result: missing_to 950
SELECT reason, COUNT(*) AS files
FROM parse_failures
GROUP BY reason
ORDER BY files DESC;

-- 7. Emails per year: a quick sanity check on date parsing.
-- Expected: most mail in 2000-2001.
-- Result: 1980 17 | 1998 3 | 1999 778 | 2000 13679 | 2001 15066 | 2002 107
--         (the 17 rows in 1980 carry bogus dates in the source files and are kept as written)
SELECT substr(date, 1, 4) AS year, COUNT(*) AS emails
FROM emails
GROUP BY year
ORDER BY year;

-- 8. Flagged duplicates and their originals (populated by the dedup stage).
-- Expected: one row per flagged email with the original it duplicates and the score.
-- Result: 436 rows (one per flagged duplicate, same as duplicates_report.csv). First row:
--         <3308296.1075852669757...> 2001-10-02T10:49:07Z -> <2852567.1075852669803...>
--         2001-10-02T10:31:35Z | 99.74 | notification_sent 1 (one of the two live sends)
SELECT d.message_id AS duplicate_message_id, d.date AS duplicate_date,
       o.message_id AS original_message_id, o.date AS original_date,
       d.similarity_score, d.notification_sent
FROM emails d
JOIN emails o ON o.message_id = d.duplicate_of
WHERE d.is_duplicate = 1
ORDER BY d.from_address, d.date;

-- 9. (NER bonus) Most-mentioned organizations and places in BODY text only (statistics use body only,
--    so quoted/forwarded copies of the same text are not counted twice). Requires `python main.py --ner`.
-- Expected: label, entity text, number of distinct emails mentioning it, largest first.
-- Result: ORG Enron 1435 | GPE Houston 688 | ORG Daren 482 | GPE Texas 466 | ORG FYI 434 | ORG FERC 376
--         ("Daren" and "FYI" tagged ORG are model errors; see README limitations)
SELECT label, text, COUNT(DISTINCT email_id) AS emails
FROM entities
WHERE source = 'body' AND label IN ('ORG', 'GPE')
GROUP BY label, text
ORDER BY emails DESC
LIMIT 6;

-- 10. (NER bonus) Search: emails that mention FERC anywhere (body, forwarded or quoted text).
-- Expected: matching emails with date and subject; the second query shows where the mentions sit.
-- Result: first rows from steffes-j sent_items/532. 2001-08-08 "RE: California Refund Proceeding...",
--         550. "RE: meeting with FERC on MA rule", 559. "RE: Negative CTC at FERC"
--         Totals: 749 emails; mentions body 893 | forwarded 488 | quoted 1012
SELECT e.source_file, e.date, e.subject
FROM emails e
WHERE e.id IN (SELECT email_id FROM entities WHERE label = 'ORG' AND text = 'FERC')
  AND e.from_address LIKE '%steffes%'
ORDER BY e.date
LIMIT 3;

SELECT COUNT(DISTINCT email_id) AS emails,
       SUM(source = 'body') AS in_body, SUM(source = 'forwarded') AS in_forwarded, SUM(source = 'quoted') AS in_quoted
FROM entities
WHERE label = 'ORG' AND text = 'FERC';
