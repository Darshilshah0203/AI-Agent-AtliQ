"""Phase 1 Verification Test Suite.

Checks:
1. Approved dependencies import.
2. .env configuration loads and validates required keys.
3. agent_ro can SELECT from views/tables but UPDATE is denied.
4. agent_ingest can read sales_orders.
5. Single-instance lock works as expected.
"""

import os
import sys
import msvcrt

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def check_dependencies() -> None:
    """Check 1: Approved dependencies import."""
    try:
        import mysql.connector
        import dotenv
        import groq
        import docx
        import googleapiclient.discovery
        import google.auth
    except ImportError as e:
        print(f"[FAIL] Dependency import failed: {e}")
        sys.exit(1)
    print("[PASS] Dependencies imported successfully (mysql-connector, python-dotenv, groq, python-docx, google-api-client, google-auth)")


def check_config() -> None:
    """Check 2: .env config loads and validates."""
    from src.config import load_config
    try:
        config = load_config()
        assert config.mysql_user == "agent_ro"
        assert config.mysql_ingest_user == "agent_ingest"
        assert config.mysql_db == "atliq_digest"
        assert config.groq_model == "openai/gpt-oss-120b"
    except Exception as e:
        print(f"[FAIL] .env config loading failed: {e}")
        sys.exit(1)
    print("[PASS] .env configuration loaded and validated")


def check_agent_ro_permissions() -> None:
    """Check 3: agent_ro can SELECT but UPDATE is denied."""
    import mysql.connector
    from src.config import load_config
    from src.db import get_ro_connection

    config = load_config()
    with get_ro_connection(config) as conn:
        cursor = conn.cursor(dictionary=True)

        # SELECT must succeed
        cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'as_of_date'")
        row = cursor.fetchone()
        assert row is not None, "settings.as_of_date row missing"
        assert row["setting_value"] == "2026-09-30", f"Unexpected as_of_date: {row['setting_value']}"

        cursor.execute("SELECT date, market, channel, customer, net_sales FROM v_sales_daily LIMIT 1")
        sales_row = cursor.fetchone()
        assert sales_row is not None, "v_sales_daily must be readable"

        # UPDATE must be denied
        update_denied = False
        try:
            cursor.execute("UPDATE settings SET setting_value = '2026-10-01' WHERE setting_key = 'as_of_date'")
        except mysql.connector.Error as err:
            if "command denied" in str(err).lower():
                update_denied = True
            else:
                print(f"[FAIL] Unexpected error during UPDATE: {err}")
        cursor.close()

    assert update_denied, "Security violation: agent_ro was able to execute UPDATE on settings!"
    print("[PASS] agent_ro can SELECT but UPDATE is denied")


def check_agent_ingest_permissions() -> None:
    """Check 4: agent_ingest can read sales_orders."""
    from src.config import load_config
    from src.db import get_ingest_connection

    config = load_config()
    with get_ingest_connection(config) as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS total_rows, MAX(date) AS newest_date FROM sales_orders")
        row = cursor.fetchone()
        assert row is not None, "sales_orders query returned no result"
        assert row["total_rows"] > 0, "sales_orders table is empty"
        assert str(row["newest_date"]) == "2026-10-04", f"Unexpected max date: {row['newest_date']}"
        cursor.close()
    print(f"[PASS] agent_ingest can read sales_orders ({row['total_rows']} rows, max date: {row['newest_date']})")


def check_single_instance_lock() -> None:
    """Check 5: Single-instance lock mechanism works."""
    lock_file = "agent.lock"
    # Process 1 acquires lock
    f1 = open(lock_file, "a+")
    f1.seek(0)
    msvcrt.locking(f1.fileno(), msvcrt.LK_NBLCK, 1)

    # Process 2 attempts lock - must fail
    second_lock_failed = False
    try:
        f2 = open(lock_file, "a+")
        f2.seek(0)
        msvcrt.locking(f2.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        second_lock_failed = True
    finally:
        f2.close()

    # Process 1 releases lock
    msvcrt.locking(f1.fileno(), msvcrt.LK_UNLCK, 1)
    f1.close()

    # Clean up lock file
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
        except OSError:
            pass

    assert second_lock_failed, "Single-instance lock failed: concurrent process was able to acquire lock"
    print("[PASS] Single-instance lock works (concurrent acquisition blocked)")


def main() -> None:
    print("=" * 65)
    print("Running Phase 1 Verification Checks (tests/test_phase1.py)")
    print("=" * 65)
    check_dependencies()
    check_config()
    check_agent_ro_permissions()
    check_agent_ingest_permissions()
    check_single_instance_lock()
    print("=" * 65)
    print("All Phase 1 checks PASSED!")
    print("=" * 65)


if __name__ == "__main__":
    main()
