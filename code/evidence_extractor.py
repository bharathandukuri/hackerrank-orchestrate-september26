"""
evidence_extractor.py - Multimodal evidence extraction for Buy or Wait? agent.

Extracts financial facts from:
1. Images: 16 receipts/payslips filling blank event amounts in financial_events.csv
2. Messages: 215 notifications conveying salary changes, freelance invoice approvals,
   rent increases, contract terminations, and unconfirmed pending credits.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# =====================================================================
# Data Classes
# =====================================================================


@dataclass(slots=True)
class ImageFact:
    event_id: str
    image_id: str
    amount: float
    currency: str
    description: str
    document_type: str
    extracted_from: str


@dataclass(slots=True)
class MessageFact:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    source_type: str
    fact_type: str
    amount: Optional[float]
    date: Optional[date]
    percentage: Optional[float]
    affects_cashflow: bool
    description: str


@dataclass(slots=True)
class SalaryAdjustment:
    adjustment_type: str  # increase | temporary_reduction | first_salary | resumed | date_change | ended
    amount: Optional[float]
    date: Optional[date]
    description: str


# =====================================================================
# Image Extractor
# =====================================================================


class ImageExtractor:
    """Manages verified amount extraction for the 16 images linked to financial events."""

    def __init__(self, cache_file: str | Path = "code/cache/image_amounts.json"):
        self.cache_file = Path(cache_file)
        self.facts_by_event_id: dict[str, ImageFact] = {}
        self.facts_by_image_id: dict[str, ImageFact] = {}
        self.load_cache()

    def load_cache(self) -> None:
        """Load verified image extraction cache."""
        if not self.cache_file.exists():
            # Fallback path if run from code/ directory
            candidate = Path(__file__).resolve().parent / "cache" / "image_amounts.json"
            if candidate.exists():
                self.cache_file = candidate

        if self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for ev_id, item in data.items():
                    fact = ImageFact(
                        event_id=ev_id,
                        image_id=item["image_id"],
                        amount=float(item["amount"]),
                        currency=item["currency"],
                        description=item["description"],
                        document_type=item["document_type"],
                        extracted_from=item["extracted_from"],
                    )
                    self.facts_by_event_id[ev_id] = fact
                    self.facts_by_image_id[fact.image_id] = fact

    def get_amount_for_event(self, event_id: str) -> Optional[float]:
        """Return extracted amount for event_id, or None if not an image-backed event."""
        fact = self.facts_by_event_id.get(event_id)
        return fact.amount if fact else None

    def get_fact_for_event(self, event_id: str) -> Optional[ImageFact]:
        """Return full ImageFact for event_id."""
        return self.facts_by_event_id.get(event_id)


# =====================================================================
# Message Interpreter
# =====================================================================


class MessageExtractor:
    """Extracts and indexes structured financial facts from messages."""

    def __init__(self, cache_file: str | Path = "code/cache/message_facts.json"):
        self.cache_file = Path(cache_file)
        self.facts: list[MessageFact] = []
        self.facts_by_user_id: dict[str, list[MessageFact]] = {}
        self.facts_by_request_id: dict[str, list[MessageFact]] = {}
        self.facts_by_event_id: dict[str, list[MessageFact]] = {}
        self.load_or_build()

    def load_or_build(self) -> None:
        """Load from cache if available."""
        if not self.cache_file.exists():
            candidate = Path(__file__).resolve().parent / "cache" / "message_facts.json"
            if candidate.exists():
                self.cache_file = candidate

        if self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    d_val = None
                    if item.get("date"):
                        try:
                            d_val = datetime.strptime(item["date"], "%Y-%m-%d").date()
                        except ValueError:
                            pass
                    fact = MessageFact(
                        message_id=item["message_id"],
                        user_id=item["user_id"],
                        request_id=item["request_id"],
                        related_event_id=item["related_event_id"],
                        source_type=item["source_type"],
                        fact_type=item["fact_type"],
                        amount=(
                            float(item["amount"])
                            if item["amount"] is not None
                            else None
                        ),
                        date=d_val,
                        percentage=(
                            float(item["percentage"])
                            if item.get("percentage") is not None
                            else None
                        ),
                        affects_cashflow=bool(item["affects_cashflow"]),
                        description=item["description"],
                    )
                    self.facts.append(fact)
                    self.facts_by_user_id.setdefault(fact.user_id, []).append(fact)
                    if fact.request_id:
                        self.facts_by_request_id.setdefault(fact.request_id, []).append(
                            fact
                        )
                    if fact.related_event_id:
                        self.facts_by_event_id.setdefault(
                            fact.related_event_id, []
                        ).append(fact)

    def get_facts_for_user(self, user_id: str) -> list[MessageFact]:
        return self.facts_by_user_id.get(user_id, [])

    def get_facts_for_request(self, request_id: str) -> list[MessageFact]:
        return self.facts_by_request_id.get(request_id, [])

    def get_facts_for_event(self, event_id: str) -> list[MessageFact]:
        return self.facts_by_event_id.get(event_id, [])

    def is_employment_ended(self, user_id: str) -> bool:
        """Check if user has a message stating employment or seasonal contract ended."""
        for f in self.get_facts_for_user(user_id):
            if f.fact_type == "employment_ended":
                return True
        return False

    def get_salary_adjustments(self, user_id: str) -> list[SalaryAdjustment]:
        """Return all salary adjustments for user."""
        adjustments = []
        for f in self.get_facts_for_user(user_id):
            if f.source_type == "employer" and f.affects_cashflow:
                adjustments.append(
                    SalaryAdjustment(
                        adjustment_type=f.fact_type,
                        amount=f.amount,
                        date=f.date,
                        description=f.description,
                    )
                )
        return adjustments

    def get_approved_freelance_invoices(self, user_id: str) -> list[MessageFact]:
        """Return approved freelance invoices for user."""
        return [
            f
            for f in self.get_facts_for_user(user_id)
            if f.fact_type == "freelance_invoice_approved" and f.amount is not None
        ]

    def get_rent_increase_pct(self, user_id: str) -> Optional[float]:
        """Return rent increase percentage if specified in messages, else None."""
        for f in self.get_facts_for_user(user_id):
            if f.fact_type == "rent_increase" and f.percentage is not None:
                return f.percentage
        return None


# =====================================================================
# Unified Evidence Extractor
# =====================================================================


class EvidenceExtractor:
    """Unified access to both image and message evidence."""

    def __init__(
        self,
        image_cache_file: str | Path = "code/cache/image_amounts.json",
        message_cache_file: str | Path = "code/cache/message_facts.json",
    ):
        self.images = ImageExtractor(image_cache_file)
        self.messages = MessageExtractor(message_cache_file)

    def print_summary(self) -> None:
        print("=== EvidenceExtractor Summary ===")
        print(f"Image Facts: {len(self.images.facts_by_event_id)} / 16")
        print(f"Message Facts: {len(self.messages.facts)} / 215")
        cashflow_affecting = sum(1 for f in self.messages.facts if f.affects_cashflow)
        print(f"Cashflow-affecting messages: {cashflow_affecting}")
        print("=================================")


if __name__ == "__main__":
    extractor = EvidenceExtractor()
    extractor.print_summary()
