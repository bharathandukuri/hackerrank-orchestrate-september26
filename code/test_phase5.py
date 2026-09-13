"""
test_phase5.py - Unit tests verifying Phase 5 (Plan Evaluation & Ranking).
"""

import unittest
from datetime import date, timedelta
from pathlib import Path

from data_loader import DataLoader
from evidence_extractor import EvidenceExtractor
from financial_state import FinancialStateBuilder
from cashflow_simulator import CashflowSimulator
from plan_evaluator import (
    PlanEvaluator,
    CandidatePlan,
    format_payment_plan,
    format_spending_changes,
)
from plan_ranker import PlanRanker, plan_sort_key


class TestPlanEvaluationAndRanking(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader().load_all()
        cls.extractor = EvidenceExtractor()
        cls.builder = FinancialStateBuilder(cls.loader, cls.extractor)
        cls.sim = CashflowSimulator()
        cls.evaluator = PlanEvaluator(cls.loader, cls.extractor, cls.builder, cls.sim)
        cls.ranker = PlanRanker()

    def test_ranking_hierarchy(self):
        # 1. Deadline priority: Plan A completing by deadline beats Plan B not completing by deadline
        p_deadline = CandidatePlan(
            method="full_payment",
            payment_plan_str="2024-03-03:100",
            schedule={date(2024, 3, 3): 100},
            earliest_date_for_full_payment=date(2024, 3, 3),
            spending_changes=[],
            completes_by_deadline=True,
            total_amount=100.0,
            start_date=date(2024, 3, 3),
            num_payments=1,
            option_id="opt_1",
            is_safe=True,
        )
        p_no_deadline = CandidatePlan(
            method="wait",
            payment_plan_str="2024-04-15:100",
            schedule={date(2024, 4, 15): 100},
            earliest_date_for_full_payment=date(2024, 4, 15),
            spending_changes=[],
            completes_by_deadline=False,
            total_amount=100.0,
            start_date=date(2024, 4, 15),
            num_payments=1,
            option_id="opt_2",
            is_safe=True,
        )
        self.assertLess(plan_sort_key(p_deadline), plan_sort_key(p_no_deadline))

        # 2. Spending changes priority: 0 changes beats 1 change
        p_with_change = CandidatePlan(
            method="full_payment",
            payment_plan_str="2024-03-03:100",
            schedule={date(2024, 3, 3): 100},
            earliest_date_for_full_payment=date(2024, 3, 3),
            spending_changes=[None],  # 1 change
            completes_by_deadline=True,
            total_amount=100.0,
            start_date=date(2024, 3, 3),
            num_payments=1,
            option_id="opt_1",
            is_safe=True,
        )
        self.assertLess(plan_sort_key(p_deadline), plan_sort_key(p_with_change))

    def test_sample_requests_method_accuracy(self):
        # 100% match on recommended_payment_method across all 25 sample requests
        loader = self.loader
        evaluator = self.evaluator
        ranker = self.ranker

        method_matches = 0
        for s in loader.sample_requests:
            candidates = evaluator.evaluate(s)
            best = ranker.select_best_plan(candidates)
            if best.method == s.recommended_payment_method:
                method_matches += 1

        self.assertEqual(
            method_matches,
            25,
            "Must achieve 100% match (25/25) on sample recommended payment methods",
        )

    def test_sample_requests_status_accuracy(self):
        # At least 90% match on affordability_status across all 25 sample requests
        loader = self.loader
        evaluator = self.evaluator
        ranker = self.ranker

        status_matches = 0
        for s in loader.sample_requests:
            candidates = evaluator.evaluate(s)
            best = ranker.select_best_plan(candidates)
            if best.affordability_status == s.affordability_status:
                status_matches += 1

        self.assertGreaterEqual(
            status_matches, 22, "Must achieve >= 88% status match on samples"
        )

    def test_partial_payment_structure(self):
        # request_19 recommends partial_payment
        req19 = self.loader.sample_requests_by_id["request_19"]
        candidates = self.evaluator.evaluate(req19)
        best = self.ranker.select_best_plan(candidates)

        self.assertEqual(best.method, "partial_payment")
        self.assertEqual(best.affordability_status, "affordable_with_plan")
        self.assertEqual(best.num_payments, 2)
        # Verify payments sum to requested amount
        self.assertAlmostEqual(sum(best.schedule.values()), req19.requested_amount)

    def test_wait_recommendation(self):
        # request_03 recommends wait
        req3 = self.loader.sample_requests_by_id["request_03"]
        candidates = self.evaluator.evaluate(req3)
        best = self.ranker.select_best_plan(candidates)

        self.assertEqual(best.method, "wait")
        self.assertEqual(best.affordability_status, "affordable_later")
        self.assertGreater(best.start_date, req3.request_date)


if __name__ == "__main__":
    unittest.main()
