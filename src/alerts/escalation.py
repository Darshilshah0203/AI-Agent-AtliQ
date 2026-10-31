"""Incident continuity and consecutive-day escalation tracker."""

import datetime
from typing import Dict, List, Optional, Set
from mysql.connector.connection import MySQLConnection

from src.alerts.resolver import ConsolidatedAlert, Owner
from src.detectors.market_channel import detect_market_channel_drops
from src.detectors.customer_zero import detect_customer_zero_orders


def get_failed_daily_checks(conn: MySQLConnection) -> Set[datetime.date]:
    """Retrieve all dates where daily_check recorded status='ERROR' in run_log."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT as_of_date FROM run_log WHERE job = 'daily_check' AND status = 'ERROR'")
    rows = cursor.fetchall()
    cursor.close()
    failed = set()
    for r in rows:
        d = r["as_of_date"]
        if isinstance(d, datetime.date):
            failed.add(d)
        elif d:
            failed.add(datetime.date.fromisoformat(str(d)))
    return failed


def evaluate_escalation_day(
    conn: MySQLConnection,
    alert: ConsolidatedAlert,
    max_lookback_days: int = 14,
) -> ConsolidatedAlert:
    """Determine consecutive-day escalation level (Day 1, Day 2, Day 3+).
    
    Rules (PRD 5.4):
    - Consecutive calendar days issue remains present (D-1, D-2, etc.).
    - Day 1: Send to primary resolved owner only (copy_owner is None).
    - Day 2: Copy next owner level up once (copy_owner set to supervisor).
    - Day 3+: Keep original owner and copy only next level up; do not climb further.
    - If primary owner is region head, there is no higher level (copy_owner is None).
    - Failed daily checks must NOT count as continuing or resolved. If continuity
      is ambiguous due to a failed run, mark escalation as unconfirmed.
    """
    failed_dates = get_failed_daily_checks(conn)
    current_date = alert.date
    consecutive_days = 1
    confirmed = True

    # Check previous consecutive calendar days
    for day_offset in range(1, max_lookback_days + 1):
        prev_date = current_date - datetime.timedelta(days=day_offset)

        if prev_date in failed_dates:
            # Cannot infer continuity across a failed run
            confirmed = False
            break

        # Reconstruct issue presence on prev_date
        prev_drops = detect_market_channel_drops(conn, prev_date)
        prev_custs = detect_customer_zero_orders(conn, prev_date)

        issue_present = False
        if alert.market_channel_baseline is not None:
            # Check if market/channel drop occurred on prev_date
            if any(d.market == alert.market and d.channel == alert.channel for d in prev_drops):
                issue_present = True

        if alert.affected_customers:
            # Check if any affected customer was zero-order on prev_date
            if any(
                c.market == alert.market and c.channel == alert.channel and c.customer in alert.affected_customers
                for c in prev_custs
            ):
                issue_present = True

        if issue_present:
            consecutive_days += 1
        else:
            # Issue was not present on prev_date; continuity chain ends
            break

    alert.escalation_day = consecutive_days
    alert.escalation_confirmed = confirmed

    # Apply recipient escalation rules
    if alert.escalation_day == 1:
        # Day 1: Primary owner only
        alert.copy_owner = None
    else:
        # Day 2, 3+: Copy next level up once (supervisor), if available
        # If primary owner is already region head, supervisor is already None
        pass

    return alert


def apply_escalation_to_all(
    conn: MySQLConnection,
    alerts: List[ConsolidatedAlert],
) -> List[ConsolidatedAlert]:
    """Calculate escalation days and recipient copy lists for all alerts."""
    return [evaluate_escalation_day(conn, a) for a in alerts]

