# System Overview: Financial Insights Calculation Engine

This document provides a technical overview of how the Neura MVP system calculates financial insights from Xero accounting data. It explains the business logic, calculation methods, data flow, and known limitations.

## System Architecture

The Neura MVP system integrates with Xero accounting software via OAuth 2.0 authentication to fetch financial data, performs deterministic calculations on that data, and generates natural language insights using AI. The system consists of three primary components: data ingestion from Xero, calculation engine for financial metrics, and AI transformation layer for insight generation.

The system operates as a multi-tenant SaaS application where each organization's data is isolated. When insights are requested, the system executes a sequence of operations: authenticating with Xero, fetching financial reports and transaction data, performing calculations, and generating insights that are stored in the database for later retrieval and engagement tracking.

## Data Flow Architecture

The system follows a sequential pipeline when processing insight requests. Authentication is handled via OAuth 2.0, where the system stores refresh tokens and access tokens in the database. Access tokens are automatically refreshed when expired, ensuring continuous access without requiring user re-authentication.

Data fetching occurs in two parallel groups to optimize performance. Group 1 fetches independent data sources simultaneously: Balance Sheet reports for the current date and prior date (typically 30 days earlier), Profit & Loss report for the specified analysis period, and the chart of accounts. Group 2 fetches dependent data after Group 1 completes: Trial Balance report (which requires account mapping), Accounts Receivable invoices, and Accounts Payable invoices.

All fetched data is cached in the database with a configurable TTL (default 15 minutes) to reduce API calls to Xero and improve response times for repeated requests within the cache window. Cache keys are based on organization ID, report type, and date range to ensure data isolation and accuracy.

The calculation phase extracts specific values from the fetched reports using deterministic parsing methods. Cash position is extracted from Balance Sheet reports by locating the "Total Cash and Cash Equivalents" summary row. Revenue, cost of sales, and expenses are extracted from Trial Balance data using account type classification, with fallback to P&L report structure parsing when Trial Balance is unavailable.

Calculated metrics are then passed to the AI service along with a summarized version of the raw data. The AI service uses OpenAI's API with structured JSON schema output to generate insights. Generated insights are stored in the database with engagement tracking fields (is_acknowledged, is_marked_done) to support user workflow management.

## Cash Runway Calculation Logic

Cash runway represents the number of months an organization can operate at its current burn rate before depleting available cash. This metric is calculated by dividing current cash position by monthly burn rate.

The system extracts cash position from the Balance Sheet report by locating the "Total Cash and Cash Equivalents" summary row in the first data column. This value represents the aggregate cash balance across all bank accounts and cash equivalent accounts as of the report date.

Burn rate calculation faces limitation due to Xero API constraints. The system requires monthly cash received and cash spent values, but Xero's Executive Summary and Cash Flow Statement reports lack a standardized structure that can be reliably parsed across different organizations. Account names, report layouts, and categorization methods vary between organizations, making deterministic extraction impossible without keyword matching, which is unreliable and breaks with custom labels.

As a result, the system uses an approximation method when direct cash flow data is unavailable. The approximation compares cash position at the current date with cash position from 30 days prior. If cash increased by $10,000, the system assumes cash_received = $10,000 and cash_spent = $0. If cash decreased by $5,000, it assumes cash_received = $0 and cash_spent = $5,000. This method is inaccurate because it cannot distinguish between scenarios where, for example, $50,000 was received and $40,000 was spent (net +$10,000) versus $10,000 received and $0 spent. Calculations using this approximation are marked with "Medium" confidence level.

A more accurate method is available when Trial Balance data is present. Trial Balance reports organize accounts by AccountType, providing deterministic extraction of revenue, cost of sales, and expenses. When available, the system calculates net profit or loss from Trial Balance (revenue - cost_of_sales - expenses). If the result is negative, that value is used as the monthly burn rate. This method is marked with "High" confidence level.

Monthly burn rate is calculated as cash_spent - cash_received. Runway in months is calculated as cash_position / monthly_burn_rate when burn_rate > 0. If burn_rate ≤ 0 (profitable), runway is reported as None (infinite). Runway in weeks is calculated as runway_months × 4.33.

Runway status is categorized as follows: "healthy" for runway_months ≥ 6, "warning" for 3 ≤ runway_months < 6, "critical" for 0 < runway_months < 3, "negative" for cash_position < 0 or runway_months < 0, and "infinite" for profitable organizations (burn_rate ≤ 0).

## Profitability Calculation Logic

Profitability metrics are calculated from revenue, cost of sales, and expenses. The system prioritizes Trial Balance data because it provides deterministic extraction via AccountType classification, which works consistently across organizations regardless of account naming conventions.

