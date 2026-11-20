import pytest

from app import db
from app.models import Customer, Order, User, Voucher


def payload(csrf):
    return {"csrf_token": csrf, "checkout_token": "a" * 64}


def test_retry_returns_original_order(checkout, csrf):
    first = checkout.post("/checkout/place_order", data=payload(csrf))
    second = checkout.post("/checkout/place_order", data=payload(csrf))
    assert first.status_code == second.status_code == 200
    assert first.json == second.json
    assert Order.query.count() == 1


def test_stale_tab_does_not_duplicate_order(checkout, csrf):
    with checkout.session_transaction() as session:
        stale = dict(session)
    first = checkout.post("/checkout/place_order", data=payload(csrf))
    with checkout.session_transaction() as session:
        session.clear()
        session.update(stale)
    second = checkout.post("/checkout/place_order", data=payload(csrf))
    assert first.json == second.json
    assert Order.query.count() == 1


def test_checkout_requires_server_token(checkout, csrf):
    response = checkout.post("/checkout/place_order", data={"csrf_token": csrf})
    assert response.status_code == 400
    assert Order.query.count() == 0


def test_retry_does_not_use_voucher_twice(checkout, csrf):
    db.session.add(Voucher(code="ONCE", discount_percentage=10, max_uses=1))
    db.session.commit()
    with checkout.session_transaction() as session:
        stale = dict(session)
        stale.update(voucher_code="ONCE", discount_percentage=10)
        session.update(stale)
    checkout.get("/checkout")
    with checkout.session_transaction() as session:
        stale = dict(session)
    first = checkout.post("/checkout/place_order", data=payload(csrf))
    with checkout.session_transaction() as session:
        session.update(stale)
    second = checkout.post("/checkout/place_order", data=payload(csrf))
    assert first.status_code == second.status_code == 200
    assert Voucher.query.one().current_uses == 1


def test_retry_preserves_new_cart(checkout, csrf):
    assert checkout.post("/checkout/place_order", data=payload(csrf)).status_code == 200
    with checkout.session_transaction() as session:
        session["cart"] = {"new-item": {"quantity": 2}}
        session["checkout_token"] = "b" * 64
    assert checkout.post("/checkout/place_order", data=payload(csrf)).status_code == 200
    with checkout.session_transaction() as session:
        assert session["cart"] == {"new-item": {"quantity": 2}}
        assert session["checkout_token"] == "b" * 64


def test_customer_password_change_revokes_session(client, csrf):
    customer = db.session.get(Customer, 1)
    customer.set_password("OriginalPassword1!")
    db.session.commit()
    assert (
        client.post(
            "/login",
            data={"csrf_token": csrf, "email": customer.email, "password": "OriginalPassword1!"},
        ).status_code
        == 302
    )
    customer.set_password("ChangedPassword1!")
    db.session.commit()
    response = client.get("/my-account/orders")
    assert response.status_code == 302
    assert response.location.endswith("/account")
    with client.session_transaction() as session:
        assert "customer_id" not in session


def test_admin_password_change_revokes_session(client, csrf):
    user = db.session.get(User, 1)
    user.set_password("OriginalPassword1!")
    db.session.commit()
    client.post(
        "/admin/login",
        data={"csrf_token": csrf, "username": user.username, "password": "OriginalPassword1!"},
    )
    user.set_password("ChangedPassword1!")
    db.session.commit()
    from urllib.parse import urlsplit

    assert urlsplit(client.get("/admin/users").location).path == "/admin/login"


@pytest.mark.parametrize(
    "endpoint,field,identity",
    [
        ("/login", "email", "customer@example.com"),
        ("/admin/login", "username", "testadmin"),
        ("/forgot-password", "email", "customer@example.com"),
    ],
)
def test_auth_attempts_are_limited(client, csrf, app, monkeypatch, endpoint, field, identity):
    from app import routes

    monkeypatch.setattr(routes, "send_reset_email", lambda customer: None)
    for key in ("AUTH_LOGIN_ACCOUNT_LIMIT", "AUTH_RESET_ACCOUNT_LIMIT"):
        monkeypatch.setitem(app.config, key, 2)
    for _ in range(2):
        response = client.post(
            endpoint, data={"csrf_token": csrf, field: identity, "password": "wrong"}
        )
        assert response.status_code != 429
    response = client.post(
        endpoint, data={"csrf_token": csrf, field: identity, "password": "wrong"}
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_stale_tab_clears_completed_cart(checkout, csrf):
    with checkout.session_transaction() as session:
        stale = dict(session)
    assert checkout.post("/checkout/place_order", data=payload(csrf)).status_code == 200
    with checkout.session_transaction() as session:
        session.update(stale)
    assert checkout.post("/checkout/place_order", data=payload(csrf)).status_code == 200
    with checkout.session_transaction() as session:
        assert "cart" not in session


def test_limit_expires(client, csrf, app, monkeypatch):
    from datetime import datetime, timedelta

    from app import auth_limits

    now = datetime(2030, 1, 1)
    monkeypatch.setattr(auth_limits, "utc_now", lambda: now)
    monkeypatch.setitem(app.config, "AUTH_LOGIN_ACCOUNT_LIMIT", 1)
    data = {"csrf_token": csrf, "email": "customer@example.com", "password": "wrong"}
    assert client.post("/login", data=data).status_code == 200
    assert client.post("/login", data=data).status_code == 429
    now += timedelta(seconds=app.config["AUTH_LOGIN_WINDOW_SECONDS"] + 1)
    assert client.post("/login", data=data).status_code == 200


def test_ip_limit_blocks_rotating_accounts(client, csrf, app, monkeypatch):
    monkeypatch.setitem(app.config, "AUTH_LOGIN_IP_LIMIT", 2)
    for index in range(2):
        assert (
            client.post(
                "/login",
                data={
                    "csrf_token": csrf,
                    "email": f"guess{index}@example.com",
                    "password": "wrong",
                },
            ).status_code
            == 200
        )
    assert (
        client.post(
            "/login", data={"csrf_token": csrf, "email": "another@example.com", "password": "wrong"}
        ).status_code
        == 429
    )


def test_simultaneous_checkout_creates_one_order(tmp_path):
    import json
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "tests.concurrent_checkout", str(tmp_path / "concurrent.db")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"statuses": [200, 200], "orders": 1, "uses": 1}
