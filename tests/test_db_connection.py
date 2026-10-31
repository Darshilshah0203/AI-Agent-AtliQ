"""Phase 1 Verification Tests: Database connection and permission segregation."""

import unittest
import mysql.connector
from src.config import Config, load_config
from src.db import get_ro_connection, get_ingest_connection


class TestPhase1DatabaseConnection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def test_01_config_validation_and_masking(self):
        """Test configuration loader, required keys, and credential masking."""
        self.assertEqual(self.config.mysql_user, "agent_ro")
        self.assertEqual(self.config.mysql_ingest_user, "agent_ingest")
        self.assertEqual(self.config.mysql_db, "atliq_digest")

        # Verify secrets are masked in __repr__
        config_repr = repr(self.config)
        self.assertNotIn("AgentRead2026", config_repr)
        self.assertNotIn("AgentIngest2026", config_repr)
        self.assertIn("mysql_password='***'", config_repr)
        self.assertIn("mysql_ingest_password='***'", config_repr)

    def test_02_agent_ro_can_read_views_and_tables(self):
        """Verify agent_ro can read v_sales_daily, targets_daily, owners, and settings."""
        with get_ro_connection(self.config) as conn:
            cursor = conn.cursor(dictionary=True)

            # Read settings.as_of_date
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'as_of_date'")
            row = cursor.fetchone()
            self.assertIsNotNone(row, "settings table must have 'as_of_date'")
            self.assertEqual(row["setting_value"], "2026-09-30", "Initial as_of_date should be 2026-09-30")

            # Read v_sales_daily
            cursor.execute("SELECT date, market, channel, customer, net_sales FROM v_sales_daily LIMIT 1")
            sales_row = cursor.fetchone()
            self.assertIsNotNone(sales_row, "v_sales_daily view must be readable")

            # Read targets_daily
            cursor.execute("SELECT date, region, net_sales_target FROM targets_daily LIMIT 1")
            target_row = cursor.fetchone()
            self.assertIsNotNone(target_row, "targets_daily must be readable")

            # Read owners
            cursor.execute("SELECT region, market, channel, name, email FROM owners LIMIT 1")
            owner_row = cursor.fetchone()
            self.assertIsNotNone(owner_row, "owners must be readable")

            cursor.close()

    def test_03_agent_ro_can_write_run_log(self):
        """Verify agent_ro has INSERT and SELECT permissions on run_log."""
        with get_ro_connection(self.config) as conn:
            cursor = conn.cursor(dictionary=True)

            # Insert a phase 1 verification test record
            cursor.execute(
                """
                INSERT INTO run_log (run_at, job, as_of_date, status, details)
                VALUES (NOW(), 'daily_check', '2026-09-30', 'OK', 'Phase 1 test_agent_ro_can_write_run_log')
                """
            )
            # Retrieve the inserted record
            cursor.execute("SELECT run_id, job, status FROM run_log WHERE details = 'Phase 1 test_agent_ro_can_write_run_log' ORDER BY run_id DESC LIMIT 1")
            record = cursor.fetchone()
            self.assertIsNotNone(record)
            self.assertEqual(record["job"], "daily_check")
            self.assertEqual(record["status"], "OK")

            # Clean up test record
            try:
                cursor.execute("DELETE FROM run_log WHERE run_id = %s", (record["run_id"],))
            except mysql.connector.Error:
                pass  # agent_ro may not have DELETE permission on run_log; that is fine as per spec

            cursor.close()

    def test_04_agent_ro_forbidden_from_updating_settings_or_raw_tables(self):
        """Verify agent_ro CANNOT write to settings or silver source tables."""
        with get_ro_connection(self.config) as conn:
            cursor = conn.cursor()

            # Attempt to update settings with agent_ro - must fail with permission error
            with self.assertRaises(mysql.connector.Error) as ctx:
                cursor.execute("UPDATE settings SET setting_value = '2026-10-01' WHERE setting_key = 'as_of_date'")
            self.assertIn("command denied", str(ctx.exception).lower())

            # Attempt to read silver raw table sales_orders - must fail
            with self.assertRaises(mysql.connector.Error) as ctx:
                cursor.execute("SELECT COUNT(*) FROM sales_orders")
            self.assertIn("command denied", str(ctx.exception).lower())

            cursor.close()

    def test_05_agent_ingest_permissions_and_boundaries(self):
        """Verify agent_ingest can read sales_orders and update settings, but not v_sales_daily."""
        with get_ingest_connection(self.config) as conn:
            cursor = conn.cursor(dictionary=True)

            # Ingest can read sales_orders
            cursor.execute("SELECT MAX(date) AS max_date FROM sales_orders")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertIsNotNone(row["max_date"], "sales_orders should contain orders up to Oct 2026")

            # Ingest can read and update settings (test update back to 2026-09-30)
            cursor.execute("UPDATE settings SET setting_value = '2026-09-30' WHERE setting_key = 'as_of_date'")
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'as_of_date'")
            setting_row = cursor.fetchone()
            self.assertEqual(setting_row["setting_value"], "2026-09-30")

            # Ingest CANNOT read v_sales_daily
            with self.assertRaises(mysql.connector.Error) as ctx:
                cursor.execute("SELECT * FROM v_sales_daily LIMIT 1")
            self.assertIn("command denied", str(ctx.exception).lower())

            # Ingest CANNOT write to run_log
            with self.assertRaises(mysql.connector.Error) as ctx:
                cursor.execute("INSERT INTO run_log (run_at, job, as_of_date, status, details) VALUES (NOW(), 'new_data', '2026-09-30', 'OK', 'test')")
            self.assertIn("command denied", str(ctx.exception).lower())

            cursor.close()


if __name__ == "__main__":
    unittest.main()

