"""AI drop investigation loop using safe SQL tool against v_sales_daily."""

import datetime
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from mysql.connector.connection import MySQLConnection

from src.config import Config, load_config
from src.alerts.resolver import ConsolidatedAlert, AlertType
from src.ai.groq_client import GroqClientWrapper, AIInvestigationError
from src.ai.sql_tool import SQL_TOOL_SCHEMA, execute_ai_sql, SQLSecurityError


@dataclass
class DropInvestigationResult:
    headline: str
    likely_causes: str
    evidence: str
    confidence: str  # "complete", "partial", or "incomplete"
    analysis_status: str  # "Complete" or "Analysis incomplete"
    steps_taken: int
    queries_run: List[str]


SYSTEM_PROMPT = """You are an expert sales analyst investigating material sales drops for AtliQ Hardware.
Your role: Investigate the root cause of the sales drop using the view `v_sales_daily`.

Approved Gold View: `v_sales_daily`
Columns:
- date, region, sub_zone, market
- customer, channel, platform
- division, segment, category, product, variant
- sold_qty, gross_price, gross_sales, pre_invoice_deduction, net_invoice_sales,
  post_invoice_discount, post_invoice_other, net_sales, manufacturing_cost,
  freight_cost, other_cost, gross_margin

Rules:
1. You have one tool: `execute_sql`. It executes a single read-only SQL query on `v_sales_daily`.
2. First, compare the drop date with the same weekday last week (target date - 7 days), by customer.
3. Next, check product and category breakdowns for significant volume, price, or discount changes.
4. Each query must be a single SELECT statement on `v_sales_daily`.
5. You have a maximum of 8 steps. Once you identify the cause, submit your final findings.
6. Do NOT invent numbers. Qualify partial evidence as partial; do not claim proven causation without evidence.
"""

SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_investigation",
        "description": "Submit final drop investigation findings once root cause is analyzed.",
        "parameters": {
            "type": "object",
            "properties": {
                "headline": {
                    "type": "string",
                    "description": "Concise 1-sentence summary of the drop's primary driver.",
                },
                "likely_causes": {
                    "type": "string",
                    "description": "Detailed explanation of likely causes backed by query evidence.",
                },
                "evidence": {
                    "type": "string",
                    "description": "Specific customers, products, volumes, or discount deltas found.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["complete", "partial", "incomplete"],
                    "description": "Confidence level in causal findings.",
                },
            },
            "required": ["headline", "likely_causes", "evidence", "confidence"],
        },
    },
}


def generate_fallback_investigation(
    alert: ConsolidatedAlert,
    reason: str = "AI analysis incomplete",
) -> DropInvestigationResult:
    """Generate deterministic factual fallback report when AI is unavailable or fails."""
    if alert.alert_type == AlertType.COMBINED:
        headline = f"Sales in {alert.market} {alert.channel} dropped {alert.market_channel_decline_pct}% driven by zero orders from key customer(s)."
        likely_causes = (
            f"Net sales fell from normal weekday baseline of ${alert.market_channel_baseline:,.2f} "
            f"to ${alert.market_channel_actual:,.2f}. The primary cause was zero orders placed by: "
            f"{', '.join(alert.affected_customers)}."
        )
        evidence = (
            f"Market actual: ${alert.market_channel_actual:,.2f} vs baseline ${alert.market_channel_baseline:,.2f} "
            f"(-{alert.market_channel_decline_pct}%). "
            + "; ".join([
                f"{c}: baseline ${alert.customer_baselines.get(c, 0):,.2f}, actual $0.00"
                for c in alert.affected_customers
            ])
        )
    elif alert.alert_type == AlertType.CUSTOMER_ZERO:
        custs = ", ".join(alert.affected_customers)
        headline = f"Customer(s) {custs} placed zero orders in {alert.market} {alert.channel}."
        likely_causes = f"Expected high-volume customer(s) {custs} had zero recorded order volume."
        evidence = "; ".join([
            f"{c}: baseline ${alert.customer_baselines.get(c, 0):,.2f}, actual $0.00"
            for c in alert.affected_customers
        ])
    else:
        headline = f"Sales in {alert.market} {alert.channel} declined by {alert.market_channel_decline_pct}%."
        likely_causes = (
            f"Net sales dropped to ${alert.market_channel_actual:,.2f} against the normal 4-week median "
            f"baseline of ${alert.market_channel_baseline:,.2f}."
        )
        evidence = f"Decline: -{alert.market_channel_decline_pct}%, dollar drop: ${round(alert.market_channel_baseline - alert.market_channel_actual, 2):,.2f}."

    return DropInvestigationResult(
        headline=headline,
        likely_causes=likely_causes,
        evidence=evidence,
        confidence="partial",
        analysis_status=f"Analysis incomplete ({reason})",
        steps_taken=0,
        queries_run=[],
    )


