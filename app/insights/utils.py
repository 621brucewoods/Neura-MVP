"""
Utility functions for safe data access in insights calculations.
"""

from typing import Any


def safe_get(data: Any, key: str, default: Any = None) -> Any:
    """
    Safely get value from dict, handling None values.
    
    Args:
        data: Dictionary or object with .get() method
        key: Key to retrieve
        default: Default value if key missing or value is None
        
    Returns:
        Value from dict, or default if missing/None
    """
    if not isinstance(data, dict):
        return default
    
    value = data.get(key, default)
    return default if value is None else value


def safe_list_get(data: Any, index: int, default: Any = None) -> Any:
    """
    Safely get item from list by index.
    
    Args:
        data: List to access
        index: Index to retrieve
        default: Default value if index out of range
        
    Returns:
        Item at index, or default if out of range
    """
    if not isinstance(data, list) or not data:
        return default
    
    try:
        return data[index] if -len(data) <= index < len(data) else default
    except (IndexError, TypeError):
        return default


def safe_str_lower(value: Any, default: str = "") -> str:
    """
    Safely convert value to lowercase string.
    
    Args:
        value: Value to convert
        default: Default if value is None or not string-like
        
    Returns:
        Lowercase string, or default
    """
    if value is None:
        return default
    
    try:
        return str(value).lower()
    except (AttributeError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safely convert value to float.
    
    Args:
        value: Value to convert
        default: Default if conversion fails
        
    Returns:
        Float value, or default
    """
    if value is None:
        return default
    
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Remove commas and whitespace
            cleaned = value.replace(",", "").strip()
            return float(cleaned) if cleaned else default
        return default
    except (ValueError, TypeError, AttributeError):
        return default

