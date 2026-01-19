"""
Accounts Fetcher
Fetches accounts and creates AccountID to AccountInfo mapping.

Enhanced to include SystemAccount field for identifying special accounts
like DEBTORS (Accounts Receivable) and CREDITORS (Accounts Payable).
"""

import logging
from typing import Any, Optional, TypedDict
import asyncio
from xero_python.exceptions import ApiException

from app.integrations.xero.exceptions import XeroDataFetchError
from app.integrations.xero.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)


class AccountInfo(TypedDict):
    """Account information structure."""
    type: str  # AccountType: BANK, CURRENT, CURRLIAB, REVENUE, EXPENSE, etc.
    system_account: Optional[str]  # SystemAccount: DEBTORS, CREDITORS, etc. or None


class AccountsFetcher(BaseFetcher):
    """Fetcher for Accounts data."""
    
    @staticmethod
    def _extract_system_account(account: Any) -> Optional[str]:
        """
        Extract SystemAccount field from account object.
        
        SystemAccount identifies special Xero accounts:
        - DEBTORS: Accounts Receivable
        - CREDITORS: Accounts Payable
        - Other system accounts: BANKCURRENCYGAIN, etc.
        
        Returns:
            SystemAccount string or None if not a system account
        """
        system_account = None
        
        # Try lowercase first (Python SDK convention)
        if hasattr(account, "system_account"):
            sys_acc_obj = account.system_account
            if sys_acc_obj is not None:
                if hasattr(sys_acc_obj, "value"):
                    system_account = str(sys_acc_obj.value)
                else:
                    system_account = str(sys_acc_obj)
        # Try PascalCase (API direct response)
        elif hasattr(account, "SystemAccount"):
            sys_acc_obj = account.SystemAccount
            if sys_acc_obj is not None:
                if hasattr(sys_acc_obj, "value"):
                    system_account = str(sys_acc_obj.value)
                else:
                    system_account = str(sys_acc_obj)
        
        return system_account if system_account else None
    
    async def fetch(self) -> dict[str, AccountInfo]:
        """
        Fetch all accounts and create AccountID to AccountInfo mapping.
        
        This mapping includes:
        - type: AccountType (REVENUE, EXPENSE, BANK, CURRENT, CURRLIAB, etc.)
        - system_account: SystemAccount (DEBTORS, CREDITORS, etc.) for special accounts
        
        The system_account field enables reliable identification of:
        - Accounts Receivable (type=CURRENT, system_account=DEBTORS)
        - Accounts Payable (type=CURRLIAB, system_account=CREDITORS)
        
        Returns:
            Dictionary mapping AccountID to AccountInfo
            Example: {"uuid": {"type": "CURRENT", "system_account": "DEBTORS"}}
        """
        try:
            organization_id = self.organization_id
            
            # Rate limit check
            if organization_id:
                await self.rate_limiter.wait_if_needed(organization_id)
            
            # Execute API call with retry logic
            async def _fetch():
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: self.api.get_accounts(xero_tenant_id=self.tenant_id))
            
            response = await self.retry_handler.execute_with_retry(_fetch)
            
            # Record API call for rate limiting
            if organization_id:
                await self.rate_limiter.record_call(organization_id)
            
            # Flush token updates (will be committed by endpoint/FastAPI)
            await self._flush_token_updates()
            
            # Build AccountID -> AccountInfo mapping
            account_type_map: dict[str, AccountInfo] = {}
            revenue_count = 0
            expense_count = 0
            cogs_count = 0
            bank_count = 0
            debtors_count = 0
            creditors_count = 0
            
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
                    
                    # Extract SystemAccount
                    system_account = self._extract_system_account(account)
                    
                    if account_id and account_type:
                        account_type_map[account_id] = {
                            "type": account_type,
                            "system_account": system_account
                        }
                        
                        # Count by type for logging
                        account_type_upper = account_type.upper()
                        if account_type_upper == "REVENUE":
                            revenue_count += 1
                        elif account_type_upper == "EXPENSE":
                            expense_count += 1
                        elif account_type_upper in ("COGS", "DIRECTCOSTS"):
                            cogs_count += 1
                        elif account_type_upper == "BANK":
                            bank_count += 1
                        
                        # Count system accounts
                        if system_account:
                            system_account_upper = system_account.upper()
                            if system_account_upper == "DEBTORS":
                                debtors_count += 1
                            elif system_account_upper == "CREDITORS":
                                creditors_count += 1
            
            logger.info(
                "Fetched %s accounts: %s REVENUE, %s EXPENSE, %s COGS, %s BANK, "
                "%s DEBTORS, %s CREDITORS (total mapped: %s)",
                len(response.accounts) if hasattr(response, "accounts") and response.accounts else 0,
                revenue_count,
                expense_count,
                cogs_count,
                bank_count,
                debtors_count,
                creditors_count,
                len(account_type_map)
            )
            return account_type_map
            
        except ApiException as e:
            logger.error("Xero API Error (Accounts): %s", e)
            raise XeroDataFetchError(f"Failed to fetch Accounts: {e}", status_code=e.status) from e

