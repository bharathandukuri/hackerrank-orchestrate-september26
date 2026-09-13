"""
output_writer.py - Formats, writes, and validates output.csv according to challenge specifications.

Required columns in exact order:
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional


@dataclass(slots=True)
class DecisionOutput:
    request_id: str
    amount_safe_to_pay: float
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: Optional[date]
    spending_changes_needed: str
    decision_explanation: str

    def to_row(self) -> dict[str, str]:
        # Format amount_safe_to_pay
        if self.amount_safe_to_pay.is_integer():
            safe_str = str(int(self.amount_safe_to_pay))
        else:
            safe_str = f"{self.amount_safe_to_pay:.2f}".rstrip("0").rstrip(".")

        earliest_str = (
            self.earliest_date_for_full_payment.strftime("%Y-%m-%d")
            if self.earliest_date_for_full_payment
            else ""
        )

        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": safe_str,
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": earliest_str,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation,
        }


COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

VALID_STATUSES = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable",
}

VALID_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}


def write_output_csv(
    decisions: List[DecisionOutput], output_path: str | Path = "dataset/output.csv"
) -> None:
    """Write decisions to output.csv."""
    path = Path(output_path)
    with open(path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for d in decisions:
            writer.writerow(d.to_row())


def validate_output_csv(
    output_path: str | Path = "dataset/output.csv", expected_count: int = 250
) -> List[str]:
    """
    Validate output.csv against all challenge rules.
    Returns list of error descriptions (empty list if 100% valid).
    """
    path = Path(output_path)
    errors: list[str] = []

    if not path.exists():
        return [f"Output file {path} does not exist"]

    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []

        if header != COLUMNS:
            errors.append(f"Header mismatch. Expected {COLUMNS}, got {header}")

        rows = list(reader)
        if len(rows) != expected_count:
            errors.append(f"Expected {expected_count} rows, found {len(rows)}")

        seen_ids = set()
        for idx, row in enumerate(rows, start=2):
            req_id = row.get("request_id", "")
            if not req_id:
                errors.append(f"Row {idx}: Missing request_id")
            elif req_id in seen_ids:
                errors.append(f"Row {idx}: Duplicate request_id {req_id}")
            seen_ids.add(req_id)

            # Validate safe amount
            try:
                safe_amt = float(row.get("amount_safe_to_pay", ""))
                if safe_amt < 0:
                    errors.append(
                        f"Row {idx} ({req_id}): Negative amount_safe_to_pay {safe_amt}"
                    )
            except ValueError:
                errors.append(
                    f"Row {idx} ({req_id}): Invalid amount_safe_to_pay '{row.get('amount_safe_to_pay')}'"
                )

            # Validate status
            status = row.get("affordability_status", "")
            if status not in VALID_STATUSES:
                errors.append(f"Row {idx} ({req_id}): Invalid status '{status}'")

            # Validate method
            method = row.get("recommended_payment_method", "")
            if method not in VALID_METHODS:
                errors.append(f"Row {idx} ({req_id}): Invalid method '{method}'")

            # Validate payment plan
            plan = row.get("payment_plan", "")
            if method == "not_recommended" and plan != "none":
                errors.append(
                    f"Row {idx} ({req_id}): Method is not_recommended but plan is '{plan}'"
                )
            elif method != "not_recommended" and plan == "none":
                errors.append(
                    f"Row {idx} ({req_id}): Method is {method} but plan is 'none'"
                )

            # Validate earliest date
            earliest = row.get("earliest_date_for_full_payment", "").strip()
            if status == "affordable_now" and not earliest:
                errors.append(
                    f"Row {idx} ({req_id}): affordable_now requires earliest_date_for_full_payment"
                )
            if earliest:
                try:
                    datetime.strptime(earliest, "%Y-%m-%d")
                except ValueError:
                    errors.append(
                        f"Row {idx} ({req_id}): Invalid earliest date format '{earliest}'"
                    )

            # Validate explanation
            explanation = row.get("decision_explanation", "").strip()
            if not explanation:
                errors.append(f"Row {idx} ({req_id}): Missing decision_explanation")

    return errors


if __name__ == "__main__":
    # Self-test validator on sample_requests.csv
    errors = validate_output_csv("dataset/sample_requests.csv", expected_count=25)
    print(f"Sample requests validation errors count: {len(errors)}")
    if errors:
        for err in errors[:5]:
            print(" ", err)
    else:
        print("dataset/sample_requests.csv passes validation perfectly!")
