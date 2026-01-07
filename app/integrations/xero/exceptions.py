"""
Xero Integration Exceptions
Custom exceptions for Xero integration.
"""

from typing import Optional


class XeroDataFetchError(Exception):
    """Exception for data fetching errors."""
    
    def __init__(
        self, 
        message: str, 
        status_code: Optional[int] = None, 
        endpoint: Optional[str] = None
    ):
        self.message = message
        self.status_code = status_code
        self.endpoint = endpoint
        super().__init__(self.message)

