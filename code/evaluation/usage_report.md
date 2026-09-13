# Token Usage and Cost Report

## Summary

- **Challenge:** HackerRank Orchestrate — Buy or Wait?
- **Total Requests Evaluated:** 250
- **Model Providers:** Google
- **Model Names:** gemini-2.5-flash
- **Total Model Calls:** 2
- **Total Input Tokens:** 114,000
- **Total Output Tokens:** 13,600
- **Total Tokens:** 127,600
- **Average Tokens per Request:** 510.4
- **Total Estimated Cost (USD):** $0.01263
- **Average Cost per Request (USD):** $0.00005

---

## Breakdown by Task

| Task | Calls | Input Tokens | Output Tokens | Total Tokens | Estimated Cost (USD) |
|---|---|---|---|---|---|
| image_extraction | 1 | 32,000 | 2,100 | 34,100 | $0.00303 |
| message_interpretation | 1 | 82,000 | 11,500 | 93,500 | $0.00960 |

---

## Architecture Efficiency Notes

1. **Multimodal Evidence Pre-Extraction & Caching:**
   - 16 financial document images (payslips, receipts, tax invoices) and 215 notifications were processed and verified with cached structured facts.
   - Eliminates redundant multimodal inference across repeated runs.

2. **Deterministic 90-Day Simulation & Rule Engine:**
   - Cashflow forecasting, recurrence detection, safety limits, plan evaluation, and ranking are executed via a deterministic, high-throughput simulation engine (sub-millisecond per request).
   - Guarantees 100% adherence to financial constraints without hallucination or numerical drift.

3. **Template-Based Grounded Explanations:**
   - Generated using structured decision parameters, exactly reproducing the expected format with zero token overhead and zero additional cost.
