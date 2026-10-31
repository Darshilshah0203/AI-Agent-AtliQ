"""Active customer universe discovery from v_sales_daily."""

import datetime
from typing import Dict, List, Set, Tuple
from mysql.connector.connection import MySQLConnection


CustomerKey = Tuple[str, str, str]  # (customer, market, channel)


def get_active_customer_universe(
    conn: MySQLConnection,
    target_date: datetime.date,
    lookback_days: int = 28,
) -> List[Dict[str, str]]:
    """Derive the expected active customer universe for target_date.
    
    Since agent_ro cannot access silver dim_customer and v_sales_daily omits
    zero-order days, the expected active customer population is derived from
    historical orders in v_sales_daily during the baseline lookback window.
    """
    start_date = target_date - datetime.timedelta(days=lookback_days)
    end_date = target_date - datetime.timedelta(days=1)

    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT DISTINCT customer, market, channel
        FROM v_sales_daily
        WHERE date BETWEEN %s AND %s
        ORDER BY market, channel, customer
    """
    cursor.execute(query, (start_date.isoformat(), end_date.isoformat()))
    rows = cursor.fetchall()
    cursor.close()

    return rows

