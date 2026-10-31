"""Alert consolidation and owner recipient hierarchy resolver."""

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
from mysql.connector.connection import MySQLConnection

from src.detectors.market_channel import MarketChannelDrop
from src.detectors.customer_zero import CustomerZeroAlert


class AlertType(str, Enum):
    COMBINED = "combined"
    MARKET_CHANNEL = "market_channel"
    CUSTOMER_ZERO = "customer_zero"


@dataclass
class Owner:
    owner_id: int
    region: str
    market: Optional[str]
    channel: Optional[str]
    name: str
    role: str
    email: str


@dataclass
class ConsolidatedAlert:
    date: datetime.date
    market: str
    channel: str
    alert_type: AlertType
    primary_owner: Owner
    copy_owner: Optional[Owner] = None
    escalation_day: int = 1
    escalation_confirmed: bool = True
    
    # Financial metrics
    market_channel_baseline: Optional[float] = None
    market_channel_actual: Optional[float] = None
    market_channel_decline_pct: Optional[float] = None
    
    # Zero-order customers
    affected_customers: List[str] = field(default_factory=list)
    customer_baselines: Dict[str, float] = field(default_factory=dict)
    
    @property
    def incident_key(self) -> str:
        """Deterministic incident key for tracking continuity."""
        if self.alert_type == AlertType.CUSTOMER_ZERO and len(self.affected_customers) == 1:
            return f"{self.market}:{self.channel}:{self.affected_customers[0]}"
        return f"{self.market}:{self.channel}"


DEFAULT_MARKET_REGION_MAP: Dict[str, str] = {
    "Australia": "APAC",
    "Brazil": "LATAM",
    "Canada": "North America",
    "France": "EU",
    "Germany": "EU",
    "India": "APAC",
    "Indonesia": "APAC",
    "Italy": "EU",
    "Japan": "APAC",
    "Mexico": "LATAM",
    "Philippines": "APAC",
    "South Korea": "APAC",
    "UAE": "MEA",
    "United Kingdom": "EU",
    "USA": "North America",
}


def get_market_region_map(
    conn: MySQLConnection,
    reference_date: Optional[datetime.date] = None,
) -> Dict[str, str]:
    """Map each market to its corresponding region using v_sales_daily.
    
    Filters by reference_date to keep query time under 50ms and within the 3s timeout.
    Falls back to DEFAULT_MARKET_REGION_MAP.
    """
    mapping = dict(DEFAULT_MARKET_REGION_MAP)
    cursor = conn.cursor(dictionary=True)
    try:
        if reference_date:
            cursor.execute(
                "SELECT DISTINCT market, region FROM v_sales_daily WHERE date = %s",
                (reference_date.isoformat(),),
            )
        else:
            cursor.execute(
                "SELECT DISTINCT market, region FROM v_sales_daily WHERE date = "
                "(SELECT setting_value FROM settings WHERE setting_key = 'as_of_date')"
            )
        for row in cursor.fetchall():
            mapping[row["market"]] = row["region"]
    except Exception:
        pass
    finally:
        cursor.close()
    return mapping


def load_owners(conn: MySQLConnection) -> List[Owner]:
    """Load all owners from owners table."""
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT owner_id, region, market, channel, name, role, email FROM owners")
    rows = cursor.fetchall()
    cursor.close()
    return [
        Owner(
            owner_id=row["owner_id"],
            region=row["region"],
            market=row["market"] if row["market"] else None,
            channel=row["channel"] if row["channel"] else None,
            name=row["name"],
            role=row["role"],
            email=row["email"],
        )
        for row in rows
    ]


