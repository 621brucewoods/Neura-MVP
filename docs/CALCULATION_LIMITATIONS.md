# Calculation Limitations

## Cash Flow Estimation Issue

**Current Problem:**
The system estimates `cash_received` and `cash_spent` from balance sheet changes, which is not fully accurate.

**Why It may Wrong:**
- If cash increased by $10k, it assumes: received=$10k, spent=$0
- Reality could be: received=$50k, spent=$40k, net=$10k
- This causes incorrect burn rate and runway calculations

**Why We Can't Fix It Yet:**
- Executive Summary report exists but has no deterministic parsing method
- No `standard_layout` parameter or cell attributes with IDs
- Would require keyword matching (unreliable, breaks with custom labels)


**Status:**
- Current: Approximation (documented limitation)
- Future: Need real Xero data samples to verify Executive Summary structure
- Alternative: Explore Bank Summary or Bank Transactions APIs

**Impact:**
Burn rate and runway calculations are approximate, not exact.

