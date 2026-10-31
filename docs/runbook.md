# Operator Runbook: AtliQ Morning Digest Agent

**Product Owner:** Peter Pandey  
**Primary Stakeholder:** Bruce Haryali  
**Environment:** Local Windows Laptop  

---

## 1. Quick Reference & CLI Commands

All commands should be executed from the project root directory inside the virtual environment:

```powershell
# 1. Inspect detected drops & zero-order customers without any changes (Non-AI scan)
.\venv\Scripts\python.exe -m src.cli --scan

# 2. Scan a specific historical date
.\venv\Scripts\python.exe -m src.cli --scan --day 2026-07-13

# 3. Replay a specific day without sending email (writes Word .docx to escalations/)
.\venv\Scripts\python.exe -m src.cli --day 2026-07-13 --no-email

# 4. Replay a specific day with email delivery (redirected to TEST_INBOX if configured)
.\venv\Scripts\python.exe -m src.cli --day 2026-07-13

# 5. Replay a complete Monday-to-Sunday week (writes Word .docx to digests/)
.\venv\Scripts\python.exe -m src.cli --week 2026-09-21 --no-email

# 6. Force redo work previously marked sent (allowed ONLY when TEST_INBOX is set)
.\venv\Scripts\python.exe -m src.cli --day 2026-07-13 --force

# 7. Run database diagnostics & permission verification
.\venv\Scripts\python.exe -m src.cli --test-db

# 8. Run full test suite
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

---

## 2. Daily 8:00 AM Automated Workflow

The automated runner is in `src/main.py` and runs at 8:00 AM via Windows Task Scheduler.

### Execution Steps
1. **Single-Instance Guard:** Acquires `agent.lock`. If another copy is already running, exits immediately with a warning.
2. **Data Freshness Step:** Checks `sales_orders` using `agent_ingest`. Advances `settings.as_of_date` to the newest order date, but never later than yesterday.
3. **Sequential Processing:** Evaluates each newly complete date in chronological order. A failed daily check halts subsequent checks to preserve consecutive-day escalation continuity.
4. **Weekly Digest Evaluation:** If the latest complete Monday-to-Sunday week has concluded through `as_of_date`, calculates company scorecard and generates personalized briefs for all stakeholders in `stakeholders.csv`.
5. **Logging:** Records every step (`new_data`, `daily_check`, `weekly_digest`) in the `run_log` table with `status='OK'` or `'ERROR'`.

---

## 3. Delivery Safety & Idempotency Rules

- **Gmail Confirmation:** A message is marked `OK` in `run_log` **only** if the Gmail API returns a message ID.
- **No Duplicate Delivery:** The agent queries `run_log` before dispatching. If `status='OK'` exists for an incident or digest, sending is automatically skipped.
- **Safety with `--force`:** `--force` will refuse to resend reports unless `TEST_INBOX` is configured in `.env`. Real recipients will never receive duplicate emails from automated or forced reruns.
- **Single-instance Lock:** Prevents race conditions and duplicate database operations.

---

## 4. Resetting the Demo Environment

To reset the database and outputs back to initial pilot state:

```powershell
# 1. Reset as_of_date to 2026-09-30 using agent_ingest
.\venv\Scripts\python.exe -c "from src.config import load_config; from src.db import get_ingest_connection; c = load_config(); conn = get_ingest_connection(c).__enter__(); cur = conn.cursor(); cur.execute('UPDATE settings SET setting_value = \'2026-09-30\' WHERE setting_key = \'as_of_date\''); cur.close(); conn.close(); print('[OK] as_of_date reset to 2026-09-30')"

# 2. Clean test records from run_log using root or agent_ro
.\venv\Scripts\python.exe -c "import mysql.connector; conn = mysql.connector.connect(host='127.0.0.1', port=3306, user='root', password='root', database='atliq_digest'); cur = conn.cursor(); cur.execute('TRUNCATE TABLE run_log'); conn.close(); print('[OK] run_log truncated')"

# 3. Clean generated output directories
Remove-Item -Path "escalations\*.docx", "digests\*.docx" -Force -ErrorAction SilentlyContinue
```

---

## 5. Adding New Stakeholders

To add a new stakeholder (e.g. Regional VP):
1. Open `stakeholders.csv` (or `Stakeholders Input/stakeholders.csv`).
2. Add a new row: `name,role,email,doc_link`.
3. Create their private Google Doc using the questions in `context/context_interview_prompt.md`.
4. Share the document with that stakeholder as **Editor** (do not share via public link).
5. No code changes are required.

---

## 6. Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `SingleInstanceError: Another instance is running` | A previous process terminated abnormally leaving `agent.lock`. | Check if Python is still running in Task Manager. If not, delete `agent.lock`. |
| `Unknown database 'atliq_digest'` | MySQL service stopped or database dropped. | Start MySQL Server 8.0 and re-import `01_silver_raw_data.sql` and `02_gold_agent_layer.sql`. |
| `Groq rate limit exceeded` | Groq free tier exceeded 8,000 TPM. | The agent automatically sleeps and retries up to 3 times. If persistent, wait 1 minute. |
| `Google OAuth token expired/invalid` | Refresh token was revoked. | Generate a fresh refresh token using Google OAuth Playground for `documents.readonly` and `gmail.send`. Update `.env`. |

