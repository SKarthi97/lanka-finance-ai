"""Categories survive re-extraction; duplicates are only matched within one bank.
All data is synthetic."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import Bank, Document, Transaction, User
from app.services.dedupe import refresh_duplicates
from app.worker import process_one

from .synthetic import boc_pdf
from .test_extraction import run_pipeline

TWO_ROWS = [
    ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
    ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
]


def by_description(client):
    return {t["description"]: t for t in client.get("/api/transactions?limit=500").json()["items"]}


def category_ids(client):
    return {c["name"]: c["id"] for c in client.get("/api/categories").json()}


def reprocess(client, csrf, session_factory, test_settings, doc_id):
    response = client.post(f"/api/documents/{doc_id}/reprocess", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 202
    assert process_one(session_factory, "w1", test_settings) is True


def test_a_manual_category_survives_re_extraction(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    # needs_review keeps the original file, so it can be extracted again
    doc_id = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(rows=TWO_ROWS, closing="999.00")
    )
    fuel = category_ids(client)["Fuel"]
    atm = by_description(client)["ATM CASH WITHDRAWAL"]
    client.put(
        f"/api/transactions/{atm['id']}/category",
        json={"category_id": fuel},
        headers={"X-CSRF-Token": csrf},
    )

    reprocess(client, csrf, session_factory, test_settings, doc_id)

    row = by_description(client)["ATM CASH WITHDRAWAL"]
    assert row["category_id"] == fuel
    assert row["classification_source"] == "manual"
    assert len(by_description(client)) == 2  # replaced, not doubled


def test_a_cleared_category_is_also_kept(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    doc_id = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(rows=TWO_ROWS, closing="999.00")
    )
    atm = by_description(client)["ATM CASH WITHDRAWAL"]
    assert atm["category_id"] is not None  # a built-in rule categorised it
    client.put(
        f"/api/transactions/{atm['id']}/category",
        json={"category_id": None},
        headers={"X-CSRF-Token": csrf},
    )

    reprocess(client, csrf, session_factory, test_settings, doc_id)

    row = by_description(client)["ATM CASH WITHDRAWAL"]
    assert row["category_id"] is None and row["classification_source"] == "manual"


def test_rows_you_did_not_touch_are_still_categorised_by_rules(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    doc_id = run_pipeline(
        client, csrf, session_factory, test_settings, boc_pdf(rows=TWO_ROWS, closing="999.00")
    )
    before = by_description(client)["SALARY CREDIT SYNTHETIC"]["category_id"]

    reprocess(client, csrf, session_factory, test_settings, doc_id)

    after = by_description(client)["SALARY CREDIT SYNTHETIC"]
    assert after["category_id"] == before
    assert after["classification_source"] != "manual"


def _statement_rows(db, user_id: int, bank_id: int | None, count: int = 1):
    doc = Document(
        user_id=user_id, bank_id=bank_id, sha256=f"{bank_id}{'a' * 63}"[:64], storage_path="p",
        original_filename="f.pdf", size_bytes=1, status="reconciled",
    )  # fmt: skip
    db.add(doc)
    db.flush()
    for seq in range(1, count + 1):
        db.add(
            Transaction(
                user_id=user_id, document_id=doc.id, bank_id=bank_id, seq=seq,
                transaction_date=date(2022, 9, 5), original_description="SAME",
                debit=Decimal("5.00"), credit=Decimal("0.00"),
                running_balance=Decimal("995.00"), source_page=1, row_hash="h" * 64,
            )  # fmt: skip
        )
    db.flush()


def test_rows_with_no_account_are_not_matched_across_banks(session_factory):
    with session_factory() as db:
        user = User(username="u", password_hash="x")
        db.add(user)
        db.add_all([Bank(code="b1", name="Bank One"), Bank(code="b2", name="Bank Two")])
        db.flush()
        b1, b2 = (db.scalar(select(Bank).where(Bank.code == code)).id for code in ("b1", "b2"))

        # the same date, amount, balance and text in two different banks, no account found
        _statement_rows(db, user.id, b1)
        _statement_rows(db, user.id, b2)

        assert refresh_duplicates(db, user.id) == 0


def test_rows_with_no_account_are_still_matched_inside_one_bank(session_factory):
    with session_factory() as db:
        user = User(username="u", password_hash="x")
        db.add(user)
        db.add(Bank(code="b1", name="Bank One"))
        db.flush()
        b1 = db.scalar(select(Bank).where(Bank.code == "b1")).id

        # a re-downloaded copy whose bytes differ, account number not detected in either
        _statement_rows(db, user.id, b1)
        db.flush()
        second = Document(
            user_id=user.id, bank_id=b1, sha256="c" * 64, storage_path="p2",
            original_filename="g.pdf", size_bytes=1, status="reconciled",
        )  # fmt: skip
        db.add(second)
        db.flush()
        db.add(
            Transaction(
                user_id=user.id, document_id=second.id, bank_id=b1, seq=1,
                transaction_date=date(2022, 9, 5), original_description="SAME",
                debit=Decimal("5.00"), credit=Decimal("0.00"),
                running_balance=Decimal("995.00"), source_page=1, row_hash="h" * 64,
            )  # fmt: skip
        )
        db.flush()

        assert refresh_duplicates(db, user.id) == 1