When Trial Balance data is available, the system aggregates all accounts with AccountType "REVENUE" to calculate total revenue, all accounts with AccountType "COSTOFGOODSSOLD" for cost of sales, and all accounts with AccountType "EXPENSE" for total expenses. Gross profit is calculated as revenue - cost_of_sales. Net profit is calculated as gross_profit - expenses, or revenue - expenses if gross_profit is unavailable.

If Trial Balance data is unavailable, the system falls back to parsing the Profit & Loss report structure. This method recursively traverses the P&L report's row structure to locate Section-type rows, then extracts summary values from the first three sections, assuming they represent revenue, cost of sales, and expenses in that order. This assumption may be incorrect for organizations with non-standard P&L structures, which is why Trial Balance is preferred.

Gross margin percentage is calculated as (gross_profit / revenue) × 100 when revenue ≠ 0. The calculation preserves the sign of revenue, so negative revenue results in negative gross margin, which correctly reflects unprofitable operations.

Profit trend analysis compares current month's net cash flow (cash_received - cash_spent) with previous months' net cash flows. If the most recent net flow is greater than the previous month's, trend is "improving." If less, trend is "declining." Otherwise, trend is "stable." Note that this analysis is limited in the MVP because executive_summary_history is always empty, so trend analysis currently defaults to "stable."

Profitability risk level is determined by: "high" if gross_margin < 20% or net_profit < 0, "medium" if 20% ≤ gross_margin < 30%, and "low" otherwise. If profit_trend is "declining" and risk_level would otherwise be "low," risk_level is elevated to "medium."

## Leading Indicators Calculation Logic

Leading indicators identify early warning signals of cash flow stress before they become critical. The system analyzes receivables health, payables pressure, and cash stress signals.

Receivables health metrics are calculated from Accounts Receivable invoice data. The system computes total receivables amount, overdue amount (invoices past due date), overdue count, and average days overdue. Overdue percentage is calculated as (overdue_amount / total) × 100. Overdue count percentage is (overdue_count / total_count) × 100. Timing risk is classified as "high" if avg_days_overdue > 30, "medium" if 15 < avg_days_overdue ≤ 30, and "low" otherwise. Overall receivables risk is "high" if overdue_percentage > 50% or avg_days_overdue > 30, "medium" if overdue_percentage > 25% or avg_days_overdue > 15, and "low" otherwise.

Payables pressure metrics are calculated similarly from Accounts Payable invoice data. The system computes total payables, overdue amount, overdue count, and average days overdue. Risk level is classified as "high" if overdue_percentage > 50% or avg_days_overdue > 30, "medium" if overdue_percentage > 25% or avg_days_overdue > 15, and "low" otherwise.

Cash stress signals are identified through multiple checks: negative cash position (cash_position < 0), declining cash position (current_cash < previous_month_cash), increasing burn rate (current_burn > previous_burn and current_burn > 0), high overdue receivables (receivables_health.risk_level == "high"), slow receivables collection (avg_days_overdue > 30), high overdue payables (payables_pressure.risk_level == "high"), and significant payables pressure (overdue_percentage > 50%). Each detected signal is added to the cash_stress_signals list.

## Upcoming Commitments Calculation Logic

The system analyzes Accounts Payable invoices to identify upcoming payment obligations within a configurable time window (default 30 days). For each invoice, the system parses the due_date field and filters invoices where due_date is between today and today + days_ahead.

The system calculates upcoming_amount as the sum of amount_due for all invoices in the upcoming window, and upcoming_count as the count of such invoices. Large upcoming bills are identified as invoices with amount_due ≥ $1,000, sorted by amount in descending order, limited to the top 5.

Squeeze risk is calculated based on upcoming commitments relative to current cash position. If cash_position < 0, squeeze_risk is "high" if upcoming_amount > 0 or if there are 2+ large bills. For positive cash positions, squeeze_risk is "high" if upcoming_amount > cash_position × 0.5, "medium" if upcoming_amount > cash_position × 0.3 or if there are 3+ large bills, and "low" otherwise.

## AI Insight Generation Process

After calculations complete, the system passes calculated metrics and a raw data summary to the AI service (currently OpenAI). The AI service uses structured output with JSON schema enforcement to ensure consistent response format.

The system prompt instructs the AI to act as a financial advisor with a calm, confident tone, focusing on actionable insights in plain English. The AI receives two data sources: calculated metrics (treated as authoritative) and raw data summary (for context and data quality validation).

The AI is explicitly instructed to use calculated metrics as the source of truth and never recalculate or override numbers. If inconsistencies are detected between calculated metrics and raw data summary, the AI must not modify metrics but instead lower confidence_level and document the issue in data_notes. This preserves calculation accuracy while allowing the AI to flag data quality issues.

