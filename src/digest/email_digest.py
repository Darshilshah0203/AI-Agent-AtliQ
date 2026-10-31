"""Phone-friendly HTML and plain-text weekly digest email generator."""

from typing import Tuple
from src.context.stakeholders import Stakeholder
from src.digest.scorecard import WeeklyScorecard
from src.ai.digest_investigator import DigestNarrativeResult
from src.reports.formatting import (
    HEX_RED,
    HEX_GREEN,
    HEX_BLUE,
    HEX_GRAY,
    HEX_LIGHT_BG,
    HEX_BORDER,
    format_delta_text,
)


def build_digest_email(
    stakeholder: Stakeholder,
    scorecard: WeeklyScorecard,
    narrative: DigestNarrativeResult,
) -> Tuple[str, str]:
    """Generate (html_body, plain_text_body) for weekly digest adhering to PRD 7.4 order."""
    
    # Deltas & formatting
    ns_lbl, ns_hex, _ = format_delta_text(scorecard.net_sales_change_pct, "%")
    tar_lbl, tar_hex, _ = format_delta_text(scorecard.net_sales_vs_target_pct, "%")
    gm_lbl, gm_hex, _ = format_delta_text(scorecard.gross_margin_pct_change, " pts")
    unit_lbl, unit_hex, _ = format_delta_text(scorecard.units_change_pct, "%")
    money_lbl, money_hex, _ = format_delta_text(scorecard.money_impact, "$")

    # 1. Plain-Text Version
    text_lines = [
        "=" * 65,
        f"ATLIQ HARDWARE • WEEKLY EXECUTIVE DIGEST",
        "=" * 65,
        f"Stakeholder: {stakeholder.name} ({stakeholder.role})",
        f"Week:        {scorecard.monday} to {scorecard.sunday}",
        "-" * 65,
        "1. COMPANY SCORECARD",
        f"  - Net Sales:      ${scorecard.net_sales:,.2f} | WoW: {ns_lbl} | vs Target: {tar_lbl} (Target: ${scorecard.net_sales_target:,.2f})",
        f"  - Gross Margin %: {scorecard.gross_margin_pct:.1f}% | WoW: {gm_lbl} | No target",
        f"  - Units Sold:     {scorecard.units_sold:,} | WoW: {unit_lbl} | No target",
        f"  - Gross Margin $: ${scorecard.gross_margin:,.2f} | WoW: {money_lbl} | Monthly Projected Impact: ${scorecard.monthly_projected_impact:,.2f}",
        "-" * 65,
        f"2. EXECUTIVE HEADLINE\n{narrative.headline}",
        "-" * 65,
        "3. KEY INSIGHTS (PRIORITIZED FOR YOU)",
    ]
    for ins in narrative.insights[:3]:
        text_lines.append(f"  • {ins}")

    text_lines.extend([
        "-" * 65,
        f"4. ROOT CAUSES & EVIDENCE\n{narrative.causes}",
        "-" * 65,
        "5. RECOMMENDED ACTIONS",
    ])
    for act in narrative.actions[:2]:
        text_lines.append(f"  • {act}")

    text_lines.extend([
        "-" * 65,
        f"6. DECISION NEEDED: {narrative.decision_needed}",
        "-" * 65,
        f"7. STATUS: {narrative.analysis_status}",
        "=" * 65,
    ])
    plain_text = "\n".join(text_lines)

    # 2. HTML Version (Single-Column, Phone-Friendly, Inline Styles Only)
    html_parts = [
        f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #222222; margin: 0; padding: 12px; background-color: #FAFAFA;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #FFFFFF; border: 1px solid {HEX_BORDER}; border-radius: 6px; padding: 16px;">
    
    <!-- Header Banner -->
    <div style="border-bottom: 2px solid {HEX_BLUE}; padding-bottom: 8px; margin-bottom: 12px;">
      <span style="font-size: 11px; font-weight: bold; color: {HEX_BLUE}; text-transform: uppercase; letter-spacing: 0.5px;">AtliQ Morning Digest &bull; Weekly Executive Digest</span>
      <h2 style="margin: 4px 0 0 0; font-size: 18px; color: #111111;">Weekly Brief: {stakeholder.name}</h2>
      <div style="font-size: 12px; color: {HEX_GRAY}; margin-top: 2px;">{stakeholder.role} &bull; Week: {scorecard.monday} to {scorecard.sunday}</div>
    </div>

    <!-- 1. Scorecard Table -->
    <h3 style="font-size: 13px; margin: 0 0 6px 0; color: {HEX_BLUE}; text-transform: uppercase;">1. Company Scorecard</h3>
    <table style="width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 14px; border: 1px solid {HEX_BORDER};">
      <tr style="background-color: {HEX_LIGHT_BG}; text-align: left;">
        <th style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER};">Metric</th>
        <th style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right;">This Week</th>
        <th style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right;">vs Last Week</th>
        <th style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right;">Target / Impact</th>
      </tr>
      <tr>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; font-weight: bold;">Net Sales</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold;">${scorecard.net_sales:,.2f}</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold; color: {ns_hex};">{ns_lbl}</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-size: 11px; color: {tar_hex};">{tar_lbl}</td>
      </tr>
      <tr style="background-color: #FAFAFA;">
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; font-weight: bold;">Gross Margin %</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold;">{scorecard.gross_margin_pct:.1f}%</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold; color: {gm_hex};">{gm_lbl}</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-size: 11px; color: {HEX_GRAY};">&mdash; (No target)</td>
      </tr>
      <tr>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; font-weight: bold;">Units Sold</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold;">{scorecard.units_sold:,}</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-weight: bold; color: {unit_hex};">{unit_lbl}</td>
        <td style="padding: 6px 8px; border-bottom: 1px solid {HEX_BORDER}; text-align: right; font-size: 11px; color: {HEX_GRAY};">&mdash; (No target)</td>
      </tr>
      <tr style="background-color: #FAFAFA;">
        <td style="padding: 6px 8px; font-weight: bold;">Gross Margin $</td>
        <td style="padding: 6px 8px; text-align: right; font-weight: bold;">${scorecard.gross_margin:,.2f}</td>
        <td style="padding: 6px 8px; text-align: right; font-weight: bold; color: {money_hex};">{money_lbl}</td>
        <td style="padding: 6px 8px; text-align: right; font-size: 11px; color: {money_hex};">Mo: ${scorecard.monthly_projected_impact:,.2f}</td>
      </tr>
    </table>

    <!-- 2. Headline -->
    <div style="background-color: #EFF6FF; border-left: 4px solid {HEX_BLUE}; padding: 10px; margin-bottom: 12px; font-size: 13px;">
      <div style="font-weight: bold; color: {HEX_BLUE}; font-size: 11px; text-transform: uppercase;">2. Executive Headline</div>
      <div style="font-weight: bold; font-size: 14px; color: #111111; margin-top: 3px;">{narrative.headline}</div>
    </div>

    <!-- 3. Key Insights -->
    <div style="margin-bottom: 12px; font-size: 13px;">
      <h3 style="font-size: 13px; margin: 0 0 4px 0; color: {HEX_BLUE}; text-transform: uppercase;">3. Key Insights (Prioritized for you)</h3>
      <ul style="margin: 0; padding-left: 18px; color: #333333;">
