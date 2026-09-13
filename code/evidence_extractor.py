"""
evidence_extractor.py - Multimodal evidence extraction for Buy or Wait? agent.

Extracts financial facts from:
1. Images: 16 receipts/payslips filling blank event amounts in financial_events.csv,
   with dynamic Gemini VLM extraction fallback for unseen images.
2. Messages: 215 notifications conveying salary changes, freelance invoice approvals,
   rent increases, contract terminations, and unconfirmed pending credits, with
   dynamic multilingual regex and keyword parsing for unseen messages.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_env_file(
    env_path: str | Path = ".env", override: bool = False
) -> Optional[Path]:
    """Load key-value pairs from .env file into os.environ."""
    candidates = [
        Path(env_path),
        Path(".env"),
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            key = k.strip()
                            val = v.strip().strip("'\"")
                            if override or key not in os.environ:
                                os.environ[key] = val
                return p
            except Exception:
                pass
    return None


load_env_file()


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
    """Manages verified amount extraction for document images linked to financial events."""

    def __init__(self, cache_file: str | Path = "code/cache/image_amounts.json"):
        self.cache_file = Path(cache_file)
        self.facts_by_event_id: dict[str, ImageFact] = {}
        self.facts_by_image_id: dict[str, ImageFact] = {}
        self.load_cache()

    def load_cache(self) -> None:
        """Load verified image extraction cache."""
        if not self.cache_file.exists():
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

    def extract_dynamically(
        self,
        image_path: Path,
        event_id: str,
        image_id: str,
        currency: str = "USD",
    ) -> Optional[ImageFact]:
        """Extract amount from an image using Gemini API if an API key is available."""
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key or not image_path.exists():
            return None

        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = (
                "You are an expert financial document parser. "
                "Look at this document image (payslip, receipt, or invoice). "
                "Find the net pay, balance due, or grand total. "
                "Respond ONLY with a JSON object with fields 'amount' (float) and 'currency' (3-letter code)."
            )
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": "image/png",
                                    "data": img_b64,
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {"response_mime_type": "application/json"},
            }

            candidate_models = [
                "gemini-3.6-flash",
                "gemini-3.7-flash",
                "gemini-flash-latest",
                "gemini-2.5-flash",
            ]

            res_data = None
            for model_name in candidate_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        break
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        continue  # Try next model candidate
                    raise

            if not res_data:
                return None

            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            amt = float(parsed["amount"])
            ccy = parsed.get("currency", currency)

            fact = ImageFact(
                event_id=event_id,
                image_id=image_id,
                amount=amt,
                currency=ccy,
                description=f"Dynamic extraction from {image_id}",
                document_type="receipt_or_invoice",
                extracted_from="gemini-vlm",
            )
            self.facts_by_event_id[event_id] = fact
            self.facts_by_image_id[image_id] = fact
            return fact
        except Exception:
            return None

    def get_amount_for_event(
        self,
        event_id: str,
        image_id: Optional[str] = None,
        image_path: Optional[Path] = None,
    ) -> Optional[float]:
        """Return extracted amount for event_id, or None if not an image-backed event."""
        fact = self.facts_by_event_id.get(event_id)
        if fact:
            return fact.amount

        # Attempt dynamic extraction if path is provided
        if image_path and image_id:
            dyn = self.extract_dynamically(image_path, event_id, image_id)
            if dyn:
                return dyn.amount

        return None

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
        self.facts_by_message_id: dict[str, MessageFact] = {}
        self.facts_by_user_id: dict[str, list[MessageFact]] = {}
        self.facts_by_request_id: dict[str, list[MessageFact]] = {}
        self.facts_by_event_id: dict[str, list[MessageFact]] = {}
        self.load_or_build()

    def add_fact(self, fact: MessageFact) -> None:
        """Index a single fact."""
        self.facts.append(fact)
        self.facts_by_message_id[fact.message_id] = fact
        self.facts_by_user_id.setdefault(fact.user_id, []).append(fact)
        if fact.request_id:
            self.facts_by_request_id.setdefault(fact.request_id, []).append(fact)
        if fact.related_event_id:
            self.facts_by_event_id.setdefault(fact.related_event_id, []).append(fact)

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
                    self.add_fact(fact)

    def parse_message_text(
        self,
        message_id: str,
        user_id: str,
        text: str,
        related_event_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> MessageFact:
        """Dynamically extract structured facts from notification text."""
        text_lower = text.lower()
        source_type = "notification"
        fact_type = "info"
        amount = None
        parsed_date = None
        percentage = None
        affects_cashflow = False

        # 1. Extract percentage (e.g. 8%, 10%)
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if pct_match:
            try:
                percentage = float(pct_match.group(1))
            except ValueError:
                pass

        # 2. Extract amount (e.g. USD 1,200 or IDR 4.500.000 or INR 50,000)
        amt_match = re.search(
            r"(?:USD|EUR|INR|GBP|ZAR|IDR|\$|€|₹|£)\s*([\d,.]+)",
            text,
            re.IGNORECASE,
        )
        if amt_match:
            raw_amt = amt_match.group(1).strip(".,")
            # Handle Indonesian dots vs decimals
            if "idr" in text_lower or (
                len(raw_amt.split(".")) > 1 and len(raw_amt.split(".")[-1]) == 3
            ):
                clean_amt = raw_amt.replace(".", "").replace(",", ".")
            else:
                clean_amt = raw_amt.replace(",", "")
            try:
                amount = float(clean_amt)
            except ValueError:
                amount = None

        # 3. Detect date
        date_match = re.search(
            r"(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4})",
            text,
            re.IGNORECASE,
        )
        if date_match:
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    parsed_date = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    pass
        elif re.search(r"\d{4}-\d{2}-\d{2}", text):
            iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            if iso_match:
                try:
                    parsed_date = datetime.strptime(
                        iso_match.group(1), "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass

        # 4. Classify source & fact type
        # A. Employment termination
        if any(
            w in text_lower
            for w in [
                "final payroll",
                "contract ended",
                "contract completion",
                "resignation",
                "employment ended",
                "pemutusan hubungan",
                "kontrak berakhir",
                "gaji terakhir",
            ]
        ):
            source_type = "employer"
            fact_type = "employment_ended"
            affects_cashflow = True
        # B. Salary adjustments
        elif any(w in text_lower for w in ["salary", "gaji", "payroll", "upah"]):
            source_type = "employer"
            if any(w in text_lower for w in ["resumed", "normal", "kembali normal"]):
                fact_type = "salary_resumed"
                affects_cashflow = True
            elif any(
                w in text_lower
                for w in ["first salary", "starting salary", "gaji pertama"]
            ):
                fact_type = "first_salary"
                affects_cashflow = True
            elif any(
                w in text_lower
                for w in ["increase", "raise", "promot", "dinaikkan", "kenaikan"]
            ):
                fact_type = "salary_increase"
                affects_cashflow = True
            elif any(
                w in text_lower
                for w in ["reduction", "cut", "potongan", "dipotong", "pemotongan"]
            ):
                fact_type = "temporary_reduction"
                affects_cashflow = True
            elif any(
                w in text_lower
                for w in ["date change", "moved to", "pembayaran diubah", "jadwal"]
            ):
                fact_type = "salary_date_change"
                affects_cashflow = True
            else:
                fact_type = "salary_info"
                affects_cashflow = False
        # C. Rent increases
        elif any(w in text_lower for w in ["rent", "sewa", "landlord", "pemilik sewa"]):
            source_type = "landlord"
            if (
                any(w in text_lower for w in ["increase", "naik", "kenaikan"])
                or percentage is not None
            ):
                fact_type = "rent_increase"
                affects_cashflow = True
            else:
                fact_type = "rent_info"
        # D. Freelance invoices
        elif any(w in text_lower for w in ["invoice", "tagihan", "freelance", "klien"]):
            source_type = "client"
            if any(
                w in text_lower
                for w in ["approved", "disetujui", "processed", "diproses"]
            ):
                fact_type = "freelance_invoice_approved"
                affects_cashflow = True
            else:
                fact_type = "invoice_info"
        # E. Untrusted credits (strictly non-cash per rules)
        elif any(
            w in text_lower
            for w in [
                "lottery",
                "prize",
                "undian",
                "hadiah",
                "cashback",
                "bonus unconfirmed",
                "menang",
            ]
        ):
            source_type = "lottery"
            fact_type = "unconfirmed_credit"
            affects_cashflow = False  # NEVER count unconfirmed credits per §6.3!

        return MessageFact(
            message_id=message_id,
            user_id=user_id,
            request_id=request_id,
            related_event_id=related_event_id,
            source_type=source_type,
            fact_type=fact_type,
            amount=amount,
            date=parsed_date,
            percentage=percentage,
            affects_cashflow=affects_cashflow,
            description=text[:80],
        )

    def ingest_messages(self, messages: list[Any]) -> None:
        """Ingest any messages from DataLoader that are not already present in the cache."""
        for msg in messages:
            msg_id = getattr(msg, "message_id", "")
            if msg_id and msg_id not in self.facts_by_message_id:
                u_id = getattr(msg, "user_id", "")
                txt = getattr(msg, "message_text", "")
                rel_ev = getattr(msg, "related_event_id", None)
                req_id = getattr(msg, "request_id", None)
                fact = self.parse_message_text(msg_id, u_id, txt, rel_ev, req_id)
                self.add_fact(fact)

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
        loader: Optional[Any] = None,
        image_cache_file: str | Path = "code/cache/image_amounts.json",
        message_cache_file: str | Path = "code/cache/message_facts.json",
    ):
        self.images = ImageExtractor(image_cache_file)
        self.messages = MessageExtractor(message_cache_file)

        if loader is not None and hasattr(loader, "messages"):
            self.messages.ingest_messages(loader.messages)

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
