"""Separate-process integration fixture using two connections to a file-backed database."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier, local

from sqlalchemy import event

from app import create_app, db
from app.auth import credential_signature
from app.checkout import current_quote
from app.models import Category, Customer, Order, Product, ProductVariant, Voucher
from config import Config


def main():
    class Settings(Config):
        TESTING = True
        SECRET_KEY = "concurrency-test-only"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + Path(sys.argv[1]).as_posix()
        WTF_CSRF_ENABLED = False

    app = create_app(Settings)
    with app.app_context():
        db.create_all()
        customer = Customer(name="Test Customer", email="test@example.com", password_hash=None)
        category = Category(name="Chicken")
        product = Product(category=category, name="Test Tray")
        variant = ProductVariant(product=product, size_name="Regular", price=100)
        voucher = Voucher(code="ONCE", discount_percentage=10, max_uses=1)
        db.session.add_all([customer, variant, voucher])
        db.session.commit()
        proof = credential_signature(customer)
        engine = db.engine
    barrier = Barrier(2)
    state = local()

    def synchronize(connection, cursor, statement, parameters, context, many):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "checkout_token" in statement
            and "Orders" in statement
            and not getattr(state, "seen", False)
        ):
            state.seen = True
            barrier.wait(timeout=10)

    event.listen(engine, "after_cursor_execute", synchronize)

    def submit(_):
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(
                customer_id=1,
                customer_name="Test Customer",
                customer_auth_version=proof,
                checkout_token="a" * 64,
                cart={"1": {"quantity": 1, "product_id": 1, "price": "100.00"}},
                event_date_str=(date.today() + timedelta(days=10)).isoformat(),
                event_time_str="12:00",
                payment_method="COD/COP",
                order_type="Pickup",
                voucher_code="ONCE",
            )
        with app.app_context():
            with client.session_transaction() as session:
                session["checkout_quote"] = current_quote(session, db.session.get(Customer, 1))[2]
        return client.post("/checkout/place_order", data={"checkout_token": "a" * 64}).status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, range(2)))
    finally:
        event.remove(engine, "after_cursor_execute", synchronize)
    with app.app_context():
        print(
            json.dumps(
                {
                    "statuses": statuses,
                    "orders": Order.query.count(),
                    "uses": Voucher.query.one().current_uses,
                }
            )
        )
        db.session.remove()
        engine.dispose()


if __name__ == "__main__":
    main()
