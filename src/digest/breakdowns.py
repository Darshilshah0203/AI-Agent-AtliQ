"""Dimensional breakdown calculations (Region & Category) for weekly digest."""

import datetime
from dataclasses import dataclass
from typing import Dict, List, Tuple
from mysql.connector.connection import MySQLConnection
from src.digest.scorecard import get_week_boundaries


@dataclass
class RegionBreakdown:
    region: str
    curr_net_sales: float
    prior_net_sales: float
    net_sales_change_pct: float
    curr_gross_margin_pct: float
    prior_gross_margin_pct: float
    curr_discount_pct: float
    prior_discount_pct: float


@dataclass
class CategoryBreakdown:
    category: str
    curr_units: int
    prior_units: int
    units_change_pct: float
    curr_price_per_unit: float
    prior_price_per_unit: float
    curr_cost_per_unit: float
    prior_cost_per_unit: float


def compute_regional_breakdown(
    conn: MySQLConnection,
    monday: datetime.date,
) -> List[RegionBreakdown]:
    """Compute week-over-week net sales, gross margin %, and discount % by region."""
    monday, sunday, prior_monday, prior_sunday = get_week_boundaries(monday)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT 
            region,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN net_sales ELSE 0 END) AS curr_sales,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN net_sales ELSE 0 END) AS prior_sales,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN gross_margin ELSE 0 END) AS curr_gm,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN gross_margin ELSE 0 END) AS prior_gm,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN post_invoice_discount ELSE 0 END) AS curr_disc,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN post_invoice_discount ELSE 0 END) AS prior_disc,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN net_invoice_sales ELSE 0 END) AS curr_nis,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN net_invoice_sales ELSE 0 END) AS prior_nis
        FROM v_sales_daily
        WHERE (date BETWEEN %s AND %s) OR (date BETWEEN %s AND %s)
        GROUP BY region
        ORDER BY curr_sales DESC
    """
    params = (
        monday, sunday, prior_monday, prior_sunday,
        monday, sunday, prior_monday, prior_sunday,
        monday, sunday, prior_monday, prior_sunday,
        monday, sunday, prior_monday, prior_sunday,
        monday, sunday, prior_monday, prior_sunday,
    )
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()

    breakdowns: List[RegionBreakdown] = []
    for r in rows:
        curr_sales = float(r["curr_sales"] or 0.0)
        prior_sales = float(r["prior_sales"] or 0.0)
        curr_gm = float(r["curr_gm"] or 0.0)
        prior_gm = float(r["prior_gm"] or 0.0)
        curr_disc = float(r["curr_disc"] or 0.0)
        prior_disc = float(r["prior_disc"] or 0.0)
        curr_nis = float(r["curr_nis"] or 0.0)
        prior_nis = float(r["prior_nis"] or 0.0)

        sales_change_pct = ((curr_sales - prior_sales) / prior_sales * 100.0) if prior_sales > 0 else 0.0
        curr_gm_pct = (curr_gm / curr_sales * 100.0) if curr_sales > 0 else 0.0
        prior_gm_pct = (prior_gm / prior_sales * 100.0) if prior_sales > 0 else 0.0
        curr_disc_pct = (curr_disc / curr_nis * 100.0) if curr_nis > 0 else 0.0
        prior_disc_pct = (prior_disc / prior_nis * 100.0) if prior_nis > 0 else 0.0

        breakdowns.append(
            RegionBreakdown(
                region=r["region"],
                curr_net_sales=round(curr_sales, 2),
                prior_net_sales=round(prior_sales, 2),
                net_sales_change_pct=round(sales_change_pct, 2),
                curr_gross_margin_pct=round(curr_gm_pct, 2),
                prior_gross_margin_pct=round(prior_gm_pct, 2),
                curr_discount_pct=round(curr_disc_pct, 2),
                prior_discount_pct=round(prior_disc_pct, 2),
            )
        )
    return breakdowns


def compute_category_breakdown(
    conn: MySQLConnection,
    monday: datetime.date,
) -> List[CategoryBreakdown]:
    """Compute week-over-week price per unit, cost per unit, and units by category."""
    monday, sunday, prior_monday, prior_sunday = get_week_boundaries(monday)
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT 
            category,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN sold_qty ELSE 0 END) AS curr_units,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN sold_qty ELSE 0 END) AS prior_units,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN gross_sales ELSE 0 END) AS curr_gs,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN gross_sales ELSE 0 END) AS prior_gs,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN manufacturing_cost ELSE 0 END) AS curr_cost,
            SUM(CASE WHEN date BETWEEN %s AND %s THEN manufacturing_cost ELSE 0 END) AS prior_cost
        FROM v_sales_daily
        WHERE (date BETWEEN %s AND %s) OR (date BETWEEN %s AND %s)
        GROUP BY category
        ORDER BY curr_units DESC
    """
    params = (
        monday, sunday, prior_monday, prior_sunday,
        monday, sunday, prior_monday, prior_sunday,
        monday, sunday, prior_monday, prior_sunday,
        monday, sunday, prior_monday, prior_sunday,
    )
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()

    breakdowns: List[CategoryBreakdown] = []
    for r in rows:
        curr_units = int(r["curr_units"] or 0)
        prior_units = int(r["prior_units"] or 0)
        curr_gs = float(r["curr_gs"] or 0.0)
        prior_gs = float(r["prior_gs"] or 0.0)
        curr_cost = float(r["curr_cost"] or 0.0)
        prior_cost = float(r["prior_cost"] or 0.0)

        units_change_pct = ((curr_units - prior_units) / prior_units * 100.0) if prior_units > 0 else 0.0
        curr_price = (curr_gs / curr_units) if curr_units > 0 else 0.0
        prior_price = (prior_gs / prior_units) if prior_units > 0 else 0.0
        curr_cpu = (curr_cost / curr_units) if curr_units > 0 else 0.0
        prior_cpu = (prior_cost / prior_units) if prior_units > 0 else 0.0

        breakdowns.append(
            CategoryBreakdown(
                category=r["category"],
                curr_units=curr_units,
                prior_units=prior_units,
                units_change_pct=round(units_change_pct, 2),
                curr_price_per_unit=round(curr_price, 2),
                prior_price_per_unit=round(prior_price, 2),
                curr_cost_per_unit=round(curr_cpu, 2),
                prior_cost_per_unit=round(prior_cpu, 2),
            )
        )
    return breakdowns

