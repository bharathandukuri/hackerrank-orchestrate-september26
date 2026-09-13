"""
test_phase3.py - Unit tests verifying Phase 3 (Financial State Reconstruction).
"""

import unittest
from datetime import date
from pathlib import Path

from data_loader import DataLoader
from evidence_extractor import EvidenceExtractor
from financial_state import FinancialStateBuilder, UserFinancialState


class TestFinancialState(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader().load_all()
        cls.extractor = EvidenceExtractor()
        cls.builder = FinancialStateBuilder(cls.loader, cls.extractor)

    def test_pending_debit_reservation(self):
        # user_01 has pending debit 567.6 (event_102)
        req1 = self.loader.sample_requests_by_id["request_01"]
        state1 = self.builder.build_state(req1)
        self.assertEqual(state1.current_available_balance, 58481.1)
        self.assertEqual(state1.pending_debit_reserve, 567.6)
        self.assertAlmostEqual(state1.starting_cash, 58481.1 - 567.6)
        self.assertEqual(state1.minimum_balance_to_keep, 18000.0)

    def test_job_ended_detection(self):
        # user_05 last salary was "Final employer payroll" -> employment ended
        req5 = self.loader.sample_requests_by_id["request_05"]
        state5 = self.builder.build_state(req5)
        self.assertTrue(state5.is_employment_ended)

        # user_12 message_09 contract ended -> employment ended
        req12 = self.loader.sample_requests_by_id["request_12"]
        state12 = self.builder.build_state(req12)
        self.assertTrue(state12.is_employment_ended)

        # user_01 has ongoing employment
        req1 = self.loader.sample_requests_by_id["request_01"]
        state1 = self.builder.build_state(req1)
        self.assertFalse(state1.is_employment_ended)

    def test_rent_increase_applied(self):
        # user_16 has 12% rent increase in message_12
        req16 = self.loader.sample_requests_by_id["request_16"]
        state16 = self.builder.build_state(req16)
        # Check rent items in daily_items
        rent_items = [
            item
            for items in state16.daily_items.values()
            for item in items
            if item.category == "rent"
            and item.direction == "debit"
            and item.is_recurring
        ]
        self.assertTrue(len(rent_items) > 0)
        # Previous settled rent was 57100; with 12% increase it should be 63952
        for r in rent_items:
            self.assertAlmostEqual(r.amount, 57100.0 * 1.12)

    def test_freelance_invoice_credited(self):
        # user_26 has approved freelance invoice of 30780000 on 2025-08-15
        req26 = self.loader.requests_by_id["request_26"]
        state26 = self.builder.build_state(req26)
        inv_d = date(2025, 8, 15)
        self.assertIn(inv_d, state26.daily_items)
        credits_on_day = [
            item
            for item in state26.daily_items[inv_d]
            if item.direction == "credit" and item.category == "income"
        ]
        self.assertTrue(any(c.amount == 30780000.0 for c in credits_on_day))

    def test_flexible_expenses_identified(self):
        # user_01 has stoppable delivery_membership and reducible dining
        req1 = self.loader.sample_requests_by_id["request_01"]
        state1 = self.builder.build_state(req1)
        flex_cats = set(f.category for f in state1.flexible_expenses)
        self.assertTrue(len(state1.flexible_expenses) > 0)
        self.assertTrue(
            any(
                f.flexibility in ("stoppable", "reducible")
                for f in state1.flexible_expenses
            )
        )

    def test_evaluation_request_state_build(self):
        # Build states for first 5 evaluation requests
        for req in self.loader.requests[:5]:
            state = self.builder.build_state(req)
            self.assertIsInstance(state, UserFinancialState)
            self.assertEqual(state.request_id, req.request_id)
            self.assertEqual(state.user_id, req.user_id)
            self.assertGreater(state.starting_cash, 0)
            self.assertGreater(len(state.daily_net_flow), 0)


if __name__ == "__main__":
    unittest.main()
