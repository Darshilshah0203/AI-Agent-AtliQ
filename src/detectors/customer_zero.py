"""Customer stopped ordering detector."""

import datetime
from dataclasses import dataclass
from typing import List, Optional
from mysql.connector.connection import MySQLConnection

from src.alerts.customer_universe import get_active_customer_universe
from src.metrics import (
    compute_median,
    get_prior_4_same_weekdays,
    check_dates_exist_in_data,
    get_customer_sales_by_dates,
)


@dataclass
class CustomerZeroAlert:
    date: datetime.date
    customer: str
    market: str
    channel: str
    baseline: float
    actual: float = 0.0
    decline_pct: float = 100.0
    drop_dollars: float = 0.0

    def __post_init__(self):
        self.drop_dollars = round(self.baseline, 2)


def detect_customer_zero_orders(
    conn: MySQLConnection,
    target_date: datetime.date,
    baseline_min_threshold: float = 5000.0,
) -> List[CustomerZeroAlert]:
    """Detect customers that stopped ordering (placed zero orders on target_date).
    
    Rules:
    - 4 prior same-weekday dates must all exist in the sales dataset.
    - Customer placed zero orders on target_date (absent from v_sales_daily on that date).
    - Customer with reduced but non-zero orders does NOT receive a standalone alert.
    - Customer's same-weekday 4-week median baseline must be >= $5,000.
    """
    prior_dates = get_prior_4_same_weekdays(target_date)
    if not check_dates_exist_in_data(conn, prior_dates):
        # Missing 4-week comparison history; skip check
        return []

    # Expected customers from active universe
    expected_customers = get_active_customer_universe(conn, target_date)
    if not expected_customers:
        return []

    # Retrieve sales across all 5 dates (target_date + 4 prior dates)
    all_dates = [target_date] + prior_dates
    sales_map = get_customer_sales_by_dates(conn, all_dates)

    alerts: List[CustomerZeroAlert] = []
    for item in expected_customers:
        cust = item["customer"]
        market = item["market"]
        channel = item["channel"]

        actual = sales_map.get((cust, market, channel, target_date), 0.0)
        # Condition 1: Must have zero orders that day. Non-zero orders do NOT fire!
        if actual > 0.0:
            continue

        # Condition 2: Compute 4-week same-weekday median baseline
        hist_sales = [sales_map.get((cust, market, channel, d), 0.0) for d in prior_dates]
        baseline = compute_median(hist_sales)

        # Condition 3: Baseline must be >= $5,000
        if baseline >= baseline_min_threshold:
            alerts.append(
                CustomerZeroAlert(
                    date=target_date,
                    customer=cust,
                    market=market,
                    channel=channel,
                    baseline=round(baseline, 2),
                    actual=0.0,
                    decline_pct=100.0,
                    drop_dollars=round(baseline, 2),
                )
            )

    return alerts

