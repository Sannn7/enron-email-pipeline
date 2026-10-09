# AI Tool Usage

## Tools used

I used two AI tools, each with a separate job.

1. **Claude Code** (the Code tab of the Claude desktop app on macOS, running Claude Opus 5.5, `claude-opus-5-5`) for all implementation. Inside the project, Claude Code wrote the code, ran the tests and the pipeline, and inspected the dataset. The Claude Code CLI isn't installed on this machine, so the desktop app was the only coding tool.
2. **Claude chat** (claude.ai, Claude Opus 5.5) as a planning and review assistant. I hadn't used an agentic coding tool for a project like this before, so I used a separate chat to learn how to structure prompts, to review Claude Code's plans and results before approving them, and to help draft prompts, which I then adjusted and sent.

My role was to direct the project: I set the requirements, made the design decisions, reviewed each step's output before approving the next one, ran the installs, set up the Gmail credentials, and ran and confirmed every live send myself.

Environment: Python 3.13, `mcp` 1.30.0, `rapidfuzz` 3.14.6, `pytest` 9.1.1.

## Prompting strategy

**Plan first, then build one step at a time.** I didn't paste the spec and ask for code. My first prompt asked Claude Code for a project structure, the architecture, testable steps, and a list of everything ambiguous, with no code. It came back with 13 open decisions (D1 to D13). I went through each one, chose an option, and added four follow up requirements of my own. The plan was saved to `PLAN.md` so every later session could refer to it. After that, every build prompt followed the same rule: build the step and its tests, run them, show me the output, and stop for my go ahead.

