"""
test_phase4.py - Unit tests verifying Phase 4 (90-Day Cashflow Simulator).
"""

import unittest
from datetime import date, timedelta
from pathlib import Path

from data_loader import DataLoader
from evidence_extractor import EvidenceExtractor
from financial_state import FinancialStateBuilder
from cashflow_simulator import CashflowSimulator, SpendingChange, SimulationResult


class TestCashflowSimulator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader().load_all()
        cls.extractor = EvidenceExtractor()
        cls.builder = FinancialStateBuilder(cls.loader, cls.extractor)
        cls.sim = CashflowSimulator()

    def test_baseline_simulation(self):
        req1 = self.loader.sample_requests_by_id["request_01"]
        state1 = self.builder.build_state(req1)
        res = self.sim.simulate(state1)
        self.assertTrue(res.is_safe)
        self.assertEqual(len(res.daily_balances), 91)
        self.assertGreaterEqual(res.min_balance_reached, state1.minimum_balance_to_keep)

    def test_amount_safe_to_pay_affordable_now(self):
        # request_01: requested 25256.0, safe to pay 25256.0
        req1 = self.loader.sample_requests_by_id["request_01"]
        state1 = self.builder.build_state(req1)
        safe1 = self.sim.compute_amount_safe_to_pay(state1, req1.requested_amount)
        self.assertEqual(safe1, 25256.0)

        # request_09: requested 166.61, safe to pay 166.61
        req9 = self.loader.sample_requests_by_id["request_09"]
        state9 = self.builder.build_state(req9)
        safe9 = self.sim.compute_amount_safe_to_pay(state9, req9.requested_amount)
        self.assertEqual(safe9, 166.61)

        # request_16: requested 122500.0, safe to pay 122500.0
        req16 = self.loader.sample_requests_by_id["request_16"]
        state16 = self.builder.build_state(req16)
        safe16 = self.sim.compute_amount_safe_to_pay(state16, req16.requested_amount)
        self.assertEqual(safe16, 122500.0)

    def test_earliest_date_for_full_payment(self):
        # request_01 earliest is request_date (2024-03-03)
        req1 = self.loader.sample_requests_by_id["request_01"]
        state1 = self.builder.build_state(req1)
        earliest1 = self.sim.find_earliest_date_for_full_payment(
            state1, req1.requested_amount
        )
        self.assertEqual(earliest1, req1.request_date)

        # request_05 is not affordable, earliest date should be None
        req5 = self.loader.sample_requests_by_id["request_05"]
        state5 = self.builder.build_state(req5)
        earliest5 = self.sim.find_earliest_date_for_full_payment(
            state5, req5.requested_amount
        )
        self.assertIsNone(earliest5)

    def test_spending_change_formatting_and_simulation(self):
        sc_stop = SpendingChange(action="stop", event_id="event_476")
        self.assertEqual(sc_stop.to_string(), "stop:event_476")

        sc_reduce = SpendingChange(
            action="reduce_to", event_id="event_1816", new_amount=23.5
        )
        self.assertEqual(sc_reduce.to_string(), "reduce_to:event_1816:23.50")

        sc_reduce_int = SpendingChange(
            action="reduce_to", event_id="event_21", new_amount=100.0
        )
        self.assertEqual(sc_reduce_int.to_string(), "reduce_to:event_21:100")

    def test_simulate_installment_plan(self):
        # Test 3 installment schedule for request_02
        req2 = self.loader.sample_requests_by_id["request_02"]
        state2 = self.builder.build_state(req2)
        # 3 installments of 15952906.67 on 2025-08-08, 2025-09-07, 2025-10-07
        schedule = {
            date(2025, 8, 8): 15952906.67,
            date(2025, 9, 7): 15952906.67,
            date(2025, 10, 7): 15952906.67,
        }
        res = self.sim.simulate(state2, payment_schedule=schedule)
        self.assertTrue(res.is_safe)
        self.assertGreaterEqual(res.min_balance_reached, state2.minimum_balance_to_keep)

    def test_bounds_on_sample_requests(self):
        # Verify 0 <= safe_amt <= requested_amount for all 25 sample requests
        for s in self.loader.sample_requests:
            state = self.builder.build_state(s)
            safe = self.sim.compute_amount_safe_to_pay(state, s.requested_amount)
            self.assertGreaterEqual(safe, 0.0)
            self.assertLessEqual(safe, s.requested_amount)


if __name__ == "__main__":
    unittest.main()
