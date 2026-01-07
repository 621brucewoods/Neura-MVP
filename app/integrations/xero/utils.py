"""
Xero Integration Utilities
Shared utility functions for Xero data processing.
"""

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


def to_json_serializable(obj: Any) -> Any:
    """
    Recursively convert any object to JSON-serializable format.
    
    Handles Xero SDK objects, enums, dates, decimals, etc.
    
    Args:
        obj: Object to convert
        
    Returns:
        JSON-serializable representation
    """
    if obj is None:
        return None
    
    # Handle dicts
    if isinstance(obj, dict):
        return {k: to_json_serializable(v) for k, v in obj.items()}
    
    # Handle lists
    if isinstance(obj, (list, tuple)):
        return [to_json_serializable(item) for item in obj]
    
    # Handle Xero SDK objects with to_dict method
    if hasattr(obj, "to_dict"):
        return to_json_serializable(obj.to_dict())
    
    # Handle primitives (already serializable)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    
    # Handle Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    
    # Handle dates/datetimes
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    
    # Handle enums
    if hasattr(obj, "value"):
        return to_json_serializable(obj.value)
    
    # Fallback: convert to string
    return str(obj)


def parse_currency_value(value: Any, default: str = "0.00") -> Decimal:
    """
    Robustly parse currency values from Xero cell values.
    
    Handles:
    - Currency symbols: $, £, €, USD, EUR, GBP, etc.
    - Parentheses for negatives: (500.00) → -500.00
    - Dashes/empty for zeros: -, —, "" → 0.00
    - European format: 1.234,56 (thousands=., decimal=,)
    - US/UK format: 1,234.56 (thousands=,, decimal=.)
    - None values
    
    Args:
        value: Raw cell value (string, number, None)
        default: Default value if parsing fails
        
    Returns:
        Decimal value or default
    """
    if value is None:
        return Decimal(default)
    
    try:
        # Convert to string
        value_str = str(value).strip()
        
        # Handle empty strings, dashes, em-dashes
        if not value_str or value_str in ("-", "—", "–", ""):
            return Decimal(default)
        
        # Remove currency symbols (common ones)
        currency_symbols = ["$", "£", "€", "USD", "EUR", "GBP", "AUD", "NZD", "CAD"]
        for symbol in currency_symbols:
            value_str = value_str.replace(symbol, "").strip()
        
        # Handle parentheses for negatives: (500.00) → -500.00
        if value_str.startswith("(") and value_str.endswith(")"):
            value_str = "-" + value_str[1:-1].strip()
        
        # Detect locale format by checking for European pattern (thousands=., decimal=,)
        # European: 1.234,56 or 1.234,56
        # US/UK: 1,234.56
        has_european_thousands = re.search(r'\d{1,3}(\.\d{3})+,\d{1,2}$', value_str)
        has_us_thousands = re.search(r'\d{1,3}(,\d{3})+\.\d{1,2}$', value_str)
        
        if has_european_thousands:
            # European format: remove thousands separator (.), replace decimal (,) with (.)
            value_str = value_str.replace(".", "").replace(",", ".")
        elif has_us_thousands:
            # US/UK format: remove thousands separator (,)
            value_str = value_str.replace(",", "")
        else:
            # No thousands separator, but might have comma as decimal (European)
            # Check if last comma is decimal separator
            if "," in value_str and "." not in value_str:
                # Likely European: 1234,56
                value_str = value_str.replace(",", ".")
            else:
                # Remove any remaining commas (safety)
                value_str = value_str.replace(",", "")
        
        # Parse to Decimal
        return Decimal(value_str)
        
    except Exception as e:
        logger.warning(
            "Failed to parse currency value '%s': %s. Using default: %s",
            value,
            e,
            default
        )
        return Decimal(default)


def parse_decimal(value: Any, default: str = "0.00") -> Decimal:
    """
    Legacy method for backward compatibility.
    Delegates to parse_currency_value.
    """
    return parse_currency_value(value, default)


def get_month_end(target_date: date) -> date:
    """
    Return the last day of the month for the given date.
    
    Args:
        target_date: Date to get month end for
        
    Returns:
        Last day of the month
    """
    next_month = target_date.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def calculate_months_ago(target_date: date, months: int) -> date:
    """
    Calculate date that is N months ago from target date.
    
    Handles month-end edge cases (e.g., Jan 31 - 1 month = Feb 28/29).
    
    Args:
        target_date: Reference date
        months: Number of months to go back
        
    Returns:
        Date that is months months before target_date
    """
    # Calculate target year and month
    target_year = target_date.year
    target_month = target_date.month
    
    # Calculate new month and year
    new_month = target_month - months
    new_year = target_year
    
    # Handle year rollover
    while new_month < 1:
        new_month += 12
        new_year -= 1
    
    # Try to create date with same day
    try:
        return date(new_year, new_month, target_date.day)
    except ValueError:
        # Day doesn't exist in target month (e.g., Jan 31 -> Feb 28/29)
        # Use last day of target month
        last_day = get_month_end(date(new_year, new_month, 1))
        return date(new_year, new_month, last_day.day)

