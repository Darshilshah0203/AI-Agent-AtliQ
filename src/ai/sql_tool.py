"""Safe SQL tool and security validator for AI investigation."""

import re
from typing import Any, Dict, List, Optional, Tuple
from mysql.connector.connection import MySQLConnection
import mysql.connector

from src.db import get_ro_connection
from src.config import Config, load_config


class SQLSecurityError(Exception):
    """Raised when an AI-generated SQL query violates security constraints."""
    pass


FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "REPLACE", "GRANT", "REVOKE", "INTO OUTFILE", "INTO DUMPFILE",
    "LOAD_FILE", "BENCHMARK", "SLEEP", "INFORMATION_SCHEMA",
    "PERFORMANCE_SCHEMA", "SYS.", "MYSQL.", "EXEC", "CALL"
]


def validate_ai_sql(query: str) -> str:
    """Validate AI-generated SQL against PRD 6.1 security rules.
    
    Constraints:
    - Exactly one SELECT statement.
    - Read only from v_sales_daily.
    - No writes, stored procedures, or metadata table access.
    - Max 30 rows enforced.
    """
    clean_query = query.strip()
    if clean_query.endswith(";"):
        clean_query = clean_query[:-1].strip()

    # 1. Reject multiple statements
    if ";" in clean_query:
        raise SQLSecurityError("Multiple SQL statements are strictly forbidden.")

    # 2. Must start with SELECT
    upper_query = clean_query.upper()
    if not upper_query.startswith("SELECT"):
        raise SQLSecurityError("Query must begin with SELECT.")

    # 3. Check forbidden write/system keywords
    for kw in FORBIDDEN_KEYWORDS:
        # Match whole word or keyword pattern
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, upper_query):
            raise SQLSecurityError(f"Forbidden SQL keyword detected: {kw}")

    # 4. Strictly verify table source: only v_sales_daily is permitted
    from_join_pattern = r"\b(?:FROM|JOIN)\s+([a-zA-Z0-9_]+)"
    referenced_tables = re.findall(from_join_pattern, clean_query, flags=re.IGNORECASE)
    if not referenced_tables:
        raise SQLSecurityError("Query must reference a table via FROM clause.")

    for tbl in referenced_tables:
        if tbl.lower() != "v_sales_daily":
            raise SQLSecurityError(
                f"Unauthorized table reference: '{tbl}'. AI analysis is strictly restricted to 'v_sales_daily'."
            )

    # 5. Enforce row limit (maximum 30 rows)
    limit_match = re.search(r"\bLIMIT\s+(\d+)", clean_query, flags=re.IGNORECASE)
    if limit_match:
        requested_limit = int(limit_match.group(1))
        if requested_limit > 30:
            clean_query = re.sub(
                r"\bLIMIT\s+\d+",
                "LIMIT 30",
                clean_query,
                flags=re.IGNORECASE,
            )
    else:
        clean_query = f"{clean_query} LIMIT 30"

    return clean_query


def execute_ai_sql(
    query: str,
    config: Optional[Config] = None,
    query_timeout_ms: int = 3000,
) -> Tuple[List[Dict[str, Any]], str]:
    """Validate, print, and execute AI-generated SQL query using agent_ro.
    
    Returns (result_rows, executed_query).
    """
    if config is None:
        config = load_config()

    validated_query = validate_ai_sql(query)
    print(f"  [AI SQL Tool] Executing: {validated_query}")

    with get_ro_connection(config, query_timeout_ms=query_timeout_ms) as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(validated_query)
            rows = cursor.fetchall()
            # Enforce 30 row max cap as second safeguard
            capped_rows = rows[:30]
            cursor.close()
            return capped_rows, validated_query
        except mysql.connector.Error as err:
            cursor.close()
            raise SQLSecurityError(f"Database execution error: {err}")


SQL_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "execute_sql",
        "description": "Execute a single read-only SQL SELECT query against v_sales_daily. Max 30 rows returned.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A single SQL SELECT statement querying v_sales_daily.",
                }
            },
            "required": ["query"],
        },
    },
}

