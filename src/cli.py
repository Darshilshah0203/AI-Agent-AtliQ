"""Unified Command Line Interface for AtliQ Morning Digest Agent."""

import argparse
import datetime
import sys
from typing import List, Optional

from src.config import load_config
from src.db import get_ro_connection, get_ingest_connection
from src.freshness import (
    get_current_as_of_date,
    get_max_order_date,
    advance_as_of_date,
)
from src.detectors.market_channel import detect_market_channel_drops
from src.detectors.customer_zero import detect_customer_zero_orders
from src.alerts.resolver import (
    load_owners,
    get_market_region_map,
    consolidate_alerts,
    AlertType,
)
from src.alerts.escalation import apply_escalation_to_all
from src.ai.drop_investigator import investigate_drop
from src.reports.email_alert import build_escalation_email
from src.reports.word_alert import build_escalation_docx
from src.digest.scorecard import compute_weekly_scorecard, get_week_boundaries
from src.digest.breakdowns import compute_regional_breakdown, compute_category_breakdown
from src.context.stakeholders import load_stakeholders
from src.context.google_docs import fetch_stakeholder_brief
from src.ai.digest_investigator import investigate_digest
from src.digest.email_digest import build_digest_email
from src.digest.word_digest import build_digest_docx
from src.delivery.gmail import send_email_via_gmail
from src.delivery.run_log import log_run_event
from src.delivery.guard import can_deliver_report, DeliveryGuardError
from src.utils.lock import SingleInstanceLock, SingleInstanceError


def run_test_db() -> int:
    """Run database diagnostics and verify user privilege boundaries (Phase 1)."""
    print("=" * 60)
    print("AtliQ Morning Digest Agent - Database Diagnostics")
    print("=" * 60)

    try:
        config = load_config()
        print(f"Configuration loaded: host={config.mysql_host}, port={config.mysql_port}, db={config.mysql_db}")
        print(f"Config summary: {config!r}")
    except Exception as e:
        print(f"[FAIL] Configuration error: {e}")
        return 1

    print("\n[1/3] Testing agent_ro (read-only + run_log)...")
    try:
        with get_ro_connection(config) as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = 'as_of_date'")
            as_of_row = cursor.fetchone()
            as_of_date = as_of_row["setting_value"] if as_of_row else "NOT FOUND"
            print(f"  [OK] Read settings.as_of_date: {as_of_date}")

            cursor.execute("SELECT date, market, channel, customer, net_sales FROM v_sales_daily LIMIT 1")
            sales_sample = cursor.fetchone()
            print(f"  [OK] v_sales_daily accessible (sample: {sales_sample['market']}, {sales_sample['channel']}, {sales_sample['customer']})")

            cursor.execute("SELECT COUNT(*) AS cnt FROM targets_daily")
            print(f"  [OK] targets_daily row count: {cursor.fetchone()['cnt']}")

            cursor.execute("SELECT COUNT(*) AS cnt FROM owners")
            print(f"  [OK] owners row count: {cursor.fetchone()['cnt']}")

            cursor.execute("SELECT COUNT(*) AS cnt FROM run_log")
            print(f"  [OK] run_log row count: {cursor.fetchone()['cnt']}")
            cursor.close()
    except Exception as e:
        print(f"  [FAIL] agent_ro failed: {e}")
        return 1

    print("\n[2/3] Testing agent_ro security boundary...")
    try:
        with get_ro_connection(config) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE settings SET setting_value = '2026-10-01' WHERE setting_key = 'as_of_date'")
            print("  [FAIL] Security violation: agent_ro was able to update settings!")
            return 1
    except Exception:
        print("  [OK] Enforced: agent_ro UPDATE on settings was denied as expected.")

    print("\n[3/3] Testing agent_ingest (ingest user)...")
    try:
        with get_ingest_connection(config) as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT COUNT(*) AS cnt, MAX(date) AS max_date FROM sales_orders")
            so_row = cursor.fetchone()
            print(f"  [OK] sales_orders count: {so_row['cnt']}, max order date: {so_row['max_date']}")
            cursor.close()
    except Exception as e:
        print(f"  [FAIL] agent_ingest failed: {e}")
        return 1

    print("\n" + "=" * 60)
    print("All Phase 1 Database Checks Passed Successfully!")
    print("=" * 60)
    return 0