"""
    ]

    for item in narrative.insights[:3]:
        html_parts.append(f"        <li style='margin-bottom: 3px;'>{item}</li>\n")

    html_parts.append(f"""      </ul>
    </div>

    <!-- 4. Root Causes -->
    <div style="margin-bottom: 12px; font-size: 13px;">
      <h3 style="font-size: 13px; margin: 0 0 4px 0; color: {HEX_BLUE}; text-transform: uppercase;">4. Root Causes & Evidence</h3>
      <div style="color: #333333; background-color: {HEX_LIGHT_BG}; padding: 8px 10px; border-radius: 4px; border: 1px solid {HEX_BORDER};">
        {narrative.causes}
      </div>
    </div>

    <!-- 5. Actions -->
    <div style="margin-bottom: 12px; font-size: 13px;">
      <h3 style="font-size: 13px; margin: 0 0 4px 0; color: {HEX_BLUE}; text-transform: uppercase;">5. Recommended Actions</h3>
      <ul style="margin: 0; padding-left: 18px; color: #333333;">
""")
    for act in narrative.actions[:2]:
        html_parts.append(f"        <li style='margin-bottom: 3px;'>{act}</li>\n")

    html_parts.append(f"""      </ul>
    </div>

    <!-- 6. Decision Needed -->
    <div style="background-color: #FEF2F2; border-left: 4px solid {HEX_RED}; padding: 10px; margin-bottom: 12px; font-size: 13px;">
      <div style="font-weight: bold; color: {HEX_RED}; font-size: 11px; text-transform: uppercase;">6. Decision Needed</div>
      <div style="font-weight: bold; color: #111111; margin-top: 3px;">{narrative.decision_needed}</div>
    </div>

    <!-- 7. Status & Footer -->
    <div style="font-size: 11px; color: {HEX_GRAY}; border-top: 1px solid {HEX_BORDER}; padding-top: 8px; margin-top: 12px;">
      7. Status: <em>{narrative.analysis_status}</em>. Attached 1-page Word report contains the permanent forwardable record.
    </div>

  </div>
</body>
</html>
""")

    return "".join(html_parts), plain_text

