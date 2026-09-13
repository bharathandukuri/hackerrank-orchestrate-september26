# Buy or Wait? — System Architecture

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          ORCHESTRATOR (main.py)                      │
│                                                                      │
│  ┌────────────┐   ┌───────────────┐   ┌───────────────────────────┐ │
│  │ DataLoader │──►│ Evidence      │──►│ Per-Request Pipeline      │ │
│  │            │   │ Extractor     │   │ (×250 requests)           │ │
│  │ • CSVs     │   │ • 16 images   │   │                           │ │
│  │ • Indexes  │   │ • 215 msgs    │   │ FinancialState            │ │
│  │ • Profiles │   │ • LLM calls   │   │   ↓                      │ │
│  │ • Events   │   │ • Caching     │   │ CashflowSimulator         │ │
│  │ • Rates    │   │               │   │   ↓                      │ │
│  │ • Options  │   │               │   │ PlanEvaluator             │ │
│  └────────────┘   └───────────────┘   │   ↓                      │ │
│                                        │ PlanRanker               │ │
│                                        │   ↓                      │ │
│                                        │ Explainer                │ │
│                                        └───────────┬──────────────┘ │
│                                                     ↓               │
│                                        ┌────────────────────────┐   │
│                                        │ OutputWriter           │   │
│                                        │ • output.csv           │   │
│                                        │ • usage_report.md      │   │
│                                        └────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Module Architecture

### Module 1: DataLoader (`data_loader.py`)

**Responsibility:** Load, parse, and index all CSV files for fast O(1) lookup.

```
                    ┌─────────────────────┐
                    │     data_loader.py   │
                    ├─────────────────────┤
     CSV Files ───► │ load_requests()      │ ──► List[Request]
                    │ load_profiles()      │ ──► Dict[user_id → Profile]
                    │ load_events()        │ ──► Dict[user_id → List[Event]]
                    │ load_exchange_rates() │ ──► Dict[(date,from,to) → rate]
                    │ load_payment_options()│ ──► Dict[request_id → List[Option]]
                    │ load_messages()      │ ──► Dict[user_id → List[Message]]
                    │ load_images()        │ ──► Dict[event_id → image_id]
                    └─────────────────────┘
```

**Data Types:**

```python
@dataclass
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str

@dataclass
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: list[str]
    expense_categories_to_protect: list[str]
    expense_categories_user_is_willing_to_reduce: list[str]
    expense_categories_user_is_willing_to_stop: list[str]
    payment_methods_user_will_consider: list[str]
    max_installment_months: int | None

@dataclass
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str          # debit | credit | non_cash
    amount: float | None    # None when blank (needs image extraction)
    currency: str
    event_date: date
    settlement_date: date
    status: str             # settled | pending | scheduled | cancelled | failed | unrealized
    linked_event_id: str | None
    flexibility: str        # fixed | reducible | stoppable | reducible_or_stoppable
    minimum_allowed_amount: float | None

@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str     # full_payment | installments
    payment_amount: float
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None
    financing_fee: float
    total_payable_amount: float
```

---

### Module 2: EvidenceExtractor (`evidence_extractor.py`)

**Responsibility:** Extract financial facts from images and messages using LLM.

```
┌─────────────────────────────────────────────────────────┐
│                 evidence_extractor.py                     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────┐    ┌──────────────────────────┐    │
│  │ Image Extractor  │    │ Message Interpreter      │    │
│  │                  │    │                          │    │
│  │ 16 PNG files ──► │    │ 215 messages ──►         │    │
│  │ Gemini Vision    │    │ Gemini Flash             │    │
│  │       ↓          │    │       ↓                  │    │
│  │ {event_id: amt}  │    │ List[MessageFact]        │    │
│  │       ↓          │    │       ↓                  │    │
│  │ image_cache.json │    │ message_cache.json       │    │
│  └─────────────────┘    └──────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Message Fact Types:**

```python
@dataclass
class MessageFact:
    message_id: str
    user_id: str
    fact_type: str          # salary_change | event_cancel | event_delay |
                            # refund_pending | bonus_unconfirmed | contract_end |
                            # amount_update | date_change
    affected_event_id: str | None
    new_amount: float | None
    new_date: date | None
    status: str | None      # confirmed | pending | cancelled
    summary: str
