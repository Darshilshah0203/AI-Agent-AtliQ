"""Market-and-channel sales drop detector."""

import datetime
from dataclasses import dataclass
from typing import List, Optional
from mysql.connector.connection import MySQLConnection

from src.metrics import (
    compute_median,
    get_prior_4_same_weekdays,
    check_dates_exist_in_data,
    get_market_channel_sales_by_dates,
)


@dataclass
class MarketChannelDrop:
    date: datetime.date
    market: str
    channel: str
    baseline: float
    actual: float
    decline_pct: float
    drop_dollars: float


def detect_market_channel_drops(
    conn: MySQLConnection,
    target_date: datetime.date,
    baseline_min_threshold: float = 5000.0,
    drop_pct_threshold: float = 0.30,
) -> List[MarketChannelDrop]:
    """Detect market-and-channel sales drops strictly exceeding 30% below baseline.
    
    Rules:
    - 4 prior same-weekday dates must all exist in the sales dataset.
    - Baseline is the median net sales over the 4 prior same-weekday dates.
    - Baseline must be >= $5,000.
    - Decline must be strictly greater than 30% (decline > 0.30). Exactly 30% does NOT trigger.
    """
    prior_dates = get_prior_4_same_weekdays(target_date)
    if not check_dates_exist_in_data(conn, prior_dates):
        # Missing 4-week historical comparison dates; skip check
        return []

    # Retrieve sales across all 5 dates (target_date + 4 prior dates)
    all_dates = [target_date] + prior_dates
    sales_map = get_market_channel_sales_by_dates(conn, all_dates)

    # Identify all (market, channel) pairs active in any of these dates
    pairs = {(m, c) for (m, c, d) in sales_map.keys()}

    drops: List[MarketChannelDrop] = []
    for market, channel in sorted(pairs):
        historical_sales = [sales_map.get((market, channel, d), 0.0) for d in prior_dates]
        baseline = compute_median(historical_sales)

        if baseline < baseline_min_threshold:
            continue

        actual = sales_map.get((market, channel, target_date), 0.0)
        decline_pct = (baseline - actual) / baseline

        # Strictly greater than 30% (0.30)
        if decline_pct > drop_pct_threshold:
            drops.append(
                MarketChannelDrop(
                    date=target_date,
                    market=market,
                    channel=channel,
                    baseline=round(baseline, 2),
                    actual=round(actual, 2),
                    decline_pct=round(decline_pct * 100, 2),
                    drop_dollars=round(baseline - actual, 2),
                )
            )

    return drops

