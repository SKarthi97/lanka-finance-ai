"""Month summary (4.4) and flagged-transaction explanations (4.5). All data synthetic; the local
model is a fake Ollama."""

import pytest

from app.models import Transaction
from app.services import flags as flag_service
from app.services import llm_guard, summary

from .synthetic import FAKE_ACCOUNT, boc_pdf
from .test_ai_features import fake_ollama
from .test_extraction import run_pipeline
from .test_overview_api import october, september

H = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731


# --- the guard ------------------------------------------------------------------------------------


def test_numbers_must_come_from_the_facts():
    facts = "Spending compared with September: down 90%\nKept 22% of income"
    assert llm_guard.only_given_numbers("Spending is down 90% and you kept 22%.", facts)
    assert not llm_guard.only_given_numbers("Spending is down 95%.", facts)
    assert llm_guard.only_given_numbers("A calm month.", facts)  # no numbers is fine


@pytest.mark.parametrize("text", ["You spent LKR 500.", "About Rs. 40 more", "It cost $5", "100 rupees"])
def test_money_is_never_allowed(text):
    assert llm_guard.mentions_money(text)
    assert llm_guard.clean(text, "100 5 500 40", 200) is None


def test_clean_tidies_and_rejects_markup_and_length():
    assert llm_guard.clean("  Two   words\n here ", "", 50) == "Two words here"
    assert llm_guard.clean("x" * 60, "", 50) is None
    assert llm_guard.clean("{placeholder}", "", 50) is None
    assert llm_guard.clean("", "", 50) is None and llm_guard.clean(None, "", 50) is None


# --- 4.4 the facts and the plain summary ----------------------------------------------------------------


