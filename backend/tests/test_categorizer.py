"""Rule matching, learning from corrections, review queue and category/rule management.
All statements are synthetic."""

from decimal import Decimal

import pytest

from app.services.categorizer import (
    CATEGORIES,
    RULES,
    Rule,
    description_stem,
    normalise,
    pick_rule,
)

from .synthetic import boc_pdf
from .test_extraction import run_pipeline

HEADERS = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731


# --- pure rule logic -------------------------------------------------------------------------


def default_rules() -> tuple[list[Rule], dict[int, str]]:
    ids = {name: index + 1 for index, (name, _) in enumerate(CATEGORIES)}
    rules = [
        Rule(index + 1, pattern.upper(), ptype, ids[name], "system", priority)
        for index, (pattern, ptype, name, priority) in enumerate(RULES)
    ]
    rules.sort(key=lambda r: (-r.priority, -len(r.pattern), r.id))
    return rules, {v: k for k, v in ids.items()}


@pytest.mark.parametrize(
    "description, expected",
    [
        ("INTEREST PAY SYS-GEN", "Interest income"),
        ("INTEREST WITHHELD", "Tax"),  # more specific than "interest"
        ("ATM SERVICE CHARGE", "Bank charges"),
        ("ATMCASHWDLSYNTHETIC TOWN BR.", "Cash withdrawal"),  # no spaces, as printed
        ("WD ATM SAV ICBS", "Cash withdrawal"),
        ("LOAN RECO 12345678", "Loan repayment"),
        ("SLIPS IN - NOV2022", "Deposits"),
        ("DEP TO SAV ICBS", "Transfers"),
        ("BOOKED SAVINGS W/D", "Transfers"),
        ("CEFT TO SOMEONE", "Transfers"),
        ("SALARY JAN", "Salary"),
        ("POS PURCHASE SYNTHETIC SHOP", "Card payment"),
        ("CEB BILL PAYMENT", "Utilities"),
        ("SMS ALERT MONTHLY FEE", "Bank charges"),
        ("CRIB CHARGES", "Bank charges"),
    ],
)
def test_built_in_rules(description, expected):
    rules, names = default_rules()
    rule = pick_rule(rules, normalise(description))
    assert rule is not None and names[rule.category_id] == expected


@pytest.mark.parametrize("description", ["MYSTERY MERCHANT", "0721600897", "FACEBOOK ADS", "SALTY SNACKS"])
def test_unknown_descriptions_match_nothing(description):
    rules, _ = default_rules()
    # "FACEBOOK" contains CEB and "SALTY" contains SLT: whole-word rules must not match them
    assert pick_rule(rules, normalise(description)) is None


def test_a_longer_pattern_wins_a_tie():
    longer = Rule(1, "ATM SERVICE CHARGE", "contains", 10, "system", 20)
    shorter = Rule(2, "ATM", "contains", 20, "system", 20)
    ordered = sorted([shorter, longer], key=lambda r: (-r.priority, -len(r.pattern), r.id))
    assert pick_rule(ordered, "ATM SERVICE CHARGE").category_id == 10


def test_normalise_and_stem():
    assert normalise("  atm   service\tcharge ") == "ATM SERVICE CHARGE"
    assert description_stem("LOAN RECO 85238526") == "LOAN RECO"
    assert description_stem("SLIPS IN - NOV2022") == "SLIPS IN"
    # A trailing branch marker says where, not what.
    assert description_stem("ATMCASHWDLJAFFNA CITY BR.") == "ATMCASHWDLJAFFNA CITY"
    assert description_stem("0721600897") == "0721600897"  # nothing reusable: keep it whole
    assert description_stem("A B C D E F") == "A B C D"  # at most four words


# --- through the whole pipeline ------------------------------------------------------------------

