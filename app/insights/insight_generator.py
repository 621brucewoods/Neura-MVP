"""
Insight Generator
Converts financial metrics into ranked, actionable insights using AI.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.insights.ai_insight_service import AIInsightService

logger = logging.getLogger(__name__)


class InsightGenerator:
    """
    Generates insights from financial metrics using AI.
    
    Uses OpenAI to convert raw metrics and data summaries into
    ranked, actionable insights.
    """
    
    def __init__(self):
        """Initialize AI insight service."""
        self.ai_service = AIInsightService()
    
    def generate_insights(
        self,
        metrics: dict[str, Any],
        raw_data_summary: dict[str, Any],
        balance_sheet_date: str,
    ) -> list[dict[str, Any]]:
        """
        Generate insights using AI.
        
        Args:
            metrics: Combined financial metrics dictionary
            raw_data_summary: Summarized raw financial data
            balance_sheet_date: Balance sheet as-of date (ISO format)
        
        Returns:
            List of insight dictionaries (1-3 items), ranked by urgency
        """
        try:
            insights = self.ai_service.generate_insights(
                metrics=metrics,
                raw_data_summary=raw_data_summary,
                balance_sheet_date=balance_sheet_date,
            )
            
            # Add insight_id and generated_at to each insight
            for insight in insights:
                if "insight_id" not in insight:
                    insight["insight_id"] = str(uuid.uuid4())
                if "generated_at" not in insight:
                    insight["generated_at"] = datetime.now(timezone.utc).isoformat()
            
            return insights
            
        except Exception as e:
            logger.error("Failed to generate AI insights: %s", e, exc_info=True)
            raise

