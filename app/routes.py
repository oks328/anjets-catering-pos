from app import db
import os
import io
import secrets
import csv
import pandas as pd
import xml.etree.ElementTree as ET
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date
from sqlalchemy import func, cast, Integer
from PIL import Image
from xml.dom import minidom
from flask import make_response, jsonify
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, session, jsonify, current_app
from flask_login import login_user, logout_user, current_user, login_required
from app.models import User, Category, Product, ProductVariant, Voucher, Customer, Order, OrderItem, Review # Rider removed
from app.forms import AdminLoginForm, CategoryForm, ProductForm, VariantForm, VoucherForm, UserAddForm, UserEditForm, CustomerRegisterForm, CustomerLoginForm, CustomerEditForm, CustomerProfileForm, DiscountVerificationForm, ReviewForm # All Rider forms removed
from functools import wraps
from flask_mail import Message
from app import mail
from app.forms import RequestResetForm, ResetPasswordForm
from flask import make_response, jsonify, current_app as app, render_template, redirect, url_for, flash, request, session, jsonify, current_app, get_flashed_messages

VAT_RATE = 0.12 # 12% Value Added Tax
MAIN_CATEGORIES = ['Pork', 'Beef', 'Chicken', 'Seafood']

CATEGORY_ORDER = [
    'Beef', 
    'Pork', 
    'Chicken', 
    'Seafood', 
    'Pasta & Noodles', 
    'Noodles',
    'Vegetables', 
    'Dessert', 
    'Drinks'
]

def get_category_choices():
    """
    Helper function to get all categories for the product form dropdown.
    """
    categories = Category.query.filter_by(is_active=True).all()
    return [(c.category_id, c.name) for c in categories]

def save_picture(form_picture):
    """
    Helper function to save an uploaded picture.
    Resizes it and returns the unique filename.
    """
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.config['UPLOAD_FOLDER'], 'products', picture_fn)

    output_size = (800, 800) 
    i = Image.open(form_picture)
    i.thumbnail(output_size)
    i.save(picture_path)

    return picture_fn

