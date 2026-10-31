"""Phone-friendly HTML and plain-text escalation email generator."""

from typing import Tuple
from src.alerts.resolver import ConsolidatedAlert, AlertType
from src.ai.drop_investigator import DropInvestigationResult
from src.reports.formatting import (
    HEX_RED,
    HEX_GREEN,
    HEX_BLUE,
    HEX_GRAY,
    HEX_LIGHT_BG,
    HEX_BORDER,
)


def build_escalation_email(
    alert: ConsolidatedAlert,
    investigation: DropInvestigationResult,
) -> Tuple[str, str]:
    """Generate (html_body, plain_text_body) for drop escalation email.
    
    Adheres strictly to PRD Section 8:
    - Phone-friendly single-column layout.
    - Inline styles only; no external CSS, remote images, or scripts.
    - Matching plain-text version.
    """
    esc_label = f"Day {alert.escalation_day}"
    if not alert.escalation_confirmed:
        esc_label += " (Unconfirmed)"

    copy_str = f"{alert.copy_owner.name} ({alert.copy_owner.role})" if alert.copy_owner else "None (Day 1 / Region Head)"

    # 1. Build Plain-Text Version
    text_lines = [
        "=" * 60,
        f"ATLIQ SALES ESCALATION [{esc_label.upper()}]",
        "=" * 60,
        f"Date:             {alert.date}",
        f"Market / Channel: {alert.market} / {alert.channel}",
        f"Primary Owner:    {alert.primary_owner.name} ({alert.primary_owner.role})",
        f"Copy Recipient:   {copy_str}",
        "-" * 60,
        "METRIC SUMMARY:",
    ]

    if alert.market_channel_baseline is not None:
        text_lines.append(f"  - 4-Week Median Baseline: ${alert.market_channel_baseline:,.2f}")
        text_lines.append(f"  - Day Actual Sales:        ${alert.market_channel_actual:,.2f}")
        text_lines.append(f"  - Sales Decline:           -{alert.market_channel_decline_pct}% [Needs attention]")

    if alert.affected_customers:
        text_lines.append("\nZERO-ORDER CUSTOMERS:")
        for c_name in alert.affected_customers:
            base = alert.customer_baselines.get(c_name, 0.0)
            text_lines.append(f"  - {c_name}: Baseline ${base:,.2f} -> Actual $0.00 [Stopped ordering]")

    text_lines.extend([
        "-" * 60,
        "CAUSE ANALYSIS:",
        f"Headline: {investigation.headline}",
        f"\nLikely Causes:\n{investigation.likely_causes}",
        f"\nEvidence:\n{investigation.evidence}",
        f"\nAnalysis Status: {investigation.analysis_status} ({investigation.confidence} confidence)",
        "=" * 60,
    ])
    plain_text = "\n".join(text_lines)

    # 2. Build Mobile-Optimized HTML Version (Inline Styles Only)
    html_parts = [
        f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #222222; margin: 0; padding: 12px; background-color: #FAFAFA;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid {HEX_BORDER}; border-radius: 6px; padding: 16px;">
    
    <!-- Header Banner -->
    <div style="border-bottom: 2px solid {HEX_RED}; padding-bottom: 8px; margin-bottom: 14px;">
      <span style="font-size: 11px; font-weight: bold; color: {HEX_RED}; text-transform: uppercase; letter-spacing: 0.5px;">AtliQ Morning Digest &bull; Incident Escalation</span>
      <h2 style="margin: 4px 0 0 0; font-size: 19px; color: #111111;">
        {alert.market} {alert.channel} Sales Drop &bull; <span style="color: {HEX_RED};">{esc_label}</span>
      </h2>
    </div>

    <!-- Metadata Box -->
    <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 16px; background-color: {HEX_LIGHT_BG}; border-radius: 4px;">
      <tr>
        <td style="padding: 6px 10px; color: {HEX_GRAY}; width: 35%;">Order Date:</td>
        <td style="padding: 6px 10px; font-weight: 600;">{alert.date}</td>
      </tr>
      <tr>
        <td style="padding: 6px 10px; color: {HEX_GRAY};">Primary Owner:</td>
        <td style="padding: 6px 10px; font-weight: 600;">{alert.primary_owner.name} ({alert.primary_owner.role})</td>
      </tr>
      <tr>
        <td style="padding: 6px 10px; color: {HEX_GRAY};">Copy (Escalation):</td>
        <td style="padding: 6px 10px; font-weight: 600;">{copy_str}</td>
      </tr>
    </table>
"""
    ]

    # Metrics Table
    if alert.market_channel_baseline is not None:
        html_parts.append(f"""
    <!-- Metrics Table -->
    <h3 style="font-size: 14px; margin: 0 0 6px 0; color: {HEX_BLUE}; text-transform: uppercase;">Performance vs 4-Week Median</h3>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 16px; border: 1px solid {HEX_BORDER};">
      <tr style="background-color: {HEX_LIGHT_BG}; text-align: left;">
        <th style="padding: 8px; border-bottom: 1px solid {HEX_BORDER};">Metric</th>
        <th style="padding: 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right;">Value</th>
      </tr>
      <tr>
        <td style="padding: 8px; border-bottom: 1px solid {HEX_BORDER};">4-Week Median Baseline:</td>
        <td style="padding: 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold;">${alert.market_channel_baseline:,.2f}</td>
      </tr>
      <tr>
        <td style="padding: 8px; border-bottom: 1px solid {HEX_BORDER};">Observed Day Sales:</td>
        <td style="padding: 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold;">${alert.market_channel_actual:,.2f}</td>
      </tr>
      <tr style="background-color: #FFEBEE;">
        <td style="padding: 8px; font-weight: bold; color: {HEX_RED};">Net Sales Decline:</td>
        <td style="padding: 8px; text-align: right; font-weight: bold; color: {HEX_RED};">-{alert.market_channel_decline_pct}% [Needs attention]</td>
      </tr>
    </table>
""")

    # Customer Zero Section
    if alert.affected_customers:
        html_parts.append(f"""
    <!-- Customer Stopped Ordering -->
    <h3 style="font-size: 14px; margin: 0 0 6px 0; color: {HEX_RED}; text-transform: uppercase;">Customer(s) Stopped Ordering</h3>
    <div style="background-color: #FFF3E0; border-left: 4px solid {HEX_RED}; padding: 10px; margin-bottom: 16px; font-size: 13px;">
      <ul style="margin: 0; padding-left: 18px;">
""")
        for c_name in alert.affected_customers:
            base = alert.customer_baselines.get(c_name, 0.0)
            html_parts.append(
                f"""        <li><strong>{c_name}</strong>: Normal weekday baseline <strong>${base:,.2f}</strong> &rarr; <span style="color: {HEX_RED}; font-weight: bold;">$0.00 actual</span></li>\n"""
            )
        html_parts.append("""      </ul>
    </div>
""")

    # AI Cause Analysis Section
    html_parts.append(f"""
    <!-- Cause Analysis Section -->
    <h3 style="font-size: 14px; margin: 0 0 6px 0; color: {HEX_BLUE}; text-transform: uppercase;">Investigation & Likely Causes</h3>
    <div style="border: 1px solid {HEX_BORDER}; border-radius: 4px; padding: 12px; margin-bottom: 14px; font-size: 13px;">
      <p style="margin: 0 0 8px 0; font-weight: bold; color: #111111;">{investigation.headline}</p>
      <p style="margin: 0 0 8px 0; color: #333333;">{investigation.likely_causes}</p>
      <div style="background-color: {HEX_LIGHT_BG}; padding: 8px; border-radius: 4px; font-size: 12px; color: {HEX_GRAY}; margin-top: 6px;">
        <strong>Supporting Evidence:</strong> {investigation.evidence}
      </div>
      <div style="margin-top: 8px; font-size: 11px; color: {HEX_GRAY};">
        Status: <em>{investigation.analysis_status}</em> &bull; Confidence: <em>{investigation.confidence}</em>
      </div>
    </div>

    <!-- Footer -->
    <div style="font-size: 11px; color: {HEX_GRAY}; border-top: 1px solid {HEX_BORDER}; padding-top: 8px; margin-top: 12px;">
      Attached Word report contains the permanent forwardable record. Generated at 8:00 AM by AtliQ Morning Digest Agent.
    </div>

  </div>
</body>
</html>
""")

    html_body = "".join(html_parts)
    return html_body, plain_text

