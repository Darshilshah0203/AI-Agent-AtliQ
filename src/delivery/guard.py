"""Delivery guard enforcing idempotency, --force safety, and --no-email rules."""

import datetime
from typing import Optional
from mysql.connector.connection import MySQLConnection

from src.config import Config, load_config
from src.delivery.run_log import check_prior_successful_delivery


class DeliveryGuardError(Exception):
    """Raised when delivery rules or resend constraints are violated."""
    pass


def can_deliver_report(
    conn: MySQLConnection,
    job: str,
    target_date: datetime.date,
    incident_key: Optional[str] = None,
    recipient: Optional[str] = None,
    force: bool = False,
    no_email: bool = False,
    config: Optional[Config] = None,
) -> bool:
    """Determine whether report delivery may proceed.
    
    Rules (PRD Section 10):
    1. If no_email is True: return False (do not send).
    2. Check if report was already sent (status='OK' in run_log).
    3. If already sent:
       - If force is False: skip delivery.
       - If force is True:
         - Resending permitted ONLY if TEST_INBOX is configured.
         - If TEST_INBOX is NOT set: refuse to resend to real recipients!
    """
    if config is None:
        config = load_config()

    if no_email:
        return False

    already_sent = check_prior_successful_delivery(
        conn=conn,
        job=job,
        target_date=target_date,
        incident_key=incident_key,
        recipient=recipient,
    )

    if not already_sent:
        return True

    # Report has already been successfully delivered previously
    if not force:
        print(f"  [Idempotency Notice] Report for {target_date} ({incident_key or recipient}) already sent (status=OK). Skipping resend.")
        return False

    # Force is requested: verify TEST_INBOX safety guard
    if not config.test_inbox:
        raise DeliveryGuardError(
            f"Safety violation: --force cannot resend reports to real recipient '{recipient}'. "
            "Resending with --force is strictly permitted only when TEST_INBOX is set."
        )

    print(f"  [Force Notice] --force requested with TEST_INBOX configured. Resending to test inbox ({config.test_inbox}).")
    return True

