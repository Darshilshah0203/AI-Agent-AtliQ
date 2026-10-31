"""Phase 3 Unit Tests: Safe SQL tool validator, AI investigation loop, and escalation reports."""

import datetime
import os
import unittest
from unittest.mock import MagicMock, patch

from src.config import load_config
from src.alerts.resolver import (
    Owner,
    AlertType,
    ConsolidatedAlert,
)
from src.ai.sql_tool import validate_ai_sql, execute_ai_sql, SQLSecurityError
from src.ai.drop_investigator import (
    DropInvestigationResult,
    generate_fallback_investigation,
    investigate_drop,
)
from src.reports.email_alert import build_escalation_email
from src.reports.word_alert import (
    build_escalation_docx,
    get_escalation_docx_path,
    sanitize_filename_part,
)


class TestPhase3AIInvestigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def test_01_sql_validator_allows_valid_query(self):
        """Valid query on v_sales_daily passes validation and has LIMIT 30 enforced."""
        q = "SELECT customer, product, SUM(net_sales) FROM v_sales_daily WHERE market = 'USA' GROUP BY customer, product"
        validated = validate_ai_sql(q)
        self.assertTrue(validated.startswith("SELECT"))
        self.assertIn("v_sales_daily", validated)
        self.assertIn("LIMIT 30", validated)

    def test_02_sql_validator_rejects_unauthorized_tables_and_writes(self):
        """Security validator rejects writes, metadata queries, and unauthorized tables."""
        # Forbidden write
        with self.assertRaises(SQLSecurityError):
            validate_ai_sql("UPDATE v_sales_daily SET net_sales = 0")

        with self.assertRaises(SQLSecurityError):
            validate_ai_sql("DELETE FROM v_sales_daily WHERE date = '2026-07-13'")

        # Multiple statements
        with self.assertRaises(SQLSecurityError):
            validate_ai_sql("SELECT * FROM v_sales_daily; DROP TABLE owners")

        # Forbidden tables
        with self.assertRaises(SQLSecurityError):
            validate_ai_sql("SELECT * FROM sales_orders LIMIT 5")

        with self.assertRaises(SQLSecurityError):
            validate_ai_sql("SELECT * FROM targets_daily")

        with self.assertRaises(SQLSecurityError):
            validate_ai_sql("SELECT * FROM information_schema.tables")

    def test_03_sql_validator_caps_excessive_limit(self):
        """LIMIT > 30 is capped to LIMIT 30."""
        q = "SELECT customer FROM v_sales_daily LIMIT 100"
        validated = validate_ai_sql(q)
        self.assertIn("LIMIT 30", validated)
        self.assertNotIn("LIMIT 100", validated)

    def test_04_execute_safe_sql_against_database(self):
        """Executing validated SQL against v_sales_daily returns at most 30 rows."""
        q = "SELECT date, market, channel, customer, net_sales FROM v_sales_daily WHERE date = '2026-07-13' LIMIT 5"
        rows, validated = execute_ai_sql(q, self.config)
        self.assertTrue(len(rows) <= 30)
        self.assertTrue(len(rows) > 0)
        self.assertIn("customer", rows[0])

    def test_05_investigation_fallback_on_missing_or_failed_ai(self):
        """When live AI key is missing or fails, report generates factual numbers and 'Analysis incomplete'."""
        import dataclasses
        mock_config = dataclasses.replace(self.config, groq_api_key="mock_fallback_key")
        primary = Owner(9, "North America", "USA", "Retailer", "Rachel Lee", "USA Retail Lead", "rachel@atliq.com")
        alert = ConsolidatedAlert(
            date=datetime.date(2026, 7, 13),
            market="USA",
            channel="Retailer",
            alert_type=AlertType.COMBINED,
            primary_owner=primary,
            escalation_day=1,
            market_channel_baseline=391488.88,
            market_channel_actual=94940.15,
            market_channel_decline_pct=75.75,
            affected_customers=["ElectroHub USA"],
            customer_baselines={"ElectroHub USA": 297628.83},
        )

        res = investigate_drop(alert, mock_config)
        self.assertIn("ElectroHub USA", res.likely_causes)
        self.assertIn("Analysis incomplete", res.analysis_status)
        self.assertEqual(res.confidence, "partial")

    def test_06_email_alert_generation_accessibility_and_inline_css(self):
        """HTML email has single-column inline styles, accessibility text, and matching plain text."""
        primary = Owner(9, "North America", "USA", "Retailer", "Rachel Lee", "USA Retail Lead", "rachel@atliq.com")
        alert = ConsolidatedAlert(
            date=datetime.date(2026, 7, 13),
            market="USA",
            channel="Retailer",
            alert_type=AlertType.COMBINED,
            primary_owner=primary,
            escalation_day=1,
            market_channel_baseline=391488.88,
            market_channel_actual=94940.15,
            market_channel_decline_pct=75.75,
            affected_customers=["ElectroHub USA"],
            customer_baselines={"ElectroHub USA": 297628.83},
        )
        inv = generate_fallback_investigation(alert, "Test run")

        html_body, plain_text = build_escalation_email(alert, inv)

        # Accessibility checks
        self.assertIn("[Needs attention]", html_body)
        self.assertIn("[Needs attention]", plain_text)
        self.assertIn("-75.75%", html_body)
        self.assertIn("ElectroHub USA", html_body)
        self.assertIn("Rachel Lee", html_body)

        # Inline style safety: no external stylesheets, no scripts
        self.assertNotIn("<link rel=\"stylesheet\"", html_body)
        self.assertNotIn("<script", html_body)
        self.assertIn("max-width: 600px", html_body)

    def test_07_word_docx_report_generation_and_naming(self):
        """Word escalation report is generated at sanitized path with correct formatting."""
        primary = Owner(9, "North America", "USA", "Retailer", "Rachel Lee", "USA Retail Lead", "rachel@atliq.com")
        alert = ConsolidatedAlert(
            date=datetime.date(2026, 7, 13),
            market="USA",
            channel="Retailer",
            alert_type=AlertType.COMBINED,
            primary_owner=primary,
            escalation_day=1,
            market_channel_baseline=391488.88,
            market_channel_actual=94940.15,
            market_channel_decline_pct=75.75,
            affected_customers=["ElectroHub USA"],
            customer_baselines={"ElectroHub USA": 297628.83},
        )
        inv = generate_fallback_investigation(alert, "Test run")

        docx_path = build_escalation_docx(alert, inv, output_dir="escalations")
        self.assertTrue(os.path.exists(docx_path))
        self.assertTrue(docx_path.endswith("USA_Retailer_2026-07-13.docx"))
        self.assertGreater(os.path.getsize(docx_path), 5000)


if __name__ == "__main__":
    unittest.main()

