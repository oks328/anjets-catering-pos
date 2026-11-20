import json
from decimal import Decimal

import pytest
from flask import flash, render_template
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import Order, OrderItem, ProductVariant, Voucher


def place(client, csrf):
    client.get("/checkout")
    with client.session_transaction() as session:
        token = session.get("checkout_token")
    return client.post("/checkout/place_order", data={"csrf_token": csrf, "checkout_token": token})


def test_reset_endpoint_is_removed(client):
    assert client.get("/admin/dangerous/reset_menu").status_code == 404


def test_checkout_requires_csrf(checkout):
    assert checkout.post("/checkout/place_order").status_code == 400
    assert Order.query.count() == 0


@pytest.mark.parametrize("directory", ["ids", "payments", "riders/documents"])
def test_sensitive_static_files_are_blocked(client, directory, tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(client.application, "static_folder", str(tmp_path))
    path = Path(tmp_path) / "uploads" / directory / "private-document.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private test document")
    assert client.get(f"/static/uploads/{directory}/{path.name}").status_code == 404


def test_customer_flash_cannot_close_script(app):
    payload = '</script><script>alert("x")</script>'
    with app.test_request_context("/account"):
        flash(payload, "danger")
        html = render_template("base.html")
    assert payload not in html
    assert json.dumps(payload).replace("<", "\\u003c").replace(">", "\\u003e") in html


def test_admin_flash_is_escaped(app):
    with app.test_request_context("/admin/login"):
        flash("<img src=x onerror=alert(1)>", "danger")
        html = render_template("admin_base.html")
    assert "<img src=x onerror=alert(1)>" not in html


@pytest.mark.parametrize("quantity", [-1, 0])
def test_buffet_rejects_nonpositive_quantity(checkout, csrf, quantity):
    response = checkout.post(
        "/buffet/add_item", data={"csrf_token": csrf, "variant_id": 1, "quantity": quantity}
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_date_str", None),
        ("event_date_str", "bad"),
        ("event_time_str", None),
        ("event_time_str", "25:00"),
        ("payment_method", "Credit/Debit Card"),
        ("payment_method", "Unknown"),
        ("order_type", "Unknown"),
    ],
)
def test_checkout_rejects_invalid_details(checkout, csrf, field, value):
    with checkout.session_transaction() as session:
        session[field] = value
    assert place(checkout, csrf).status_code == 400
    assert Order.query.count() == 0


def test_checkout_rechecks_buffet_lead_time(checkout, csrf):
    from datetime import date, timedelta

    with checkout.session_transaction() as session:
        session["event_date_str"] = (date.today() + timedelta(days=3)).isoformat()
        cart = session["cart"]
        cart["1"]["is_buffet_item"] = True
        session["cart"] = cart
    assert place(checkout, csrf).status_code == 400


def test_checkout_uses_current_price(checkout, csrf):
    db.session.get(ProductVariant, 1).price = 200
    db.session.commit()
    assert place(checkout, csrf).status_code == 200
    order = Order.query.one()
    assert order.final_amount == Decimal("224.00")
    assert order.items[0].price_per_item == Decimal("200.00")


def test_checkout_rejects_inactive_category(checkout, csrf):
    db.session.get(ProductVariant, 1).product.category.is_active = False
    db.session.commit()
    assert place(checkout, csrf).status_code == 400
    assert Order.query.count() == 0


@pytest.mark.parametrize("quantity", [-1, 0, "invalid"])
def test_checkout_rejects_invalid_cart_quantity(checkout, csrf, quantity):
    with checkout.session_transaction() as session:
        cart = session["cart"]
        cart["1"]["quantity"] = quantity
        session["cart"] = cart
    assert place(checkout, csrf).status_code == 400
    assert Order.query.count() == 0


@pytest.mark.parametrize("active,uses", [(False, 0), (True, 1)])
def test_checkout_revalidates_voucher(checkout, csrf, active, uses):
    db.session.add(
        Voucher(
            code="SAVE", discount_percentage=10, is_active=active, max_uses=1, current_uses=uses
        )
    )
    db.session.commit()
    with checkout.session_transaction() as session:
        session.update(voucher_code="SAVE", discount_percentage=10)
    assert place(checkout, csrf).status_code == 400
    assert Order.query.count() == 0


def test_failed_item_insert_rolls_back_order(checkout, csrf):
    def fail_insert(*args):
        raise SQLAlchemyError("injected item failure")

    event.listen(OrderItem, "before_insert", fail_insert)
    try:
        response = place(checkout, csrf)
    finally:
        event.remove(OrderItem, "before_insert", fail_insert)
    assert response.status_code == 500
    assert Order.query.count() == 0
    assert b"injected item failure" not in response.data


def test_order_clears_payment_metadata(checkout, csrf):
    with checkout.session_transaction() as session:
        session.update(
            card_last_four="1234",
            card_type="Visa",
            card_holder_name="Old Customer",
            gcash_image_file="payments/old.jpg",
            gcash_reference_no="1234567890123",
        )
    assert place(checkout, csrf).status_code == 200
    assert Order.query.one().card_last_four is None
    assert Order.query.one().payment_image_file is None
    with checkout.session_transaction() as session:
        assert "card_last_four" not in session
        assert "gcash_image_file" not in session


def test_card_route_does_not_collect_card_data(checkout):
    with checkout.session_transaction() as session:
        session.update(payment_method="Credit/Debit Card", final_total=112)
    response = checkout.get("/checkout/card/payment")
    assert response.status_code == 302
    assert response.location.endswith("/checkout/options")


