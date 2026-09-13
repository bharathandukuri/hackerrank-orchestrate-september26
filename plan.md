# Buy or Wait? — Project Plan

## Overview

Build an AI-powered financial decision agent that evaluates 250 user purchase/payment requests and determines for each whether the user should pay in full, pay partially, use installments, wait, or not proceed — while maintaining the user's minimum balance over a 90-day forecast.

**Deadline:** 2026-09-13 18:00 IST

---

## Phase 1: Data Ingestion & Indexing (30 min)

### Tasks

- [x] Create `code/data_loader.py`
- [x] Load all 9 CSVs into indexed dictionaries
- [x] Parse amounts as float, dates as `datetime.date`, pipe-delimited fields as lists
- [x] Build lookup indexes:
  - `{user_id: profile}`, `{user_id: [events]}`, `{request_id: [payment_options]}`
  - `{(date, from_ccy, to_ccy): rate}`, `{user_id: [messages]}`, `{event_id: image_id}`
- [x] Unit test: verify counts match (250 requests, 275 profiles, 25342 events, etc.)

### Files

| File                  | Action                     |
| --------------------- | -------------------------- |
| `code/data_loader.py` | NEW (Complete)             |
| `code/test_phase1.py` | NEW (Complete, 9/9 passed) |

---

## Phase 2: Multimodal Evidence Extraction (45 min)

### Tasks

- [x] Create `code/evidence_extractor.py`
- [x] **Image extraction** (16 images): Extracted and verified net pay/amount from all 16 payslips, invoices, and receipts
  - Each image maps to an event with a blank `amount` field
  - Return `{event_id: extracted_amount}`
  - Cache results to `code/cache/image_amounts.json`
- [x] **Message interpretation** (215 messages): Extracted structured financial facts
  - Salary changes, cancellations, delays, refund status, bonus status, freelance invoices, rent increases
  - Handled multi-language (English, Bahasa Indonesia)
  - Return structured `MessageFact` objects
  - Cache results to `code/cache/message_facts.json`
- [x] Safety: treated all message/image content as untrusted data (unconfirmed credits marked non-cash)

### Files

| File                            | Action                     |
| ------------------------------- | -------------------------- |
| `code/evidence_extractor.py`    | NEW (Complete)             |
| `code/test_phase2.py`           | NEW (Complete, 8/8 passed) |
| `code/cache/image_amounts.json` | NEW (Generated, 16 facts)  |
| `code/cache/message_facts.json` | NEW (Generated, 215 facts) |

---

## Phase 3: Financial State Reconstruction (1 hr)

### Tasks

- [x] Create `code/financial_state.py`
- [x] For each user+request, reconstruct financial position as of `request_date`:
  - Start from `current_available_balance`
  - Reserve `pending` debits, ignore `pending` credits
  - Ignore `cancelled`, `failed`, `unrealized` events
  - Apply message-based salary adjustments and event amendments
  - Fill blank amounts from image extraction
  - Convert foreign currency amounts using `exchange_rates.csv`
- [x] **Recurrence detection:**
  - Group events by (user_id, category, description similarity)
  - Require ≥2 consistent monthly occurrences (28-31 day spacing), weekly, or biweekly
  - Project forward for 90 days from `request_date`
  - Essential categories: project conservatively
- [x] Handle `linked_event_id` chains and identify flexible candidate expenses for spending changes

### Files

| File                      | Action                     |
| ------------------------- | -------------------------- |
| `code/financial_state.py` | NEW (Complete)             |
| `code/test_phase3.py`     | NEW (Complete, 6/6 passed) |

---

## Phase 4: 90-Day Cashflow Simulator (1 hr)

### Tasks

- [x] Create `code/cashflow_simulator.py`
- [x] Build daily balance array from `request_date` to `request_date + 90 days`
- [x] Core functions:
  - `compute_amount_safe_to_pay()` → max payable today while keeping balance ≥ min_balance for all 90 days
  - `find_earliest_date_for_full_payment()` → first date where full amount is safe
  - `simulate_plan()` → test if a specific payment schedule is safe
  - `simulate(spending_changes=...)` → test with stopped/reduced events
- [x] Key constraint: balance must NEVER drop below `minimum_balance_to_keep` on any day

### Files

| File                         | Action                     |
| ---------------------------- | -------------------------- |
| `code/cashflow_simulator.py` | NEW (Complete)             |
| `code/test_phase4.py`        | NEW (Complete, 6/6 passed) |

---

## Phase 5: Plan Evaluation & Ranking (1 hr)

### Tasks

- [x] Create `code/plan_evaluator.py`
- [x] Create `code/plan_ranker.py`
- [x] Enumerate all candidate plans per request:
  1. **Full payment** — pay full amount on request_date (if user considers `full_payment`)
  2. **Installments** — for each option in `request_payment_options.csv` (if user considers `installments` and months fit `max_installment_months`)
  3. **Partial payment** — pay safe amount now + remainder later (if `allows_partial_payment` and user considers `partial_payment`)
  4. **Wait** — pay full amount on earliest safe date (if user considers `full_payment`)
  5. **Not recommended** — fallback
