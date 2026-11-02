"""Account identity without storing account numbers.

Only the last 4 digits (for masked display) and a keyed fingerprint (HMAC-SHA256) are
kept, so the same account is recognised across statements but the number cannot be
read back from the database. The full number is never stored or logged.
"""

import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Account, Setting

_KEY_SETTING = "account_fingerprint_key"


def _fingerprint_key(db: Session, settings: Settings) -> str:
    if settings.account_fingerprint_key:
        return settings.account_fingerprint_key

    row = db.get(Setting, _KEY_SETTING)
    if row is None:
        db.add(Setting(key=_KEY_SETTING, value=secrets.token_hex(32)))
        try:
            db.commit()
        except IntegrityError:  # another worker created it first
            db.rollback()
        row = db.get(Setting, _KEY_SETTING)
    return str(row.value)


def fingerprint(key: str, account_number: str) -> str:
    digits = re.sub(r"\D", "", account_number)
    return hmac.new(key.encode(), digits.encode(), hashlib.sha256).hexdigest()


def get_or_create_account(
    db: Session,
    settings: Settings,
    user_id: int,
    bank_id: int | None,
    account_number: str,
) -> Account:
    digits = re.sub(r"\D", "", account_number)
    print_ = fingerprint(_fingerprint_key(db, settings), digits)

    def lookup() -> Account | None:
        return db.scalar(
            select(Account).where(
                Account.user_id == user_id,
                Account.bank_id == bank_id,
                Account.account_fingerprint == print_,
            )
        )

    account = lookup()
    if account is None:
        account = Account(
            user_id=user_id,
            bank_id=bank_id,
            account_fingerprint=print_,
            account_number_last4=digits[-4:],
        )
        db.add(account)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            account = lookup()
    return account
