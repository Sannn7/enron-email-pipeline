# Fixture expected values

**Status: AI drafted, reviewed by flags, not manually verified line by line.** The user decided the open rules below; every other value was accepted as drafted.

## Decided rules
- Body split: first marker wins. Outlook '-----Original Message-----' -> quoted_content, unless the subject starts with FW:/Fwd:, then forwarded_content. Lotus 'Forwarded by' -> forwarded_content. '>' lines before the first marker -> quoted_content.
- Bodies are stored exactly as written. Quoted-printable artifacts (=20, =3D, =09, soft line breaks) are cleaned only in the normalized text used for similarity and NER.
- Malformed addresses are kept exactly as written, lowercased.
- Dedup compares the normalized primary body; if it is under 20 chars, it compares normalized forwarded_content; if that is also under 20 chars, the email is excluded.
- NER expectations are 'at least these' (labels PERSON, ORG, DATE, GPE). NER itself is dropped for the deadline.

## Conventions
Dates are ISO-8601 UTC (`Z`); addresses are lowercased in original order; empty X-headers are null; `body`/`forwarded_content`/`quoted_content` are checked with starts_with / ends_with / length after strip(), except where an exact body is given. Raw files: `tests/fixtures/real/maildir/`; the synthetic re-send: `tests/fixtures/synthetic/maildir/`.

| id | category | files | status | flags |
|---|---|---|---|---|
| F00_clean_baseline | Clean baseline | 1 | ok | 1 |
| F01_folded_to_long_list | Folded To + long recipient list + 'Last, First' names | 1 | ok | 2 |
| F02_missing_to | Missing To (failure) | 1 | failed | 1 |
| F02b_missing_to_with_to_in_body | Missing To (failure) + header/body boundary | 1 | failed | 1 |
| F04_non_rfc_addresses | IMCEANOTES / non-RFC addresses | 1 | ok | 2 |
| F05_bcc | BCC present | 1 | ok | 1 |
| F06_lotus_forward | Lotus 'Forwarded by' forward | 1 | ok | 0 |
| F07_outlook_reply_chain | Outlook 'Original Message' reply chain | 1 | ok | 1 |
| F08_nested_forward | Nested forward | 1 | ok | 2 |
| F09_gt_quoted | '>' quoted reply | 1 | ok | 0 |
| F10_attachments | <<attachment>> references | 1 | ok | 0 |
| F10n_attachments_negative | <<attachment>> references (negative case) | 1 | ok | 1 |
| F11_encoding_junk | Encoding junk | 1 | ok | 2 |
| F12_short_body | Empty or very short body | 1 | ok | 1 |
| F13r_synthetic_resend | Dedup: re-send pair (SYNTHETIC) | 2 | ok | 2 |
| F13a_near_miss | Dedup: ~85% near miss (should NOT flag) | 2 | ok | 1 |
| F13b_folder_copies | Dedup: folder copy group (3 copies) | 3 | ok | 1 |
| F13c_forwarded_fallback | Dedup: short primary body -> compare forwarded_content | 2 | ok | 1 |
| F13x_timezone_edge_case | Dedup: timezone edge case (flagged by the spec) | 2 | ok | 1 |
| F14a_reply_chain | Thread: reply chain | 8 | ok | 1 |
| F14b1_window | Thread: generic subject outside the 14-day window | 2 | ok | 0 |
| F14b2_alias_limitation | Thread: ALIAS LIMITATION case | 2 | ok | 1 |
| F14b3_unrelated_people | Thread: generic subject, genuinely different people | 2 | ok | 1 |
| F15a_ner_orgs | NER-rich body (organizations) | 1 | ok | 1 |
| F15b_ner_people_places | NER-rich body (people, places, orgs) | 1 | ok | 1 |
