# Tasks: AtliQ Morning Digest Agent

This document defines the atomic, dependency-ordered implementation tasks for the AtliQ Morning Digest Agent, based on `prd.md`, `scope.md`, and `data_dictionary.md`.

---

## Architecture & Foundational Principles

1. **The Core Rule:** Code identifies issues and calculates every number. AI explains the evidence and writes the narrative. AI does not choose recipients, calculate business metrics, or send email.
2. **Database Access Segregation:**
   - `agent_ro` (`AgentRead2026`): Read-only queries against `v_sales_daily`, `targets_daily`, `owners`, `settings`, plus SELECT and INSERT on `run_log`.
   - `agent_ingest` (`AgentIngest2026`): Strictly limited to SELECT on `sales_orders` and UPDATE on `settings.as_of_date`.
3. **State Boundaries:** Only two persistent state locations exist: `settings.as_of_date` and `run_log`. No external incident tables, ledgers, or state caches.
4. **Data Freshness:** Complete days only. Analysis never includes "today". `as_of_date` may move forward up to newest order date, but never beyond yesterday.
5. **Sequential Safety:** Daily checks run in chronological order. A failed daily check blocks subsequent daily checks to preserve consecutive-day escalation logic. Weekly digests process stakeholders independently.

---

## Phase 1: Project Setup and Database Connection

### Task 1.1: Virtual Environment & Dependency Specification
- **Objective:** Establish an isolated Windows Python virtual environment with strictly approved packages.
- **Files:** `requirements.txt`, `.gitignore`
- **Dependencies:** Only the following libraries are permitted (PRD 12.1):
  - `mysql-connector-python`
  - `python-dotenv`
  - `groq`
  - `python-docx`
  - `google-api-python-client`
  - `google-auth`
- **Constraints:** No pandas, no LangChain, no LlamaIndex, no agent frameworks.
- **Details:** 
  - Define folder skeleton: `src/`, `src/ai/`, `src/alerts/`, `src/digest/`, `src/delivery/`, `context/`, `escalations/`, `digests/`, `tests/`.
  - Configure `.gitignore` to exclude `.env`, `venv/`, `__pycache__/`, `*.docx`, `*.log`, and temporary files.

