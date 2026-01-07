"""
Error Handling Utilities
Provides sanitized error messages and consistent error responses.
"""

import logging
from enum import Enum
from typing import Optional

from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.oauth import XeroOAuthError
from app.integrations.xero.sdk_client import XeroSDKClientError

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """Error codes for frontend handling."""
    
    # Xero integration errors
    XERO_CONNECTION_FAILED = "xero_connection_failed"
    XERO_TOKEN_INVALID = "xero_token_invalid"
    XERO_DATA_FETCH_FAILED = "xero_data_fetch_failed"
    XERO_AUTH_FAILED = "xero_auth_failed"
    
    # Data and calculation errors
    INSUFFICIENT_DATA = "insufficient_data"
    CALCULATION_FAILED = "calculation_failed"
    INSIGHT_GENERATION_FAILED = "insight_generation_failed"
    
    # General errors
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"
    SERVICE_UNAVAILABLE = "service_unavailable"


# User-friendly error messages
ERROR_MESSAGES = {
    ErrorCode.XERO_CONNECTION_FAILED: "Unable to connect to Xero. Please try reconnecting your account.",
    ErrorCode.XERO_TOKEN_INVALID: "Xero connection has expired. Please reconnect your account.",
    ErrorCode.XERO_DATA_FETCH_FAILED: "Unable to fetch data from Xero. Please try again in a moment.",
    ErrorCode.XERO_AUTH_FAILED: "Xero authentication failed. Please try connecting again.",
    ErrorCode.INSUFFICIENT_DATA: "Insufficient data to generate insights. Please ensure your Xero account has recent transactions.",
    ErrorCode.CALCULATION_FAILED: "Unable to calculate financial metrics. Please try again later.",
    ErrorCode.INSIGHT_GENERATION_FAILED: "Unable to generate insights at this time. Please try again later.",
    ErrorCode.VALIDATION_ERROR: "Invalid request. Please check your input and try again.",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred. Please try again later.",
    ErrorCode.SERVICE_UNAVAILABLE: "Service temporarily unavailable. Please try again in a moment.",
}


def sanitize_error_message(
    exception: Exception,
    error_code: ErrorCode,
    log_details: bool = True,
) -> str:
    """
    Sanitize error message for user-facing responses.
    
    Logs full exception details internally but returns user-friendly message.
    
    Args:
        exception: The exception that occurred
        error_code: Error code for categorization
        log_details: Whether to log full exception details
        
    Returns:
        User-friendly error message
    """
    if log_details:
        logger.error(
            "Error [%s]: %s",
            error_code.value,
            str(exception),
            exc_info=exception,
        )
    
    return ERROR_MESSAGES.get(error_code, ERROR_MESSAGES[ErrorCode.INTERNAL_ERROR])


def get_error_code_for_exception(exception: Exception) -> tuple[ErrorCode, int]:
    """
    Map exception types to error codes and HTTP status codes.
    
    Args:
        exception: The exception that occurred
        
    Returns:
        Tuple of (error_code, http_status_code)
    """
    if isinstance(exception, XeroSDKClientError):
        if "token" in str(exception).lower() or "expired" in str(exception).lower():
            return ErrorCode.XERO_TOKEN_INVALID, status.HTTP_401_UNAUTHORIZED
        return ErrorCode.XERO_CONNECTION_FAILED, status.HTTP_502_BAD_GATEWAY
    
    if isinstance(exception, XeroOAuthError):
        if exception.error_code == "invalid_grant":
            return ErrorCode.XERO_TOKEN_INVALID, status.HTTP_401_UNAUTHORIZED
        return ErrorCode.XERO_AUTH_FAILED, status.HTTP_502_BAD_GATEWAY
    
    if isinstance(exception, XeroDataFetchError):
        return ErrorCode.XERO_DATA_FETCH_FAILED, status.HTTP_502_BAD_GATEWAY
    
    if isinstance(exception, ValueError):
        return ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
    
    if isinstance(exception, KeyError):
        return ErrorCode.INSUFFICIENT_DATA, status.HTTP_400_BAD_REQUEST
    
    # Default to internal error
    return ErrorCode.INTERNAL_ERROR, status.HTTP_500_INTERNAL_SERVER_ERROR


async def global_exception_handler(_request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for FastAPI.
    
    Catches all unhandled exceptions and returns sanitized error responses.
    Excludes HTTPException (intentional responses) and ValidationError (FastAPI validation).
    """
    # Don't handle HTTPException - those are intentional responses
    if isinstance(exc, HTTPException):
        raise exc
    
    # Don't handle RequestValidationError - FastAPI handles this
    if isinstance(exc, RequestValidationError):
        raise exc
    
    error_code, http_status = get_error_code_for_exception(exc)
    message = sanitize_error_message(exc, error_code)
    
    return JSONResponse(
        status_code=http_status,
        content={
            "error_code": error_code.value,
            "message": message,
        },
    )


def create_error_response(
    error_code: ErrorCode,
    message: Optional[str] = None,
    http_status: Optional[int] = None,
) -> HTTPException:
    """
    Create a standardized HTTPException with error code.
    
    Args:
        error_code: Error code enum
        message: Optional custom message (uses default if not provided)
        http_status: Optional HTTP status code (uses default if not provided)
        
    Returns:
        HTTPException with standardized format
    """
    if message is None:
        message = ERROR_MESSAGES.get(error_code, ERROR_MESSAGES[ErrorCode.INTERNAL_ERROR])
    
    if http_status is None:
        # Default status codes by error type
        if error_code in [ErrorCode.XERO_TOKEN_INVALID, ErrorCode.XERO_AUTH_FAILED]:
            http_status = status.HTTP_401_UNAUTHORIZED
        elif error_code in [ErrorCode.XERO_CONNECTION_FAILED, ErrorCode.XERO_DATA_FETCH_FAILED, ErrorCode.SERVICE_UNAVAILABLE]:
            http_status = status.HTTP_502_BAD_GATEWAY
        elif error_code == ErrorCode.VALIDATION_ERROR:
            http_status = status.HTTP_400_BAD_REQUEST
        else:
            http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    
    return HTTPException(
        status_code=http_status,
        detail={
            "error_code": error_code.value,
            "message": message,
        },
    )

