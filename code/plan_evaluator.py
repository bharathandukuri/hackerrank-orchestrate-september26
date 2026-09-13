"""
plan_evaluator.py - Generates and evaluates candidate payment plans for a request.

Candidate types:
1. Full Payment on request_date (if user considers full_payment)
2. Installments (for each option in request_payment_options.csv within max_installment_months)
3. Partial Payment (if allowed and considered, exactly 2 payments: safe_today + remainder)
4. Wait (if full_payment considered and full payment becomes safe on a future date)
5. Not Recommended (fallback)

Also evaluates candidate spending changes (stop and reduce_to) for non-protected, flexible categories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from data_loader import DataLoader, PaymentOption, Request
from evidence_extractor import EvidenceExtractor
from financial_state import FinancialStateBuilder, UserFinancialState, FlexibleExpense
from cashflow_simulator import CashflowSimulator, SpendingChange, SimulationResult


@dataclass(slots=True)
class CandidatePlan:
    method: (
        str  # full_payment | installments | partial_payment | wait | not_recommended
    )
    payment_plan_str: str
    schedule: Dict[date, float]
    earliest_date_for_full_payment: Optional[date]
    spending_changes: List[SpendingChange]
    completes_by_deadline: bool
    total_amount: float
    start_date: date
    num_payments: int
    option_id: str
    is_safe: bool = False
    affordability_status: str = "not_affordable"
    amount_safe_to_pay: float = 0.0


def format_payment_plan(schedule: Dict[date, float]) -> str:
    """Format chronological YYYY-MM-DD:amount separated by |."""
    if not schedule:
        return "none"
    sorted_items = sorted(schedule.items(), key=lambda x: x[0])
    parts = []
    for d, amt in sorted_items:
        if amt.is_integer():
            parts.append(f"{d}:{int(amt)}")
        else:
            parts.append(f"{d}:{amt:.2f}")
    return "|".join(parts)


def format_spending_changes(changes: List[SpendingChange]) -> str:
    """Format spending changes as stop:<id>|reduce_to:<id>:<amt> or none."""
    if not changes:
        return "none"
    return "|".join(c.to_string() for c in changes)


class PlanEvaluator:
    """Generates all eligible candidate plans and evaluates their safety."""

    def __init__(
        self,
        loader: DataLoader,
        extractor: EvidenceExtractor,
        builder: FinancialStateBuilder,
        simulator: CashflowSimulator,
    ):
        self.loader = loader
        self.extractor = extractor
        self.builder = builder
        self.sim = simulator

    def evaluate(self, request: Request) -> List[CandidatePlan]:
        user_id = request.user_id
        profile = self.loader.profiles[user_id]
        state = self.builder.build_state(request)

        # Baseline metrics
        safe_today = self.sim.compute_amount_safe_to_pay(
            state, request.requested_amount
        )
        earliest_full_date = self.sim.find_earliest_date_for_full_payment(
            state, request.requested_amount
        )

        user_methods = set(profile.payment_methods_user_will_consider)
        options = self.loader.payment_options_by_request_id.get(request.request_id, [])

        # Collect eligible spending change candidates
        valid_changes: List[SpendingChange] = []
        for flex in state.flexible_expenses:
            cat = flex.category
            if cat in profile.expense_categories_to_protect:
                continue
            if (
                cat in profile.expense_categories_user_is_willing_to_stop
                and flex.flexibility in ("stoppable", "reducible_or_stoppable")
            ):
                valid_changes.append(
                    SpendingChange(action="stop", event_id=flex.event_id)
                )
            if (
                cat in profile.expense_categories_user_is_willing_to_reduce
                and flex.flexibility in ("reducible", "reducible_or_stoppable")
                and flex.minimum_allowed_amount is not None
            ):
                valid_changes.append(
                    SpendingChange(
                        action="reduce_to",
                        event_id=flex.event_id,
                        new_amount=flex.minimum_allowed_amount,
                    )
                )

        # Build change combinations: [] (none), single changes, pairs (referencing distinct events)
        change_subsets: List[List[SpendingChange]] = [[]]
        for c in valid_changes:
            change_subsets.append([c])
        for i in range(len(valid_changes)):
            for j in range(i + 1, len(valid_changes)):
                c1 = valid_changes[i]
                c2 = valid_changes[j]
                if c1.event_id != c2.event_id:
                    change_subsets.append([c1, c2])

        candidate_plans: List[CandidatePlan] = []

        # -------------------------------------------------------------
        # 1. Full Payment
        # -------------------------------------------------------------
        if "full_payment" in user_methods:
            full_opt = next(
                (o for o in options if o.payment_method == "full_payment"), None
            )
            opt_id = full_opt.payment_option_id if full_opt else "full_payment"
            total_amt = (
                full_opt.total_payable_amount if full_opt else request.requested_amount
            )
            sched = {request.request_date: request.requested_amount}

            for changes in change_subsets:
                # If no changes and safe_today < requested_amount, full payment today without changes is NOT safe
                if not changes and safe_today < request.requested_amount - 1e-4:
                    continue

                if self.sim.simulate_plan(state, sched, spending_changes=changes):
                    status = "affordable_now" if not changes else "affordable_with_plan"
                    plan_earliest = (
                        request.request_date if not changes else earliest_full_date
                    )
                    candidate_plans.append(
                        CandidatePlan(
                            method="full_payment",
                            payment_plan_str=format_payment_plan(sched),
                            schedule=sched,
                            earliest_date_for_full_payment=plan_earliest,
                            spending_changes=changes,
                            completes_by_deadline=request.request_date
                            <= request.desired_completion_date,
                            total_amount=total_amt,
                            start_date=request.request_date,
                            num_payments=1,
                            option_id=opt_id,
                            is_safe=True,
                            affordability_status=status,
                            amount_safe_to_pay=safe_today,
                        )
                    )

        # -------------------------------------------------------------
        # 2. Installments
        # -------------------------------------------------------------
        if (
            "installments" in user_methods
            and profile.max_installment_months is not None
        ):
            max_months = profile.max_installment_months
            installment_opts = [
                o
                for o in options
                if o.payment_method == "installments"
                and o.number_of_payments <= max_months
            ]

            for opt in installment_opts:
                sched = {}
                first_d = opt.first_payment_date
                freq = opt.payment_frequency_days or 30
                for k in range(opt.number_of_payments):
                    d = first_d + timedelta(days=k * freq)
                    sched[d] = opt.payment_amount
                last_d = first_d + timedelta(days=(opt.number_of_payments - 1) * freq)

                for changes in change_subsets:
                    # Test simulation with plan
                    # Check safety over active payment period
                    res = self.sim.simulate(
                        state, payment_schedule=sched, spending_changes=changes
                    )
                    # A plan is considered safe if either fully safe across 90 days or no breach occurs during active payments
                    active_breaches = [d for d in res.breach_dates if d <= last_d]
                    if len(active_breaches) == 0:
                        candidate_plans.append(
                            CandidatePlan(
                                method="installments",
                                payment_plan_str=format_payment_plan(sched),
                                schedule=sched,
                                earliest_date_for_full_payment=earliest_full_date,
                                spending_changes=changes,
                                completes_by_deadline=last_d
                                <= request.desired_completion_date,
                                total_amount=opt.total_payable_amount,
                                start_date=first_d,
                                num_payments=opt.number_of_payments,
                                option_id=opt.payment_option_id,
                                is_safe=True,
                                affordability_status="affordable_with_plan",
                                amount_safe_to_pay=safe_today,
                            )
                        )

        # -------------------------------------------------------------
        # 3. Partial Payment
        # -------------------------------------------------------------
        if "partial_payment" in user_methods and request.allows_partial_payment:
            if (
                1e-4 < safe_today < (request.requested_amount - 1e-4)
                and earliest_full_date is not None
                and earliest_full_date > request.request_date
            ):
                remainder = request.requested_amount - safe_today
                sched = {
                    request.request_date: safe_today,
                    earliest_full_date: remainder,
                }
                if earliest_full_date <= request.desired_completion_date:
                    if self.sim.simulate_plan(state, sched):
                        candidate_plans.append(
                            CandidatePlan(
                                method="partial_payment",
                                payment_plan_str=format_payment_plan(sched),
                                schedule=sched,
                                earliest_date_for_full_payment=earliest_full_date,
                                spending_changes=[],
                                completes_by_deadline=True,
                                total_amount=request.requested_amount,
                                start_date=request.request_date,
                                num_payments=2,
                                option_id="partial_payment",
                                is_safe=True,
                                affordability_status="affordable_with_plan",
                                amount_safe_to_pay=safe_today,
                            )
                        )

        # -------------------------------------------------------------
        # 4. Wait
        # -------------------------------------------------------------
        if (
            "full_payment" in user_methods
            and earliest_full_date is not None
            and earliest_full_date > request.request_date
        ):
            sched = {earliest_full_date: request.requested_amount}
            if self.sim.simulate_plan(state, sched):
                candidate_plans.append(
                    CandidatePlan(
                        method="wait",
                        payment_plan_str=format_payment_plan(sched),
                        schedule=sched,
                        earliest_date_for_full_payment=earliest_full_date,
                        spending_changes=[],
                        completes_by_deadline=earliest_full_date
                        <= request.desired_completion_date,
                        total_amount=request.requested_amount,
                        start_date=earliest_full_date,
                        num_payments=1,
                        option_id="wait",
                        is_safe=True,
                        affordability_status="affordable_later",
                        amount_safe_to_pay=safe_today,
                    )
                )

        # -------------------------------------------------------------
        # 5. Not Recommended (Fallback)
        # -------------------------------------------------------------
        fallback = CandidatePlan(
            method="not_recommended",
            payment_plan_str="none",
            schedule={},
            earliest_date_for_full_payment=None,
            spending_changes=[],
            completes_by_deadline=False,
            total_amount=request.requested_amount,
            start_date=request.request_date + timedelta(days=999),
            num_payments=0,
            option_id="none",
            is_safe=True,
            affordability_status="not_affordable",
            amount_safe_to_pay=safe_today,
        )

        candidate_plans.append(fallback)
        return candidate_plans
