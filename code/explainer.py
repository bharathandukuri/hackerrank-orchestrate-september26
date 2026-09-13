"""
explainer.py - Template-based explanation generator matching the official challenge style.

Generates concise, grounded explanations for all affordability statuses and recommended payment methods:
- affordable_now + full_payment
- affordable_with_plan + installments
- affordable_with_plan + partial_payment
- affordable_with_plan + full_payment (with spending changes)
- affordable_later + wait
- not_affordable + not_recommended
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from data_loader import FinancialEvent, Profile, Request
from plan_evaluator import CandidatePlan
from cashflow_simulator import SpendingChange


def format_amount_str(amt: float) -> str:
    """Format amount with thousands separators and appropriate decimal places."""
    if amt.is_integer():
        return f"{int(amt):,}"
    else:
        return f"{amt:,.2f}"


def format_date_str(d: date) -> str:
    """Format date as 'D Month YYYY' (e.g. '8 August 2025', '15 November 2019')."""
    return f"{d.day} {d.strftime('%B')} {d.year}"


class Explainer:
    """Generates decision explanations matching sample_requests.csv patterns."""

    def __init__(self, events_by_id: Dict[str, FinancialEvent]):
        self.events_by_id = events_by_id

    def explain(
        self,
        plan: CandidatePlan,
        request: Request,
        profile: Profile,
    ) -> str:
        ccy = profile.home_currency
        min_bal_str = format_amount_str(profile.minimum_balance_to_keep)
        req_amt_str = format_amount_str(request.requested_amount)

        # -----------------------------------------------------------------
        # 1. Affordable Now + Full Payment
        # -----------------------------------------------------------------
        if (
            plan.affordability_status == "affordable_now"
            and plan.method == "full_payment"
        ):
            return (
                f"Pay {ccy} {req_amt_str} today. "
                f"This leaves at least {ccy} {min_bal_str} available over the next 90 days."
            )

        # -----------------------------------------------------------------
        # 2. Affordable With Plan + Installments
        # -----------------------------------------------------------------
        if (
            plan.affordability_status == "affordable_with_plan"
            and plan.method == "installments"
        ):
            # Get installment payment amount and start date
            inst_amount = (
                list(plan.schedule.values())[0]
                if plan.schedule
                else (request.requested_amount / plan.num_payments)
            )
            inst_amt_str = format_amount_str(inst_amount)
            start_date_str = format_date_str(plan.start_date)

            return (
                f"Use {plan.num_payments} installments of {ccy} {inst_amt_str}, "
                f"starting {start_date_str}. This leaves at least {ccy} {min_bal_str} available."
            )

        # -----------------------------------------------------------------
        # 3. Affordable With Plan + Partial Payment
        # -----------------------------------------------------------------
        if (
            plan.affordability_status == "affordable_with_plan"
            and plan.method == "partial_payment"
        ):
            sorted_sched = sorted(plan.schedule.items(), key=lambda x: x[0])
            first_amt = (
                sorted_sched[0][1] if len(sorted_sched) > 0 else plan.amount_safe_to_pay
            )
            second_amt = (
                sorted_sched[1][1]
                if len(sorted_sched) > 1
                else (request.requested_amount - first_amt)
            )
            second_date = (
                sorted_sched[1][0]
                if len(sorted_sched) > 1
                else (plan.earliest_date_for_full_payment or request.request_date)
            )

            first_amt_str = format_amount_str(first_amt)
            second_amt_str = format_amount_str(second_amt)
            second_date_str = format_date_str(second_date)

            return (
                f"Pay {ccy} {first_amt_str} today and the remaining {ccy} {second_amt_str} "
                f"on {second_date_str}. This completes the full request and keeps the "
                f"{ccy} {min_bal_str} minimum protected."
            )

        # -----------------------------------------------------------------
        # 4. Affordable With Plan + Full Payment (with spending changes)
        # -----------------------------------------------------------------
        if (
            plan.affordability_status == "affordable_with_plan"
            and plan.method == "full_payment"
        ):
            change_clauses = []
            for sc in plan.spending_changes:
                ev = self.events_by_id.get(sc.event_id)
                desc = ev.description.lower() if ev else "the subscription"
                if not desc.startswith("the "):
                    desc = f"the {desc}"
                if sc.action == "stop":
                    change_clauses.append(f"Stop {desc}")
                elif sc.action == "reduce_to" and sc.new_amount is not None:
                    new_amt_str = format_amount_str(sc.new_amount)
                    change_clauses.append(f"reduce {desc} to {ccy} {new_amt_str}")

            if len(change_clauses) == 1:
                prefix = change_clauses[0]
            elif len(change_clauses) == 2:
                # E.g. "Stop the online backup subscription and reduce the streaming subscription to USD 23.50"
                c2 = change_clauses[1]
                if c2.startswith("reduce "):
                    prefix = f"{change_clauses[0]} and {c2}"
                else:
                    prefix = f"{change_clauses[0]} and {c2.lower()}"
            else:
                prefix = ", ".join(change_clauses[:-1]) + f", and {change_clauses[-1]}"

            return (
                f"{prefix}, then pay {ccy} {req_amt_str} today. "
                f"This leaves at least {ccy} {min_bal_str} available."
            )

        # -----------------------------------------------------------------
        # 5. Affordable Later + Wait
        # -----------------------------------------------------------------
        if plan.affordability_status == "affordable_later" and plan.method == "wait":
            earliest_d = plan.earliest_date_for_full_payment or plan.start_date
            date_str = format_date_str(earliest_d)

            return (
                f"Pay {ccy} {req_amt_str} in full on {date_str}. "
                f"Paying earlier would take the balance below the {ccy} {min_bal_str} minimum."
            )

        # -----------------------------------------------------------------
        # 6. Not Affordable + Not Recommended
        # -----------------------------------------------------------------
        deadline_str = format_date_str(request.desired_completion_date)
        safe_today = plan.amount_safe_to_pay

        # Style A: If some funds are available today but full amount cannot be completed safely
        if safe_today > 0 and safe_today < request.requested_amount:
            safe_str = format_amount_str(safe_today)
            return (
                f"Do not proceed with the {ccy} {req_amt_str} request. "
                f"Although {ccy} {safe_str} is available today, the full amount "
                f"cannot be completed safely within 90 days."
            )

        # Style B: None of the options keeps minimum protected by deadline
        return (
            f"Do not make this payment by {deadline_str}. "
            f"None of the available options keeps the {ccy} {min_bal_str} minimum protected."
        )


if __name__ == "__main__":
    from data_loader import DataLoader

    loader = DataLoader().load_all()
    explainer = Explainer(loader.events_by_id)

    # Test format on sample_01
    s1 = loader.sample_requests_by_id["request_01"]
    p1 = loader.profiles[s1.user_id]
    from plan_evaluator import CandidatePlan

    plan1 = CandidatePlan(
        method="full_payment",
        payment_plan_str="2024-03-03:25256",
        schedule={date(2024, 3, 3): 25256.0},
        earliest_date_for_full_payment=date(2024, 3, 3),
        spending_changes=[],
        completes_by_deadline=True,
        total_amount=25256.0,
        start_date=date(2024, 3, 3),
        num_payments=1,
        option_id="opt_1",
        is_safe=True,
        affordability_status="affordable_now",
    )
    exp = explainer.explain(plan1, s1, p1)
    print("Generated:", exp)
    print("Target:   ", s1.decision_explanation)
