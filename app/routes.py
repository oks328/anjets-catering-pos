import os
import secrets
from PIL import Image
from flask import current_app as app
from flask import render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, current_user, login_required
from app.models import User
from app.forms import AdminLoginForm
from app import db 
from app.models import User, Category 
from app.forms import AdminLoginForm, CategoryForm 
from app.models import User, Category, Product, ProductVariant # <-- ADD Product, ProductVariant
from app.forms import AdminLoginForm, CategoryForm, ProductForm # <-- ADD ProductForm
from app.forms import AdminLoginForm, CategoryForm, ProductForm, VariantForm # <-- ADD VariantForm
from app.models import User, Category, Product, ProductVariant, Voucher # <-- ADD Voucher
from app.forms import AdminLoginForm, CategoryForm, ProductForm, VariantForm, VoucherForm # <-- ADD VoucherForm
from app.forms import VoucherForm, UserAddForm, UserEditForm




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

@app.route('/')
def client_home():
    """
    Client-facing homepage.
    """
    # This tells Flask to render your new HTML file
    return render_template('client_home.html')

@app.route('/menu')
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

# ===============================================
# CLIENT-SIDE: SHOPPING CART
# ===============================================

@app.route('/cart/add', methods=['POST'])
def add_to_cart():
    """
    Add a product to the user's session cart.
    """
    cart = session.get('cart', {})
    product_id = request.form.get('product_id')
    
    # --- THIS IS THE FIX ---
    # Get the product object *before* the if/else logic.
    # This ensures the 'product' variable always exists.
    product = Product.query.get_or_404(product_id)
    # -----------------------

    quantity = 1
    
    if product_id in cart:
        # If item is already in cart, increment quantity
        cart[product_id]['quantity'] += quantity
    else:
        # If new, add it to the cart
        # We already have the 'product' object
        cart[product_id] = {
            'name': product.name,
            'quantity': quantity
        }
    
    session['cart'] = cart
    
    print("Updated Cart:", session['cart'])
    
    # Now this line will always work
    flash(f"Added {product.name} to cart!", 'success')
    return redirect(url_for('client_menu'))

@app.route('/cart')
def client_cart():
    """
    (R)EAD: Display the user's shopping cart.
    """
    # Get the cart from the session, default to an empty dict
    cart_session = session.get('cart', {})
    
    cart_items = []
    total_price = 0.0

    # Loop through items in the session cart to get full details
    for product_id, item_data in cart_session.items():
        product = Product.query.get(product_id)
        
        if product:
            # --- This logic gets the price ---
            price = 0.0
            if product.has_variants:
                # If it has variants, grab the cheapest one (for now)
                if product.variants:
                    price = min(v.price for v in product.variants)
            else:
                # If it's a simple product, grab the 'Regular' price
                if product.variants:
                    price = product.variants[0].price
            # --- End of price logic ---
            
            quantity = item_data['quantity']
            line_total = float(price) * quantity
            total_price += line_total
            
            cart_items.append({
                'id': product.product_id,
                'name': product.name,
                'image': product.image_file,
                'price': float(price),
                'quantity': quantity,
                'line_total': line_total
            })

    return render_template(
        'client_cart.html', 
        cart_items=cart_items, 
        total_price=total_price
    )

@app.route('/cart/remove/<string:product_id>')
def remove_from_cart(product_id):
    """
    Remove an item from the shopping cart.
    """
    cart = session.get('cart', {})
    
    # Use .pop() to remove the item if it exists
    item_name = cart.pop(product_id, None) 
    
    if item_name:
        flash(f"Removed {item_name['name']} from cart.", 'info')
    
    # Save the modified cart back to the session
    session['cart'] = cart
    
    return redirect(url_for('client_cart'))


@app.route('/cart/update', methods=['POST'])
def update_cart_quantity():
    """
    Update the quantity of an item in the cart.
    """
    cart = session.get('cart', {})
    product_id = request.form.get('product_id')
    
    # Get the new quantity from the form, default to 1
    try:
        quantity = int(request.form.get('quantity'))
        if quantity < 1:
            quantity = 1 # Minimum quantity is 1
    except:
        quantity = 1 # Default to 1 if something goes wrong
    
    # Update the cart if the item exists
    if product_id in cart:
        cart[product_id]['quantity'] = quantity
        flash(f"Updated {cart[product_id]['name']} quantity.", 'success')
        
    session['cart'] = cart
    
    return redirect(url_for('client_cart'))

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


@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """
    The main admin dashboard page.
    """
    # This route now renders our new HTML page
    return render_template('admin_dashboard.html')


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
            # THIS IS THE CRITICAL LINE FOR "CREATE"
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
            flash(f"Voucher '{voucher.code}' has been Activated.", 'success')
        else:
            flash(f"Voucher '{voucher.code}' has been Deactivated.", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f"Error changing voucher status: {e}", 'danger')

    # Redirect back to the correct anchor
    return redirect(url_for('admin_vouchers') + '#existing-vouchers-card')

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

