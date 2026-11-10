from .synthetic import FAKE_ACCOUNT, boc_pdf  # noqa: F401
from .test_extraction import run_pipeline
from .test_planning import category_ids, september

H = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731


def test_a_transaction_remembers_where_it_came_from_and_what_you_changed(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    row = next(t for t in client.get("/api/transactions?limit=50").json()["items"] if t["description"] == "ATM CASH WITHDRAWAL")
    fuel = category_ids(client)["Fuel"]

    client.put(f"/api/transactions/{row['id']}/category", json={"category_id": fuel}, headers=H(csrf))
    client.put(f"/api/transactions/{row['id']}/merchant", json={"name": "Cash machine"}, headers=H(csrf))

    body = client.get(f"/api/transactions/{row['id']}/history").json()
    texts = [e["text"] for e in body["events"]]
    assert any("Added from" in t for t in texts)
    assert any("changed the category" in t and "Fuel" in t for t in texts)
    assert any("Cash machine" in t for t in texts)
    assert body["current"].startswith("Category: Fuel, set by you")


def test_history_of_someone_elses_transaction_is_not_found(logged_in):
    client, _ = logged_in
    assert client.get("/api/transactions/999999/history").status_code == 404
