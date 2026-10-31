# AtliQ AI Agent

A personal learning project from the Codebasics Data Analytics Bootcamp: an AI agent that checks AtliQ
Hardware's sales every morning, tells the right person when sales drop and why, and sends a one-page
weekly digest.

This repository is the app's public home page for its Google sign-in screen. The privacy policy is in
[PRIVACY.md](PRIVACY.md) and the terms of service are in [TERMS.md](TERMS.md).

---

## 📌 Table of Contents
- [Problem Statement](#-problem-statement)
- [What the Agent Does](#️-what-the-agent-does)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Setup & Installation](#-setup--installation)
- [Configuration](#-configuration)
- [Running the Agent](#️-running-the-agent)
- [Scheduling (Windows)](#-scheduling-windows)
- [Testing](#-testing)
- [Run Logging & Observability](#-run-logging--observability)
- [Safety & Design Decisions](#-safety--design-decisions)


---

## 🎯 Problem Statement

Business stakeholders at AtliQ had to check dashboards manually to notice sales drops or KPI changes, and then wait for an analyst to find out why. This is slow, depends on individual people, and issues are often spotted late.

**Goal:** Automate the whole loop of *detect → investigate → explain → notify*.

---

## ⚙️ What the Agent Does

1. **Daily Check** – A scheduled job checks key business metrics for a target date.
2. **Drop Investigation** – If a significant drop is found, the `drop_investigator` runs read-only SQL queries to drill down by customer, product, region and channel.
3. **Digest Generation** – The `digest_investigator` summarises findings into a short, readable report using an LLM (Groq).
4. **Email Delivery** – The digest is sent to the right stakeholders (from `stakeholders.csv`) via Gmail.
5. **Run Logging** – Every run is stored in a `run_log` table with status, date and Gmail message ID for auditing.

---

## 🏗 Architecture

```
 Scheduler (Windows Task Scheduler)
            │
            ▼
      run_day_job()
            │
   ┌────────┴─────────┐
   ▼                  ▼
Daily Check      Stakeholder Context
(SQL metrics)    (bruce_context.md, stakeholders.csv)
   │
   ▼  drop detected?
Drop Investigator ──► SQL Tool (read-only DB) ──► Database
   │
   ▼
Digest Investigator ──► Groq LLM
   │
   ▼
Email (Gmail)  ──►  run_log (status, message ID)
```

---

## 🛠 Tech Stack

| Area | Tools |
|------|-------|
| Language | Python 3 |
| LLM | Groq API |
| Database | MySQL (EDIT: confirm) |
| Email | Gmail (EDIT: API or SMTP) |
| Scheduling | Windows Task Scheduler (`.bat`) |
| Testing | `unittest` |
| Config | `.env` |

---

## 📂 Project Structure

```
AI-Agent-AtliQ/
├── src/
│   ├── ai/
│   │   ├── digest_investigator.py   # Builds the stakeholder digest
│   │   ├── drop_investigator.py     # Investigates metric drops
│   │   ├── groq_client.py           # LLM client wrapper
│   │   └── sql_tool.py              # Safe, read-only SQL tool for the agent
│   └── ...                          # config, db, email, main job modules
├── tests/
│   └── test_end_to_end.py           # Full live daily-check test
├── scripts/
│   └── setup_scheduler.bat          # Creates the daily scheduled task
├── context/
│   ├── bruce_context.md             # Stakeholder persona/context
│   └── context_interview_prompt.md
├── Stakeholders Input/
│   └── stakeholders.csv             # Who receives which report
├── data/
│   └── data_dictionary.md           # Table & column definitions
├── docs/
│   └── runbook.md                   # Operations guide
├── prd.md                           # Product requirements
├── scope.md                         # Project scope
├── requirements.txt
├── .env.example                     # Template for environment variables
└── README.md
```

---

## 🚀 Setup & Installation

**Prerequisites**
- Python 3.10+
- Access to the AtliQ database (a read-only user is recommended)
- A Groq API key
- Gmail credentials for sending mail

**Steps**

```bash
# 1. Clone the repo
git clone https://github.com/Darshilshah0203/AI-Agent-AtliQ.git
cd AI-Agent-AtliQ

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env from the template
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux
```

---

## 🔐 Configuration

Fill in `.env` (never commit this file). EDIT: match the exact names in your `.env.example`.

```env
# Database
DB_HOST=
DB_PORT=3306
DB_NAME=
DB_RO_USER=
DB_RO_PASSWORD=

# LLM
GROQ_API_KEY=

# Email
GMAIL_SENDER=
GMAIL_APP_PASSWORD=

# Testing
TEST_INBOX=you@example.com
```

---

## ▶️ Running the Agent

Run the job for a specific date (EDIT: replace with your real entry point):

```bash
python -m src.main --date 2026-07-13
```

| Flag | Purpose |
|------|---------|
| `--date` | Target date to check (`YYYY-MM-DD`) |
| `--no-email` | Run everything without sending email |
| `--force` | Re-run even if the date was already processed |

---

## ⏰ Scheduling (Windows)

Run the setup script once to create the daily task:

```bat
scripts\setup_scheduler.bat
```

See [`docs/runbook.md`](docs/runbook.md) for changing the time, checking the task and troubleshooting.

---

## 🧪 Testing

```bash
python -m unittest discover tests
```

The end-to-end test runs a real daily check on a known drop date (`2026-07-13`), sends the email to `TEST_INBOX`, and then verifies the `run_log` row has `status = 'OK'` and a Gmail message ID. It is skipped automatically if `TEST_INBOX` is not set.

---

## 📈 Run Logging & Observability

Each execution writes to `run_log`:

| Column | Description |
|--------|-------------|
| `run_id` | Unique run identifier |
| `job` | Job name (e.g. `daily_check`) |
| `as_of_date` | Date that was analysed |
| `status` | `OK` / error state |
| `details` | JSON with extra info such as `gmail_message_id` |

---

## 🛡 Safety & Design Decisions

- **Read-only database