### Task 1.2: Environment Configuration & Validation Module
- **Objective:** Centralize and validate all runtime configuration from `.env`.
- **Files:** `src/config.py`, `.env.example`
- **Details:**
  - Create `.env.example` documenting all 14 required keys:
    - `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD`
    - `MYSQL_INGEST_USER`, `MYSQL_INGEST_PASSWORD`
    - `GROQ_API_KEY`, `GROQ_MODEL`
    - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`
    - `EMAIL_FROM`, `TEST_INBOX`
  - Implement `Config` loader in `src/config.py` using `python-dotenv`.
  - Validate presence of all keys at startup; raise descriptive configuration errors if any key is missing or blank.
  - Implement security safeguard: mask passwords, tokens, and API keys in string representations (`__repr__`) and logs.

### Task 1.3: Dual Database Connection Managers
- **Objective:** Implement dedicated connection managers enforcing database user privilege boundaries.
- **Files:** `src/db.py`
- **Details:**
  - Create `get_ro_connection()` using `MYSQL_USER` (`agent_ro`) and `MYSQL_PASSWORD`. Used for reading views/tables and logging.
  - Create `get_ingest_connection()` using `MYSQL_INGEST_USER` (`agent_ingest`) and `MYSQL_INGEST_PASSWORD`. Strictly used for advancing `as_of_date`.
  - Implement context managers (`with get_ro_connection() as conn:`) with automatic connection closure and query error handling.
  - Support query timeout handling (PRD 6.1: 3-second query timeout).

### Task 1.4: Database Permissions & Schema Verification Script
- **Objective:** Verify database connectivity, user privileges, and table availability against `atliq_digest`.
- **Files:** `tests/test_db_connection.py`
- **Details:**
  - Verify `agent_ro` connection:
    - Can SELECT from `v_sales_daily`, `targets_daily`, `owners`, `settings`.
    - Can SELECT and INSERT into `run_log`.
    - Assert that `agent_ro` CANNOT UPDATE `settings` or write to any silver table (expect permission denied).
  - Verify `agent_ingest` connection:
    - Can SELECT from `sales_orders`.
    - Can SELECT and UPDATE `settings`.
    - Assert that `agent_ingest` CANNOT SELECT from `v_sales_daily` or write to `run_log`.
  - Check starting value of `settings.as_of_date` (expected initial: `2026-09-30`).

### Phase 1 "Done when" Test
Run the database and environment verification script from the terminal:
```powershell
python -m unittest tests/test_db_connection.py
```
**Done criteria:**
- Output displays `OK`.
- Both `agent_ro` and `agent_ingest` connect successfully.
- Permission boundaries are enforced (write attempts by `agent_ro` on settings fail as expected).
- The stored `as_of_date` is read and confirmed as `2026-09-30`.

---

## Phase 2: New-Data Step and Drop Detection with No AI

### Task 2.1: Data Freshness & `as_of_date` Advancement Engine
- **Objective:** Advance `settings.as_of_date` to the newest order date no later than yesterday, in complete-day increments.
- **Files:** `src/freshness.py`
- **Details:**
  - Read current `as_of_date` from `settings` via `agent_ro`.
  - Read maximum order date from `sales_orders` via `agent_ingest`.
  - Calculate "yesterday" relative to the system clock at run time (8:00 AM local time).
  - Enforce bounds: target date = `MIN(max_order_date, yesterday)`. Never advance to today or future dates.
  - If target date > current `as_of_date`:
    - Update `settings.as_of_date` using `agent_ingest`.
    - Record `job='new_data'` in `run_log` with status `OK` and updated date range using `agent_ro`.
  - If no newer eligible date exists, retain current date and log that data is current.
  - Return the ordered list of newly eligible complete dates to evaluate (chronological order).

### Task 2.2: Active Customer Universe Resolver
- **Objective:** Resolve the expected active customer population per market and channel to enable zero-order detection.
- **Files:** `src/alerts/customer_universe.py`
- **Details:**
  - Address PRD Risk 16 & Assumption 8: `v_sales_daily` contains no rows for days when a customer placed zero orders, and `agent_ro` cannot access the silver `dim_customer` table.
  - Derive expected customers from `v_sales_daily` historical data: extract distinct active `(customer, market, channel)` tuples that generated orders during the prior 4-week baseline window.
  - Cache this expected customer list per evaluation date to compare against observed orders.

### Task 2.3: Baseline & Net Sales Metric Engine
- **Objective:** Pure code implementation of same-weekday 4-week median baselines and net sales calculations.
- **Files:** `src/metrics.py`
- **Details:**
  - Net sales formula from `data_dictionary.md`:
    - `net_sales = net_invoice_sales - post_invoice_discount - post_invoice_other`
  - Implement 4-week same-weekday lookup:
    - For date $D$, target historical dates are $D - 7$, $D - 14$, $D - 21$, $D - 28$.
    - Check history completeness: if any of the 4 prior same-weekday dates are missing from the dataset, skip the check (PRD 5.1).
    - Calculate baseline as the exact median of the 4 values:
      - Formula: average of the 2 middle values for an even 4-element set.

### Task 2.4: Market-and-Channel Drop Detector
- **Objective:** Identify material sales drops for market-channel combinations.
- **Files:** `src/detectors/market_channel.py`
- **Details:**
  - For each market and channel on eligible date $D$:
    - Calculate actual net sales on date $D$.
    - Calculate 4-week same-weekday median baseline.
    - Check baseline threshold: baseline must be $\ge \$5,000$. Skip if $<\$5,000$.
    - Check decline percentage: `decline = (baseline - actual) / baseline`.
    - Trigger condition: `decline > 0.30` (strictly greater than 30%). Exactly 30.0% does NOT trigger.
  - Return structured incident payload: `date`, `market`, `channel`, `baseline`, `actual`, `drop_pct`.

### Task 2.5: Customer Stopped Ordering Detector
- **Objective:** Detect expected customers who placed zero orders on date $D$.
- **Files:** `src/detectors/customer_zero.py`
- **Details:**
  - For each expected customer in the resolved customer universe:
    - Determine if customer had zero orders on date $D$ (no rows in `v_sales_daily`).
    - If customer had orders on date $D$ (even if severely reduced), do NOT trigger a standalone alert.
    - If zero orders:
      - Calculate customer's same-weekday 4-week median net sales baseline.
      - Check baseline threshold: customer baseline must be $\ge \$5,000$.
    - Trigger condition: zero orders AND baseline $\ge \$5,000$.
  - Return structured customer incident payload: `date`, `market`, `channel`, `customer`, `baseline`, `actual=0.0`.

### Task 2.6: Alert Consolidation & Recipient Resolution
- **Objective:** Merge overlapping alerts and resolve email recipients from the `owners` table.
- **Files:** `src/alerts/resolver.py`
- **Details:**
  - Consolidation logic (PRD 5.3):
    - If both a market-and-channel drop AND zero-order customer(s) occur in the same market, channel, and date $\rightarrow$ merge into ONE combined alert naming the customer(s).
    - If only the customer condition fires $\rightarrow$ generate a standalone customer alert.
    - If only the market-and-channel drop fires $\rightarrow$ generate a market-channel alert.
  - Recipient resolution hierarchy from `owners` table:
    1. Look up exact match on `market` AND `channel`.
    2. If not found, look up `market` (with channel blank/null).
    3. If not found, look up regional head (`region` match, market and channel blank).
  - Explicit rule: AI never selects or changes recipients.

### Task 2.7: Incident Continuity & Escalation Day Calculation
- **Objective:** Deterministically calculate escalation day (Day 1, Day 2, Day 3+) and copy recipients.
- **Files:** `src/alerts/escalation.py`
- **Details:**
  - Incident key: generate deterministic key `market:channel` (or `market:channel:customer`).
  - Reconstruct continuity across consecutive calendar days using past `v_sales_daily` checks and `run_log` entries.
  - Rules (PRD 5.4):
    - Day 1: Send to primary resolved owner only.
    - Day 2: Primary resolved owner + copy the next owner level up once.
    - Day 3+: Primary resolved owner + copy the next owner level up. Do not continue climbing hierarchy.
    - If primary owner is already the region head, no copy recipient exists.
    - Failed daily checks do NOT infer continuity or resolution.
    - If continuity cannot be determined unambiguously, log ambiguity and flag escalation level as "unconfirmed" in output.

### Task 2.8: CLI `--scan` Mode Implementation
- **Objective:** Provide a terminal tool to inspect all detected drops without executing AI or modifying database state.
- **Files:** `src/cli.py`
- **Details:**
  - Implement `--scan` flag in CLI:
    - Evaluates data freshness without advancing `as_of_date`.
    - Runs drop detection and zero-order customer detection across all eligible complete days.
    - Prints detected incidents, baselines, actuals, drop percentages, resolved owners, and escalation levels to stdout in plain English.
    - Guarantees zero side effects: no AI calls, no email sent, no writes to `run_log` or `settings`.

### Phase 2 "Done when" Test
Run scan mode and targeted unit tests from the terminal:
```powershell
python -m src.cli --scan
python -m unittest tests/test_drop_detection.py
```
**Done criteria:**
- Terminal outputs clean, plain-English summary of detected drops and zero-order customers.
- Unit tests verify:
  - Exact 30% drop does not fire; 30.01% drop fires.
  - Baseline of $4,999 does not fire; $5,000 fires.
  - Missing 4-week history skips check.
  - Zero-order customer detected; reduced-order customer does not trigger standalone alert.
  - Owner resolution correctly navigates channel $\rightarrow$ market $\rightarrow$ region head.
  - Escalation Day 1 (no copy), Day 2 (copy level up), Day 3 (no further climbing).
  - Zero changes made to `settings` or `run_log` during `--scan`.

---

## Phase 3: The AI Investigation Loop and the Escalation Report

### Task 3.1: Groq Client & Rate Limit Resilience
- **Objective:** Implement the Groq API client with robust rate-limiting and retry logic.
- **Files:** `src/ai/groq_client.py`
- **Details:**
  - Initialize `Groq` client using `GROQ_API_KEY` and model `GROQ_MODEL` (default: `openai/gpt-oss-120b`).
  - Rate-limit wrapper: Groq free tier limit is ~8,000 tokens/min and 30 requests/min.
  - Inspect HTTP 429 response headers: extract stated retry-after wait time, sleep for the requested duration, and retry up to 3 times before failing gracefully.
  - Keep prompts, schema definitions, and query results compact to minimize token usage.

### Task 3.2: Safe SQL Tool & Security Validator
- **Objective:** Implement the AI's single tool (`execute_sql`) with strict query validation.
- **Files:** `src/ai/sql_tool.py`
- **Details:**
  - Implement query validator enforcing all PRD 6.1 constraints:
    - Statement count: exactly one SQL statement. Reject multiple queries or semicolons.
    - Allowed statement: must start with `SELECT`.
    - Table restriction: strictly inspect table references. Must read ONLY from `v_sales_daily`. Reject any other table, view, schema metadata, or stored procedure.
    - Disallow all write/DDL/DML operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `GRANT`).
  - Execution rules:
    - Execute exclusively via `agent_ro` connection.
    - Query timeout: enforce 3.0-second timeout.
    - Row limit: enforce maximum 30 rows returned (append `LIMIT 30` or slice result set).
    - Terminal logging: print every generated query to stdout in plain English before execution.

### Task 3.3: Drop Investigation AI Agent Loop
- **Objective:** Multi-turn tool-calling loop that investigates the root cause of a detected drop.
- **Files:** `src/ai/drop_investigator.py`
- **Details:**
  - System prompt: supply `data_dictionary.md` column definitions, formulas, and normal business patterns (e.g. Sunday dips, month-end spikes).
  - Initial instruction: investigate cause starting with same weekday last week, comparing by customer, then by product.
  - Tool execution: handle one tool call at a time (no parallel tool calls). Return tabular results or error back to the model.
  - Step limit: enforce hard ceiling of 8 steps per drop investigation.
  - Final answer submission tool: model must submit via structured schema:
    - `headline`: concise 1-sentence summary of findings.
    - `likely_causes`: evidence-based causal explanation.
    - `evidence`: specific customers, products, or metrics supporting the claim.
    - `confidence`: whether evidence is complete or partial.
  - Answer validation: validate required fields and word limits.
  - Fallback: if AI exceeds 8 steps, times out, or fails validation, output factual numbers with "Analysis incomplete" and qualify partial evidence without claiming proven causation.

### Task 3.4: Visual Hierarchy & Color Styling Engine
- **Objective:** Apply strict, code-determined color styling with monochrome accessibility.
- **Files:** `src/reports/formatting.py`
- **Details:**
  - Color definitions (PRD 8.2):
    - Red (`#D32F2F`): Drop alerts or numbers marked as needing attention.
    - Green (`#2E7D32`): Better than baseline or above target.
    - Blue (`#1976D2`): Neutral information, labels, section headings.
  - Accessibility safeguard: Color must never be used alone. Always include a textual indicator and sign: e.g., `+5.2%`, `-34.1% [Needs attention]`.
  - Provide formatting helpers for both HTML (inline CSS) and Word (`python-docx` RGBColor and XML shading).

