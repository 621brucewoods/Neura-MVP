"""
Sync Service
Manages the asynchronous synchronization process and state updates.
"""

import logging
from datetime import date, datetime, timezone
import traceback
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, SyncStatus, SyncStep
from app.integrations.xero.data_fetcher import XeroDataFetcher
from app.integrations.xero.sdk_client import create_xero_sdk_client
from app.integrations.xero.cache_service import CacheService
from app.integrations.xero.extractors import Extractors
from app.insights.service import InsightsService
from app.insights.data_summarizer import DataSummarizer
from app.insights.insight_generator import InsightGenerator
from app.insights.health_score_calculator import HealthScoreCalculator
from app.models.insight import Insight as InsightModel
from app.models.calculated_metrics import CalculatedMetrics
from app.insights.schemas import (
    CashRunwayMetrics,
    LeadingIndicatorsMetrics,
    CashPressureMetrics,
    ProfitabilityMetrics,
    UpcomingCommitmentsMetrics,
)

logger = logging.getLogger(__name__)


class SyncService:
    """
    Service to handle the full sync process:
    1. Update Status -> CONNECTING/IMPORTING
    2. Fetch Xero Data
    3. Update Status -> CALCULATING
    4. Calculate Metrics
    5. Update Status -> GENERATING_INSIGHTS
    6. Generate AI Insights
    7. Update Status -> COMPLETED
    """

    def __init__(self, db: AsyncSession, organization_id: UUID):
        self.db = db
        self.organization_id = organization_id

    async def _update_status(self, status: SyncStatus, step: Optional[SyncStep] = None, error: Optional[str] = None):
        """Helper to update organization sync status."""
        try:
            stmt = select(Organization).where(Organization.id == self.organization_id)
            result = await self.db.execute(stmt)
            org = result.scalar_one_or_none()
            
            if org:
                org.sync_status = status
                if step:
                    org.sync_step = step
                if error:
                    org.last_sync_error = error
                
                await self.db.commit()
                # logger.info(f"Updated Organization {self.organization_id} status to {status}/{step}")
        except Exception as e:
            logger.error(f"Failed to update sync status: {e}")
            await self.db.rollback()

    async def run_sync(self, balance_sheet_date: date, force_refresh: bool = False):
        """
        Main entry point for the background task.
        
        Args:
            balance_sheet_date: The "as of" date for Balance Sheet (typically today)
            force_refresh: If True, bypass cache and fetch fresh data
            
        Data fetched:
        - Balance Sheet: as of balance_sheet_date
        - Monthly P&L: last 12 months from today (for trends/health score)
        - AR/AP Invoices: current outstanding
        
        Note: Status is already set to IN_PROGRESS/CONNECTING by the trigger endpoint.
        """
        try:
            # Setup Xero Client
            cache_service = CacheService(self.db)
            try:
                sdk_client = await create_xero_sdk_client(self.organization_id, self.db)
                data_fetcher = XeroDataFetcher(sdk_client, cache_service=cache_service, db=self.db)
            except Exception as e:
                await self._update_status(SyncStatus.FAILED, None, error=f"Xero Connection Error: {str(e)}")
                return

            # Fetch Balance Sheet and AR/AP data
            await self._update_status(SyncStatus.IN_PROGRESS, SyncStep.IMPORTING)
            financial_data = await data_fetcher.fetch_all_data(
                organization_id=self.organization_id,
                balance_sheet_date=balance_sheet_date,
                force_refresh=force_refresh,
            )
            
            # Commit token updates
            if data_fetcher.session_manager:
                await data_fetcher.session_manager.commit_all()

            # Fetch Monthly P&L (12 months for trends, health score, AI summary)
            await self._update_status(SyncStatus.IN_PROGRESS, SyncStep.CALCULATING)
            
            # Get account map for P&L extraction (needed for both fetch and cache)
            account_map = financial_data.get("account_type_map", {})
            
            monthly_pnl_data = None
            try:
                monthly_pnl_raw = await data_fetcher.orchestrator.fetch_monthly_pnl_with_cache(
                    organization_id=self.organization_id,
                    account_map=account_map,  # Pass account_map for cache extraction
                    num_months=12,
                    force_refresh=force_refresh,
                )
                
                # Extract P&L totals from monthly data
                if monthly_pnl_raw and account_map:
                    monthly_pnl_data = Extractors.extract_monthly_pnl_totals(
                        monthly_pnl_raw,
                        account_map,
                    )
                    # Log how many months have actual data
                    months_with_data = sum(1 for m in monthly_pnl_data if m.get("has_data"))
                    logger.info(f"Extracted P&L: {months_with_data} months with data out of {len(monthly_pnl_data)} fetched")
            except Exception as e:
                logger.warning(f"Failed to fetch monthly P&L: {e}")
                monthly_pnl_data = None
            
            # Calculate Metrics
            metrics = InsightsService.calculate_all_insights(financial_data, monthly_pnl_data)
            raw_data_summary = DataSummarizer.summarize(financial_data, balance_sheet_date, monthly_pnl_data)

            # Calculate Health Score
            health_score_payload = None
            try:
                extracted = financial_data.get("extracted", {})
                balance_sheet_totals = extracted.get("balance_sheet", {})
                invoices_receivable = financial_data.get("invoices_receivable", {})
                invoices_payable = financial_data.get("invoices_payable", {})
                
                health_score = HealthScoreCalculator.calculate(
                    balance_sheet_totals=balance_sheet_totals,
                    invoices_receivable=invoices_receivable,
                    invoices_payable=invoices_payable,
                    monthly_pnl_data=monthly_pnl_data,
                )
                
                # Add metadata
                months_with_data = sum(1 for m in (monthly_pnl_data or []) if m.get("has_data"))
                health_score["generated_at"] = datetime.now(timezone.utc).isoformat()
                health_score["periods"] = {
                    "balance_sheet_asof": balance_sheet_date.isoformat(),
                    "monthly_pnl": {
                        "months_fetched": len(monthly_pnl_data) if monthly_pnl_data else 0,
                        "months_with_data": months_with_data,
                    },
                }
                
                # Generate AI descriptive text (during sync, not fetch)
                try:
                    from app.insights.health_score_ai_generator import HealthScoreAIGenerator
                    
                    # Generate 2 hardcoded items for Category A
                    key_metrics = health_score.get("key_metrics", {})
                    cash = abs(key_metrics.get("current_cash", 0))
                    burn = abs(key_metrics.get("monthly_burn", 0))
                    period = key_metrics.get("period_label", "the past 90 days").lower()
                    hardcoded_a = [
                        f"Current cash balance of ${cash:,.0f} across all connected accounts",
                        f"Average monthly outflows of ${burn:,.0f} over {period}"
                    ]
                    
                    # Run AI generation in executor (blocking call)
                    import asyncio
                    loop = asyncio.get_running_loop()
                    
                    def _generate_text():
                        generator = HealthScoreAIGenerator()
                        return generator.generate_descriptive_text(
                            health_score=health_score,
                            key_metrics=key_metrics,
                            raw_data_summary=raw_data_summary,
                            calculated_metrics=metrics,
                        )
                    
                    ai_text = await loop.run_in_executor(None, _generate_text)
                    
                    # Merge AI-generated text into health score
                    if ai_text.get("category_metrics"):
                        for category_id, category_metrics_list in ai_text["category_metrics"].items():
                            if category_id in health_score["category_scores"]:
                                # Prepend hardcoded items for Category A
                                if category_id == "A":
                                    health_score["category_scores"][category_id]["metrics"] = hardcoded_a + category_metrics_list
                                else:
                                    health_score["category_scores"][category_id]["metrics"] = category_metrics_list
                    else:
                        health_score["category_scores"]["A"]["metrics"] = hardcoded_a
                    
                    if ai_text.get("why_this_matters"):
                        health_score["why_this_matters"] = ai_text["why_this_matters"]
                    
                    if ai_text.get("assumptions"):
                        health_score["assumptions"] = ai_text["assumptions"]
                except Exception as e:
                    logger.warning(f"Failed to generate AI descriptive text for health score: {e}")
                    health_score["category_scores"]["A"]["metrics"] = hardcoded_a
                
                health_score_payload = health_score
                logger.info(
                    f"Health Score calculated: score={health_score['scorecard']['final_score']}, "
                    f"grade={health_score['scorecard']['grade']}, "
                    f"confidence={health_score['scorecard']['confidence']}"
                )
            except Exception as e:
                logger.warning(f"Failed to calculate health score during sync: {e}")
                health_score_payload = None

            # Persist Metrics Snapshot
            # This allows the dashboard to load without re-fetching Xero data
            generated_at = datetime.now(timezone.utc)
            
            # Convert dictionaries to Pydantic models, then serialize for storage
            # This validates the structure and ensures consistency with the API schema
            def serialize_metric(metric_dict, model_class):
                """Convert metric dict to Pydantic model and serialize."""
                if not metric_dict:
                    return None
                try:
                    return model_class(**metric_dict).model_dump()
                except Exception as e:
                    logger.warning(f"Failed to serialize {model_class.__name__}: {e}, using dict as-is")
                    return metric_dict
            
            metrics_payload = {
                "cash_runway": serialize_metric(metrics.get("cash_runway"), CashRunwayMetrics),
                "cash_pressure": serialize_metric(metrics.get("cash_pressure"), CashPressureMetrics),
                "leading_indicators": serialize_metric(metrics.get("leading_indicators"), LeadingIndicatorsMetrics),
                "profitability": serialize_metric(metrics.get("profitability"), ProfitabilityMetrics),
                "upcoming_commitments": serialize_metric(metrics.get("upcoming_commitments"), UpcomingCommitmentsMetrics),
            }
            
            stmt = select(CalculatedMetrics).where(CalculatedMetrics.organization_id == self.organization_id)
            result = await self.db.execute(stmt)
            calc_metrics = result.scalar_one_or_none()
            
            if calc_metrics:
                # Update existing
                calc_metrics.metrics_payload = metrics_payload
                calc_metrics.health_score_payload = health_score_payload
                calc_metrics.calculated_at = generated_at
                calc_metrics.data_period_end = datetime.combine(balance_sheet_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            else:
                # Create new
                calc_metrics = CalculatedMetrics(
                    organization_id=self.organization_id,
                    metrics_payload=metrics_payload,
                    health_score_payload=health_score_payload,
                    calculated_at=generated_at,
                    data_period_end=datetime.combine(balance_sheet_date, datetime.min.time()).replace(tzinfo=timezone.utc),
                )
                self.db.add(calc_metrics)
                
            await self.db.commit()

            # 5. Generate AI Insights (The Slow Part)
            await self._update_status(SyncStatus.IN_PROGRESS, SyncStep.GENERATING_INSIGHTS)
            
            # Run blocking AI call in a thread if possible, but for now just calling it directly 
            # as this whole run_sync is referenced in BackgroundTasks, so it is already async from the API perspective.
            # However, since generate_insights uses requests/sync client, it keeps the event loop blocked.
            # ideally we wrap this in run_in_executor to avoid blocking the MAIN event loop if using uvicorn workers.
            
            # Since OpenAI client is sync, we should use run_in_executor
            import asyncio
            loop = asyncio.get_running_loop()
            
            insight_generator = InsightGenerator()
            
            # Wrapper for the sync call
            def _generate():
                return insight_generator.generate_insights(
                    metrics={
                        "cash_runway": metrics["cash_runway"],
                        "cash_pressure": metrics["cash_pressure"],
                        "leading_indicators": metrics["leading_indicators"],
                        "profitability": metrics["profitability"],
                        "upcoming_commitments": metrics["upcoming_commitments"],
                    },
                    raw_data_summary=raw_data_summary,
                    balance_sheet_date=balance_sheet_date.isoformat(),
                )

            generated_insights = await loop.run_in_executor(None, _generate)

            # 6. Save Insights
            generated_at = datetime.now(timezone.utc)
            for insight_dict in generated_insights:
                # Upsert Logic
                stmt = select(InsightModel).where(
                    and_(
                        InsightModel.insight_id == insight_dict["insight_id"],
                        InsightModel.organization_id == self.organization_id,
                    )
                )
                result = await self.db.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.title = insight_dict["title"]
                    existing.severity = insight_dict["severity"]
                    existing.confidence_level = insight_dict["confidence_level"]
                    existing.summary = insight_dict["summary"]
                    existing.why_it_matters = insight_dict["why_it_matters"]
                    existing.recommended_actions = insight_dict["recommended_actions"]
                    existing.supporting_numbers = insight_dict.get("supporting_numbers", [])
                    existing.data_notes = insight_dict.get("data_notes")
                    existing.generated_at = generated_at
                else:
                    new_insight = InsightModel(
                        organization_id=self.organization_id,
                        insight_id=insight_dict["insight_id"],
                        insight_type=insight_dict["insight_type"],
                        title=insight_dict["title"],
                        severity=insight_dict["severity"],
                        confidence_level=insight_dict["confidence_level"],
                        summary=insight_dict["summary"],
                        why_it_matters=insight_dict["why_it_matters"],
                        recommended_actions=insight_dict["recommended_actions"],
                        supporting_numbers=insight_dict.get("supporting_numbers", []),
                        data_notes=insight_dict.get("data_notes"),
                        generated_at=generated_at,
                    )
                    self.db.add(new_insight)
            
            await self.db.commit()

            # 7. Complete
            await self._update_status(SyncStatus.COMPLETED, SyncStep.COMPLETED)

        except Exception as e:
            logger.error(f"Sync process failed: {e}")
            logger.error(traceback.format_exc())
            await self._update_status(SyncStatus.FAILED, error=str(e))
