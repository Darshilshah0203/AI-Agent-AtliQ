# PRD: AtliQ Morning Digest Agent

**Product owner:** Peter Pandey  
**Primary stakeholder:** Bruce Haryali  
**Project type:** Local Windows pilot  
**Status:** Product requirements defined, ready for implementation planning

## 1. Overview

Build a Python agent that runs on Peter's Windows laptop at 8:00 AM each morning. It checks newly available complete-day sales data, identifies material sales drops and customers that have stopped ordering, sends escalation emails with short Word reports, and sends a weekly company-wide digest once the latest Monday-to-Sunday week is complete.

The agent is not a dashboard. The email itself must provide the essential information in under two minutes. The Word attachment is a consistent, forwardable record.

**Core rule:** Code identifies issues and calculates every number. AI explains the evidence and writes the narrative. AI does not choose recipients, calculate business metrics, or send email.

## 2. Goals and non-goals

### Goals
- Detect material market-and-channel sales drops and customers with zero orders.
- Explain likely causes using evidence from the approved sales view.
- Escalate persistent issues through the specified owner hierarchy.
- Deliver phone-friendly HTML and plain-text emails with matching Word attachments.
- Send one weekly digest to each stakeholder when a complete week is available.
- Make runs observable, retryable, and safe against duplicate real-world delivery.
- Keep the implementation small, readable, local, and suitable for a non-developer to operate.

### Non-goals
- Dashboard or web application.
- Cloud-hosted execution.
- Per-region weekly digests.
- Replacing the specified database, email provider, AI provider, or technology stack.
- Automatic correction emails to real recipients during the pilot.

## 3. Users and stakeholders

- **Peter Pandey / operator:** Runs and monitors the agent on a Windows laptop and reviews logs and generated files.
- **Bruce Haryali:** Receives the initial weekly digest and serves as the primary executive stakeholder.
- **Sales owners:** Receive daily drop alerts based on the `owners` hierarchy.
- **Other stakeholders:** Receive company-wide weekly digests based on `stakeholders.csv` and their individual private briefs.

Adding a stakeholder requires adding a row to `stakeholders.csv` and providing that person's private Google Doc. It must not require a code change.

## 4. Runtime and data freshness

### 4.1 Daily schedule
- Windows Task Scheduler starts the agent at 8:00 AM.
- The agent processes complete days only.
- `settings.as_of_date` is the last complete date the agent may analyze.
- The agent may advance `as_of_date` to the newest order date, but never beyond yesterday.
- All daily and weekly eligibility decisions use `as_of_date`, not the system clock.
- On the first run, begin at the stored `as_of_date`. Do not send historical alerts or digests automatically.
- Historical replay is explicit through `--day YYYY-MM-DD` and `--week YYYY-MM-DD`.

### 4.2 Advancing `as_of_date`
- Use `agent_ingest` only for the plain-code step that reads the newest date from `sales_orders` and updates `settings.as_of_date`.
- Do not let the AI update settings.
- Do not advance the date beyond yesterday.
- If no newer eligible order date exists, retain the current date.
- Log the data-freshness step in `run_log`.

### 4.3 Sequential processing
- Process each newly eligible day in date order.
- A failed daily check blocks later daily checks until the failed day is successfully resolved. This preserves consecutive-day escalation logic.
- Independent jobs may continue where their prerequisites are satisfied. In particular, weekly digest processing may continue if its required complete-week data is available.
- A failed check is not evidence that the incident stopped. Do not infer continuity or resolution from a failed run.
- Retry failed jobs on the next scheduled run.
- `--day` must be rejected if its date is after `as_of_date`.
- `--week` must be rejected if the requested week's Sunday is after `as_of_date`.
- The agent must never analyze today.

## 5. Daily alert detection

### 5.1 Market-and-channel sales drop
For each eligible date and market/channel:
1. Calculate that day's net sales.
2. Calculate the baseline as the median net sales for the same weekday over the prior four weeks.
3. Skip the check if all four historical comparison weeks are not available.
4. Only consider a baseline of at least $5,000.
5. Trigger an alert only when the decline is strictly greater than 30%. A decline of exactly 30% does not trigger.
6. Code performs all calculations and determines whether an alert fires.