### Task 3.5: Phone-Friendly Escalation HTML & Plain-Text Email Builder
- **Objective:** Build single-column HTML email body and matching plain-text body for drop alerts.
- **Files:** `src/reports/email_alert.py`
- **Details:**
  - HTML email specs:
    - Single-column layout readable on mobile screens in under 2 minutes.
    - Inline styles only. No external CSS, no `<style>` blocks, no remote images, no JavaScript.
    - Structure: Alert title, incident metadata (market, channel, date, escalation day), baseline vs actual table, AI cause analysis, resolved owner and CC list.
  - Plain-text alternative:
    - Identical content, hierarchy, and ordering formatted cleanly for plain-text email clients.

### Task 3.6: Half-Page Escalation Word Document Generator
- **Objective:** Generate a half-page `.docx` attachment for drop alerts matching the email report.
- **Files:** `src/reports/word_alert.py`
- **Details:**
  - Structure matches email exactly: header banner, incident summary, metrics table, AI cause explanation.
  - Target length: approximately half a page.
  - Sanitize file paths to avoid illegal Windows filename characters.
  - Filename conventions (PRD 8.3):
    - Combined / Market-Channel alert: `escalations/<market>_<channel>_<date>.docx`
    - Standalone customer alert: `escalations/<market>_<channel>_<customer>_<date>.docx`

