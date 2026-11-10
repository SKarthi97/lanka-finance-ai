"""Every threshold the reports and alerts use, in one place.

Each value has a default here. To change one without touching code, set an environment variable
named TUNE_<NAME> (for example TUNE_IDLE_MIN_BALANCE=50000) and restart the backend and worker
(no rebuild). A value that cannot be read is an error at start-up, never silently ignored.
`docs/07-budgets-recurring-reports.md` explains what each one does.
"""

import os
from decimal import Decimal, InvalidOperation


def _read(name: str, default, convert):
    raw = os.environ.get(f"TUNE_{name}", "").strip()
    if not raw:
        return default
    try:
        return convert(raw)
    except (ValueError, InvalidOperation):
        raise ValueError(f"TUNE_{name}={raw!r} is not a valid {convert.__name__}") from None


def _int(name: str, default: int) -> int:
    return _read(name, default, int)


def _dec(name: str, default: str) -> Decimal:
    return _read(name, Decimal(default), Decimal)


def _float(name: str, default: float) -> float:
    return _read(name, default, float)


# --- budgets ---
BUDGET_NEAR = _dec("BUDGET_NEAR", "0.80")  # at or above this share of the limit a budget is "near"

# --- savings page and the falling-rate alert ---
TRAILING_DAYS = _int("TRAILING_DAYS", 365)  # the window for "what a bank pays"
DROP_POINTS = _dec("DROP_POINTS", "0.50")  # a fall of this many percentage points is worth telling
DROP_BASELINE = _int("DROP_BASELINE", 3)  # compare with the average of up to this many earlier credits
DROP_MIN_BEFORE = _int("DROP_MIN_BEFORE", 2)  # needs at least this many earlier credits
IDLE_NO_INTEREST_DAYS = _int("IDLE_NO_INTEREST_DAYS", 180)  # no interest for this long
IDLE_WINDOW_DAYS = _int("IDLE_WINDOW_DAYS", 90)  # average balance is taken over this many days
IDLE_MIN_BALANCE = _dec("IDLE_MIN_BALANCE", "25000")  # ...and must be at least this much
PROJECTION_MONTHS = _int("PROJECTION_MONTHS", 12)
TREND_MONTHS = _int("TREND_MONTHS", 6)  # months of history the projection continues

# --- interest rate from balances ---
TAX_WINDOW_DAYS = _int("TAX_WINDOW_DAYS", 3)  # withheld tax on the credit day or up to this many days after
MIN_ASSUMED_DAYS = _int("MIN_ASSUMED_DAYS", 25)  # a first credit needs about this many days of data
MIN_SAME_MONTH_DAYS = _int("MIN_SAME_MONTH_DAYS", 20)  # ...or this many when it pays for its own month

# --- IRD ---
NEAR_BEFORE_DAYS = _int("NEAR_BEFORE_DAYS", 1)  # a tax line may sit this many days before its credit...
NEAR_AFTER_DAYS = _int("NEAR_AFTER_DAYS", 3)  # ...or up to this many days after

# --- statements and backups ---
BACKUP_STALE_DAYS = _int("BACKUP_STALE_DAYS", 7)  # a backup older than this is flagged (bell and System page)
STALE_DAYS = _int("STALE_DAYS", 45)  # an account whose latest statement is older is "out of date"

# --- recurring payments ---
AMOUNT_TOLERANCE = _dec("RECURRING_AMOUNT_TOLERANCE", "0.20")  # amounts within 20% of the median match
SHARE = _float("RECURRING_SHARE", 0.75)  # this share of gaps and amounts must fit

# --- transfers between your own accounts ---
TRANSFER_WINDOW_DAYS = _int("TRANSFER_WINDOW_DAYS", 3)  # the two legs must be within this many days

# --- flags on a transaction ---
FLAG_MIN_PEERS = _int("FLAG_MIN_PEERS", 5)
FLAG_LARGE_TIMES = _int("FLAG_LARGE_TIMES", 3)
FLAG_MIN_PAYMENTS_FOR_NEW_PAYEE = _int("FLAG_MIN_PAYMENTS_FOR_NEW_PAYEE", 30)
FLAG_NEW_PAYEE_TIMES = _int("FLAG_NEW_PAYEE_TIMES", 2)
