"""Rules that also look at the amount and the direction (a credit or a debit)."""

from decimal import Decimal

from app.services import categorizer
from app.services.categorizer import Rule

from .synthetic import FAKE_ACCOUNT, boc_pdf
from .test_extraction import run_pipeline

H = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731
D = Decimal


def rule(**kw):
    base = dict(id=1, pattern="ACME", pattern_type="contains", category_id=1, origin="user", priority=40)
    return Rule(**{**base, **kw})


def test_a_rule_without_conditions_matches_as_before():
    assert categorizer.rule_matches(rule(), "ACME PAYMENT")
    assert categorizer.rule_matches(rule(), "ACME PAYMENT", D("5"), "out")


def test_direction_decides():
    r = rule(direction="in")
    assert categorizer.rule_matches(r, "ACME PAYMENT", D("5"), "in")
    assert not categorizer.rule_matches(r, "ACME PAYMENT", D("5"), "out")
    assert not categorizer.rule_matches(r, "ACME PAYMENT")  # direction unknown: the condition cannot be met


def test_the_amount_range_decides():
    r = rule(min_amount=D("1000"), max_amount=D("5000"))
    for amount, expected in ((D("999.99"), False), (D("1000"), True), (D("5000"), True), (D("5000.01"), False)):
        assert categorizer.rule_matches(r, "ACME", amount, "out") is expected


def test_a_rule_with_conditions_beats_the_plain_one_with_the_same_words():
    plain = rule(id=1, category_id=10)
    large_credit = rule(id=2, category_id=20, direction="in", min_amount=D("50000"))
    ordered = sorted([plain, large_credit], key=lambda r: (-r.priority, -len(r.pattern), -r.conditions, r.id))
    assert categorizer.pick_rule(ordered, "ACME", D("75000"), "in").category_id == 20
    assert categorizer.pick_rule(ordered, "ACME", D("500"), "in").category_id == 10
    assert categorizer.pick_rule(ordered, "ACME", D("75000"), "out").category_id == 10


def test_the_same_words_can_have_two_rules_with_different_conditions(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    ids = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    body = {"pattern": "SYNTHETIC", "category_id": ids["Other income"], "direction": "in"}
    assert client.post("/api/rules", json=body, headers=H(csrf)).status_code == 201
    other = {**body, "category_id": ids["Other expense"], "direction": "out"}
    assert client.post("/api/rules", json=other, headers=H(csrf)).status_code == 201
    assert client.post("/api/rules", json=body, headers=H(csrf)).status_code == 409  # exactly the same rule again


def test_a_rule_by_direction_sorts_a_real_statement(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(
        client,
        csrf,
        session_factory,
        test_settings,
        boc_pdf(
            rows=[
                ("02/09", "MIXED PAYMENT SYNTHETIC", "2,500.00", "3,500.00"),  # a credit
                ("05/09", "MIXED PAYMENT SYNTHETIC", "500.00", "3,000.00"),  # a debit
            ],
            closing="3,000.00",
            account=FAKE_ACCOUNT,
        ),
    )
    ids = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    for direction, category in (("in", "Other income"), ("out", "Other expense")):
        r = client.post(
            "/api/rules",
            json={"pattern": "MIXED PAYMENT", "category_id": ids[category], "direction": direction},
            headers=H(csrf),
        )
        assert r.status_code == 201
    rows = {t["credit"]: t["category_id"] for t in client.get("/api/transactions?limit=50").json()["items"]}
    assert rows["2500.00"] == ids["Other income"]
    assert rows["0.00"] == ids["Other expense"]


def test_a_backwards_range_is_refused(logged_in):
    client, csrf = logged_in
    ids = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    r = client.post(
        "/api/rules",
        json={"pattern": "ACME", "category_id": ids["Other income"], "min_amount": "500", "max_amount": "100"},
        headers=H(csrf),
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "amount_range"