### Phase 3 "Done when" Test
Execute a single-day escalation test run without email delivery:
```powershell
python -m src.cli --day 2026-09-15 --no-email
python -m unittest tests/test_ai_investigation.py
```
**Done criteria:**
- AI queries are printed to stdout in plain English during execution.
- SQL validator blocks disallowed tables, multi-statements, and queries without row limits.
- The generated `.docx` file exists in `escalations/`, opens cleanly, and is approximately half a page.
- Both HTML and plain-text outputs contain identical data, valid color styling, and accessibility labels.
- If AI fails or simulated rate limit occurs, report generates with "Analysis incomplete" fallback.

---

## Phase 4: The Stakeholder Context and the Weekly Digest

### Task 4.1: Company Scorecard Calculation Engine
- **Objective:** Calculate company-wide weekly scorecard metrics in pure code.
- **Files:** `src/digest/scorecard.py`
- **Details:**
  - Verify complete Monday-to-Sunday week in `v_sales_daily` up to `as_of_date`.
  - Calculate company-wide metrics for the week vs prior week:
    - Net Sales ($), Gross Margin %, Gross Margin ($), Units Sold.
    - Week-over-week (WoW) dollar/unit changes and percentage changes.
  - Target comparison:
    - Query `targets_daily` for the 7 dates of the week, summed across all regions.
    - Compare Net Sales with target.
    - Strict rule: Do NOT invent targets for Gross Margin %, Gross Margin $, or Units.
  - Money impact calculation:
    - Money impact = Week-over-week change in Gross Margin ($).
    - Annualized monthly impact = `change in gross margin $ * 52 / 12` (preserve sign).

