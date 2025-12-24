"""
Xero Integration Package
OAuth 2.0 integration with Xero accounting API using official SDK.
"""

from app.integrations.xero.data_fetcher import XeroDataFetcher, XeroDataFetchError
from app.integrations.xero.oauth import XeroOAuth
from app.integrations.xero.router import router
from app.integrations.xero.sdk_client import XeroSDKClient, XeroSDKClientError, create_xero_sdk_client
from app.integrations.xero.service import XeroService
from app.integrations.xero.state_store import oauth_state_store

__all__ = [
    "router",
    "XeroService",
    "XeroOAuth",
    "XeroSDKClient",
    "XeroSDKClientError",
    "create_xero_sdk_client",
    "XeroDataFetcher",
    "XeroDataFetchError",
    "oauth_state_store",
]

