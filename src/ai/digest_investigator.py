"""AI digest narrative prioritization and investigation loop."""

import datetime
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.config import Config, load_config
from src.context.stakeholders import Stakeholder
from src.digest.scorecard import WeeklyScorecard
from src.digest.breakdowns import RegionBreakdown, CategoryBreakdown
from src.ai.groq_client import GroqClientWrapper, AIInvestigationError
from src.ai.sql_tool import SQL_TOOL_SCHEMA, execute_ai_sql, SQLSecurityError


@dataclass
class DigestNarrativeResult:
    headline: str
    insights: List[str]
    causes: str
    actions: List[str]
    decision_needed: str
    attention_numbers: List[str]
    analysis_status: str
    steps_taken: int


DIGEST_SYSTEM_PROMPT = """You are an executive sales intelligence analyst preparing a weekly digest for an AtliQ executive.
You are given:
1. Pure code-calculated company scorecard metrics vs prior week and target.
2. Code-calculated regional performance breakdown (sales, GM%, discount %).
3. Code-calculated category performance breakdown (units, price/unit, cost/unit).
4. The stakeholder's private brief defining their priorities, focus areas, and decisions.

Rules (PRD Section 7):
1. The stakeholder's brief determines narrative priority when metrics conflict (e.g. margin vs volume).
2. The brief cannot override calculated values, invent targets, or require unsupported causal claims.
3. You have the `execute_sql` tool to run single SELECT queries against `v_sales_daily` (up to 10 steps) if you need deeper evidence.
4. Output must be submitted via `submit_digest` with:
   - headline: 1 high-impact sentence.
   - insights: up to 3 key insights.
   - causes: evidence-backed causal explanation.
   - actions: up to 2 concrete actions.
   - decision_needed: specific decision required.
   - attention_numbers: names of metrics needing attention according to the brief.
5. If the brief is vague, contradictory, or unusable, mark personalized analysis as incomplete and stick to factual numbers.
"""

SUBMIT_DIGEST_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_digest",
        "description": "Submit final weekly digest narrative components.",
        "parameters": {
            "type": "object",
            "properties": {
                "headline": {
                    "type": "string",
                    "description": "Concise high-impact headline.",
                },
                "insights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Up to 3 key bullet points.",
                },
                "causes": {
                    "type": "string",
                    "description": "Root cause analysis supported by evidence.",
                },
                "actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Up to 2 concrete recommended actions.",
                },
                "decision_needed": {
                    "type": "string",
                    "description": "Specific decision required from this stakeholder.",
                },
                "attention_numbers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Metric names that need attention based on the brief.",
                },
            },
            "required": ["headline", "insights", "causes", "actions", "decision_needed", "attention_numbers"],
        },
    },
}


def generate_fallback_digest(
    scorecard: WeeklyScorecard,
    stakeholder: Stakeholder,
    reason: str = "Live AI key not provided",
) -> DigestNarrativeResult:
    """Generate deterministic factual digest narrative when AI is unavailable or fails."""
    # Build factual headline
    sales_dir = "grew" if scorecard.net_sales_change >= 0 else "declined"
    headline = (
        f"Company net sales {sales_dir} by {abs(scorecard.net_sales_change_pct):.1f}% WoW to "
        f"${scorecard.net_sales:,.2f} ({scorecard.net_sales_vs_target_pct:+.1f}% vs target)."
    )

    insights = [
        f"Gross Margin ended at {scorecard.gross_margin_pct:.1f}% (${scorecard.gross_margin:,.2f}), a change of {scorecard.gross_margin_pct_change:+.1f} pts WoW.",
        f"Total units sold reached {scorecard.units_sold:,} ({scorecard.units_change_pct:+.1f}% vs prior week).",
        f"Weekly money impact is ${scorecard.money_impact:,.2f}, annualizing to ${scorecard.monthly_projected_impact:,.2f} monthly if trend continues.",
    ]

    causes = (
        f"Weekly net sales variance was driven by {sales_dir} across company markets against target of "
        f"${scorecard.net_sales_target:,.2f}. Gross margin dollar change was ${scorecard.money_impact:,.2f}."
    )

    actions = [
        "Review market and regional performance against weekly sales targets.",
        "Monitor gross margin percentage trajectory and post-invoice discount rules.",
    ]

    decision_needed = "Review weekly target allocation and promotional discount guidelines."

    attention = []
    if scorecard.net_sales_change < 0 or scorecard.net_sales_vs_target_pct < 0:
        attention.append("Net Sales")
    if scorecard.gross_margin_pct_change < 0:
        attention.append("Gross Margin %")

    return DigestNarrativeResult(
        headline=headline,
        insights=insights[:3],
        causes=causes,
        actions=actions[:2],
        decision_needed=decision_needed,
        attention_numbers=attention,
        analysis_status=f"Factual scorecard (Personalized analysis incomplete: {reason})",
        steps_taken=0,
    )