### Task 4.2: Pre-Calculated Dimensional Breakdowns
- **Objective:** Pre-calculate regional and category breakdowns in code before AI analysis.
- **Files:** `src/digest/breakdowns.py`
- **Details:**
  - Regional breakdown (this week vs last week):
    - Net sales change %, Gross margin %, Discount % by region.
  - Category breakdown (this week vs last week):
    - Price per unit (`SUM(gross_sales)/SUM(sold_qty)`), Cost per unit (`SUM(manufacturing_cost)/SUM(sold_qty)`), Units sold change by category.
  - Format breakdowns as compact tables to provide directly in the AI's prompt.

### Task 4.3: Stakeholder Registry & Google Docs API Client
- **Objective:** Load stakeholders and retrieve private briefs fresh via Google Docs API.
- **Files:** `src/context/stakeholders.py`, `src/context/google_docs.py`
- **Details:**
  - Parse `stakeholders.csv` (columns: `name`, `role`, `email`, `doc_link`).
  - Google Docs API client:
    - Authenticate using `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN`.
    - Enforce OAuth scope: `https://www.googleapis.com/auth/documents.readonly`.
    - Fetch plain text from the private Google Doc on every run.
  - Caching and fallback logic (PRD 7.3, 9):
    - On success, update local brief cache: `context/cache/<stakeholder_name>.txt`.
    - If Google Docs API read fails: load the last saved local copy and log fallback to operator.
    - If no saved copy exists: skip that stakeholder's digest, log the reason, and mark for retry on next run. Never send a generic personalized digest.

