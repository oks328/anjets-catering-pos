from datetime import datetime, timezone
from hashlib import sha256
from hmac import compare_digest

from flask import current_app
from flask_login import UserMixin
from itsdangerous import URLSafeTimedSerializer as Serializer
from sqlalchemy.orm import validates

from app import bcrypt, db


class Category(db.Model):
    """
    Model for food categories.
    e.g., "Ulam", "Noodles", "Dessert"
    """

    __tablename__ = "Categories"
    category_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)

    products = db.relationship("Product", backref="category", lazy=True)


class Product(db.Model):
    """
    Model for individual food products.
    e.g., "Kalderetang Baka"
    """

    __tablename__ = "Products"
    product_id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("Categories.category_id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    has_variants = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    image_file = db.Column(db.String(100), nullable=False, default="default.jpg")

    variants = db.relationship(
        "ProductVariant", backref="product", lazy=True, cascade="all, delete-orphan"
    )
    reviews = db.relationship("Review", backref="product", lazy=True)  # Keep Review relationship


class ProductVariant(db.Model):
    """
    Model for product prices based on size.
    e.g., "S", "M", "L"
    """

    __tablename__ = "Product_Variants"
    __table_args__ = (
        db.CheckConstraint(
            "price > 0 AND price <= 99999999.99", name="ck_product_variants_price_range"
        ),
    )
    variant_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("Products.product_id"), nullable=False)
    size_name = db.Column(db.String(50), nullable=False, default="Regular")
    price = db.Column(db.Numeric(10, 2), nullable=False)


class Customer(db.Model, UserMixin):
    """
    Model for client-facing website users.
    """

    __tablename__ = "Customers"
    customer_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    contact_number = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    registration_date = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    address = db.Column(db.Text, nullable=True)
    landmark = db.Column(db.String(255), nullable=True)
    birthdate = db.Column(db.Date, nullable=True)
    discount_type = db.Column(db.String(50), nullable=True)
    id_image_file = db.Column(db.String(100), nullable=True)
    is_verified_discount = db.Column(db.Boolean, default=False, nullable=False)
    discount_status = db.Column(db.String(20), nullable=True, default=None)
    google_id = db.Column(db.String(100), unique=True, nullable=True)

    orders = db.relationship("Order", backref="customer", lazy=True)

    @validates("email")
    def normalize_email(self, key, value):
        return value.strip().lower()

    def get_id(self):
        """Required by flask-login"""
        return str(self.customer_id)

    @property
    def is_active(self):
        return True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        if not self.password_hash:
            return False
        try:
            return bcrypt.check_password_hash(self.password_hash, password)
        except (ValueError, TypeError):
            return False

    def get_reset_token(self, expires_sec=1800):
        s = Serializer(current_app.config["SECRET_KEY"], salt="password-reset")
        version = sha256((self.password_hash or "").encode()).hexdigest()
        return s.dumps({"customer_id": self.customer_id, "password_version": version})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = Serializer(current_app.config["SECRET_KEY"], salt="password-reset")
        try:
            data = s.loads(token, max_age=expires_sec)
            customer_id = data.get("customer_id")
        except Exception:
            return None
        customer = db.session.get(Customer, customer_id) if customer_id else None
        if not customer:
            return None
        version = sha256((customer.password_hash or "").encode()).hexdigest()
        if not compare_digest(data.get("password_version", ""), version):
            return None
        return customer


class User(db.Model, UserMixin):
    """
    Model for secure admin/staff logins.
    """

    __tablename__ = "Users"
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="Admin")

    def get_id(self):
        return str(self.user_id)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        try:
            return bcrypt.check_password_hash(self.password_hash, password)
        except (ValueError, TypeError):
            return False


class Order(db.Model):
    """
    Model for a single customer order.
    Updated for Event-Based Logic.
    """

    __tablename__ = "Orders"
    __table_args__ = (db.UniqueConstraint("checkout_token", name="uq_orders_checkout_token"),)
    order_id = db.Column(db.Integer, primary_key=True)
    checkout_token = db.Column(db.String(64), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("Customers.customer_id"), nullable=False)
    order_date = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    completed_at = db.Column(db.DateTime, nullable=True, index=True)

    event_date = db.Column(db.Date, nullable=True)
    event_time = db.Column(db.Time, nullable=True)
    decline_reason = db.Column(db.Text, nullable=True)

    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    final_amount = db.Column(db.Numeric(10, 2), nullable=False)

    status = db.Column(db.String(50), nullable=False, default="Pending Approval")

    order_type = db.Column(db.String(50), nullable=False, default="Pickup")
    delivery_address = db.Column(db.Text, nullable=True)
    delivery_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    vat_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    special_instructions = db.Column(db.Text, nullable=True)

    payment_method = db.Column(db.String(50), nullable=False, default="COD/COP")
    payment_status = db.Column(db.String(50), nullable=False, default="Pending")
    payment_image_file = db.Column(db.String(100), nullable=True)
    gcash_reference_no = db.Column(db.String(50), nullable=True)
    card_last_four = db.Column(db.String(4), nullable=True)  # Last 4 digits of card
    card_type = db.Column(db.String(20), nullable=True)  # Visa, Mastercard, etc.

    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")


class OrderItem(db.Model):
    """
    Model for an individual item within an order.
    """

    __tablename__ = "Order_Items"
    __table_args__ = (
        db.CheckConstraint(
            "quantity > 0 AND quantity <= 2147483647", name="ck_order_items_quantity_range"
        ),
    )
    order_item_id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("Orders.order_id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("Products.product_id"), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey("Product_Variants.variant_id"), nullable=True)
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
    quantity = db.Column(db.Integer, nullable=False)
    price_per_item = db.Column(db.Numeric(10, 2), nullable=False)
    product_name_snapshot = db.Column(db.String(255), nullable=True)
    variant_name_snapshot = db.Column(db.String(50), nullable=True)

    @property
    def product_name(self):
        return self.product_name_snapshot or (
            self.product.name if self.product else "Unavailable product"
        )

    @property
    def variant_name(self):
        return self.variant_name_snapshot or (
            self.variant.size_name if self.variant else "Unavailable variant"
        )


class Voucher(db.Model):
    """
    Model for discount vouchers.
    """

    __tablename__ = "Vouchers"
    voucher_id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_percentage = db.Column(db.Numeric(5, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    max_uses = db.Column(db.Integer, nullable=True)
    current_uses = db.Column(db.Integer, nullable=False, default=0)


class Review(db.Model):
    """
    Model for customer product reviews.
    """

    __tablename__ = "Reviews"
    review_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("Products.product_id"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("Customers.customer_id"), nullable=False)

    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    review_date = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    customer = db.relationship("Customer")


class AuthRateLimit(db.Model):
    """Shared fixed-window counters. Keys contain HMAC digests rather than identities."""

    __tablename__ = "Auth_Rate_Limits"
    key = db.Column(db.String(64), primary_key=True)
    attempts = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
