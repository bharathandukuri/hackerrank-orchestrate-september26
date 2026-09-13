# Buy or Wait? — Autonomous AI Financial Decision Agent

HackerRank Orchestrate (September 2026) Challenge Solution.

---

## 1. Overview

**Buy or Wait?** is an autonomous AI-powered financial decision agent designed to evaluate purchase and payment requests against a user's reconstructed financial reality. For each request, the agent assesses affordability, determines the maximum safe payment on the request date, selects the optimal payment method (full payment, installments, partial payment, wait, or not recommended), constructs a chronological payment schedule, identifies earliest safe dates, proposes permitted spending adjustments, and generates grounded explanations.

The system enforces strict real-world financial constraints:

- 100% preservation of the user's `minimum_balance_to_keep` across a 90-day forward simulation.
- Conservative cashflow modeling: pending debits reserved immediately, unconfirmed credits ignored until settled.
- Multi-currency support using fixed dated exchange rates.
- Multimodal evidence integration: fills missing financial event amounts from payslips/invoices (`images.csv` / PNGs) and parses status updates from notifications (`messages.csv`).
- Priority-driven decision optimization: prefers completing requests by deadline without spending changes, minimizes payment cost, and minimizes number of installments.

---

## 2. Directory Structure

```text
code/
├── main.py                     # Primary pipeline entry point
├── data_loader.py              # Data ingestion and typed indexing dataclasses
├── evidence_extractor.py       # Multimodal evidence extraction (image + message)
├── financial_state.py          # State reconstruction, recurrence detection, cashflows
├── cashflow_simulator.py       # 90-day cashflow simulation and safe amount calculation
├── plan_evaluator.py           # Candidate plan generation (full, installment, partial, wait)
├── plan_ranker.py              # 6-tier hierarchical plan selection
├── explainer.py                # Grounded natural-language explanation generation
├── output_writer.py            # CSV output writer and validation logic
├── validate_output.py          # Standalone CLI validation script
├── usage_tracker.py            # Model calls, token usage, and cost tracking
├── requirements.txt            # Python dependencies
├── README.md                   # System documentation and execution guide
├── cache/
│   ├── image_amounts.json      # Verified amounts extracted from 16 document images
│   └── message_facts.json      # Structured facts extracted from 215 notifications
├── evaluation/
│   └── usage_report.md         # Official token and cost breakdown report
└── test_phase*.py              # Comprehensive unit tests for phases 1-6
```

---

## 3. Quick Start & Execution

### Requirements

- Python 3.10+ (tested on Python 3.12, 3.13, 3.14)
- Standard library only for core simulation; optional dependencies in `requirements.txt`.

### Installation

```bash
pip install -r code/requirements.txt
```

### Running the Full Pipeline

To run evaluation on all 250 requests and generate `dataset/output.csv` and `code/evaluation/usage_report.md`:

```bash
python code/main.py
```

### Options

```bash
# Run benchmark only on the 25 reference sample requests
python code/main.py --evaluate-samples

# Specify custom dataset directory and output paths
python code/main.py --dataset-dir dataset --output-file dataset/output.csv --report-file code/evaluation/usage_report.md
```

### Validating Output Format

```bash
python code/validate_output.py dataset/output.csv 250
```

### Running the Test Suite

```bash
python code/test_phase1.py
python code/test_phase2.py
python code/test_phase3.py
python code/test_phase4.py
python code/test_phase5.py
python code/test_phase6.py
```

---

## 4. Architectural Highlights

1. **Multimodal Evidence Integration:**
   - 16 financial events with blank amounts correspond to 16 receipts, payslips, and invoices in `dataset/media/images/`. These were verified and structured into `code/cache/image_amounts.json`.
   - 215 notifications in English and Indonesian were categorized into salary changes, terminations, rent adjustments, freelance invoices, and untrusted credit alerts in `code/cache/message_facts.json`.

2. **90-Day Cashflow Engine:**
   - Simulates cash balances day-by-day up to 90 days.
   - Accurately tracks recurring salary, subscriptions, rent, and loan repayments with recurrence detection.
   - Computes `amount_safe_to_pay` as the exact maximum amount payable on `request_date` such that projected balances never dip below `minimum_balance_to_keep`.

3. **Multi-Method Plan Evaluation & Ranking:**
   - Evaluates:
     - **Full Payment:** safe now or with up to 3 non-protected flexible spending cuts (`stop` or `reduce_to`).
     - **Installments:** checks provider options against user preferences and `max_installment_months`.
     - **Partial Payment:** 2-payment split (`amount_safe_to_pay` today, remainder on earliest safe date).
     - **Wait:** safe full payment on earliest projected date.
     - **Not Recommended:** safe fallback when no viable plan exists within 90 days.
   - Strictly ranks candidates using the 6-tier preference rule.

4. **Zero-Hallucination & Sub-3-Second Performance:**
   - The entire 250-request evaluation executes deterministically in ~2.2 seconds.
   - Generates grounded, compliant explanations without external LLM latency during evaluation.
