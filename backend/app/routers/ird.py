import csv
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_session
from app.models import Account, Bank, Category, Document, Setting, Transaction, UserSession
from app.routers.transactions import _safe
from app.services import coverage, ird, ird_pack
from app.services.extraction import ACTIVE_STATUSES

router = APIRouter(prefix="/api/reports", tags=["reports"])

ZERO = Decimal("0.00")
MAX_LINES = 300  # itemised rows per list; the totals above them always count everything


class Head(BaseModel):
    key: str
    label: str
    amount: Decimal  # credits minus debits in the head's categories
    tax_withheld: Decimal  # tax lines found for it (interest and dividends only)
    count: int


class MonthRow(BaseModel):
    year: int
    month: int
    employment: Decimal
    interest: Decimal
    dividends: Decimal
    other_income: Decimal
    tax_withheld: Decimal


class BankRow(BaseModel):
    bank_code: str | None
    bank_name: str | None
    employment: Decimal
    interest: Decimal
    interest_tax: Decimal
    dividends: Decimal
    other_income: Decimal


class Line(BaseModel):
    kind: str  # employment | interest | dividends | tax
    date: date
    bank_code: str | None
    account_last4: str | None
    description: str
    amount: Decimal


class CategoryRow(BaseModel):
    head: str
    category: str
    amount: Decimal


class MissingMonth(BaseModel):
    year: int
    month: int


class AccountCover(BaseModel):
    bank_code: str | None
    account_last4: str | None
    covered: int  # months of the year of assessment with a statement
    missing: list[MissingMonth]


class Extras(BaseModel):
    """Figures that are not on a bank statement, entered by you for one year of assessment."""

    employer_tax: Decimal = Field(default=ZERO, ge=0)  # tax your employer deducted (APIT), from their certificate
    other_tax_paid: Decimal = Field(default=ZERO, ge=0)  # tax you paid some other way (a payment to the IRD, say)
    notes: str = Field(default="", max_length=500)


def _extras_key(user_id: int, year: int) -> str:
    return f"ird_extras:{user_id}:{year}"


def load_extras(db: Session, user_id: int, year: int) -> Extras:
    row = db.get(Setting, _extras_key(user_id, year))
    if row is None or not isinstance(row.value, dict):
        return Extras()
    cents = Decimal("0.01")
    return Extras(
        employer_tax=Decimal(row.value.get("employer_tax", 0)).quantize(cents),
        other_tax_paid=Decimal(row.value.get("other_tax_paid", 0)).quantize(cents),
        notes=row.value.get("notes", ""),
    )


class IrdOut(BaseModel):
    year: int
    label: str  # "2025/26"
    period_start: date
    period_end: date
    heads: list[Head]
    other_tax: Decimal  # tax lines that are not on interest or dividends (stamp duty and so on)
    total_income: Decimal  # employment + interest + dividends + other income; deposits are separate
    months: list[MonthRow]
    banks: list[BankRow]
    by_category: list[CategoryRow]
    lines: list[Line]
    uncategorised_credits: Decimal
    uncategorised_count: int
    extras: Extras
    review_documents: int  # statements in the period still waiting for review: not in these figures
    possible_tax: Decimal  # uncategorised debits right next to an interest or dividend credit
    possible_tax_count: int
    coverage: list[AccountCover]