### Task 4.4: Digest AI Prioritization & Synthesis Loop
- **Objective:** Execute AI narrative synthesis customized to each stakeholder's brief.
- **Files:** `src/ai/digest_investigator.py`
- **Details:**
  - Prompt structure: Company scorecard, regional & category breakdowns, and the stakeholder's private brief.
  - Priority rules: Brief determines narrative priority when metrics conflict, but cannot alter numbers or invent targets.
  - Investigation tool: AI may execute up to 10 SQL SELECT queries against `v_sales_daily` via the safe SQL tool for deeper causal evidence.
  - Final structured output schema:
    1. `headline`: concise summary tailored to stakeholder's focus.
    2. `insights`: up to 3 key insights.
    3. `causes`: evidence-based causal explanation.
    4. `actions`: up to 2 concrete recommended actions.
    5. `decision_needed`: specific decision required from the stakeholder.
    6. `attention_flags`: list of specific metric keys that need attention according to the brief.
  - Fallback: If brief is vague, contradictory, or unusable, send basic factual scorecard report and mark personalized analysis incomplete.

### Task 4.5: One-Page Weekly Digest Word Document Generator
- **Objective:** Generate a one-page `.docx` digest attachment.
- **Files:** `src/digest/word_digest.py`
- **Details:**
  - Strict delivery order (PRD 7.4):
    1. Scorecard table (Net Sales, GM %, GM $, Units, vs Target, Money Impact, Monthly Impact).
    2. Headline.
    3. Up to 3 insights.
    4. Causes.
    5. Up to 2 actions.
    6. Decision needed.
    7. Analysis status or caveats.
  - Target length: exactly one page.
  - Path formatting: `digests/<name>_<monday>_to_<sunday>.docx` (sanitized names).

### Task 4.6: Phone-Friendly Weekly Digest HTML & Plain-Text Email Builder
- **Objective:** Generate single-column HTML email body and matching plain-text body for weekly digests.
- **Files:** `src/digest/email_digest.py`
- **Details:**
  - Same strict order and content as Word document.
  - Scorecard rendered as clean, mobile-optimized HTML table.
  - Code-enforced color rules (Red for attention flags, Green for positive changes, Blue for headers) with `+`/`-` signs and text labels.
  - Plain-text alternative matching structure.

### Phase 4 "Done when" Test
Execute a weekly digest replay for a complete week without email delivery:
```powershell
python -m src.cli --week 2026-09-21 --no-email
python -m unittest tests/test_weekly_digest.py
```
**Done criteria:**
- Company scorecard correctly calculates Net Sales, GM%, GM$, Units, and WoW deltas.
- Net sales is compared to target; no targets exist for GM%, GM$, or Units.
- The stakeholder's Google Doc brief is read (or uses local cached fallback).
- AI produces the 7 ordered sections adhering to brief priorities.
- The generated Word file exists at `digests/Bruce_Haryali_2026-09-21_to_2026-09-27.docx`, opens cleanly, and fits on one page.

---

## Phase 5: Email, Run Log and the Daily Schedule