def investigate_drop(
    alert: ConsolidatedAlert,
    config: Optional[Config] = None,
    max_steps: int = 8,
) -> DropInvestigationResult:
    """Run multi-turn investigation loop using safe SQL queries against v_sales_daily."""
    if config is None:
        config = load_config()

    groq_client = GroqClientWrapper(config)
    if not groq_client.is_configured:
        print("  [AI] Groq client not configured with live key; using factual evidence engine.")
        return generate_fallback_investigation(alert, "Live AI key not provided")

    # Initial context prompt
    same_weekday_prior = alert.date - datetime.timedelta(days=7)
    initial_user_prompt = f"""Investigate the sales drop on {alert.date} for Market '{alert.market}', Channel '{alert.channel}'.
Incident Details:
- Alert Type: {alert.alert_type.value}
- Market Baseline: ${alert.market_channel_baseline if alert.market_channel_baseline is not None else 'N/A'}
- Market Actual: ${alert.market_channel_actual if alert.market_channel_actual is not None else 'N/A'}
- Decline: {alert.market_channel_decline_pct if alert.market_channel_decline_pct is not None else 'N/A'}%
- Affected Customer(s): {', '.join(alert.affected_customers) if alert.affected_customers else 'None'}
- Comparison date (same weekday last week): {same_weekday_prior}

Please begin your investigation by querying v_sales_daily for customer sales on {alert.date} vs {same_weekday_prior} in this market and channel.
"""

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": initial_user_prompt},
    ]

    tools = [SQL_TOOL_SCHEMA, SUBMIT_TOOL_SCHEMA]
    queries_run: List[str] = []
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

            # Check if model made tool calls
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                # Model provided plain text without tool call; prompt to submit findings
                messages.append({
                    "role": "user",
                    "content": "Please submit your final findings using the submit_investigation tool.",
                })
                continue

            # Process single tool call
            tool_call = tool_calls[0]
            func_name = tool_call.function.name
            raw_args = tool_call.function.arguments

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}

            if func_name == "submit_investigation":
                # Final submission received
                headline = args.get("headline", "").strip() or f"Sales drop in {alert.market} {alert.channel}"
                likely_causes = args.get("likely_causes", "").strip() or "Cause could not be established."
                evidence = args.get("evidence", "").strip() or "Partial query evidence collected."
                confidence = args.get("confidence", "partial")

                return DropInvestigationResult(
                    headline=headline,
                    likely_causes=likely_causes,
                    evidence=evidence,
                    confidence=confidence,
                    analysis_status="Complete" if confidence == "complete" else "Partial evidence",
                    steps_taken=step,
                    queries_run=queries_run,
                )

            elif func_name == "execute_sql":
                query_str = args.get("query", "")
                try:
                    rows, validated_query = execute_ai_sql(query_str, config)
                    queries_run.append(validated_query)
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

    except AIInvestigationError as aie:
        print(f"  [AI NOTICE] Investigation error: {aie}. Falling back to factual summary.")
        return generate_fallback_investigation(alert, str(aie))
    except Exception as e:
        print(f"  [AI NOTICE] Unexpected failure: {e}. Falling back to factual summary.")
        return generate_fallback_investigation(alert, str(e))

    # Reached step limit without submission
    return generate_fallback_investigation(alert, f"Exceeded maximum investigation limit of {max_steps} steps")