def test_rendered_post_forms_have_csrf(client):
    import re

    html = client.get("/account").get_data(as_text=True)
    forms = re.findall(
        r'<form\b[^>]*method=["\']POST["\'][^>]*>(.*?)</form>', html, re.IGNORECASE | re.DOTALL
    )
    assert forms
    assert all('name="csrf_token"' in form for form in forms)


def test_private_upload_requires_admin(client):
    assert client.get("/admin/uploads/ids/example.jpg").status_code == 302


def test_private_upload_serves_authorized_file(admin, app):
    from pathlib import Path

    folder = Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / "ids"
    folder.mkdir(exist_ok=True)
    (folder / "example.jpg").write_bytes(b"test-document")
    response = admin.get("/admin/uploads/ids/example.jpg")
    assert response.status_code == 200
    assert response.data == b"test-document"
    assert response.headers["Cache-Control"] == "no-store"


def test_logout_clears_checkout_state(checkout, csrf):
    with checkout.session_transaction() as session:
        session.update(gcash_image_file="payments/old.jpg", card_last_four="1234")
    checkout.post("/logout", data={"csrf_token": csrf})
    with checkout.session_transaction() as session:
        assert "event_date_str" not in session
        assert "gcash_image_file" not in session
        assert "card_last_four" not in session


def test_valid_voucher_is_redeemed(checkout, csrf):
    db.session.add(Voucher(code="SAVE", discount_percentage=10, max_uses=1))
    db.session.commit()
    with checkout.session_transaction() as session:
        session.update(voucher_code="SAVE", discount_percentage=99)
    assert place(checkout, csrf).status_code == 200
    assert Order.query.one().final_amount == Decimal("100.80")
    assert Voucher.query.one().current_uses == 1


def test_database_migration_command_is_available(app):
    result = app.test_cli_runner().invoke(args=["db", "heads"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("days", [2, 3, 4])
def test_standard_lead_time_boundary(checkout, csrf, days):
    from datetime import date, timedelta

    with checkout.session_transaction() as session:
        session["event_date_str"] = (date.today() + timedelta(days=days)).isoformat()
    assert place(checkout, csrf).status_code == (400 if days < 3 else 200)


@pytest.mark.parametrize("days", [6, 7, 8])
def test_buffet_lead_time_boundary(checkout, csrf, days):
    from datetime import date, timedelta

    with checkout.session_transaction() as session:
        session["event_date_str"] = (date.today() + timedelta(days=days)).isoformat()
        cart = session["cart"]
        cart["1"]["is_buffet_item"] = True
        session["cart"] = cart
    assert place(checkout, csrf).status_code == (400 if days < 7 else 200)


@pytest.mark.parametrize(
    "path",
    [
        "/cart/clear",
        "/cart/remove/1",
        "/cart/remove_voucher",
        "/buffet/remove/1",
        "/buffet/remove_item/1/Chicken",
        "/logout",
        "/admin/logout",
    ],
)
def test_mutations_reject_get(checkout, path):
    assert checkout.get(path).status_code == 405


@pytest.mark.parametrize(
    "field,value",
    [("payment_method", "Credit/Debit Card"), ("event_time", "25:00"), ("order_type", "Unknown")],
)
def test_checkout_options_reject_invalid_details(checkout, csrf, field, value):
    from datetime import date, timedelta

    data = {
        "csrf_token": csrf,
        "event_date": (date.today() + timedelta(days=10)).isoformat(),
        "event_time": "12:00",
        "order_type": "Pickup",
        "payment_method": "COD/COP",
    }
    data[field] = value
    response = checkout.post("/checkout/save_options", data=data)
    assert response.location.endswith("/checkout/options")


def test_gcash_checkout_uses_private_upload(checkout, csrf, app):
    import io
    from datetime import date, timedelta
    from pathlib import Path

    from PIL import Image

    response = checkout.post(
        "/checkout/save_options",
        data={
            "csrf_token": csrf,
            "event_date": (date.today() + timedelta(days=10)).isoformat(),
            "event_time": "12:00",
            "order_type": "Pickup",
            "payment_method": "GCash",
        },
    )
    assert response.location.endswith("/checkout/gcash/upload")
    image = io.BytesIO()
    Image.new("RGB", (10, 10)).save(image, format="PNG")
    image.seek(0)
    response = checkout.post(
        "/checkout/gcash/upload",
        data={
            "csrf_token": csrf,
            "reference_number": "1234567890123",
            "receipt_image": (image, "receipt.png"),
        },
    )
    assert response.location.endswith("/checkout")
    assert place(checkout, csrf).status_code == 200
    order = Order.query.one()
    assert order.status == "Pending Payment Verification"
    assert order.payment_status == "Pending Verification"
    assert (Path(app.config["PRIVATE_UPLOAD_FOLDER"]) / order.payment_image_file).is_file()


def test_migrations_build_empty_database(app, tmp_path):
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine, inspect

    uri = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    env = dict(os.environ, DATABASE_URL=uri, SECRET_KEY="test-migration-only")
    result = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "run", "db", "upgrade"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for command in [("upgrade",), ("check",)]:
        result = subprocess.run(
            [sys.executable, "-m", "flask", "--app", "run", "db", *command],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(uri)
    try:
        assert set(db.metadata.tables).issubset(inspect(engine).get_table_names())
    finally:
        engine.dispose()