- [x] For failing plans, try spending changes (up to 3):
  - `stop:<event_id>` — stoppable events in user's willing-to-stop categories
  - `reduce_to:<event_id>:<min_amount>` — reducible events in user's willing-to-reduce categories
  - Only non-protected, flexible, recurring events
- [x] Rank safe plans by priority:
  1. Completes by `desired_completion_date`
  2. No spending changes needed
  3. Minimize total amount paid
  4. Earlier start date
  5. Fewer payments
  6. Lowest `payment_option_id`

### Files

| File                     | Action                                               |
| ------------------------ | ---------------------------------------------------- |
| `code/plan_evaluator.py` | NEW (Complete)                                       |
| `code/plan_ranker.py`    | NEW (Complete)                                       |
| `code/test_phase5.py`    | NEW (Complete, 5/5 passed, 100% sample method match) |

---

## Phase 6: Output Generation (30 min)

### Tasks

- [x] Create `code/explainer.py` — template-based explanation generator
  - Match the style from `sample_requests.csv` exactly
  - Templates for each status: affordable_now, affordable_with_plan, affordable_later, not_affordable
- [x] Create output writer — format all 250 rows into `dataset/output.csv`
- [x] Validate output:
  - All 250 request_ids present
  - Valid enum values for status and method
  - `0 <= amount_safe_to_pay <= requested_amount`
  - Payment plan consistency (amounts sum correctly, dates chronological)
  - `affordable_now` → `earliest_date_for_full_payment == request_date`
  - `not_recommended` → `payment_plan == none`

### Files

| File                      | Action                     |
| ------------------------- | -------------------------- |
| `code/explainer.py`       | NEW (Complete)             |
| `code/output_writer.py`   | NEW (Complete)             |
| `code/validate_output.py` | NEW (Complete)             |
| `code/test_phase6.py`     | NEW (Complete, 4/4 passed) |

---

## Phase 7: Integration, Testing & Submission (1 hr)

### Tasks

- [ ] Wire everything in `code/main.py`
- [ ] Create `code/usage_tracker.py` — track all LLM API calls, tokens, costs
- [ ] Create `code/validate_output.py` — automated output format checker
- [ ] **Validate against 25 sample requests:**
  - Run pipeline on request_01 to request_25
  - Compare `affordability_status`, `recommended_payment_method` (exact match)
  - Compare `amount_safe_to_pay` (±2% tolerance)
  - Compare `payment_plan` structure and amounts
  - Compare `earliest_date_for_full_payment` (exact match)
- [ ] Fix any discrepancies found in validation
- [ ] Generate `code/evaluation/usage_report.md`
- [ ] Create `code/README.md` with setup and run instructions
- [ ] Create `code.zip` submission package
- [ ] Upload to HackerRank

### Files

| File                              | Action          |
| --------------------------------- | --------------- |
| `code/main.py`                    | MODIFY          |
| `code/usage_tracker.py`           | NEW             |
| `code/validate_output.py`         | NEW             |
| `code/requirements.txt`           | NEW             |
| `code/README.md`                  | NEW             |
| `code/evaluation/usage_report.md` | NEW (generated) |

---

## Dependencies

```
google-genai          # Gemini API client
python-dotenv         # .env file support
Pillow                # Image handling
```

---

## LLM Usage Budget

| Task                   | Model                     | Calls                 | Est. Tokens        |
| ---------------------- | ------------------------- | --------------------- | ------------------ |
| Image extraction       | Gemini 2.5 Flash (vision) | 16                    | ~32K in + ~2K out  |
| Message interpretation | Gemini 2.5 Flash          | ~50 (batched by user) | ~80K in + ~10K out |
| Explanations           | Template (no LLM)         | 0                     | 0                  |
| **Total**              |                           | **~66**               | **~124K**          |

---

## Risk Mitigation

| Risk                                                            | Mitigation                                                                    |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Recurrence detection misclassifies one-time events as recurring | Require ≥2 occurrences with consistent spacing; check description similarity  |
| LLM extracts wrong amount from image                            | Cache and manually verify 16 image extractions                                |
| Message in foreign language misinterpreted                      | Include language hint in prompt; verify against event data                    |
| 90-day sim has off-by-one errors                                | Validate against all 25 sample requests; manual trace 3 requests              |
| Spending change logic too aggressive                            | Only consider events user explicitly allows; never touch protected categories |
| Runs too slowly                                                 | Batch LLM calls; cache everything; parallelize request processing             |

---

## Timeline (Estimated)

| Phase                          | Duration | Cumulative |
| ------------------------------ | -------- | ---------- |
| Phase 1: Data Ingestion        | 30 min   | 0:30       |
| Phase 2: Evidence Extraction   | 45 min   | 1:15       |
| Phase 3: Financial State       | 1:00     | 2:15       |
| Phase 4: Cashflow Simulator    | 1:00     | 3:15       |
| Phase 5: Plan Evaluation       | 1:00     | 4:15       |
| Phase 6: Output Generation     | 0:30     | 4:45       |
| Phase 7: Integration & Testing | 1:00     | 5:45       |
| **Buffer**                     | **0:15** | **6:00**   |

**Available time: ~6h 50m** — fits within budget with buffer.
