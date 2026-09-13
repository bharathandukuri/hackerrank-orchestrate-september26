"""
data_loader.py - Data ingestion and indexing for Buy or Wait? financial agent.

Loads all dataset CSVs from dataset/ into typed, indexed dataclasses for O(1) lookups.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# =====================================================================
# Helper Parsing Functions
# =====================================================================


def parse_date(val: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD date string."""
    if not val or not val.strip():
        return None
    return datetime.strptime(val.strip(), "%Y-%m-%d").date()


def parse_float(val: Optional[str]) -> Optional[float]:
    """Parse string to float, returning None if empty."""
    if val is None:
        return None
    val = val.strip()
    if not val:
        return None
    return float(val)


def parse_int(val: Optional[str]) -> Optional[int]:
    """Parse string to int, returning None if empty."""
    if val is None:
        return None
    val = val.strip()
    if not val:
        return None
    return int(val)


def parse_bool(val: Optional[str]) -> bool:
    """Parse case-insensitive boolean string."""
    if not val:
        return False
    return val.strip().lower() in ("true", "1", "yes", "t")


def parse_pipe_list(val: Optional[str]) -> list[str]:
    """Parse pipe-separated string into list of non-empty strings."""
    if not val or not val.strip():
        return []
    return [item.strip() for item in val.strip().split("|") if item.strip()]


# =====================================================================
# Data Classes
# =====================================================================