@pytest.fixture()
def two_months(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    run_pipeline(client, csrf, session_factory, test_settings, october())
    return client, csrf


def ask(client, csrf, year=2022, month=10, ai=False):
    return client.post("/api/summary", json={"year": year, "month": month, "ai": ai}, headers=H(csrf)).json()


def test_the_plain_summary_has_the_real_figures(two_months):
    client, csrf = two_months
    out = ask(client, csrf)
    text = " ".join(out["bullets"])
    assert out["label"] == "October 2022"
    assert "Income LKR 0.00, spending LKR 50.00" in text and "overspent" in text
    assert "Spending is down 90% on September 2022." in text
    assert "Income is down 100% on September 2022." in text
    assert out["narrative"] is None and out["used_ai"] is False


def test_september_has_nothing_to_compare_with_and_says_it_kept_income(two_months):
    client, csrf = two_months
    text = " ".join(ask(client, csrf, month=9)["bullets"])
    assert "on August" not in text  # no earlier month to compare
    assert "You kept 80% of your income." in text  # 2,500 in, 500 out
    assert "Income LKR 2,500.00, spending LKR 500.00, net LKR 2,000.00 saved." in text


def test_an_empty_month_says_so_and_does_not_call_the_model(logged_in, test_settings):
    client, csrf = logged_in
    test_settings.llm_classify_enabled = True
    out = ask(client, csrf, month=1, ai=True)
    assert out["bullets"] == ["No transactions in January 2022."] and out["narrative"] is None


def test_budgets_and_the_biggest_rise_appear(two_months):
    client, csrf = two_months
    cats = {c["name"]: c["id"] for c in client.get("/api/categories").json()}
    items = {t["description"]: t for t in client.get("/api/transactions?limit=50").json()["items"]}
    pos = items["POS PURCHASE SYNTHETIC"]["id"]
    client.put(f"/api/transactions/{pos}/category", json={"category_id": cats["Fuel"]}, headers=H(csrf))
    client.put(f"/api/budgets/{cats['Fuel']}", json={"amount": "20.00"}, headers=H(csrf))

    text = " ".join(ask(client, csrf)["bullets"])
    assert "Over budget: Fuel." in text
    assert "Fuel rose the most (new this month)." in text


# --- 4.4 the model's paragraph -----------------------------------------------------------------------------


def narrate(session_factory, settings, reply, seen):
    settings.llm_classify_enabled = True
    with session_factory() as db:
        facts = summary.compute_facts(db, 1, 2022, 10)
        result = summary.narrate(db, settings, facts, fake_ollama([reply], seen))
        db.commit()
    return result


def test_a_good_paragraph_is_kept(two_months, session_factory, test_settings):
    paragraph, model_ms, note = narrate(
        session_factory, test_settings,
        {"summary": "A quiet month: spending is down 90% on September and income is down 100%."}, [],
    )  # fmt: skip
    assert paragraph.startswith("A quiet month") and note is None and model_ms is not None


def test_an_invented_number_drops_the_paragraph(two_months, session_factory, test_settings):
    paragraph, _, note = narrate(session_factory, test_settings, {"summary": "Spending is down 95%."}, [])
    assert paragraph is None and "figure it was not given" in note


def test_an_amount_drops_the_paragraph(two_months, session_factory, test_settings):
    paragraph, _, _ = narrate(session_factory, test_settings, {"summary": "You spent LKR 50 this month."}, [])
    assert paragraph is None


def test_the_model_never_sees_an_amount(two_months, session_factory, test_settings):
    seen: list = []
    narrate(session_factory, test_settings, {"summary": "Calm."}, seen)
    prompt = seen[0]["prompt"]
    for secret in ("2,500", "2500", "500.00", "50.00", "3,000", "LKR"):
        assert secret not in prompt
    assert "down 90%" in prompt  # percentages and names are what it gets
    assert seen[0]["format"]["required"] == ["summary"] and seen[0]["think"] is False


def test_an_unusable_reply_leaves_just_the_plain_summary(two_months, session_factory, test_settings):
    test_settings.llm_classify_enabled = True
    with session_factory() as db:
        facts = summary.compute_facts(db, 1, 2022, 10)
        paragraph, _, note = summary.narrate(db, test_settings, facts, fake_ollama(["not json", "not json"], []))
    assert paragraph is None and "usable" in note


def test_the_ai_is_skipped_when_turned_off(two_months):
    client, csrf = two_months  # the test settings turn the AI off
    out = ask(client, csrf, ai=True)
    assert out["narrative"] is None and out["ai_note"] is None and out["model_ms"] is None


# --- 4.5 flags ----------------------------------------------------------------------------------------------


def fuel_statement():
    """Six 100 payments and one 900, all later filed as Fuel."""
    names = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF"]
    rows, balance = [], 5000
    for i, name in enumerate(names):
        amount = 900 if name == "GOLF" else 100
        balance -= amount
        rows.append((f"0{i + 2}/09", f"FUEL STOP {name}", f"{amount:.2f}", f"{balance:,.2f}"))
    return boc_pdf(opening=("30/08", "5,000.00"), rows=rows, closing=f"{balance:,.2f}", account=FAKE_ACCOUNT)


@pytest.fixture()
def fuel(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, fuel_statement())
    fuel_id = {c["name"]: c["id"] for c in client.get("/api/categories").json()}["Fuel"]
    items = {t["description"]: t for t in client.get("/api/transactions?limit=50").json()["items"]}
    for item in items.values():
        client.put(f"/api/transactions/{item['id']}/category", json={"category_id": fuel_id}, headers=H(csrf))
    return client, csrf, items


def codes(client, transaction_id):
    return [f["code"] for f in client.get(f"/api/transactions/{transaction_id}/flags").json()["flags"]]


def test_a_payment_far_above_the_usual_for_its_category_is_flagged(fuel):
    client, _, items = fuel
    found = client.get(f"/api/transactions/{items['FUEL STOP GOLF']['id']}/flags").json()["flags"]
    assert [f["code"] for f in found] == ["large_for_category"]
    assert found[0]["title"] == "The amount is about 9 times the usual for Fuel."
    assert codes(client, items["FUEL STOP ALPHA"]["id"]) == []  # an ordinary one


def test_the_reasons_never_hold_amounts_or_descriptions(fuel):
    client, _, items = fuel
    title = client.get(f"/api/transactions/{items['FUEL STOP GOLF']['id']}/flags").json()["flags"][0]["title"]
    assert "900" not in title and "GOLF" not in title


def test_two_identical_charges_in_a_day_look_like_a_double_charge(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    rows = [("05/09", "COFFEE HOUSE SYNTHETIC", "40.00", "960.00"), ("05/09", "COFFEE HOUSE SYNTHETIC", "40.00", "920.00")]
    run_pipeline(client, csrf, session_factory, test_settings, boc_pdf(rows=rows, closing="920.00"))
    for item in client.get("/api/transactions").json()["items"]:
        assert "possible_double_charge" in codes(client, item["id"])


def test_a_row_the_statement_check_doubted_is_flagged_with_its_statement(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    bad = boc_pdf(rows=[("05/09", "ATM CASH WITHDRAWAL", "500.00", "600.00")], closing="600.00")
    run_pipeline(client, csrf, session_factory, test_settings, bad)
    item = client.get("/api/transactions").json()["items"][0]
    found = codes(client, item["id"])
    assert "statement_not_reconciled" in found and len(found) >= 2


def test_flags_belong_to_you(fuel):
    client, _, _ = fuel
    assert client.get("/api/transactions/99999/flags").status_code == 404


# --- 4.5 the explanation -------------------------------------------------------------------------------------


def explain_with(session_factory, settings, reply, seen, description="FUEL STOP GOLF"):
    settings.llm_classify_enabled = True
    with session_factory() as db:
        t = db.query(Transaction).filter(Transaction.original_description == description).one()
        found = flag_service.flags_for(db, 1, t)
        result = flag_service.explain(db, settings, t, found, "Fuel", fake_ollama([reply], seen))
        db.commit()
    return result


def test_the_ai_explains_the_reasons_in_plain_words(fuel, session_factory, test_settings):
    reply = {
        "explanation": "This payment is about 9 times what you normally spend on fuel, which may be a mistake or a one-off.",
        "check": "Look at the receipt and the date.",
    }
    seen: list = []
    explanation, model_ms, note = explain_with(session_factory, test_settings, reply, seen)
    assert explanation.explanation.startswith("This payment is about 9 times") and note is None
    assert explanation.check == "Look at the receipt and the date."

    prompt = seen[0]["prompt"]
    assert "about 9 times the usual for Fuel" in prompt
    for private in ("GOLF", "FUEL STOP", "900", "5,000", "2022"):  # no description, amount, date
        assert private not in prompt


def test_an_invented_figure_drops_the_explanation(fuel, session_factory, test_settings):
    reply = {"explanation": "This is 20 times the usual amount.", "check": "Check it."}
    explanation, _, note = explain_with(session_factory, test_settings, reply, [])
    assert explanation is None and "figure it was not given" in note


def test_the_endpoint_returns_the_reasons_even_without_the_ai(fuel):
    client, csrf, items = fuel
    out = client.post(f"/api/transactions/{items['FUEL STOP GOLF']['id']}/explain", headers=H(csrf)).json()
    assert out["used_ai"] is False and out["explanation"] is None  # the test settings turn the AI off
    assert out["flags"][0]["code"] == "large_for_category" and out["ai_note"] is None


def test_there_is_nothing_to_explain_for_an_ordinary_transaction(fuel):
    client, csrf, items = fuel
    response = client.post(f"/api/transactions/{items['FUEL STOP ALPHA']['id']}/explain", headers=H(csrf))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "nothing_flagged"