The AI generates 1-3 insights ranked by urgency. Each insight includes: insight_type (enum: cash_runway_risk, upcoming_cash_squeeze, receivables_risk, expense_spike, profitability_pressure), title (max 100 chars), severity (high/medium/low), confidence_level (high/medium/low), summary (1-2 sentences), why_it_matters (paragraph), recommended_actions (array of 3-5 strings), supporting_numbers (array of {label, value} objects), and data_notes (string, optional).

The raw data summary is truncated if it exceeds token limits (default 100,000 input tokens). Truncation preserves important information: top 20 receivables invoices by overdue amount, top 20 payables invoices by amount, up to 30 rows per report structure, and up to 50 accounts. This ensures the AI receives relevant context without exceeding API limits.

## Technical Constraints and Limitations

The system has several documented constraints that are transparently communicated through confidence levels and data notes in generated insights.

**Cash Flow Approximation Method**: When direct cash flow data is unavailable, the system uses an approximation method for cash_received and cash_spent. The system compares cash positions between two dates and assumes net change equals cash_received (if positive) or cash_spent (if negative). This cannot distinguish between scenarios with different gross cash flows but the same net change. For example, a $10,000 cash increase could result from $10,000 received and $0 spent, or $50,000 received and $40,000 spent. This method may affect burn rate accuracy, which in turn affects runway calculations. Calculations using this method are marked with "Medium" confidence. The system prefers Trial Balance-based burn rate calculation when available, which uses net profit/loss and is marked with "High" confidence.

**Xero Report Structure Variability**: Xero's Executive Summary and Cash Flow Statement reports lack standardized, deterministic structures. Account names, report layouts, and categorization methods vary between organizations. Attempting to parse these reports using keyword matching would be unreliable and would break with custom labels or non-standard setups. This is why the system uses approximation methods rather than direct extraction.



**Data Completeness Dependency**: The system relies on accurate and complete data from Xero. Missing transactions, incorrect categorizations, or incomplete data may affect calculation accuracy. The system handles missing data gracefully by using safe defaults (0.0 for missing numeric values, empty arrays for missing lists), and calculations reflect the completeness of the source data.

**Profitability Calculation Dependencies**: Profitability calculations require either Trial Balance data (preferred) or a properly structured P&L report. If neither is available or if the P&L report has an unusual structure, profitability metrics may be limited. The system logs warnings when falling back to P&L parsing, and the AI includes data quality notes in generated insights when data limitations are detected.

## MVP Assumptions and Design Decisions

The system is designed as a Minimum Viable Product with specific scope boundaries and assumptions.

**Data Currency Assumptions**: The system assumes Xero accounts are reasonably up to date and that financial data reflects recent business activity. It does not handle edge cases like organizations with months-old stale data or organizations that haven't synced transactions to Xero.

**Accounting Structure Assumptions**: The system assumes standard accounting practices with accounts categorized by standard types (revenue, expense, asset, liability, equity). Highly customized or non-standard chart of accounts structures may result in less accurate calculations, particularly for P&L parsing fallback methods.

**Scope Limitations**: The system focuses exclusively on cash flow health metrics (runway, burn rate, profitability, leading indicators, upcoming commitments). It does not provide comprehensive financial analysis, tax planning, investment advice, or detailed financial statement generation.

**Multi-Tenant Architecture**: The system is organization-scoped with complete data isolation between organizations. This ensures data privacy and security but means the system does not support cross-organization comparisons, benchmarking, or aggregate analytics across multiple organizations.

**Insight Generation Model**: Insights are generated on-demand when requested, ensuring they reflect current financial data. Generated insights are persisted in the database with engagement tracking (is_acknowledged, is_marked_done, timestamps, user references) to support workflow management. The system implements deduplication logic: if an insight with the same type and title was generated within the last 24 hours, it updates the existing insight rather than creating a duplicate.

**Transparency and Confidence Scoring**: The system explicitly communicates data quality and calculation limitations through confidence levels (High/Medium/Low) and data_notes fields. Confidence levels are determined by data completeness, calculation method used (Trial Balance vs. approximation), and data quality indicators. This transparency allows users to assess the reliability of each insight.

## Interpreting Results and Confidence Levels

Insights include confidence levels and data notes that indicate calculation reliability and data quality.

**Confidence Level Interpretation**: "High" confidence indicates complete, reliable data and accurate calculations (typically when Trial Balance data is used). "Medium" confidence indicates approximation methods were used or some data gaps exist (typically when balance sheet comparison approximation is used). "Low" confidence indicates data limitations that may affect calculation accuracy.

**Data Notes Review**: The data_notes field explains data quality issues, missing information, or calculation limitations. Common notes include: "burn_from_trial_balance" (accurate method used), "approx_burn_from_balance_sheet" (approximation method used), "missing_balance_sheet_current" or "missing_balance_sheet_prior" (incomplete data), "cash_extraction_failed" (cash position could not be determined), and "discrepancy detected between metrics and raw data" (AI-detected inconsistency).

