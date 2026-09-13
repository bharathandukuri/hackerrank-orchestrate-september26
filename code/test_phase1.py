"""
test_phase1.py - Unit tests verifying Phase 1 (Data Ingestion & Indexing).
"""

import unittest
from datetime import date
from pathlib import Path

from data_loader import (
    DataLoader,
    parse_bool,
    parse_date,
    parse_float,
    parse_int,
    parse_pipe_list,
)


class TestDataLoader(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader()
        cls.loader.load_all()

    def test_helpers(self):
        self.assertEqual(parse_date("2024-03-03"), date(2024, 3, 3))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date(None))

        self.assertEqual(parse_float("123.45"), 123.45)
        self.assertIsNone(parse_float(""))
        self.assertIsNone(parse_float(None))

        self.assertEqual(parse_int("42"), 42)
        self.assertIsNone(parse_int(""))
        self.assertIsNone(parse_int(None))

        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool("True"))
        self.assertTrue(parse_bool("yes"))
        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool(""))

        self.assertEqual(parse_pipe_list("a|b|c"), ["a", "b", "c"])
        self.assertEqual(parse_pipe_list("a"), ["a"])
        self.assertEqual(parse_pipe_list(""), [])
        self.assertEqual(parse_pipe_list(None), [])

    def test_requests_counts_and_indexing(self):
        loader = self.loader
        self.assertEqual(len(loader.requests), 250)
        self.assertEqual(len(loader.requests_by_id), 250)
        self.assertEqual(len(loader.requests_by_user_id), 250)

        # First request check
        req26 = loader.requests_by_id["request_26"]
        self.assertEqual(req26.user_id, "user_26")
        self.assertEqual(req26.request_date, date(2025, 8, 3))
        self.assertEqual(req26.request_type, "family_transfer")
        self.assertEqual(req26.requested_amount, 15656000.0)
        self.assertEqual(req26.desired_completion_date, date(2025, 10, 7))
        self.assertFalse(req26.allows_partial_payment)

        # Last request check
        req275 = loader.requests_by_id["request_275"]
        self.assertEqual(req275.user_id, "user_275")

    def test_sample_requests(self):
        loader = self.loader
        self.assertEqual(len(loader.sample_requests), 25)
        self.assertEqual(len(loader.sample_requests_by_id), 25)

        s1 = loader.sample_requests_by_id["request_01"]
        self.assertEqual(s1.user_id, "user_01")
        self.assertEqual(s1.affordability_status, "affordable_now")
        self.assertEqual(s1.recommended_payment_method, "full_payment")
        self.assertEqual(s1.amount_safe_to_pay, 25256.0)
        self.assertEqual(s1.earliest_date_for_full_payment, date(2024, 3, 3))

    def test_profiles(self):
        loader = self.loader
        self.assertEqual(len(loader.profiles), 275)

        p1 = loader.profiles["user_01"]
        self.assertEqual(p1.home_currency, "ZAR")
        self.assertEqual(p1.current_available_balance, 58481.1)
        self.assertEqual(p1.minimum_balance_to_keep, 18000.0)
        self.assertIn("education", p1.financial_priorities)
        self.assertIn("rent", p1.expense_categories_to_protect)
        self.assertEqual(p1.payment_methods_user_will_consider, ["full_payment"])
        self.assertIsNone(p1.max_installment_months)

        p2 = loader.profiles["user_02"]
        self.assertEqual(p2.max_installment_months, 7)

    def test_events_and_blank_amounts(self):
        loader = self.loader
        self.assertEqual(len(loader.events), 25342)
        self.assertEqual(len(loader.events_by_id), 25342)
        self.assertEqual(len(loader.events_by_user_id), 275)

        blank_events = [e for e in loader.events if e.amount is None]
        self.assertEqual(len(blank_events), 16)

        # Every blank event must have a matching entry in images
        for be in blank_events:
            self.assertIn(be.event_id, loader.images_by_event_id)

    def test_exchange_rates(self):
        loader = self.loader
        self.assertEqual(len(loader.exchange_rates), 134)

        # Same currency rate
        self.assertEqual(loader.get_exchange_rate(date(2024, 1, 15), "USD", "USD"), 1.0)

        # Direct rate
        rate = loader.get_exchange_rate(date(2024, 1, 15), "USD", "INR")
        self.assertEqual(rate, 83.33)

        # Inverse rate
        inv_rate = loader.get_exchange_rate(date(2024, 1, 15), "INR", "USD")
        self.assertAlmostEqual(inv_rate, 1.0 / 83.33)

    def test_payment_options(self):
        loader = self.loader
        self.assertEqual(len(loader.payment_options), 790)
        self.assertEqual(len(loader.payment_options_by_request_id), 275)

        # Check options for request_01
        opts = loader.payment_options_by_request_id["request_01"]
        self.assertEqual(len(opts), 4)

    def test_messages(self):
        loader = self.loader
        self.assertEqual(len(loader.messages), 215)
        self.assertEqual(len(loader.messages_by_user_id), 215)

    def test_images(self):
        loader = self.loader
        self.assertEqual(len(loader.images), 16)
        self.assertEqual(len(loader.images_by_id), 16)
        self.assertEqual(len(loader.images_by_event_id), 16)

        # All 16 PNG files must exist on disk
        for img in loader.images:
            self.assertIsNotNone(
                img.file_path, f"Image {img.image_id} has no file path"
            )
            self.assertTrue(
                img.file_path.exists(), f"Image file {img.file_path} does not exist"
            )


if __name__ == "__main__":
    unittest.main()
