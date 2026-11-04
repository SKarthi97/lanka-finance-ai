"""Multi-bank correctness: own-account transfer matching, statement coverage and balance
continuity, per-bank split, per-account balance history. All data is synthetic."""

from decimal import Decimal

from app.models import Bank
from app.services import transfers

from .synthetic import FAKE_ACCOUNT, boc_pdf, hnb_lines, pdf_from_pages
from .test_extraction import run_pipeline

OTHER_ACCOUNT = "9990002222"  # a second fake account


def csrf_header(csrf):
    return {"X-CSRF-Token": csrf}


def account_a(day="05/09", amount="500.00", **kwargs):
    """Money leaves account A: 1,000 - amount."""
    left = Decimal("1000.00") - Decimal(amount)
    text = f"{left:,.2f}"
    return boc_pdf(
        rows=[(day, "PAYMENT OUT SYNTHETIC", amount, text)],
        closing=text,
        account=FAKE_ACCOUNT,
        **kwargs,
    )


def account_b(day="06/09", amount="500.00", extra=None):
    """Money arrives in account B (a different account): 200 + amount."""
    rows = [(day, "RECEIVED IN SYNTHETIC", amount, f"{Decimal('200.00') + Decimal(amount):,.2f}")]
    closing = rows[0][3]
    if extra:  # a second credit of the same amount, for the ambiguous case
        closing = f"{Decimal(closing.replace(',', '')) + Decimal(amount):,.2f}"
        rows.append((extra, "RECEIVED AGAIN SYNTHETIC", amount, closing))
    return boc_pdf(
        opening=("30/08", "200.00"), rows=rows, closing=closing, account=OTHER_ACCOUNT
    )


def load(client, csrf, session_factory, test_settings, *pdfs):
    for pdf in pdfs:
        run_pipeline(client, csrf, session_factory, test_settings, pdf)


def suggestions(client):
    return client.get("/api/transfers/suggestions").json()


# --- own-account transfer matching -----------------------------------------------------


def test_a_debit_and_a_credit_in_two_accounts_are_suggested(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b())

    found = suggestions(client)
    assert found["total"] == 1
    pair = found["items"][0]
    assert pair["amount"] == "500.00"
    assert pair["days_apart"] == 1
    assert pair["ambiguous"] is False
    assert pair["out"]["description"] == "PAYMENT OUT SYNTHETIC"
    assert pair["into"]["description"] == "RECEIVED IN SYNTHETIC"
    assert pair["out"]["account_last4"] != pair["into"]["account_last4"]


def test_nothing_changes_until_you_confirm(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b())
    before = client.get("/api/dashboard?year=2022&month=9").json()["month"]

    suggestions(client)

    after = client.get("/api/dashboard?year=2022&month=9").json()["month"]
    assert before == after
    assert Decimal(after["expense"]) == Decimal("500.00")


def test_confirming_files_both_halves_as_transfers_and_out_of_the_totals(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b())
    pair = suggestions(client)["items"][0]

    response = client.post(
        "/api/transfers/confirm",
        json={"out_id": pair["out"]["id"], "in_id": pair["into"]["id"]},
        headers=csrf_header(csrf),
    )
    assert response.status_code == 200
    assert response.json()["category_name"] == "Transfers"

    items = {t["description"]: t for t in client.get("/api/transactions").json()["items"]}
    for name in ("PAYMENT OUT SYNTHETIC", "RECEIVED IN SYNTHETIC"):
        assert items[name]["category_name"] == "Transfers"
        assert items[name]["classification_source"] == "manual"

    month = client.get("/api/dashboard?year=2022&month=9").json()["month"]
    assert Decimal(month["expense"]) == Decimal("0.00")
    assert Decimal(month["income"]) == Decimal("0.00")
    assert Decimal(month["transfers_out"]) == Decimal("500.00")
    assert Decimal(month["transfers_in"]) == Decimal("500.00")
    assert suggestions(client)["total"] == 0


def test_confirming_learns_no_rule_from_the_description(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b())
    rules_before = len(client.get("/api/rules").json())
    pair = suggestions(client)["items"][0]

    client.post(
        "/api/transfers/confirm",
        json={"out_id": pair["out"]["id"], "in_id": pair["into"]["id"]},
        headers=csrf_header(csrf),
    )

    assert len(client.get("/api/rules").json()) == rules_before