def run_scan(target_date_str: Optional[str] = None) -> int:
    """Run non-AI scan mode: detect drops and stopped customers without side effects (Phase 2)."""
    print("=" * 70)
    print("AtliQ Morning Digest Agent - Drop Detection Scan (No AI, No Side Effects)")
    print("=" * 70)

    config = load_config()
    current_as_of = get_current_as_of_date(config)
    print(f"Current settings.as_of_date: {current_as_of}")

    with get_ro_connection(config) as conn:
        owners = load_owners(conn)

        if target_date_str:
            scan_dates = [datetime.date.fromisoformat(target_date_str)]
        else:
            scan_dates = [current_as_of]

        total_alerts = 0
        for s_date in scan_dates:
            print(f"\n--- Scanning Date: {s_date} ---")
            market_region_map = get_market_region_map(conn, reference_date=s_date)
            m_drops = detect_market_channel_drops(conn, s_date)
            c_alerts = detect_customer_zero_orders(conn, s_date)
            alerts = consolidate_alerts(m_drops, c_alerts, owners, market_region_map)
            alerts = apply_escalation_to_all(conn, alerts)

            if not alerts:
                print("  [INFO] No material sales drops or zero-order customers detected.")
                continue

            for idx, a in enumerate(alerts, 1):
                total_alerts += 1
                type_label = {
                    AlertType.COMBINED: "COMBINED ALERT (Market Drop + Customer Zero-Orders)",
                    AlertType.MARKET_CHANNEL: "MARKET & CHANNEL SALES DROP",
                    AlertType.CUSTOMER_ZERO: "CUSTOMER STOPPED ORDERING (Zero Orders)",
                }[a.alert_type]

                print(f"\n  [ALERT #{idx}] {type_label}")
                print(f"    Market / Channel:  {a.market} / {a.channel}")
                print(f"    Primary Owner:     {a.primary_owner.name} ({a.primary_owner.role}) <{a.primary_owner.email}>")
                if a.copy_owner:
                    print(f"    Copy Recipient:    {a.copy_owner.name} ({a.copy_owner.role}) <{a.copy_owner.email}>")
                else:
                    print(f"    Copy Recipient:    None (Day 1 or region head)")

                esc_status = "Confirmed" if a.escalation_confirmed else "Unconfirmed"
                print(f"    Escalation Level:  Day {a.escalation_day} ({esc_status})")

                if a.market_channel_baseline is not None:
                    print(f"    Market Baseline:   ${a.market_channel_baseline:,.2f}")
                    print(f"    Market Actual:     ${a.market_channel_actual:,.2f}")
                    print(f"    Decline:           {a.market_channel_decline_pct}%")

                if a.affected_customers:
                    print(f"    Zero-Order Customers:")
                    for c_name in a.affected_customers:
                        base = a.customer_baselines.get(c_name, 0.0)
                        print(f"      - {c_name} (Normal weekday baseline: ${base:,.2f}, Actual: $0.00)")

    print("\n" + "=" * 70)
    print(f"Scan complete. Total alerts identified: {total_alerts}")
    print("=" * 70)
    return 0


