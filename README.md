# Enron Email Pipeline

> Full README (setup, MCP, architecture, results) is written at the end of the build (Plan step 21).
> Notes recorded during the build are collected below so nothing is lost.

## Design notes and known behaviours

### Duplicate detection
- **Recurring automated emails are flagged, as the spec defines.** A duplicate is the same sender +
  same normalized subject + body similarity >= 90%. Daily or weekly automated messages with a fixed
  template (e.g. `rickya@calpine.com` "Calpine Daily Gas Nomination", 23 flagged in one group; marketing
  mail from `_corolla@response.etracks.com`) meet that definition even though they are not accidental
  re-sends. We keep them flagged rather than adding a rule the spec does not ask for.
- **Timezone-shifted copies are merged before detection** (`--no-tz-collapse` disables this for a
  literal-spec comparison). Some emails appear in two exports of the same mailbox with the timestamp
  shifted by a whole number of hours (mostly 10 or 11). When two rows have the same sender, normalized
  subject and identical body, sit in different folders, and differ by 1-12 whole hours with identical
  minutes:seconds, the later one is marked `is_copy = 1, copy_kind = 'tz_shift'`. On the main 5 mailboxes
  this merges 376 rows and reduces flagged duplicates from 798 to 436. 48 whole-hour pairs with score 100
  remain flagged because a condition fails: 31 are in the same folder (e.g. the ybarbo-p fixture) and 23
  differ in the full body (e.g. trailing quoted text) while their comparison text is identical (some
  pairs fail both). Leaving them flagged is a deliberate, conservative choice: the rule only merges pairs
  that meet every condition, so it never hides a duplicate it cannot fully justify.

### Notifications
- **Subject rule (no "Re: Re:").** The notice subject is built from the original email's subject, as the
  template says. If that subject already starts with `Re:` (any case) it is used as written; otherwise
  `Re: ` is prepended. `Forecast` -> `[Duplicate Notice] Re: Forecast`; `RE: Forecast` ->
  `[Duplicate Notice] RE: Forecast`; an empty subject becomes `(no subject)`.
- **Live sends are redirected to a test inbox**, as confirmed by the AISH team ("You can redirect to your own
  test inbox." - Ali). `--send-live` refuses to run without `--redirect-to`. The dry-run `.eml` drafts keep
  the real Enron sender in `To:`. Each live email carries the real recipient in an `X-Original-To` header,
  and `send_log.csv` adds an `original_recipient` column after the spec's columns.
- **Drafts vs sends.** A `.eml` draft is written for every flagged duplicate; live mode sends only the latest
  duplicate of each group (spec 4.2), at most `--max-send` per run.