```

**LLM Prompt Strategy:**

- Image: "Extract the net pay / total amount from this financial document. Return only the numeric amount and currency."
- Messages: "Extract financial facts from this message. Return structured JSON with fact_type, amount, date, status."
- Batch messages by user to reduce API calls (~50 batched calls instead of 215)

---

### Module 3: FinancialState (`financial_state.py`)

**Responsibility:** Reconstruct a user's complete financial picture as of `request_date`.

```
┌─────────────────────────────────────────────────────────────┐
│                    financial_state.py                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Profile + Events + Messages + Images + FX Rates             │
│        │                                                     │
│        ▼                                                     │
│  ┌─────────────────────────────────┐                        │
│  │ 1. Filter events by user_id     │                        │
│  │ 2. Apply status rules:          │                        │
│  │    • settled → historical       │                        │
│  │    • pending debit → reserve    │                        │
│  │    • pending credit → IGNORE    │                        │
│  │    • cancelled/failed → IGNORE  │                        │
│  │    • unrealized → IGNORE        │                        │
│  │    • scheduled → future commit  │                        │
│  │ 3. Fill blank amounts (images)  │                        │
│  │ 4. Apply message amendments     │                        │
│  │ 5. Convert foreign currencies   │                        │
│  │ 6. Detect recurring patterns    │                        │
│  │ 7. Project recurring 90 days    │                        │
│  └────────────────┬────────────────┘                        │
│                   ▼                                          │
│           UserFinancialState                                 │
│  ┌─────────────────────────────────┐                        │
│  │ balance: float                  │                        │
│  │ min_balance: float              │                        │
│  │ currency: str                   │                        │
│  │ pending_debits: float           │                        │
│  │ future_debits: Dict[date, amt]  │  (scheduled + recurring)│
│  │ future_credits: Dict[date, amt] │  (confirmed salary only)│
│  │ flexible_events: List[Event]    │  (stoppable/reducible)  │
│  └─────────────────────────────────┘                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Recurrence Detection Algorithm:**

```
Input: List of settled events for one user
Output: List of recurring patterns with projected future dates

1. Group events by (category, approximate_description)
2. For each group with ≥2 events:
   a. Sort by event_date
   b. Compute intervals between consecutive dates
   c. If avg_interval ∈ [28, 31] → monthly recurrence
   d. Use last known amount (or avg for variable categories)
   e. Project from last_date + interval until request_date + 90 days
3. For essential categories (rent, salary, utilities, debt_repayment):
   → Always project if pattern exists
4. For flexible categories:
   → Project but mark as stoppable/reducible per event flexibility
```

**Currency Conversion:**

```
1. For event with currency != home_currency:
2. Look up rate in exchange_rates.csv by:
   - rate_date closest to (and ≤) settlement_date
   - from_currency → to_currency matching
3. converted_amount = amount × rate (or amount / rate for reverse)
```

---

### Module 4: CashflowSimulator (`cashflow_simulator.py`)

**Responsibility:** Simulate daily balance over 90 days. Core safety engine.

```
┌──────────────────────────────────────────────────────────────┐
│                  cashflow_simulator.py                        │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Input: UserFinancialState + optional payment_schedule        │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │           90-Day Balance Array                        │    │
│  │                                                       │    │
│  │  Day 0: balance - pending_debits - payment_today      │    │
│  │  Day 1: += credits[day1] - debits[day1]              │    │
│  │  Day 2: += credits[day2] - debits[day2]              │    │
│  │  ...                                                  │    │
│  │  Day 90: += credits[day90] - debits[day90]           │    │
│  │                                                       │    │
│  │  CHECK: min(balance[0..90]) ≥ minimum_balance_to_keep │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                               │
│  Functions:                                                   │
│  ├── compute_amount_safe_to_pay(state) → float               │
│  │   Binary search: largest X where paying X on day 0         │
│  │   keeps min(balance) ≥ min_balance                         │
│  │                                                            │
│  ├── find_earliest_full_payment_date(state, amount) → date    │
│  │   Iterate day by day: first date where paying full amount  │
│  │   keeps all subsequent days ≥ min_balance                  │
│  │                                                            │
│  ├── simulate_with_plan(state, schedule) → bool               │
│  │   Insert plan payments into the cashflow, check safety     │
│  │                                                            │
│  └── simulate_with_changes(state, changes) → new_state        │
│      Remove/reduce specified events from projections          │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

**Binary Search for `amount_safe_to_pay`:**

```
lo = 0, hi = requested_amount
while hi - lo > 0.01:
    mid = (lo + hi) / 2
    if simulate(state, pay mid on request_date) is SAFE:
        lo = mid
    else:
        hi = mid
