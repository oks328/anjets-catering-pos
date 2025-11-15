from app import db
import os
import io
import secrets
import csv
import pandas as pd
import xml.etree.ElementTree as ET
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from sqlalchemy import func
from PIL import Image
from xml.dom import minidom
from flask import make_response, jsonify
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, session, jsonify, current_app
from flask_login import login_user, logout_user, current_user, login_required
# We only need to import the models once
from app.models import User, Category, Product, ProductVariant, Voucher, Customer, Order, OrderItem
from app.forms import AdminLoginForm, CategoryForm, ProductForm, VariantForm, VoucherForm, UserAddForm, UserEditForm, CustomerRegisterForm, CustomerLoginForm, CustomerEditForm, CustomerProfileForm
from functools import wraps
from flask_mail import Message
from app import mail
from app.forms import RequestResetForm, ResetPasswordForm

def get_category_choices():
    """
    Helper function to get all categories for the product form dropdown.
    """
    # We query the database for all categories
    categories = Category.query.filter_by(is_active=True).all()
    # We format them as a list of (value, label) tuples
    return [(c.category_id, c.name) for c in categories]

def save_picture(form_picture):
    """
    Helper function to save an uploaded picture.
    Resizes it and returns the unique filename.
    """
    # 1. Create a random, unique filename
    random_hex = secrets.token_hex(8)
    # Get the file extension (e.g., '.jpg')
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    # 2. Define the full save path
    picture_path = os.path.join(app.config['UPLOAD_FOLDER'], 'products', picture_fn)

    # 3. Resize the image to save space
    output_size = (800, 800) # Max 800x800 pixels
    i = Image.open(form_picture)
    i.thumbnail(output_size)

    # 4. Save the resized image
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

@app.route('/')
def client_home():
    """
    Client-facing homepage.
    Now fetches top 3 popular products.
    """

    # This query finds the top 3 selling product_ids
    top_product_ids = db.session.query(
            OrderItem.product_id,
            func.sum(OrderItem.quantity).label('total_sold')
        ).group_by(OrderItem.product_id)\
         .order_by(func.sum(OrderItem.quantity).desc())\
         .limit(3)\
         .all()

    # Get the full product objects for those IDs
    product_ids = [pid for pid, total in top_product_ids]
    popular_products = Product.query.filter(Product.product_id.in_(product_ids)).all()

    return render_template(
        'client_home.html',
        popular_products=popular_products
    )

# THIS FUNCTION WAS MISSING
@app.route('/menu')
@customer_login_required
def client_menu():
    """
    Client-facing Menu page.
    Shows ACTIVE categories and products.
    Can be filtered by category_id.
    """
    # Get the category_id from the URL (e.g., /menu?category_id=1)
    category_id = request.args.get('category_id', type=int)

    # Fetch all ACTIVE categories for the tabs
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()

    selected_category = None

    # Base query for products, joining with Category to filter
    product_query = Product.query.join(Category).filter(Category.is_active==True)

    if category_id:
        # If a category is selected, filter the product query
        product_query = product_query.filter(Product.category_id==category_id)
        selected_category = Category.query.get(category_id)

    # Execute the query
    products = product_query.order_by(Product.name.asc()).all()

    return render_template(
        'client_menu.html',
        categories=categories,
        products=products,
        selected_category=selected_category
    )

@app.route('/my-account')
@customer_login_required
def client_my_account():
    """
    (R)EAD: Display the customer's account page.
    Shows their profile and order history.
    """
    # Get the logged-in customer's ID from the session
    customer_id = session['customer_id']

    # Fetch all orders for this customer, newest first
    orders = Order.query.filter_by(customer_id=customer_id).order_by(Order.order_date.desc()).all()

    # We'll add the profile form later

    return render_template(
        'client_account.html',
        orders=orders
    )