STATEMENT_ROWS = [
    ("02/09", "SALARY CREDIT SYNTHETIC", "2,500.00", "3,500.00"),
    ("03/09", "ATM CASH WITHDRAWAL", "500.00", "3,000.00"),
    ("04/09", "BOOKED SAVINGS W/D", "1,000.00", "4,000.00"),  # transfer in
    ("05/09", "DEP TO SAV ICBS", "700.00", "3,300.00"),  # transfer out
    ("06/09", "MYSTERY MERCHANT 111", "100.00", "3,200.00"),
    ("07/09", "MYSTERY MERCHANT 222", "50.00", "3,150.00"),
    ("08/09", "UNKNOWN REFUND", "300.00", "3,450.00"),  # uncategorised credit
]


def statement(**kwargs):
    return boc_pdf(rows=STATEMENT_ROWS, closing="3,450.00", **kwargs)


def items(client, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/api/transactions?limit=500&{query}").json()["items"]


def by_description(client):
    return {t["description"]: t for t in items(client)}


def categories(client):
    return {c["name"]: c for c in client.get("/api/categories").json()}


def run(logged_in, session_factory, test_settings, pdf=None):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, pdf or statement())
    return client, csrf


def test_new_statements_are_categorised_on_extraction(logged_in, session_factory, test_settings):
    client, _ = run(logged_in, session_factory, test_settings)
    rows = by_description(client)

    salary = rows["SALARY CREDIT SYNTHETIC"]
    assert (salary["category_name"], salary["category_kind"]) == ("Salary", "income")
    assert salary["classification_source"] == "rule"
    assert salary["classification_explanation"] == "Rule: contains 'SALARY'"
    assert rows["ATM CASH WITHDRAWAL"]["category_name"] == "Cash withdrawal"
    assert rows["BOOKED SAVINGS W/D"]["category_kind"] == "transfer"

    mystery = rows["MYSTERY MERCHANT 111"]
    assert mystery["category_id"] is None
    assert mystery["classification_source"] is None


def test_defaults_are_created_once(logged_in, session_factory, test_settings):
    client, _ = run(logged_in, session_factory, test_settings)
    first = client.get("/api/categories").json()
    second = client.get("/api/categories").json()
    assert len(first) == len(second) == len(CATEGORIES)
    assert all(c["is_system"] for c in first)
    assert len(client.get("/api/rules").json()) == len(RULES)


def test_transfers_are_left_out_of_income_and_expense(logged_in, session_factory, test_settings):
    client, _ = run(logged_in, session_factory, test_settings)
    month = client.get("/api/dashboard?year=2022&month=9").json()["month"]

    # income: salary 2,500 + the uncategorised credit 300 (counted by direction)
    assert Decimal(month["income"]) == Decimal("2800.00")
    # expense: 500 cash + 100 + 50 uncategorised debits
    assert Decimal(month["expense"]) == Decimal("650.00")
    assert Decimal(month["transfers_in"]) == Decimal("1000.00")
    assert Decimal(month["transfers_out"]) == Decimal("700.00")
    assert Decimal(month["net"]) == Decimal("2150.00")
    assert month["uncategorised"] == 3
    assert month["transactions"] == 7


def test_dashboard_breaks_spending_down_by_category(logged_in, session_factory, test_settings):
    client, _ = run(logged_in, session_factory, test_settings)
    breakdown = {c["name"]: c for c in client.get("/api/dashboard?year=2022&month=9").json()["month_by_category"]}

    assert Decimal(breakdown["Cash withdrawal"]["expense"]) == Decimal("500.00")
    assert Decimal(breakdown["Salary"]["income"]) == Decimal("2500.00")
    assert breakdown["Uncategorised"]["category_id"] is None
    assert breakdown["Uncategorised"]["transactions"] == 3
    assert breakdown["Transfers"]["kind"] == "transfer"


def test_explorer_filters_by_category(logged_in, session_factory, test_settings):
    client, _ = run(logged_in, session_factory, test_settings)
    cash = categories(client)["Cash withdrawal"]["id"]

    assert [t["description"] for t in items(client, category_id=cash)] == ["ATM CASH WITHDRAWAL"]
    assert len(items(client, uncategorised="true")) == 3