### 5.2 Customer stopped ordering
For each eligible date and customer:
1. Determine whether the customer placed zero orders on that date. The source view may not contain a row for zero-order customers, so code must derive zero-order status by comparing expected customers with that day's observed orders.
2. Calculate the customer's baseline using the median for the same weekday over the prior four weeks.
3. Only consider customers with a baseline of at least $5,000.
4. A customer with reduced but non-zero orders does not receive a standalone customer alert.
5. Code determines the condition and calculates all values.

### 5.3 Combined and standalone alerts
- If a market-and-channel drop and a zero-order customer occur in the same market, channel, and date, send one combined alert naming the customer.
- If only the customer condition fires, send a standalone alert to the resolved market/channel owner.
- Resolve the recipient using `owners`: market plus channel first, then market, then regional head.
- The AI must never select or change the recipient.

### 5.4 Escalation
- A persistent issue is labelled day 1, day 2, day 3, and so on, based on consecutive calendar days for which the issue remains present.
- On day 1, send to the resolved owner.
- On day 2, copy the next owner level up once.
- On day 3 and later, do not continue climbing the hierarchy. Keep the original owner and copy only the next level up.
- If the resolved owner is already the region head, there is no higher-level copy recipient.
- The agent must reconstruct incident continuity from the existing database records and deterministic checks. A failed daily check must not count as either a continuing incident or a resolved incident.
- Do not add a separate incident-state file, ledger, or database table. `run_log` and `settings.as_of_date` remain the only persisted agent state.
- If the existing records cannot establish the correct escalation day unambiguously, do not guess. Log the ambiguity and send the alert with the safest supported escalation information, marking the escalation level as unconfirmed in the report. This fallback is an implementation safeguard because the current schema does not define a dedicated incident-history ledger.

## 6. Cause analysis

### 6.1 AI role
- The AI investigates likely causes but does not calculate final business metrics or determine alert eligibility.
- Start with a comparison to the same weekday last week, first by customer, then by product.
- The AI can use one tool: write a single SQL `SELECT` against `v_sales_daily`.
- Code obtains the view's column list and formulas from `data/data_dictionary.md`.
- Each generated query must be validated before execution:
  - Exactly one `SELECT` statement.
  - Read only from `v_sales_daily`.
  - No other tables, views, stored procedures, or write operations.
  - Maximum 30 result rows, even if the AI requests more.
  - Query timeout of 3 seconds.
  - Execute using `agent_ro`.
- The model makes one tool call at a time.
- Limit the investigation loop to about 8 steps per drop investigation and 10 steps per digest.
- Validate the AI's final answer for required fields and word limits before using it.
- If the AI fails or cannot establish a credible cause, send the report with the factual numbers and a clear statement that analysis is incomplete. If there is partial evidence, explain it as partial evidence and do not state it as proven causation.
- Retry Groq rate-limit responses using the provider's stated wait time, up to 3 retries. Keep prompts and returned data compact.

### 6.2 SQL safety
- Use a read-only database account for all analysis queries.
- The only permitted update is the plain-code `as_of_date` update using `agent_ingest`.
- Do not execute AI-generated SQL until validation has passed.
- Never allow AI output to determine recipients, thresholds, escalation rules, send status, or delivery actions.

## 7. Weekly digest

### 7.1 Eligibility
- Send a weekly digest once the latest Monday-to-Sunday week is fully available through `as_of_date`.
- The digest covers the whole company and is sent to each person in `stakeholders.csv`.
- Do not send a digest for historical weeks on the first run. Use `--week` for explicit replay.
- Each stakeholder receives the same calculated company scorecard but may receive a differently prioritized narrative based on their private brief.

### 7.2 Scorecard
Include:
- Net sales.
- Gross margin percentage.
- Gross margin dollars.
- Units sold.
- Week-over-week change for each of the above.
- Compare net sales with its target. Do not invent targets for gross margin percentage, gross margin dollars, or units.
- Calculate margin-dollar change as the money impact.
- Calculate monthly impact if the same change continues as `change in gross margin dollars × 52 ÷ 12`.
- Before AI analysis, code calculates and provides:
  - Week-over-week sales, gross margin percentage, and discount percentage by region.
  - Week-over-week price per unit, cost per unit, and units by category.
