"""Renaming categories, sub-categories and re-running the rules."""

H = lambda csrf: {"X-CSRF-Token": csrf}  # noqa: E731


def make(client, csrf, name, kind="expense", parent_id=None):
    return client.post("/api/categories", json={"name": name, "kind": kind, "parent_id": parent_id}, headers=H(csrf))


def by_name(client):
    return {c["name"]: c for c in client.get("/api/categories").json()}


def test_a_category_you_made_can_be_renamed(logged_in):
    client, csrf = logged_in
    made = make(client, csrf, "Pets").json()
    r = client.patch(f"/api/categories/{made['id']}", json={"name": "Pet care"}, headers=H(csrf))
    assert r.status_code == 200 and r.json()["name"] == "Pet care"
    assert "Pet care" in by_name(client) and "Pets" not in by_name(client)


def test_a_built_in_category_keeps_its_name(logged_in):
    client, csrf = logged_in
    interest = by_name(client)["Interest income"]["id"]
    r = client.patch(f"/api/categories/{interest}", json={"name": "Savings interest"}, headers=H(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "system_category"


def test_a_name_already_taken_is_refused(logged_in):
    client, csrf = logged_in
    a, b = make(client, csrf, "Gifts").json(), make(client, csrf, "Charity").json()
    r = client.patch(f"/api/categories/{b['id']}", json={"name": "Gifts"}, headers=H(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_category"
    assert a["id"] != b["id"]


def test_a_sub_category_sits_under_a_parent_of_the_same_kind(logged_in):
    client, csrf = logged_in
    food = by_name(client)["Food and dining"]["id"]
    child = make(client, csrf, "Groceries", parent_id=food)
    assert child.status_code == 201 and child.json()["full_name"] == "Food and dining › Groceries"
    assert by_name(client)["Groceries"]["parent_id"] == food

    wrong_kind = make(client, csrf, "Side income", kind="income", parent_id=food)
    assert wrong_kind.status_code == 422 and wrong_kind.json()["detail"]["code"] == "parent_kind"


def test_only_one_level_is_allowed(logged_in):
    client, csrf = logged_in
    food = by_name(client)["Food and dining"]["id"]
    child = make(client, csrf, "Groceries", parent_id=food).json()
    grandchild = make(client, csrf, "Vegetables", parent_id=child["id"])
    assert grandchild.status_code == 422 and grandchild.json()["detail"]["code"] == "parent_is_sub"

    other = make(client, csrf, "Pets").json()
    r = client.patch(f"/api/categories/{food}", json={"set_parent": True, "parent_id": other["id"]}, headers=H(csrf))
    assert r.status_code == 409  # built-in: cannot be moved
    # a category that has children cannot become a child itself
    parent = make(client, csrf, "Travel").json()
    make(client, csrf, "Flights", parent_id=parent["id"])
    r = client.patch(f"/api/categories/{parent['id']}", json={"set_parent": True, "parent_id": other["id"]}, headers=H(csrf))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "has_children"


def test_a_category_can_be_moved_out_again_and_a_parent_with_children_cannot_be_deleted(logged_in):
    client, csrf = logged_in
    parent = make(client, csrf, "Travel").json()
    child = make(client, csrf, "Flights", parent_id=parent["id"]).json()
    assert client.delete(f"/api/categories/{parent['id']}", headers=H(csrf)).status_code == 409
    moved = client.patch(f"/api/categories/{child['id']}", json={"set_parent": True, "parent_id": None}, headers=H(csrf))
    assert moved.json()["parent_id"] is None and moved.json()["full_name"] == "Flights"
    assert client.delete(f"/api/categories/{parent['id']}", headers=H(csrf)).status_code == 204


def test_reclassify_endpoint_still_reports_how_many_changed(logged_in):
    client, csrf = logged_in
    r = client.post("/api/categorization/reclassify", headers=H(csrf))
    assert r.status_code == 200 and r.json() == {"changed": 0}
