"""
financial_state.py - Reconstructs user financial position and 90-day cashflow baseline.

Handles:
- Starting balance and pending debits reserve
- Filtering non-cash / cancelled / failed / pending credits
- Image amount resolution for blank event amounts
- Foreign currency conversion using dated exchange rates
- Message-based salary amendments, rent increases, freelance invoices, contract endings
- Recurrence detection for monthly, biweekly, and weekly income/expenses
- Projection of all confirmed/recurring cashflows across 90 days
- Identification of flexible candidate expenses eligible for spending changes
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from data_loader import DataLoader, FinancialEvent, Profile, Request
from evidence_extractor import EvidenceExtractor, MessageFact


@dataclass(slots=True)
class CashflowItem:
    item_date: date
    amount: float
    category: str
    description: str
    direction: str  # credit | debit
    is_recurring: bool
    event_id: Optional[str] = None
    flexibility: str = "fixed"  # fixed | reducible | stoppable | reducible_or_stoppable
    minimum_allowed_amount: Optional[float] = None


@dataclass(slots=True)
class FlexibleExpense:
    event_id: str
    category: str
    description: str
    amount: float
    minimum_allowed_amount: Optional[float]
    flexibility: str  # stoppable | reducible | reducible_or_stoppable
    recurring_dates: list[date]


@dataclass(slots=True)
class UserFinancialState:
    user_id: str
    request_id: str
    request_date: date
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    pending_debit_reserve: float
    starting_cash: float
    daily_net_flow: dict[date, float]
    daily_items: dict[date, list[CashflowItem]]
    flexible_expenses: list[FlexibleExpense]
    is_employment_ended: bool


class FinancialStateBuilder:
    """Builds a grounded, conservative 90-day financial state for a user at request_date."""

    def __init__(self, loader: DataLoader, extractor: EvidenceExtractor):
        self.loader = loader
        self.extractor = extractor

    def build_state(self, request: Request) -> UserFinancialState:
        user_id = request.user_id
        req_date = request.request_date
        end_date = req_date + timedelta(days=90)
        profile = self.loader.profiles[user_id]
        events = self.loader.events_by_user_id.get(user_id, [])
        home_ccy = profile.home_currency

        # 1. Fill missing amounts from image extractor
        for ev in events:
            if ev.amount is None:
                img_amt = self.extractor.images.get_amount_for_event(ev.event_id)
                if img_amt is not None:
                    ev.amount = img_amt

        # 2. Compute pending debit reserve
        # Pending debits are reserved immediately; pending credits are ignored
        pending_debits = [
            e for e in events if e.status == "pending" and e.direction == "debit"
        ]
        total_pending_debit = 0.0
        for pd in pending_debits:
            amt = pd.amount or 0.0
            if pd.currency != home_ccy:
                rate = self.loader.get_exchange_rate(
                    pd.settlement_date, pd.currency, home_ccy
                )
                amt *= rate
            total_pending_debit += amt

        starting_cash = profile.current_available_balance - total_pending_debit

        daily_net_flow = defaultdict(float)
        daily_items = defaultdict(list)

        # 3. Scheduled events within [request_date, end_date]
        scheduled_events = [
            e
            for e in events
            if e.status == "scheduled" and req_date <= e.settlement_date <= end_date
        ]
        has_scheduled_salary = False
        scheduled_salary_date = None
        scheduled_salary_amt = 0.0

        for se in scheduled_events:
            amt = se.amount or 0.0
            if se.currency != home_ccy:
                rate = self.loader.get_exchange_rate(
                    se.settlement_date, se.currency, home_ccy
                )
                amt *= rate

            item = CashflowItem(
                item_date=se.settlement_date,
                amount=amt,
                category=se.category,
                description=se.description,
                direction=se.direction,
                is_recurring=False,
                event_id=se.event_id,
                flexibility=se.flexibility,
                minimum_allowed_amount=se.minimum_allowed_amount,
            )
            daily_items[se.settlement_date].append(item)

            if se.direction == "credit":
                daily_net_flow[se.settlement_date] += amt
                if se.category == "salary":
                    has_scheduled_salary = True
                    scheduled_salary_date = se.settlement_date
                    scheduled_salary_amt = amt
            elif se.direction == "debit":
                daily_net_flow[se.settlement_date] -= amt

        # 4. Message facts
        is_job_ended = self.extractor.messages.is_employment_ended(user_id)
        rent_inc_pct = self.extractor.messages.get_rent_increase_pct(user_id) or 0.0

        # Approved freelance invoices
        freelance_invoices = self.extractor.messages.get_approved_freelance_invoices(
            user_id
        )
        for fi in freelance_invoices:
            if fi.date and req_date <= fi.date <= end_date and fi.amount:
                daily_net_flow[fi.date] += fi.amount
                daily_items[fi.date].append(
                    CashflowItem(
                        item_date=fi.date,
                        amount=fi.amount,
                        category="income",
                        description=f"Approved freelance invoice ({fi.description})",
                        direction="credit",
                        is_recurring=False,
                    )
                )

        # 5. Settled historical events for recurrence detection
        settled_events = [
            e for e in events if e.status == "settled" and e.settlement_date <= req_date
        ]

        # Check if last salary was final or job ended
        salary_settled = [
            e
            for e in settled_events
            if e.category == "salary" and e.direction == "credit"
        ]
        salary_settled.sort(key=lambda x: x.settlement_date)

        if salary_settled and "final" in salary_settled[-1].description.lower():
            is_job_ended = True

        # Determine regular salary amount and pay day
        recurring_salary_amt = 0.0
        salary_day = 15
        if not is_job_ended:
            sal_adjs = self.extractor.messages.get_salary_adjustments(user_id)
            if sal_adjs:
                last_adj = sal_adjs[-1]
                if last_adj.amount:
                    recurring_salary_amt = last_adj.amount
                if last_adj.date:
                    salary_day = last_adj.date.day
            elif has_scheduled_salary:
                recurring_salary_amt = scheduled_salary_amt
                if scheduled_salary_date:
                    salary_day = scheduled_salary_date.day
            elif salary_settled:
                last_s = salary_settled[-1]
                s_amt = last_s.amount or 0.0
                if last_s.currency != home_ccy:
                    rate = self.loader.get_exchange_rate(
                        last_s.settlement_date, last_s.currency, home_ccy
                    )
                    s_amt *= rate
                recurring_salary_amt = s_amt
                salary_day = last_s.settlement_date.day

        # Project recurring salary forward
        if recurring_salary_amt > 0 and not is_job_ended:
            for m_offset in range(4):
                y = req_date.year + (req_date.month + m_offset - 1) // 12
                m = (req_date.month + m_offset - 1) % 12 + 1
                dom = min(salary_day, 28 if m == 2 else 30)
                sal_d = date(y, m, dom)
                if req_date <= sal_d <= end_date:
                    # Avoid duplicate on scheduled salary date
                    already_scheduled = any(
                        item.category == "salary" and item.direction == "credit"
                        for item in daily_items[sal_d]
                    )
                    if not already_scheduled:
                        daily_net_flow[sal_d] += recurring_salary_amt
                        daily_items[sal_d].append(
                            CashflowItem(
                                item_date=sal_d,
                                amount=recurring_salary_amt,
                                category="salary",
                                description="Projected regular salary",
                                direction="credit",
                                is_recurring=True,
                            )
                        )

        # 6. Detect recurring debits
        by_cat_desc = defaultdict(list)
        for e in settled_events:
            if e.direction == "debit" and e.amount is not None:
                by_cat_desc[(e.category, e.description)].append(e)

        flexible_candidates: list[FlexibleExpense] = []

        for (cat, desc), elist in by_cat_desc.items():
            if len(elist) < 2:
                continue
            elist.sort(key=lambda x: x.settlement_date)
            intervals = [
                (elist[i].settlement_date - elist[i - 1].settlement_date).days
                for i in range(1, len(elist))
            ]
            avg_int = sum(intervals) / len(intervals)

            last_ev = elist[-1]
            amt = last_ev.amount or 0.0
            if last_ev.currency != home_ccy:
                rate = self.loader.get_exchange_rate(
                    last_ev.settlement_date, last_ev.currency, home_ccy
                )
                amt *= rate

            if cat == "rent" and rent_inc_pct > 0:
                amt *= 1.0 + rent_inc_pct / 100.0

            min_allowed = last_ev.minimum_allowed_amount
            if min_allowed is not None and last_ev.currency != home_ccy:
                rate = self.loader.get_exchange_rate(
                    last_ev.settlement_date, last_ev.currency, home_ccy
                )
                min_allowed *= rate

            projected_dates: list[date] = []

            # Project according to interval
            if 25 <= avg_int <= 35:
                # Monthly on day of month
                dom = last_ev.settlement_date.day
                for m_offset in range(4):
                    y = req_date.year + (req_date.month + m_offset - 1) // 12
                    m = (req_date.month + m_offset - 1) % 12 + 1
                    dom_adj = min(dom, 28 if m == 2 else 30)
                    d = date(y, m, dom_adj)
                    if req_date <= d <= end_date:
                        # Avoid duplicating if already in scheduled events
                        already_scheduled = any(
                            item.category == cat and item.direction == "debit"
                            for item in daily_items[d]
                        )
                        if not already_scheduled:
                            projected_dates.append(d)
                            daily_net_flow[d] -= amt
                            daily_items[d].append(
                                CashflowItem(
                                    item_date=d,
                                    amount=amt,
                                    category=cat,
                                    description=desc,
                                    direction="debit",
                                    is_recurring=True,
                                    event_id=last_ev.event_id,
                                    flexibility=last_ev.flexibility,
                                    minimum_allowed_amount=min_allowed,
                                )
                            )

            elif 6 <= avg_int <= 8:
                # Weekly
                cur_d = last_ev.settlement_date
                while cur_d <= end_date:
                    cur_d += timedelta(days=7)
                    if req_date <= cur_d <= end_date:
                        projected_dates.append(cur_d)
                        daily_net_flow[cur_d] -= amt
                        daily_items[cur_d].append(
                            CashflowItem(
                                item_date=cur_d,
                                amount=amt,
                                category=cat,
                                description=desc,
                                direction="debit",
                                is_recurring=True,
                                event_id=last_ev.event_id,
                                flexibility=last_ev.flexibility,
                                minimum_allowed_amount=min_allowed,
                            )
                        )

            elif 13 <= avg_int <= 16:
                # Biweekly
                cur_d = last_ev.settlement_date
                while cur_d <= end_date:
                    cur_d += timedelta(days=14)
                    if req_date <= cur_d <= end_date:
                        projected_dates.append(cur_d)
                        daily_net_flow[cur_d] -= amt
                        daily_items[cur_d].append(
                            CashflowItem(
                                item_date=cur_d,
                                amount=amt,
                                category=cat,
                                description=desc,
                                direction="debit",
                                is_recurring=True,
                                event_id=last_ev.event_id,
                                flexibility=last_ev.flexibility,
                                minimum_allowed_amount=min_allowed,
                            )
                        )

            # Record flexible expense candidate if eligible
            if (
                last_ev.flexibility
                in ("stoppable", "reducible", "reducible_or_stoppable")
                and projected_dates
            ):
                flexible_candidates.append(
                    FlexibleExpense(
                        event_id=last_ev.event_id,
                        category=cat,
                        description=desc,
                        amount=amt,
                        minimum_allowed_amount=min_allowed,
                        flexibility=last_ev.flexibility,
                        recurring_dates=projected_dates,
                    )
                )

        return UserFinancialState(
            user_id=user_id,
            request_id=request.request_id,
            request_date=req_date,
            home_currency=home_ccy,
            current_available_balance=profile.current_available_balance,
            minimum_balance_to_keep=profile.minimum_balance_to_keep,
            pending_debit_reserve=total_pending_debit,
            starting_cash=starting_cash,
            daily_net_flow=daily_net_flow,
            daily_items=daily_items,
            flexible_expenses=flexible_candidates,
            is_employment_ended=is_job_ended,
        )


if __name__ == "__main__":
    loader = DataLoader().load_all()
    extractor = EvidenceExtractor()
    builder = FinancialStateBuilder(loader, extractor)

    state1 = builder.build_state(loader.requests[0])
    print(f"State for {state1.request_id} ({state1.user_id}):")
    print(
        f"  Starting cash: {state1.starting_cash:.2f} (bal: {state1.current_available_balance:.2f}, pending: {state1.pending_debit_reserve:.2f})"
    )
    print(f"  Min balance: {state1.minimum_balance_to_keep:.2f}")
    print(f"  Flexible expenses count: {len(state1.flexible_expenses)}")
    print(f"  Daily flow entries count: {len(state1.daily_net_flow)}")