- All scorecard values and calculations come from code, not the AI.

### 7.3 Narrative
The AI reads each stakeholder's private brief and produces:
- Headline.
- Up to 3 insights.
- Causes, supported by available evidence.
- Up to 2 actions.
- Decision needed.
- Indicators for which numbers need attention, according to the brief.

Priority rules:
- The private brief determines narrative priority when metrics conflict.
- A brief cannot override calculated values, invent targets, or require unsupported causal claims.
- Code applies red/green/blue formatting independently of the AI.
- If the brief is vague, contradictory, or unusable, send a basic factual report and mark personalized analysis incomplete. Do not invent priorities, actions, or decisions.
- If a Google Doc cannot be read, use the last saved copy and log that fallback. If no saved copy exists, skip that stakeholder, log the reason, and retry on the next run. Never send a generic personalized digest in this case.

### 7.4 Digest delivery order
The email and Word document must always use the same order:
1. Scorecard table.
2. Headline.
3. Up to 3 insights.
4. Causes.
5. Up to 2 actions.
6. Decision needed.
7. Analysis status or caveat where applicable.

## 8. Email and Word report requirements

### 8.1 Email
- Send HTML email with the complete report in the body.
- Include a plain-text alternative in the same message.
- Use a single-column, phone-friendly layout with inline styles only.
- No external CSS, images, or scripts.
- The email is the primary report and should be readable in under two minutes.
- The Word attachment is a forwardable record.
- HTML email and Word report use the same information and ordering.

### 8.2 Colour rules
Code decides all colours:
- **Red:** drop alert or a number marked as needing attention.
- **Green:** better than last week or above target.
- **Blue:** neutral information, labels, and headings.
- Apply colour to the number or a small adjacent label, never colour alone.
- Preserve the plus/minus sign and a textual label such as "Needs attention" for monochrome accessibility.
- Apply equivalent colours in Word documents.

### 8.3 Attachments and file names
- Combined or market/channel alert: `escalations/<market>_<channel>_<date>.docx`
- Standalone customer alert: `escalations/<market>_<channel>_<customer>_<date>.docx`
- Weekly digest: `digests/<name>_<monday>_to_<sunday>.docx`
- Sanitize file-name values so market, channel, customer, and stakeholder names cannot create invalid or unintended paths.
- Alert Word attachment should be approximately half a page.
- Digest Word attachment should be one page.

## 9. Stakeholder briefs and Google APIs

- Each stakeholder has a private Google Doc, initially based on `context/context_interview_prompt.md`.
- The document is shared only with that stakeholder as Editor, not shared by link.
- Read each brief fresh on every run using Google Docs API with read-only access.
- Send emails using Gmail API send-only access.
- Use one Google Cloud project and OAuth client for both APIs.
- Read the refresh token from `.env`; do not implement a sign-in screen, token files, or app password.
- Use exactly these OAuth scopes:
  - `https://www.googleapis.com/auth/documents.readonly`
  - `https://www.googleapis.com/auth/gmail.send`
- Use `EMAIL_FROM` as the sender address.
- If a brief read fails, use the last saved copy and log the fallback. If no saved copy exists, skip that stakeholder's digest and retry next run.
- `stakeholders.csv` columns: name, role, email, Doc link.
- `TEST_INBOX`, when set, redirects all email deliveries to the demo inbox and notes the intended recipient in the message.

## 10. Delivery reliability and idempotency

