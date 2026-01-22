"""
AI Insight Service
Generates financial insights using OpenAI with structured JSON output.
"""

import json
import logging
from typing import Any

from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Token limits (conservative estimates)
MAX_INPUT_TOKENS = 100000  # Leave room for output (~28k tokens)
TOKENS_PER_CHAR = 0.25  # Rough estimate: ~4 chars = 1 token


class AIInsightService:
    """Service for generating insights using OpenAI."""
    
    def __init__(self):
        """Initialize OpenAI client."""
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
    
    def generate_insights(
        self,
        metrics: dict[str, Any],
        raw_data_summary: dict[str, Any],
        balance_sheet_date: str,
    ) -> list[dict[str, Any]]:
        """
        Generate insights using OpenAI.
        
        Args:
            metrics: Calculated financial metrics
            raw_data_summary: Summarized raw financial data
            balance_sheet_date: Balance sheet as-of date
        
        Returns:
            List of insight dictionaries (1-3 items)
        
        Raises:
            ValueError: If API response is invalid
            Exception: If API call fails
        """
        # Truncate summary if needed to stay within token limits
        truncated_summary = self._truncate_summary_if_needed(raw_data_summary)
        
        prompt = self._build_prompt(metrics, truncated_summary, balance_sheet_date)
        schema = self._get_json_schema()
        
        # Log token usage estimate
        estimated_tokens = self._estimate_tokens(prompt)
        if estimated_tokens > MAX_INPUT_TOKENS:
            logger.warning(
                "Estimated tokens (%d) exceed limit (%d) even after truncation",
                estimated_tokens,
                MAX_INPUT_TOKENS,
            )
        else:
            logger.info("Estimated input tokens: %d", estimated_tokens)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "financial_insights",
                        "strict": True,
                        "schema": schema,
                    },
                },
                temperature=0.1,
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from OpenAI")
            
            parsed = json.loads(content)
            insights = parsed.get("insights", [])
            
            if not insights:
                logger.warning("OpenAI returned no insights")
                return []
            
            # Validate and limit to 3
            validated_insights = self._validate_insights(insights[:3])
            return validated_insights
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenAI JSON response: %s", e)
            raise ValueError(f"Invalid JSON response from OpenAI: {e}") from e
        except Exception as e:
            logger.error("OpenAI API error: %s", e)
            raise
    
    def _get_system_prompt(self) -> str:
        """Get system prompt with role and guidelines."""
        return """You are a financial advisor helping small business owners understand their cash flow health.

                Your role:
                - Generate clear, actionable insights in plain English
                - Use a calm, confident tone (never panic or shame)
                - Focus on what matters now and what to do next
                - Explain "why" without overwhelming detail
                - Assume data may be imperfect and communicate gracefully

                Tone guidelines:
                - ✅ "You may have a cash squeeze in 3-4 weeks unless invoices are collected."
                - ❌ "Your accounts are unhealthy and at risk."

                Data handling rules:
                - CALCULATED METRICS are the source of truth - never recalculate or override these numbers
                - Use RAW DATA SUMMARY only for context and to check consistency
                - If you spot data issues or inconsistencies:
                  * Do not modify the calculated metrics
                  * Lower confidence level appropriately
                  * Explain the issue in 'data_notes'
                - If data is missing, provide qualitative guidance and note the gap
                - Never expose sensitive information like invoice numbers or contact names

                Output requirements:
                - Generate 1-3 insights ranked by urgency
                - Each insight must be actionable with concrete next steps
                - Use severity: high (immediate action), medium (monitor closely), low (awareness)
                - Use confidence: high (data is complete), medium (some gaps), low (limited data)
                - Always maintain data integrity and transparency about limitations"""
    
    def _build_prompt(
        self,
        metrics: dict[str, Any],
        raw_data_summary: dict[str, Any],
        balance_sheet_date: str,
    ) -> str:
        """Build user prompt with metrics and data summary."""
        return f"""Analyze the following financial data and generate 1-3 insights ranked by urgency.

                Balance Sheet As Of: {balance_sheet_date}
                P&L Data: Rolling 12 months (most recent data available)

                CALCULATED METRICS (AUTHORITATIVE):
                {json.dumps(metrics, indent=2)}

                RAW DATA SUMMARY (CONTEXT ONLY):
                {json.dumps(raw_data_summary, indent=2)}

Generate insights that:
1. Identify the most urgent cash flow risks or opportunities
2. Explain what's happening in plain English
3. Explain why it matters now
4. Provide 3-5 concrete, actionable next steps
5. Include relevant supporting numbers (can be empty array if not applicable)
6. Include data notes if data quality issues exist or if you detect inconsistencies

Important Instructions:
- Use 'CALCULATED METRICS' as the source of truth for all numbers shown to the user.
- Use 'RAW DATA SUMMARY' only for narrative context and consistency checks.
- If you detect inconsistencies between metrics and raw data, do not modify the metrics. Instead:
  - Lower the 'confidence_level' (e.g., to 'medium' or 'low')
  - Add a brief explanation in 'data_notes' (e.g., "Note: Discrepancy detected between metrics and raw data")
- If a required metric is missing, do not fabricate values. Instead:
  - Provide qualitative guidance
  - Lower the 'confidence_level'
  - Note the missing data in 'data_notes'
- Skip insights that cannot be supported by the available data
- Avoid exposing sensitive identifiers (e.g., contact names, invoice numbers) unless absolutely necessary

Return insights as JSON matching the required schema. Rank by urgency (most urgent first).
All fields are required, but supporting_numbers can be [] and data_notes can be "" if not applicable."""
    
    def _get_json_schema(self) -> dict[str, Any]:
        """Get JSON schema for structured output."""
        return {
            "type": "object",
            "properties": {
                "insights": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "insight_type": {
                                "type": "string",
                                "enum": [
                                    "cash_runway_risk",
                                    "upcoming_cash_squeeze",
                                    "receivables_risk",
                                    "expense_spike",
                                    "profitability_pressure",
                                ],
                            },
                            "title": {
                                "type": "string",
                                "description": "Plain-English headline (max 100 chars)",
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                            "confidence_level": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                            "summary": {
                                "type": "string",
                                "description": "1-2 sentence summary of what's happening",
                            },
                            "why_it_matters": {
                                "type": "string",
                                "description": "Short paragraph explaining why this matters now",
                            },
                            "recommended_actions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 3,
                                "maxItems": 5,
                                "description": "List of concrete, actionable steps",
                            },
                            "supporting_numbers": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "value": {"type": "string"},
                                    },
                                    "required": ["label", "value"],
                                    "additionalProperties": False,
                                },
                            },
                            "data_notes": {
                                "type": "string",
                                "description": "Optional notes about data quality or limitations",
                            },
                        },
                        "required": [
                            "insight_type",
                            "title",
                            "severity",
                            "confidence_level",
                            "summary",
                            "why_it_matters",
                            "recommended_actions",
                            "supporting_numbers",
                            "data_notes",
                        ],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 3,
                },
            },
            "required": ["insights"],
            "additionalProperties": False,
        }
    
    def _validate_insights(self, insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Validate insights structure and fix common issues.
        
        Args:
            insights: List of insight dictionaries
        
        Returns:
            Validated list of insights
        """
        validated = []
        
        for insight in insights:
            # Ensure required fields
            if not all(
                key in insight
                for key in [
                    "insight_type",
                    "title",
                    "severity",
                    "confidence_level",
                    "summary",
                    "why_it_matters",
                    "recommended_actions",
                ]
            ):
                logger.warning("Skipping invalid insight: missing required fields")
                continue
            
            # Ensure actions list is 3-5 items
            actions = insight.get("recommended_actions", [])
            if len(actions) < 3:
                logger.warning("Insight has fewer than 3 actions, padding with generic actions")
                actions.extend([
                    "Review your cash position regularly",
                    "Monitor key financial metrics weekly",
                ])
                insight["recommended_actions"] = actions[:5]
            elif len(actions) > 5:
                insight["recommended_actions"] = actions[:5]
            
            # Ensure supporting_numbers is a list (required, can be empty)
            if "supporting_numbers" not in insight:
                insight["supporting_numbers"] = []
            elif not isinstance(insight["supporting_numbers"], list):
                insight["supporting_numbers"] = []
            
            # Ensure data_notes is a string (required, can be empty)
            if "data_notes" not in insight:
                insight["data_notes"] = ""
            elif insight["data_notes"] is None:
                insight["data_notes"] = ""
            
            validated.append(insight)
        
        return validated
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Rough estimate: ~4 characters = 1 token.
        More accurate for English text.
        
        Args:
            text: Text to estimate
        
        Returns:
            Estimated token count
        """
        return int(len(text) * TOKENS_PER_CHAR)
    
    def _generate_health_score_text(
        self,
        health_score: dict[str, Any],
        key_metrics: dict[str, Any],
        raw_data_summary: dict[str, Any],
        calculated_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate descriptive text for health score using OpenAI.
        
        Args:
            health_score: Complete health score dictionary
            key_metrics: Key metrics (current_cash, monthly_burn, etc.)
            raw_data_summary: Summarized raw financial data
        
        Returns:
            Dictionary with category_metrics, why_this_matters, and assumptions
        """
        prompt = self._build_health_score_prompt(health_score, key_metrics, raw_data_summary, calculated_metrics)
        schema = self._get_health_score_json_schema()
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_health_score_system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "health_score_text",
                        "strict": True,
                        "schema": schema,
                    },
                },
                temperature=0.1,
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from OpenAI")
            
            parsed = json.loads(content)
            return parsed
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenAI JSON response: %s", e)
            raise ValueError(f"Invalid JSON response from OpenAI: {e}") from e
        except Exception as e:
            logger.error("OpenAI API error: %s", e)
            raise
    
    def _get_health_score_system_prompt(self) -> str:
        """Get system prompt for health score text generation."""
        return """You are a financial advisor helping small business owners understand their business health score.

Your role:
- Generate clear, descriptive text in plain English
- Use a calm, confident tone (never panic or shame)
- Focus on what the data shows, why it matters, and what assumptions were made
- Be specific with numbers and timeframes
- Match the exact format required by the UI

Tone guidelines:
- ✅ "Current cash balance of $49,600 across all connected accounts"
- ✅ "Average monthly outflows of $12,400 over the past 90 days"
- ❌ "Your cash is low" or "You're spending too much"

Data handling rules:
- Use the exact numbers provided in key_metrics and health_score
- Never fabricate or estimate numbers not provided
- If data is missing, note it in assumptions
- Be precise with timeframes (e.g., "90 days" not "3 months" unless specified)

Output requirements:
- Category metrics: 2-3 descriptive sentences per category (A, B, C, D, E)
- Why this matters: One paragraph explaining the current situation contextually
- Assumptions: List of key assumptions made in the calculation"""
    
    def _build_health_score_prompt(
        self,
        health_score: dict[str, Any],
        key_metrics: dict[str, Any],
        raw_data_summary: dict[str, Any],
        calculated_metrics: dict[str, Any] | None = None,
    ) -> str:
        """Build user prompt for health score text generation."""
        scorecard = health_score.get("scorecard", {})
        runway_months = key_metrics.get("runway_months")
        current_cash = key_metrics.get("current_cash", 0)
        monthly_burn = key_metrics.get("monthly_burn", 0)
        period_label = key_metrics.get("period_label", "Last 90 days")
        
        return f"""Generate descriptive text for a Business Health Score of {scorecard.get('final_score', 0)}/100 (Grade: {scorecard.get('grade', 'D')}).

KEY METRICS:
- Current cash: ${current_cash:,.0f}
- Monthly burn: ${monthly_burn:,.0f}
- Runway: {runway_months} months (if applicable)
- Data period: {period_label}

HEALTH SCORE DATA:
{json.dumps(health_score, indent=2)}

RAW DATA SUMMARY (for context):
{json.dumps(raw_data_summary, indent=2)}

Generate:

1. CATEGORY METRICS: For each category, create descriptive sentences:
   - Category A: Generate ONLY 2 items about burn rate stability, trends, or runway context (DO NOT mention current cash or monthly outflows - those are already provided)
   - Categories B-E: 2-3 items each
   - Use exact numbers from the data
   - Be specific and factual

2. WHY THIS MATTERS: One paragraph (3-4 sentences) that:
   - Explains the current situation contextually
   - Uses the runway months and cash position
   - Provides appropriate context based on the score
   - Example: "With 4 months of runway, your cash position is stable for the near term. This gives you time to plan without immediate pressure. However, it's worth monitoring closely if you're expecting any large expenses or if revenue becomes uncertain."

3. ASSUMPTIONS: List 2-4 key assumptions made in the calculation:
   - Data quality notes
   - Calculation assumptions
   - Example: "Cash balance reference point: Today", "Calculation based on 90 days of transaction data"

Return as JSON matching the required schema."""
    
    def _get_health_score_json_schema(self) -> dict[str, Any]:
        """Get JSON schema for health score descriptive text."""
        return {
            "type": "object",
            "properties": {
                "category_metrics": {
                    "type": "object",
                    "properties": {
                        "A": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 2,
                            "description": "2 items about burn rate stability/trends ",
                        },
                        "B": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 3,
                            "description": "Descriptive sentences for Profitability & Efficiency category",
                        },
                        "C": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 3,
                            "description": "Descriptive sentences for Revenue Quality & Momentum category",
                        },
                        "D": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 4,
                            "description": "Descriptive sentences for Working Capital & Liquidity category",
                        },
                        "E": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 3,
                            "description": "Descriptive sentences for Compliance & Data Confidence category",
                        },
                    },
                    "required": ["A", "B", "C", "D", "E"],
                    "additionalProperties": False,
                },
                "why_this_matters": {
                    "type": "string",
                    "description": "One paragraph explaining why the current situation matters contextually",
                },
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 4,
                    "description": "Key assumptions made in the calculation",
                },
            },
            "required": ["category_metrics", "why_this_matters", "assumptions"],
            "additionalProperties": False,
        }
    
    def _truncate_summary_if_needed(self, summary: dict[str, Any]) -> dict[str, Any]:
        """
        Truncate raw data summary if it's too large.
        
        Intelligently reduces size while preserving important information:
        - Limits invoice lists to top N items
        - Limits report rows
        - Preserves key metrics and totals
        
        Args:
            summary: Raw data summary dictionary
        
        Returns:
            Truncated summary dictionary
        """
        # Estimate current size
        summary_json = json.dumps(summary)
        estimated_tokens = self._estimate_tokens(summary_json)
        
        if estimated_tokens <= MAX_INPUT_TOKENS * 0.8:  # 80% threshold
            return summary
        
        logger.info(
            "Summary too large (%d estimated tokens), truncating...",
            estimated_tokens,
        )
        
        truncated = summary.copy()
        
        # Truncate receivables invoices (keep top 20 by amount/overdue)
        if "receivables" in truncated and isinstance(truncated["receivables"], dict):
            invoices = truncated["receivables"].get("invoices", [])
            if isinstance(invoices, list) and len(invoices) > 20:
                # Sort by overdue amount (descending) and take top 20
                sorted_invoices = sorted(
                    invoices,
                    key=lambda x: x.get("overdue_amount", 0) or x.get("amount", 0),
                    reverse=True,
                )
                truncated["receivables"]["invoices"] = sorted_invoices[:20]
                logger.debug("Truncated receivables invoices from %d to 20", len(invoices))
        
        # Truncate payables invoices (keep top 20 by amount/overdue)
        if "payables" in truncated and isinstance(truncated["payables"], dict):
            invoices = truncated["payables"].get("invoices", [])
            if isinstance(invoices, list) and len(invoices) > 20:
                # Sort by amount (descending) and take top 20
                sorted_invoices = sorted(
                    invoices,
                    key=lambda x: x.get("amount", 0) or 0,
                    reverse=True,
                )
                truncated["payables"]["invoices"] = sorted_invoices[:20]
                logger.debug("Truncated payables invoices from %d to 20", len(invoices))
        
        # Truncate report structures (limit rows)
        for report_key in ["balance_sheet_current", "balance_sheet_prior", "profit_loss"]:
            if report_key in truncated and isinstance(truncated[report_key], dict):
                truncated[report_key] = self._truncate_report_structure(
                    truncated[report_key],
                    max_rows=30,
                )
        
        # Truncate accounts list if too large
        if "accounts" in truncated and isinstance(truncated["accounts"], list):
            if len(truncated["accounts"]) > 50:
                truncated["accounts"] = truncated["accounts"][:50]
                logger.debug("Truncated accounts from %d to 50", len(truncated["accounts"]))
        
        # Re-estimate after truncation
        truncated_json = json.dumps(truncated)
        new_estimated_tokens = self._estimate_tokens(truncated_json)
        logger.info(
            "After truncation: %d estimated tokens (reduced from %d)",
            new_estimated_tokens,
            estimated_tokens,
        )
        
        return truncated
    
    def _truncate_report_structure(
        self,
        report: dict[str, Any],
        max_rows: int = 30,
    ) -> dict[str, Any]:
        """
        Truncate report structure by limiting rows.
        
        Args:
            report: Report structure dictionary
            max_rows: Maximum rows to keep
        
        Returns:
            Truncated report structure
        """
        if not isinstance(report, dict):
            return report
        
        truncated = report.copy()
        
        # If report has rows/rows_list, limit them
        if "rows" in truncated and isinstance(truncated["rows"], list):
            if len(truncated["rows"]) > max_rows:
                truncated["rows"] = truncated["rows"][:max_rows]
        
        if "Rows" in truncated and isinstance(truncated["Rows"], list):
            if len(truncated["Rows"]) > max_rows:
                truncated["Rows"] = truncated["Rows"][:max_rows]
        
        return truncated

