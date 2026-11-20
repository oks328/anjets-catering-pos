import io
from decimal import Decimal

import pytest

from app import db
from app.models import Customer, Order, OrderItem, Product, ProductVariant, Voucher
from tests.test_security_checkout import place


def upload(admin, csrf, text, filename="menu.csv"):
    return admin.post(
        "/admin/import/products_csv",
        data={"csrf_token": csrf, "csv_file": (io.BytesIO(text.encode("utf-8")), filename)},
    )


@pytest.mark.parametrize(
    "price,size",
    [
        ("", ""),
        ("-1", "Regular"),
        ("0", "Regular"),
        ("NaN", "Regular"),
        ("1.001", "Regular"),
        ("Infinity", "Regular"),
        ("100000000", "Regular"),
    ],
)
def test_csv_invalid_row_does_not_create_product(admin, csrf, price, size):
    upload(admin, csrf, f"Chicken,Invalid Dish,Description,false,{price},{size}\n")
    assert Product.query.filter_by(name="Invalid Dish").first() is None


def test_csv_good_row_survives_bad_row(admin, csrf):
    upload(
        admin,
        csrf,
        "Chicken,Good Dish,Description,false,125.25,Regular\n"
        "Chicken,Incomplete Dish,Description,false,,\n",
    )
    assert Product.query.filter_by(name="Good Dish").one().variants[0].price == Decimal("125.25")
    assert Product.query.filter_by(name="Incomplete Dish").first() is None


def test_csv_imports_multiple_sizes(admin, csrf):
    upload(
        admin,
        csrf,
        "Chicken,Party Tray,Description,true,100,Small\n"
        "Chicken,Party Tray,Description,true,200,Large\n",
    )
    product = Product.query.filter_by(name="Party Tray").one()
    assert len(product.variants) == 2
    assert {variant.size_name for variant in product.variants} == {"Small", "Large"}


def test_csv_accepts_bom_header(admin, csrf):
    upload(
        admin,
        csrf,
        "\ufeffCategory Name,Product Name,Description,Has Variants,Price,Size\n"
        "Chicken,Header Dish,Description,false,100,Regular\n",
        "MENU.CSV",
    )
    assert Product.query.filter_by(name="Header Dish").one().variants


def test_csv_rejects_invalid_boolean(admin, csrf):
    upload(admin, csrf, "Chicken,Bad Boolean,Description,maybe,100,Regular\n")
    assert Product.query.filter_by(name="Bad Boolean").first() is None


@pytest.mark.parametrize("price", ["-1", "0", "NaN", "Infinity", "1.001", "100000000"])
def test_variant_form_rejects_invalid_prices(admin, csrf, price):
    admin.post(
        "/admin/products/1/variants/add",
        data={"csrf_token": csrf, "size_name": "Invalid Size", "price": price},
    )
    assert ProductVariant.query.filter_by(size_name="Invalid Size").first() is None


def test_order_history_keeps_names_after_menu_edit(checkout, csrf):
    assert place(checkout, csrf).status_code == 200
    order = Order.query.one()
    order.status = "Approved"
    variant = db.session.get(ProductVariant, 1)
    variant.product.name = "Renamed Food"
    variant.size_name = "Renamed Size"
    db.session.commit()
    html = checkout.get(f"/my-account/order/{order.order_id}/receipt").get_data(as_text=True)
    assert "Test Tray (Regular)" in html
    assert "Renamed Food" not in html


def test_variant_used_in_order_cannot_be_deleted(checkout, csrf, admin):
    assert place(checkout, csrf).status_code == 200
    admin.post("/admin/variants/delete/1", data={"csrf_token": csrf})
    assert db.session.get(ProductVariant, 1) is not None


def test_verified_discount_does_not_consume_voucher(checkout, csrf):
    customer = db.session.get(Customer, 1)
    customer.is_verified_discount = True
    customer.discount_status = "Approved"
    db.session.add(Voucher(code="SAVE", discount_percentage=10, max_uses=1))
    db.session.commit()
    with checkout.session_transaction() as session:
        session.update(voucher_code="SAVE", discount_percentage=10)
    assert place(checkout, csrf).status_code == 200
    assert Voucher.query.one().current_uses == 0


@pytest.mark.parametrize("price", ["0", "-1", "100000000"])
def test_database_rejects_invalid_variant_price(price):
    from sqlalchemy.exc import IntegrityError

    db.session.add(ProductVariant(product_id=1, size_name="Invalid", price=Decimal(price)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize("quantity", [0, -1])
def test_database_rejects_nonpositive_order_quantity(quantity):
    from sqlalchemy.exc import IntegrityError

    from tests.test_order_workflow import make_order

    order = make_order()
    db.session.add(
        OrderItem(
            order_id=order.order_id,
            product_id=1,
            variant_id=1,
            price_per_item=100,
            quantity=quantity,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_sales_report_keeps_historical_item_name(checkout, csrf, admin):
    from datetime import datetime, timezone

    assert place(checkout, csrf).status_code == 200
    order = Order.query.one()
    order.status = "Completed"
    order.payment_status = "Paid"
    order.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    variant = db.session.get(ProductVariant, 1)
    variant.product.name = "Renamed Food"
    variant.size_name = "Renamed Size"
    db.session.commit()
    html = admin.get("/admin/sales_reports").get_data(as_text=True)
    assert "Test Tray" in html
    assert "Renamed Food" not in html


def test_buffet_cached_prices_are_exact_strings(checkout, csrf):
    db.session.get(ProductVariant, 1).price = Decimal("0.10")
    db.session.commit()
    response = checkout.post(
        "/buffet/add_item",
        data={"csrf_token": csrf, "variant_id": 1, "quantity": 3, "force": "true"},
    )
    assert response.status_code == 200
    assert response.json["new_total_price"] == 0.3
    with checkout.session_transaction() as session:
        assert session["buffet_package"]["1"]["price"] == "0.10"


@pytest.mark.parametrize("path", ["/cart", "/checkout"])
def test_oversized_cart_can_be_corrected(checkout, path):
    with checkout.session_transaction() as session:
        cart = session["cart"]
        cart["1"]["quantity"] = 1000000
        session["cart"] = cart
    response = checkout.get(path, follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Cannot calculate this cart" in html
    assert "Proceed to Checkout" not in html


def test_gcash_options_reject_oversized_order(checkout, csrf):
    from datetime import date, timedelta

    with checkout.session_transaction() as session:
        cart = session["cart"]
        cart["1"]["quantity"] = 1000000
        session["cart"] = cart
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
    assert response.location.endswith("/cart")


def test_simple_product_requires_price_before_save(admin, csrf):
    admin.post(
        "/admin/products/add",
        data={
            "csrf_token": csrf,
            "category": 1,
            "name": "Missing Price",
            "description": "Incomplete",
            "price": "",
        },
    )
    assert Product.query.filter_by(name="Missing Price").first() is None
