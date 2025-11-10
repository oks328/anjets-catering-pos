from app import db
from datetime import datetime
from flask_login import UserMixin
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt()

# This file defines the Python classes for our database tables.
# These are called "models".
# db.Model is the base class from SQLAlchemy.

class Category(db.Model):
    """
    Model for food categories.
    e.g., "Ulam", "Noodles", "Dessert"
    """
    __tablename__ = 'Categories'
    category_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    products = db.relationship('Product', backref='category', lazy=True)

class Product(db.Model):
    """
    Model for individual food products.
    e.g., "Kalderetang Baka"
    """
    __tablename__ = 'Products'
    product_id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('Categories.category_id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    has_variants = db.Column(db.Boolean, default=False, nullable=False)
    
    image_file = db.Column(db.String(100), nullable=False, default='default.jpg')

    variants = db.relationship('ProductVariant', backref='product', lazy=True, cascade="all, delete-orphan")

class ProductVariant(db.Model):
    """
    Model for product prices based on size.
    e.g., "S", "M", "L"
    """
    __tablename__ = 'Product_Variants'
    variant_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('Products.product_id'), nullable=False)
    size_name = db.Column(db.String(50), nullable=False, default='Regular')
    # --- FIX WAS HERE ---
    price = db.Column(db.Numeric(10, 2), nullable=False)

class Customer(db.Model, UserMixin): # <-- ADDED UserMixin
    """
    Model for client-facing website users.
    """
    __tablename__ = 'Customers'
    customer_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    contact_number = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    orders = db.relationship('Order', backref='customer', lazy=True)

    # --- ADD ALL THESE METHODS BELOW ---

    def get_id(self):
        """Required by flask-login"""
        return str(self.customer_id)
    
    @property
    def is_active(self):
        """Required by flask-login"""
        return True

    @property
    def is_authenticated(self):
        """Required by flask-login"""
        return True

    @property
    def is_anonymous(self):
        """Required by flask-login"""
        return False
    
    def set_password(self, password):
        """Hashes and sets the user's password."""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        """Checks if the provided password matches the hash."""
        return bcrypt.check_password_hash(self.password_hash, password)

class User(db.Model, UserMixin): # <-- Note the change here
    """
    Model for secure admin/staff logins.
    """
    __tablename__ = 'Users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='Admin')

    # New methods for flask-login
    def get_id(self):
        """Required by flask-login"""
        return str(self.user_id)
    
    @property
    def is_active(self):
        """Required by flask-login"""
        return True

    @property
    def is_authenticated(self):
        """Required by flask-login"""
        return True

    @property
    def is_anonymous(self):
        """Required by flask-login"""
        return False
    
    # New methods for password hashing
    def set_password(self, password):
        """Hashes and sets the user's password."""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        """Checks if the provided password matches the hash."""
        return bcrypt.check_password_hash(self.password_hash, password)

class Order(db.Model):
    """
    Model for a single customer order.
    """
    __tablename__ = 'Orders'
    order_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('Customers.customer_id'), nullable=False)
    order_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # --- FIX WAS HERE ---
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    # --- FIX WAS HERE ---
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    # --- FIX WAS HERE ---
    final_amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Pending')
    
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")

class OrderItem(db.Model):
    """
    Model for an individual item within an order.
    """
    __tablename__ = 'Order_Items'
    order_item_id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('Orders.order_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('Products.product_id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('Product_Variants.variant_id'), nullable=True)
    product = db.relationship('Product')
    variant = db.relationship('ProductVariant')
    quantity = db.Column(db.Integer, nullable=False)
    # --- FIX WAS HERE ---
    price_per_item = db.Column(db.Numeric(10, 2), nullable=False)

class Voucher(db.Model):
    """
    Model for discount vouchers.
    """
    __tablename__ = 'Vouchers'
    voucher_id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    # --- FIX WAS HERE ---
    discount_percentage = db.Column(db.Numeric(5, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)