def resolve_owner_hierarchy(
    market: str,
    channel: str,
    owners: List[Owner],
    market_region_map: Dict[str, str],
) -> Tuple[Owner, Optional[Owner]]:
    """Resolve primary owner and immediate supervisor (next level up) in hierarchy.
    
    Hierarchy rules:
    - Level 1: Market + Channel
    - Level 2: Market
    - Level 3: Region head
    
    Returns (primary_owner, next_level_up_owner).
    If primary owner is already region head, next_level_up_owner is None.
    """
    region = market_region_map.get(market)

    # 1. Look for market + channel match
    mc_owner = next(
        (o for o in owners if o.market == market and o.channel == channel),
        None,
    )

    # 2. Look for market match (channel empty)
    m_owner = next(
        (o for o in owners if o.market == market and not o.channel),
        None,
    )

    # 3. Look for region head (market and channel empty)
    r_owner = next(
        (o for o in owners if o.region == region and not o.market and not o.channel),
        None,
    )

    if mc_owner:
        primary = mc_owner
        supervisor = m_owner or r_owner
    elif m_owner:
        primary = m_owner
        supervisor = r_owner
    elif r_owner:
        primary = r_owner
        supervisor = None
    else:
        # Fallback if unmapped: find any regional owner or first owner
        primary = owners[0]
        supervisor = None

    return primary, supervisor


def consolidate_alerts(
    market_drops: List[MarketChannelDrop],
    customer_alerts: List[CustomerZeroAlert],
    owners: List[Owner],
    market_region_map: Dict[str, str],
) -> List[ConsolidatedAlert]:
    """Merge overlapping market/channel drops and zero-order customer alerts on same date, market, channel.
    
    Rules (PRD 5.3):
    - If market-and-channel drop and zero-order customer occur in same market, channel, and date:
      produce ONE combined alert naming customer(s).
    - If only customer condition fires: standalone customer alert.
    - If only market-and-channel drop fires: market-channel alert.
    """
    # Group customer alerts by (market, channel)
    cust_by_mc: Dict[Tuple[str, str], List[CustomerZeroAlert]] = {}
    for ca in customer_alerts:
        cust_by_mc.setdefault((ca.market, ca.channel), []).append(ca)

    drops_by_mc: Dict[Tuple[str, str], MarketChannelDrop] = {
        (md.market, md.channel): md for md in market_drops
    }

    all_keys = set(drops_by_mc.keys()).union(set(cust_by_mc.keys()))
    consolidated: List[ConsolidatedAlert] = []

    for market, channel in sorted(all_keys):
        m_drop = drops_by_mc.get((market, channel))
        c_list = cust_by_mc.get((market, channel), [])

        primary_owner, supervisor = resolve_owner_hierarchy(
            market=market,
            channel=channel,
            owners=owners,
            market_region_map=market_region_map,
        )

        date = (m_drop.date if m_drop else c_list[0].date)

        if m_drop and c_list:
            # COMBINED alert
            alert = ConsolidatedAlert(
                date=date,
                market=market,
                channel=channel,
                alert_type=AlertType.COMBINED,
                primary_owner=primary_owner,
                copy_owner=supervisor,
                market_channel_baseline=m_drop.baseline,
                market_channel_actual=m_drop.actual,
                market_channel_decline_pct=m_drop.decline_pct,
                affected_customers=[c.customer for c in c_list],
                customer_baselines={c.customer: c.baseline for c in c_list},
            )
        elif m_drop:
            # MARKET_CHANNEL drop only
            alert = ConsolidatedAlert(
                date=date,
                market=market,
                channel=channel,
                alert_type=AlertType.MARKET_CHANNEL,
                primary_owner=primary_owner,
                copy_owner=supervisor,
                market_channel_baseline=m_drop.baseline,
                market_channel_actual=m_drop.actual,
                market_channel_decline_pct=m_drop.decline_pct,
            )
        else:
            # CUSTOMER_ZERO standalone alert
            alert = ConsolidatedAlert(
                date=date,
                market=market,
                channel=channel,
                alert_type=AlertType.CUSTOMER_ZERO,
                primary_owner=primary_owner,
                copy_owner=supervisor,
                affected_customers=[c.customer for c in c_list],
                customer_baselines={c.customer: c.baseline for c in c_list},
            )

        consolidated.append(alert)

    return consolidated
