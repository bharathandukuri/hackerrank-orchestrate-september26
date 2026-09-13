"""
test_phase2.py - Unit tests verifying Phase 2 (Multimodal Evidence Extraction).
"""

import unittest
from datetime import date
from pathlib import Path

from evidence_extractor import EvidenceExtractor, ImageExtractor, MessageExtractor


class TestEvidenceExtractor(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.extractor = EvidenceExtractor()

    def test_image_facts_completeness(self):
        images = self.extractor.images
        self.assertEqual(len(images.facts_by_event_id), 16)
        self.assertEqual(len(images.facts_by_image_id), 16)

        # Check image_01 (payslip)
        f1 = images.get_fact_for_event("event_253")
        self.assertIsNotNone(f1)
        self.assertEqual(f1.image_id, "image_01")
        self.assertEqual(f1.amount, 4365000.0)
        self.assertEqual(f1.currency, "IDR")

        # Check image_02 (rent receipt)
        f2 = images.get_fact_for_event("event_1442")
        self.assertIsNotNone(f2)
        self.assertEqual(f2.image_id, "image_02")
        self.assertEqual(f2.amount, 100000.0)
        self.assertEqual(f2.currency, "INR")

        # Check image_05 (utility bill)
        f5 = images.get_fact_for_event("event_1786")
        self.assertIsNotNone(f5)
        self.assertEqual(f5.amount, 704.05)

        # Check image_12 (USD taxi fare)
        f12 = images.get_fact_for_event("event_7307")
        self.assertIsNotNone(f12)
        self.assertEqual(f12.amount, 33.50)
        self.assertEqual(f12.currency, "USD")

    def test_image_amount_lookup(self):
        images = self.extractor.images
        self.assertEqual(images.get_amount_for_event("event_253"), 4365000.0)
        self.assertEqual(images.get_amount_for_event("event_10521"), 393.22)
        self.assertIsNone(images.get_amount_for_event("non_existent_event"))

    def test_message_facts_completeness(self):
        msgs = self.extractor.messages
        self.assertEqual(len(msgs.facts), 215)
        self.assertGreater(len(msgs.facts_by_user_id), 100)

    def test_employment_ended_detection(self):
        msgs = self.extractor.messages
        # user_12 message_09 states seasonal contract ended
        self.assertTrue(msgs.is_employment_ended("user_12"))
        # user_01 has no employment ended notice
        self.assertFalse(msgs.is_employment_ended("user_01"))

    def test_salary_adjustments(self):
        msgs = self.extractor.messages
        # user_02 has salary increase to IDR 42750000
        adj2 = msgs.get_salary_adjustments("user_02")
        self.assertTrue(
            any(
                a.adjustment_type == "salary_increase" and a.amount == 42750000.0
                for a in adj2
            )
        )

        # user_08 has temporary salary reduction to EUR 1422.85
        adj8 = msgs.get_salary_adjustments("user_08")
        self.assertTrue(
            any(
                a.adjustment_type == "salary_temporary_reduction"
                and a.amount == 1422.85
                for a in adj8
            )
        )

    def test_rent_increase(self):
        msgs = self.extractor.messages
        # user_16 message_12 has 12% rent increase
        pct = msgs.get_rent_increase_pct("user_16")
        self.assertEqual(pct, 12.0)

    def test_freelance_invoices(self):
        msgs = self.extractor.messages
        # user_26 has freelance invoice approved (message_18) for IDR 30780000
        invs = msgs.get_approved_freelance_invoices("user_26")
        self.assertEqual(len(invs), 1)
        self.assertEqual(invs[0].amount, 30780000.0)
        self.assertEqual(invs[0].date, date(2025, 8, 15))

    def test_unconfirmed_credits_ignored(self):
        msgs = self.extractor.messages
        # user_04 has unconfirmed quarterly bonus (message_03)
        facts4 = msgs.get_facts_for_user("user_04")
        bonus_facts = [
            f for f in facts4 if f.fact_type == "unconfirmed_bonus_commission"
        ]
        self.assertEqual(len(bonus_facts), 1)
        self.assertFalse(bonus_facts[0].affects_cashflow)


if __name__ == "__main__":
    unittest.main()