**Runway Calculation Accuracy**: Cash runway calculations with "Medium" confidence use the balance sheet comparison approximation method and should be interpreted as estimates rather than precise values. Runway calculations with "High" confidence use Trial Balance-based burn rate calculation and are more accurate.

**Data Currency Considerations**: Insights reflect data available at calculation time. If Xero data is incomplete or stale, insights will reflect that incomplete picture. Users should ensure Xero data is current before requesting insights for accurate results.

**System Scope**: The system provides financial analysis tools and insights but does not replace professional financial advice. Insights should be considered alongside business knowledge and professional consultation when appropriate.

## Business Health Score (BHS) Calculation

The Business Health Score is a comprehensive 0-100 score that evaluates financial health across five categories:

**Category A: Cash & Runway (30 points)**
- A1: Runway Months (15 pts) - Cash available divided by average monthly net outflow
- A2: Cash Volatility (10 pts) - Standard deviation of monthly net cash proxy / average revenue
- A3: Cash Conversion Buffer (5 pts) - AR to Cash ratio

**Category B: Profitability & Efficiency (25 points)**
- B1: Net Profit Margin (10 pts) - Net profit / revenue (rolling 3-month)
- B2: Gross Margin (8 pts) - (Revenue - COGS) / revenue (rolling 3-month)
- B3: Operating Expense Load (7 pts) - Operating expenses / revenue (rolling 3-month)

**Category C: Revenue Quality & Momentum (15 points)**
- C1: Revenue Trend (10 pts) - Compares last 3 months vs prior 3 months revenue
- C2: Revenue Consistency (5 pts) - Coefficient of variation of 6-month revenue

**Category D: Working Capital & Liquidity (20 points)**
- D1: Current Ratio (8 pts) - Current assets / current liabilities
- D2: Quick Ratio (5 pts) - (Cash + AR) / current liabilities
- D3: Receivables Health (4 pts) - AR ageing analysis (>30 days, >60 days)
- D4: Payables Pressure (3 pts) - AP ageing analysis (>60 days)

**Category E: Compliance & Data Confidence (10 points)**
- E3: Data Completeness (10 pts) - Checks for P&L, Balance Sheet, AR, AP, and historical data availability

**Data Source Architecture:**
The Health Score uses **Monthly P&L reports** (not Trial Balance) for revenue, expenses, and COGS metrics. This is because:
1. Monthly P&L reports provide **period activity** (actual revenue/expenses for that month)
2. Trial Balance provides **cumulative YTD balances** (which can be 0 at financial year start)
3. The BHS spec requires "rolling 3-month" calculations, which aligns with monthly P&L data

The extraction uses deterministic AccountType-based summing:
- `REVENUE`, `SALES`, `OTHERINCOME` → revenue
- `COGS`, `DIRECTCOSTS` → cost_of_sales
- `EXPENSE`, `OVERHEADS` → expenses

This approach works consistently across all organizations regardless of account naming conventions.

**Confidence and Grading:**
- Grade A (Strong): 80-100 points
- Grade B (Stable): 65-79 points
- Grade C (At Risk): 45-64 points
- Grade D (Critical): <45 points

Confidence is determined by Category E score: High (≥8), Medium (5-7), Low (≤4).
A confidence cap is applied: High→100, Medium→90, Low→80.

## Planned Enhancements

The system architecture supports extensibility, and several enhancements are planned for future versions.

**Cash Flow Data Extraction**: A planned improvement is implementing reliable extraction of actual cash_received and cash_spent from Xero reports. This requires either: (1) identifying a deterministic parsing method for Executive Summary or Cash Flow Statement reports that works across organizations, (2) exploring Bank Summary or Bank Transactions APIs as alternative data sources, or (3) implementing a data validation and normalization layer that can handle report structure variations. This enhancement would provide more accurate burn rate and runway calculations.

**Historical Trend Analysis**: Implementing monthly snapshot collection and storage would enable multi-month trend analysis. This would require: (1) a data collection mechanism to store monthly financial snapshots, (2) a storage schema for historical data, and (3) trend calculation logic that analyzes changes over time. This would provide context for understanding financial trajectory beyond single-period analysis.

**Multi-Provider AI Support**: The system architecture can be extended to support multiple AI providers (e.g., OpenAI, Gemini) through a provider abstraction layer. This would allow configuration-based provider selection and provide flexibility for cost optimization or performance requirements.

**Data Quality Validation**: Enhanced validation layers could check data completeness before calculations, flag data quality issues proactively, and provide confidence scoring based on data coverage metrics. This would improve transparency about calculation reliability.

**Edge Case Handling**: Improved handling of unusual accounting structures, missing data scenarios, and error recovery would increase system robustness. This includes better fallback mechanisms when primary data sources are unavailable.

All enhancements will be implemented with careful consideration for system simplicity, maintainability, and reliability.