def run_day_job(target_date_str: str, no_email: bool = False, force: bool = False) -> int:
    """Run single-day escalation check, report generation, and email delivery."""
    print("=" * 70)
    print(f"AtliQ Morning Digest Agent - Daily Check for Date: {target_date_str}")
    print("=" * 70)

    config = load_config()
    current_as_of = get_current_as_of_date(config)
    target_date = datetime.date.fromisoformat(target_date_str)

    if target_date > current_as_of:
        print(f"[ERROR] Requested date {target_date} is after current as_of_date ({current_as_of}). Replay rejected.")
        return 1

    with get_ro_connection(config) as conn:
        owners = load_owners(conn)
        market_region_map = get_market_region_map(conn, reference_date=target_date)

        print(f"Detecting sales drops and zero-order customers for {target_date}...")
        m_drops = detect_market_channel_drops(conn, target_date)
        c_alerts = detect_customer_zero_orders(conn, target_date)
        alerts = consolidate_alerts(m_drops, c_alerts, owners, market_region_map)
        alerts = apply_escalation_to_all(conn, alerts)

        if not alerts:
            print("  [INFO] No material sales drops or zero-order customers detected on this date.")
            return 0

        print(f"Detected {len(alerts)} alert incident(s). Proceeding with investigation and delivery...")
        for idx, a in enumerate(alerts, 1):
            print(f"\n[{idx}/{len(alerts)}] Investigating {a.market} {a.channel} (Escalation Day {a.escalation_day})...")

            # Check delivery guard permissions
            try:
                allowed_to_send = can_deliver_report(
                    conn=conn,
                    job="daily_check",
                    target_date=target_date,
                    incident_key=a.incident_key,
                    recipient=a.primary_owner.email,
                    force=force,
                    no_email=no_email,
                    config=config,
                )
            except DeliveryGuardError as dge:
                print(f"  [ERROR] Delivery Guard Block: {dge}")
                return 1

            # AI investigation
            investigation = investigate_drop(a, config)
            print(f"  [AI Result] Headline: {investigation.headline}")
            print(f"  [AI Result] Status:   {investigation.analysis_status} ({investigation.confidence})")

            # Generate HTML & Plain text email content
            html_body, plain_text = build_escalation_email(a, investigation)

            # Generate Word Document (.docx)
            docx_path = build_escalation_docx(a, investigation, output_dir="escalations")
            print(f"  [Report] Generated Word document: {docx_path}")

            # Delivery via Gmail API
            if allowed_to_send:
                subject = f"AtliQ Sales Escalation [Day {a.escalation_day}] - {a.market} {a.channel}"
                cc_list = [a.copy_owner.email] if a.copy_owner else []

                success, msg_id, err_msg = send_email_via_gmail(
                    recipient=a.primary_owner.email,
                    subject=subject,
                    html_body=html_body,
                    plain_text=plain_text,
                    attachment_path=docx_path,
                    cc_recipients=cc_list,
                    config=config,
                )

                status = "OK" if success else "ERROR"
                details = {
                    "job_type": "daily_check",
                    "target_date": target_date.isoformat(),
                    "incident_key": a.incident_key,
                    "recipient": a.primary_owner.email,
                    "cc_recipients": cc_list,
                    "escalation_day": a.escalation_day,
                    "report_file": docx_path,
                    "gmail_message_id": msg_id,
                    "error_summary": err_msg,
                }
                log_run_event(conn, "daily_check", target_date, status, details)

                if not success:
                    print(f"  [Delivery Failure] Failed to send email: {err_msg}")
                    return 1
            else:
                if no_email:
                    print("  [Delivery] --no-email specified. Email dispatch skipped.")
                else:
                    print("  [Delivery] Report already delivered. Skipping duplicate dispatch.")

    print("\n" + "=" * 70)
    print("Daily Check & Escalation Reporting Completed Successfully!")
    print("=" * 70)
    return 0