return floor(lo * 100) / 100   # round down for safety
```

---

### Module 5: PlanEvaluator (`plan_evaluator.py`)

**Responsibility:** Generate and test all candidate payment plans.

```
┌──────────────────────────────────────────────────────────────┐
│                   plan_evaluator.py                           │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  For each request:                                            │
│                                                               │
│  1. FULL PAYMENT ─────────────────────────────────────────── │
│     │ Eligible if: "full_payment" in user prefs               │
│     │ Pay: requested_amount on request_date                   │
│     │ Use: full_payment option from payment_options            │
│     │ Test: simulate → safe?                                  │
│     │                                                         │
│  2. INSTALLMENTS ─────────────────────────────────────────── │
│     │ Eligible if: "installments" in user prefs               │
│     │ For each installment option:                            │
│     │   • Check: num_payments ≤ max_installment_months        │
│     │   • Generate: schedule from first_payment_date          │
│     │     every payment_frequency_days                        │
│     │   • Check: last_payment ≤ desired_completion_date       │
│     │   • Test: simulate → safe?                              │
│     │                                                         │
│  3. PARTIAL PAYMENT ──────────────────────────────────────── │
│     │ Eligible if: "partial_payment" in user prefs            │
│     │              AND allows_partial_payment == true          │
│     │ Plan: pay amount_safe_to_pay on request_date            │
│     │       pay remainder on earliest_full_payment_date       │
│     │ Check: 0 < safe_amt < requested_amt                    │
│     │ Check: earliest_full_date ≤ desired_completion_date     │
│     │ Test: simulate → safe?                                  │
│     │                                                         │
│  4. WAIT ─────────────────────────────────────────────────── │
│     │ Eligible if: "full_payment" in user prefs               │
│     │ Plan: pay requested_amount on earliest_full_date        │
│     │ Check: earliest_full_date exists                        │
│     │ Test: simulate → safe?                                  │
│     │                                                         │
│  5. NOT RECOMMENDED ──────────────────────────────────────── │
│     │ Fallback when no safe plan exists                       │
│                                                               │
│  For plans 1-4 that FAIL, retry with spending changes:        │
│  ┌─────────────────────────────────────────────────┐         │
│  │ Spending Change Candidates:                      │         │
│  │ • stop:<event_id>     (stoppable + user allows)  │         │
│  │ • reduce_to:<event_id>:<min_amt>  (reducible)    │         │
│  │ Max 3 changes. Greedy: biggest savings first.    │         │
│  └─────────────────────────────────────────────────┘         │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

### Module 6: PlanRanker (`plan_ranker.py`)

**Responsibility:** Select the best safe plan using the specified priority order.

```
┌──────────────────────────────────────────────────────────────┐
│                     plan_ranker.py                            │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Input: List of safe CandidatePlans                           │
│                                                               │
│  Sort by (higher priority first):                             │
│  ┌───┬──────────────────────────────────────────────────┐    │
│  │ 1 │ Completes by desired_completion_date (bool, T>F) │    │
│  │ 2 │ No spending changes needed (bool, T>F)           │    │
│  │ 3 │ Minimize total_payable_amount (lower is better)  │    │
│  │ 4 │ Earliest start date (earlier is better)          │    │
│  │ 5 │ Fewer payments (lower is better)                 │    │
│  │ 6 │ Lowest payment_option_id (tie-breaker)           │    │
│  └───┴──────────────────────────────────────────────────┘    │
│                                                               │
│  Output:                                                      │
│  ┌──────────────────────────────────────────┐                │
│  │ DecisionResult:                          │                │
│  │   request_id                             │                │
│  │   amount_safe_to_pay                     │                │
│  │   affordability_status                   │                │
│  │   recommended_payment_method             │                │
│  │   payment_plan                           │                │
│  │   earliest_date_for_full_payment         │                │
│  │   spending_changes_needed                │                │
│  │   decision_explanation                   │                │
│  └──────────────────────────────────────────┘                │
│                                                               │
│  Status Mapping:                                              │
│  ├── full_payment (no changes) → affordable_now              │
│  ├── full_payment (with changes) → affordable_with_plan      │
│  ├── installments → affordable_with_plan                     │
│  ├── partial_payment → affordable_with_plan                  │
│  ├── wait → affordable_later                                 │
│  └── not_recommended → not_affordable                        │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

### Module 7: Explainer (`explainer.py`)

**Responsibility:** Generate concise decision explanations using templates.

```
Templates (derived from 25 sample outputs):

affordable_now + full_payment:
  "Pay {currency} {amount:,} today. This leaves at least
   {currency} {min_balance:,} available over the next 90 days."

affordable_with_plan + installments:
  "Use {n} installments of {currency} {installment_amt:,},
   starting {first_date}. This leaves at least
   {currency} {min_balance:,} available."

affordable_with_plan + full_payment + spending changes:
  "{spending_change_text}, then pay {currency} {amount:,}
   today. This leaves at least {currency} {min_balance:,} available."

affordable_with_plan + partial_payment:
  "Pay {currency} {first_amt:,} today and the remaining
   {currency} {second_amt:,} on {second_date}. This completes
   the full request and keeps the {currency} {min_balance:,}
   minimum protected."