def test_a_rejected_pair_is_not_suggested_again(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b())
    pair = suggestions(client)["items"][0]

    response = client.post(
        "/api/transfers/reject",
        json={"out_id": pair["out"]["id"], "in_id": pair["into"]["id"]},
        headers=csrf_header(csrf),
    )
    assert response.status_code == 204
    assert suggestions(client)["total"] == 0
    # rejecting twice is harmless
    again = client.post(
        "/api/transfers/reject",
        json={"out_id": pair["out"]["id"], "in_id": pair["into"]["id"]},
        headers=csrf_header(csrf),
    )
    assert again.status_code == 204


def test_different_amounts_or_dates_too_far_apart_are_not_suggested(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(
        client,
        csrf,
        session_factory,
        test_settings,
        account_a(),
        account_b(amount="499.00"),
    )
    assert suggestions(client)["total"] == 0


def test_a_gap_of_more_than_three_days_is_not_suggested(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b(day="10/09"))
    assert suggestions(client)["total"] == 0


def test_two_halves_in_one_account_are_not_a_transfer(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    pdf = boc_pdf(
        rows=[
            ("05/09", "PAYMENT OUT SYNTHETIC", "500.00", "500.00"),
            ("05/09", "RECEIVED IN SYNTHETIC", "500.00", "1,000.00"),
        ],
        closing="1,000.00",
        account=FAKE_ACCOUNT,
    )
    load(client, csrf, session_factory, test_settings, pdf)
    assert suggestions(client)["total"] == 0


def test_a_category_you_chose_yourself_is_left_alone(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b())
    pair = suggestions(client)["items"][0]
    fuel = {c["name"]: c["id"] for c in client.get("/api/categories").json()}["Fuel"]
    client.put(
        f"/api/transactions/{pair['out']['id']}/category",
        json={"category_id": fuel},
        headers=csrf_header(csrf),
    )
    assert suggestions(client)["total"] == 0


def test_two_candidates_make_the_pair_ambiguous_and_one_to_one(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(
        client,
        csrf,
        session_factory,
        test_settings,
        account_a(),
        account_b(day="06/09", extra="07/09"),
    )
    found = suggestions(client)
    assert found["total"] == 1  # one debit pairs with one credit, never two
    assert found["items"][0]["ambiguous"] is True
    assert found["items"][0]["days_apart"] == 1  # the closer one wins


def test_confirm_refuses_rows_that_are_not_a_pair(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, account_a(), account_b(amount="400.00"))
    ids = [t["id"] for t in client.get("/api/transactions").json()["items"]]

    response = client.post(
        "/api/transfers/confirm",
        json={"out_id": ids[0], "in_id": ids[1]},
        headers=csrf_header(csrf),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "not_a_pair"


def test_pair_key_is_order_independent():
    assert transfers.pair_key("b", "a") == transfers.pair_key("a", "b") == ("a", "b")


# --- coverage ----------------------------------------------------------------------------


def september():
    return boc_pdf(
        rows=[
            ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
            ("05/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
        ],
        closing="3,000.00",
        account=FAKE_ACCOUNT,
    )


def october(opening="3,000.00"):
    value = Decimal(opening.replace(",", ""))
    left = f"{value - Decimal('50.00'):,.2f}"
    return boc_pdf(
        statement_date="31/10/2022",
        opening=("30/09", opening),
        rows=[("05/10", "POS PURCHASE SYNTHETIC", "50.00", left)],
        closing=left,
        account=FAKE_ACCOUNT,
    )


def december():
    return boc_pdf(
        statement_date="31/12/2022",
        opening=("30/11", "3,000.00"),
        rows=[("05/12", "POS PURCHASE SYNTHETIC", "50.00", "2,950.00")],
        closing="2,950.00",
        account=FAKE_ACCOUNT,
    )


def tracker_row(client, year=2022):
    return client.get(f"/api/tracker?year={year}").json()["rows"][0]


def test_statements_that_join_up_have_no_break(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, september(), october())

    assert tracker_row(client)["breaks"] == []
    assert client.get("/api/dashboard?year=2022&month=10").json()["coverage"] == {
        "gap_months": 0,
        "balance_breaks": 0,
    }


def test_a_closing_balance_that_is_not_the_next_opening_is_a_break(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, september(), october(opening="3,100.00"))

    breaks = tracker_row(client)["breaks"]
    assert len(breaks) == 1
    assert breaks[0]["expected"] == "3000.00"
    assert breaks[0]["found"] == "3100.00"
    assert client.get("/api/dashboard?year=2022&month=10").json()["coverage"]["balance_breaks"] == 1


def test_months_between_two_statements_are_reported_missing(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, september(), december())

    row = tracker_row(client)
    assert row["gap_months"] == [10, 11]
    assert row["gap_total"] == 2
    assert row["breaks"] == []  # too far apart to compare balances
    assert client.get("/api/dashboard?year=2022&month=12").json()["coverage"]["gap_months"] == 2


def test_missing_months_are_counted_across_years(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, september(), december())
    assert tracker_row(client, year=2021)["gap_months"] == []  # the gap is in 2022 only


# --- per-bank split ------------------------------------------------------------------------


def two_banks(client, csrf, session_factory, test_settings):
    with session_factory() as db:
        db.add(Bank(code="hnb", name="Hatton National Bank"))
        db.commit()
    boc = boc_pdf(
        statement_date="31/10/2026",
        opening=("30/09", "1,000.00"),
        rows=[("05/10", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00")],
        closing="3,500.00",
    )
    hnb = pdf_from_pages([hnb_lines()])
    run_pipeline(client, csrf, session_factory, test_settings, boc, bank_code="boc")
    run_pipeline(client, csrf, session_factory, test_settings, hnb, bank_code="hnb")


def test_the_cards_split_by_bank_when_all_banks_are_shown(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    two_banks(client, csrf, session_factory, test_settings)

    month = client.get("/api/dashboard?year=2026&month=10").json()
    split = {b["bank_code"]: b for b in month["month_by_bank"]}
    assert set(split) == {"boc", "hnb"}
    assert Decimal(split["boc"]["income"]) == Decimal("2500.00")
    assert Decimal(split["hnb"]["expense"]) == Decimal("100.00")
    # the parts add up to the whole
    assert sum(Decimal(b["income"]) for b in month["month_by_bank"]) == Decimal(month["month"]["income"])
    assert sum(Decimal(b["expense"]) for b in month["month_by_bank"]) == Decimal(month["month"]["expense"])
    assert {b["bank_code"] for b in month["year_by_bank"]} == {"boc", "hnb"}


def test_no_split_when_one_bank_is_selected(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    two_banks(client, csrf, session_factory, test_settings)

    month = client.get("/api/dashboard?year=2026&month=10&bank_code=boc").json()
    assert month["month_by_bank"] == [] and month["year_by_bank"] == []


# --- per-account balance history ------------------------------------------------------------


def test_each_account_has_month_end_balances_and_a_change(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, september(), october())

    balance = client.get("/api/dashboard?year=2022&month=10").json()["balances"][0]
    assert [(p["year"], p["month"], p["balance"]) for p in balance["history"]] == [
        (2022, 9, "3000.00"),
        (2022, 10, "2950.00"),
    ]
    assert balance["change"] == "-50.00"
    assert (balance["change_year"], balance["change_month"]) == (2022, 10)


def test_balance_history_carries_through_a_month_without_transactions(
    logged_in, session_factory, test_settings
):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, september(), december())

    history = client.get("/api/dashboard?year=2022&month=12").json()["balances"][0]["history"]
    assert [(p["month"], p["balance"]) for p in history] == [
        (9, "3000.00"),
        (10, "3000.00"),
        (11, "3000.00"),
        (12, "2950.00"),
    ]


def test_a_single_month_has_no_change(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    load(client, csrf, session_factory, test_settings, september())

    balance = client.get("/api/dashboard?year=2022&month=9").json()["balances"][0]
    assert len(balance["history"]) == 1
    assert balance["change"] is None and balance["change_month"] is None