### Task 5.1: Gmail API Dispatcher & Delivery Verification
- **Objective:** Send MIME multipart emails with attachments using Gmail API send-only OAuth.
- **Files:** `src/delivery/gmail.py`
- **Details:**
  - Authenticate using Google OAuth refresh token with scope: `https://www.googleapis.com/auth/gmail.send`.
  - Sender header: `EMAIL_FROM`.
  - Build MIME multipart/mixed message containing:
    - `multipart/alternative` with `text/plain` and `text/html`.
    - `application/vnd.openxmlformats-officedocument.wordprocessingml.document` attachment (`.docx`).
  - `TEST_INBOX` redirection:
    - If `TEST_INBOX` is set in `.env`, redirect recipient `To:` to `TEST_INBOX`.
    - Explicitly note intended recipient in the email subject and top of email body.
  - Delivery verification rule:
    - An email is considered sent (`OK`) ONLY when Gmail API returns a message ID.
    - Any network failure, API exception, or missing ID is logged as `ERROR` and scheduled for retry.
    - Document edge case: lost response after Gmail acceptance cannot be proven exactly-once.

### Task 5.2: State Persistence & Structured Run Log Engine
- **Objective:** Record every job attempt in `run_log` with structured details.
- **Files:** `src/delivery/run_log.py`
- **Details:**
  - Table: `run_log` (`run_id`, `run_at`, `job`, `as_of_date`, `status`, `details`).
  - Allowed `job` values: `new_data`, `daily_check`, `weekly_digest`.
  - Allowed `status` values: `OK`, `ERROR`.
  - Store structured JSON in `details`:
    - `job_type`, `target_date` or `week_start`, `incident_key`, `recipient`, `escalation_level`, `report_file`, `gmail_message_id`, `error_summary`.
  - Maintain constraint: `run_log` and `settings.as_of_date` are the only persistent state stores. No extra state files.

### Task 5.3: Delivery Idempotency & Resend Prevention Guard
- **Objective:** Prevent duplicate delivery to real recipients while supporting safe test replays.
- **Files:** `src/delivery/guard.py`
- **Details:**
  - Query `run_log` before sending:
    - If a job for that date/incident/recipient has `status='OK'`, skip sending.
  - `--force` flag logic:
    - If `--force` is passed AND `TEST_INBOX` is set: allow resending to `TEST_INBOX`.
    - If `--force` is passed AND `TEST_INBOX` is blank/unset: refuse to resend to real recipients; exit with error.
  - `--no-email` flag logic:
    - Generate all files and terminal output; do not call Gmail API; do not record `status='OK'` in `run_log`.

### Task 5.4: Process-Level Single Instance Guard
- **Objective:** Ensure only one instance of the agent can run at any time on Windows.
- **Files:** `src/utils/lock.py`
- **Details:**
  - Implement file lock mechanism using `msvcrt.locking` on an `agent.lock` file (or a Windows named mutex).
  - Acquire lock at agent startup; release on exit.
  - If lock cannot be acquired, print "Another agent instance is currently running. Exiting." and terminate with non-zero exit code.

### Task 5.5: Unified CLI & Master Orchestrator
- **Objective:** Wire together all components into the main daily agent runner and CLI.
- **Files:** `src/main.py`, `src/cli.py`
- **Details:**
  - CLI arguments supported (PRD 11):
    - `--scan`: list detected drops and stopped customers without AI, email, or state changes.
    - `--day YYYY-MM-DD`: replay one day (reject if date > `as_of_date`).
    - `--week YYYY-MM-DD`: replay week whose Monday is supplied (reject if Sunday > `as_of_date`).
    - `--no-email`: generate files only; do not send or mark sent.
    - `--force`: redo work; resending permitted only when `TEST_INBOX` is set.
  - Scheduled run flow (at 8:00 AM daily):
    1. Acquire single-instance lock.
    2. Run data freshness step: advance `as_of_date` via `agent_ingest` up to yesterday.
    3. Process newly eligible days in chronological order.
    4. For each day, run drop and zero-order detection. If issues found, run AI investigation, generate reports, send emails, log in `run_log`.
    5. Sequential rule: if a daily check fails, halt subsequent daily checks until resolved.
    6. Check weekly digest eligibility: if latest Monday-to-Sunday is complete, process digests for each stakeholder in `stakeholders.csv`.
    7. Process each stakeholder independently: one stakeholder failure does not block others.
    8. Release lock and exit cleanly.

