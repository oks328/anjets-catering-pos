from datetime import datetime
from decimal import Decimal

import pytest
from flask import template_rendered

from app import db
from app.models import Customer, OrderItem, User


def test_reports_include_only_completed_paid_sales(admin, app):
    from tests.test_order_workflow import make_order

    for status, payment in [
        ("Pending Approval", "Pending"),
        ("Declined", "Paid"),
        ("Approved", "Paid"),
        ("Completed", "Pending"),
        ("Completed", "Paid"),
    ]:
        order = make_order(status, payment=payment)
        order.order_date = datetime(2026, 1, 1)
        order.completed_at = datetime(2026, 11, 17, 16, 30)
        db.session.add(
            OrderItem(
                order_id=order.order_id, product_id=1, variant_id=1, quantity=2, price_per_item=50
            )
        )
    db.session.commit()
    contexts = []

    def capture(sender, template, context, **extra):
        contexts.append(context)

    with template_rendered.connected_to(capture, app):
        response = admin.get("/admin/sales_reports?start_date=2026-11-18&end_date=2026-11-18")
    assert response.status_code == 200
    context = contexts[-1]
    assert sum(day.total_sales for day in context["sales_by_day"]) == Decimal("112")
    assert context["top_selling_items"][0].total_sold == 2
    csv = admin.get("/admin/export/sales_csv?start_date=2026-11-18&end_date=2026-11-18")
    assert "2026-11-18,112.00" in csv.get_data(as_text=True)


def test_sales_page_renders_sqlite_dates(admin):
    from tests.test_order_workflow import make_order

    order = make_order("Completed", payment="Paid")
    order.order_date = datetime(2026, 11, 18, 5)
    order.completed_at = datetime(2026, 11, 18, 5)
    db.session.commit()
    assert (
        admin.get("/admin/sales_reports?start_date=2026-11-18&end_date=2026-11-18").status_code
        == 200
    )


@pytest.mark.parametrize("value", ["google_oauth_user_placeholder", None, "invalid-hash"])
def test_nonlocal_password_returns_false(value):
    customer = Customer(name="Google User", email="google@example.com", password_hash=value)
    assert customer.check_password("AnyPassword1!") is False


def test_login_normalizes_email(client, csrf):
    customer = db.session.get(Customer, 1)
    customer.set_password("ValidPassword1!")
    db.session.commit()
    response = client.post(
        "/login",
        data={"csrf_token": csrf, "email": " CUSTOMER@EXAMPLE.COM ", "password": "ValidPassword1!"},
    )
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["customer_id"] == 1


def test_reset_token_expires_after_password_change(app):
    customer = db.session.get(Customer, 1)
    customer.set_password("OriginalPassword1!")
    db.session.commit()
    token = customer.get_reset_token()
    assert Customer.verify_reset_token(token) == customer
    customer.set_password("ChangedPassword1!")
    db.session.commit()
    assert Customer.verify_reset_token(token) is None


def test_reset_unknown_email_matches_known_response(client, csrf, monkeypatch):
    from app import routes

    monkeypatch.setattr(routes, "send_reset_email", lambda customer: None)
    known = client.post(
        "/forgot-password", data={"csrf_token": csrf, "email": "customer@example.com"}
    )
    unknown = client.post(
        "/forgot-password", data={"csrf_token": csrf, "email": "missing@example.com"}
    )
    assert (known.status_code, known.location) == (unknown.status_code, unknown.location)


def test_admin_login_accepts_existing_older_password(client, csrf):
    user = db.session.get(User, 1)
    user.set_password("oldpass")
    db.session.commit()
    response = client.post(
        "/admin/login", data={"csrf_token": csrf, "username": "testadmin", "password": "oldpass"}
    )
    assert response.location.endswith("/admin/dashboard")


def test_dashboard_uses_completed_paid_sales(admin, app):
    from datetime import timezone

    from tests.test_order_workflow import make_order

    contexts = []
    for status in ["Approved", "Completed"]:
        order = make_order(status, payment="Paid")
        order.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()

    def capture(sender, template, context, **extra):
        contexts.append(context)

    with template_rendered.connected_to(capture, app):
        assert admin.get("/admin/dashboard").status_code == 200
    assert contexts[-1]["total_sales_month"] == Decimal("112")


def test_reports_exclude_next_business_day(admin):
    from tests.test_order_workflow import make_order

    order = make_order("Completed", payment="Paid")
    order.completed_at = datetime(2026, 11, 18, 16)  # midnight on November 19 in Manila
    db.session.commit()
    response = admin.get("/admin/export/sales_csv?start_date=2026-11-18&end_date=2026-11-18")
    assert response.get_data(as_text=True).strip() == "Date,Total Sales (PHP)"


def test_registration_rejects_normalized_duplicate(client, csrf):
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf,
            "name": "Duplicate Customer",
            "email": " CUSTOMER@EXAMPLE.COM ",
            "contact_number": "09123456789",
            "address": "Test address Manila",
            "birthdate": "1990-01-01",
            "password": "ValidPassword1!",
            "confirm_password": "ValidPassword1!",
        },
    )
    assert b"That email address is already in use" in response.data
    assert Customer.query.count() == 1


def test_password_validator_rejects_excessive_utf8_length(app):
    from app.forms import ResetPasswordForm

    with app.test_request_context():
        form = ResetPasswordForm(
            data={"password": "A1!" + "\u00e9" * 40, "confirm_password": "A1!" + "\u00e9" * 40},
            meta={"csrf": False},
        )
        assert not form.validate()
        assert "72" in str(form.password.errors)


def test_customer_session_clears_previous_checkout_on_login(client, csrf):
    customer = db.session.get(Customer, 1)
    customer.set_password("ValidPassword1!")
    db.session.commit()
    with client.session_transaction() as session:
        session["gcash_image_file"] = "payments/previous-customer.jpg"
    client.post(
        "/login", data={"csrf_token": csrf, "email": customer.email, "password": "ValidPassword1!"}
    )
    with client.session_transaction() as session:
        assert "gcash_image_file" not in session


def test_staff_cannot_manage_admin_accounts(admin, csrf):
    user = db.session.get(User, 1)
    user.role = "Staff"
    db.session.commit()
    assert admin.get("/admin/users").status_code == 403
    assert admin.post("/admin/users/delete/2", data={"csrf_token": csrf}).status_code == 403


def test_staff_cannot_use_admin_login(client, csrf):
    user = db.session.get(User, 1)
    user.role = "Staff"
    user.set_password("ValidPassword1!")
    db.session.commit()
    response = client.post(
        "/admin/login",
        data={"csrf_token": csrf, "username": user.username, "password": "ValidPassword1!"},
    )
    assert not response.location or not response.location.endswith("/admin/dashboard")


def test_user_mixin_exposes_authentication_properties():
    user = db.session.get(User, 1)
    assert user.is_active is True
    assert user.is_authenticated is True
    assert user.is_anonymous is False
