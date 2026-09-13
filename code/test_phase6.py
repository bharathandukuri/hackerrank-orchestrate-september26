"""
test_phase6.py - Unit tests verifying Phase 6 (Output Generation and Formatting).
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from data_loader import DataLoader
from explainer import Explainer, format_amount_str, format_date_str
from plan_evaluator import CandidatePlan
from output_writer import DecisionOutput, write_output_csv, validate_output_csv


class TestOutputGeneration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader().load_all()
        cls.explainer = Explainer(cls.loader.events_by_id)

    def test_format_helpers(self):
        self.assertEqual(format_amount_str(25256.0), "25,256")
        self.assertEqual(format_amount_str(166.61), "166.61")
        self.assertEqual(format_amount_str(996.6), "996.60")

        self.assertEqual(format_date_str(date(2025, 8, 8)), "8 August 2025")
        self.assertEqual(format_date_str(date(2024, 3, 3)), "3 March 2024")

    def test_explainer_affordable_now(self):
        s1 = self.loader.sample_requests_by_id["request_01"]
        p1 = self.loader.profiles[s1.user_id]
        plan = CandidatePlan(
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
        exp = self.explainer.explain(plan, s1, p1)
        self.assertIn("Pay ZAR 25,256 today.", exp)
        self.assertIn("18,000", exp)

    def test_explainer_installments(self):
        s2 = self.loader.sample_requests_by_id["request_02"]
        p2 = self.loader.profiles[s2.user_id]
        plan = CandidatePlan(
            method="installments",
            payment_plan_str="plan_str",
            schedule={
                date(2025, 8, 8): 15952906.67,
                date(2025, 9, 7): 15952906.67,
                date(2025, 10, 7): 15952906.67,
            },
            earliest_date_for_full_payment=date(2025, 9, 15),
            spending_changes=[],
            completes_by_deadline=True,
            total_amount=47858720.0,
            start_date=date(2025, 8, 8),
            num_payments=3,
            option_id="opt_2",
            is_safe=True,
            affordability_status="affordable_with_plan",
        )
        exp = self.explainer.explain(plan, s2, p2)
        self.assertIn("Use 3 installments of IDR 15,952,906.67", exp)
        self.assertIn("8 August 2025", exp)

    def test_write_and_validate_output(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            temp_path = tf.name

        try:
            # Create 2 valid dummy decisions
            decisions = [
                DecisionOutput(
                    request_id="request_26",
                    amount_safe_to_pay=1000.0,
                    affordability_status="affordable_now",
                    recommended_payment_method="full_payment",
                    payment_plan="2025-08-03:1000",
                    earliest_date_for_full_payment=date(2025, 8, 3),
                    spending_changes_needed="none",
                    decision_explanation="Pay EUR 1,000 today.",
                ),
                DecisionOutput(
                    request_id="request_27",
                    amount_safe_to_pay=0.0,
                    affordability_status="not_affordable",
                    recommended_payment_method="not_recommended",
                    payment_plan="none",
                    earliest_date_for_full_payment=None,
                    spending_changes_needed="none",
                    decision_explanation="Do not make this payment.",
                ),
            ]
            write_output_csv(decisions, output_path=temp_path)

            # Validate
            errors = validate_output_csv(temp_path, expected_count=2)
            self.assertEqual(len(errors), 0, f"Validation errors: {errors}")

        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
