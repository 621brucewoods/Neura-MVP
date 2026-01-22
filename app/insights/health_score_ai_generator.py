"""
Health Score AI Generator
Generates descriptive text for health score using OpenAI with structured JSON output.
"""

import json
import logging
from typing import Any

from app.insights.ai_insight_service import AIInsightService

logger = logging.getLogger(__name__)


class HealthScoreAIGenerator:
    """
    Generates descriptive text for health score using AI.
    
    Uses OpenAI to convert health score data into human-readable,
    contextual descriptions that match the UI/UX requirements.
    """
    
    def __init__(self):
        """Initialize AI insight service."""
        self.ai_service = AIInsightService()
    
    def generate_descriptive_text(
        self,
        health_score: dict[str, Any],
        key_metrics: dict[str, Any],
        raw_data_summary: dict[str, Any],
        calculated_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate descriptive text for health score using AI.
        
        Args:
            health_score: Complete health score dictionary from HealthScoreCalculator
            key_metrics: Key metrics dictionary (current_cash, monthly_burn, etc.)
            raw_data_summary: Summarized raw financial data for context
        
        Returns:
            Dictionary with:
            - category_metrics: Dict mapping category IDs to arrays of descriptive strings
            - why_this_matters: Contextual explanation paragraph
            - assumptions: Array of assumption strings
        """
        try:
            result = self.ai_service._generate_health_score_text(
                health_score=health_score,
                key_metrics=key_metrics,
                raw_data_summary=raw_data_summary,
                calculated_metrics=calculated_metrics,
            )
            
            # Validate result structure
            if not result:
                logger.warning("AI returned empty result")
                return {
                    "category_metrics": {},
                    "why_this_matters": "",
                    "assumptions": [],
                }
            
            return result
        except Exception as e:
            logger.error("Failed to generate health score descriptive text: %s", e, exc_info=True)
            # Return empty structure on error (graceful degradation)
            return {
                "category_metrics": {},
                "why_this_matters": "",
                "assumptions": [],
            }
