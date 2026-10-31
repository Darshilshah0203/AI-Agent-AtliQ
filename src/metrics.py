"""Metric calculations and 4-week same-weekday median baselines."""

import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Union
from mysql.connector.connection import MySQLConnection


def compute_median(values: List[float]) -> float:
    """Calculate the mathematical median of a list of numeric values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    else:
        return float((sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0)


def get_prior_4_same_weekdays(target_date: datetime.date) -> List[datetime.date]:
    """Return the 4 same-weekday dates preceding target_date (D-7, D-14, D-21, D-28)."""
    return [target_date - datetime.timedelta(days=7 * i) for i in range(1, 5)]


def check_dates_exist_in_data(
    conn: MySQLConnection,
    dates: List[datetime.date],
) -> bool:
    """Verify that all target historical dates exist in v_sales_daily (completeness check)."""
    if not dates:
        return False

    cursor = conn.cursor(dictionary=True)
    format_strings = ",".join(["%s"] * len(dates))
    query = f"""
        SELECT DISTINCT date
        FROM v_sales_daily
        WHERE date IN ({format_strings})
    """
    date_strs = [d.isoformat() for d in dates]
    cursor.execute(query, date_strs)
    found_dates = {row["date"] if isinstance(row["date"], datetime.date) else datetime.date.fromisoformat(str(row["date"])) for row in cursor.fetchall()}
    cursor.close()

    # All 4 dates must be present in the sales dataset
    return len(found_dates) == len(dates)


def get_market_channel_sales_by_dates(
    conn: MySQLConnection,
    dates: List[datetime.date],
) -> Dict[Tuple[str, str, datetime.date], float]:
    """Retrieve aggregate net_sales for each market, channel, and date in the list."""
    if not dates:
        return {}

    cursor = conn.cursor(dictionary=True)
    format_strings = ",".join(["%s"] * len(dates))
    query = f"""
        SELECT market, channel, date, SUM(net_sales) AS total_net_sales
        FROM v_sales_daily
        WHERE date IN ({format_strings})
        GROUP BY market, channel, date
    """
    date_strs = [d.isoformat() for d in dates]
    cursor.execute(query, date_strs)
    results = {}
    for row in cursor.fetchall():
        d = row["date"] if isinstance(row["date"], datetime.date) else datetime.date.fromisoformat(str(row["date"]))
        results[(row["market"], row["channel"], d)] = float(row["total_net_sales"] or 0.0)
    cursor.close()
    return results


def get_customer_sales_by_dates(
    conn: MySQLConnection,
    dates: List[datetime.date],
) -> Dict[Tuple[str, str, str, datetime.date], float]:
    """Retrieve aggregate net_sales for each customer, market, channel, and date in the list."""
    if not dates:
        return {}

    cursor = conn.cursor(dictionary=True)
    format_strings = ",".join(["%s"] * len(dates))
    query = f"""
        SELECT customer, market, channel, date, SUM(net_sales) AS total_net_sales
        FROM v_sales_daily
        WHERE date IN ({format_strings})
        GROUP BY customer, market, channel, date
    """
    date_strs = [d.isoformat() for d in dates]
    cursor.execute(query, date_strs)
    results = {}
    for row in cursor.fetchall():
        d = row["date"] if isinstance(row["date"], datetime.date) else datetime.date.fromisoformat(str(row["date"]))
        results[(row["customer"], row["market"], row["channel"], d)] = float(row["total_net_sales"] or 0.0)
    cursor.close()
    return results