- Write every job attempt to `run_log`.
- `OK` means Gmail returned a message ID for an email delivery. Any send error is `ERROR` and is retried on the next run.
- A report is not considered sent merely because its file was generated.
- Do not send a report twice to a real recipient.
- `--force` may resend only when `TEST_INBOX` is set. It must never resend to real recipients.
- `--no-email` generates files but does not send and does not mark delivery as sent.
- `--scan` lists detected drops and stopped-order customers without AI, email, or state changes.
- One failed job must not stop unrelated jobs that have valid prerequisites.
- Only one copy of the agent may run at a time. Use a process-level lock or equivalent single-instance guard.
- If the Gmail request fails before a message ID is returned, record `ERROR` and retry next run, as specified.
- **Delivery uncertainty risk:** Gmail could accept a message but the response could be lost before the agent receives the message ID. Because the required design has no separate delivery ledger and treats only a returned message ID as `OK`, the agent cannot guarantee exactly-once delivery in this edge case. The implementation must log the uncertainty where detectable and must not claim exactly-once delivery is mathematically guaranteed.

## 11. CLI and operator experience

Supported options:
- `--scan`: list all drops and stopped customers; no AI, email, or state changes.
- `--day YYYY-MM-DD`: replay one day, provided it is not after `as_of_date`.
- `--week YYYY-MM-DD`: replay the week whose Monday is supplied, provided its Sunday is not after `as_of_date`.
- `--no-email`: write files only, do not send and do not mark as sent.
- `--force`: redo work already done; resending is permitted only with `TEST_INBOX` set.

The agent prints every step in plain English, including each AI-generated SQL query before execution. Logs should make it clear which dates, jobs, recipients, and outputs are being processed and why.

## 12. Technology and configuration

### 12.1 Technology
- Python on Windows in a virtual environment.
- Dependencies limited to:
  - `mysql-connector-python`
  - `python-dotenv`
  - `groq`
  - `python-docx`
  - `google-api-python-client`
  - `google-auth`
- No agent frameworks and no pandas.
- AI model: `openai/gpt-oss-120b` on Groq, configurable through `.env`.

