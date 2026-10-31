"""Data freshness and as_of_date advancement engine."""

import datetime
import json
from typing import List, Optional, Tuple
import mysql.connector

from src.config import Config, load_config
from src.db import get_ro_connection, get_ingest_connection


def get_current_as_of_date(config: Optional[Config] = None) -> datetime.date:
    """Read the current as_of_date from settings via agent_ro."""
    if config is None:
        config = load_config()

    with get_ro_connection(config) as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'as_of_date'")
        row = cursor.fetchone()
        cursor.close()

    if not row or not row["setting_value"]:
        raise ValueError("Missing 'as_of_date' in settings table.")

    return datetime.date.fromisoformat(str(row["setting_value"]))


def get_max_order_date(config: Optional[Config] = None) -> Optional[datetime.date]:
    """Read the maximum order date from sales_orders via agent_ingest."""
    if config is None:
        config = load_config()

    with get_ingest_connection(config) as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT MAX(date) AS max_date FROM sales_orders")
        row = cursor.fetchone()
        cursor.close()

    if not row or not row["max_date"]:
        return None

    if isinstance(row["max_date"], datetime.date):
        return row["max_date"]
    return datetime.date.fromisoformat(str(row["max_date"]))


def advance_as_of_date(
    config: Optional[Config] = None,
    reference_today: Optional[datetime.date] = None,
    dry_run: bool = False,
) -> Tuple[datetime.date, datetime.date, List[datetime.date]]:
    """Evaluate and advance as_of_date if newer eligible complete-day sales data exists.
    
    Rules:
    - Complete days only.
    - Never advance beyond yesterday (reference_today - 1 day).
    - Never analyze today.
    - Updates settings.as_of_date using agent_ingest.
    - Logs the freshness step in run_log using agent_ro.
    - Returns (old_as_of_date, new_as_of_date, newly_eligible_dates_in_order).
    """
    if config is None:
        config = load_config()

    if reference_today is None:
        reference_today = datetime.date.today()

    yesterday = reference_today - datetime.timedelta(days=1)
    current_as_of = get_current_as_of_date(config)
    max_order = get_max_order_date(config)

    if not max_order:
        return current_as_of, current_as_of, []

    # Target date is newest order date, but never later than yesterday
    eligible_target = min(max_order, yesterday)

    if eligible_target <= current_as_of:
        # Already up to date or no newer complete date
        return current_as_of, current_as_of, []

    # Generate sequence of newly eligible dates in chronological order
    new_dates: List[datetime.date] = []
    curr = current_as_of + datetime.timedelta(days=1)
    while curr <= eligible_target:
        new_dates.append(curr)
        curr += datetime.timedelta(days=1)

    if not dry_run:
        # Update settings.as_of_date via agent_ingest
        with get_ingest_connection(config) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE settings SET setting_value = %s WHERE setting_key = 'as_of_date'",
                (eligible_target.isoformat(),),
            )
            cursor.close()

        # Log new_data job in run_log via agent_ro
        with get_ro_connection(config) as conn:
            cursor = conn.cursor()
            details_json = json.dumps({
                "job_type": "new_data",
                "old_as_of_date": current_as_of.isoformat(),
                "new_as_of_date": eligible_target.isoformat(),
                "new_dates_count": len(new_dates),
                "first_date": new_dates[0].isoformat(),
                "last_date": new_dates[-1].isoformat(),
            })
            cursor.execute(
                """
                INSERT INTO run_log (run_at, job, as_of_date, status, details)
                VALUES (NOW(), 'new_data', %s, 'OK', %s)
                """,
                (eligible_target.isoformat(), details_json),
            )
            cursor.close()

    return current_as_of, eligible_target, new_dates

