"""Structured run logging and delivery persistence in run_log table."""

import datetime
import json
from typing import Any, Dict, List, Optional
from mysql.connector.connection import MySQLConnection


def log_run_event(
    conn: MySQLConnection,
    job: str,
    as_of_date: datetime.date,
    status: str,
    details: Dict[str, Any],
) -> int:
    """Insert structured job record into run_log.
    
    Status must be 'OK' or 'ERROR'.
    Details are serialized as structured JSON.
    """
    if status not in ("OK", "ERROR"):
        raise ValueError(f"Invalid status '{status}'. Must be 'OK' or 'ERROR'.")

    if job not in ("new_data", "daily_check", "weekly_digest"):
        raise ValueError(f"Invalid job '{job}'. Must be 'new_data', 'daily_check', or 'weekly_digest'.")

    details_str = json.dumps(details, default=str)

    cursor = conn.cursor()
    query = """
        INSERT INTO run_log (run_at, job, as_of_date, status, details)
        VALUES (NOW(), %s, %s, %s, %s)
    """
    cursor.execute(query, (job, as_of_date.isoformat(), status, details_str))
    run_id = cursor.lastrowid
    cursor.close()
    return run_id


def check_prior_successful_delivery(
    conn: MySQLConnection,
    job: str,
    target_date: datetime.date,
    incident_key: Optional[str] = None,
    recipient: Optional[str] = None,
) -> bool:
    """Check if a job for given date, incident, and recipient already succeeded (status='OK').
    
    Used to enforce delivery idempotency (PRD 10).
    """
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT details
        FROM run_log
        WHERE job = %s AND as_of_date = %s AND status = 'OK'
    """
    cursor.execute(query, (job, target_date.isoformat()))
    rows = cursor.fetchall()
    cursor.close()

    for r in rows:
        try:
            d_json = json.loads(r["details"] or "{}")
        except json.JSONDecodeError:
            continue

        match = True
        if incident_key and d_json.get("incident_key") != incident_key:
            match = False
        if recipient and d_json.get("recipient") != recipient:
            match = False

        if match:
            return True

    return False