### 12.2 Required `.env` keys
Use exactly these names:
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_DB`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_INGEST_USER`
- `MYSQL_INGEST_PASSWORD`
- `GROQ_API_KEY`
- `GROQ_MODEL`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`
- `EMAIL_FROM`
- `TEST_INBOX`

Never hardcode passwords, API keys, or OAuth secrets in source code or logs.

## 13. Run logging and failure handling

- Use `run_log` for `new_data`, `daily_check`, and `weekly_digest` jobs.
- Record run time, job, applicable `as_of_date`, status, and useful details.
- Details should include the date/week, detected issue, report path, delivery result, and error summary where applicable, without exposing credentials or tokens.
- Retry failed jobs on the next scheduled run.
- A failure for one stakeholder's digest must not prevent other stakeholders' digests from being processed.
- If a failure prevents reliable determination of an escalation level, log the ambiguity and do not fabricate the escalation day.

## 14. Acceptance criteria

### Data freshness and sequencing
- [ ] `as_of_date` advances only to an available order date no later than yesterday.
- [ ] No daily or weekly analysis includes dates after `as_of_date`.
- [ ] The first run does not automatically send historical alerts or digests.
- [ ] Newly eligible dates are checked in chronological order.
- [ ] A failed daily check blocks later daily checks until resolved.
- [ ] `--day` and `--week` reject dates beyond `as_of_date`.

### Detection
- [ ] A 30% drop does not trigger; a drop greater than 30% can trigger.
- [ ] Baselines below $5,000 do not trigger.
- [ ] Missing four-week same-weekday history skips the applicable check.
- [ ] Zero-order customers are detected even when absent from the daily sales view.
- [ ] A customer with non-zero but reduced orders does not trigger a standalone customer alert.
- [ ] A market/channel drop and customer zero-order condition on the same date and market/channel produce one combined alert.

### Escalation and explanation
- [ ] Recipient resolution follows market + channel, then market, then region head.
- [ ] Day 2 copies the next level up once; day 3 and later do not climb further.
- [ ] Failed checks are not treated as issue continuation or resolution.
- [ ] AI causal claims are evidence-based and qualified when uncertain.
- [ ] AI-generated SQL is validated, limited to `v_sales_daily`, capped at 30 rows, and stopped after 3 seconds.
- [ ] AI cannot select recipients, calculate final metrics, or send emails.

### Digest
- [ ] A digest is sent only when the latest Monday-to-Sunday week is complete.
- [ ] The scorecard contains the specified company-wide metrics and week-over-week comparisons.
- [ ] Only net sales is compared with a target.
- [ ] Regional and category comparisons are calculated before AI analysis.
- [ ] Each usable private brief affects narrative priority without changing facts.
- [ ] Unusable briefs result in a factual digest with personalized analysis marked incomplete.
- [ ] An unreadable brief uses the last saved copy, or skips the stakeholder if no copy exists.

### Delivery and format
- [ ] HTML and plain-text email alternatives contain the report.
- [ ] Email and Word attachment content appear in the same order.
- [ ] Code determines colour and includes text labels for meaning.
- [ ] `OK` requires a Gmail message ID.
- [ ] `--no-email` does not mark a report sent.
- [ ] `--force` cannot resend to real recipients.
- [ ] One failed stakeholder job does not stop other independent jobs.
- [ ] A second simultaneous agent instance is refused.
- [ ] No credentials are written to logs.

## 15. Assumptions

These assumptions fill gaps not explicitly settled by the scope or the five product decisions. They should be reviewed before implementation.

1. **Uncertain causes:** If partial evidence exists, the report explains it as partial evidence. If no credible cause is supported, it explicitly says the cause could not be determined.
2. **Failed daily processing:** Later daily checks wait until the failed day is resolved. Independent weekly digest processing may continue when its prerequisites are satisfied.
3. **Previously delivered reports:** Real recipients never receive an automatic resend for an already-sent report. Corrections during the pilot are handled manually.
4. **Digest prioritization:** The stakeholder's brief determines narrative priority, but cannot change numbers, invent targets, or require unsupported claims.
5. **Unusable brief:** Send factual scorecard content and mark personalized analysis incomplete rather than inventing a narrative.
6. **Escalation continuity:** Existing logs and deterministic daily checks are used to reconstruct incident continuity. If the escalation day cannot be established unambiguously, the agent does not guess and flags the escalation level as unconfirmed.
7. **Delivery uncertainty:** A lost Gmail response can make delivery status uncertain. The implementation will log this limitation and will not claim strict exactly-once delivery in this edge case.
8. **Zero-order customer population:** The implementation will use the customer population available through the approved data model or an explicitly documented fixed customer list. The current scope does not specify a customer dimension exposed to `agent_ro`; this must be verified before implementation because `v_sales_daily` cannot alone reveal a customer that has never appeared in a given day's rows.
9. **Run-log granularity:** `run_log` rows will be structured so job type, business date/week, report identity, recipient, and delivery outcome can be reconstructed from `details` without adding a new persistent state store. The current schema's `details` format is not specified, so the implementation must define a stable structured format.
10. **Date semantics:** "Yesterday" is interpreted in the laptop's local time zone, with the run scheduled at 8:00 AM local time. `as_of_date` remains the authoritative analysis boundary.
11. **Monthly margin impact:** The monthly projection uses the stated formula `change in gross margin dollars × 52 ÷ 12`, with the sign preserved.
12. **Report generation and delivery:** Generating a Word file does not mean an email was sent. Only a Gmail message ID establishes an `OK` delivery result under the specified rule.

## 16. Implementation risks to resolve

These are not new product decisions; they are issues the implementation must verify against the existing schema and API behavior.

- **Customer universe:** The data dictionary says `agent_ro` cannot read the Silver customer table, while the sales view has no row for a customer with zero orders. Code needs a reliable customer universe to detect zero-order customers. Do not silently assume the sales view can supply missing customers.
- **Incident identity:** The scope describes consecutive-day escalation but does not define a formal incident key for matching the same issue across dates. Define a deterministic key, likely based on market/channel and affected customer where relevant, and document how combined versus standalone incidents are matched.
- **Run-log reconstruction:** The implementation must encode enough structured information in `run_log.details` to identify prior successful checks and deliveries without a new ledger.
- **Exactly-once delivery:** A Gmail send accepted by the service with a lost response cannot be distinguished reliably from a failed send using only the returned message ID. The pilot must accept this residual uncertainty or later revise the persistence requirement.
- **Weekly digest partial failures:** Process each stakeholder independently and log individual outcomes so one failure does not block the others.