@dataclass(slots=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(slots=True)
class SampleRequest:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str
    # Ground truth output columns
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str
    decision_explanation: str


@dataclass(slots=True)
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: list[str]
    expense_categories_to_protect: list[str]
    expense_categories_user_is_willing_to_reduce: list[str]
    expense_categories_user_is_willing_to_stop: list[str]
    payment_methods_user_will_consider: list[str]
    max_installment_months: Optional[int]


@dataclass(slots=True)
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str  # debit | credit | non_cash
    amount: Optional[float]  # None when blank (needs image extraction)
    currency: str
    event_date: date
    settlement_date: date
    status: str  # settled | pending | scheduled | cancelled | failed | unrealized
    linked_event_id: Optional[str]
    flexibility: str  # fixed | reducible | stoppable | reducible_or_stoppable
    minimum_allowed_amount: Optional[float]


@dataclass(slots=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: float


@dataclass(slots=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str  # full_payment | installments
    payment_amount: float
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int]  # None for full_payment
    financing_fee: float
    total_payable_amount: float


@dataclass(slots=True)
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: str  # ISO timestamp
    source_type: (
        str  # employer | service_provider | financial_service | bank | merchant
    )
    message_text: str


@dataclass(slots=True)
class ImageRecord:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: str
    file_path: Optional[Path] = None


# =====================================================================
# DataLoader Class
# =====================================================================


class DataLoader:
    """Loads and indexes all dataset files from the dataset directory."""

    def __init__(self, dataset_dir: str | Path = "dataset"):
        self.dataset_dir = Path(dataset_dir)
        if not self.dataset_dir.is_dir():
            # Try searching parent or repo root
            candidate = Path(__file__).resolve().parent.parent / "dataset"
            if candidate.is_dir():
                self.dataset_dir = candidate

        # Data stores
        self.requests: list[Request] = []
        self.requests_by_id: dict[str, Request] = {}
        self.requests_by_user_id: dict[str, Request] = {}

        self.sample_requests: list[SampleRequest] = []
        self.sample_requests_by_id: dict[str, SampleRequest] = {}

        self.profiles: dict[str, Profile] = {}

        self.events: list[FinancialEvent] = []
        self.events_by_id: dict[str, FinancialEvent] = {}
        self.events_by_user_id: dict[str, list[FinancialEvent]] = {}

        self.exchange_rates: list[ExchangeRate] = []
        self.exchange_rates_by_key: dict[tuple[date, str, str], float] = {}

        self.payment_options: list[PaymentOption] = []
        self.payment_options_by_request_id: dict[str, list[PaymentOption]] = {}
        self.payment_options_by_id: dict[str, PaymentOption] = {}

        self.messages: list[Message] = []
        self.messages_by_user_id: dict[str, list[Message]] = {}
        self.messages_by_request_id: dict[str, list[Message]] = {}
        self.messages_by_event_id: dict[str, list[Message]] = {}

        self.images: list[ImageRecord] = []
        self.images_by_id: dict[str, ImageRecord] = {}
        self.images_by_event_id: dict[str, ImageRecord] = {}
        self.images_by_user_id: dict[str, list[ImageRecord]] = {}

    def load_all(self) -> "DataLoader":
        """Load and index all CSVs."""
        self.load_requests()
        self.load_sample_requests()
        self.load_profiles()
        self.load_events()
        self.load_exchange_rates()
        self.load_payment_options()
        self.load_messages()
        self.load_images()
        return self

    def load_requests(self) -> list[Request]:
        file_path = self.dataset_dir / "requests.csv"
        requests = []
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                req = Request(
                    request_id=row["request_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_date=parse_date(row["request_date"]),
                    request_type=row["request_type"].strip(),
                    requested_amount=float(row["requested_amount"]),
                    desired_completion_date=parse_date(row["desired_completion_date"]),
                    allows_partial_payment=parse_bool(row["allows_partial_payment"]),
                    request_text=row["request_text"].strip(),
                )
                requests.append(req)
                self.requests_by_id[req.request_id] = req
                self.requests_by_user_id[req.user_id] = req
        self.requests = requests
        return requests

    def load_sample_requests(self) -> list[SampleRequest]:
        file_path = self.dataset_dir / "sample_requests.csv"
        samples = []
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sample = SampleRequest(
                    request_id=row["request_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_date=parse_date(row["request_date"]),
                    request_type=row["request_type"].strip(),
                    requested_amount=float(row["requested_amount"]),
                    desired_completion_date=parse_date(row["desired_completion_date"]),
                    allows_partial_payment=parse_bool(row["allows_partial_payment"]),
                    request_text=row["request_text"].strip(),
                    amount_safe_to_pay=float(row["amount_safe_to_pay"]),
                    affordability_status=row["affordability_status"].strip(),
                    recommended_payment_method=row[
                        "recommended_payment_method"
                    ].strip(),
                    payment_plan=row["payment_plan"].strip(),
                    earliest_date_for_full_payment=parse_date(
                        row["earliest_date_for_full_payment"]
                    ),
                    spending_changes_needed=row["spending_changes_needed"].strip(),
                    decision_explanation=row["decision_explanation"].strip(),
                )
                samples.append(sample)
                self.sample_requests_by_id[sample.request_id] = sample
        self.sample_requests = samples
        return samples

    def load_profiles(self) -> dict[str, Profile]:
        file_path = self.dataset_dir / "financial_profiles.csv"
        profiles = {}
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                profile = Profile(
                    user_id=row["user_id"].strip(),
                    home_currency=row["home_currency"].strip(),
                    current_available_balance=float(row["current_available_balance"]),
                    minimum_balance_to_keep=float(row["minimum_balance_to_keep"]),
                    financial_priorities=parse_pipe_list(row["financial_priorities"]),
                    expense_categories_to_protect=parse_pipe_list(
                        row["expense_categories_to_protect"]
                    ),
                    expense_categories_user_is_willing_to_reduce=parse_pipe_list(
                        row["expense_categories_user_is_willing_to_reduce"]
                    ),
                    expense_categories_user_is_willing_to_stop=parse_pipe_list(
                        row["expense_categories_user_is_willing_to_stop"]
                    ),
                    payment_methods_user_will_consider=parse_pipe_list(
                        row["payment_methods_user_will_consider"]
                    ),
                    max_installment_months=parse_int(row["max_installment_months"]),
                )
                profiles[profile.user_id] = profile
        self.profiles = profiles
        return profiles

    def load_events(self) -> list[FinancialEvent]:
        file_path = self.dataset_dir / "financial_events.csv"
        events = []
        events_by_user: dict[str, list[FinancialEvent]] = {}
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ev = FinancialEvent(
                    event_id=row["event_id"].strip(),
                    user_id=row["user_id"].strip(),
                    event_type=row["event_type"].strip(),
                    description=row["description"].strip(),
                    category=row["category"].strip(),
                    direction=row["direction"].strip(),
                    amount=parse_float(row["amount"]),
                    currency=row["currency"].strip(),
                    event_date=parse_date(row["event_date"]),
                    settlement_date=parse_date(row["settlement_date"]),
                    status=row["status"].strip(),
                    linked_event_id=(
                        row["linked_event_id"].strip()
                        if row["linked_event_id"] and row["linked_event_id"].strip()
                        else None
                    ),
                    flexibility=row["flexibility"].strip(),
                    minimum_allowed_amount=parse_float(row["minimum_allowed_amount"]),
                )
                events.append(ev)
                self.events_by_id[ev.event_id] = ev
                events_by_user.setdefault(ev.user_id, []).append(ev)
        self.events = events
        self.events_by_user_id = events_by_user
        return events

    def load_exchange_rates(self) -> list[ExchangeRate]:
        file_path = self.dataset_dir / "exchange_rates.csv"
        rates = []
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                er = ExchangeRate(
                    rate_date=parse_date(row["rate_date"]),
                    from_currency=row["from_currency"].strip(),
                    to_currency=row["to_currency"].strip(),
                    rate=float(row["rate"]),
                )
                rates.append(er)
                self.exchange_rates_by_key[
                    (er.rate_date, er.from_currency, er.to_currency)
                ] = er.rate
        self.exchange_rates = rates
        return rates

    def load_payment_options(self) -> list[PaymentOption]:
        file_path = self.dataset_dir / "request_payment_options.csv"
        options = []
        options_by_req: dict[str, list[PaymentOption]] = {}
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                opt = PaymentOption(
                    payment_option_id=row["payment_option_id"].strip(),
                    request_id=row["request_id"].strip(),
                    payment_method=row["payment_method"].strip(),
                    payment_amount=float(row["payment_amount"]),
                    number_of_payments=int(row["number_of_payments"]),
                    first_payment_date=parse_date(row["first_payment_date"]),
                    payment_frequency_days=parse_int(row["payment_frequency_days"]),
                    financing_fee=float(row["financing_fee"]),
                    total_payable_amount=float(row["total_payable_amount"]),
                )
                options.append(opt)
                self.payment_options_by_id[opt.payment_option_id] = opt
                options_by_req.setdefault(opt.request_id, []).append(opt)
        self.payment_options = options
        self.payment_options_by_request_id = options_by_req
        return options

    def load_messages(self) -> list[Message]:
        file_path = self.dataset_dir / "messages.csv"
        messages = []
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                req_id = (
                    row["request_id"].strip()
                    if row["request_id"] and row["request_id"].strip()
                    else None
                )
                ev_id = (
                    row["related_event_id"].strip()
                    if row["related_event_id"] and row["related_event_id"].strip()
                    else None
                )
                msg = Message(
                    message_id=row["message_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_id=req_id,
                    related_event_id=ev_id,
                    sent_at=row["sent_at"].strip(),
                    source_type=row["source_type"].strip(),
                    message_text=row["message_text"].strip(),
                )
                messages.append(msg)
                self.messages_by_user_id.setdefault(msg.user_id, []).append(msg)
                if req_id:
                    self.messages_by_request_id.setdefault(req_id, []).append(msg)
                if ev_id:
                    self.messages_by_event_id.setdefault(ev_id, []).append(msg)
        self.messages = messages
        return messages

    def load_images(self) -> list[ImageRecord]:
        file_path = self.dataset_dir / "images.csv"
        images = []
        media_dir = self.dataset_dir / "media" / "images"
        with open(file_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                img_id = row["image_id"].strip()
                req_id = (
                    row["request_id"].strip()
                    if row["request_id"] and row["request_id"].strip()
                    else None
                )
                rel_ev_id = row["related_event_id"].strip()
                img_file = media_dir / f"{img_id}.png"
                img_rec = ImageRecord(
                    image_id=img_id,
                    user_id=row["user_id"].strip(),
                    request_id=req_id,
                    related_event_id=rel_ev_id,
                    file_path=img_file if img_file.exists() else None,
                )
                images.append(img_rec)
                self.images_by_id[img_id] = img_rec
                self.images_by_event_id[rel_ev_id] = img_rec
                self.images_by_user_id.setdefault(img_rec.user_id, []).append(img_rec)
        self.images = images
        return images

    def get_exchange_rate(
        self, settlement_date: date, from_currency: str, to_currency: str
    ) -> float:
        """
        Get exchange rate from from_currency to to_currency on settlement_date.
        Returns 1.0 if currencies match.
        Uses exact dated match first, then closest prior date if necessary.
        """
        if from_currency == to_currency:
            return 1.0

        # Exact match
        key = (settlement_date, from_currency, to_currency)
        if key in self.exchange_rates_by_key:
            return self.exchange_rates_by_key[key]

        # Inverse match
        inv_key = (settlement_date, to_currency, from_currency)
        if inv_key in self.exchange_rates_by_key:
            return 1.0 / self.exchange_rates_by_key[inv_key]

        # Closest available rate date <= settlement_date
        candidate_dates = [
            r.rate_date
            for r in self.exchange_rates
            if r.from_currency == from_currency and r.to_currency == to_currency
        ]
        if candidate_dates:
            prior_dates = [d for d in candidate_dates if d <= settlement_date]
            best_date = max(prior_dates) if prior_dates else min(candidate_dates)
            return self.exchange_rates_by_key[(best_date, from_currency, to_currency)]

        raise ValueError(
            f"No exchange rate found for {from_currency} -> {to_currency} around {settlement_date}"
        )

    def print_summary(self) -> None:
        """Print summary counts of all loaded data."""
        print("=== DataLoader Summary ===")
        print(f"Requests: {len(self.requests)} (indexed: {len(self.requests_by_id)})")
        print(
            f"Sample Requests: {len(self.sample_requests)} (indexed: {len(self.sample_requests_by_id)})"
        )
        print(f"Profiles: {len(self.profiles)}")
        print(
            f"Financial Events: {len(self.events)} (users with events: {len(self.events_by_user_id)})"
        )
        print(
            f"Exchange Rates: {len(self.exchange_rates)} (unique pairs/dates: {len(self.exchange_rates_by_key)})"
        )
        print(
            f"Payment Options: {len(self.payment_options)} (requests with options: {len(self.payment_options_by_request_id)})"
        )
        print(
            f"Messages: {len(self.messages)} (users with messages: {len(self.messages_by_user_id)})"
        )
        print(
            f"Images: {len(self.images)} (events with images: {len(self.images_by_event_id)})"
        )
        print("==========================")


if __name__ == "__main__":
    loader = DataLoader()
    loader.load_all()
    loader.print_summary()
