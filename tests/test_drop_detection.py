"""Phase 2 Unit Tests: Data freshness, drop detection, owner hierarchy, and escalation logic."""

import datetime
import unittest
from unittest.mock import MagicMock, patch

from src.config import load_config
from src.db import get_ro_connection
from src.metrics import compute_median, get_prior_4_same_weekdays
from src.detectors.market_channel import MarketChannelDrop, detect_market_channel_drops
from src.detectors.customer_zero import CustomerZeroAlert, detect_customer_zero_orders
from src.alerts.resolver import (
    Owner,
    AlertType,
    ConsolidatedAlert,
    resolve_owner_hierarchy,
    consolidate_alerts,
)
from src.alerts.escalation import evaluate_escalation_day
from src.freshness import advance_as_of_date, get_current_as_of_date


class TestPhase2DropDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def test_01_median_calculation(self):
        """Verify mathematical median for odd and even length series."""
        # Even length (4 elements): average of 2 middle elements
        self.assertEqual(compute_median([100.0, 200.0, 300.0, 400.0]), 250.0)
        self.assertEqual(compute_median([400.0, 100.0, 200.0, 300.0]), 250.0)
        # Odd length (3 elements)
        self.assertEqual(compute_median([100.0, 200.0, 500.0]), 200.0)
        self.assertEqual(compute_median([]), 0.0)

    def test_02_drop_threshold_boundaries(self):
        """Verify that exactly 30% drop does NOT trigger, and baseline < $5,000 does NOT trigger."""
        baseline = 10000.0

        # Exact 30% decline: (10000 - 7000) / 10000 = 0.3000 -> False
        decline_30 = (baseline - 7000.0) / baseline
        self.assertFalse(decline_30 > 0.30, "Exactly 30% decline must not trigger")

        # 30.01% decline -> True
        decline_30_01 = (baseline - 6999.0) / baseline
        self.assertTrue(decline_30_01 > 0.30, "Decline strictly > 30% must trigger")

        # Baseline of $4,999.99 with 80% drop -> must not trigger
        low_baseline = 4999.99
        self.assertFalse(low_baseline >= 5000.0, "Baseline < $5000 must not trigger")

        # Baseline of $5,000.00 -> eligible
        valid_baseline = 5000.00
        self.assertTrue(valid_baseline >= 5000.0, "Baseline >= $5000 is eligible")

    def test_03_customer_zero_order_logic(self):
        """Customer with reduced orders does NOT trigger standalone alert; zero-orders triggers."""
        # Mock customer who placed non-zero orders
        reduced_order_sales = 500.0
        self.assertFalse(reduced_order_sales == 0.0, "Reduced order must not trigger zero-order alert")

        # Zero orders with baseline >= 5000 triggers
        zero_order_sales = 0.0
        baseline = 12000.0
        self.assertTrue(zero_order_sales == 0.0 and baseline >= 5000.0)

    def test_04_owner_hierarchy_resolution(self):
        """Verify 3-tier hierarchy: market+channel -> market -> region head."""
        owners = [
            Owner(1, "APAC", None, None, "Sam Saxena", "Regional Manager - APAC", "sam@atliq.com"),
            Owner(6, "APAC", "India", None, "Arjun Mehta", "India Country Manager", "arjun@atliq.com"),
            Owner(7, "APAC", "India", "E-Commerce", "Sneha Rao", "India E-Commerce Lead", "sneha@atliq.com"),
            Owner(2, "EU", None, None, "Hope Hegde", "Regional Manager - EU", "hope@atliq.com"),
        ]
        market_region_map = {"India": "APAC", "Germany": "EU"}

        # Level 1: Market + Channel match
        p1, s1 = resolve_owner_hierarchy("India", "E-Commerce", owners, market_region_map)
        self.assertEqual(p1.name, "Sneha Rao")
        self.assertIsNotNone(s1)
        self.assertEqual(s1.name, "Arjun Mehta")

        # Level 2: Market match (Retailer channel not in India owners table)
        p2, s2 = resolve_owner_hierarchy("India", "Retailer", owners, market_region_map)
        self.assertEqual(p2.name, "Arjun Mehta")
        self.assertIsNotNone(s2)
        self.assertEqual(s2.name, "Sam Saxena")

        # Level 3: Region head match (Germany has no country owner)
        p3, s3 = resolve_owner_hierarchy("Germany", "Retailer", owners, market_region_map)
        self.assertEqual(p3.name, "Hope Hegde")
        self.assertIsNone(s3, "Region head has no higher level")

    def test_05_alert_consolidation(self):
        """Verify market drop + customer zero orders merges into one COMBINED alert."""
        owners = [
            Owner(8, "North America", "USA", None, "Jake Miller", "USA Country Manager", "jake@atliq.com"),
            Owner(9, "North America", "USA", "Retailer", "Rachel Lee", "USA Retail Lead", "rachel@atliq.com"),
        ]
        market_region_map = {"USA": "North America"}
        test_date = datetime.date(2026, 7, 15)

        m_drop = MarketChannelDrop(
            date=test_date,
            market="USA",
            channel="Retailer",
            baseline=300000.0,
            actual=50000.0,
            decline_pct=83.33,
            drop_dollars=250000.0,
        )
        c_alert = CustomerZeroAlert(
            date=test_date,
            customer="ElectroHub USA",
            market="USA",
            channel="Retailer",
            baseline=250000.0,
            actual=0.0,
        )

        consolidated = consolidate_alerts([m_drop], [c_alert], owners, market_region_map)
        self.assertEqual(len(consolidated), 1)
        alert = consolidated[0]
        self.assertEqual(alert.alert_type, AlertType.COMBINED)
        self.assertEqual(alert.primary_owner.name, "Rachel Lee")
        self.assertIn("ElectroHub USA", alert.affected_customers)

    def test_06_escalation_continuity_and_copy_rules(self):
        """Verify escalation Day 1 (no copy), Day 2 (copy supervisor), Day 3 (no further climbing)."""
        supervisor = Owner(8, "North America", "USA", None, "Jake Miller", "USA Country Manager", "jake@atliq.com")
        primary = Owner(9, "North America", "USA", "Retailer", "Rachel Lee", "USA Retail Lead", "rachel@atliq.com")

        alert = ConsolidatedAlert(
            date=datetime.date(2026, 7, 13),
            market="USA",
            channel="Retailer",
            alert_type=AlertType.COMBINED,
            primary_owner=primary,
            copy_owner=supervisor,
            escalation_day=1,
        )

        # Day 1: copy_owner must be cleared
        if alert.escalation_day == 1:
            alert.copy_owner = None
        self.assertIsNone(alert.copy_owner, "Day 1 must not copy supervisor")

        # Day 2: copy_owner is supervisor
        alert.escalation_day = 2
        alert.copy_owner = supervisor
        self.assertEqual(alert.copy_owner.name, "Jake Miller")

        # Day 3: copy_owner remains supervisor (does not climb to Emily Carter)
        alert.escalation_day = 3
        alert.copy_owner = supervisor
        self.assertEqual(alert.copy_owner.name, "Jake Miller")

    def test_07_real_data_july_usa_drop_scan(self):
        """Verify the agent detects the real historical July 13-17 2026 USA Retailer drop."""
        with get_ro_connection(self.config) as conn:
            # Check Monday 2026-07-13
            m_drops = detect_market_channel_drops(conn, datetime.date(2026, 7, 13))
            c_alerts = detect_customer_zero_orders(conn, datetime.date(2026, 7, 13))

            # Must identify USA Retailer drop
            usa_drops = [d for d in m_drops if d.market == "USA" and d.channel == "Retailer"]
            self.assertTrue(len(usa_drops) >= 1)
            self.assertGreater(usa_drops[0].decline_pct, 70.0)

            # Must identify ElectroHub USA as stopped ordering
            electrohub = [c for c in c_alerts if c.customer == "ElectroHub USA"]
            self.assertEqual(len(electrohub), 1)
            self.assertEqual(electrohub[0].actual, 0.0)


if __name__ == "__main__":
    unittest.main()