### Task 5.6: Windows Task Scheduler Setup & Operator Runbook
- **Objective:** Create Task Scheduler installation script and operator runbook for Peter Pandey.
- **Files:** `scripts/setup_scheduler.bat`, `docs/runbook.md`
- **Details:**
  - `setup_scheduler.bat`: Windows batch script creating a Windows Scheduled Task:
    - Task Name: `AtliQMorningDigestAgent`
    - Trigger: Daily at 8:00 AM
    - Action: `cmd.exe /c "cd /d C:\Users\lap\Desktop\AI Agent AtliQ && venv\Scripts\python.exe -m src.main >> logs\agent.log 2>&1"`
  - `docs/runbook.md`:
    - Daily operations: how to check `run_log` and `agent.log`.
    - Troubleshooting: Groq rate limits, Google token refresh, MySQL connectivity.
    - Demo reset procedure: setting `as_of_date` back to `2026-09-30`, clearing `run_log`, and cleaning `escalations/` and `digests/`.

### Phase 5 "Done when" Test
Execute full end-to-end integration test with CLI validation and test inbox delivery:
```powershell
python -m src.cli --help
python -m src.cli --day 2026-09-15 --force
python -m unittest tests/test_end_to_end.py
```
**Done criteria:**
- Process lock prevents a second simultaneous process from running.
- `--help` displays all documented CLI options.
- Email is delivered to `TEST_INBOX` with valid Gmail message ID returned.
- Word attachment is attached and intact.
- `run_log` contains a new row with `status='OK'` and valid structured JSON details.
- Running without `--force` confirms duplicate delivery prevention (skips send).
- Attempting `--force` without `TEST_INBOX` refuses execution.
- Scheduled task XML/script is valid for Windows Task Scheduler at 8:00 AM.

---

## Traceability Matrix: PRD Requirements to Tasks

| PRD Section | Requirement Description | Implementing Tasks |
|---|---|---|
| **4.1 - 4.3** | Runtime, data freshness, complete days only, sequential processing | Task 2.1, Task 5.5 |
| **5.1** | Market-and-channel drop (>30% decline, $5k baseline, 4-week median) | Task 2.3, Task 2.4 |
| **5.2** | Customer stopped ordering (zero orders only, $5k baseline) | Task 2.2, Task 2.5 |
| **5.3** | Alert consolidation & owner resolution hierarchy | Task 2.6 |
| **5.4** | Incident continuity, Day 1/2/3 escalation rules | Task 2.7 |
| **6.1 - 6.2** | Safe SQL tool (`v_sales_daily`, 30 rows, 3s timeout), AI loop | Task 3.1, Task 3.2, Task 3.3 |
| **7.1 - 7.4** | Weekly digest scorecard, targets, dimensional breakdowns, brief | Task 4.1, Task 4.2, Task 4.3, Task 4.4 |
| **8.1 - 8.3** | Phone-friendly HTML/text email, Word half-page/one-page, color rules | Task 3.4, Task 3.5, Task 3.6, Task 4.5, Task 4.6 |
| **9.0** | Google Docs API (read-only), Gmail API (send-only), OAuth refresh | Task 4.3, Task 5.1 |
| **10.0** | Delivery reliability, Gmail message ID, idempotency, no duplicate sends | Task 5.1, Task 5.2, Task 5.3 |
| **11.0** | CLI options (`--scan`, `--day`, `--week`, `--no-email`, `--force`) | Task 2.8, Task 5.5 |
| **12.1 - 12.2**| Virtual environment, approved libraries, 14 required `.env` keys | Task 1.1, Task 1.2, Task 1.3 |
| **13.0** | `run_log` schema, structured details, failure isolation | Task 1.3, Task 5.2, Task 5.5 |
| **Windows** | Single instance lock, Windows Task Scheduler at 8:00 AM | Task 5.4, Task 5.6 |

