"""
Accounts Fetcher
Fetches accounts and creates AccountID to AccountType mapping.
"""

import logging
from typing import Any

from xero_python.exceptions import ApiException

from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)


class AccountsFetcher(BaseFetcher):
    """Fetcher for Accounts data."""
    
    async def fetch(self) -> dict[str, str]:
        """
        Fetch all accounts and create AccountID to AccountType mapping.
        
        This mapping is used to identify account types (REVENUE, EXPENSE, COGS)
        regardless of user-defined account names.
        
        Returns:
            Dictionary mapping AccountID to AccountType (e.g., {"uuid": "REVENUE", ...})
        """
        try:
            organization_id = self.organization_id
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            async def _fetch():
                return self.api.get_accounts(xero_tenant_id=self.tenant_id)
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            # Flush token updates (will be committed by endpoint/FastAPI)
            await self._flush_token_updates()
            
            # Build AccountID -> AccountType mapping
            account_type_map = {}
            revenue_count = 0
            expense_count = 0
            cogs_count = 0
            
            if hasattr(response, "accounts") and response.accounts:
                for account in response.accounts:
                    account_id = None
                    account_type = None
                    
                    # Extract AccountID (handle both PascalCase and lowercase)
                    if hasattr(account, "account_id"):
                        account_id = str(account.account_id)
                    elif hasattr(account, "AccountID"):
                        account_id = str(account.AccountID)
                    
                    # Extract AccountType (handle both PascalCase and lowercase)
                    if hasattr(account, "type"):
                        account_type_obj = account.type
                        if hasattr(account_type_obj, "value"):
                            account_type = str(account_type_obj.value)
                        else:
                            account_type = str(account_type_obj)
                    elif hasattr(account, "Type"):
                        account_type_obj = account.Type
                        if hasattr(account_type_obj, "value"):
                            account_type = str(account_type_obj.value)
                        else:
                            account_type = str(account_type_obj)
                    
                    if account_id and account_type:
                        account_type_map[account_id] = account_type
                        # Count by type for logging
                        if account_type.upper() == "REVENUE":
                            revenue_count += 1
                        elif account_type.upper() == "EXPENSE":
                            expense_count += 1
                        elif account_type.upper() == "COGS":
                            cogs_count += 1
            
            logger.info(
                "Fetched %s accounts: %s REVENUE, %s EXPENSE, %s COGS (total mapped: %s)",
                len(response.accounts) if hasattr(response, "accounts") and response.accounts else 0,
                revenue_count,
                expense_count,
                cogs_count,
                len(account_type_map)
            )
            return account_type_map
            
        except ApiException as e:
            logger.error("Xero API Error (Accounts): %s", e)
            raise XeroDataFetchError(f"Failed to fetch Accounts: {e}", status_code=e.status) from e

