"""Company scorecard calculation engine for weekly digest."""

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from mysql.connector.connection import MySQLConnection


@dataclass
class WeeklyScorecard:
    monday: datetime.date
    sunday: datetime.date
    prior_monday: datetime.date
    prior_sunday: datetime.date
    
    # Current Week Core Metrics
    net_sales: float
    gross_margin: float
    gross_margin_pct: float
    units_sold: int
    
    # Prior Week Core Metrics
    prior_net_sales: float
    prior_gross_margin: float
    prior_gross_margin_pct: float
    prior_units_sold: int
    
    # Week-over-Week Changes
    net_sales_change: float
    net_sales_change_pct: float
    gross_margin_change: float
    gross_margin_change_pct: float
    gross_margin_pct_change: float  # Percentage point change
    units_change: int
    units_change_pct: float
    
    # Target (Net Sales only)
    net_sales_target: float
    net_sales_vs_target_dollars: float
    net_sales_vs_target_pct: float
    
    # Impact Projections
    money_impact: float              # Change in gross margin $
    monthly_projected_impact: float  # Money impact * 52 / 12


def get_week_boundaries(monday: datetime.date) -> Tuple[datetime.date, datetime.date, datetime.date, datetime.date]:
    """Calculate current Monday-Sunday and prior Monday-Sunday boundaries."""
    if monday.weekday() != 0:
        raise ValueError(f"Supplied date {monday} is not a Monday (weekday {monday.weekday()}).")
    sunday = monday + datetime.timedelta(days=6)
    prior_monday = monday - datetime.timedelta(days=7)
    prior_sunday = monday - datetime.timedelta(days=1)
    return monday, sunday, prior_monday, prior_sunday


def compute_weekly_scorecard(
    conn: MySQLConnection,
    monday: datetime.date,
) -> WeeklyScorecard:
    """Compute pure code scorecard metrics for completed Monday-to-Sunday week vs prior week.
    
    Strict rules (PRD 7.2):
    - All scorecard values calculated by code, not AI.
    - Only Net Sales has a target from targets_daily; no invented targets for others.
    - Money impact is the change in gross margin dollars.
    - Monthly projected impact is change in gross margin $ * 52 / 12.
    """
    monday, sunday, prior_monday, prior_sunday = get_week_boundaries(monday)

    cursor = conn.cursor(dictionary=True)

    # 1. Query Current Week Aggregates
    cursor.execute(
        """
        SELECT 
            SUM(net_sales) AS net_sales,
            SUM(gross_margin) AS gross_margin,
            SUM(sold_qty) AS units_sold
        FROM v_sales_daily
        WHERE date BETWEEN %s AND %s
        """,
        (monday.isoformat(), sunday.isoformat()),
    )
    curr_row = cursor.fetchone() or {}
    net_sales = float(curr_row.get("net_sales") or 0.0)
    gross_margin = float(curr_row.get("gross_margin") or 0.0)
    units_sold = int(curr_row.get("units_sold") or 0)
    gross_margin_pct = (gross_margin / net_sales * 100.0) if net_sales > 0 else 0.0

    # 2. Query Prior Week Aggregates
    cursor.execute(
        """
        SELECT 
            SUM(net_sales) AS net_sales,
            SUM(gross_margin) AS gross_margin,
            SUM(sold_qty) AS units_sold
        FROM v_sales_daily
        WHERE date BETWEEN %s AND %s
        """,
        (prior_monday.isoformat(), prior_sunday.isoformat()),
    )
    prior_row = cursor.fetchone() or {}
    prior_net_sales = float(prior_row.get("net_sales") or 0.0)
    prior_gross_margin = float(prior_row.get("gross_margin") or 0.0)
    prior_units_sold = int(prior_row.get("units_sold") or 0)
    prior_gross_margin_pct = (prior_gross_margin / prior_net_sales * 100.0) if prior_net_sales > 0 else 0.0

    # 3. Query Targets for Current Week (Sum across regions and 7 days)
    cursor.execute(
        """
        SELECT SUM(net_sales_target) AS total_target
        FROM targets_daily
        WHERE date BETWEEN %s AND %s
        """,
        (monday.isoformat(), sunday.isoformat()),
    )
    target_row = cursor.fetchone() or {}
    net_sales_target = float(target_row.get("total_target") or 0.0)
    cursor.close()

    # 4. Compute Deltas
    net_sales_change = net_sales - prior_net_sales
    net_sales_change_pct = (net_sales_change / prior_net_sales * 100.0) if prior_net_sales > 0 else 0.0

    gross_margin_change = gross_margin - prior_gross_margin
    gross_margin_change_pct = (gross_margin_change / prior_gross_margin * 100.0) if prior_gross_margin > 0 else 0.0
    gross_margin_pct_change = gross_margin_pct - prior_gross_margin_pct

    units_change = units_sold - prior_units_sold
    units_change_pct = (units_change / prior_units_sold * 100.0) if prior_units_sold > 0 else 0.0

    net_sales_vs_target_dollars = net_sales - net_sales_target
    net_sales_vs_target_pct = (net_sales_vs_target_dollars / net_sales_target * 100.0) if net_sales_target > 0 else 0.0

    # 5. Money impact & Monthly projection
    money_impact = gross_margin_change
    monthly_projected_impact = (money_impact * 52.0) / 12.0

    return WeeklyScorecard(
        monday=monday,
        sunday=sunday,
        prior_monday=prior_monday,
        prior_sunday=prior_sunday,
        net_sales=round(net_sales, 2),
        gross_margin=round(gross_margin, 2),
        gross_margin_pct=round(gross_margin_pct, 2),
        units_sold=units_sold,
        prior_net_sales=round(prior_net_sales, 2),
        prior_gross_margin=round(prior_gross_margin, 2),
        prior_gross_margin_pct=round(prior_gross_margin_pct, 2),
        prior_units_sold=prior_units_sold,
        net_sales_change=round(net_sales_change, 2),
        net_sales_change_pct=round(net_sales_change_pct, 2),
        gross_margin_change=round(gross_margin_change, 2),
        gross_margin_change_pct=round(gross_margin_change_pct, 2),
        gross_margin_pct_change=round(gross_margin_pct_change, 2),
        units_change=units_change,
        units_change_pct=round(units_change_pct, 2),
        net_sales_target=round(net_sales_target, 2),
        net_sales_vs_target_dollars=round(net_sales_vs_target_dollars, 2),
        net_sales_vs_target_pct=round(net_sales_vs_target_pct, 2),
        money_impact=round(money_impact, 2),
        monthly_projected_impact=round(monthly_projected_impact, 2),
    )