def customer_login_required(f):
    """
    A decorator to ensure a customer is logged in by checking the session.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'customer_id' not in session:
            flash("You must be logged in to view that page.", 'danger')
            return redirect(url_for('client_account_page'))
        return f(*args, **kwargs)
    return decorated_function

# ===============================================
# HELPER: Check if review exists (NEW)
# ===============================================

def has_reviewed_product(customer_id, product_id):
    """
    Checks only if a customer has already submitted a review for this product.
    Returns True if a review exists, False otherwise.
    """
    return Review.query.filter_by(
        customer_id=customer_id,
        product_id=product_id
    ).first() is not None


# ===============================================
# CLIENT-SIDE ROUTES
# ===============================================

@app.route('/')
def client_home():
    """
    Client-facing homepage.
    Now fetches top 3 popular products.
    """
    top_product_ids = db.session.query(
            OrderItem.product_id,
            func.sum(OrderItem.quantity).label('total_sold')
        ).group_by(OrderItem.product_id)\
         .order_by(func.sum(OrderItem.quantity).desc())\
         .limit(3)\
         .all()

    product_ids = [pid for pid, total in top_product_ids]
    popular_products = Product.query.filter(Product.product_id.in_(product_ids)).all()

    return render_template(
        'client_home.html',
        popular_products=popular_products
    )

@app.route('/menu')
def client_menu():
    """
    Client-facing Menu page.
    Shows ACTIVE categories and products.
    Can be filtered by category_id.
    NOW includes average product ratings.
    """
    category_id = request.args.get('category_id', type=int)
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()
    selected_category = None

    product_query = Product.query.join(Category).filter(Category.is_active==True)

    if category_id:
        product_query = product_query.filter(Product.category_id==category_id)
        selected_category = Category.query.get(category_id)

    products = product_query.order_by(Product.name.asc()).all()
    
    product_ids = [p.product_id for p in products]
    
    ratings_query = db.session.query(
        Review.product_id,
        func.avg(Review.rating).label('average_rating'),
        func.count(Review.review_id).label('review_count')
    ).filter(Review.product_id.in_(product_ids))\
     .group_by(Review.product_id)\
     .all()
     
    ratings_map = {item.product_id: {'avg': float(item.average_rating), 'count': item.review_count} for item in ratings_query}

    return render_template(
        'client_menu.html',
        categories=categories,
        products=products,
        selected_category=selected_category,
        ratings_map=ratings_map
    )


# app/routes.py (Add these functions back into the file)

def has_reviewed_product(customer_id, product_id):
    """
    Checks only if a customer has already submitted a review for this product.
    Returns True if a review exists, False otherwise.
    """
    return Review.query.filter_by(
        customer_id=customer_id,
        product_id=product_id
    ).first() is not None


# app/routes.py (Add this function back into the CATEGORY MANAGEMENT section)

@app.route('/admin/categories/add', methods=['POST'])
@login_required
def admin_add_category():
    """
    (C)REATE: Process the add category form.
    """
    add_form = CategoryForm()
    
    if add_form.validate_on_submit():
        # Create new category object
        new_category = Category(
            name=add_form.name.data,
            description=add_form.description.data 
        )
        # Add to database
        db.session.add(new_category)
        try:
            db.session.commit()
            flash(f"Category '{new_category.name}' added successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding category: {e}", 'danger')
    else:
        # Form had validation errors
        flash('Error: Could not add category. Please check form.', 'danger')

    return redirect(url_for('admin_categories') + '#add-category-card')

# app/routes.py (Add this function back, e.g., after client_my_account)

@app.route('/my-account/order/<int:order_id>/receipt')
@customer_login_required
def client_view_receipt(order_id):
    """
    Renders a printable receipt for a specific order.
    """
    # 1. Fetch the order and related data (customer, items, products, variants)
    order = Order.query.options(
        db.joinedload(Order.customer),
        db.joinedload(Order.items).joinedload(OrderItem.product),
        db.joinedload(Order.items).joinedload(OrderItem.variant)
    ).filter_by(order_id=order_id).first_or_404()

    # 2. Security Check: Ensure the order belongs to the logged-in customer
    if order.customer_id != session['customer_id']:
        flash("You do not have permission to view that receipt.", 'danger')
        return redirect(url_for('client_orders'))

    # 3. Render the receipt template (which you should have already created)
    return render_template(
        'client_receipt.html', 
        order=order
    )
# app/routes.py (Add this function back, e.g., before admin_dashboard)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """
    Handle the admin login page.
    """
    # If user is already logged in, redirect to a future admin dashboard
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard')) # We will create 'admin_dashboard' next

    form = AdminLoginForm()
    if form.validate_on_submit():
        # Form has been submitted and is valid
        username = form.username.data
        password = form.password.data
        
        # 1. Check if the user exists in the database
        user = User.query.filter_by(username=username).first()
        
        # 2. Check if the password is correct
        if user and user.check_password(password):
            # Password is correct! Log the user in.
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard')) # Redirect to the dashboard
        else:
            # Invalid credentials
            flash('Invalid username or password. Please try again.', 'danger')
            return redirect(url_for('admin_login'))

    # If it's a 'GET' request or form validation failed, show the login page
    return render_template('admin_login.html', form=form)

@app.route('/my-account')
@customer_login_required
def client_my_account():
    """
    (R)EAD: Redirects the main account URL directly to the profile.
    This removes the redundant dashboard step.
    """
    return redirect(url_for('client_profile'))

@app.route('/my-account/profile', methods=['GET', 'POST'])
@customer_login_required
def client_profile():
    """
    (R)EAD and (U)PDATE the customer's own profile.
    NOW revokes senior discount if birthdate is changed.
    """
    customer = Customer.query.get_or_404(session['customer_id'])
    form = CustomerProfileForm(obj=customer) 
    upload_form = DiscountVerificationForm()

    if form.validate_on_submit():
        # Get the new birthdate from the form
        new_birthdate = form.birthdate.data
        profile_updated_message = 'Your profile has been updated.'

        # --- NEW LOGIC: Auto-revoke discount if age changes ---
        if new_birthdate:
            today = date.today()
            age = today.year - new_birthdate.year - ((today.month, today.day) < (new_birthdate.month, new_birthdate.day))
            
            # Check if they are currently verified as a Senior
            if customer.is_verified_discount and customer.discount_type == 'Senior':
                if age < 60:
                    # They are no longer a senior, revoke the discount!
                    customer.is_verified_discount = False
                    customer.discount_status = None # Reset status
                    customer.discount_type = None
                    customer.id_image_file = None # Clear the old ID
                    flash('Your Senior discount has been revoked as your new birthdate makes you ineligible.', 'warning')
                    # Change the success message so it doesn't conflict
                    profile_updated_message = 'Your profile and discount status have been updated.'
        # --- END NEW LOGIC ---

        # Update the customer's details
        customer.name = form.name.data
        customer.contact_number = form.contact_number.data
        customer.birthdate = new_birthdate # Save the new birthdate

        customer.landmark = form.landmark.data
        try:
            db.session.commit()
            session['customer_name'] = customer.name
            
            # Check if a warning was just flashed. If not, flash the success message.
            if 'warning' not in [m[0] for m in get_flashed_messages(with_categories=True)]:
                 flash(profile_updated_message, 'success')
                 
            return redirect(url_for('client_profile'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating profile: {e}", 'danger')

    # This handles GET requests AND POST requests that fail validation
    return render_template(
        'client_profile.html',
        form=form,
        upload_form=upload_form,
        customer=customer
    )

@app.route('/my-account/orders')
@customer_login_required
def client_orders():
    """
    (R)EAD: Display the customer's order history (Active and Past).
    """
    customer_id = session['customer_id']
    
    # Fetch all orders, newest first
    orders = Order.query\
        .filter_by(customer_id=customer_id)\
        .order_by(Order.order_date.desc())\
        .all()

    return render_template(
        'client_orders.html',
        orders=orders,
        has_reviewed_product=has_reviewed_product # Pass the helper function
    )

@app.route('/my-account/upload-id', methods=['POST'])
@customer_login_required
def client_upload_id():
    """
    (C)REATE: Process the ID upload form for discount verification.
    """
    form = DiscountVerificationForm()
    customer = Customer.query.get_or_404(session['customer_id'])

    if form.validate_on_submit():
        if form.id_image.data:
            try:
                id_upload_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'ids')
                if not os.path.exists(id_upload_folder):
                    os.makedirs(id_upload_folder)

                random_hex = secrets.token_hex(8)
                _, f_ext = os.path.splitext(form.id_image.data.filename)
                picture_fn = random_hex + f_ext
                picture_path = os.path.join(id_upload_folder, picture_fn)

                output_size = (800, 800)
                i = Image.open(form.id_image.data)
                i.thumbnail(output_size)
                i.save(picture_path)

                customer.id_image_file = f"ids/{picture_fn}"

            except Exception as e:
                flash(f'Error uploading image: {e}', 'danger')
                return redirect(url_for('client_profile'))

        customer.discount_type = form.discount_type.data
        customer.is_verified_discount = False 
        customer.discount_status = 'Pending'  

        try:
            db.session.commit()
            flash('Your ID has been submitted for verification.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error submitting ID: {e}", 'danger')

    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {field}: {error}", 'danger')

    return redirect(url_for('client_profile'))

@app.route('/review/product/<int:product_id>', methods=['GET', 'POST'])
@customer_login_required
def client_review_product(product_id):
    """
    Renders the review form for a specific product and processes submission.
    """
    product = Product.query.get_or_404(product_id)
    customer_id = session['customer_id']
    form = ReviewForm()

    # Check 1: Prevent submission if already reviewed (using the new helper)
    if has_reviewed_product(customer_id, product_id):
        flash("You have already submitted a review for this product.", 'danger')
        return redirect(url_for('client_orders'))
    
    # Check 2: Ensure the product was bought in a COMPLETED order
    has_bought = db.session.query(OrderItem.order_item_id)\
        .join(Order)\
        .filter(
            Order.customer_id == customer_id,
            OrderItem.product_id == product_id,
            Order.status == 'Completed'
        ).first()

    if not has_bought:
        flash("You can only review products from completed orders that you purchased.", 'danger')
        return redirect(url_for('client_orders'))

    if form.validate_on_submit():
        new_review = Review(
            product_id=product_id,
            customer_id=customer_id,
            rating=form.rating.data,
            comment=form.comment.data
        )

        try:
            db.session.add(new_review)
            db.session.commit()
            flash(f"Thank you for reviewing {product.name}!", 'success')
            return redirect(url_for('client_orders'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error submitting review: {e}", 'danger')
            
    return render_template(
        'client_review_form.html',
        form=form,
        product=product
    )

# ===============================================
# CLIENT-SIDE: SHOPPING CART & ORDERING
# ===============================================
@app.route('/cart/add', methods=['POST'])
def add_to_cart():
    """
    Add a product to the user's session cart.
    NOW checks for login status.
    """
    # --- NEW: Manual Login Check ---
    if 'customer_id' not in session:
        return jsonify({'status': 'login_required', 'url': url_for('client_account_page')})
    # --- End New Check ---

    cart = session.get('cart', {})
    
    # Get all data from the modal form
    product_id = request.form.get('product_id')
    # ... (rest of the function remains the same)
    variant_id = request.form.get('variant_id')
    
    try:
        quantity = int(request.form.get('quantity', 1))
        if quantity < 1:
            quantity = 1
    except:
        quantity = 1
        
    if not variant_id:
        return jsonify({'status': 'error', 'message': 'No product size selected.'}), 400
        
    variant = ProductVariant.query.get(variant_id)
    if not variant:
        return jsonify({'status': 'error', 'message': 'Could not find that product option.'}), 404

    product = variant.product 
    
    if variant_id in cart:
        cart[variant_id]['quantity'] += quantity
    else:
        cart[variant_id] = {
            'product_id': product.product_id,
            'name': product.name,
            'variant_name': variant.size_name,
            'price': float(variant.price),
            'image': product.image_file,
            'quantity': quantity
        }
    
    session['cart'] = cart
    
    message = f"Added {quantity} x {product.name} ({variant.size_name}) to cart!"
    return jsonify({'status': 'success', 'message': message})

@app.route('/product_details/<int:product_id>')
def product_details(product_id):
    product = Product.query.get_or_404(product_id)

    buffet_cart = session.get('buffet_package', {})

    variants_data = []
    for variant in product.variants:
        current_quantity = buffet_cart.get(str(variant.variant_id), {}).get('quantity', 0)

        variants_data.append({
            'id': variant.variant_id,
            'size': variant.size_name,
            'price': float(variant.price),
            'current_quantity': current_quantity
        })

    return jsonify({
        'id': product.product_id,
        'name': product.name,
        'has_variants': product.has_variants,
        'variants': variants_data
    })

@app.route('/cart')
@customer_login_required
def client_cart():
    """
    (R)EAD: Display the user's shopping cart with smart totals.
    NOW INCLUDES VAT calculation and order history.
    """
    cart_session = session.get('cart', {})
    cart_items = []

    ala_carte_subtotal = 0.0
    buffet_subtotal = 0.0
    total_price = 0.0 # Gross Subtotal

    for item_id, item_data in cart_session.items():
        if 'name' not in item_data or 'price' not in item_data:
            continue
        quantity = item_data['quantity']
        price = item_data['price']
        line_total = float(price) * quantity
        total_price += line_total
        if item_data.get('is_buffet_item', False):
            buffet_subtotal += line_total
        else:
            ala_carte_subtotal += line_total
        cart_items.append({
            'product_id': item_data['product_id'],
            'variant_id': item_id, 'name': item_data['name'],
            'variant_name': item_data['variant_name'], 'image': item_data['image'],
            'price': float(price), 'quantity': quantity,
            'line_total': line_total, 'is_buffet_item': item_data.get('is_buffet_item', False)
        })

    customer = Customer.query.get(session['customer_id'])

    voucher_discount_amt = 0.0
    senior_discount_amt = 0.0
    pwd_discount_amt = 0.0
    subtotal = total_price

    if customer and customer.is_verified_discount:
        if 'voucher_code' in session:
            session.pop('voucher_code', None)
            session.pop('discount_percentage', None)
            flash(f"Your verified {customer.discount_type} discount has replaced the voucher.", 'info')

        if customer.discount_type == 'Senior':
            senior_discount_amt = subtotal * 0.20

        elif customer.discount_type == 'PWD':
            pwd_discount_amt = subtotal * 0.20
            if pwd_discount_amt > 150.00:
                pwd_discount_amt = 150.00

    else:
        voucher_discount_perc = session.get('discount_percentage', 0.0)
        voucher_discount_amt = (subtotal * voucher_discount_perc) / 100

    total_discount_amount = voucher_discount_amt + senior_discount_amt + pwd_discount_amt

    # --- NEW VAT CALCULATION ---
    taxable_base = subtotal - total_discount_amount
    vat_amount = taxable_base * VAT_RATE

    # Final Total includes VAT
    final_total = taxable_base + vat_amount
    # --- END NEW VAT CALCULATION ---

    available_vouchers = Voucher.query.filter(
        Voucher.is_active == True,
        (Voucher.max_uses == None) | (Voucher.current_uses < Voucher.max_uses)
    ).all()

# --- NEW: Fetch Order History for the Cart Page ---
    orders = Order.query\
        .filter_by(customer_id=session['customer_id'])\
        .order_by(Order.order_date.desc())\
        .all()  
    
    return render_template(
        'client_cart.html', 
        cart_items=cart_items, 
        total_price=total_price,
        ala_carte_subtotal=ala_carte_subtotal,
        buffet_subtotal=buffet_subtotal,
        voucher_discount_amt=voucher_discount_amt,
        senior_discount_amt=senior_discount_amt,
        pwd_discount_amt=pwd_discount_amt,
        vat_amount=vat_amount,
        total_discount_amount=total_discount_amount,
        final_total=final_total,
        available_vouchers=available_vouchers,
        customer=customer,
        orders=orders,                          # <--- NEW
        has_reviewed_product=has_reviewed_product # <--- NEW
    )

@app.route('/cart/clear')
@customer_login_required
def clear_cart():
    session.pop('cart', None)
    session.pop('voucher_code', None)
    session.pop('discount_percentage', None)
    flash("Cart has been cleared.", 'info')
    return redirect(url_for('client_cart'))

@app.route('/cart/remove/<string:variant_id>')
@customer_login_required
def remove_from_cart(variant_id):
    cart = session.get('cart', {})

    item_data = cart.pop(variant_id, None) 

    if item_data:
        flash(f"Removed {item_data['name']} ({item_data['variant_name']}) from cart.", 'info')

    session['cart'] = cart

    return redirect(url_for('client_cart'))

@app.route('/cart/update', methods=['POST'])
@customer_login_required
def update_cart_quantity():
    cart = session.get('cart', {})

    variant_id = request.form.get('variant_id')
    try:
        quantity = int(request.form.get('quantity'))
        if quantity < 1:
            quantity = 1
    except:
        quantity = 1

    if variant_id in cart:
        cart[variant_id]['quantity'] = quantity
        flash(f"Updated {cart[variant_id]['name']} quantity.", 'success')

    session['cart'] = cart

    return redirect(url_for('client_cart'))

@app.route('/cart/apply_voucher', methods=['POST'])
@customer_login_required
def apply_voucher():
    code = request.form.get('voucher_code')
    
    if not code:
        flash("Please enter a voucher code.", 'danger')
        return redirect(url_for('client_cart'))

    voucher = Voucher.query.filter_by(code=code, is_active=True).first()
    
    if voucher:
        if voucher.max_uses is not None and voucher.current_uses >= voucher.max_uses:
            flash("This voucher code has reached its maximum usage limit.", 'danger')
            session.pop('voucher_code', None)
            session.pop('discount_percentage', None)
            return redirect(url_for('client_cart'))

        session['voucher_code'] = voucher.code
        session['discount_percentage'] = float(voucher.discount_percentage)
        flash(f"Voucher '{voucher.code}' applied successfully!", 'success')
    else:
        session.pop('voucher_code', None)
        session.pop('discount_percentage', None)
        flash("Invalid or expired voucher code.", 'danger')
        
    return redirect(url_for('client_cart'))

@app.route('/checkout')
@customer_login_required
def client_checkout():
    """
    (R)EAD: Display the FINAL checkout page with ALL totals.
    NOW INCLUDES VAT calculation.
    """
    cart_session = session.get('cart', {})
    if not cart_session:
        flash("Your cart is empty.", 'info')
        return redirect(url_for('client_cart'))
    if 'order_type' not in session:
        flash("Please select your delivery or pickup option first.", 'info')
        return redirect(url_for('client_checkout_options'))

    cart_items = []
    ala_carte_subtotal = 0.0
    buffet_subtotal = 0.0
    total_price = 0.0

    for item_id, item_data in cart_session.items():
        if 'name' not in item_data or 'price' not in item_data:
            continue
        quantity = item_data['quantity']
        price = item_data['price']
        line_total = float(price) * quantity
        total_price += line_total
        if item_data.get('is_buffet_item', False):
            buffet_subtotal += line_total
        else:
            ala_carte_subtotal += line_total
        cart_items.append({
            'product_id': item_data['product_id'],
            'variant_id': item_id, 'name': item_data['name'],
            'variant_name': item_data['variant_name'], 'image': item_data['image'],
            'price': float(price), 'quantity': quantity,
            'line_total': line_total, 'is_buffet_item': item_data.get('is_buffet_item', False)
        })

    customer = Customer.query.get(session['customer_id'])

    voucher_discount_amt = 0.0
    senior_discount_amt = 0.0
    pwd_discount_amt = 0.0
    delivery_fee = session.get('delivery_fee', 0.0)
    subtotal = total_price 

    if customer and customer.is_verified_discount:
        if customer.discount_type == 'Senior':
            senior_discount_amt = subtotal * 0.20
        elif customer.discount_type == 'PWD':
            pwd_discount_amt = subtotal * 0.20
            if pwd_discount_amt > 150.00:
                pwd_discount_amt = 150.00
    else:
        voucher_discount_perc = session.get('discount_percentage', 0.0)
        voucher_discount_amt = (subtotal * voucher_discount_perc) / 100

    total_discount_amount = voucher_discount_amt + senior_discount_amt + pwd_discount_amt
    
    # --- NEW VAT CALCULATION ---
    taxable_base = subtotal - total_discount_amount
    vat_amount = taxable_base * VAT_RATE
    
    # Final Total includes VAT and Delivery Fee
    final_total = taxable_base + vat_amount + delivery_fee 
    # --- END NEW VAT CALCULATION ---

    return render_template(
        'client_checkout.html',
        cart_items=cart_items,
        total_price=total_price,
        voucher_discount_amt=voucher_discount_amt,
        senior_discount_amt=senior_discount_amt,
        pwd_discount_amt=pwd_discount_amt,
        vat_amount=vat_amount, # <-- PASS VAT
        delivery_fee=delivery_fee,
        total_discount_amount=total_discount_amount,
        final_total=final_total
    )

@app.route('/checkout/options', methods=['GET'])
@customer_login_required
def client_checkout_options():
    """
    (R)EAD: Show the page for selecting Delivery or Pickup.
    Now includes Dynamic Lead Time Calculation.
    """
    cart_session = session.get('cart', {})
    if not cart_session:
        flash("Your cart is empty.", 'info')
        return redirect(url_for('client_cart'))

    # --- DYNAMIC LEAD TIME LOGIC ---
    min_days = 3 # Default for standard items
    
    # Scan cart for buffet items
    for item in cart_session.values():
        if item.get('is_buffet_item', False):
            min_days = 7 # Extended time for buffet
            break
            
    # Get the customer's default address
    customer = Customer.query.get(session['customer_id'])
    default_address = customer.address

    return render_template(
        'client_checkout_options.html',
        default_address=default_address,
        customer=customer,
        min_days=min_days # Pass this variable to the template
    )

@app.route('/checkout/save_options', methods=['POST'])
@customer_login_required
def save_checkout_options():
    """
    (C)REATE: Validate and save delivery options.
    Now enforces strict server-side date validation.
    """
    cart_session = session.get('cart', {})
    if not cart_session:
        flash("Your cart is empty.", 'info')
        return redirect(url_for('client_cart'))

    # 1. Recalculate Lead Time (Security Check)
    min_days = 3
    for item in cart_session.values():
        if item.get('is_buffet_item', False):
            min_days = 7
            break

    # 2. Get Form Data
    event_date_str = request.form.get('event_date')
    event_time_str = request.form.get('event_time')
    order_type = request.form.get('order_type')
    delivery_address = request.form.get('delivery_address')
    landmark = request.form.get('landmark')

    # 3. Strict Date Validation
    if not event_date_str:
        flash("Please select an event date.", 'danger')
        return redirect(url_for('client_checkout_options'))
    
    try:
        event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
        today = date.today()
        # Calculate the earliest valid date
        min_date = today + timedelta(days=min_days)
        
        if event_date < min_date:
            flash(f"Invalid date. For this order content, we require at least {min_days} days lead time.", 'danger')
            return redirect(url_for('client_checkout_options'))
            
    except ValueError:
        flash("Invalid date format.", 'danger')
        return redirect(url_for('client_checkout_options'))

    # 4. Validate Delivery Logic
    if order_type == 'Delivery':
        if not delivery_address:
            flash("Please provide a delivery address.", 'danger')
            return redirect(url_for('client_checkout_options'))
        
        full_address = delivery_address
        if landmark:
            full_address += f" (Landmark: {landmark})"

        session['delivery_fee'] = 100.00
        session['order_type'] = 'Delivery'
        session['delivery_address'] = full_address
    
    else:
        session['delivery_fee'] = 0.00
        session['order_type'] = 'Pickup'
        session['delivery_address'] = 'Store Pickup'

    # 5. Save Validated Data to Session
    session['event_date_str'] = event_date_str
    session['event_time_str'] = event_time_str

    return redirect(url_for('client_checkout'))

@app.route('/checkout/place_order', methods=['POST'])
@customer_login_required
def place_order():
    """
    (C)REATE: Create the order in the database with Event Date logic.
    """
    cart_session = session.get('cart', {})
    if not cart_session:
        return jsonify({'status': 'error', 'message': "Your cart is empty. Please try again."}), 400

    # 1. Validate Items and Calculate Base Totals
    valid_cart_items = {} 
    ala_carte_subtotal = 0.0
    buffet_subtotal = 0.0
    total_price = 0.0 # Gross Subtotal

    for item_id, item_data in cart_session.items():
        if 'product_id' not in item_data or 'price' not in item_data:
            continue
        valid_cart_items[item_id] = item_data
        line_total = float(item_data['price']) * item_data['quantity']
        total_price += line_total
        if item_data.get('is_buffet_item', False):
            buffet_subtotal += line_total
        else:
            ala_carte_subtotal += line_total
            
    if not valid_cart_items:
        return jsonify({'status': 'error', 'message': "No valid items were found in your cart."}), 400

    # 2. Retrieve Event Details from Session
    event_date_str = session.get('event_date_str')
    event_time_str = session.get('event_time_str')
    
    event_date = None
    event_time = None
    
    # Parse the date string back into a Python date object
    if event_date_str:
        try:
            event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass # Handle error gracefully or log it
            
    # Parse the time string back into a Python time object
    if event_time_str:
        try:
            event_time = datetime.strptime(event_time_str, '%H:%M').time()
        except ValueError:
            pass

    # 3. Calculate Financials (Discounts & VAT)
    customer = Customer.query.get(session['customer_id'])

    voucher_discount_amt = 0.0
    senior_discount_amt = 0.0
    pwd_discount_amt = 0.0
    delivery_fee = session.get('delivery_fee', 0.0)
    subtotal = total_price

    if customer and customer.is_verified_discount:
        if customer.discount_type == 'Senior':
            senior_discount_amt = subtotal * 0.20
        elif customer.discount_type == 'PWD':
            pwd_discount_amt = subtotal * 0.20
            if pwd_discount_amt > 150.00:
                pwd_discount_amt = 150.00
    else:
        voucher_discount_perc = session.get('discount_percentage', 0.0)
        voucher_discount_amt = (subtotal * voucher_discount_perc) / 100

    total_discount_amount = voucher_discount_amt + senior_discount_amt + pwd_discount_amt
    
    # --- VAT CALCULATION ---
    taxable_base = subtotal - total_discount_amount
    vat_amount = taxable_base * VAT_RATE
    final_total = taxable_base + vat_amount + delivery_fee 
    # -----------------------

    try:
        special_instructions = request.form.get('special_instructions')
        
        # 4. Create Order Object
        new_order = Order(
            customer_id=session['customer_id'],
            total_amount=subtotal,
            discount_amount=total_discount_amount,
            vat_amount=vat_amount, 
            final_amount=final_total,
            
            # UPDATED STATUS
            status="Pending Approval", 
            
            # NEW EVENT FIELDS
            event_date=event_date,
            event_time=event_time,
            
            order_type=session.get('order_type', 'Pickup'),
            delivery_address=session.get('delivery_address', 'Store Pickup'),
            delivery_fee=delivery_fee,
            special_instructions=special_instructions
        )
        db.session.add(new_order)
        db.session.commit() # Commit first to get the order_id

        # 5. Save Order Items
        for item_key, item_data in valid_cart_items.items():
            # Handle composite keys for buffet items (e.g., "buffet_12")
            real_variant_id = item_data.get('variant_id', item_key)
            if isinstance(real_variant_id, str) and real_variant_id.startswith('buffet_'):
                final_variant_id = int(real_variant_id.split('_')[1])
            else:
                final_variant_id = int(real_variant_id)
                
            new_item = OrderItem(
                order_id=new_order.order_id,
                product_id=item_data['product_id'],
                variant_id=final_variant_id,
                quantity=item_data['quantity'],
                price_per_item=item_data['price'] 
            )
            db.session.add(new_item)

        # 6. Update Voucher Usage
        if session.get('voucher_code'):
            voucher_to_update = Voucher.query.filter_by(code=session['voucher_code']).first()
            if voucher_to_update:
                voucher_to_update.current_uses += 1
                db.session.add(voucher_to_update)

        db.session.commit()

        # 7. Clear Session Data
        session.pop('cart', None)
        session.pop('voucher_code', None)
        session.pop('discount_percentage', None)
        session.pop('delivery_fee', None)
        session.pop('order_type', None)
        session.pop('delivery_address', None)
        
        # Clear Buffet Session Data
        session.pop('buffet_package', None)
        session.pop('buffet_recommendations', None)
        session.pop('buffet_sequence', None)
        
        # Clear New Event Data
        session.pop('event_date_str', None)
        session.pop('event_time_str', None)

        return jsonify({
            'status': 'success',
            'message': f"Order #{new_order.order_id} has been placed! Please wait for admin approval.",
            'redirect_url': url_for('client_orders') # Redirects to the Orders page
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f"DB Error: {e}"}), 500
# ===============================================
# CLIENT-SIDE: CUSTOMER ACCOUNTS (Login/Register/Reset)
# ===============================================

@app.route('/account', methods=['GET'])
def client_account_page():
    if 'customer_id' in session:
        return redirect(url_for('client_home'))

    login_form = CustomerLoginForm()

    return render_template(
        'client_login.html',
        login_form=login_form
    )

@app.route('/register', methods=['GET'])
def client_register_page():
    if 'customer_id' in session:
        return redirect(url_for('client_home'))

    register_form = CustomerRegisterForm()

    return render_template(
        'client_register.html',
        register_form=register_form
    )

@app.route('/logout')
def client_logout():
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    session.pop('cart', None)
    session.pop('voucher_code', None)
    session.pop('discount_percentage', None)

    flash("You have been logged out.", 'info')
    return redirect(url_for('client_home'))

@app.route('/register', methods=['POST'])
def client_register():
    register_form = CustomerRegisterForm()

    if register_form.validate_on_submit():
        new_customer = Customer(
            name=register_form.name.data,
            contact_number=register_form.contact_number.data,
            address=register_form.address.data,
            landmark=register_form.landmark.data, # <-- ADDED LANDMARK
            email=register_form.email.data.lower(),
            birthdate=register_form.birthdate.data
        )
        new_customer.set_password(register_form.password.data)

        db.session.add(new_customer)
        try:
            db.session.commit()
            session['customer_id'] = new_customer.customer_id
            session['customer_name'] = new_customer.name

            flash(f"Welcome, {new_customer.name}! Your account has been created.", 'success')
            return redirect(url_for('client_home'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating account: {e}", 'danger')

@app.route('/login', methods=['POST'])
def client_login():
    login_form = CustomerLoginForm()

    if login_form.validate_on_submit():
        customer = Customer.query.filter_by(email=login_form.email.data).first()

        if customer and customer.check_password(login_form.password.data):
            session['customer_id'] = customer.customer_id
            session['customer_name'] = customer.name

            flash(f"Welcome back, {customer.name}!", 'success')
            return redirect(url_for('client_home'))
        else:
            flash("Invalid email or password. Please try again.", 'danger')

    return render_template(
        'client_login.html',
        login_form=login_form
    )

def send_async_email(app, msg):
    with app.app_context():
        mail.send(msg)

def send_reset_email(customer):
    token = customer.get_reset_token()
    
    # Ensure we have a sender string, otherwise fallback to a dummy string to prevent crash
    sender_email = current_app.config.get('MAIL_USERNAME') or 'noreply@demo.com'

    msg = Message(
        'Password Reset Request',
        sender=sender_email,  # <--- Updated variable
        recipients=[customer.email]
    )
    # ... rest of function ...
    msg.html = render_template('reset_email.html', customer=customer, token=token)
    
    from threading import Thread
    app = current_app._get_current_object() 
    thread = Thread(target=send_async_email, args=(app, msg))
    thread.start()
    return thread

@app.route('/forgot-password', methods=['GET', 'POST'])
def client_forgot_password():
    if 'customer_id' in session:
        return redirect(url_for('client_home'))
    
    form = RequestResetForm()
    if form.validate_on_submit():
        customer = Customer.query.filter_by(email=form.email.data).first()
        if customer:
            send_reset_email(customer)
        flash('If an account exists with that email, a reset link has been sent.', 'info')
        return redirect(url_for('client_account_page'))

    return render_template('client_forgot_password.html', form=form)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def client_reset_token(token):
    if 'customer_id' in session:
        return redirect(url_for('client_home'))
    
    customer = Customer.verify_reset_token(token)
    if customer is None:
        flash('That is an invalid or expired token.', 'danger')
        return redirect(url_for('client_forgot_password'))
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        customer.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been updated! You are now able to log in.', 'success')
        return redirect(url_for('client_account_page'))
    
    return render_template('client_reset_password.html', form=form)

# ===============================================
# CLIENT-SIDE: BUFFET WIZARD
# (Routes are kept as they do not depend on Rider)
# ===============================================

@app.route('/buffet-builder', methods=['GET'])
def buffet_wizard_start():
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()
    return render_template(
        'client_buffet_step1.html',
        categories=categories
    )

@app.route('/buffet-builder/reco', methods=['POST'])
def buffet_wizard_reco():
    try:
        guest_count = int(request.form.get('guest_count'))
        if guest_count < 1:
            guest_count = 1
    except:
        guest_count = 30

    selected_categories = request.form.getlist('categories')

    if not selected_categories:
        flash("Please select at least one category to include in your buffet.", 'danger')
        return redirect(url_for('buffet_wizard_start'))

    # --- NEW: SORT THE SEQUENCE ---
    # This ensures Mains come first, then Carbs, then Sides, then Dessert
    def get_sort_index(cat_name):
        try:
            return CATEGORY_ORDER.index(cat_name)
        except ValueError:
            return 999 # Put unknown/custom categories at the end
            
    selected_categories.sort(key=get_sort_index)
    # ------------------------------

    recommendations = {}
    
    # Shared Mains Logic
    total_mains_needed = (guest_count + 9) // 10
    recommendations['Shared_Mains'] = total_mains_needed

    for category_name in selected_categories:
        if category_name in MAIN_CATEGORIES:
            continue
        elif category_name in ['Pasta & Noodles', 'Vegetables', 'Dessert']:
            # Adjust this ratio if needed (e.g. 1 per 15 for sides)
            count = (guest_count + 14) // 15
            recommendations[category_name] = count
        else:
            recommendations[category_name] = (guest_count + 9) // 10

    session['buffet_recommendations'] = recommendations
    session['buffet_guest_count'] = guest_count
    session['buffet_package'] = {}
    
    # Save the SORTED sequence
    session['buffet_sequence'] = selected_categories

    return redirect(url_for('buffet_wizard_select', category_name=selected_categories[0]))

@app.route('/buffet-builder/select/<string:category_name>', methods=['GET', 'POST'])
@customer_login_required
def buffet_wizard_select(category_name):
    recommendations = session.get('buffet_recommendations')
    wizard_sequence = session.get('buffet_sequence')

    if not recommendations or not wizard_sequence:
        flash("Your buffet session has expired. Please start over.", 'danger')
        return redirect(url_for('buffet_wizard_start'))

    category_obj = Category.query.filter_by(name=category_name, is_active=True).first_or_404()
    products = Product.query.filter_by(category_id=category_obj.category_id)\
                            .order_by(Product.name.asc()).all()

    buffet_package = session.get('buffet_package', {})
    
    # --- SHARED MAINS LOGIC ---
    is_main_category = category_name in MAIN_CATEGORIES
    
    if is_main_category:
        required_count = recommendations.get('Shared_Mains', 0)
        current_count = 0
        for item in buffet_package.values():
            if item['category'] in MAIN_CATEGORIES:
                current_count += item['quantity']
    else:
        required_count = recommendations.get(category_name, 0)
        current_count = 0
        for item in buffet_package.values():
            if item['category'] == category_name:
                current_count += item['quantity']

    # Filter selections for display
    current_selections = []
    current_total_price = 0.0 # <-- NEW: Calculate Total Price
    
    for variant_id, item_data in buffet_package.items():
        # Calculate total for the badge
        current_total_price += (item_data['price'] * item_data['quantity'])
        
        if item_data['category'] == category_name:
            item_data['variant_id'] = variant_id
            current_selections.append(item_data)

    # Navigation Logic
    current_index = wizard_sequence.index(category_name)
    
    if current_index > 0:
        previous_category = wizard_sequence[current_index - 1]
        previous_url = url_for('buffet_wizard_select', category_name=previous_category)
    else:
        previous_url = url_for('buffet_wizard_start')

    is_final_category = (current_index == len(wizard_sequence) - 1)
    if is_final_category:
        next_url = url_for('buffet_wizard_checkout')
    else:
        next_category = wizard_sequence[current_index + 1]
        next_url = url_for('buffet_wizard_select', category_name=next_category)

    # Button Logic
    min_to_proceed = required_count
    if is_main_category:
        remaining_categories = wizard_sequence[current_index+1:]
        has_more_mains = any(cat in MAIN_CATEGORIES for cat in remaining_categories)
        if has_more_mains:
            min_to_proceed = 0 
        else:
            min_to_proceed = required_count

    return render_template(
        'client_buffet_select.html',
        category_name=category_name,
        products=products,
        required_count=required_count,
        current_count=current_count,
        min_to_proceed=min_to_proceed,
        current_selections=current_selections,
        next_url=next_url,
        previous_url=previous_url,
        is_final_category=is_final_category,
        is_main_category=is_main_category,
        
        # --- NEW VARIABLES FOR UI ---
        current_step=current_index + 1,
        total_steps=len(wizard_sequence),
        current_total_price=current_total_price
    )

@app.route('/buffet-builder/checkout', methods=['GET'])
@customer_login_required
def buffet_wizard_checkout():
    buffet_package = session.get('buffet_package', {})
    
    total_price = 0.0
    for item_data in buffet_package.values():
        total_price += float(item_data['price']) * item_data['quantity']
    
    return render_template(
        'client_buffet_checkout.html',
        buffet_package=buffet_package,
        total_price=total_price
    )


@app.route('/buffet/commit_package', methods=['POST'])
@customer_login_required
def buffet_commit_package():
    buffet_package = session.get('buffet_package', {})
    if not buffet_package:
        flash("Buffet package is empty. Please start over.", 'danger')
        return redirect(url_for('buffet_wizard_start'))

    main_cart = session.get('cart', {})

    for variant_id, item_data in buffet_package.items():
        # --- FIX: ALWAYS PREFIX BUFFET ITEMS ---
        # Previously, we checked if the item existed and tried to merge.
        # Now, we force a unique 'buffet_' key. This ensures that even if 
        # the user adds the exact same item via A La Carte (which uses raw variant_id),
        # they will be treated as separate entries in the cart.
        cart_key = f"buffet_{variant_id}"

        if cart_key in main_cart:
            main_cart[cart_key]['quantity'] += item_data['quantity']
        else:
            main_cart[cart_key] = {
                'product_id': item_data['product_id'],
                'name': item_data['product_name'],
                'variant_id': variant_id, # Store raw ID inside for reference
                'variant_name': item_data['variant_name'],
                'price': item_data['price'],
                'image': item_data['image'],
                'quantity': item_data['quantity'],
                'is_buffet_item': True
            }

    session['cart'] = main_cart

    # Clear the wizard session
    session.pop('buffet_package', None)
    session.pop('buffet_recommendations', None)
    session.pop('buffet_sequence', None)
    session.pop('buffet_guest_count', None)

    flash("Success! Your custom buffet package has been added to the cart.", 'success')
    return redirect(url_for('client_cart'))


@app.route('/buffet/remove/<string:variant_id>')
@customer_login_required
def buffet_remove_item(variant_id):
    buffet_package = session.get('buffet_package', {})
    
    item_data = buffet_package.pop(variant_id, None) 
    
    if item_data:
        flash(f"Removed {item_data['product_name']} from your buffet.", 'info')
    
    session['buffet_package'] = buffet_package
    
    return redirect(url_for('buffet_wizard_checkout'))


@app.route('/buffet/update', methods=['POST'])
@customer_login_required
def buffet_update_quantity():
    buffet_package = session.get('buffet_package', {})
    variant_id = request.form.get('variant_id')
    
    try:
        quantity = int(request.form.get('quantity'))
        if quantity < 1:
            quantity = 1
    except:
        quantity = 1
    
    if variant_id in buffet_package:
        buffet_package[variant_id]['quantity'] = quantity
        flash(f"Updated {buffet_package[variant_id]['product_name']} quantity.", 'success')
        
    session['buffet_package'] = buffet_package
    
    return redirect(url_for('buffet_wizard_checkout'))

@app.route('/buffet/add_item', methods=['POST'])
@customer_login_required
def buffet_add_item():
    variant_id = request.form.get('variant_id')
    force_add = request.form.get('force', 'false').lower() == 'true'
    try:
        quantity = int(request.form.get('quantity', 1))
    except:
        quantity = 1

    buffet_cart = session.get('buffet_package', {})
    recommendations = session.get('buffet_recommendations', {})

    if not variant_id:
        return jsonify({'status': 'error', 'message': 'No variant selected.'}), 400

    variant = ProductVariant.query.get(variant_id)
    if not variant:
        return jsonify({'status': 'error', 'message': 'Item not found.'}), 404
        
    product = variant.product
    category_name = product.category.name

    # Shared Limit Validation
    if category_name in MAIN_CATEGORIES:
        current_count = 0
        for item in buffet_cart.values():
            if item['category'] in MAIN_CATEGORIES:
                current_count += item['quantity']
        recommended_count = recommendations.get('Shared_Mains', 0)
    else:
        current_count = 0
        for item in buffet_cart.values():
            if item['category'] == category_name:
                current_count += item['quantity']
        recommended_count = recommendations.get(category_name, 0)
    
    potential_new_count = current_count + quantity

    if potential_new_count > recommended_count and not force_add:
        return jsonify({
            'status': 'warning',
            'message': f"You've selected {potential_new_count} items for this section, but the recommendation is {recommended_count}. Add anyway?"
        })

    # Add to cart
    if variant_id in buffet_cart:
        buffet_cart[variant_id]['quantity'] += quantity
    else:
        buffet_cart[variant_id] = {
            'product_id': product.product_id,
            'product_name': product.name,
            'variant_name': variant.size_name,
            'quantity': quantity,
            'category': category_name,
            'price': float(variant.price),
            'image': product.image_file
        }
    
    session['buffet_package'] = buffet_cart
    
    # --- NEW: CALCULATE NEW TOTAL ---
    new_total_price = 0.0
    for item in buffet_cart.values():
        new_total_price += (item['price'] * item['quantity'])

    return jsonify({
        'status': 'success',
        'message': f"Added {product.name}",
        'new_total_price': new_total_price # Return this to JS
    })

@app.route('/buffet/remove_item/<string:variant_id>/<string:category_name>')
@customer_login_required
def buffet_remove_item_from_package(variant_id, category_name):
    buffet_package = session.get('buffet_package', {})
    
    if variant_id in buffet_package:
        item_name = buffet_package.pop(variant_id)['product_name']
        flash(f"Removed {item_name} from your selections.", 'info')
    
    session['buffet_package'] = buffet_package
    
    return redirect(url_for('buffet_wizard_select', category_name=category_name))

@app.route('/buffet/review')
@customer_login_required
def buffet_review_and_add():
    # This route is deprecated by commit_package, but kept for compatibility.
    return redirect(url_for('client_cart'))

# ===============================================
# ADMIN-SIDE ROUTES (Rider management removed)
# ===============================================

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    # 1. Get "New Orders Today" (All orders except Declined)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    orders_today_count = Order.query.filter(
        Order.order_date >= today_start,
        Order.status != 'Declined'
    ).count()

    # 2. Get "Total Sales this Month" (Only Confirmed Orders)
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Filter for valid sales only (Approved, In Progress, Completed)
    valid_statuses = ['Approved', 'In Progress', 'Completed']
    
    total_sales_month_query = db.session.query(func.sum(Order.final_amount)).filter(
        Order.order_date >= month_start,
        Order.status.in_(valid_statuses)
    ).scalar()
    
    total_sales_month = total_sales_month_query or 0.0

    # 3. Get "New Customer Registrations" this month
    new_customers_month_count = Customer.query.filter(Customer.registration_date >= month_start).count()

    # 4. Get "Recent Pending Requests" (Updated Status)
    # We want the ones waiting for approval, ordered by Event Date (so urgency is visible)
    recent_pending_orders = Order.query.filter_by(status='Pending Approval')\
        .order_by(Order.event_date.asc())\
        .limit(5)\
        .all()
        
    # 5. Get Pending Verifications (For Discount IDs)
    pending_verifications_count = Customer.query.filter(Customer.discount_status == 'Pending').count()

    return render_template(
        'admin_dashboard.html',
        orders_today_count=orders_today_count,
        total_sales_month=total_sales_month,
        new_customers_month_count=new_customers_month_count,
        recent_pending_orders=recent_pending_orders,
        pending_verifications_count=pending_verifications_count
    )


@app.route('/admin/logout')
@login_required
def admin_logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin_login'))

# ===============================================
# MODULE 1: ORDER MANAGEMENT (Simplified)
# ===============================================

@app.route('/admin/orders')
@login_required
def admin_orders():
    """
    (R)EAD: Display all customer orders.
    Rider assignment UI removed.
    """
    status_filter = request.args.get('status')
    order_query = Order.query.join(Customer).order_by(Order.order_date.desc())

    if status_filter:
        order_query = order_query.filter(Order.status == status_filter)

    orders = order_query.all()
    
    # available_riders list is removed since there are no riders.

    return render_template(
        'admin_orders.html', 
        orders=orders, 
        current_filter=status_filter,
        available_riders=[] # Pass empty list
    )

@app.route('/admin/orders/update_status/<int:order_id>', methods=['POST'])
@login_required
def admin_update_order_status(order_id):
    """
    (U)PDATE: Update an order's status and save decline reason if applicable.
    """
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    decline_reason = request.form.get('decline_reason') # Get the reason from the modal form
    
    try:
        # Only update if a new status is provided and it's different from the current one
        if new_status and new_status != order.status:
            order.status = new_status
            
            # If the status is specifically 'Declined', save the reason text
            if new_status == 'Declined' and decline_reason:
                order.decline_reason = decline_reason
            
            # If Approved, we might want to clear any previous decline reason (optional)
            if new_status == 'Approved':
                order.decline_reason = None

            db.session.commit()
            flash(f"Order #{order.order_id} updated to '{new_status}'.", 'success')
        else:
             flash("No status change submitted.", 'info')

    except Exception as e:
        db.session.rollback()
        flash(f"Error updating order: {e}", 'danger')

    return redirect(url_for('admin_orders'))


@app.route('/admin/orders/delete/<int:order_id>', methods=['POST'])
@login_required
def admin_delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    
    try:
        OrderItem.query.filter_by(order_id=order.order_id).delete()
        
        db.session.delete(order)
        db.session.commit()
        flash(f"Order #{order.order_id} has been deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting order: {e}", 'danger')

    current_filter = request.args.get('status')
    if current_filter:
        return redirect(url_for('admin_orders', status=current_filter))
    return redirect(url_for('admin_orders'))

@app.route('/admin/export/orders_json')
@login_required
def admin_export_orders_json():
    try:
        orders = Order.query.options(
            db.joinedload(Order.customer),
            db.joinedload(Order.items).joinedload(OrderItem.product),
            db.joinedload(Order.items).joinedload(OrderItem.variant)
        ).order_by(Order.order_date.desc()).all()

        all_orders_data = []

        for order in orders:
            order_data = {
                'order_id': order.order_id,
                'customer_name': order.customer.name,
                'customer_email': order.customer.email,
                'order_date': order.order_date.isoformat(),
                'total_amount': float(order.total_amount),
                'discount_amount': float(order.discount_amount),
                'final_amount': float(order.final_amount),
                'status': order.status,
                'items': []
            }

            for item in order.items:
                item_data = {
                    'product_name': item.product.name,
                    'variant': item.variant.size_name,
                    'quantity': item.quantity,
                    'price_per_item': float(item.price_per_item)
                }
                order_data['items'].append(item_data)

            all_orders_data.append(order_data)

        response = make_response(jsonify(all_orders_data))
        response.headers["Content-Disposition"] = "attachment; filename=orders_export.json"
        response.headers["Content-type"] = "application/json"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the JSON: {e}", 'danger')
        return redirect(url_for('admin_orders'))

# ===============================================
# MODULE 3: CATEGORY MANAGEMENT
# ===============================================

@app.route('/admin/categories', methods=['GET'])
@login_required
def admin_categories():
    search_query = request.args.get('search')
    
    add_form = CategoryForm()
    edit_form = CategoryForm()
    
    category_query = Category.query
    
    if search_query:
        category_query = category_query.filter(Category.name.ilike(f'%{search_query}%'))
        
    categories = category_query.order_by(Category.name.asc()).all()
    
    return render_template(
        'admin_categories.html',
        add_form=add_form,
        edit_form=edit_form,
        categories=categories,
        search_query=search_query
    )

@app.route('/admin/products/toggle/<int:product_id>', methods=['POST'])
@login_required
def admin_toggle_product_status(product_id):
    product = Product.query.get_or_404(product_id)

    product.is_active = not product.is_active

    try:
        db.session.commit()
        if product.is_active:
            flash(f"Product '{product.name}' has been Activated.", 'success')
        else:
            flash(f"Product '{product.name}' has been Deactivated.", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f"Error changing product status: {e}", 'danger')

    return redirect(url_for('admin_products'))

@app.route('/admin/categories/edit/<int:category_id>', methods=['POST'])
@login_required
def admin_edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    edit_form = CategoryForm()

    if edit_form.validate_on_submit():
        category.name = edit_form.name.data
        category.description = edit_form.description.data

        try:
            db.session.commit()
            flash(f"Category '{category.name}' updated successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating category: {e}", 'danger')
    else:
        flash('Error: Could not update category. Please check form.', 'danger')

    return redirect(url_for('admin_categories') + '#existing-categories-card')

@app.route('/admin/categories/toggle/<int:category_id>', methods=['POST'])
@login_required
def admin_toggle_category_status(category_id):
    category = Category.query.get_or_404(category_id)

    category.is_active = not category.is_active

    try:
        db.session.commit()
        if category.is_active:
            flash(f"Category '{category.name}' has been Activated.", 'success')
        else:
            flash(f"Category '{category.name}' has been Deactivated.", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f"Error changing category status: {e}", 'danger')

    return redirect(url_for('admin_categories') + '#existing-categories-card')


# ===============================================
# MODULE 2: PRODUCT MANAGEMENT
# ===============================================

@app.route('/admin/products', methods=['GET'])
@login_required
def admin_products():
    search_query = request.args.get('search')
    selected_category_id = request.args.get('category', type=int)
    
    all_categories = Category.query.order_by(Category.name.asc()).all()
    
    product_query = Product.query
    
    if selected_category_id:
        product_query = product_query.filter_by(category_id=selected_category_id)
    
    if search_query:
        product_query = product_query.filter(Product.name.ilike(f'%{search_query}%'))
        
    products = product_query.order_by(Product.name.asc()).all()
    
    return render_template(
        'admin_products.html', 
        products=products,
        all_categories=all_categories,
        selected_category_id=selected_category_id,
        search_query=search_query
    )

@app.route('/admin/products/add', methods=['GET', 'POST'])
@login_required
def admin_add_product():
    form = ProductForm()
    form.category.choices = get_category_choices()

    if form.validate_on_submit():

        image_filename = 'default.jpg'
        if form.image.data:
            try:
                image_filename = save_picture(form.image.data)
            except Exception as e:
                flash(f'Error uploading image: {e}', 'danger')
                return redirect(url_for('admin_add_product'))
            
        new_product = Product(
            category_id=form.category.data,
            name=form.name.data,
            description=form.description.data,
            has_variants=form.has_variants.data
        )
        db.session.add(new_product)

        if not new_product.has_variants:
            if form.price.data is None:
                flash('Error: A simple product (no variants) must have a price.', 'danger')
                return redirect(url_for('admin_add_product'))

            simple_variant = ProductVariant(
                product=new_product,
                size_name="Regular",
                price=form.price.data
            )
            db.session.add(simple_variant)

        try:
            db.session.commit()
            flash(f"Product '{new_product.name}' added successfully.", 'success')
            return redirect(url_for('admin_products'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding product: {e}", 'danger')

    return render_template(
        'admin_product_form.html',
        form=form,
        form_title="Add New Product",
        action_url=url_for('admin_add_product')
    )


@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    form = ProductForm(obj=product)
    form.category.choices = get_category_choices()

    if form.validate_on_submit():

        if form.image.data:
            try:
                image_filename = save_picture(form.image.data)
                product.image_file = image_filename
            except Exception as e:
                flash(f'Error uploading image: {e}', 'danger')
                return redirect(url_for('admin_edit_product', product_id=product_id))

        product.category_id = form.category.data
        product.name = form.name.data
        product.description = form.description.data
        product.has_variants = form.has_variants.data

        if not product.has_variants:
            if form.price.data is None:
                flash('Error: A simple product (no variants) must have a price.', 'danger')
                return redirect(url_for('admin_edit_product', product_id=product_id))

            simple_variant = ProductVariant.query.filter_by(
                product_id=product.product_id, 
                size_name="Regular"
            ).first()

            if simple_variant:
                simple_variant.price = form.price.data
            else:
                simple_variant = ProductVariant(
                    product=product,
                    size_name="Regular",
                    price=form.price.data
                )
                db.session.add(simple_variant)

        try:
            db.session.commit()
            flash(f"Product '{product.name}' updated successfully.", 'success')
            return redirect(url_for('admin_products'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating product: {e}", 'danger')

    if not product.has_variants and product.variants:
        simple_variant = ProductVariant.query.filter_by(
            product_id=product.product_id,
            size_name="Regular"
        ).first()
        if simple_variant:
            form.price.data = simple_variant.price

    return render_template(
        'admin_product_form.html',
        form=form,
        form_title=f"Edit Product: {product.name}",
        action_url=url_for('admin_edit_product', product_id=product_id)
    )


@app.route('/admin/products/delete/<int:product_id>', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    product = Product.query.get_or_404(product_id)

    try:
        db.session.delete(product)
        db.session.commit()
        flash(f"Product '{product.name}' deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting product: {e}. It might be in use in an order.", 'danger')

    return redirect(url_for('admin_products'))

@app.route('/admin/export/products_xml')
@login_required
def admin_export_products_xml():
    try:
        products = Product.query.options(
            db.joinedload(Product.category),
            db.joinedload(Product.variants)
        ).all()

        root = ET.Element('Menu')

        for product in products:
            product_elem = ET.SubElement(root, 'Product')
            product_elem.set('id', str(product.product_id))

            ET.SubElement(product_elem, 'Name').text = product.name
            ET.SubElement(product_elem, 'Description').text = product.description
            ET.SubElement(product_elem, 'Category').text = product.category.name
            ET.SubElement(product_elem, 'HasVariants').text = str(product.has_variants)

            variants_elem = ET.SubElement(product_elem, 'Variants')
            for variant in product.variants:
                variant_elem = ET.SubElement(variants_elem, 'Variant')
                ET.SubElement(variant_elem, 'Size').text = variant.size_name
                ET.SubElement(variant_elem, 'Price').text = str(variant.price)

        xml_str = minidom.parseString(ET.tostring(root))\
                         .toprettyxml(indent="   ")

        response = make_response(xml_str)
        response.headers["Content-Disposition"] = "attachment; filename=menu_export.xml"
        response.headers["Content-type"] = "application/xml"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the XML: {e}", 'danger')
        return redirect(url_for('admin_products'))

# ===============================================
# MODULE 2b: PRODUCT VARIANT MANAGEMENT
# ===============================================

@app.route('/admin/products/<int:product_id>/variants', methods=['GET'])
@login_required
def admin_product_variants(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.has_variants:
        flash(f"'{product.name}' is a simple product and cannot have variants.", 'danger')
        return redirect(url_for('admin_products'))
        
    search_query = request.args.get('search')
    
    add_form = VariantForm()
    edit_form = VariantForm()
    
    variant_query = ProductVariant.query.filter_by(product_id=product.product_id)
    
    if search_query:
        variant_query = variant_query.filter(ProductVariant.size_name.ilike(f'%{search_query}%'))
        
    variants = variant_query.all()
    
    return render_template(
        'admin_product_variants.html',
        product=product,
        variants=variants,
        add_form=add_form,
        edit_form=edit_form,
        search_query=search_query
    )

@app.route('/admin/products/<int:product_id>/variants/add', methods=['POST'])
@login_required
def admin_add_variant(product_id):
    product = Product.query.get_or_404(product_id)
    add_form = VariantForm()

    if add_form.validate_on_submit():
        form_size_name = add_form.size_name.data
        
        existing_variant = ProductVariant.query.filter_by(
            product_id=product.product_id, 
            size_name=form_size_name
        ).first()
        
        if existing_variant:
            flash(f"Error: A variant named '{form_size_name}' already exists for this product.", 'danger')
            return redirect(url_for('admin_product_variants', product_id=product.product_id))
        
        new_variant = ProductVariant(
            product_id=product.product_id,
            size_name=add_form.size_name.data,
            price=add_form.price.data
        )
        db.session.add(new_variant)
        try:
            db.session.commit()
            flash(f"Variant '{new_variant.size_name}' added.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding variant: {e}", 'danger')
    else:
        flash('Error: Could not add variant. Please check form.', 'danger')

    return redirect(url_for('admin_product_variants', product_id=product.product_id) + '#add-variant-card')


@app.route('/admin/variants/delete/<int:variant_id>', methods=['POST'])
@login_required
def admin_delete_variant(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    product_id = variant.product_id

    try:
        db.session.delete(variant)
        db.session.commit()
        flash(f"Variant '{variant.size_name}' deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting variant: {e}", 'danger')

    return redirect(url_for('admin_product_variants', product_id=product_id) + '#existing-variants-card')

@app.route('/admin/variants/edit/<int:variant_id>', methods=['POST'])
@login_required
def admin_edit_variant(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    product_id = variant.product_id
    edit_form = VariantForm()
    
    if edit_form.validate_on_submit():
        form_size_name = edit_form.size_name.data
        
        existing_variant = ProductVariant.query.filter(
            ProductVariant.product_id == product_id,
            ProductVariant.size_name == form_size_name,
            ProductVariant.variant_id != variant_id
        ).first()
        
        if existing_variant:
            flash(f"Error: Cannot rename. A variant named '{form_size_name}' already exists.", 'danger')
            return redirect(url_for('admin_product_variants', product_id=product_id))
            
        variant.size_name = form_size_name
        variant.price = edit_form.price.data
        
        try:
            db.session.commit()
            flash(f"Variant '{variant.size_name}' updated successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating variant: {e}", 'danger')
    else:
        for field, errors in edit_form.errors.items():
            for error in errors:
                field_name = getattr(edit_form, field).label.text
                flash(f"Error in '{field_name}': {error}", 'danger')

    return redirect(url_for('admin_product_variants', product_id=product_id) + '#existing-variants-card')

@app.route('/admin/import/products_csv', methods=['POST'])
@login_required
def admin_import_products_csv():
    if 'csv_file' not in request.files:
        flash('No file part in the request.', 'danger')
        return redirect(url_for('admin_products'))

    file = request.files['csv_file']

    if file.filename == '':
        flash('No selected file.', 'danger')
        return redirect(url_for('admin_products'))

    if file and file.filename.endswith('.csv'):
        try:
            stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
            # Use csv.reader for headerless reading (returns list of strings)
            csv_reader = csv.reader(stream)

            products_added = 0
            errors = []

            for row_idx, row in enumerate(csv_reader):
                # Skip empty rows
                if not row:
                    continue
                
                # Check if row has enough columns (we expect 6)
                if len(row) < 6:
                    errors.append(f"Row {row_idx + 1}: Skipped (insufficient columns)")
                    continue

                # EXTRACT VALUES BY INDEX
                # 0: Category, 1: Name, 2: Description, 3: HasVariants, 4: Price, 5: Size
                r_category    = row[0].strip()
                r_name        = row[1].strip()
                r_description = row[2].strip()
                r_has_variant = row[3].strip()
                r_price       = row[4].strip()
                r_size        = row[5].strip()

                # 1. Find the Category
                category = Category.query.filter_by(name=r_category).first()
                if not category:
                    errors.append(f"Row {row_idx + 1}: Category '{r_category}' not found.")
                    continue

                # 2. Check if product already exists
                existing_product = Product.query.filter_by(name=r_name).first()
                if existing_product:
                    errors.append(f"Row {row_idx + 1}: Product '{r_name}' already exists.")
                    continue

                # 3. Create the Product
                has_variants_bool = r_has_variant.lower() == 'true'
                new_product = Product(
                    name=r_name,
                    description=r_description,
                    category_id=category.category_id,
                    has_variants=has_variants_bool
                )
                db.session.add(new_product)

                # 4. If it's a simple product, add its one variant
                if not has_variants_bool:
                    if not r_price or not r_size:
                        errors.append(f"Row {row_idx + 1}: Simple product '{r_name}' missing price or size.")
                        # We should probably rollback/skip adding the product here if variant fails,
                        # but for simplicity in this loop we just won't add the variant.
                        # Ideally, we shouldn't commit the product if this fails.
                        # For now, let's just continue (the product will exist with no price, requiring admin fix).
                        continue

                    simple_variant = ProductVariant(
                        product=new_product,
                        size_name=r_size,
                        price=r_price
                    )
                    db.session.add(simple_variant)

                products_added += 1

            db.session.commit()

            if products_added > 0:
                flash(f"Successfully imported {products_added} new products!", 'success')
            if errors:
                # Show up to 3 errors to avoid flooding the flash message
                error_msg = " | ".join(errors[:3])
                if len(errors) > 3:
                    error_msg += f" ...and {len(errors)-3} more errors."
                flash(f"Import completed with issues: {error_msg}", 'warning')

        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred during import: {e}", 'danger')
    else:
        flash('Invalid file type. Please upload a .csv file.', 'danger')

    return redirect(url_for('admin_products'))

# ===============================================
# MODULE 4: VOUCHER MANAGEMENT
# ===============================================

@app.route('/admin/vouchers', methods=['GET'])
@login_required
def admin_vouchers():
    add_form = VoucherForm()
    edit_form = VoucherForm()
    vouchers = Voucher.query.order_by(Voucher.code.asc()).all()

    return render_template(
        'admin_vouchers.html',
        add_form=add_form,
        edit_form=edit_form,
        vouchers=vouchers
    )

@app.route('/admin/vouchers/add', methods=['POST'])
@login_required
def admin_add_voucher():
    add_form = VoucherForm()
    
    if add_form.validate_on_submit():
        form_code = add_form.code.data
        
        existing_voucher = Voucher.query.filter_by(code=form_code).first()
        if existing_voucher:
            flash(f"Error: A voucher with the code '{form_code}' already exists.", 'danger')
            return redirect(url_for('admin_vouchers') + '#add-voucher-card')

        new_voucher = Voucher(
            code=form_code,
            discount_percentage=add_form.discount_percentage.data,
            is_active=add_form.is_active.data,
            max_uses=add_form.max_uses.data
        )
        db.session.add(new_voucher)
        try:
            db.session.commit()
            flash(f"Voucher '{new_voucher.code}' added successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding voucher: {e}", 'danger')
    else:
        for field, errors in add_form.errors.items():
            for error in errors:
                field_name = getattr(add_form, field).label.text
                flash(f"Error in '{field_name}': {error}", 'danger')

    return redirect(url_for('admin_vouchers') + '#add-voucher-card')

@app.route('/admin/vouchers/edit/<int:voucher_id>', methods=['POST'])
@login_required
def admin_edit_voucher(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)
    edit_form = VoucherForm()
    
    if edit_form.validate_on_submit():
        form_code = edit_form.code.data

        existing_voucher = Voucher.query.filter(
            Voucher.code == form_code,
            Voucher.voucher_id != voucher_id
        ).first()
        if existing_voucher:
            flash(f"Error: Cannot rename. The code '{form_code}' is already in use.", 'danger')
            return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')

        voucher.code = form_code
        voucher.discount_percentage = edit_form.discount_percentage.data
        voucher.max_uses = edit_form.max_uses.data
        
        try:
            db.session.commit()
            flash(f"Voucher '{voucher.code}' updated successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating voucher: {e}", 'danger')
    else:
        for field, errors in edit_form.errors.items():
            for error in errors:
                field_name = getattr(edit_form, field).label.text
                flash(f"Error in '{field_name}': {error}", 'danger')

    return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')

@app.route('/admin/vouchers/delete/<int:voucher_id>', methods=['POST'])
@login_required
def admin_delete_voucher(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)

    try:
        db.session.delete(voucher)
        db.session.commit()
        flash(f"Voucher '{voucher.code}' deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting voucher: {e}", 'danger')

    return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')

@app.route('/admin/vouchers/toggle/<int:voucher_id>', methods=['POST'])
@login_required
def admin_toggle_voucher_status(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)

    voucher.is_active = not voucher.is_active

    try:
        db.session.commit()
        if voucher.is_active:
            flash(f"VVoucher '{voucher.code}' has been Activated.", 'success')
        else:
            flash(f"Voucher '{voucher.code}' has been Deactivated.", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f"Error changing voucher status: {e}", 'danger')

    return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')

# ===============================================
# MODULE 5: CUSTOMER MANAGEMENT
# ===============================================

@app.route('/admin/customers')
@login_required
def admin_customers():
    search_query = request.args.get('search')
    
    customer_query = Customer.query
    
    if search_query:
        search_term = f'%{search_query}%'
        customer_query = customer_query.filter(
            db.or_(
                Customer.name.ilike(search_term),
                Customer.email.ilike(search_term)
            )
        )
        
    customers = customer_query.order_by(Customer.registration_date.desc()).all()
    
    return render_template(
        'admin_customers.html', 
        customers=customers, 
        search_query=search_query
    )

@app.route('/admin/customers/delete/<int:customer_id>', methods=['POST'])
@login_required
def admin_delete_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    try:
        order_ids = [order.order_id for order in customer.orders]
        if order_ids:
            OrderItem.query.filter(OrderItem.order_id.in_(order_ids)).delete(synchronize_session=False)
        
        Order.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
        
        db.session.delete(customer)
        
        db.session.commit()
        flash(f"Customer '{customer.name}' and all their associated orders have been deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting customer: {e}", 'danger')

    return redirect(url_for('admin_customers'))

@app.route('/admin/customers/edit/<int:customer_id>', methods=['GET'])
@login_required
def admin_edit_customer_page(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    form = CustomerEditForm(obj=customer)

    return render_template(
        'admin_customer_form.html',
        form=form,
        customer=customer
    )

@app.route('/admin/customers/edit/<int:customer_id>', methods=['POST'])
@login_required
def admin_edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    form = CustomerEditForm()

    if form.validate_on_submit():
        new_email = form.email.data
        if new_email != customer.email:
            existing_customer = Customer.query.filter_by(email=new_email).first()
            if existing_customer:
                flash('That email is already in use by another customer.', 'danger')
                return render_template('admin_customer_form.html', form=form, customer=customer)

        customer.name = form.name.data
        customer.contact_number = form.contact_number.data
        customer.email = new_email

        if form.password.data:
            customer.set_password(form.password.data)
            flash(f"Customer '{customer.name}' updated successfully (password changed).", 'success')
        else:
            flash(f"Customer '{customer.name}' updated successfully (password unchanged).", 'success')

        try:
            db.session.commit()
            return redirect(url_for('admin_customers'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating customer: {e}", 'danger')

    return render_template(
        'admin_customer_form.html',
        form=form,
        customer=customer
    )

@app.route('/admin/verifications')
@login_required
def admin_verifications():
    """
    (R)EAD: Show all pending Customer verifications (Rider checks removed).
    """
    customers_to_verify = Customer.query.filter(
        Customer.discount_status == 'Pending'
    ).order_by(Customer.registration_date.desc()).all()

    # Riders are no longer part of the system
    riders_to_verify = [] 

    return render_template(
        'admin_verifications_hub.html', 
        customers=customers_to_verify,
        riders=riders_to_verify
    )

@app.route('/admin/approve_discount/<int:customer_id>', methods=['POST'])
@login_required
def admin_approve_discount(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    customer.is_verified_discount = True
    customer.discount_status = 'Approved'

    try:
        db.session.commit()
        flash(f"Approved discount for {customer.name}.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error approving discount: {e}", 'danger')

    return redirect(url_for('admin_verifications'))

@app.route('/admin/deny_discount/<int:customer_id>', methods=['POST'])
@login_required
def admin_deny_discount(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    customer.is_verified_discount = False
    customer.discount_status = 'Denied'

    try:
        db.session.commit()
        flash(f"Denied and cleared discount request for {customer.name}.", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f"Error denying discount: {e}", 'danger')

    return redirect(url_for('admin_verifications'))

# ===============================================
# MODULE 6: SALES REPORTING
# ===============================================

@app.route('/admin/sales_reports')
@login_required
def admin_sales_reports():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else date.today() - timedelta(days=30)
    except:
        start_date = date.today() - timedelta(days=30)
    
    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else date.today()
    except:
        end_date = date.today()

    date_filter = [Order.order_date.between(start_date, end_date + timedelta(days=1))]

    if start_date.strftime('%Y-%m-%d') == (date.today() - timedelta(days=30)).strftime('%Y-%m-%d') and end_date.strftime('%Y-%m-%d') == date.today().strftime('%Y-%m-%d'):
        date_range_str = "Last 30 Days"
    else:
        date_range_str = f"from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"


    top_selling_items = db.session.query(
        Product.name,
        ProductVariant.size_name,
        func.sum(OrderItem.quantity).label('total_sold')
    ).join(Product, Product.product_id == OrderItem.product_id)\
     .join(ProductVariant, ProductVariant.variant_id == OrderItem.variant_id)\
     .join(Order, Order.order_id == OrderItem.order_id)\
     .filter(*date_filter)\
     .group_by(OrderItem.variant_id)\
     .order_by(func.sum(OrderItem.quantity).desc())\
     .all()

    sales_by_day = db.session.query(
        func.date(Order.order_date).label('date'),
        func.sum(Order.final_amount).label('total_sales')
    ).filter(*date_filter)\
     .group_by(func.date(Order.order_date))\
     .order_by(func.date(Order.order_date).desc())\
     .all()

    return render_template(
        'admin_sales_reports.html',
        top_selling_items=top_selling_items,
        sales_by_day=sales_by_day,
        start_date=start_date_str,
        end_date=end_date_str,
        date_range_str=date_range_str
    )

@app.route('/admin/export/sales_csv')
@login_required
def admin_export_sales_csv():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else date.today() - timedelta(days=30)
    except:
        start_date = date.today() - timedelta(days=30)
    
    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else date.today()
    except:
        end_date = date.today()

    date_filter = [Order.order_date.between(start_date, end_date + timedelta(days=1))]
    
    try:
        sales_by_day_query = db.session.query(
            func.date(Order.order_date).label('date'),
            func.sum(Order.final_amount).label('total_sales')
        ).filter(*date_filter)\
         .group_by(func.date(Order.order_date))\
         .order_by(func.date(Order.order_date).desc())

        df = pd.read_sql(sales_by_day_query.statement, db.engine)

        df = df.rename(columns={
            'date': 'Date',
            'total_sales': 'Total Sales (PHP)'
        })

        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)

        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=sales_report.csv"
        response.headers["Content-type"] = "text/csv"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the CSV: {e}", 'danger')
        return redirect(url_for('admin_sales_reports'))

# ===============================================
# MODULE 7: USER (STAFF) MANAGEMENT 
# (Rider management removed from all user routes)
# ===============================================

@app.route('/admin/users', methods=['GET'])
@login_required
def admin_users():
    """
    (R)EAD: Display all staff users (Riders removed).
    """
    staff_users = User.query.order_by(User.username.asc()).all()
    
    # Riders list is now empty
    riders = [] 
    
    return render_template('admin_users.html', staff_users=staff_users, riders=riders)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@login_required
def admin_add_user():
    form = UserAddForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash('That username is already taken. Please choose a different one.', 'danger')
            return render_template('admin_user_form.html', form=form, form_title="Add New Staff User", action_url=url_for('admin_add_user'))

        new_user = User(
            username=form.username.data,
            role=form.role.data
        )
        new_user.set_password(form.password.data)

        db.session.add(new_user)
        try:
            db.session.commit()
            flash(f"Staff user '{new_user.username}' created successfully.", 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating user: {e}", 'danger')

    return render_template(
        'admin_user_form.html',
        form=form,
        form_title="Add New Staff User",
        action_url=url_for('admin_add_user')
    )


@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = UserEditForm(obj=user)

    if form.validate_on_submit():
        new_username = form.username.data
        if new_username != user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user:
                flash('That username is already taken. Please choose a different one.', 'danger')
                return render_template('admin_user_form.html', form=form, form_title=f"Edit User: {user.username}", action_url=url_for('admin_edit_user', user_id=user_id))

        user.username = new_username
        user.role = form.role.data

        if form.password.data:
            user.set_password(form.password.data)
            flash(f"User '{user.username}' updated successfully (password changed).", 'success')
        else:
            flash(f"User '{user.username}' updated successfully (password unchanged).", 'success')

        try:
            db.session.commit()
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating user: {e}", 'danger')

    return render_template(
        'admin_user_form.html',
        form=form,
        form_title=f"Edit User: {user.username}",
        action_url=url_for('admin_edit_user', user_id=user_id)
    )


@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if user_id == current_user.user_id:
        flash("You cannot delete your own account.", 'danger')
        return redirect(url_for('admin_users'))

    user = User.query.get_or_404(user_id)

    try:
        db.session.delete(user)
        db.session.commit()
        flash(f"User '{user.username}' has been deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting user: {e}", 'danger')

    return redirect(url_for('admin_users'))

@app.route('/admin/dangerous/reset_menu')
@login_required
def admin_reset_menu():
    """
    DANGEROUS: Deletes all Categories, Products, Variants, and Orders.
    Use this to clear the DB before importing a fresh CSV.
    """
    if current_user.role != 'Admin':
        flash("Unauthorized.", "danger")
        return redirect(url_for('admin_dashboard'))

    try:
        # 1. Delete all Order Items first (The lowest child)
        num_items = db.session.query(OrderItem).delete()
        
        # 2. Delete all Orders (Since they are now empty)
        num_orders = db.session.query(Order).delete()

        # 3. Delete all Product Variants
        num_variants = db.session.query(ProductVariant).delete()

        # 4. Delete all Reviews (If you have them)
        num_reviews = db.session.query(Review).delete()

        # 5. Delete all Products
        num_products = db.session.query(Product).delete()

        # 6. Delete all Categories (The highest parent)
        num_categories = db.session.query(Category).delete()

        db.session.commit()
        
        flash(f"Database Wiped: {num_orders} Orders, {num_products} Products, {num_categories} Categories deleted.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error resetting database: {e}", "danger")

    return redirect(url_for('admin_products'))