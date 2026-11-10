from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import UserSession
from app.services import interest, savings

router = APIRouter(prefix="/api/savings", tags=["savings"])


class InterestMonth(BaseModel):
    month: int
    interest: Decimal  # credited in this month, after tax; shown even when no rate can be worked out
    tax: Decimal  # tax withheld on it, when a line for it was found
    average_balance: Decimal | None  # average end-of-day balance over the days the interest covers
    days: int
    annual_rate: Decimal | None  # percent a year; None when there is too little data behind it
    monthly_rate: Decimal | None  # annual / 12
    assumed: str | None  # what the start of the period was assumed to be, when it had to be
    unrated: int  # credits in the month that could not be rated


class InterestOut(BaseModel):
    year: int
    accounts: int  # accounts that were credited interest in the data
    unrecognised: int  # credits that mention interest but are not in the Interest income category
    months: list[InterestMonth]


@router.get("/interest", response_model=InterestOut)
def interest_by_month(
    year: int = Query(ge=2000, le=2100),
    bank_code: str | None = Query(default=None, max_length=32),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> InterestOut:
    """The interest credited each month and the annual rate it works out to, from the days your
    money was kept. Interest credited in a month pays for the days before it (see services/interest)."""
    infos, unrecognised = savings.load_accounts(db, session.user_id, bank_code, year)
    paying = [i.data for i in infos if i.data.credits]
    months = interest.monthly_rates(paying, year)
    return InterestOut(
        year=year,
        accounts=len(paying),
        unrecognised=unrecognised,
        months=[
            InterestMonth(
                month=m.month,
                interest=m.interest,
                tax=m.tax,
                average_balance=m.average_balance.quantize(Decimal("0.01")) if m.average_balance is not None else None,
                days=m.days,
                annual_rate=m.annual_rate,
                monthly_rate=m.monthly_rate,
                assumed=m.assumed,
                unrated=m.unrated,
            )
            for m in months
        ],
    )


# --- insights ----------------------------------------------------------------------------------


class BankRateOut(BaseModel):
    bank_code: str | None
    bank_name: str | None
    accounts: int
    interest: Decimal
    average_balance: Decimal
    annual_rate: Decimal


class RateDropOut(BaseModel):
    bank_code: str | None
    bank_name: str | None
    previous_rate: Decimal
    latest_rate: Decimal
    since: date


class IdleOut(BaseModel):
    bank_code: str | None
    bank_name: str | None
    last4: str | None
    average_balance: Decimal
    could_earn_a_year: Decimal | None
    best_rate: Decimal | None


class ProjectionPoint(BaseModel):
    day: date
    balance: Decimal


class ProjectionOut(BaseModel):
    current_balance: Decimal
    monthly_change: Decimal
    months_used: int
    points: list[ProjectionPoint]
    months_to_goal: int | None
    goal_reached: bool


class InsightsOut(BaseModel):
    as_of: date | None
    banks: list[BankRateOut]
    best_rate: Decimal | None
    drops: list[RateDropOut]
    idle: list[IdleOut]
    projection: ProjectionOut | None


@router.get("/insights", response_model=InsightsOut)
def insights(
    goal: Decimal | None = Query(default=None, gt=0),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> InsightsOut:
    """What each bank pays you, a rate that is falling, money that may be idle and where the balance
    is heading. All of it is worked out from the statements (services/savings)."""
    infos, _ = savings.load_accounts(db, session.user_id)
    today = savings.as_of(infos)
    if today is None:
        return InsightsOut(as_of=None, banks=[], best_rate=None, drops=[], idle=[], projection=None)
    banks = savings.bank_rates(infos, today)
    best = banks[0].annual_rate if banks else None
    plan = savings.projection(infos, today, goal)
    return InsightsOut(
        as_of=today,
        banks=[BankRateOut(**vars(b)) for b in banks],
        best_rate=best,
        drops=[RateDropOut(**vars(d)) for d in savings.rate_drops(infos)],
        idle=[IdleOut(**vars(i)) for i in savings.idle_accounts(infos, today, best)],
        projection=(
            ProjectionOut(
                current_balance=plan.current_balance,
                monthly_change=plan.monthly_change,
                months_used=plan.months_used,
                points=[ProjectionPoint(day=d, balance=b) for d, b in plan.points],
                months_to_goal=plan.months_to_goal,
                goal_reached=plan.goal_reached,
            )
            if plan
            else None
        ),
    )