I stopped for a full review at the three points where a mistake would be expensive: the database schema (everything else depends on it), duplicate detection (the core logic), and any live email send (it can't be undone).

**Ask for evidence instead of conclusions.** Whenever Claude Code proposed something based on assumptions, such as which mailboxes to use or which emails to use as tests, I asked it to measure on the real data first and show me the numbers.

**Repeat the important constraints.** In almost every prompt: no live email without my explicit y/N, don't read credential files, don't change code just to make a number match, and report the actual test results.

### Example prompts

1. **Planning before code.** This was my opening prompt, with the spec attached:
   > "1. Don't write any code yet. 2. i want you to structure the entire project 3. give the architecture of the workflow from the beginning — pipeline stages, how data flows etc till the end 4. break the work into steps, these steps should be testable individually 5. flag the steps or components of the workflow which is ambiguous for you, ask me what to do there 6. If you feel there are multiple options to solve any problem then give me the options i will select them …"

   *Why I structured it this way:* the spec hides a lot of choices (folder copies, who gets notified, threshold edge cases). Getting them listed as decisions before any code meant the code was written once, against rules I had agreed to. My first draft of this prompt mixed questions and planning together; I split it so the plan wouldn't be built on the AI's guesses.

2. **Choosing mailboxes by measurement, not job titles.**
   > "Before I confirm the main 5 mailboxes, I want the selection based on measured criteria, not job titles alone … Total between 12,000 and 25,000 emails AFTER collapsing folder copies … Measure this, don't estimate … Shortlist about 10 candidate mailboxes across the 5 roles … Compute the metrics above for each with a quick script (read only, nothing written to the database)."

   *Why:* Claude Code's first suggestion was two executives and two traders, picked by title, which overlapped heavily. The spec asks us to justify the selection, so I wanted one mailbox per type of email behaviour, backed by numbers. This produced `scripts/mailbox_profile.py` and the selection table in the README. I chose skilling-j over lay-k because it scored higher on the edge cases I cared about (large recipient lists, quoting, fuzzy matches, missing To).

3. **Test fixtures from mailboxes the parser wasn't built around.**
   > "pick 20 to 30 genuinely messy real emails from mailboxes NOT in our main 5, so we test on data the parser wasn't built around. For each one, we write down the expected parsed output and I will manually verify those expected values before they become tests."

   *Why:* tests written on the same mailboxes the parser was tuned on prove very little. When the candidate list grew to 32 categories, I cut it to 16 real fixtures, moving simple cases like timezones and subject prefixes into small string based unit tests, so the set stayed small enough to review. Because of the deadline, I didn't verify every expected value line by line in the end. They are honestly labelled "AI drafted, reviewed by flags" in `tests/fixtures/expected/INDEX.md`.

4. **Copy collapse and dedup, with "don't force the numbers".**
   > "Reuse the exact copy definition from mailbox_profile.py through a shared function. Do not reimplement or modify the definition … Compare the pipeline's unique email count with the profile's 16,764. If they differ, investigate and explain why instead of adjusting code to force a match."

   *Why:* the README numbers have to agree with the pipeline output. They did differ (16,054), and because of this instruction the gap was traced to 710 emails that only exist in files with no To header, rather than the definition being tweaked until it matched.

5. **Notifications and MCP, with the safety rules written into the prompt.**
   > "Dry-run is the default … Live mode (--send-live): sends only the latest duplicate per group, requires --redirect-to, prints a summary of how many emails go to whom, and waits for y/N … Test the sender against a fake MCP server: cap, abort on N, delay, log, idempotency … Do NOT send any live email yet."

   *Why:* sending real email is the one irreversible action in this project, so I wanted every safeguard built and tested before a credential even existed.

## Decisions I made along the way

These are the main calls I made. In most cases Claude Code laid out options and tradeoffs, and I chose.

1. **Folder copies (D2).** I verified myself that the same email sits in two farmer-d folders with different Message-IDs, then chose to collapse same timestamp copies before dedup instead of following the spec literally, because a stored copy isn't a re-send. A flag keeps the literal behaviour available.
2. **Grouping method (D3).** I chose the anchor method over chaining because chaining can group emails that are only 85% similar to the original, which breaks the spec's 90% rule.
3. **Live recipients (D7).** The real recipients are old Enron addresses, so before building live mode I emailed the AISH team to ask whether to redirect. Ali confirmed I could redirect to my own test inbox, so `--redirect-to` is mandatory in live mode and both live sends went to my own Gmail.
4. **Both MCP routes (D6).** I chose to support the pipeline calling MCP programmatically and Claude Code calling `send_email` directly, because section 4.4 asks for prompts showing the AI using the tool.
5. **The timezone artifact.** When Claude Code reported that about half the flagged duplicates were the same email exported with a 10 or 11 hour offset, I treated it like the folder copy problem. I asked for it as a separate, switchable stage with strict conditions (different folders, identical body, whole hour shift of 12 or less, matching minutes and seconds), so it wouldn't break the copy definition shared with the profile script.
6. **Scope under deadline.** I started out aiming for all five bonuses, then cut NER, the dashboard and the full dataset run once the deadline was clear, so the core pipeline and every required deliverable were done properly. They're listed in the README as future work.
7. **Not sending everything.** I verified live mode with two capped sends to a test inbox instead of sending all 301 notifications. The full set exists as dry-run drafts in `output/replies/`.

## Iterations and debugging

1. **CRLF headers broke the fixture search.** Claude Code's first scripts for finding test emails split each file into headers and body on `"\n\n"`. Enron header lines end in `\r\n` while body lines end in `\n`, so the split landed inside the body and body lines were read as headers. Four fixture picks were wrong because of it: an email that seemed to have Lotus names in its To line actually had no To header at all (those lines were a forwarded block), an "empty body" email had two lines, and an "IMCEANOTES address" was only in the body. A supposed 100% re-send pair turned out to score 83.9 on the full body, so it became the near miss test instead. **Fix:** all parsing moved to the standard library email parser, the picks were replaced, and a regression test (`test_crlf_header_lf_body_boundary`) was added.

2. **Unknown timezones were silently treated as UTC.** A unit test for `"... 10:00:00 BST"` failed. The code assumed `email.utils.parsedate_tz` returns `None` for an unknown zone, but it actually returns offset 0, so BST was parsed as UTC with no error. **Fix:** check our own timezone table before trusting `parsedate_tz`. This is the kind of silent bug that would have quietly corrupted dates without the test.

3. **Expected values broke our own "store as written" rule.** Two fixtures failed because the AI had collapsed double spaces and a tab when drafting expected header values, while the parser kept headers exactly as written. I decided the parser was right, since the spec asks for the full subject line and I'd chosen to store values as written, so the two expected files were updated.

4. **Half the flagged duplicates were an export artifact.** The first dedup run flagged 798 emails. Many pairs scored 100 and were exactly 10 or 11 hours apart in different folders. I chose the strict, switchable timezone stage described above (`--no-tz-collapse` turns it off), which brought the count to 436. The README documents the 48 borderline same folder pairs I left flagged as a conservative choice.

5. **Lost context between tools.** At one point I told Claude Code to use "the 24 categories I gave you earlier", but that list only existed in my planning chat, so Claude Code had never seen it. It said so instead of guessing, and proposed its own list, which was actually stronger on header edge cases. I merged the two. Lesson: Claude Code only knows what's in its own session and files.

6. **MCP setup issues.** `pip` pulled `mcp` 2.3.0, a new major version, while the code was written for 1.x, so I pinned `mcp>=1.2,<2`. The first live run stopped because the config still had placeholder values, and the pipeline's guard caught it before anything was sent.

## What I wrote vs what the AI wrote

| Part | Who |
|---|---|
| Requirements, the 13 planning decisions, follow up requirements, scope cuts, mailbox and fixture selection, rule choices (timezone stage, forwarded fallback, body split, store as written, redirect) | Me, choosing between options the AI laid out and adding my own requirements |
| Reviewing each step's output, approving or pushing back, deciding when to stop adding checks | Me |
| Gmail App Password, credential files, package installs, both live sends and their confirmation, screenshots | Me |
| Prompts | Drafted with help from my planning chat, then adjusted and sent by me |
| Python code (pipeline, MCP server and client, scripts), SQL schema and queries, tests, draft fixture expected values, first drafts of README and AI_USAGE | AI (Claude Code), prompted and reviewed by me |

In lines of code, the AI wrote roughly 95%. My work was directing the project: the decisions, the review, the verification and the scoping.

## Lessons learned

1. **Planning before code paid off.** Listing the decisions up front meant almost nothing had to be rewritten. The cost was a long first exchange, which was worth it.
2. **Ask for evidence, not conclusions.** "Measure, don't estimate" and "investigate instead of forcing a match" were my most useful instructions. They surfaced the 710 email gap, the CRLF problem and the timezone artifact.
3. **The AI is confident about data it hasn't looked at.** Its first fixture picks came from a buggy quick script. Next time I'd ask for raw samples earlier.
4. **Tests caught real bugs** (the timezone fallback and the whitespace mismatch) before the real run.
5. **More checking isn't always better.** I let the fixture work grow past what the assignment needed and had to cut it back under deadline pressure. Knowing when a check is good enough is part of the job.
6. **Context doesn't travel between tools.** Anything decided in one tool has to be written into the project (PLAN.md) or the prompt, or the other tool simply won't know it.
7. **Harder than expected:** the Enron data itself (CRLF/LF mix, copies with different Message-IDs, timezone shifted exports, bogus 1980 dates, address aliases) and MCP setup details (version pin, Claude Code config scope, interactive prompts).
8. **Credentials need care in an AI session.** The App Password ended up visible to the AI tools while I was setting it up. It was never committed to the repo, and I rotated it after setup.

---

## MCP integration

### Which server and why

A **custom Python MCP server**, [`mcp_server/gmail_smtp_server.py`](mcp_server/gmail_smtp_server.py), built with the official MCP Python SDK (`FastMCP`). It exposes one tool:

```
send_email(to, subject, body, references="", original_to="") -> "sent <message-id> to <to>"
```

The SMTP part lives in [`mcp_server/smtp_send.py`](mcp_server/smtp_send.py): STARTTLS to `smtp.gmail.com:587` with a Gmail App Password. `references` sets `References` and `In-Reply-To`, and `original_to` sets `X-Original-To`, since every live send is redirected to a test inbox.

I chose this over the listed Node and Docker servers for four reasons:

1. **One language.** The whole project stays in Python, with no Node or Docker.
2. **Simple auth.** An App Password needs no Google Cloud OAuth setup, which can eat hours.
3. **Testable.** The SMTP part is tested against a fake SMTP class, and the MCP tool against the real server without sending.
4. **Full control.** We could add the `original_to` header and the placeholder guard.

### Setup, step by step

1. **App Password:** turn on 2-Step Verification for the Gmail account and create an App Password at https://myaccount.google.com/apppasswords.
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt   # includes mcp>=1.2,<2
   ```
3. **Route (a), pipeline to MCP:**
   ```bash
   cp mcp_config.json.example mcp_config.json   # gitignored
   ```
   Fill in `SMTP_USER`, `SMTP_PASS` and `SMTP_FROM`. The client (`pipeline/notify/mcp_client.py`) starts the server over stdio with those environment variables and calls `send_email`.
4. **Route (b), register the server with Claude Code:** add a project scoped `.mcp.json` (gitignored) in the repo root:
   ```json
   {"mcpServers": {"gmail": {
       "command": "/abs/path/AISH/.venv/bin/python",
       "args": ["/abs/path/AISH/mcp_server/gmail_smtp_server.py"],
       "env": {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587",
               "SMTP_USER": "<your_gmail_address>", "SMTP_PASS": "<app_password>",
               "SMTP_FROM": "<your_gmail_address>"}}}}
   ```
   Then start a new Claude Code session with the project folder as its working directory, approve the `gmail` server when asked, and check that `send_email` appears as a tool (`mcp__gmail__send_email`).

### How I prompted the AI to use `send_email`

**Route (a), the pipeline.** I ran this in the terminal and answered the y/N prompt myself:
```bash
python -m pipeline.notify.run --send-live --max-send 1 --redirect-to sanikakillekar7@gmail.com
```
`python main.py --send-live ...` does the same.

**Route (b), Claude Code calling the tool directly.** In a new Claude Code session with the server loaded, I sent:
> "Read output/pending_notifications.json and take the FIRST entry. Use the gmail MCP server's send_email tool to send it with: to = sanikakillekar7@gmail.com, subject = the entry's subject, body = the entry's body, references = the entry's references, original_to = the entry's original_to. Then append one row to output/send_log.csv with columns timestamp (UTC, ISO format ending in Z), recipient, subject, message_id_referenced (= references), status (sent or failed), error_message, original_recipient (= original_to). Show me the tool call and its result."

Before sending, Claude Code pointed out that the first entry had already been sent by the pipeline, proposed the next unsent entry instead, and showed me the exact tool call. It waited for my explicit "Yes, send it." It then called `mcp__gmail__send_email(to="sanikakillekar7@gmail.com", original_to="_corolla@response.etracks.com", subject="[Duplicate Notice] Re: Fall with a Twist", references="<8458892.1075852667397.JavaMail.evans@thyme>", body=…)`, and the result was `sent <…@gmail.com> to sanikakillekar7@gmail.com` (screenshot: [`docs/live_send_claude_code.png`](docs/live_send_claude_code.png)). Afterwards, `python main.py --sync-send-log` set `notification_sent` for that duplicate, so neither route will notify it again.

### Issues and how they were resolved

| Issue | Resolution |
|---|---|
| `pip install mcp` pulled 2.3.0 | Pinned `mcp>=1.2,<2` (1.30.0 installed) and updated `requirements.txt` |
| First live run: `mcp_config.json` still had placeholder values | The client refuses to start the server while any placeholder remains. I fixed the file and re-ran. Nothing was sent |
| Typed "y" in the chat instead of the terminal at the y/N prompt | Answered in the terminal tab. The confirmation is deliberately interactive and can't be bypassed by the AI |
| Live sends would go to dead Enron addresses | Asked the AISH team, who approved redirecting to my own test inbox. `--redirect-to` is mandatory, and the real recipient is kept in `X-Original-To` and `send_log.csv` |
| Claude Code reads `.mcp.json` from the folder a session starts in | My original session had started in a different folder, so I started a new session in the project folder. Absolute paths make sure the venv's `mcp` is found |
| Route (b) sends bypass the pipeline's database update | `--sync-send-log` reads `send_log.csv` and sets `notification_sent` and `notification_date` |

### Proof of successful live sends

`output/send_log.csv`:
```
timestamp,recipient,subject,message_id_referenced,status,error_message,original_recipient
2026-10-09T15:09:57Z,sanikakillekar7@gmail.com,[Duplicate Notice] Re: All The Color Of The Season,<3308296.1075852669757.JavaMail.evans@thyme>,sent,,_corolla@response.etracks.com
2026-10-09T15:29:59Z,sanikakillekar7@gmail.com,[Duplicate Notice] Re: Fall with a Twist,<8458892.1075852667397.JavaMail.evans@thyme>,sent,,_corolla@response.etracks.com
```

Pipeline terminal output after answering `y`:
```
Proceed? [y/N] y
  [sent] <3308296.1075852669757.JavaMail.evans@thyme>
live result: {'pending': 301, 'attempted': 1, 'sent': 1, 'failed': 0, 'aborted': False}
```

Screenshots:

1. [`docs/live_send_pipeline.png`](docs/live_send_pipeline.png): route (a), the email received in Gmail
2. [`docs/live_send_claude_code.png`](docs/live_send_claude_code.png): route (b), the tool call and result
3. [`docs/live_send_claude_code_email.png`](docs/live_send_claude_code_email.png): route (b), the email received in Gmail