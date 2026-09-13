"""
plan_ranker.py - Ranks safe candidate payment plans using hierarchical challenge rules.

Ranking Priority:
1. Complete the full request by desired_completion_date (True before False)
2. Require no spending changes (0 changes before 1+, fewer changes preferred)
3. Minimize total amount paid (total_payable_amount, lower is better)
4. Start payment earlier (first payment date, earlier is better)
5. Use fewer payments (number_of_payments, lower is better)
6. Lowest payment_option_id as final tie-breaker
"""

from __future__ import annotations

from typing import List, Optional
from plan_evaluator import CandidatePlan


def plan_sort_key(plan: CandidatePlan):
    """
    Tuple for sorting candidate plans in priority order.
    Lower values indicate higher preference.
    """
    # 1. Complete by deadline (True -> 0, False -> 1)
    deadline_score = 0 if plan.completes_by_deadline else 1

    # 2. Number of spending changes (0 is best, then 1, 2, 3)
    changes_score = len(plan.spending_changes)

    # 3. Minimize total amount paid
    total_amount = plan.total_amount

    # 4. Start date (earlier date -> smaller)
    start_date = plan.start_date

    # 5. Fewer payments
    num_payments = plan.num_payments

    # 6. Tie breaker: option_id
    option_id = plan.option_id

    return (
        deadline_score,
        changes_score,
        total_amount,
        start_date,
        num_payments,
        option_id,
    )


class PlanRanker:
    """Ranks and selects the best safe candidate plan."""

    @staticmethod
    def select_best_plan(candidates: List[CandidatePlan]) -> CandidatePlan:
        """
        Filter for safe plans and return the top-ranked plan.
        If no safe plans exist, return the not_recommended fallback.
        """
        # Separate viable safe plans from fallback
        viable = [p for p in candidates if p.is_safe and p.method != "not_recommended"]
        fallback = next((p for p in candidates if p.method == "not_recommended"), None)

        if not viable:
            return fallback or candidates[0]

        # Sort viable plans using the hierarchical ranking key
        viable.sort(key=plan_sort_key)
        return viable[0]


if __name__ == "__main__":
    from data_loader import DataLoader
    from evidence_extractor import EvidenceExtractor
    from financial_state import FinancialStateBuilder
    from cashflow_simulator import CashflowSimulator
    from plan_evaluator import PlanEvaluator

    loader = DataLoader().load_all()
    extractor = EvidenceExtractor()
    builder = FinancialStateBuilder(loader, extractor)
    sim = CashflowSimulator()
    evaluator = PlanEvaluator(loader, extractor, builder, sim)
    ranker = PlanRanker()

    # Test on sample_01
    s1 = loader.sample_requests_by_id["request_01"]
    candidates = evaluator.evaluate(s1)
    best = ranker.select_best_plan(candidates)
    print(
        f"Sample 01 Best: method={best.method}, status={best.affordability_status}, plan={best.payment_plan_str}"
    )