def investigate_digest(
    scorecard: WeeklyScorecard,
    regional_breakdowns: List[RegionBreakdown],
    category_breakdowns: List[CategoryBreakdown],
    stakeholder: Stakeholder,
    brief_text: str,
    config: Optional[Config] = None,
    max_steps: int = 10,
) -> DigestNarrativeResult:
    """Run digest AI synthesis loop tailored to the stakeholder's private brief."""
    if config is None:
        config = load_config()

    groq_client = GroqClientWrapper(config)
    if not groq_client.is_configured:
        print("  [AI] Groq client not configured with live key; using factual digest synthesis.")
        return generate_fallback_digest(scorecard, stakeholder, "Live AI key not provided")

    # Serialize structured data context for prompt
    regions_summary = "\n".join([
        f"  - {r.region}: Sales ${r.curr_net_sales:,.0f} ({r.net_sales_change_pct:+.1f}%), GM {r.curr_gross_margin_pct:.1f}% (vs {r.prior_gross_margin_pct:.1f}%), Discount {r.curr_discount_pct:.1f}%"
        for r in regional_breakdowns
    ])

    top_categories = "\n".join([
        f"  - {c.category}: Units {c.curr_units:,} ({c.units_change_pct:+.1f}%), Price/Unit ${c.curr_price_per_unit:.1f}, Cost/Unit ${c.curr_cost_per_unit:.1f}"
        for c in category_breakdowns[:5]
    ])

    user_prompt = f"""Prepare the weekly digest narrative for {stakeholder.name} ({stakeholder.role}).

Stakeholder Private Brief:
\"\"\"
{brief_text}
\"\"\"

Company Scorecard ({scorecard.monday} to {scorecard.sunday}):
- Net Sales: ${scorecard.net_sales:,.2f} ({scorecard.net_sales_change_pct:+.1f}% WoW, {scorecard.net_sales_vs_target_pct:+.1f}% vs Target)
- Target Net Sales: ${scorecard.net_sales_target:,.2f}
- Gross Margin %: {scorecard.gross_margin_pct:.1f}% ({scorecard.gross_margin_pct_change:+.1f} pts WoW)
- Gross Margin $: ${scorecard.gross_margin:,.2f} ({scorecard.gross_margin_change_pct:+.1f}% WoW)
- Units Sold: {scorecard.units_sold:,} ({scorecard.units_change_pct:+.1f}% WoW)
- Money Impact (Margin $ change): ${scorecard.money_impact:,.2f}
- Monthly Projected Impact: ${scorecard.monthly_projected_impact:,.2f}

Regional Performance:
{regions_summary}

Top Categories:
{top_categories}

Please review the data against {stakeholder.name}'s priorities and submit your findings using `submit_digest`.
"""

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    tools = [SQL_TOOL_SCHEMA, SUBMIT_DIGEST_SCHEMA]
    step = 0

    try:
        while step < max_steps:
            step += 1
            response = groq_client.create_chat_completion(
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            msg = response.choices[0].message
            
            # Format assistant message cleanly for subsequent requests (avoiding unsupported fields like annotations)
            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if msg.content:
                assistant_msg["content"] = msg.content
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                messages.append({
                    "role": "user",
                    "content": "Please submit the final digest narrative using the submit_digest tool.",
                })
                continue

            tool_call = tool_calls[0]
            func_name = tool_call.function.name
            raw_args = tool_call.function.arguments

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}

            if func_name == "submit_digest":
                return DigestNarrativeResult(
                    headline=args.get("headline", "").strip() or f"Weekly Digest for {stakeholder.name}",
                    insights=(args.get("insights") or [])[:3],
                    causes=args.get("causes", "").strip(),
                    actions=(args.get("actions") or [])[:2],
                    decision_needed=args.get("decision_needed", "").strip(),
                    attention_numbers=args.get("attention_numbers") or [],
                    analysis_status="Personalized analysis complete",
                    steps_taken=step,
                )

            elif func_name == "execute_sql":
                query_str = args.get("query", "")
                try:
                    rows, _ = execute_ai_sql(query_str, config)
                    tool_content = json.dumps(rows, default=str)
                except SQLSecurityError as sse:
                    tool_content = f"SQL SECURITY REJECTION: {sse}"
                except Exception as ex:
                    tool_content = f"DATABASE ERROR: {ex}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_content,
                })
            else:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"Unknown tool: {func_name}",
                })

    except Exception as e:
        print(f"  [AI Warning] Digest AI synthesis failed: {e}. Falling back to factual digest.")
        return generate_fallback_digest(scorecard, stakeholder, str(e))

    return generate_fallback_digest(scorecard, stakeholder, f"Exceeded step limit of {max_steps}")
