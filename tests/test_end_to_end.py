"""Phase 5 Unit & End-to-End Tests: Delivery guard, single instance lock, run_log, and Gmail dispatch."""

import dataclasses
import datetime
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from src.config import load_config
from src.db import get_ro_connection
from src.delivery.run_log import log_run_event, check_prior_successful_delivery
from src.delivery.guard import can_deliver_report, DeliveryGuardError
from src.utils.lock import SingleInstanceLock, SingleInstanceError
from src.cli import build_parser, run_day_job


class TestPhase5EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def test_01_cli_parser_options(self):
        """CLI parser includes all PRD 11 required arguments."""
        parser = build_parser()
        args = parser.parse_args(["--scan", "--no-email", "--force"])
        self.assertTrue(args.scan)
        self.assertTrue(args.no_email)
        self.assertTrue(args.force)

        day_args = parser.parse_args(["--day", "2026-07-13"])
        self.assertEqual(day_args.day, "2026-07-13")

        week_args = parser.parse_args(["--week", "2026-09-21"])
        self.assertEqual(week_args.week, "2026-09-21")

    def test_02_single_instance_lock_blocks_concurrent_instance(self):
        """Holding SingleInstanceLock blocks a second simultaneous attempt."""
        lock_file = "test_agent.lock"
        with SingleInstanceLock(lock_file):
            with self.assertRaises(SingleInstanceError):
                with SingleInstanceLock(lock_file):
                    pass
        # After release, lock can be acquired again
        with SingleInstanceLock(lock_file):
            pass

    def test_03_run_log_persistence_and_structured_details(self):
        """Write and read structured job events in run_log table."""
        test_date = datetime.date(2026, 7, 13)
        details = {
            "job_type": "daily_check",
            "incident_key": "USA:Retailer:TestE2E",
            "recipient": "rachel.lee@atliq-demo.com",
            "gmail_message_id": "test_msg_id_12345",
        }

        with get_ro_connection(self.config) as conn:
            run_id = log_run_event(conn, "daily_check", test_date, "OK", details)
            self.assertIsNotNone(run_id)

            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT job, as_of_date, status, details FROM run_log WHERE run_id = %s", (run_id,))
            row = cursor.fetchone()
            self.assertEqual(row["job"], "daily_check")
            self.assertEqual(row["status"], "OK")

            d_parsed = json.loads(row["details"])
            self.assertEqual(d_parsed["incident_key"], "USA:Retailer:TestE2E")
            cursor.close()

    def test_04_delivery_guard_idempotency_and_force_rules(self):
        """Delivery guard prevents duplicate sends and restricts --force without TEST_INBOX."""
        test_date = datetime.date(2026, 7, 13)
        incident = "USA:Retailer:TestE2E"
        recipient = "rachel.lee@atliq-demo.com"

        with get_ro_connection(self.config) as conn:
            # 1. No email flag always blocks delivery
            can_send_no_email = can_deliver_report(
                conn, "daily_check", test_date, incident, recipient,
                force=False, no_email=True, config=self.config
            )
            self.assertFalse(can_send_no_email)

            # 2. Already sent without force is blocked
            can_send_duplicate = can_deliver_report(
                conn, "daily_check", test_date, incident, recipient,
                force=False, no_email=False, config=self.config
            )
            self.assertFalse(can_send_duplicate)

            # 3. Already sent with force AND TEST_INBOX is permitted
            config_with_test_inbox = dataclasses.replace(self.config, test_inbox="test@demo.com")
            can_send_force_test = can_deliver_report(
                conn, "daily_check", test_date, incident, recipient,
                force=True, no_email=False, config=config_with_test_inbox
            )
            self.assertTrue(can_send_force_test)

            # 4. Already sent with force WITHOUT TEST_INBOX raises DeliveryGuardError
            config_without_test_inbox = dataclasses.replace(self.config, test_inbox=None)
            with self.assertRaises(DeliveryGuardError):
                can_deliver_report(
                    conn, "daily_check", test_date, incident, recipient,
                    force=True, no_email=False, config=config_without_test_inbox
                )

    def test_05_live_dispatch_with_test_inbox(self):
        """Execute a full live daily check run with TEST_INBOX configured."""
        if not self.config.test_inbox:
            self.skipTest("TEST_INBOX not configured in .env")

        # Run day check on known July drop date with force (safe because TEST_INBOX is set)
        ret = run_day_job(target_date_str="2026-07-13", no_email=False, force=True)
        self.assertEqual(ret, 0)

        # Verify run_log row was written with status='OK' and message ID
        with get_ro_connection(self.config) as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT run_id, job, status, details
                FROM run_log
                WHERE job = 'daily_check' AND as_of_date = '2026-07-13' AND status = 'OK'
                ORDER BY run_id DESC LIMIT 1
                """
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "OK")
            details = json.loads(row["details"])
            self.assertIn("gmail_message_id", details)
            self.assertIsNotNone(details["gmail_message_id"])
            cursor.close()


if __name__ == "__main__":
    unittest.main()

