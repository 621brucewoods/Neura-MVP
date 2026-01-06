"""
Xero Retry Handler
Handles retries with exponential backoff and Retry-After header support.
"""

import asyncio
import logging
from typing import Any, Callable, Optional

from xero_python.exceptions import ApiException

logger = logging.getLogger(__name__)


class XeroRetryHandler:
    """
    Handles retries for Xero API calls with exponential backoff.
    
    Supports:
    - Exponential backoff: 1s, 2s, 4s, 8s, 16s (max)
    - Retry-After header from 429 responses
    - Maximum retry attempts
    """
    
    def __init__(
        self,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        max_backoff: float = 16.0,
    ):
        """
        Initialize retry handler.
        
        Args:
            max_retries: Maximum number of retry attempts (default: 5)
            backoff_base: Base seconds for exponential backoff (default: 1.0)
            max_backoff: Maximum backoff seconds (default: 16.0)
        """
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
    
    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute a function with retry logic.
        
        Handles:
        - 429 (Too Many Requests) with Retry-After header
        - Other ApiException errors with exponential backoff
        - Maximum retry limit
        
        Args:
            func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            ApiException: If all retries exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            
            except ApiException as e:
                last_exception = e
                status = getattr(e, "status", None)
                
                # Check for permanent client errors (400) - DO NOT RETRY
                if status == 400:
                    # Check if it's invalid_grant (token expired/revoked)
                    error_message = str(e).lower()
                    if "invalid_grant" in error_message:
                        logger.error(
                            "Invalid grant error (400) - token expired or revoked. "
                            "User must reconnect Xero. Not retrying."
                        )
                        # Fail immediately - retrying won't help
                        raise
                    
                    # Other 400 errors are also permanent client errors
                    logger.error(
                        "Client error (400) - %s. Not retrying.",
                        str(e)[:100]  # Truncate long error messages
                    )
                    raise
                
                # Check if it's a 429 (rate limit) error - RETRY with Retry-After
                if status == 429:
                    # Try to extract Retry-After header
                    retry_after = self._extract_retry_after(e)
                    
                    if retry_after:
                        wait_seconds = min(retry_after, self.max_backoff)
                        logger.info(
                            "Rate limited (429). Retrying after %.1f seconds (attempt %d/%d)...",
                            wait_seconds,
                            attempt + 1,
                            self.max_retries + 1
                        )
                        await asyncio.sleep(wait_seconds)
                        continue
                
                # Check if it's a 5xx server error - RETRY with exponential backoff
                if status and 500 <= status < 600:
                    if attempt < self.max_retries:
                        wait_seconds = min(
                            self.backoff_base * (2 ** attempt),
                            self.max_backoff
                        )
                        logger.warning(
                            "Server error (status: %s). Retrying after %.1f seconds (attempt %d/%d)...",
                            status,
                            wait_seconds,
                            attempt + 1,
                            self.max_retries + 1
                        )
                        await asyncio.sleep(wait_seconds)
                        continue
                    else:
                        logger.error(
                            "All retry attempts exhausted for server error. Status: %s",
                            status
                        )
                        raise
                
                # For other errors (non-400, non-429, non-5xx), fail immediately
                logger.error(
                    "API error (status: %s) - %s. Not retrying.",
                    status or "unknown",
                    str(e)[:100]
                )
                raise
        
        # Should never reach here, but just in case
        if last_exception:
            raise last_exception
    
    def _extract_retry_after(self, exception: ApiException) -> Optional[float]:
        """
        Extract Retry-After header value from ApiException.
        
        Args:
            exception: ApiException with response headers
            
        Returns:
            Retry-After seconds or None if not found
        """
        try:
            # Check if exception has headers attribute
            if hasattr(exception, "headers") and exception.headers:
                retry_after = exception.headers.get("Retry-After")
                if retry_after:
                    try:
                        return float(retry_after)
                    except (ValueError, TypeError):
                        pass
            
            # Check if exception has response attribute with headers
            if hasattr(exception, "response") and exception.response:
                if hasattr(exception.response, "headers"):
                    retry_after = exception.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            return float(retry_after)
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            logger.debug("Failed to extract Retry-After header: %s", e)
        
        return None

