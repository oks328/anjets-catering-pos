from app import db, bcrypt
from datetime import datetime
from flask_login import UserMixin
from flask_bcrypt import Bcrypt
from itsdangerous import URLSafeTimedSerializer as Serializer
from flask import current_app 

bcrypt = Bcrypt()

# This file defines the Python classes for our database tables.

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
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    image_file = db.Column(db.String(100), nullable=False, default='default.jpg')

    variants = db.relationship('ProductVariant', backref='product', lazy=True, cascade="all, delete-orphan")
    reviews = db.relationship('Review', backref='product', lazy=True) # Keep Review relationship

class ProductVariant(db.Model):
    """
    Model for product prices based on size.
    e.g., "S", "M", "L"
    """
    __tablename__ = 'Product_Variants'
    variant_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('Products.product_id'), nullable=False)
    size_name = db.Column(db.String(50), nullable=False, default='Regular')
    price = db.Column(db.Numeric(10, 2), nullable=False)

class Customer(db.Model, UserMixin): 
    """
    Model for client-facing website users.
    """
    __tablename__ = 'Customers'
    customer_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    contact_number = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    registration_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    address = db.Column(db.Text, nullable=True)
    landmark = db.Column(db.String(255), nullable=True) # <-- Ensure this is correctly defined
    birthdate = db.Column(db.Date, nullable=True)
    discount_type = db.Column(db.String(50), nullable=True) 
    id_image_file = db.Column(db.String(100), nullable=True)
    is_verified_discount = db.Column(db.Boolean, default=False, nullable=False)
    discount_status = db.Column(db.String(20), nullable=True, default=None) 

    orders = db.relationship('Order', backref='customer', lazy=True)

    def get_id(self):
        """Required by flask-login"""
        return str(self.customer_id)
    
    @property
    def is_active(self): return True

    @property
    def is_authenticated(self): return True

    @property
    def is_anonymous(self): return False
    
    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def get_reset_token(self, expires_sec=1800):
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'customer_id': self.customer_id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token, max_age=expires_sec)
            customer_id = data.get('customer_id')
        except Exception:
            return None
        return Customer.query.get(customer_id)

class User(db.Model, UserMixin): 
    """
    Model for secure admin/staff logins.
    """
    __tablename__ = 'Users'
    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='Admin')

    def get_id(self): return str(self.user_id)
    def is_active(self): return True
    def is_authenticated(self): return True
    def is_anonymous(self): return False
    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

# In app/models.py

class Order(db.Model):
    """
    Model for a single customer order.
    Updated for Event-Based Logic.
    """
    __tablename__ = 'Orders'
    order_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('Customers.customer_id'), nullable=False)
    order_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # When they clicked "Buy"
    
    # --- NEW FIELDS FOR CATERING ---
    event_date = db.Column(db.Date, nullable=True) # When they need the food
    event_time = db.Column(db.Time, nullable=True) # What time
    decline_reason = db.Column(db.Text, nullable=True) # If admin rejects it
    # -------------------------------

    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    final_amount = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Default status is now 'Pending Approval' instead of just 'Pending'
    status = db.Column(db.String(50), nullable=False, default='Pending Approval')
    
    order_type = db.Column(db.String(50), nullable=False, default='Pickup')
    delivery_address = db.Column(db.Text, nullable=True)
    delivery_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    vat_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    special_instructions = db.Column(db.Text, nullable=True)

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
    price_per_item = db.Column(db.Numeric(10, 2), nullable=False)

class Voucher(db.Model):
    """
    Model for discount vouchers.
    """
    __tablename__ = 'Vouchers'
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
    __tablename__ = 'Reviews'
    review_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('Products.product_id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('Customers.customer_id'), nullable=False)
    
    # Review data
    rating = db.Column(db.Integer, nullable=False) 
    comment = db.Column(db.Text, nullable=True)
    review_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships: ONLY DEFINE THE FOREIGN KEY
    # The backref in the Product model handles the product property.
    # We only need to explicitly define the customer relationship here.
    customer = db.relationship('Customer')
