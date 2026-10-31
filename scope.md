# Scope: a morning digest agent for Bruce

*Peter Pandey, data analyst, AtliQ Hardware*

## The problem

Bruce runs AtliQ Hardware and has more dashboards than hours, so most never get opened. In July one of
our biggest USA retailers placed no orders for a whole week, and nobody noticed until month-end.
Bruce doesn't want another dashboard. He wants to be told when something breaks, and why.

## What I want

An agent that runs on my laptop every morning at 8 AM.

1. **Pick up new data, complete days only.** When it runs at 8 AM, all of **yesterday's** data is
   already in the database. Today's isn't complete yet, so the agent **never checks or raises
   anything for today**.
   - `as_of_date` in the `settings` table is the last complete day the agent may see.
   - If the orders have newer days, move `as_of_date` to the newest order date, but **never later
     than yesterday**. Then check each new day in order.
   - Everything else (which days to check, which week is complete) is decided from `as_of_date`, not
     from the computer's clock.
   - On the very first run, start from the stored `as_of_date`. Don't send alerts or digests for all the
     old history; I can replay old days or weeks with `--day` / `--week`.
2. **Check each day for sudden drops.** Two checks:
   - **Market + channel drop:** compare the day's net sales with a normal day: the median of the same
     weekday over the last 4 weeks. Flag it if it's more than 30% below normal (exactly 30% doesn't
     count), and normal is at least $5,000. Skip it if there aren't 4 weeks of history.
   - **Customer stopped ordering:** a customer with **no orders at all** that day, whose normal day
     (same median rule) is at least $5,000. Only zero-order days; a customer that is merely down is
     evidence, not its own alert. The sales view has no row for a customer with no orders, so code
     must work out that zero itself.
   - If both happen in the same market and channel on the same day, send **one** alert and name the
     customer in it. If only the customer check fires, send it on its own to that market and channel's
     owner.
   - The owner comes from the `owners` table: market and channel first, then market, then the
     region head. If the same issue is still there the next day, call it "day 2" (then day 3 and so
     on) and copy the person one level up, once; don't keep climbing. A region head has no one above,
     so no copy.
   - The AI finds the cause. A good start is to compare with the same weekday last week, by customer,
     then by product.
   - The owner gets an email (see "What the emails look like" below) with a half-page Word file
     attached.
3. **Send a weekly digest.** When the latest Monday-to-Sunday week is fully in the data, send it
   once to everyone in `stakeholders.csv`.
   - The numbers cover the whole company and are the same for everyone: net sales, gross margin %,
     gross margin $ and units, vs last week. Only **net sales** has a target, so only net sales is
     compared with target; don't invent targets for the others.
   - The money impact is the change in margin $, and "if this continues", that × 52 ÷ 12 per month.
   - Before the AI starts, code also works out this week vs last by region (sales, margin %,
     discount %) and by category (price per unit, cost per unit, units), and hands that over.
   - The AI reads the person's brief and writes the headline, up to 3 insights, the real causes, up
     to 2 actions and the decision needed. It also marks which numbers need attention, based on the
     brief.
   - It goes out as an email with a one-page Word file attached, always in the same order.

## What the emails look like

Bruce reads this on his phone in under 2 minutes, so **the email itself is the report**. The Word file
is attached as the record he can forward or file.

- **HTML email** with the full content: for the digest, the scorecard as a small table, then headline,
  insights, causes, actions and the decision; for an alert, the numbers and the reason. Same order as
  the Word file. Include a plain-text version in the same email for mail apps that don't show HTML.
- **Colour shows good or bad at a glance**, decided by code, never by the AI:
  - **Red:** needs attention (a drop alert, or a number the AI marked against the brief).
  - **Green:** better than last week or above target.
  - **Blue:** neutral information, labels and headings.
  - Use colour on the number or a small label next to it, never colour alone: keep the `+` / `-` sign
    and a word like "Needs attention", so it still reads in black and white.
- Keep it simple and phone-friendly: one column, inline styles only (no external CSS, images or
  scripts), readable at phone width.
- The Word file uses the same colours.

## The one rule

**Code finds the problems and calculates every number. The AI only explains why and writes the words.**

## How the AI works

- It has one tool: it **writes its own SQL** (one SELECT on `v_sales_daily`) and code runs it. Don't
  replace this with a fixed menu of queries. Before running, code checks it is a single SELECT on
  that view only, caps the result at 30 rows (even if the AI asks for more), and stops it after 3
  seconds. The read-only login is the real safety net. It gets the column list and the formulas from
  the data dictionary.