def build(db: Session, user_id: int, year: int) -> IrdOut:
    start, end = ird.bounds(year)
    included = select(Document.id).where(Document.user_id == user_id, Document.status.in_(ACTIVE_STATUSES))
    rows = db.execute(
        select(
            Transaction.account_id,
            Transaction.transaction_date,
            Transaction.credit,
            Transaction.debit,
            Transaction.original_description,
            Category.name,
            Category.kind,
            Bank.code,
            Bank.name,
            Account.account_number_last4,
        )
        .select_from(Transaction)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .outerjoin(Bank, Transaction.bank_id == Bank.id)
        .outerjoin(Account, Transaction.account_id == Account.id)
        .where(
            Transaction.user_id == user_id,
            Transaction.document_id.in_(included),
            Transaction.is_duplicate.is_(False),
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .order_by(Transaction.transaction_date, Transaction.document_id, Transaction.seq)
    ).all()

    amount: dict[str, Decimal] = defaultdict(lambda: ZERO)
    count: dict[str, int] = defaultdict(int)
    tax: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_month: dict[tuple[int, int], dict[str, Decimal]] = {m: defaultdict(lambda: ZERO) for m in ird.months(year)}
    by_bank: dict[tuple, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    by_category: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    lines: dict[str, list[Line]] = defaultdict(list)
    uncategorised = ZERO
    uncategorised_count = 0
    possible_tax = ZERO
    possible_tax_count = 0

    # Dates of each account's interest and dividend credits: a tax line right next to one of them
    # is the tax on it, whatever the bank called it.
    credited: dict[str, dict[int | None, list[date]]] = {ird.INTEREST: defaultdict(list), ird.DIVIDENDS: defaultdict(list)}
    for account_id, when, credit, _d, _desc, category, kind, *_rest in rows:
        head = ird.head_of(category, kind)
        if head in credited and Decimal(credit) > 0:
            credited[head][account_id].append(when)

    def tax_of(account_id, when, description) -> str:
        head = ird.tax_head(description)
        if head == "other" and "STAMP" not in description.upper():
            for candidate in (ird.INTEREST, ird.DIVIDENDS):
                if ird.near(credited[candidate].get(account_id, []), when):
                    return candidate
        return head

    for account_id, when, credit, debit, description, category, kind, bank_code, bank_name, last4 in rows:
        credit, debit = Decimal(credit), Decimal(debit)
        key = (when.year, when.month)
        bank_key = (bank_code, bank_name)

        if category is None:
            if credit > 0:
                uncategorised += credit
                uncategorised_count += 1
            elif debit > 0 and tax_of(account_id, when, description) != "other":
                possible_tax += debit  # an uncategorised debit next to an interest credit: likely its tax
                possible_tax_count += 1
            continue
        if category == "Tax" and kind == "expense":
            net = debit - credit
            head = tax_of(account_id, when, description)
            if head == "other":
                tax["other"] += net
            else:
                tax[head] += net
                by_month[key]["tax_withheld"] += net
                if head == ird.INTEREST:
                    by_bank[bank_key]["interest_tax"] += net
            if len(lines["tax"]) < MAX_LINES:
                lines["tax"].append(Line(kind="tax", date=when, bank_code=bank_code, account_last4=last4, description=description, amount=net))
            continue

        head = ird.head_of(category, kind)
        if head is None:
            continue
        net = credit - debit
        amount[head] += net
        count[head] += 1
        by_category[(head, category)] += net
        if head != ird.DEPOSITS:
            by_month[key][head] += net
            by_bank[bank_key][head] += net
        if head in (ird.EMPLOYMENT, ird.INTEREST, ird.DIVIDENDS) and len(lines[head]) < MAX_LINES:
            lines[head].append(Line(kind=head, date=when, bank_code=bank_code, account_last4=last4, description=description, amount=net))

    heads = [
        Head(
            key=h,
            label=ird.HEAD_LABEL[h],
            amount=amount[h],
            tax_withheld=tax[h] if h in (ird.INTEREST, ird.DIVIDENDS) else ZERO,
            count=count[h],
        )
        for h in (ird.EMPLOYMENT, ird.INTEREST, ird.DIVIDENDS, ird.OTHER_INCOME, ird.DEPOSITS)
    ]
    total = amount[ird.EMPLOYMENT] + amount[ird.INTEREST] + amount[ird.DIVIDENDS] + amount[ird.OTHER_INCOME]

    # which months of the year of assessment each account has a statement for
    wanted = set(ird.months(year))
    banks = {b.id: b for b in db.scalars(select(Bank))}
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))}
    seen: dict[tuple, set[tuple[int, int]]] = defaultdict(set)
    review = 0
    for doc in db.scalars(
        select(Document).where(
            Document.user_id == user_id,
            Document.period_end.is_not(None),
            Document.status.in_(ACTIVE_STATUSES + ("needs_review",)),
        )
    ):
        months_covered = coverage.covered_months(doc.period_start, doc.period_end)
        if not months_covered & wanted:
            continue
        if doc.status == "needs_review":
            review += 1
            continue
        seen[(doc.bank_id, doc.account_id)] |= months_covered & wanted
    covers = []
    for (bank_id, account_id), have in sorted(seen.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)):
        covers.append(
            AccountCover(
                bank_code=banks[bank_id].code if bank_id in banks else None,
                account_last4=accounts[account_id].account_number_last4 if account_id in accounts else None,
                covered=len(have),
                missing=[MissingMonth(year=y, month=m) for y, m in ird.months(year) if (y, m) not in have],
            )
        )

    return IrdOut(
        year=year,
        label=ird.label(year),
        period_start=start,
        period_end=end,
        heads=heads,
        other_tax=tax["other"],
        total_income=total,
        months=[
            MonthRow(
                year=y,
                month=m,
                employment=by_month[(y, m)][ird.EMPLOYMENT],
                interest=by_month[(y, m)][ird.INTEREST],
                dividends=by_month[(y, m)][ird.DIVIDENDS],
                other_income=by_month[(y, m)][ird.OTHER_INCOME],
                tax_withheld=by_month[(y, m)]["tax_withheld"],
            )
            for y, m in ird.months(year)
        ],
        banks=[
            BankRow(
                bank_code=code,
                bank_name=name,
                employment=v[ird.EMPLOYMENT],
                interest=v[ird.INTEREST],
                interest_tax=v["interest_tax"],
                dividends=v[ird.DIVIDENDS],
                other_income=v[ird.OTHER_INCOME],
            )
            for (code, name), v in sorted(by_bank.items(), key=lambda kv: (kv[0][1] or "~"))
        ],
        by_category=[
            CategoryRow(head=h, category=c, amount=v) for (h, c), v in sorted(by_category.items())
        ],
        lines=[line for kind in ("employment", "interest", "dividends", "tax") for line in lines[kind]],
        uncategorised_credits=uncategorised,
        uncategorised_count=uncategorised_count,
        extras=load_extras(db, user_id, year),
        review_documents=review,
        possible_tax=possible_tax,
        possible_tax_count=possible_tax_count,
        coverage=covers,
    )