affordable_later + wait:
  "Pay {currency} {amount:,} in full on {date}. Paying
   earlier would take the balance below the
   {currency} {min_balance:,} minimum."
  OR
  "Wait until {date}, then pay {currency} {amount:,} in full.
   Paying sooner would put the {currency} {min_balance:,}
   minimum at risk."

not_affordable + not_recommended:
  "Do not make this payment by {deadline}. None of the
   available options keeps the {currency} {min_balance:,}
   minimum protected."
  OR
  "Do not proceed with the {currency} {amount:,} request.
   Although {currency} {safe_amt:,} is available today,
   the full amount cannot be completed safely within 90 days."
```

---

### Module 8: UsageTracker (`usage_tracker.py`)

**Responsibility:** Track all LLM API calls and generate usage report.

```python
class UsageTracker:
    calls: list[APICallRecord]  # model, input_tokens, output_tokens, cost

    def record_call(model, input_tokens, output_tokens, cost)
    def generate_report(output_path)  # → evaluation/usage_report.md
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  dataset/                                                            │
│  ├── requests.csv ─────────────┐                                    │
│  ├── financial_profiles.csv ───┤                                    │
│  ├── financial_events.csv ─────┤      ┌──────────────┐              │
│  ├── exchange_rates.csv ───────┼─────►│  DataLoader   │              │
│  ├── request_payment_options ──┤      └──────┬───────┘              │
│  ├── messages.csv ─────────────┤             │                      │
│  ├── images.csv ───────────────┤             ▼                      │
│  └── media/images/*.png ───────┘      ┌──────────────┐              │
│                                        │  Evidence    │              │
│                                        │  Extractor   │              │
│                                        │  (LLM calls) │              │
│                                        └──────┬───────┘              │
│                                               │                      │
│            ┌──────────────────────────────────┘                      │
│            │                                                         │
│            ▼          ×250 requests                                  │
│     ┌─────────────┐  ┌────────────────┐  ┌──────────────┐           │
│     │  Financial   │─►│   Cashflow     │─►│    Plan      │           │
│     │  State       │  │   Simulator    │  │  Evaluator   │           │
│     │  Builder     │  │  (90 days)     │  │  + Ranker    │           │
│     └─────────────┘  └────────────────┘  └──────┬───────┘           │
│                                                  │                   │
│                                                  ▼                   │
│                                           ┌──────────────┐          │
│                                           │  Explainer   │          │
│                                           └──────┬───────┘          │
│                                                  │                   │
│                                                  ▼                   │
│                                           ┌──────────────┐          │
│                                           │ output.csv   │          │
│                                           │ usage_report │          │
│                                           └──────────────┘          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
hackerrank-orchestrate-september26/
├── AGENTS.md
├── plan.md                          ← this file's sibling
├── architecture.md                  ← this file
├── problem_statement.md
├── log.txt
├── dataset/
│   ├── requests.csv                 (250 rows — evaluation targets)
│   ├── sample_requests.csv          (25 rows — ground truth reference)
│   ├── financial_profiles.csv       (275 rows)
│   ├── financial_events.csv         (25,342 rows)
│   ├── exchange_rates.csv           (134 rows)
│   ├── request_payment_options.csv  (790 rows)
│   ├── messages.csv                 (215 rows)
│   ├── images.csv                   (16 rows)
│   ├── output.csv                   (250 rows — to fill)
│   └── media/images/                (16 PNGs)
└── code/
    ├── main.py                      # Entry point
    ├── data_loader.py               # CSV ingestion
    ├── evidence_extractor.py        # LLM vision + message parsing
    ├── financial_state.py           # State reconstruction
    ├── cashflow_simulator.py        # 90-day balance simulation
    ├── plan_evaluator.py            # Plan generation + testing
    ├── plan_ranker.py               # Multi-criteria ranking
    ├── explainer.py                 # Template-based explanations
    ├── usage_tracker.py             # Token tracking
    ├── validate_output.py           # Output format checker
    ├── requirements.txt
    ├── .env.example
    ├── README.md
    ├── cache/                       # LLM result caches
    │   ├── image_amounts.json
    │   └── message_facts.json
    └── evaluation/
        └── usage_report.md          # Generated token report
```

---

## Key Design Decisions

1. **Template-based explanations** instead of LLM — saves ~250 API calls, fully deterministic, matches sample style exactly.
2. **Binary search for `amount_safe_to_pay`** — efficient O(log N) instead of brute-force iteration.
3. **Greedy spending changes** — try the most impactful changes first (biggest recurring savings), capped at 3.
4. **LLM caching** — all image and message extractions cached to JSON for reproducibility and re-runs.
5. **Per-request independence** — each request is processed independently, enabling potential parallelization.
6. **Conservative financial stance** — never count pending credits, never invent income, always round down safe amounts.
