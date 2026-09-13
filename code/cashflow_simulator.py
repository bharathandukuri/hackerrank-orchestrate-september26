"""
cashflow_simulator.py - 90-day daily cashflow simulator and safety engine.

Provides:
- Daily balance simulation with arbitrary payment schedules and spending changes
- compute_amount_safe_to_pay(): maximum safe payment on request_date
- find_earliest_date_for_full_payment(): first projected date for a safe full payment
- simulate_plan(): verification that a candidate payment plan is safe across 90 days
- SpendingChange dataclass supporting 'stop:<event_id>' and 'reduce_to:<event_id>:<new_amount>'
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from financial_state import UserFinancialState, FlexibleExpense

# =====================================================================
# Data Classes
# =====================================================================


@dataclass(slots=True)
class SpendingChange:
    action: str  # "stop" or "reduce_to"
    event_id: str
    new_amount: Optional[float] = None

    def to_string(self) -> str:
        if self.action == "stop":
            return f"stop:{self.event_id}"
        elif self.action == "reduce_to":
            # Format nicely: if integer amount, format without trailing zeroes
            if self.new_amount is not None:
                if self.new_amount.is_integer():
                    amt_str = str(int(self.new_amount))
                else:
                    amt_str = f"{self.new_amount:.2f}"
            else:
                amt_str = "0"
            return f"reduce_to:{self.event_id}:{amt_str}"
        return ""


@dataclass(slots=True)
class SimulationResult:
    is_safe: bool
    min_balance_reached: float
    min_balance_date: date
    daily_balances: dict[date, float]
    breach_dates: list[date]


# =====================================================================
# Simulator Engine
# =====================================================================


class CashflowSimulator:
    """Simulates daily financial balances across a 90-day horizon."""

    def __init__(self, forecast_days: int = 90):
        self.forecast_days = forecast_days

    def simulate(
        self,
        state: UserFinancialState,
        payment_schedule: Optional[Dict[date, float]] = None,
        spending_changes: Optional[List[SpendingChange]] = None,
    ) -> SimulationResult:
        """
        Simulate day-by-day cashflow from request_date to request_date + forecast_days.
        Returns SimulationResult with daily balances, safety flag, and min balance seen.
        """
        req_date = state.request_date
        min_balance = state.minimum_balance_to_keep
        schedule = payment_schedule or {}

        # Precompute daily adjustments from spending changes
        # Map: date -> amount saved (credit to balance)
        savings_by_date = self._calculate_savings(state, spending_changes)

        current_balance = state.starting_cash
        daily_balances: dict[date, float] = {}
        breach_dates: list[date] = []

        min_bal_seen = current_balance
        min_bal_date = req_date

        for offset in range(self.forecast_days + 1):
            d = req_date + timedelta(days=offset)

            # 1. Apply baseline net flow for day d
            current_balance += state.daily_net_flow.get(d, 0.0)

            # 2. Apply savings from spending changes
            if d in savings_by_date:
                current_balance += savings_by_date[d]

            # 3. Apply payment schedule debit
            if d in schedule:
                current_balance -= schedule[d]

            daily_balances[d] = current_balance

            if current_balance < min_bal_seen:
                min_bal_seen = current_balance
                min_bal_date = d

            # Safety check against minimum balance
            # Use small epsilon (1e-4) to avoid floating point inaccuracies
            if current_balance < min_balance - 1e-4:
                breach_dates.append(d)

        return SimulationResult(
            is_safe=len(breach_dates) == 0,
            min_balance_reached=round(min_bal_seen, 4),
            min_balance_date=min_bal_date,
            daily_balances=daily_balances,
            breach_dates=breach_dates,
        )

    def compute_amount_safe_to_pay(
        self,
        state: UserFinancialState,
        requested_amount: float,
    ) -> float:
        """
        Largest amount the user can safely pay on request_date before optional spending changes,
        while maintaining minimum_balance_to_keep over all 90 days.
        0 <= amount_safe_to_pay <= requested_amount.
        """
        # Baseline simulation with 0 payments and no spending changes
        res = self.simulate(state)

        # If already dipping below min balance without any payment, safe amount is 0
        if not res.is_safe:
            return 0.0

        # Paying X on day 0 reduces balance on day 0 and on all subsequent days by X
        # Therefore, max safe payment is the minimum buffer above min_balance across all 90 days
        min_buffer = min(
            bal - state.minimum_balance_to_keep for bal in res.daily_balances.values()
        )

        safe_amt = max(0.0, min(min_buffer, requested_amount))
        # Round to 2 decimal places conservatively
        safe_amt = round(safe_amt, 2)
        if safe_amt >= round(requested_amount, 2) - 1e-4:
            safe_amt = round(requested_amount, 2)
        return safe_amt

    def find_earliest_date_for_full_payment(
        self,
        state: UserFinancialState,
        requested_amount: float,
    ) -> Optional[date]:
        """
        Earliest date when paying requested_amount in full is safe across the rest of the 90 days.
        Returns request_date if affordable_now.
        Returns None if not safe on any date within the 90-day forecast.
        """
        req_date = state.request_date

        # Check day-by-day
        for offset in range(self.forecast_days + 1):
            cand_date = req_date + timedelta(days=offset)
            # Test paying full requested_amount on cand_date
            res = self.simulate(state, payment_schedule={cand_date: requested_amount})
            if res.is_safe:
                return cand_date

        return None

    def simulate_plan(
        self,
        state: UserFinancialState,
        schedule: Dict[date, float],
        spending_changes: Optional[List[SpendingChange]] = None,
    ) -> bool:
        """Convenience method returning True if plan is safe across 90 days."""
        res = self.simulate(
            state, payment_schedule=schedule, spending_changes=spending_changes
        )
        return res.is_safe

    def _calculate_savings(
        self,
        state: UserFinancialState,
        spending_changes: Optional[List[SpendingChange]],
    ) -> Dict[date, float]:
        """Calculate daily cash savings from spending changes."""
        if not spending_changes:
            return {}

        savings: dict[date, float] = defaultdict(float)

        # Map event_id to FlexibleExpense in state
        flex_map = {f.event_id: f for f in state.flexible_expenses}

        for change in spending_changes:
            flex = flex_map.get(change.event_id)
            if not flex:
                continue

            if change.action == "stop":
                # Save the full recurring amount on each recurring date
                for d in flex.recurring_dates:
                    savings[d] += flex.amount
            elif change.action == "reduce_to" and change.new_amount is not None:
                # Save the difference (amount - new_amount)
                reduction = max(0.0, flex.amount - change.new_amount)
                for d in flex.recurring_dates:
                    savings[d] += reduction

        return savings


if __name__ == "__main__":
    from data_loader import DataLoader
    from evidence_extractor import EvidenceExtractor
    from financial_state import FinancialStateBuilder

    loader = DataLoader().load_all()
    extractor = EvidenceExtractor()
    builder = FinancialStateBuilder(loader, extractor)
    sim = CashflowSimulator()

    # Test on sample_01
    s1 = loader.sample_requests_by_id["request_01"]
    state1 = builder.build_state(s1)
    safe1 = sim.compute_amount_safe_to_pay(state1, s1.requested_amount)
    earliest1 = sim.find_earliest_date_for_full_payment(state1, s1.requested_amount)
    print(f"Sample 01: Target safe={s1.amount_safe_to_pay}, Calc safe={safe1}")
    print(
        f"Sample 01: Target earliest={s1.earliest_date_for_full_payment}, Calc earliest={earliest1}"
    )