# --- correcting a transaction ------------------------------------------------------------------------


def test_correcting_one_transaction_sticks_and_offers_to_learn(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    shopping = categories(client)["Shopping"]["id"]
    target = by_description(client)["MYSTERY MERCHANT 111"]

    response = client.put(
        f"/api/transactions/{target['id']}/category", json={"category_id": shopping}, headers=HEADERS(csrf)
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["category_name"], body["stem"], body["similar_count"]) == ("Shopping", "MYSTERY MERCHANT", 1)
    assert body["rule_id"] is None  # nothing learned yet

    rows = by_description(client)
    assert rows["MYSTERY MERCHANT 111"]["classification_source"] == "manual"
    assert rows["MYSTERY MERCHANT 222"]["category_id"] is None  # the sibling is untouched


def test_preview_reports_similar_rows_without_changing_anything(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    shopping = categories(client)["Shopping"]["id"]
    target = by_description(client)["MYSTERY MERCHANT 111"]
    before = target["category_id"], target["classification_source"]

    body = client.put(
        f"/api/transactions/{target['id']}/category",
        json={"category_id": shopping, "preview": True},
        headers=HEADERS(csrf),
    ).json()
    assert (body["category_name"], body["similar_count"], body["changed"]) == ("Shopping", 1, 0)

    after = by_description(client)["MYSTERY MERCHANT 111"]
    assert (after["category_id"], after["classification_source"]) == before


def test_learning_a_rule_applies_it_to_similar_rows_and_future_statements(
    logged_in, session_factory, test_settings
):
    client, csrf = run(logged_in, session_factory, test_settings)
    shopping = categories(client)["Shopping"]["id"]
    target = by_description(client)["MYSTERY MERCHANT 111"]

    body = client.put(
        f"/api/transactions/{target['id']}/category",
        json={"category_id": shopping, "create_rule": True},
        headers=HEADERS(csrf),
    ).json()
    assert body["rule_id"] is not None and body["changed"] == 1

    rows = by_description(client)
    assert rows["MYSTERY MERCHANT 222"]["category_name"] == "Shopping"
    assert rows["MYSTERY MERCHANT 222"]["classification_source"] == "user_rule"

    rule = next(r for r in client.get("/api/rules").json() if r["id"] == body["rule_id"])
    assert (rule["pattern"], rule["origin"], rule["category_name"]) == ("MYSTERY MERCHANT", "correction", "Shopping")

    # a later statement benefits straight away
    run_pipeline(
        client, csrf, session_factory, test_settings,
        boc_pdf(
            statement_date="31/10/2022",
            opening=("30/09", "3,450.00"),
            rows=[("05/10", "MYSTERY MERCHANT 999", "10.00", "3,440.00")],
            closing="3,440.00",
        ),
    )  # fmt: skip
    assert by_description(client)["MYSTERY MERCHANT 999"]["category_name"] == "Shopping"


def test_your_correction_beats_a_built_in_rule(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    food = categories(client)["Food and dining"]["id"]
    atm = by_description(client)["ATM CASH WITHDRAWAL"]

    client.put(
        f"/api/transactions/{atm['id']}/category",
        json={"category_id": food, "create_rule": True},
        headers=HEADERS(csrf),
    )
    assert by_description(client)["ATM CASH WITHDRAWAL"]["category_name"] == "Food and dining"


def test_a_manual_choice_is_never_overwritten(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    cats = categories(client)
    tx = by_description(client)["MYSTERY MERCHANT 111"]
    client.put(
        f"/api/transactions/{tx['id']}/category", json={"category_id": cats["Fuel"]["id"]}, headers=HEADERS(csrf)
    )

    # a rule that matches it, and a full re-run, must both leave it alone
    client.post(
        "/api/rules",
        json={"pattern": "MYSTERY MERCHANT", "category_id": cats["Shopping"]["id"]},
        headers=HEADERS(csrf),
    )
    client.post("/api/categorization/reclassify", headers=HEADERS(csrf))

    rows = by_description(client)
    assert rows["MYSTERY MERCHANT 111"]["category_name"] == "Fuel"  # yours
    assert rows["MYSTERY MERCHANT 222"]["category_name"] == "Shopping"  # the rule's


def test_clearing_a_category(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    atm = by_description(client)["ATM CASH WITHDRAWAL"]
    client.put(f"/api/transactions/{atm['id']}/category", json={"category_id": None}, headers=HEADERS(csrf))

    row = by_description(client)["ATM CASH WITHDRAWAL"]
    assert row["category_id"] is None and row["classification_source"] == "manual"


def test_correction_validation(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    tx = by_description(client)["MYSTERY MERCHANT 111"]
    url = f"/api/transactions/{tx['id']}/category"

    assert client.put(url, json={"category_id": 99999}, headers=HEADERS(csrf)).status_code == 404
    assert client.put(url, json={"category_id": None, "create_rule": True}, headers=HEADERS(csrf)).status_code == 422
    assert client.put("/api/transactions/99999/category", json={"category_id": None}, headers=HEADERS(csrf)).status_code == 404
    assert client.put(url, json={"category_id": None}).status_code == 403  # CSRF


# --- review queue ----------------------------------------------------------------------------------------


def test_review_queue_groups_similar_descriptions(logged_in, session_factory, test_settings):
    client, _ = run(logged_in, session_factory, test_settings)
    queue = client.get("/api/categorization/review").json()

    assert queue["total"] == 3
    groups = {g["stem"]: g["count"] for g in queue["groups"]}
    assert groups == {"MYSTERY MERCHANT": 2, "UNKNOWN REFUND": 1}
    assert queue["groups"][0]["stem"] == "MYSTERY MERCHANT"  # biggest first


def test_applying_to_a_group_categorises_it_and_remembers(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    shopping = categories(client)["Shopping"]["id"]

    body = client.post(
        "/api/categorization/apply",
        json={"stem": "mystery merchant", "category_id": shopping},
        headers=HEADERS(csrf),
    ).json()
    assert body["changed"] == 2

    queue = client.get("/api/categorization/review").json()
    assert [g["stem"] for g in queue["groups"]] == ["UNKNOWN REFUND"]
    assert any(r["pattern"] == "MYSTERY MERCHANT" and r["origin"] == "correction" for r in client.get("/api/rules").json())


def test_duplicates_do_not_inflate_the_review_queue(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    run_pipeline(  # the same seven rows again, inside a longer statement (same account: none)
        client, csrf, session_factory, test_settings,
        boc_pdf(
            statement_date="31/10/2022",
            opening=("30/08", "1,000.00"),
            rows=STATEMENT_ROWS + [("05/10", "ATM SERVICE CHARGE", "5.00", "3,445.00")],
            closing="3,445.00",
        ),
    )  # fmt: skip
    assert len(items(client, duplicates="only")) == 7  # confirms they really are duplicates
    assert client.get("/api/categorization/review").json()["total"] == 3


# --- managing categories and rules -------------------------------------------------------------------------


def test_custom_categories(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    h = HEADERS(csrf)

    created = client.post("/api/categories", json={"name": "Pets", "kind": "expense"}, headers=h)
    assert created.status_code == 201 and created.json()["is_system"] is False
    assert client.post("/api/categories", json={"name": "Pets", "kind": "expense"}, headers=h).status_code == 409
    assert client.post("/api/categories", json={"name": "X", "kind": "bogus"}, headers=h).status_code == 422

    pets = created.json()["id"]
    assert client.delete(f"/api/categories/{pets}", headers=h).status_code == 204  # unused

    # a built-in one cannot go, and neither can one that is in use
    system = categories(client)["Salary"]["id"]
    assert client.delete(f"/api/categories/{system}", headers=h).status_code == 409
    custom = client.post("/api/categories", json={"name": "Hobbies", "kind": "expense"}, headers=h).json()["id"]
    tx = by_description(client)["MYSTERY MERCHANT 111"]
    client.put(f"/api/transactions/{tx['id']}/category", json={"category_id": custom}, headers=h)
    in_use = client.delete(f"/api/categories/{custom}", headers=h)
    assert in_use.status_code == 409 and in_use.json()["detail"]["code"] == "in_use"


def test_creating_a_rule_applies_it_to_existing_rows(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    shopping = categories(client)["Shopping"]["id"]

    created = client.post(
        "/api/rules",
        json={"pattern": "unknown refund", "category_id": shopping},
        headers=HEADERS(csrf),
    )
    assert created.status_code == 201
    assert created.json()["pattern"] == "UNKNOWN REFUND"  # normalised
    assert created.json()["changed"] == 1
    assert by_description(client)["UNKNOWN REFUND"]["category_name"] == "Shopping"

    again = client.post("/api/rules", json={"pattern": "UNKNOWN REFUND", "category_id": shopping}, headers=HEADERS(csrf))
    assert again.status_code == 409


def test_built_in_rules_can_be_turned_off_but_not_deleted(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    h = HEADERS(csrf)
    # "SALARY" is the only rule that matches this description (the ATM rules overlap)
    rule = next(r for r in client.get("/api/rules").json() if r["pattern"] == "SALARY")

    assert client.delete(f"/api/rules/{rule['id']}", headers=h).status_code == 409
    off = client.patch(f"/api/rules/{rule['id']}", json={"enabled": False}, headers=h)
    assert off.json()["changed"] == 1
    assert by_description(client)["SALARY CREDIT SYNTHETIC"]["category_id"] is None

    client.patch(f"/api/rules/{rule['id']}", json={"enabled": True}, headers=h)
    assert by_description(client)["SALARY CREDIT SYNTHETIC"]["category_name"] == "Salary"


def test_deleting_your_rule_uncategorises_what_it_covered(logged_in, session_factory, test_settings):
    client, csrf = run(logged_in, session_factory, test_settings)
    h = HEADERS(csrf)
    shopping = categories(client)["Shopping"]["id"]
    rule = client.post("/api/rules", json={"pattern": "UNKNOWN REFUND", "category_id": shopping}, headers=h).json()

    assert client.delete(f"/api/rules/{rule['id']}", headers=h).status_code == 204
    assert by_description(client)["UNKNOWN REFUND"]["category_id"] is None


def test_rule_hit_counts_grow_as_rules_apply(logged_in, session_factory, test_settings):
    client, _ = run(logged_in, session_factory, test_settings)
    rule = next(r for r in client.get("/api/rules").json() if r["pattern"] == "SALARY")
    assert rule["hit_count"] == 1


def test_category_endpoints_need_login(client):
    for path in ("/api/categories", "/api/rules", "/api/categorization/review", "/api/categorization/status"):
        assert client.get(path).status_code == 401


def test_backfill_categorises_rows_saved_before_categories_existed(logged_in, session_factory, test_settings):
    from sqlalchemy import update

    from app.models import Transaction
    from app.services.categorizer import classify_all_users

    client, _ = run(logged_in, session_factory, test_settings)
    with session_factory() as db:  # simulate rows from before this feature
        db.execute(update(Transaction).values(category_id=None, classification_source=None,
                                              classification_confidence=None, classification_explanation=None))
        db.commit()
    assert by_description(client)["SALARY CREDIT SYNTHETIC"]["category_id"] is None

    with session_factory() as db:
        assert classify_all_users(db) == 4  # salary, ATM and the two transfers
    assert by_description(client)["SALARY CREDIT SYNTHETIC"]["category_name"] == "Salary"

    with session_factory() as db:
        assert classify_all_users(db) == 0  # running it again changes nothing