- It has a step limit (about 8 for a drop, 10 for a digest), then it hands in its answer through a
  submit tool with fixed fields.
- Code checks the answer (word limits, missing fields) before using it. If the AI fails, the report
  still goes out with the numbers and "Analysis incomplete".
- Groq's free tier allows about 8,000 tokens per minute (30 requests per minute). If it hits a limit, wait
  for the time Groq says, then retry, up to 3 times. Keep what is sent to the AI short.
- The model makes one tool call at a time (no parallel tool calls), so the loop handles one query per
  step.

## Briefs and email

- Each stakeholder's brief is a **private Google Doc**, written with
  `context/context_interview_prompt.md`. It sits in the agent's Gmail account and is shared only with
  that stakeholder, as Editor, so they can change it any time. It is **not** shared by link.
- **One Google Cloud app does both jobs**, signed in as the agent's Gmail account:
  - It reads each Doc fresh on every run through the **Google Docs API** (read-only).
  - It sends every email through the **Gmail API** (send only).
  - I've already set this up by hand (a Cloud project and an OAuth client, with the refresh token
    from Google's OAuth Playground). `.env` has
    `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REFRESH_TOKEN`.
  - The code just uses the refresh token: no sign-in screen, no token files, no app password.
  - The token was made for exactly these two scopes, and the code must use the same ones:
    `https://www.googleapis.com/auth/documents.readonly` and `https://www.googleapis.com/auth/gmail.send`.
  - `EMAIL_FROM` is the agent's Gmail address (the account that owns the token). Just use it as the
    From address; the send-only permission can't check it.
- If the Doc can't be read, the agent uses the last copy it saved and says so in the log. If there
  is no saved copy either, skip that person (log it, retry next run); never send a generic digest.
- Bruce is first; `context/bruce_context.md` is his starting text. One row per person goes in
  `stakeholders.csv` (name, role, email, Doc link). Adding a person means adding a row, with no code
  change.
- `TEST_INBOX` in `.env` sends every email to the demo inbox, with the real recipient noted.

## Safety

- The AI uses the read-only login `agent_ro`. Only the "move `as_of_date`" step uses
  `agent_ingest`, and that step is plain code.
- The AI never picks who gets an email and never sends anything itself.
- Every job is written to `run_log`. Nothing is ever sent twice. One failure doesn't stop the
  others, and a failed job is retried on the next run.
- An email counts as sent (`OK`) only once Gmail returns a message ID; any error is `ERROR` and is
  retried next run. Keep it that simple.
- `run_log` and `settings.as_of_date` are the **only** places the agent remembers anything: no extra
  state or ledger files. So resetting my demo is just: set `as_of_date` back, delete the `run_log`
  rows, delete the output folders.
- Only one copy of the agent may run at a time.
- Refuse `--week` for a week whose Sunday is after `as_of_date`, and `--day` after `as_of_date`.
  Never check today.
- Keys and passwords only go in `.env`, with exactly these names: `MYSQL_HOST`, `MYSQL_PORT`,
  `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_INGEST_USER`, `MYSQL_INGEST_PASSWORD`,
  `GROQ_API_KEY`, `GROQ_MODEL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`,
  `EMAIL_FROM`, `TEST_INBOX`.

## How to build it

- Python on Windows in a virtual environment. Only `mysql-connector-python`, `python-dotenv`, `groq`,
  `python-docx`, and Google's `google-api-python-client` + `google-auth` for the Docs and Gmail APIs.
  No agent frameworks, no pandas. Keep it to a few readable files.
- Model: `openai/gpt-oss-120b` on Groq, with the name in `.env`.
- Print every step in plain English, including each AI query, so I can watch a run.
- File names: `escalations/<market>_<channel>_<date>.docx` and
  `digests/<name>_<monday>_to_<sunday>.docx`.
- File name for a standalone customer alert: `escalations/<market>_<channel>_<customer>_<date>.docx`.
- Options for testing:
  - `--scan`: list all drops and stopped customers. No AI, no email, changes nothing.
  - `--day YYYY-MM-DD` and `--week YYYY-MM-DD` (that week's Monday): replay one day or week.
  - `--no-email`: write the files but don't send, and don't mark anything as sent.
  - `--force`: redo work already done. It may send again **only when `TEST_INBOX` is set** (to the
    test inbox); never re-send to real people.
- Windows Task Scheduler runs it at 8 AM.

## The data

It's already in MySQL (`atliq_digest`). Tables, columns, money formulas, owners and logins are all in
**`data/data_dictionary.md`**.

## Not now

No dashboard, no web app, no cloud, no per-region digests. I'll test it against incidents I already
know about.
