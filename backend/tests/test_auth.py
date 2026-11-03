from app.deps import login_limiter

from .conftest import PASSWORD


def test_status_requires_setup_on_empty_db(client):
    body = client.get("/api/auth/status").json()
    assert body == {"setup_required": True, "authenticated": False}


def test_setup_creates_user_and_session_cookie(client):
    response = client.post(
        "/api/auth/setup", json={"username": "owner", "password": PASSWORD}
    )
    assert response.status_code == 201
    assert "csrf_token" in response.json()

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie

    assert client.get("/api/auth/status").json() == {
        "setup_required": False,
        "authenticated": True,
    }


def test_setup_rejects_short_password(client):
    response = client.post(
        "/api/auth/setup", json={"username": "owner", "password": "short"}
    )
    assert response.status_code == 422


def test_setup_only_allowed_once(logged_in):
    client, _ = logged_in
    response = client.post(
        "/api/auth/setup", json={"username": "other", "password": PASSWORD}
    )
    assert response.status_code == 409


def test_login_wrong_password_and_unknown_user_look_identical(logged_in):
    client, _ = logged_in
    client.cookies.clear()

    wrong = client.post("/api/auth/login", json={"username": "owner", "password": "nope"})
    unknown = client.post("/api/auth/login", json={"username": "ghost", "password": "nope"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_success_after_logout(logged_in):
    client, csrf = logged_in
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    response = client.post(
        "/api/auth/login", json={"username": "owner", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert client.get("/api/auth/me").json()["username"] == "owner"


def test_logout_requires_csrf_token(logged_in):
    client, _ = logged_in
    assert client.post("/api/auth/logout").status_code == 403
    assert (
        client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    # Still logged in after the rejected attempts.
    assert client.get("/api/auth/me").status_code == 200


def test_login_rate_limit_blocks_after_repeated_failures(logged_in):
    client, _ = logged_in
    client.cookies.clear()

    for _ in range(login_limiter.max_attempts):
        assert (
            client.post(
                "/api/auth/login", json={"username": "owner", "password": "bad"}
            ).status_code
            == 401
        )

    blocked = client.post(
        "/api/auth/login", json={"username": "owner", "password": PASSWORD}
    )
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


def test_protected_routes_reject_anonymous(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/system/hardware").status_code == 401
    assert client.get("/api/system/ollama").status_code == 401


def test_change_password_flow(logged_in):
    client, csrf = logged_in
    headers = {"X-CSRF-Token": csrf}
    new_password = PASSWORD + "-changed"

    wrong = client.post(
        "/api/auth/change-password",
        json={"current_password": "nope", "new_password": new_password},
        headers=headers,
    )
    assert wrong.status_code == 403

    short = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=headers,
    )
    assert short.status_code == 422

    same = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=headers,
    )
    assert same.status_code == 422

    ok = client.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": new_password},
        headers=headers,
    )
    assert ok.status_code == 204
    assert client.get("/api/auth/me").status_code == 200  # this session stays signed in

    client.post("/api/auth/logout", headers=headers)
    old = client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD})
    assert old.status_code == 401
    new = client.post("/api/auth/login", json={"username": "owner", "password": new_password})
    assert new.status_code == 200


def test_change_password_requires_csrf_and_login(logged_in):
    client, _ = logged_in
    body = {"current_password": PASSWORD, "new_password": PASSWORD + "-x"}
    assert client.post("/api/auth/change-password", json=body).status_code == 403
    client.cookies.clear()
    assert client.post("/api/auth/change-password", json=body).status_code == 401
