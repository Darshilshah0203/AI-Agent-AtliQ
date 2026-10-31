"""Main entry point for AtliQ Morning Digest Agent (Daily 8:00 AM Scheduled Runner)."""

import datetime
import sys
from typing import Optional

from src.config import Config, load_config
from src.db import get_ro_connection
from src.freshness import advance_as_of_date, get_current_as_of_date
from src.cli import run_day_job, run_week_job
from src.digest.scorecard import get_week_boundaries
from src.utils.lock import SingleInstanceLock, SingleInstanceError


def get_latest_completed_week_monday(as_of_date: datetime.date) -> Optional[datetime.date]:
    """Find the Monday of the latest completed Monday-to-Sunday week <= as_of_date."""
    # Find the latest Sunday <= as_of_date
    offset_to_prev_sunday = (as_of_date.weekday() + 1) % 7
    if as_of_date.weekday() == 6:  # Today is Sunday
        latest_sunday = as_of_date
    else:
        latest_sunday = as_of_date - datetime.timedelta(days=as_of_date.weekday() + 1)

    latest_monday = latest_sunday - datetime.timedelta(days=6)
    return latest_monday


def run_daily_agent(config: Optional[Config] = None) -> int:
    """Execute the full 8:00 AM daily scheduled run."""
    print("=" * 75)
    print("AtliQ Morning Digest Agent - Daily Execution Run (8:00 AM)")
    print(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    if config is None:
        config = load_config()

    try:
        with SingleInstanceLock("agent.lock"):
            # Step 1: Advance as_of_date to newest available order date <= yesterday
            print("\n[Step 1/3] Checking data freshness and advancing as_of_date...")
            old_as_of, new_as_of, newly_eligible_dates = advance_as_of_date(config)
            print(f"  as_of_date status: {old_as_of} -> {new_as_of} ({len(newly_eligible_dates)} newly eligible dates)")

            # Step 2: Sequential daily drop checks in chronological order
            print("\n[Step 2/3] Processing daily drop checks sequentially...")
            if not newly_eligible_dates:
                print("  No new dates to evaluate today.")
            else:
                for target_date in newly_eligible_dates:
                    print(f"\nProcessing eligible date: {target_date}...")
                    ret = run_day_job(target_date_str=target_date.isoformat(), no_email=False, force=False)
                    if ret != 0:
                        print(f"  [CRITICAL] Daily check for {target_date} failed. Sequential processing halted to preserve consecutive-day escalation.")
                        break

            # Step 3: Check weekly digest eligibility
            print("\n[Step 3/3] Evaluating weekly digest eligibility...")
            current_as_of = get_current_as_of_date(config)
            latest_monday = get_latest_completed_week_monday(current_as_of)

            if latest_monday:
                print(f"  Latest completed week starts on Monday: {latest_monday}")
                # run_week_job checks idempotency; will send if not already delivered
                run_week_job(monday_str=latest_monday.isoformat(), no_email=False, force=False)
            else:
                print("  No completed Monday-to-Sunday week available yet.")

            print("\n" + "=" * 75)
            print("AtliQ Morning Digest Agent Daily Run Finished Successfully!")
            print("=" * 75)
            return 0

    except SingleInstanceError as sie:
        print(f"[PROCESS LOCK] {sie}")
        return 1
    except Exception as e:
        print(f"[FATAL ERROR] Agent encountered an unexpected exception: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_daily_agent())

