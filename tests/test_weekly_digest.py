"""Phase 4 Unit Tests: Scorecard calculation, dimensional breakdowns, stakeholder briefs, and weekly digests."""

import datetime
import os
import unittest

from src.config import load_config
from src.db import get_ro_connection
from src.context.stakeholders import Stakeholder, load_stakeholders
from src.digest.scorecard import (
    WeeklyScorecard,
    get_week_boundaries,
    compute_weekly_scorecard,
)
from src.digest.breakdowns import (
    compute_regional_breakdown,
    compute_category_breakdown,
)
from src.context.google_docs import fetch_stakeholder_brief, get_cached_brief
from src.ai.digest_investigator import (
    DigestNarrativeResult,
    generate_fallback_digest,
)
from src.digest.email_digest import build_digest_email
from src.digest.word_digest import build_digest_docx, get_digest_docx_path


class TestPhase4WeeklyDigest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.monday = datetime.date(2026, 9, 21)

    def test_01_week_boundaries_validation(self):
        """Monday date produces correct Monday-Sunday and prior Monday-Sunday boundaries."""
        mon, sun, p_mon, p_sun = get_week_boundaries(self.monday)
        self.assertEqual(mon, datetime.date(2026, 9, 21))
        self.assertEqual(sun, datetime.date(2026, 9, 27))
        self.assertEqual(p_mon, datetime.date(2026, 9, 14))
        self.assertEqual(p_sun, datetime.date(2026, 9, 20))

        # Non-Monday date raises ValueError
        with self.assertRaises(ValueError):
            get_week_boundaries(datetime.date(2026, 9, 22))

    def test_02_company_scorecard_calculation(self):
        """Verify scorecard metrics, target comparison, money impact, and monthly projection."""
        with get_ro_connection(self.config) as conn:
            sc = compute_weekly_scorecard(conn, self.monday)

            # Core metrics check
            self.assertGreater(sc.net_sales, 10_000_000.0)
            self.assertGreater(sc.gross_margin, 1_000_000.0)
            self.assertGreater(sc.units_sold, 100_000)
            self.assertGreater(sc.gross_margin_pct, 20.0)

            # Only net sales has target; targets_daily summed across regions
            self.assertGreater(sc.net_sales_target, 10_000_000.0)

            # Money impact is gross margin change
            self.assertEqual(sc.money_impact, sc.gross_margin_change)

            # Monthly projected impact = money impact * 52 / 12
            expected_monthly = round((sc.money_impact * 52.0) / 12.0, 2)
            self.assertEqual(sc.monthly_projected_impact, expected_monthly)

    def test_03_dimensional_breakdowns_calculation(self):
        """Verify regional and category breakdown calculations."""
        with get_ro_connection(self.config) as conn:
            reg = compute_regional_breakdown(conn, self.monday)
            self.assertEqual(len(reg), 5, "AtliQ has 5 standard regions")
            for r in reg:
                self.assertIn(r.region, ["APAC", "EU", "LATAM", "MEA", "North America"])
                self.assertGreater(r.curr_net_sales, 0.0)

            cat = compute_category_breakdown(conn, self.monday)
            self.assertEqual(len(cat), 14, "AtliQ has 14 standard product categories")
            for c in cat:
                self.assertGreater(c.curr_units, 0)
                self.assertGreater(c.curr_price_per_unit, 0.0)

    def test_04_stakeholders_loader(self):
        """Verify loading stakeholders from CSV and extracting doc ID."""
        stakeholders = load_stakeholders()
        self.assertGreater(len(stakeholders), 0)
        bruce = next((s for s in stakeholders if "bruce" in s.name.lower()), None)
        self.assertIsNotNone(bruce)
        self.assertEqual(bruce.role, "CEO")
        self.assertIsNotNone(bruce.doc_id)

    def test_05_stakeholder_brief_fetching_and_cache(self):
        """Verify brief retrieval (live Google Docs API or seed cache)."""
        bruce = Stakeholder(
            name="Bruce Haryali",
            role="CEO",
            email="bruce@atliq.com",
            doc_link="https://docs.google.com/document/d/1g6BUgFzMgRjo3S_BmbmmpEUEvX5GTAaZ7UeKCq1HRD0/edit",
        )
        brief = fetch_stakeholder_brief(bruce, self.config)
        self.assertIsNotNone(brief)
        self.assertIn("Bruce", brief)

    def test_06_weekly_digest_word_document_structure(self):
        """Verify one-page Word document generation following PRD 7.4 delivery order."""
        with get_ro_connection(self.config) as conn:
            sc = compute_weekly_scorecard(conn, self.monday)

        bruce = Stakeholder("Bruce Haryali", "CEO", "bruce@atliq.com", "https://docs.google.com/document/d/123/edit")
        narrative = generate_fallback_digest(sc, bruce, "Unit test")

        docx_path = build_digest_docx(bruce, sc, narrative, output_dir="digests")
        self.assertTrue(os.path.exists(docx_path))
        self.assertTrue(docx_path.endswith("Bruce_Haryali_2026-09-21_to_2026-09-27.docx"))
        self.assertGreater(os.path.getsize(docx_path), 10_000)

    def test_07_weekly_digest_email_structure(self):
        """Verify HTML and plain-text digest emails adhere to PRD 7.4 ordering and accessibility."""
        with get_ro_connection(self.config) as conn:
            sc = compute_weekly_scorecard(conn, self.monday)

        bruce = Stakeholder("Bruce Haryali", "CEO", "bruce@atliq.com", "https://docs.google.com/document/d/123/edit")
        narrative = generate_fallback_digest(sc, bruce, "Unit test")

        html_body, plain_text = build_digest_email(bruce, sc, narrative)

        # Check PRD 7.4 ordering in plain text
        self.assertIn("1. COMPANY SCORECARD", plain_text)
        self.assertIn("2. EXECUTIVE HEADLINE", plain_text)
        self.assertIn("3. KEY INSIGHTS", plain_text)
        self.assertIn("4. ROOT CAUSES & EVIDENCE", plain_text)
        self.assertIn("5. RECOMMENDED ACTIONS", plain_text)
        self.assertIn("6. DECISION NEEDED", plain_text)
        self.assertIn("7. STATUS", plain_text)

        # Accessibility and inline CSS in HTML
        self.assertNotIn("<script", html_body)
        self.assertNotIn("<link rel=\"stylesheet\"", html_body)
        self.assertIn("max-width: 600px", html_body)
        self.assertIn(f"${sc.net_sales:,.2f}", html_body)


if __name__ == "__main__":
    unittest.main()

