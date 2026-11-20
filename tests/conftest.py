import pytest
from itsdangerous import URLSafeTimedSerializer

from app import create_app, db
from app.models import Category, Customer, Product, ProductVariant, User
from config import Config


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-only-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        MAIL_SUPPRESS_SEND = True
        SERVER_NAME = None
        PRIVATE_UPLOAD_FOLDER = str(tmp_path_factory.mktemp("private"))

    return create_app(TestConfig)


@pytest.fixture(autouse=True)
def database(app):
    with app.app_context():
        db.create_all()
        customer = Customer(
            name="Test Customer", email="customer@example.com", password_hash="unused"
        )
        category = Category(name="Chicken")
        product = Product(name="Test Tray", category=category)
        variant = ProductVariant(product=product, size_name="Regular", price=100)
        admin = User(username="testadmin", password_hash="unused", role="Admin")
        db.session.add_all([customer, variant, admin])
        db.session.commit()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    from app.auth import credential_signature

    with client.session_transaction() as session:
        session["_user_id"] = "1"
        session["_fresh"] = True
        session["admin_auth_version"] = credential_signature(db.session.get(User, 1))
    return client


@pytest.fixture
def csrf(client, app):
    with client.session_transaction() as session:
        session["csrf_token"] = "test-session-token"
    return URLSafeTimedSerializer(app.secret_key, salt="wtf-csrf-token").dumps("test-session-token")


@pytest.fixture
def checkout(client):
    from datetime import date, timedelta

    from app.auth import credential_signature
    from app.checkout import current_quote

    with client.session_transaction() as session:
        session.update(
            customer_id=1,
            customer_name="Test Customer",
            customer_auth_version=credential_signature(db.session.get(Customer, 1)),
            checkout_token="a" * 64,
            cart={
                "1": {
                    "product_id": 1,
                    "variant_id": 1,
                    "price": 100,
                    "quantity": 1,
                    "name": "Test Tray",
                    "variant_name": "Regular",
                    "image": "default.jpg",
                }
            },
            event_date_str=(date.today() + timedelta(days=10)).isoformat(),
            event_time_str="12:00",
            payment_method="COD/COP",
            order_type="Pickup",
            delivery_fee=0,
        )
        session["checkout_quote"] = current_quote(session, db.session.get(Customer, 1))[2]
    return client