def run_week_job(monday_str: str, no_email: bool = False, force: bool = False) -> int:
    """Run company-wide weekly digest generation and email delivery for all stakeholders."""
    print("=" * 70)
    print(f"AtliQ Morning Digest Agent - Weekly Digest for Monday: {monday_str}")
    print("=" * 70)

    config = load_config()
    current_as_of = get_current_as_of_date(config)
    monday = datetime.date.fromisoformat(monday_str)

    if monday.weekday() != 0:
        print(f"[ERROR] Date {monday} is not a Monday (weekday {monday.weekday()}). Replay rejected.")
        return 1

    monday, sunday, _, _ = get_week_boundaries(monday)

    if sunday > current_as_of:
        print(f"[ERROR] Requested week's Sunday ({sunday}) is after current as_of_date ({current_as_of}). Replay rejected.")
        return 1

    try:
        stakeholders = load_stakeholders()
        print(f"Loaded {len(stakeholders)} stakeholder(s) from registry:")
        for s in stakeholders:
            print(f"  - {s.name} ({s.role}) <{s.email}>")
    except Exception as e:
        print(f"[ERROR] Failed to load stakeholders: {e}")
        return 1

    with get_ro_connection(config) as conn:
        print(f"\nComputing company scorecard for week {monday} to {sunday}...")
        scorecard = compute_weekly_scorecard(conn, monday)
        print(f"  [Scorecard] Net Sales: ${scorecard.net_sales:,.2f} ({scorecard.net_sales_change_pct:+.1f}% WoW)")
        print(f"  [Scorecard] Target:    ${scorecard.net_sales_target:,.2f} ({scorecard.net_sales_vs_target_pct:+.1f}% vs Target)")
        print(f"  [Scorecard] Gross Margin: {scorecard.gross_margin_pct:.1f}% (${scorecard.gross_margin:,.2f})")
        print(f"  [Scorecard] Units Sold:   {scorecard.units_sold:,} ({scorecard.units_change_pct:+.1f}% WoW)")
        print(f"  [Scorecard] Money Impact: ${scorecard.money_impact:,.2f} (Monthly Projected: ${scorecard.monthly_projected_impact:,.2f})")

        print("Computing regional and category breakdowns...")
        reg_breakdowns = compute_regional_breakdown(conn, monday)
        cat_breakdowns = compute_category_breakdown(conn, monday)

        success_count = 0
        for idx, st in enumerate(stakeholders, 1):
            print(f"\n[{idx}/{len(stakeholders)}] Processing Weekly Digest for {st.name} ({st.role})...")

            try:
                allowed_to_send = can_deliver_report(
                    conn=conn,
                    job="weekly_digest",
                    target_date=monday,
                    recipient=st.email,
                    force=force,
                    no_email=no_email,
                    config=config,
                )
            except DeliveryGuardError as dge:
                print(f"  [ERROR] Delivery Guard Block: {dge}")
                continue

            brief_text = fetch_stakeholder_brief(st, config)
            if not brief_text:
                print(f"  [SKIP] No brief available for {st.name}. Skipping digest for this stakeholder.")
                continue

            # Run AI prioritization loop
            narrative = investigate_digest(
                scorecard=scorecard,
                regional_breakdowns=reg_breakdowns,
                category_breakdowns=cat_breakdowns,
                stakeholder=st,
                brief_text=brief_text,
                config=config,
            )
            print(f"  [AI Headline] {narrative.headline}")
            print(f"  [AI Status]   {narrative.analysis_status}")

            # Generate HTML & Plain text email content
            html_body, plain_text = build_digest_email(st, scorecard, narrative)

            # Generate Word Document (.docx)
            docx_path = build_digest_docx(st, scorecard, narrative, output_dir="digests")
            print(f"  [Report] Generated Word document: {docx_path}")

            if allowed_to_send:
                subject = f"AtliQ Weekly Executive Digest - {scorecard.monday} to {scorecard.sunday}"
                success, msg_id, err_msg = send_email_via_gmail(
                    recipient=st.email,
                    subject=subject,
                    html_body=html_body,
                    plain_text=plain_text,
                    attachment_path=docx_path,
                    config=config,
                )

                status = "OK" if success else "ERROR"
                details = {
                    "job_type": "weekly_digest",
                    "week_start": monday.isoformat(),
                    "week_end": sunday.isoformat(),
                    "recipient": st.email,
                    "report_file": docx_path,
                    "gmail_message_id": msg_id,
                    "error_summary": err_msg,
                }
                log_run_event(conn, "weekly_digest", monday, status, details)

                if success:
                    success_count += 1
            else:
                if no_email:
                    print("  [Delivery] --no-email specified. Email dispatch skipped.")
                else:
                    print("  [Delivery] Digest already sent previously. Skipping duplicate dispatch.")
                success_count += 1

    print("\n" + "=" * 70)
    print(f"Weekly Digest Processing Completed! Successfully processed: {success_count}/{len(stakeholders)}")
    print("=" * 70)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build command-line parser."""
    parser = argparse.ArgumentParser(
        description="AtliQ Morning Digest Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--test-db",
        action="store_true",
        help="Run database diagnostics, verify permissions, and test connectivity.",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="List all drops and stopped customers without AI, email, or state changes.",
    )
    parser.add_argument(
        "--day",
        metavar="YYYY-MM-DD",
        type=str,
        help="Replay one specific day (must not be after as_of_date).",
    )
    parser.add_argument(
        "--week",
        metavar="YYYY-MM-DD",
        type=str,
        help="Replay week starting on given Monday (Sunday must not be after as_of_date).",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Write report files only; do not send emails or mark sent.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redo already-completed jobs. Allowed only when TEST_INBOX is configured.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.test_db:
        return run_test_db()

    if args.scan:
        return run_scan(target_date_str=args.day)

    if args.day:
        return run_day_job(target_date_str=args.day, no_email=args.no_email, force=args.force)

    if args.week:
        return run_week_job(monday_str=args.week, no_email=args.no_email, force=args.force)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
