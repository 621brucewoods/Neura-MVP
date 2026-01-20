"""
Sync Service
Manages the asynchronous synchronization process and state updates.
"""

import logging
from datetime import datetime, timezone
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

    async def run_sync(self, start_date, end_date, force_refresh: bool = False):
        """
        Main entry point for the background task.
        Note: Status is already set to IN_PROGRESS/CONNECTING by the trigger endpoint,
        so we don't need to set it again here.
        """
        try:
            # Status already set to CONNECTING by trigger endpoint, so we proceed directly
            
            # 2. Setup Xero Client
            cache_service = CacheService(self.db)
            try:
                sdk_client = await create_xero_sdk_client(self.organization_id, self.db)
                data_fetcher = XeroDataFetcher(sdk_client, cache_service=cache_service, db=self.db)
            except Exception as e:
                await self._update_status(SyncStatus.FAILED, None, error=f"Xero Connection Error: {str(e)}")
                return

            # 3. Fetch Data
            await self._update_status(SyncStatus.IN_PROGRESS, SyncStep.IMPORTING)
            financial_data = await data_fetcher.fetch_all_data(
                organization_id=self.organization_id,
                start_date=start_date,
                end_date=end_date,
                force_refresh=force_refresh,
            )
            
             # Commit token updates
            if data_fetcher.session_manager:
                await data_fetcher.session_manager.commit_all()

            # 4. Fetch Monthly P&L (used by ALL services: metrics, health score, AI summary)
            await self._update_status(SyncStatus.IN_PROGRESS, SyncStep.CALCULATING)
            
            monthly_pnl_data = None
            try:
                # Fetch monthly P&L (uses batched fetching to avoid rate limits)
                monthly_pnl_raw = await data_fetcher.orchestrator.fetch_monthly_pnl_with_cache(
                    organization_id=self.organization_id,
                    num_months=12,
                    force_refresh=force_refresh,
                )
                
                # Extract P&L totals from monthly data
                account_map = financial_data.get("account_type_map", {})
                if monthly_pnl_raw and account_map:
                    monthly_pnl_data = Extractors.extract_monthly_pnl_totals(
                        monthly_pnl_raw,
                        account_map,
                    )
                    logger.info(f"Extracted {len(monthly_pnl_data)} months of P&L data")
            except Exception as e:
                logger.warning(f"Failed to fetch monthly P&L: {e}")
                monthly_pnl_data = None
            
            # 4.5 Calculate Metrics (using monthly P&L data)
            metrics = InsightsService.calculate_all_insights(financial_data, monthly_pnl_data)
            raw_data_summary = DataSummarizer.summarize(financial_data, start_date, end_date, monthly_pnl_data)

            # 4.6 Calculate Health Score (using same monthly P&L data)
            health_score_payload = None
            try:
                
                # Prepare data for Health Score calculation
                # Note: P&L data now comes from monthly_pnl_data (rolling 3-month)
                # instead of trial_balance_pnl (YTD cumulative)
                extracted = financial_data.get("extracted", {})
                balance_sheet_totals = extracted.get("balance_sheet", {})
                invoices_receivable = financial_data.get("invoices_receivable", {})
                invoices_payable = financial_data.get("invoices_payable", {})
                
                # Calculate Health Score using monthly P&L data
                health_score = HealthScoreCalculator.calculate(
                    balance_sheet_totals=balance_sheet_totals,
                    invoices_receivable=invoices_receivable,
                    invoices_payable=invoices_payable,
                    monthly_pnl_data=monthly_pnl_data,
                )
                
                # Add metadata
                health_score["generated_at"] = datetime.now(timezone.utc).isoformat()
                health_score["periods"] = {
                    "pnl_monthly": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "months": len(monthly_pnl_data) if monthly_pnl_data else 1,
                    },
                    "balance_sheet_asof": end_date.isoformat(),
                }
                
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
                calc_metrics.health_score_payload = health_score_payload  # NEW: Save health score
                calc_metrics.calculated_at = generated_at
                calc_metrics.data_period_start = start_date
                calc_metrics.data_period_end = end_date
            else:
                # Create new
                calc_metrics = CalculatedMetrics(
                    organization_id=self.organization_id,
                    metrics_payload=metrics_payload,
                    health_score_payload=health_score_payload,  # NEW: Save health score
                    calculated_at=generated_at,
                    data_period_start=start_date,
                    data_period_end=end_date,
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
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
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