@app.route('/my-account/profile', methods=['GET', 'POST'])
@customer_login_required
def client_profile():
    """
    (R)EAD and (U)PDATE the customer's own profile.
    """
    customer = Customer.query.get_or_404(session['customer_id'])
    form = CustomerProfileForm(obj=customer) # Pre-fill form

    if form.validate_on_submit():
        # Update the customer's details
        customer.name = form.name.data
        customer.contact_number = form.contact_number.data

        try:
            db.session.commit()
            # Update the session name in case they changed it
            session['customer_name'] = customer.name
            flash('Your profile has been updated.', 'success')
            return redirect(url_for('client_profile'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating profile: {e}", 'danger')

    # Show the pre-filled form on a GET request
    return render_template(
        'client_profile.html',
        form=form
    )

# ===============================================
# CLIENT-SIDE: SHOPPING CART
# ===============================================

@app.route('/cart/add', methods=['POST'])
@customer_login_required
def add_to_cart():
    """
    Add a product to the user's session cart.
    Now handles variant_id and quantity.
    NOW RETURNS JSON for a fetch() request.
    """
    cart = session.get('cart', {})
    
    # Get all data from the modal form
    product_id = request.form.get('product_id')
    variant_id = request.form.get('variant_id')
    
    try:
        quantity = int(request.form.get('quantity', 1))
        if quantity < 1:
            quantity = 1
    except:
        quantity = 1
        
    if not variant_id:
        # Return JSON error
        return jsonify({'status': 'error', 'message': 'No product size selected.'}), 400
        
    # Get the specific variant to get its name and price
    variant = ProductVariant.query.get(variant_id)
    if not variant:
        # Return JSON error
        return jsonify({'status': 'error', 'message': 'Could not find that product option.'}), 404

    product = variant.product # Get the parent product
    
    # Use variant_id as the key in the cart
    if variant_id in cart:
        # If item is already in cart, just add to its quantity
        cart[variant_id]['quantity'] += quantity
    else:
        # If new, add it to the cart
        cart[variant_id] = {
            'product_id': product.product_id,
            'name': product.name,
            'variant_name': variant.size_name,
            'price': float(variant.price),
            'image': product.image_file,
            'quantity': quantity
        }
    
    session['cart'] = cart
    
    print("Updated Cart:", session['cart'])
    
    # Return JSON success
    message = f"Added {quantity} x {product.name} ({variant.size_name}) to cart!"
    return jsonify({'status': 'success', 'message': message})

@app.route('/product_details/<int:product_id>')
def product_details(product_id):
    """
    API endpoint to get product details (especially variants) as JSON.
    NOW INCLUDES current quantity in the buffet cart.
    """
    product = Product.query.get_or_404(product_id)

    # Get the buffet cart from the session
    buffet_cart = session.get('buffet_package', {})

    variants_data = []
    for variant in product.variants:
        # Check if this variant is in the cart and get its quantity
        current_quantity = buffet_cart.get(str(variant.variant_id), {}).get('quantity', 0)

        variants_data.append({
            'id': variant.variant_id,
            'size': variant.size_name,
            'price': float(variant.price),
            'current_quantity': current_quantity # Add the count
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
    """
    cart_session = session.get('cart', {})
    cart_items = []
    
    # --- NEW: Separate Subtotals ---
    ala_carte_subtotal = 0.0
    buffet_subtotal = 0.0

    for item_id, item_data in cart_session.items():
        # Skip any corrupted items
        if 'name' not in item_data or 'price' not in item_data:
            continue
            
        quantity = item_data['quantity']
        price = item_data['price']
        line_total = float(price) * quantity
        
        # --- NEW: Check the tag ---
        if item_data.get('is_buffet_item', False):
            buffet_subtotal += line_total
        else:
            ala_carte_subtotal += line_total
            
        cart_items.append({
            'product_id': item_data['product_id'],
            'variant_id': item_id,
            'name': item_data['name'],
            'variant_name': item_data['variant_name'],
            'image': item_data['image'],
            'price': float(price),
            'quantity': quantity,
            'line_total': line_total,
            'is_buffet_item': item_data.get('is_buffet_item', False) # Pass tag to template
        })

    # --- NEW: Smart Discount Calculation ---
    
    # 1. Buffet Discount (10% on buffet items only)
    buffet_discount_amt = buffet_subtotal * 0.10
    
    # 2. Voucher Discount (on à la carte items only)
    voucher_discount_perc = session.get('discount_percentage', 0.0)
    voucher_discount_amt = (ala_carte_subtotal * voucher_discount_perc) / 100
    
    # 3. Final Totals
    total_price = ala_carte_subtotal + buffet_subtotal
    total_discount_amount = buffet_discount_amt + voucher_discount_amt
    final_total = total_price - total_discount_amount

    return render_template(
        'client_cart.html', 
        cart_items=cart_items, 
        total_price=total_price,
        ala_carte_subtotal=ala_carte_subtotal,
        buffet_subtotal=buffet_subtotal,
        voucher_discount_amt=voucher_discount_amt,
        buffet_discount_amt=buffet_discount_amt,
        total_discount_amount=total_discount_amount,
        final_total=final_total
    )

@app.route('/cart/clear')
@customer_login_required
def clear_cart():
    """
    Clear the entire shopping cart and all discounts.
    """
    session.pop('cart', None)
    session.pop('voucher_code', None)
    session.pop('discount_percentage', None)
    session.pop('buffet_discount_percentage', None)
    flash("Cart has been cleared.", 'info')
    return redirect(url_for('client_cart'))

@app.route('/cart/remove/<string:variant_id>')
@customer_login_required
def remove_from_cart(variant_id):
    """
    Remove an item from the shopping cart.
    """
    cart = session.get('cart', {})

    # Use .pop() to remove the item if it exists
    item_data = cart.pop(variant_id, None) 

    if item_data:
        flash(f"Removed {item_data['name']} ({item_data['variant_name']}) from cart.", 'info')

    # Save the modified cart back to the session
    session['cart'] = cart

    return redirect(url_for('client_cart'))

@app.route('/cart/update', methods=['POST'])
@customer_login_required
def update_cart_quantity():
    """
    Update the quantity of an item in the cart.
    """
    cart = session.get('cart', {})

    # Get the new data from the form
    variant_id = request.form.get('variant_id')
    try:
        quantity = int(request.form.get('quantity'))
        if quantity < 1:
            quantity = 1 # Minimum quantity is 1
    except:
        quantity = 1 # Default to 1 if something goes wrong

    # Update the cart if the item exists
    if variant_id in cart:
        cart[variant_id]['quantity'] = quantity
        flash(f"Updated {cart[variant_id]['name']} quantity.", 'success')

    session['cart'] = cart

    return redirect(url_for('client_cart'))

@app.route('/cart/apply_voucher', methods=['POST'])
@customer_login_required
def apply_voucher():
    """
    Apply a voucher code to the cart.
    """
    code = request.form.get('voucher_code')
    
    if not code:
        flash("Please enter a voucher code.", 'danger')
        return redirect(url_for('client_cart'))

    # Check the database for the voucher
    voucher = Voucher.query.filter_by(code=code, is_active=True).first()
    
    if voucher:
        # Found a valid, active voucher! Save it to the session.
        session['voucher_code'] = voucher.code
        session['discount_percentage'] = float(voucher.discount_percentage)
        flash(f"Voucher '{voucher.code}' applied successfully!", 'success')
    else:
        # No valid voucher found
        session.pop('voucher_code', None)
        session.pop('discount_percentage', None)
        flash("Invalid or expired voucher code.", 'danger')
        
    return redirect(url_for('client_cart'))

@app.route('/checkout')
@customer_login_required
def client_checkout():
    """
    (R)EAD: Display the FINAL checkout page with ALL totals.
    """
    cart_session = session.get('cart', {})
    if not cart_session:
        flash("Your cart is empty.", 'info')
        return redirect(url_for('client_cart'))

    # Check if they've completed the options step
    if 'order_type' not in session:
        flash("Please select your delivery or pickup option first.", 'info')
        return redirect(url_for('client_checkout_options'))

    # --- This is the same logic from client_cart() ---
    cart_items = []
    ala_carte_subtotal = 0.0
    buffet_subtotal = 0.0

    for item_id, item_data in cart_session.items():
        if 'name' not in item_data or 'price' not in item_data:
            continue

        quantity = item_data['quantity']
        price = item_data['price']
        line_total = float(price) * quantity

        if item_data.get('is_buffet_item', False):
            buffet_subtotal += line_total
        else:
            ala_carte_subtotal += line_total

        cart_items.append({
            'product_id': item_data['product_id'],
            'variant_id': item_id,
            'name': item_data['name'],
            'variant_name': item_data['variant_name'],
            'image': item_data['image'],
            'price': float(price),
            'quantity': quantity,
            'line_total': line_total,
            'is_buffet_item': item_data.get('is_buffet_item', False)
        })

    # --- NEW: Smart Discount + Delivery Fee ---
    total_price = ala_carte_subtotal + buffet_subtotal

    buffet_discount_amt = buffet_subtotal * 0.10
    voucher_discount_perc = session.get('discount_percentage', 0.0)
    voucher_discount_amt = (ala_carte_subtotal * voucher_discount_perc) / 100

    # Get the new delivery fee
    delivery_fee = session.get('delivery_fee', 0.0)

    total_discount_amount = buffet_discount_amt + voucher_discount_amt
    final_total = (total_price - total_discount_amount) + delivery_fee
    # --- END OF NEW LOGIC ---

    return render_template(
        'client_checkout.html',
        cart_items=cart_items,
        total_price=total_price,
        ala_carte_subtotal=ala_carte_subtotal,
        buffet_subtotal=buffet_subtotal,
        voucher_discount_amt=voucher_discount_amt,
        buffet_discount_amt=buffet_discount_amt,
        delivery_fee=delivery_fee, # Pass new fee
        total_discount_amount=total_discount_amount,
        final_total=final_total
    )

@app.route('/checkout/options', methods=['GET'])
@customer_login_required
def client_checkout_options():
    """
    (R)EAD: Show the page for selecting Delivery or Pickup.
    """
    cart_session = session.get('cart', {})
    if not cart_session:
        flash("Your cart is empty.", 'info')
        return redirect(url_for('client_cart'))

    # Get the customer's default address to pre-fill the form
    customer = Customer.query.get(session['customer_id'])
    default_address = customer.address

    return render_template(
        'client_checkout_options.html',
        default_address=default_address
    )

@app.route('/checkout/save_options', methods=['POST'])
@customer_login_required
def save_checkout_options():
    """
    (C)REATE: Save the chosen delivery options to the session.
    """
    cart_session = session.get('cart', {})
    if not cart_session:
        flash("Your cart is empty.", 'info')
        return redirect(url_for('client_cart'))

    order_type = request.form.get('order_type')
    delivery_address = request.form.get('delivery_address')

    if order_type == 'Delivery':
        if not delivery_address:
            # If they chose delivery but left the address blank
            flash("Please provide a delivery address.", 'danger')
            return redirect(url_for('client_checkout_options'))
        
        session['delivery_fee'] = 100.00
        session['order_type'] = 'Delivery'
        session['delivery_address'] = delivery_address
    else:
        # It's a Pickup
        session['delivery_fee'] = 0.00
        session['order_type'] = 'Pickup'
        session['delivery_address'] = 'Store Pickup'

    # Send them to the final review page
    return redirect(url_for('client_checkout'))

@app.route('/checkout/place_order', methods=['POST'])
@customer_login_required
def place_order():
    """
    (C)REATE: Create the order in the database.
    Returns JSON status for AJAX submission.
    """
    # --- (Existing Totals Recalculation Logic is Here) ---
    cart_session = session.get('cart', {})
    if not cart_session:
        return jsonify({'status': 'error', 'message': "Your cart is empty. Please try again."}), 400

    # Create a copy of the cart for validation and processing
    valid_cart_items = {} 
    ala_carte_subtotal = 0.0
    buffet_subtotal = 0.0
    total_price = 0.0

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

    # Calculate Discounts and Fee
    buffet_discount_amt = buffet_subtotal * 0.10
    voucher_discount_perc = session.get('discount_percentage', 0.0)
    voucher_discount_amt = (ala_carte_subtotal * voucher_discount_perc) / 100
    delivery_fee = session.get('delivery_fee', 0.0)

    total_discount_amount = buffet_discount_amt + voucher_discount_amt
    final_total = (total_price - total_discount_amount) + delivery_fee

    # --- 2. Create the main Order ---
    try:
        new_order = Order(
            customer_id=session['customer_id'],
            total_amount=total_price,
            discount_amount=total_discount_amount,
            final_amount=final_total,
            status="Pending",
            order_type=session.get('order_type', 'Pickup'),
            delivery_address=session.get('delivery_address', 'Store Pickup'),
            delivery_fee=delivery_fee
        )
        db.session.add(new_order)
        db.session.commit()

        # --- 3. Create the OrderItems (using the VALID list) ---
        for item_key, item_data in valid_cart_items.items():

            # Determine the REAL variant ID: 
            # For a simple item, the key IS the variant_id. For a smart buffet key (e.g., 'buffet_2'), the ID is stored inside the data.
            real_variant_id = item_data.get('variant_id', item_key)

            # Now, check if the key is a string (meaning it's a buffet collision key like 'buffet_2')
            # We only want to save the integer part to the database.
            if isinstance(real_variant_id, str) and real_variant_id.startswith('buffet_'):
                # The real ID is the part after 'buffet_'
                final_variant_id = int(real_variant_id.split('_')[1])
            else:
                # Otherwise, it's the correct integer variant ID
                final_variant_id = int(real_variant_id)

            # --- Now create the OrderItem ---
            new_item = OrderItem(
                order_id=new_order.order_id,
                product_id=item_data['product_id'],
                variant_id=final_variant_id, # <-- FIX: Use the cleaned integer ID
                quantity=item_data['quantity'],
                price_per_item=item_data['price'] 
            )
            db.session.add(new_item)

        db.session.commit()

        # --- 4. Clear the cart AND ALL checkout session data ---
        session.pop('cart', None)
        session.pop('voucher_code', None)
        session.pop('discount_percentage', None)
        session.pop('buffet_discount_percentage', None)
        session.pop('delivery_fee', None)
        session.pop('order_type', None)
        session.pop('delivery_address', None)
        session.pop('buffet_package', None)
        session.pop('buffet_recommendations', None)
        session.pop('buffet_sequence', None)

        # --- SUCCESS RETURN: Return JSON status and the URL to redirect to ---
        return jsonify({
            'status': 'success',
            'message': f"Order #{new_order.order_id} has been placed successfully!",
            'redirect_url': url_for('client_my_account')
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f"DB Error: {e}"}), 500

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

# ===============================================
# CLIENT-SIDE: CUSTOMER ACCOUNTS
# ===============================================

@app.route('/account', methods=['GET'])
def client_account_page():
    """
    (R)EAD: Display the login form.
    """
    if 'customer_id' in session:
        return redirect(url_for('client_home'))

    login_form = CustomerLoginForm()

    return render_template(
        'client_login.html',
        login_form=login_form
    )

@app.route('/register', methods=['GET'])
def client_register_page():
    """
    (R)EAD: Display the register form.
    """
    if 'customer_id' in session:
        return redirect(url_for('client_home'))

    register_form = CustomerRegisterForm()

    return render_template(
        'client_register.html',
        register_form=register_form
    )

@app.route('/logout')
def client_logout():
    """
    Log the customer out by clearing their session data.
    """
    # Remove customer info from the session
    session.pop('customer_id', None)
    session.pop('customer_name', None)

    # We can also clear the whole cart, or leave it. Let's leave it for now.

    flash("You have been logged out.", 'info')
    return redirect(url_for('client_home'))

@app.route('/register', methods=['POST'])
def client_register():
    """
    (C)REATE: Process the customer registration form.
    """
    # We only need the register_form
    register_form = CustomerRegisterForm()

    if register_form.validate_on_submit():
        # ... (all the logic to create a user is the same) ...
        new_customer = Customer(
            name=register_form.name.data,
            contact_number=register_form.contact_number.data,
            address=register_form.address.data,
            email=register_form.email.data
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

    # --- THIS IS THE FIX ---
    # If form fails, re-render the REGISTER page with the errors
    return render_template(
        'client_register.html',
        register_form=register_form
    )

@app.route('/login', methods=['POST'])
def client_login():
    """
    (U)PDATE: Process the customer login form.
    """
    login_form = CustomerLoginForm() # To process

    if login_form.validate_on_submit():
        customer = Customer.query.filter_by(email=login_form.email.data).first()

        if customer and customer.check_password(login_form.password.data):
            session['customer_id'] = customer.customer_id
            session['customer_name'] = customer.name

            flash(f"Welcome back, {customer.name}!", 'success')
            return redirect(url_for('client_home'))
        else:
            flash("Invalid email or password. Please try again.", 'danger')

    # --- THIS IS THE FIX ---
    # If form fails, re-render the LOGIN page with the errors
    return render_template(
        'client_login.html',
        login_form=login_form
    )
def send_async_email(app, msg):
    """
    New helper function to send email in a thread with app context.
    """
    with app.app_context():
        mail.send(msg)

def send_reset_email(customer):
    """
    Helper function to send the password reset email.
    """
    token = customer.get_reset_token()
    msg = Message(
        'Password Reset Request',
        sender=current_app.config['MAIL_USERNAME'],
        recipients=[customer.email]
    )
    msg.html = render_template('reset_email.html', customer=customer, token=token)
    
    # Use a thread to send email in the background
    from threading import Thread
    
    # Get the real app object (not the proxy)
    app = current_app._get_current_object() 
    
    # Pass the app and the message to our new async function
    thread = Thread(target=send_async_email, args=(app, msg))
    thread.start()
    return thread

@app.route('/forgot-password', methods=['GET', 'POST'])
# ... (rest of your routes) ...

@app.route('/forgot-password', methods=['GET', 'POST'])
def client_forgot_password():
    """
    (C)REATE: Show form to request a password reset.
    """
    if 'customer_id' in session:
        return redirect(url_for('client_home'))
    
    form = RequestResetForm()
    if form.validate_on_submit():
        customer = Customer.query.filter_by(email=form.email.data).first()
        if customer:
            send_reset_email(customer)
        # Security: Don't reveal if an email exists or not
        flash('If an account exists with that email, a reset link has been sent.', 'info')
        return redirect(url_for('client_account_page'))

    return render_template('client_forgot_password.html', form=form)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def client_reset_token(token):
    """
    (U)PDATE: Process the password reset form using the token.
    """
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
# ===============================================

@app.route('/buffet-builder', methods=['GET'])
@customer_login_required
def buffet_wizard_start():
    """
    (R)EAD: Show Step 1 of the buffet wizard: How many guests?
    """
    return render_template('client_buffet_step1.html')

@app.route('/buffet-builder/reco', methods=['POST'])
@customer_login_required
def buffet_wizard_reco():
    """
    (C)REATE: Processes guest count, calculates recommendations, 
    and redirects user to the first selection page (Ulam).
    """
    try:
        guest_count = int(request.form.get('guest_count'))
        if guest_count < 1:
            guest_count = 1
    except:
        guest_count = 30 # Default if something goes wrong
        
    # --- Smart Recommendation Logic ---
    # 1 dish type per 10 guests, rounded up. Noodles serve more (1 per 15).
    num_ulam = (guest_count + 9) // 10
    num_noodles = (guest_count + 14) // 15 
    num_dessert = (guest_count + 14) // 15
    
    recommendations = {
        'Ulam': num_ulam,
        'Noodles': num_noodles,
        'Dessert': num_dessert
    }

    # --- Initialize Session State ---
    session['buffet_recommendations'] = recommendations
    session['buffet_guest_count'] = guest_count
    session['buffet_package'] = {} # This will store the final selected items

    # --- Define the sequence of pages/categories for the wizard ---
    # The wizard must step through these categories in this exact order.
    wizard_sequence = ['Ulam', 'Noodles', 'Dessert'] 
    session['buffet_sequence'] = wizard_sequence
    
    # --- Redirect to the first selection page ---
    return redirect(url_for('buffet_wizard_select', category_name='Ulam'))

@app.route('/buffet-builder/select/<string:category_name>', methods=['GET', 'POST'])
@customer_login_required
def buffet_wizard_select(category_name):
    """
    (R)EAD: Show the selection page for a specific category (Step 3).
    NOW INCLUDES "Back" button logic and "Final Step" detection.
    """
    # 1. Check Session State
    recommendations = session.get('buffet_recommendations')
    wizard_sequence = session.get('buffet_sequence')

    if not recommendations or not wizard_sequence:
        flash("Your buffet session has expired. Please start over.", 'danger')
        return redirect(url_for('buffet_wizard_start'))

    # 2. Get the current category object
    category_obj = Category.query.filter_by(name=category_name, is_active=True).first_or_404()

    # 3. Get the required count for this page
    required_count = recommendations.get(category_name, 0)

    # 4. Get all active products in this category
    products = Product.query.filter_by(category_id=category_obj.category_id)\
                            .order_by(Product.name.asc()).all()

    # 5. Get current selections for the tracker (and display list)
    buffet_package = session.get('buffet_package', {})
        
        # NEW: Filter the items that belong to THIS page's category
    current_selections = []
    current_count = 0
    for variant_id, item_data in buffet_package.items():
        if item_data['category'] == category_name:
            item_data['variant_id'] = variant_id # Add the ID for the remove button
            current_selections.append(item_data)
            current_count += item_data['quantity']

    # 6. --- NEW LOGIC for Back/Next buttons ---
    current_index = wizard_sequence.index(category_name)

    # Check for PREVIOUS step
    if current_index > 0:
        previous_category = wizard_sequence[current_index - 1]
        previous_url = url_for('buffet_wizard_select', category_name=previous_category)
    else:
        previous_url = url_for('buffet_wizard_start') # Go back to Step 1

    # Check for NEXT step
    is_final_category = (current_index == len(wizard_sequence) - 1)
    if is_final_category:
        next_url = url_for('buffet_wizard_checkout') # Go to Review Page
    else:
        next_category = wizard_sequence[current_index + 1]
        next_url = url_for('buffet_wizard_select', category_name=next_category)
    # --- END OF NEW LOGIC ---

    return render_template(
        'client_buffet_select.html',
        category_name=category_name,
        products=products,
        required_count=required_count,
        current_count=current_count,
        current_selections=current_selections,
        next_url=next_url,
        previous_url=previous_url,         # <-- Pass Back button URL
        is_final_category=is_final_category # <-- Pass final step check
    )

@app.route('/buffet-builder/checkout', methods=['GET'])
@customer_login_required
def buffet_wizard_checkout():
    """
    (R)EAD: Show final summary with an editable cart.
    Now includes total price calculation.
    """
    buffet_package = session.get('buffet_package', {})
    
    # --- NEW: Calculate Total Price ---
    total_price = 0.0
    for item_data in buffet_package.values():
        total_price += float(item_data['price']) * item_data['quantity']
    # --- END OF NEW LOGIC ---
    
    return render_template(
        'client_buffet_checkout.html',
        buffet_package=buffet_package,
        total_price=total_price  # <-- Pass the new total
    )


@app.route('/buffet/commit_package', methods=['POST'])
@customer_login_required
def buffet_commit_package():
    """
    (C)REATE: Commits the final selected buffet package to the main cart.
    """
    buffet_package = session.get('buffet_package', {})
    if not buffet_package:
        flash("Buffet package is empty. Please start over.", 'danger')
        return redirect(url_for('buffet_wizard_start'))

    main_cart = session.get('cart', {})

    # Loop through the temporary package and add to the main cart
    for variant_id, item_data in buffet_package.items():

        # --- THIS IS THE NEW LOGIC ---
        if variant_id in main_cart and not main_cart[variant_id].get('is_buffet_item', False):
            # COLLISION! The main cart has this item as À LA CARTE.
            # We must create a new, unique key for the BUFFET version.
            new_key = f"buffet_{variant_id}"

            if new_key in main_cart:
                main_cart[new_key]['quantity'] += item_data['quantity']
            else:
                main_cart[new_key] = {
                    'product_id': item_data['product_id'],
                    'name': item_data['product_name'], # <-- This is the fix
                    'variant_id': variant_id,
                    'variant_name': item_data['variant_name'],
                    'price': item_data['price'],
                    'image': item_data['image'],
                    'quantity': item_data['quantity'],
                    'is_buffet_item': True # Tag as a buffet item
                }
        else:
            # No collision. Add/stack normally using the variant_id as the key.
            if variant_id in main_cart:
                main_cart[variant_id]['quantity'] += item_data['quantity']
            else:
                main_cart[variant_id] = {
                    'product_id': item_data['product_id'],
                    'name': item_data['product_name'], # <-- This is the fix
                    'variant_id': variant_id,
                    'variant_name': item_data['variant_name'],
                    'price': item_data['price'],
                    'image': item_data['image'],
                    'quantity': item_data['quantity'],
                    'is_buffet_item': True # Tag as a buffet item
                }
        # --- END OF NEW LOGIC ---

    # Apply the Buffet Discount
    session['buffet_discount_percentage'] = 10.0

    # Save the updated main cart
    session['cart'] = main_cart

    # Clear the temporary buffet data
    session.pop('buffet_package', None)
    session.pop('buffet_recommendations', None)
    session.pop('buffet_sequence', None)

    flash("Success! Your custom buffet package has been added to the cart.", 'success')
    return redirect(url_for('client_cart'))


@app.route('/buffet/remove/<string:variant_id>')
@customer_login_required
def buffet_remove_item(variant_id):
    """
    (D)ELETE: Remove an item from the temporary 'buffet_package'.
    """
    buffet_package = session.get('buffet_package', {})
    
    # Use .pop() to remove the item if it exists
    item_data = buffet_package.pop(variant_id, None) 
    
    if item_data:
        flash(f"Removed {item_data['product_name']} from your buffet.", 'info')
    
    # Save the modified package back to the session
    session['buffet_package'] = buffet_package
    
    # Redirect back to the review page
    return redirect(url_for('buffet_wizard_checkout'))


@app.route('/buffet/update', methods=['POST'])
@customer_login_required
def buffet_update_quantity():
    """
    (U)PDATE: Update the quantity of an item in the 'buffet_package'.
    """
    buffet_package = session.get('buffet_package', {})
    variant_id = request.form.get('variant_id')
    
    try:
        quantity = int(request.form.get('quantity'))
        if quantity < 1:
            quantity = 1 # Minimum quantity is 1
    except:
        quantity = 1 # Default to 1
    
    # Update the package if the item exists
    if variant_id in buffet_package:
        buffet_package[variant_id]['quantity'] = quantity
        flash(f"Updated {buffet_package[variant_id]['product_name']} quantity.", 'success')
        
    session['buffet_package'] = buffet_package
    
    return redirect(url_for('buffet_wizard_checkout'))

@app.route('/buffet/add_item', methods=['POST'])
@customer_login_required
def buffet_add_item():
    """
    (C)REATE: Add an item to the temporary 'buffet_cart' in the session.
    Now includes a check for exceeding recommendations.
    """
    # 1. Get data from the form
    variant_id = request.form.get('variant_id')
    force_add = request.form.get('force', 'false').lower() == 'true'
    try:
        quantity = int(request.form.get('quantity', 1))
    except:
        quantity = 1

    # 2. Get the temporary cart and recommendations
    buffet_cart = session.get('buffet_package', {})
    recommendations = session.get('buffet_recommendations', {})

    if not variant_id:
        return jsonify({'status': 'error', 'message': 'No variant selected.'}), 400

    # 3. Get item details
    variant = ProductVariant.query.get(variant_id)
    if not variant:
        return jsonify({'status': 'error', 'message': 'Item not found.'}), 404
        
    product = variant.product
    category_name = product.category.name

    # 4. Check if we are over the limit AND not forcing it
    current_category_count = 0
    for item in buffet_cart.values():
        if item['category'] == category_name:
            current_category_count += item['quantity']
    
    potential_new_count = current_category_count + quantity
    recommended_count = recommendations.get(category_name, 0)

    if potential_new_count > recommended_count and not force_add:
        return jsonify({
            'status': 'warning',
            'message': f"You've selected {potential_new_count} {category_name} items, but we only recommend {recommended_count}. Add anyway?"
        })

    # 5. Add the item to the buffet_cart
    if variant_id in buffet_cart:
        buffet_cart[variant_id]['quantity'] += quantity
    else:
        # If new, add it to the buffet_cart
        buffet_cart[variant_id] = {
            'product_id': product.product_id,  # <-- ADD THIS LINE
            'product_name': product.name,
            'variant_name': variant.size_name,
            'quantity': quantity,
            'category': category_name,
            'price': float(variant.price),
            'image': product.image_file
        }
    
    session['buffet_package'] = buffet_cart
    
    # 6. Calculate the new counts for the tracker
    new_counts = {}
    total_items = 0
    for cat in recommendations.keys():
        new_counts[cat] = 0
    
    for item in buffet_cart.values():
        item_cat = item['category']
        if item_cat in new_counts:
            new_counts[item_cat] += item['quantity']
        total_items += item['quantity']
        
    # 7. Send the new counts back to the JavaScript
    return jsonify({
        'status': 'success',
        'message': f"Added {product.name} ({variant.size_name})",
        'new_counts': new_counts,
        'total_items': total_items
    })

@app.route('/buffet/remove_item/<string:variant_id>/<string:category_name>')
@customer_login_required
def buffet_remove_item_from_package(variant_id, category_name):
    """
    (D)ELETE: Remove a specific item (variant_id) from the current buffet package.
    """
    buffet_package = session.get('buffet_package', {})
    
    if variant_id in buffet_package:
        item_name = buffet_package.pop(variant_id)['product_name']
        flash(f"Removed {item_name} from your selections.", 'info')
    
    session['buffet_package'] = buffet_package
    
    # Redirect back to the current category selection page
    return redirect(url_for('buffet_wizard_select', category_name=category_name))

@app.route('/buffet/review')
@customer_login_required
def buffet_review_and_add():
    """
    (U)PDATE: Move all items from the 'buffet_cart' to the main 'cart'.
    Also applies a 10% buffet discount.
    """
    buffet_cart = session.get('buffet_cart', {})
    if not buffet_cart:
        flash("Your buffet is empty. Please add some items.", 'danger')
        return redirect(url_for('buffet_wizard_start'))

    main_cart = session.get('cart', {})
    items_added_count = 0

    # Loop through the buffet cart and add each item to the main cart
    for variant_id, item_data in buffet_cart.items():
        
        # --- FIX: Skip any corrupted items that are missing the product_id key ---
        if 'product_id' not in item_data:
            print(f"Skipping corrupted buffet item with variant_id: {variant_id}")
            continue 
        
        if variant_id in main_cart:
            # If item is already in main cart, just add the quantity
            main_cart[variant_id]['quantity'] += item_data['quantity']
        else:
            # If new, add the full item data
            main_cart[variant_id] = {
                'product_id': item_data['product_id'],
                'name': item_data['product_name'],
                'variant_name': item_data['variant_name'],
                'price': item_data['price'],
                'image': item_data['image'],
                'quantity': item_data['quantity']
            }
        items_added_count += item_data['quantity']
            
    # --- Apply the Buffet Discount ---
    session['buffet_discount_percentage'] = 10.0
    
    # Save the updated main cart
    session['cart'] = main_cart
    
    # Clear the temporary buffet data
    session.pop('buffet_cart', None)
    session.pop('buffet_recommendations', None)
    
    if items_added_count > 0:
        flash("Success! Your buffet has been added to the cart with a 10% discount!", 'success')
    else:
        # If the cart was just full of corrupted items, let the user know
        flash("No valid items were added. Please try rebuilding your buffet.", 'warning')

    return redirect(url_for('client_cart'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """
    (R)EAD: The main admin dashboard page with business stats.
    """
    # --- Stats Calculation ---

    # 1. Get "New Orders Today"
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    orders_today_count = Order.query.filter(Order.order_date >= today_start).count()

    # 2. Get "Total Sales this Month"
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # func.sum(Order.final_amount) adds up the 'final_amount' column
    total_sales_month_query = db.session.query(func.sum(Order.final_amount)).filter(Order.order_date >= month_start).scalar()
    total_sales_month = total_sales_month_query or 0.0 # Set to 0 if no sales

    # 3. Get "New Customer Registrations" this month
    new_customers_month_count = Customer.query.filter(Customer.registration_date >= month_start).count() # Assumes a registration_date, let's add that

    # 4. Get recent 5 pending orders
    recent_pending_orders = Order.query.filter_by(status='Pending').order_by(Order.order_date.asc()).limit(5).all()

    return render_template(
        'admin_dashboard.html',
        orders_today_count=orders_today_count,
        total_sales_month=total_sales_month,
        new_customers_month_count=new_customers_month_count,
        recent_pending_orders=recent_pending_orders
    )


@app.route('/admin/logout')
@login_required
def admin_logout():
    """
    Handle logging the admin user out.
    """
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin_login'))

# ===============================================
# MODULE 1: ORDER MANAGEMENT (CRUD)
# ===============================================

@app.route('/admin/orders')
@login_required
def admin_orders():
    """
    (R)EAD: Display all customer orders.
    """
    # Get the filter status from the URL (e.g., /admin/orders?status=Pending)
    status_filter = request.args.get('status')

    # Start the base query
    order_query = Order.query.join(Customer).order_by(Order.order_date.desc())

    if status_filter:
        # Apply the filter if one is provided
        order_query = order_query.filter(Order.status == status_filter)

    # Execute the query
    orders = order_query.all()

    return render_template('admin_orders.html', orders=orders, current_filter=status_filter)

@app.route('/admin/orders/update_status/<int:order_id>', methods=['POST'])
@login_required
def admin_update_order_status(order_id):
    """
    (U)PDATE: Update an order's status.
    """
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    
    # Check if the status is valid
    if new_status in ['Pending', 'In Progress', 'Completed']:
        order.status = new_status
        try:
            db.session.commit()
            flash(f"Order #{order.order_id} status updated to '{new_status}'.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating order status: {e}", 'danger')
    else:
        flash("Invalid status selected.", 'danger')
        
    # Redirect back to the orders page, preserving any filter
    current_filter = request.args.get('status')
    if current_filter:
        return redirect(url_for('admin_orders', status=current_filter))
    return redirect(url_for('admin_orders'))


@app.route('/admin/orders/delete/<int:order_id>', methods=['POST'])
@login_required
def admin_delete_order(order_id):
    """
    (D)ELETE: Delete an order.
    """
    order = Order.query.get_or_404(order_id)
    
    try:
        # First, delete all associated OrderItems
        OrderItem.query.filter_by(order_id=order.order_id).delete()
        
        # Now delete the main Order
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
    """
    (R)EAD: Generate and download a JSON file of all orders.
    """
    try:
        # 1. Fetch all orders with their customer and items
        orders = Order.query.options(
            db.joinedload(Order.customer),
            db.joinedload(Order.items).joinedload(OrderItem.product),
            db.joinedload(Order.items).joinedload(OrderItem.variant)
        ).order_by(Order.order_date.desc()).all()

        all_orders_data = []

        # 2. Manually build a list of dictionaries
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

        # 3. Create the JSON file download response
        response = make_response(jsonify(all_orders_data))
        response.headers["Content-Disposition"] = "attachment; filename=orders_export.json"
        response.headers["Content-type"] = "application/json"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the JSON: {e}", 'danger')
        return redirect(url_for('admin_orders'))


# ===============================================
# MODULE 3: CATEGORY MANAGEMENT (CRUD)
# ===============================================

@app.route('/admin/categories', methods=['GET'])
@login_required
def admin_categories():
    """
    (R)EAD: Display all categories and show forms.
    """
    # Get the search query from the URL
    search_query = request.args.get('search')
    
    add_form = CategoryForm()
    edit_form = CategoryForm() # We use the same form for editing
    
    # Start the base query
    category_query = Category.query
    
    if search_query:
        # If there is a search, filter the query
        category_query = category_query.filter(Category.name.ilike(f'%{search_query}%'))
        
    categories = category_query.order_by(Category.name.asc()).all()
    
    return render_template(
        'admin_categories.html',
        add_form=add_form,
        edit_form=edit_form,
        categories=categories,
        search_query=search_query  # Pass the query back to the template
    )

@app.route('/admin/products/toggle/<int:product_id>', methods=['POST'])
@login_required
def admin_toggle_product_status(product_id):
    """
    (U)PDATE: Toggle the is_active status of a product.
    """
    product = Product.query.get_or_404(product_id)

    # This is the "soft delete" logic
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
    """
    (U)PDATE: Process the edit category form.
    """
    category = Category.query.get_or_404(category_id)
    edit_form = CategoryForm()

    if edit_form.validate_on_submit():
        # Update the category's fields
        category.name = edit_form.name.data
        category.description = edit_form.description.data
        # We no longer set 'is_active' here

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
    """
    (U)PDATE: Toggle the is_active status of a category.
    """
    category = Category.query.get_or_404(category_id)

    # This is the "soft delete" logic
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
# MODULE 2: PRODUCT MANAGEMENT (CRUD)
# ===============================================

@app.route('/admin/products', methods=['GET'])
@login_required
def admin_products():
    """
    (R)EAD: Display all products.
    """
    # Get query params from the URL
    search_query = request.args.get('search')
    selected_category_id = request.args.get('category', type=int)
    
    # Get all categories for the filter dropdown
    # We get all categories, including inactive ones, for admin filtering
    all_categories = Category.query.order_by(Category.name.asc()).all()
    
    # Start the base query
    product_query = Product.query
    
    # Apply category filter if one is selected
    if selected_category_id:
        product_query = product_query.filter_by(category_id=selected_category_id)
    
    # Apply search filter if there is one
    if search_query:
        product_query = product_query.filter(Product.name.ilike(f'%{search_query}%'))
        
    # Execute the final query
    products = product_query.order_by(Product.name.asc()).all()
    
    return render_template(
        'admin_products.html', 
        products=products,
        all_categories=all_categories, # Pass categories to template
        selected_category_id=selected_category_id, # Pass the selected ID back
        search_query=search_query
    )

@app.route('/admin/products/add', methods=['GET', 'POST'])
@login_required
def admin_add_product():
    """
    (C)REATE: Add a new product.
    """
    form = ProductForm()
    # Set the choices for the category dropdown
    form.category.choices = get_category_choices()

    if form.validate_on_submit():

        image_filename = 'default.jpg' # Default
        if form.image.data:
            # If a new image is uploaded, save it
            try:
                image_filename = save_picture(form.image.data)
            except Exception as e:
                flash(f'Error uploading image: {e}', 'danger')
                return redirect(url_for('admin_add_product'))
            
        # Create new product object
        new_product = Product(
            category_id=form.category.data,
            name=form.name.data,
            description=form.description.data,
            has_variants=form.has_variants.data
        )
        db.session.add(new_product)

        # --- Handle price for simple (non-variant) products ---
        if not new_product.has_variants:
            if form.price.data is None:
                # If no variants and no price, flash an error
                flash('Error: A simple product (no variants) must have a price.', 'danger')
                return redirect(url_for('admin_add_product'))

            # Create the single "Regular" variant
            simple_variant = ProductVariant(
                product=new_product, # Link to the product
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

    # This is for the GET request (showing the form)
    return render_template(
        'admin_product_form.html',
        form=form,
        form_title="Add New Product",
        action_url=url_for('admin_add_product')
    )


@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_product(product_id):
    """
    (U)PDATE: Edit an existing product.
    """
    product = Product.query.get_or_404(product_id)
    form = ProductForm(obj=product) # 'obj=product' pre-fills the form
    form.category.choices = get_category_choices()

    if form.validate_on_submit():

        if form.image.data:
            # A new image was uploaded. Save it.
            try:
                image_filename = save_picture(form.image.data)
                # We can also delete the old picture here, but let's skip for simplicity
                product.image_file = image_filename # Update the product
            except Exception as e:
                flash(f'Error uploading image: {e}', 'danger')
                return redirect(url_for('admin_edit_product', product_id=product_id))

        # Update product fields from form
        product.category_id = form.category.data
        product.name = form.name.data
        product.description = form.description.data
        product.has_variants = form.has_variants.data

        # --- Handle price for simple (non-variant) products ---
        if not product.has_variants:
            if form.price.data is None:
                flash('Error: A simple product (no variants) must have a price.', 'danger')
                return redirect(url_for('admin_edit_product', product_id=product_id))

            # Check if a "Regular" variant already exists
            simple_variant = ProductVariant.query.filter_by(
                product_id=product.product_id, 
                size_name="Regular"
            ).first()

            if simple_variant:
                # Update existing simple variant's price
                simple_variant.price = form.price.data
            else:
                # Create a new one if it doesn't exist
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

    # --- Handle GET request (pre-filling the form) ---
    if not product.has_variants and product.variants:
        # If it's a simple product, find its 'Regular' price
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
    """
    (D)ELETE: Delete a product.
    """
    product = Product.query.get_or_404(product_id)

    try:
        # Note: Because we set 'cascade="all, delete-orphan"' in our
        # models.py, deleting the product will AUTOMATICALLY delete
        # all its associated ProductVariants.
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
    """
    (R)EAD: Generate and download an XML file of the full menu.
    """
    try:
        # 1. Fetch all products with their categories and variants
        products = Product.query.options(
            db.joinedload(Product.category),
            db.joinedload(Product.variants)
        ).all()

        # 2. Build the XML structure
        root = ET.Element('Menu')

        for product in products:
            # Create a <Product> tag
            product_elem = ET.SubElement(root, 'Product')
            product_elem.set('id', str(product.product_id))

            # Add child tags for product data
            ET.SubElement(product_elem, 'Name').text = product.name
            ET.SubElement(product_elem, 'Description').text = product.description
            ET.SubElement(product_elem, 'Category').text = product.category.name
            ET.SubElement(product_elem, 'HasVariants').text = str(product.has_variants)

            # Add a <Variants> parent tag
            variants_elem = ET.SubElement(product_elem, 'Variants')
            for variant in product.variants:
                variant_elem = ET.SubElement(variants_elem, 'Variant')
                ET.SubElement(variant_elem, 'Size').text = variant.size_name
                ET.SubElement(variant_elem, 'Price').text = str(variant.price)

        # 3. Convert the XML tree to a string
        # We use 'minidom' to "pretty-print" the XML with indentation
        xml_str = minidom.parseString(ET.tostring(root))\
                         .toprettyxml(indent="   ")

        # 4. Create the file download response
        response = make_response(xml_str)
        response.headers["Content-Disposition"] = "attachment; filename=menu_export.xml"
        response.headers["Content-type"] = "application/xml"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the XML: {e}", 'danger')
        return redirect(url_for('admin_products'))

# ===============================================
# MODULE 2b: PRODUCT VARIANT MANAGEMENT (CRUD)
# ===============================================

@app.route('/admin/products/<int:product_id>/variants', methods=['GET'])
@login_required
def admin_product_variants(product_id):
    """
    (R)EAD: Display all variants for a specific product.
    """
    product = Product.query.get_or_404(product_id)
    # Check if product is simple, if so, redirect
    if not product.has_variants:
        flash(f"'{product.name}' is a simple product and cannot have variants.", 'danger')
        return redirect(url_for('admin_products'))
        
    # Get the search query from the URL
    search_query = request.args.get('search')
    
    add_form = VariantForm()
    edit_form = VariantForm()
    
    # Start the base query, already filtered by product_id
    variant_query = ProductVariant.query.filter_by(product_id=product.product_id)
    
    if search_query:
        # If there is a search, filter the query by variant size_name
        variant_query = variant_query.filter(ProductVariant.size_name.ilike(f'%{search_query}%'))
        
    variants = variant_query.all()
    
    return render_template(
        'admin_product_variants.html',
        product=product,
        variants=variants,
        add_form=add_form,
        edit_form=edit_form,
        search_query=search_query # Pass the query back to the template
    )

@app.route('/admin/products/<int:product_id>/variants/add', methods=['POST'])
@login_required
def admin_add_variant(product_id):
    """
    (C)REATE: Process the add variant form.
    """
    product = Product.query.get_or_404(product_id)
    add_form = VariantForm()

    if add_form.validate_on_submit():
        form_size_name = add_form.size_name.data
        
        # Check if a variant with this name already exists for this product
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

    # Redirect back to the variants page for that product
    return redirect(url_for('admin_product_variants', product_id=product.product_id) + '#add-variant-card')


@app.route('/admin/variants/delete/<int:variant_id>', methods=['POST'])
@login_required
def admin_delete_variant(variant_id):
    """
    (D)ELETE: Delete a variant.
    """
    variant = ProductVariant.query.get_or_404(variant_id)
    product_id = variant.product_id # Save this for the redirect

    try:
        db.session.delete(variant)
        db.session.commit()
        flash(f"Variant '{variant.size_name}' deleted.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting variant: {e}", 'danger')

    return redirect(url_for('admin_product_variants', product_id=product_id) + '#existing-variants-card')

# ... admin_delete_variant function is above ...

@app.route('/admin/variants/edit/<int:variant_id>', methods=['POST'])
@login_required
def admin_edit_variant(variant_id):
    """
    (U)PDATE: Process the edit variant form.
    """
    variant = ProductVariant.query.get_or_404(variant_id)
    product_id = variant.product_id # Save for the redirect
    edit_form = VariantForm()
    
    if edit_form.validate_on_submit():
        form_size_name = edit_form.size_name.data
        
        # --- DUPLICATE CHECK (for Update) ---
        # Check if another variant (but not this one) already has the new name
        existing_variant = ProductVariant.query.filter(
            ProductVariant.product_id == product_id,
            ProductVariant.size_name == form_size_name,
            ProductVariant.variant_id != variant_id # Exclude self
        ).first()
        
        if existing_variant:
            flash(f"Error: Cannot rename. A variant named '{form_size_a}' already exists.", 'danger')
            return redirect(url_for('admin_product_variants', product_id=product_id))
        # --- END OF CHECK ---
            
        # If no conflicts, update the variant
        variant.size_name = form_size_name
        variant.price = edit_form.price.data
        
        try:
            db.session.commit()
            flash(f"Variant '{variant.size_name}' updated successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating variant: {e}", 'danger')
    else:
        flash('Error: Could not update variant. Please check form.', 'danger')

    return redirect(url_for('admin_product_variants', product_id=product_id) + '#existing-variants-card')

@app.route('/admin/import/products_csv', methods=['POST'])
@login_required
def admin_import_products_csv():
    """
    (C)REATE: Import products from an uploaded CSV file.
    """
    if 'csv_file' not in request.files:
        flash('No file part in the request.', 'danger')
        return redirect(url_for('admin_products'))

    file = request.files['csv_file']

    if file.filename == '':
        flash('No selected file.', 'danger')
        return redirect(url_for('admin_products'))

    if file and file.filename.endswith('.csv'):
        try:
            # Read the file in-memory
            stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
            csv_reader = csv.DictReader(stream)

            products_added = 0
            errors = []

            for row in csv_reader:
                # 1. Find the Category
                category = Category.query.filter_by(name=row['category_name']).first()
                if not category:
                    errors.append(f"Category '{row['category_name']}' for product '{row['name']}' not found. Skipping.")
                    continue # Skip this row

                # 2. Check if product already exists
                existing_product = Product.query.filter_by(name=row['name']).first()
                if existing_product:
                    errors.append(f"Product '{row['name']}' already exists. Skipping.")
                    continue # Skip this row

                # 3. Create the Product
                has_variants = row['has_variants'].lower() == 'true'
                new_product = Product(
                    name=row['name'],
                    description=row['description'],
                    category_id=category.category_id,
                    has_variants=has_variants
                )
                db.session.add(new_product)

                # 4. If it's a simple product, add its one variant
                if not has_variants:
                    if not row['price'] or not row['size_name']:
                        errors.append(f"Product '{row['name']}' is simple but missing price/size. Skipping variant.")
                        continue

                    simple_variant = ProductVariant(
                        product=new_product,
                        size_name=row['size_name'],
                        price=row['price']
                    )
                    db.session.add(simple_variant)

                products_added += 1

            # Commit all new products and variants to the database
            db.session.commit()

            # Report results
            if products_added > 0:
                flash(f"Successfully imported {products_added} new products!", 'success')
            if errors:
                flash(f"Completed with {len(errors)} errors: " + " | ".join(errors), 'warning')

        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred during import: {e}", 'danger')
    else:
        flash('Invalid file type. Please upload a .csv file.', 'danger')

    return redirect(url_for('admin_products'))

# ===============================================
# MODULE 4: VOUCHER MANAGEMENT (CRUD)
# ===============================================

@app.route('/admin/vouchers', methods=['GET'])
@login_required
def admin_vouchers():
    """
    (R)EAD: Display all vouchers and show forms.
    """
    add_form = VoucherForm()
    edit_form = VoucherForm() # We use the same form for editing
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
    """
    (C)REATE: Process the add voucher form.
    """
    add_form = VoucherForm()
    
    if add_form.validate_on_submit():
        form_code = add_form.code.data
        
        # --- NEW: DUPLICATE CHECK ---
        existing_voucher = Voucher.query.filter_by(code=form_code).first()
        if existing_voucher:
            flash(f"Error: A voucher with the code '{form_code}' already exists.", 'danger')
            return redirect(url_for('admin_vouchers') + '#add-voucher-card')
        # --- END OF CHECK ---

        new_voucher = Voucher(
            code=form_code,
            discount_percentage=add_form.discount_percentage.data,
            is_active=add_form.is_active.data
        )
        db.session.add(new_voucher)
        try:
            db.session.commit()
            flash(f"Voucher '{new_voucher.code}' added successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding voucher: {e}", 'danger')
    else:
        # This block catches form validation errors (like > 20%)
        for field, errors in add_form.errors.items():
            for error in errors:
                field_name = getattr(add_form, field).label.text
                flash(f"Error in '{field_name}': {error}", 'danger')

    return redirect(url_for('admin_vouchers') + '#add-voucher-card')

@app.route('/admin/vouchers/edit/<int:voucher_id>', methods=['POST'])
@login_required
def admin_edit_voucher(voucher_id):
    """
    (U)PDATE: Process the edit voucher form.
    """
    voucher = Voucher.query.get_or_404(voucher_id)
    edit_form = VoucherForm()
    
    if edit_form.validate_on_submit():
        form_code = edit_form.code.data

        # --- NEW: DUPLICATE CHECK ---
        # Check if another voucher (but not this one) already has the new code
        existing_voucher = Voucher.query.filter(
            Voucher.code == form_code,
            Voucher.voucher_id != voucher_id
        ).first()
        if existing_voucher:
            flash(f"Error: Cannot rename. The code '{form_code}' is already in use.", 'danger')
            return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')
        # --- END OF CHECK ---

        voucher.code = form_code
        voucher.discount_percentage = edit_form.discount_percentage.data
        # We don't update is_active here, that's handled by the toggle route
        
        try:
            db.session.commit()
            flash(f"Voucher '{voucher.code}' updated successfully.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating voucher: {e}", 'danger')
    else:
        # This block catches form validation errors (like > 20%)
        for field, errors in edit_form.errors.items():
            for error in errors:
                field_name = getattr(edit_form, field).label.text
                flash(f"Error in '{field_name}': {error}", 'danger')

    return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')

@app.route('/admin/vouchers/delete/<int:voucher_id>', methods=['POST'])
@login_required
def admin_delete_voucher(voucher_id):
    """
    (D)ELETE: Delete a voucher.
    """
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
    """
    (U)PDATE: Toggle the is_active status of a voucher.
    """
    voucher = Voucher.query.get_or_404(voucher_id)

    # This is the "soft delete" logic
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

    # Redirect back to the correct anchor
    return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')

# ===============================================
# MODULE 5: CUSTOMER MANAGEMENT (CRUD)
# ===============================================

@app.route('/admin/customers')
@login_required
def admin_customers():
    """
    (R)EAD: Display all registered customers.
    """
    search_query = request.args.get('search')
    
    customer_query = Customer.query
    
    if search_query:
        # Search by name or email
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
    """
    (D)ELETE: Delete a customer account.
    """
    customer = Customer.query.get_or_404(customer_id)
    
    # We must delete their orders first, or the database will complain.
    try:
        # 1. Delete all associated OrderItems
        order_ids = [order.order_id for order in customer.orders]
        if order_ids:
            OrderItem.query.filter(OrderItem.order_id.in_(order_ids)).delete(synchronize_session=False)
        
        # 2. Delete all their Orders
        Order.query.filter_by(customer_id=customer_id).delete(synchronize_session=False)
        
        # 3. Now delete the Customer
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
    """
    (R)EAD: Show the form to edit a customer.
    """
    customer = Customer.query.get_or_404(customer_id)
    # Pre-fill the form with the customer's existing data
    form = CustomerEditForm(obj=customer)

    return render_template(
        'admin_customer_form.html',
        form=form,
        customer=customer
    )

@app.route('/admin/customers/edit/<int:customer_id>', methods=['POST'])
@login_required
def admin_edit_customer(customer_id):
    """
    (U)PDATE: Process the edit customer form.
    """
    customer = Customer.query.get_or_404(customer_id)
    form = CustomerEditForm()

    if form.validate_on_submit():
        # Check if email is being changed to one that already exists
        new_email = form.email.data
        if new_email != customer.email:
            existing_customer = Customer.query.filter_by(email=new_email).first()
            if existing_customer:
                flash('That email is already in use by another customer.', 'danger')
                return render_template('admin_customer_form.html', form=form, customer=customer)

        # Update the customer's details
        customer.name = form.name.data
        customer.contact_number = form.contact_number.data
        customer.email = new_email

        # Check if a new password was entered
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

    # If form validation fails, show the form again with errors
    return render_template(
        'admin_customer_form.html',
        form=form,
        customer=customer
    )

# ===============================================
# MODULE 6: SALES REPORTING
# ===============================================

@app.route('/admin/sales_reports')
@login_required
def admin_sales_reports():
    """
    (R)EAD: Display sales reports and analytics.
    """

    # --- 1. Top Selling Items Report ---
    # This query groups items by their variant_id,
    # joins with Product and ProductVariant to get their names,
    # and sums up the total quantity sold for each.
    top_selling_items = db.session.query(
        Product.name,
        ProductVariant.size_name,
        func.sum(OrderItem.quantity).label('total_sold')
    ).join(Product, Product.product_id == OrderItem.product_id)\
     .join(ProductVariant, ProductVariant.variant_id == OrderItem.variant_id)\
     .group_by(OrderItem.variant_id)\
     .order_by(func.sum(OrderItem.quantity).desc())\
     .all()

    # --- 2. Sales Per Day Report (Example) ---
    # This query groups orders by the date they were created
    # and sums up the final_amount for each day.
    sales_by_day = db.session.query(
        func.date(Order.order_date).label('date'),
        func.sum(Order.final_amount).label('total_sales')
    ).group_by(func.date(Order.order_date))\
     .order_by(func.date(Order.order_date).desc())\
     .limit(30).all() # Get last 30 days

    return render_template(
        'admin_sales_reports.html',
        top_selling_items=top_selling_items,
        sales_by_day=sales_by_day
    )

@app.route('/admin/export/sales_csv')
@login_required
def admin_export_sales_csv():
    """
    (R)EAD: Generate and download a CSV file of daily sales.
    """
    try:
        # 1. Run the same query as the sales report page
        sales_by_day_query = db.session.query(
            func.date(Order.order_date).label('date'),
            func.sum(Order.final_amount).label('total_sales')
        ).group_by(func.date(Order.order_date))\
         .order_by(func.date(Order.order_date).desc())

        # 2. Use Pandas to read the query directly
        # This is a bit advanced, but it's the most efficient way
        df = pd.read_sql(sales_by_day_query.statement, db.engine)

        # 3. Rename columns for a user-friendly CSV
        df = df.rename(columns={
            'date': 'Date',
            'total_sales': 'Total Sales (PHP)'
        })

        # 4. Create an in-memory file to hold the CSV
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0) # Go to the start of the file

        # 5. Create the file download response
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=sales_report.csv"
        response.headers["Content-type"] = "text/csv"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the CSV: {e}", 'danger')
        return redirect(url_for('admin_sales_reports'))

# ===============================================
# MODULE 7: USER (STAFF) MANAGEMENT (CRUD)
# ===============================================

@app.route('/admin/users', methods=['GET'])
@login_required
def admin_users():
    """
    (R)EAD: Display all staff users.
    """
    # We query all users except our own, to list them
    users = User.query.order_by(User.username.asc()).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/add', methods=['GET', 'POST'])
@login_required
def admin_add_user():
    """
    (C)REATE: Add a new staff user.
    """
    form = UserAddForm()
    if form.validate_on_submit():
        # Check if username already exists
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash('That username is already taken. Please choose a different one.', 'danger')
            return render_template('admin_user_form.html', form=form, form_title="Add New Staff User", action_url=url_for('admin_add_user'))

        # Create new user
        new_user = User(
            username=form.username.data,
            role=form.role.data
        )
        new_user.set_password(form.password.data) # Hash the password

        db.session.add(new_user)
        try:
            db.session.commit()
            flash(f"Staff user '{new_user.username}' created successfully.", 'success')
            return redirect(url_for('admin_users'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating user: {e}", 'danger')

    # Show the form on a GET request
    return render_template(
        'admin_user_form.html',
        form=form,
        form_title="Add New Staff User",
        action_url=url_for('admin_add_user')
    )


@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    """
    (U)PDATE: Edit an existing staff user.
    """
    user = User.query.get_or_404(user_id)
    # Use the UserEditForm, pre-filled with user's data
    form = UserEditForm(obj=user)

    if form.validate_on_submit():
        # Check if username is being changed to one that already exists
        new_username = form.username.data
        if new_username != user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user:
                flash('That username is already taken. Please choose a different one.', 'danger')
                return render_template('admin_user_form.html', form=form, form_title=f"Edit User: {user.username}", action_url=url_for('admin_edit_user', user_id=user_id))

        # Update fields
        user.username = new_username
        user.role = form.role.data

        # Check if a new password was entered
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

    # Show the pre-filled form on a GET request
    return render_template(
        'admin_user_form.html',
        form=form,
        form_title=f"Edit User: {user.username}",
        action_url=url_for('admin_edit_user', user_id=user_id)
    )


@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    """
    (D)ELETE: Delete a staff user.
    """
    # Security check: You can't delete yourself.
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