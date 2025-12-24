"""
Cache Service for Xero Data
Manages caching of Executive Summary and financial data.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.executive_summary_cache import ExecutiveSummaryCache
from app.models.financial_cache import FinancialCache

logger = logging.getLogger(__name__)




class CacheService:
    """
    Service for managing Xero data cache.
    
    Handles:
    - Executive Summary (current month with TTL, historical months forever)
    - Receivables, Payables, P&L (with TTL)
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache_ttl_minutes = settings.cache_ttl_minutes
    
    def _calculate_expires_at(self) -> datetime:
        """Calculate expiration time based on TTL."""
        return datetime.now(timezone.utc) + timedelta(minutes=self.cache_ttl_minutes)
    
    def _get_month_end_date(self, year: int, month: int) -> date:
        """Get the last day of a given month."""
        if month == 12:
            return date(year, 12, 31)
        else:
            next_month = date(year, month + 1, 1)
            return next_month - timedelta(days=1)
    
    def _calculate_historical_month_ends(self, months: int) -> list[date]:
        """Calculate month-end dates for historical months."""
        today = datetime.now(timezone.utc).date()
        current_month_start = today.replace(day=1)
        
        month_ends = []
        for i in range(1, months + 1):
            target_year = current_month_start.year
            target_month = current_month_start.month - i
            
            while target_month <= 0:
                target_month += 12
                target_year -= 1
            
            month_end = self._get_month_end_date(target_year, target_month)
            month_ends.append(month_end)
        
        return month_ends
    
    async def get_cached_executive_summary(
        self,
        organization_id: UUID,
        months: int = 3,
    ) -> tuple[Optional[dict[str, Any]], dict[date, dict[str, Any]], list[date]]:
        """
        Get cached Executive Summary data.
        
        Args:
            organization_id: Organization UUID
            months: Number of historical months to check
        
        Returns:
            Tuple of:
            - current_month_data: Current month data if fresh, else None
            - historical_cached: Dict mapping report_date -> cached data
            - missing_dates: List of month-end dates that need fetching
        """
        # 1. Get current month cache
        financial_cache = await self._get_financial_cache(organization_id)
        current_month_data = None
        if financial_cache and financial_cache.is_executive_summary_current_fresh:
            current_month_data = financial_cache.executive_summary_current
        
        # 2. Get historical months cache
        historical_dates = self._calculate_historical_month_ends(months)
        
        stmt = (
            select(ExecutiveSummaryCache)
            .where(ExecutiveSummaryCache.organization_id == organization_id)
            .where(ExecutiveSummaryCache.report_date.in_(historical_dates))
        )
        result = await self.db.execute(stmt)
        cached_historical = result.scalars().all()
        
        # Build map: report_date -> cached_data
        historical_map = {
            item.report_date: item.to_dict() for item in cached_historical
        }
        
        # Determine missing dates
        missing_dates = [d for d in historical_dates if d not in historical_map]
        
        return current_month_data, historical_map, missing_dates
    
    async def get_cached_financial_data(
        self,
        organization_id: UUID,
    ) -> Optional[dict[str, Any]]:
        """
        Get cached receivables/payables/P&L data.
        
        Args:
            organization_id: Organization UUID
        
        Returns:
            Dict with receivables, payables, profit_loss if fresh, else None
        """
        financial_cache = await self._get_financial_cache(organization_id)
        
        if financial_cache and financial_cache.is_fresh:
            return {
                "invoices_receivable": financial_cache.invoices_receivable,
                "invoices_payable": financial_cache.invoices_payable,
                "profit_loss": financial_cache.profit_loss_data,
            }
        
        return None
    
    async def save_executive_summary_cache(
        self,
        organization_id: UUID,
        current: dict[str, Any],
        historical: list[dict[str, Any]],
    ) -> None:
        """
        Save Executive Summary data to cache.
        
        Args:
            organization_id: Organization UUID
            current: Current month Executive Summary data
            historical: List of historical month data
        """
        now = datetime.now(timezone.utc)
        expires_at = self._calculate_expires_at()
        
        # 1. Save current month to FinancialCache
        financial_cache = await self._get_or_create_financial_cache(organization_id)
        financial_cache.executive_summary_current = current
        financial_cache.executive_summary_current_fetched_at = now
        financial_cache.executive_summary_current_expires_at = expires_at
        
        # 2. Save historical months to ExecutiveSummaryCache
        for month_data in historical:
            report_date_str = month_data.get("report_date")
            if not report_date_str:
                logger.warning("Missing report_date in historical data, skipping")
                continue
            
            report_date = date.fromisoformat(report_date_str)
            
            # Check if already exists
            stmt = (
                select(ExecutiveSummaryCache)
                .where(ExecutiveSummaryCache.organization_id == organization_id)
                .where(ExecutiveSummaryCache.report_date == report_date)
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing
                existing.cash_position = Decimal(str(month_data["cash_position"]))
                existing.cash_spent = Decimal(str(month_data["cash_spent"]))
                existing.cash_received = Decimal(str(month_data["cash_received"]))
                existing.operating_expenses = Decimal(str(month_data["operating_expenses"]))
                existing.raw_data = month_data.get("raw_data")
                existing.fetched_at = now
            else:
                # Create new
                new_cache = ExecutiveSummaryCache(
                    organization_id=organization_id,
                    report_date=report_date,
                    cash_position=Decimal(str(month_data["cash_position"])),
                    cash_spent=Decimal(str(month_data["cash_spent"])),
                    cash_received=Decimal(str(month_data["cash_received"])),
                    operating_expenses=Decimal(str(month_data["operating_expenses"])),
                    raw_data=month_data.get("raw_data"),
                    fetched_at=now,
                )
                self.db.add(new_cache)
        
        await self.db.commit()
        logger.info(
            "Saved Executive Summary cache for org %s: current + %d historical months",
            organization_id,
            len(historical),
        )
    
    async def save_financial_data_cache(
        self,
        organization_id: UUID,
        receivables: dict[str, Any],
        payables: dict[str, Any],
        profit_loss: dict[str, Any],
    ) -> None:
        """
        Save receivables/payables/P&L to cache.
        
        Args:
            organization_id: Organization UUID
            receivables: Receivables data
            payables: Payables data
            profit_loss: Profit & Loss data
        """
        now = datetime.now(timezone.utc)
        expires_at = self._calculate_expires_at()
        
        financial_cache = await self._get_or_create_financial_cache(organization_id)
        financial_cache.invoices_receivable = receivables
        financial_cache.invoices_payable = payables
        financial_cache.profit_loss_data = profit_loss
        financial_cache.fetched_at = now
        financial_cache.expires_at = expires_at
        
        await self.db.commit()
        logger.info("Saved financial data cache for org %s", organization_id)
    
    async def invalidate_cache(self, organization_id: UUID) -> None:
        """
        Invalidate all cache for an organization.
        
        Used when Xero is disconnected or force refresh is requested.
        
        Args:
            organization_id: Organization UUID
        """
        # Delete FinancialCache
        financial_cache = await self._get_financial_cache(organization_id)
        if financial_cache:
            await self.db.delete(financial_cache)
        
        # Delete all ExecutiveSummaryCache records
        stmt = (
            select(ExecutiveSummaryCache)
            .where(ExecutiveSummaryCache.organization_id == organization_id)
        )
        result = await self.db.execute(stmt)
        historical_cache = result.scalars().all()
        for cache in historical_cache:
            await self.db.delete(cache)
        
        await self.db.commit()
        logger.info("Invalidated all cache for org %s", organization_id)
    
    async def _get_financial_cache(
        self, organization_id: UUID
    ) -> Optional[FinancialCache]:
        """Get FinancialCache for organization, if it exists."""
        stmt = select(FinancialCache).where(
            FinancialCache.organization_id == organization_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def _get_or_create_financial_cache(
        self, organization_id: UUID
    ) -> FinancialCache:
        """Get or create FinancialCache for organization."""
        cache = await self._get_financial_cache(organization_id)
        if cache is None:
            cache = FinancialCache(
                organization_id=organization_id,
                fetched_at=datetime.now(timezone.utc),
                expires_at=self._calculate_expires_at(),
            )
            self.db.add(cache)
        return cache

