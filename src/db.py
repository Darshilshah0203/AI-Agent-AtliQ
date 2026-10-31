"""Database connection managers for AtliQ Morning Digest Agent."""

import contextlib
from typing import Generator, Optional
import mysql.connector
from mysql.connector.connection import MySQLConnection
from src.config import Config, load_config


def create_connection(
    user: str,
    password: str,
    config: Optional[Config] = None,
    connect_timeout: int = 5,
) -> MySQLConnection:
    """Create a MySQL connection for a specific user."""
    if config is None:
        config = load_config()

    conn = mysql.connector.connect(
        host=config.mysql_host,
        port=config.mysql_port,
        database=config.mysql_db,
        user=user,
        password=password,
        connection_timeout=connect_timeout,
        autocommit=True,
    )
    return conn


@contextlib.contextmanager
def get_ro_connection(
    config: Optional[Config] = None,
    query_timeout_ms: int = 3000,
) -> Generator[MySQLConnection, None, None]:
    """Context manager for read-only agent_ro connection.
    
    Used for reading v_sales_daily, targets_daily, owners, settings,
    and reading/writing run_log.
    """
    if config is None:
        config = load_config()

    conn = create_connection(
        user=config.mysql_user,
        password=config.mysql_password,
        config=config,
    )
    try:
        # Enforce read-only query timeout if MySQL server supports max_execution_time
        try:
            cursor = conn.cursor()
            cursor.execute(f"SET SESSION max_execution_time = {query_timeout_ms}")
            cursor.close()
        except mysql.connector.Error:
            pass  # Fall back gracefully if max_execution_time is not supported
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def get_ingest_connection(
    config: Optional[Config] = None,
) -> Generator[MySQLConnection, None, None]:
    """Context manager for agent_ingest connection.
    
    Strictly used for reading sales_orders and updating settings.as_of_date.
    """
    if config is None:
        config = load_config()

    conn = create_connection(
        user=config.mysql_ingest_user,
        password=config.mysql_ingest_password,
        config=config,
    )
    try:
        yield conn
    finally:
        conn.close()