@router.get("/ird", response_model=IrdOut)
def ird_report(
    year: int | None = Query(default=None, ge=2000, le=2100),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> IrdOut:
    """Income by head and tax withheld for a year of assessment (1 April to 31 March)."""
    return build(db, session.user_id, year if year is not None else ird.assessment_year(date.today()))


@router.get("/ird/extras", response_model=Extras)
def get_extras(
    year: int = Query(ge=2000, le=2100),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Extras:
    return load_extras(db, session.user_id, year)


@router.put("/ird/extras", response_model=Extras)
def put_extras(
    body: Extras,
    year: int = Query(ge=2000, le=2100),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Extras:
    """Save the figures you entered for a year (amounts and a short note; nothing from a statement)."""
    key = _extras_key(session.user_id, year)
    value = {"employer_tax": str(body.employer_tax), "other_tax_paid": str(body.other_tax_paid), "notes": body.notes.strip()}
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()
    return load_extras(db, session.user_id, year)


@router.get("/ird.csv")
def ird_csv(
    year: int | None = Query(default=None, ge=2000, le=2100),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    report = build(db, session.user_id, year if year is not None else ird.assessment_year(date.today()))
    buffer = io.StringIO()
    out = csv.writer(buffer)
    out.writerow([f"Year of assessment {report.label}", f"{report.period_start} to {report.period_end}"])
    out.writerow(["Currency", "LKR"])
    out.writerow(["Figures from bank statements; not tax advice. Check certificates and the IRD rules before filing."])
    out.writerow([])
    out.writerow(["Head", "Amount", "Tax withheld", "Rows"])
    for h in report.heads:
        out.writerow([h.label, h.amount, h.tax_withheld, h.count])
    out.writerow(["Total income recorded (not counting deposits)", report.total_income])
    out.writerow(["Other tax lines (stamp duty and so on)", report.other_tax])
    out.writerow(["Entered by you", "Employer tax (APIT)", report.extras.employer_tax, "Other tax paid", report.extras.other_tax_paid])
    if report.extras.notes:
        out.writerow(["Note", _safe(report.extras.notes)])
    out.writerow([])
    out.writerow(["Month", "Employment", "Interest", "Dividends", "Other income", "Tax withheld"])
    for m in report.months:
        out.writerow([f"{m.year}-{m.month:02d}", m.employment, m.interest, m.dividends, m.other_income, m.tax_withheld])
    out.writerow([])
    out.writerow(["Bank", "Employment", "Interest", "Tax on interest", "Dividends", "Other income"])
    for b in report.banks:
        out.writerow([b.bank_name or "Unknown bank", b.employment, b.interest, b.interest_tax, b.dividends, b.other_income])
    out.writerow([])
    out.writerow(["Itemised", "Date", "Bank", "Account", "Description", "Amount"])
    for line in report.lines:
        out.writerow([line.kind, line.date, line.bank_code or "", line.account_last4 or "", _safe(line.description), line.amount])
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ird-{report.label.replace("/", "-")}.csv"'},
    )


@router.get("/ird.pdf")
def ird_pdf(
    year: int | None = Query(default=None, ge=2000, le=2100),
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> Response:
    """A printable pack for an accountant: the figures, what to check, and the transactions."""
    report = build(db, session.user_id, year if year is not None else ird.assessment_year(date.today()))
    return Response(
        ird_pack.build_pdf(report, date.today(), MAX_LINES),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="ird-{report.label.replace("/", "-")}.pdf"'},
    )
