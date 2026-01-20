"""
Extracted Data Types
====================

Single source of truth for all extracted financial data structures.
All extractors return data conforming to these types.

Design Principles:
- All values are Optional (None = data not available)
- All numeric values are float (for JSON serialization)
- Clear, descriptive field names
- Immutable structures (TypedDict)
"""

from typing import Optional, TypedDict


class BalanceSheetData(TypedDict):
    """
    Extracted Balance Sheet data.
    
    All values in organization's base currency.
    None means the value could not be extracted.
    
    Handles ALL Xero AccountTypes:
    - BANK → cash
    - CURRENT + DEBTORS → accounts_receivable  
    - CURRENT (other) → other_current_assets
    - INVENTORY → inventory
    - PREPAYMENT → prepayments
    - FIXED → fixed_assets
    - NONCURRENT → non_current_assets
    - DEPRECIATN → accumulated_depreciation (contra-asset)
    - CURRLIAB + CREDITORS → accounts_payable
    - CURRLIAB (other) → other_current_liabilities
    - LIABILITY → long_term_liabilities
    - TERMLIAB → long_term_liabilities
    - EQUITY → equity
    """
    # Cash & Bank
    cash: Optional[float]  # Sum of all BANK accounts
    
    # Current Assets
    accounts_receivable: Optional[float]  # CURRENT + SystemAccount=DEBTORS
    other_current_assets: Optional[float]  # CURRENT without DEBTORS
    inventory: Optional[float]  # INVENTORY accounts
    prepayments: Optional[float]  # PREPAYMENT accounts
    current_assets_total: Optional[float]  # cash + AR + other_current + inventory + prepayments
    
    # Non-Current Assets
    fixed_assets: Optional[float]  # Sum of FIXED accounts
    non_current_assets: Optional[float]  # NONCURRENT accounts
    accumulated_depreciation: Optional[float]  # DEPRECIATN accounts (typically negative)
    total_assets: Optional[float]  # current_assets + fixed + non_current + depreciation
    
    # Current Liabilities
    accounts_payable: Optional[float]  # CURRLIAB + SystemAccount=CREDITORS
    other_current_liabilities: Optional[float]  # CURRLIAB without CREDITORS
    current_liabilities_total: Optional[float]  # Sum of all CURRLIAB
    
    # Non-Current Liabilities
    long_term_liabilities: Optional[float]  # LIABILITY + TERMLIAB accounts
    total_liabilities: Optional[float]  # current_liabilities + long_term
    
    # Equity
    equity: Optional[float]  # EQUITY accounts


class PnLData(TypedDict):
    """
    Extracted Profit & Loss data.
    
    All values in organization's base currency.
    None means the value could not be extracted.
    """
    revenue: Optional[float]  # REVENUE + SALES + OTHERINCOME
    cost_of_sales: Optional[float]  # COGS + DIRECTCOSTS
    expenses: Optional[float]  # EXPENSE + OVERHEADS
    
    # Calculated fields (derived from above)
    gross_profit: Optional[float]  # revenue - cost_of_sales
    net_profit: Optional[float]  # gross_profit - expenses


class AgeingBucket(TypedDict):
    """Single ageing bucket for AR/AP."""
    amount: float
    count: int
    percentage: float  # Percentage of total


class InvoiceAgeingData(TypedDict):
    """
    Extracted invoice ageing data (AR or AP).
    
    Buckets:
    - current: Not yet due
    - days_1_30: 1-30 days overdue
    - days_31_60: 31-60 days overdue  
    - days_61_90: 61-90 days overdue
    - days_90_plus: >90 days overdue
    """
    total: float
    count: int
    overdue_total: float
    overdue_count: int
    
    # Ageing buckets
    current: AgeingBucket
    days_1_30: AgeingBucket
    days_31_60: AgeingBucket
    days_61_90: AgeingBucket
    days_90_plus: AgeingBucket
    
    # Derived metrics
    over_30_days_ratio: float  # (31-60 + 61-90 + 90+) / total
    over_60_days_ratio: float  # (61-90 + 90+) / total


class FinancialData(TypedDict):
    """
    Complete extracted financial data.
    
    This is the single output type from the extraction layer.
    All downstream services consume this structure.
    """
    # Core financial statements
    balance_sheet: BalanceSheetData
    pnl: PnLData
    
    # Receivables & Payables
    receivables: InvoiceAgeingData
    payables: InvoiceAgeingData
    
    # Metadata
    extraction_timestamp: str  # ISO format
    organization_id: Optional[str]
    period_end: Optional[str]  # Balance sheet as-of date (ISO)
    
    # Data quality indicators
    has_balance_sheet: bool
    has_pnl: bool
    has_receivables: bool
    has_payables: bool
