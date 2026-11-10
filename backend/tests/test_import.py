from decimal import Decimal

from sqlalchemy import select

from app.models import Document, Transaction

from .conftest import make_pdf
from .test_extraction import run_pipeline

CSV = (
    "Date,Details,Debit,Credit,Balance\n"
    "01/03/2024,OPENING SALARY ACME,,50000.00,60000.00\n"
    "03/03/2024,SUPERMARKET,2500.50,,57499.50\n"
    "10/03/2024,RENT,20000.00,,37499.50\n"
)


def post_csv(client, csrf, text, **form):
    return client.post(
        "/api/imports/csv",
        files={"file": ("bank.csv", text.encode(), "text/csv")},
        data=form,
        headers={"X-CSRF-Token": csrf},
    )


def test_csv_import_reconciles(logged_in, session_factory):
    client, csrf = logged_in
    response = post_csv(client, csrf, CSV, account_number="1234567890")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "reconciled"
    with session_factory() as db:
        doc = db.scalar(select(Document))
        assert doc.adapter == "import" and doc.opening_balance == Decimal("10000.00")
        assert doc.closing_balance == Decimal("37499.50")
        rows = db.scalars(select(Transaction).order_by(Transaction.seq)).all()
        assert [r.debit for r in rows] == [Decimal("0.00"), Decimal("2500.50"), Decimal("20000.00")]
        assert rows[0].extraction_method == "import"
        assert doc.account_id is not None


def test_csv_with_a_wrong_balance_goes_to_review(logged_in):
    client, csrf = logged_in
    bad = CSV.replace("57499.50", "57000.00", 1)
    response = post_csv(client, csrf, bad)
    assert response.status_code == 201
    assert response.json()["status"] == "needs_review"


def test_csv_duplicate_and_bad_input(logged_in):
    client, csrf = logged_in
    assert post_csv(client, csrf, CSV).status_code == 201
    assert post_csv(client, csrf, CSV).status_code == 409
    assert post_csv(client, csrf, "nothing,useful\n1,2\n").json()["detail"]["code"] == "csv_no_header"
    bad_date = CSV.replace("03/03/2024", "someday")
    detail = post_csv(client, csrf, bad_date).json()["detail"]
    assert detail == {"code": "csv_bad_date", "row": 3}


def test_csv_signed_amount_column_and_semicolons(logged_in):
    client, csrf = logged_in
    text = "Date;Description;Amount;Balance\n2024-03-01;PAY;1,000.00;3000.00\n2024-03-02;SHOP;-500.00;2500.00\n"
    response = post_csv(client, csrf, text)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "reconciled"


def test_manual_entry_needs_an_opening_balance_without_balances(logged_in):
    client, csrf = logged_in
    body = {"rows": [{"date": "2024-03-01", "description": "Coffee", "debit": "300"}]}
    r = client.post("/api/imports/manual", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "opening_balance_needed"
    body["opening_balance"] = "1000"
    r = client.post("/api/imports/manual", json=body, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201 and r.json()["status"] == "reconciled"


GENERIC = (
    "Some Unknown Bank   Account Number: 111 222 3333\n"
    "Opening Balance 10,000.00\n"
    "01/03/2024 SALARY 5,000.00 15,000.00\n"
    "02/03/2024 SHOP 1,000.00 14,000.00\n"
    "03/03/2024 CAFE 200.00 13,800.00\n"
    "Closing Balance 13,800.00\n"
)


def test_unknown_layout_is_read_by_the_generic_adapter(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, make_pdf([GENERIC]))
    with session_factory() as db:
        doc = db.get(Document, doc_id)
        assert doc.adapter == "generic"
        assert doc.status == "reconciled"
        assert len(db.scalars(select(Transaction)).all()) == 3


def test_generic_without_a_closing_line_is_sent_to_review(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    text = GENERIC.replace("Closing Balance 13,800.00\n", "")
    doc_id = run_pipeline(client, csrf, session_factory, test_settings, make_pdf([text]))
    with session_factory() as db:
        assert db.get(Document, doc_id).status == "needs_review"
