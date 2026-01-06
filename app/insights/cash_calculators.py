"""
Cash-related calculators: runway and pressure.
"""

from decimal import Decimal
from typing import Any, Optional

# No utils needed for cash calculators


class CashRunwayCalculator:
    """
    Calculates cash runway metrics from Executive Summary data.
    
    Cash runway = how long the business can operate at current burn rate.
    """
    
    @staticmethod
    def calculate_monthly_burn_rate(cash_spent: float, cash_received: float) -> float:
        """
        Calculate monthly net burn rate.
        
        Args:
            cash_spent: Total cash spent in the month
            cash_received: Total cash received in the month
        
        Returns:
            Monthly burn rate (positive = burning cash, negative = growing cash)
        """
        return float(Decimal(str(cash_spent)) - Decimal(str(cash_received)))
    
    @staticmethod
    def calculate_runway_months(
        cash_position: float,
        monthly_burn_rate: float
    ) -> Optional[float]:
        """
        Calculate cash runway in months.
        
        Args:
            cash_position: Current cash balance
            monthly_burn_rate: Monthly net burn rate
        
        Returns:
            Runway in months, or None if calculation not applicable
        """
        if monthly_burn_rate == 0:
            return None
        
        if monthly_burn_rate < 0:
            return None
        
        return float(Decimal(str(cash_position)) / Decimal(str(monthly_burn_rate)))
    
    @staticmethod
    def calculate_runway_weeks(runway_months: Optional[float]) -> Optional[float]:
        """
        Convert runway from months to weeks.
        
        Args:
            runway_months: Runway in months (can be None)
        
        Returns:
            Runway in weeks, or None if input is None
        """
        if runway_months is None:
            return None
        
        return float(Decimal(str(runway_months)) * Decimal("4.33"))
    
    @staticmethod
    def get_runway_status(runway_months: Optional[float], cash_position: float) -> str:
        """
        Determine runway status based on months remaining and cash position.
        
        Args:
            runway_months: Runway in months (can be None or negative)
            cash_position: Current cash balance
        
        Returns:
            Status: "healthy", "warning", "critical", "negative", or "infinite"
        """
        # Check for negative cash position first
        if cash_position < 0:
            return "negative"
        
        if runway_months is None:
            return "infinite"
        
        if runway_months < 0:
            return "negative"
        
        if runway_months >= 6:
            return "healthy"
        elif runway_months >= 3:
            return "warning"
        else:
            return "critical"
    
    @staticmethod
    def calculate(
        cash_position: float,
        cash_spent: float,
        cash_received: float
    ) -> dict[str, Any]:
        """
        Calculate all cash runway metrics.
        
        Args:
            cash_position: Current cash balance
            cash_spent: Total cash spent in current month
            cash_received: Total cash received in current month
        
        Returns:
            Dictionary with all cash runway metrics
        """
        monthly_burn_rate = CashRunwayCalculator.calculate_monthly_burn_rate(
            cash_spent, cash_received
        )
        
        runway_months = CashRunwayCalculator.calculate_runway_months(
            cash_position, monthly_burn_rate
        )
        
        runway_weeks = CashRunwayCalculator.calculate_runway_weeks(runway_months)
        
        status = CashRunwayCalculator.get_runway_status(runway_months, cash_position)
        
        return {
            "current_cash": cash_position,
            "monthly_burn_rate": monthly_burn_rate,
            "runway_months": runway_months,
            "runway_weeks": runway_weeks,
            "status": status,
        }


class CashPressureCalculator:
    """
    Calculates cash pressure status (GREEN/AMBER/RED).
    
    Combines runway status with revenue volatility to determine overall pressure.
    """
    
    @staticmethod
    def calculate(
        runway_months: Optional[float],
        runway_status: str,
        revenue_volatility: Optional[float],
        cash_position: Optional[float] = None
    ) -> dict[str, Any]:
        """
        Calculate cash pressure status.
        
        Args:
            runway_months: Cash runway in months (None if infinite/profitable)
            runway_status: Runway status (healthy/warning/critical/negative/infinite)
            revenue_volatility: Revenue volatility coefficient (None if insufficient data)
            cash_position: Current cash balance (optional, for additional validation)
        
        Returns:
            Dictionary with pressure status and confidence
        """
        # Check for negative cash position first (regardless of runway status)
        if cash_position is not None and cash_position < 0:
            return {
                "status": "RED",
                "confidence": "high",
            }
        
        if runway_status == "negative":
            return {
                "status": "RED",
                "confidence": "high",
            }
        
        if runway_status == "infinite":
            return {
                "status": "GREEN",
                "confidence": "high",
            }
        
        if runway_status == "critical":
            return {
                "status": "RED",
                "confidence": "high",
            }
        
        if runway_status == "warning":
            if runway_months is not None and runway_months < 3.5:
                return {
                    "status": "AMBER",
                    "confidence": "high",
                }
            if revenue_volatility is not None and revenue_volatility > 50:
                return {
                    "status": "AMBER",
                    "confidence": "high",
                }
            return {
                "status": "AMBER",
                "confidence": "medium",
            }
        
        if runway_status == "healthy":
            if revenue_volatility is not None and revenue_volatility > 40:
                return {
                    "status": "AMBER",
                    "confidence": "medium",
                }
            return {
                "status": "GREEN",
                "confidence": "high",
            }
        
        return {
            "status": "AMBER",
            "confidence": "low",
        }

