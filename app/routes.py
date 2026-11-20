import csv
import hmac
import io
import os
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from threading import Thread
from xml.dom import minidom

from flask import (
    abort,
    current_app,
    flash,
    get_flashed_messages,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask import current_app as app
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message
from PIL import Image
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import db, mail
from app.auth import credential_signature, customer_login_required, sign_in_customer
from app.checkout import (
    clear_checkout_session,
    current_quote,
    invalidate_quote,
    positive_quantity,
    quote_signature,
    validate_cart,
    validate_event_details,
)
from app.forms import (
    AdminLoginForm,
    CategoryForm,
    CustomerEditForm,
    CustomerLoginForm,
    CustomerProfileForm,
    CustomerRegisterForm,
    DiscountVerificationForm,
    GCashPaymentForm,
    ProductForm,
    RequestResetForm,
    ResetPasswordForm,
    ReviewForm,
    UserAddForm,
    UserEditForm,
    VariantForm,
    VoucherForm,
)
from app.menu_import import import_menu_csv
from app.models import (
    Category,
    Customer,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    Review,
    User,
    Voucher,
)
from app.order_workflow import (
    allowed_order_statuses,
    transition_order,
    verify_gcash_payment,
)
from app.pricing import ZERO, calculate_order_totals, money
from app.reporting import business_timezone, sales_filters, sales_report, utc_boundary

MAIN_CATEGORIES = ["Pork", "Beef", "Chicken", "Seafood"]

CATEGORY_ORDER = [
    "Beef",
    "Pork",
    "Chicken",
    "Seafood",
    "Pasta & Noodles",
    "Noodles",
    "Vegetables",
    "Dessert",
    "Drinks",
]


def get_category_choices():

    categories = Category.query.filter_by(is_active=True).all()
    return [(c.category_id, c.name) for c in categories]


def save_picture(form_picture):
    """
    Helper function to save an uploaded picture.
    FIXED: Uses file stream explicitly and ensures the products directory exists.
    """
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.config["UPLOAD_FOLDER"], "products", picture_fn)

    os.makedirs(os.path.dirname(picture_path), exist_ok=True)

    output_size = (800, 800)

    form_picture.stream.seek(0)
    i = Image.open(form_picture.stream)

    i.thumbnail(output_size)
    i.save(picture_path)

    return picture_fn


def save_payment_receipt(form_picture):

    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext

    picture_path = os.path.join(app.config["PRIVATE_UPLOAD_FOLDER"], "payments", picture_fn)

    os.makedirs(os.path.dirname(picture_path), exist_ok=True)

    output_size = (800, 800)
    i = Image.open(form_picture)
    i.thumbnail(output_size)
    i.save(picture_path)

    return f"payments/{picture_fn}"


@login_required
def admin_private_upload(filename):
    if current_user.role != "Admin":
        abort(403)
    parts = filename.replace("\\", "/").split("/")
    if len(parts) != 2 or parts[0] not in ("ids", "payments") or parts[1] in ("", ".", ".."):
        abort(404)
    root = app.config["PRIVATE_UPLOAD_FOLDER"]
    # Keep existing documents accessible to admins while new uploads use private storage.
    if not os.path.isfile(os.path.join(root, *parts)):
        root = app.config["UPLOAD_FOLDER"]
    response = send_from_directory(root, "/".join(parts), conditional=False)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def google_login_complete():
    return redirect(url_for("google_login"))


def client_home():

    top_product_ids = (
        db.session.query(OrderItem.product_id, func.sum(OrderItem.quantity).label("total_sold"))
        .group_by(OrderItem.product_id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(3)
        .all()
    )

    product_ids = [pid for pid, total in top_product_ids]
    popular_products = Product.query.filter(
        Product.product_id.in_(product_ids), Product.is_active.is_(True)
    ).all()

    return render_template("client_home.html", popular_products=popular_products)


def client_menu():

    category_id = request.args.get("category_id", type=int)

    categories = Category.query.filter_by(is_active=True).all()

    def get_sort_index(cat_name):

        try:
            return CATEGORY_ORDER.index(cat_name)
        except ValueError:
            return 999

    categories.sort(key=lambda c: get_sort_index(c.name))

    selected_category = None
    product_query = Product.query.join(Category).filter(
        Category.is_active.is_(True), Product.is_active.is_(True)
    )

    if category_id:
        product_query = product_query.filter(Product.category_id == category_id)
        selected_category = Category.query.get(category_id)

    products = product_query.order_by(Product.name.asc()).all()

    product_ids = [p.product_id for p in products]

    ratings_query = (
        db.session.query(
            Review.product_id,
            func.avg(Review.rating).label("average_rating"),
            func.count(Review.review_id).label("review_count"),
        )
        .filter(Review.product_id.in_(product_ids))
        .group_by(Review.product_id)
        .all()
    )

    ratings_map = {
        item.product_id: {"avg": float(item.average_rating), "count": item.review_count}
        for item in ratings_query
    }

    return render_template(
        "client_menu.html",
        categories=categories,
        products=products,
        selected_category=selected_category,
        ratings_map=ratings_map,
    )


def has_reviewed_product(customer_id, product_id):

    return (
        Review.query.filter_by(customer_id=customer_id, product_id=product_id).first() is not None
    )


@login_required
def admin_add_category():

    add_form = CategoryForm()

    if add_form.validate_on_submit():
        new_category = Category(name=add_form.name.data, description=add_form.description.data)

        db.session.add(new_category)
        try:
            db.session.commit()
            flash(f"Category '{new_category.name}' added successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding category: {e}", "danger")
    else:
        flash("Error: Could not add category. Please check form.", "danger")

    return redirect(url_for("admin_categories") + "#add-category-card")


@login_required
def admin_delete_category(category_id):

    password_attempt = request.form.get("admin_confirm_password")
    if not verify_admin_password(password_attempt):
        flash("Incorrect password. Action cancelled.", "danger")
        return redirect(url_for("admin_categories"))

    category = Category.query.get_or_404(category_id)

    product_count = Product.query.filter_by(category_id=category_id).count()

    if product_count > 0:
        flash(
            f"Cannot delete category '{category.name}'. It contains {product_count} products. Please delete or move them first.",
            "warning",
        )
        return redirect(url_for("admin_categories"))

    try:
        db.session.delete(category)
        db.session.commit()
        flash(f"Category '{category.name}' has been deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting category: {e}", "danger")

    return redirect(url_for("admin_categories"))


@customer_login_required
def client_view_receipt(order_id):

    order = (
        Order.query.options(
            db.joinedload(Order.customer),
            db.joinedload(Order.items).joinedload(OrderItem.product),
            db.joinedload(Order.items).joinedload(OrderItem.variant),
        )
        .filter_by(order_id=order_id)
        .first_or_404()
    )

    if order.customer_id != session["customer_id"]:
        flash("You do not have permission to view that receipt.", "danger")
        return redirect(url_for("client_orders"))

    if order.status not in ("Approved", "In Progress", "Up for Delivery", "Completed"):
        flash("Order documents are available after approval.", "info")
        return redirect(url_for("client_orders"))

    return render_template("client_receipt.html", order=order)


def admin_login():

    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard"))

    form = AdminLoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        user = User.query.filter_by(username=username).first()

        if user and user.role == "Admin" and user.check_password(password):
            login_user(user)
            session["admin_auth_version"] = credential_signature(user)
            flash("Login successful!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid username or password. Please try again.", "danger")
            return redirect(url_for("admin_login"))

    return render_template("admin_login.html", form=form)


@customer_login_required
def client_my_account():

    return redirect(url_for("client_profile"))


@customer_login_required
def client_profile():

    customer = Customer.query.get_or_404(session["customer_id"])
    form = CustomerProfileForm(obj=customer)
    upload_form = DiscountVerificationForm()

    if form.validate_on_submit():
        new_birthdate = form.birthdate.data
        profile_updated_message = "Your profile has been updated."

        if new_birthdate:
            today = date.today()
            age = (
                today.year
                - new_birthdate.year
                - ((today.month, today.day) < (new_birthdate.month, new_birthdate.day))
            )

            if customer.is_verified_discount and customer.discount_type == "Senior":
                if age < 60:
                    customer.is_verified_discount = False
                    customer.discount_status = None
                    customer.discount_type = None
                    customer.id_image_file = None
                    flash(
                        "Your Senior discount has been revoked as your new birthdate makes you ineligible.",
                        "warning",
                    )

                    profile_updated_message = "Your profile and discount status have been updated."

        customer.name = form.name.data
        customer.contact_number = form.contact_number.data
        customer.birthdate = new_birthdate

        customer.landmark = form.landmark.data
        try:
            db.session.commit()
            session["customer_name"] = customer.name

            if "warning" not in [m[0] for m in get_flashed_messages(with_categories=True)]:
                flash(profile_updated_message, "success")

            return redirect(url_for("client_profile"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating profile: {e}", "danger")

    return render_template(
        "client_profile.html", form=form, upload_form=upload_form, customer=customer
    )


@customer_login_required
def client_orders():

    customer_id = session["customer_id"]

    orders = Order.query.filter_by(customer_id=customer_id).order_by(Order.order_date.desc()).all()

    return render_template(
        "client_orders.html", orders=orders, has_reviewed_product=has_reviewed_product
    )


@customer_login_required
def client_upload_id():

    form = DiscountVerificationForm()
    customer = Customer.query.get_or_404(session["customer_id"])

    if form.validate_on_submit():
        if form.id_image.data:
            try:
                id_upload_folder = os.path.join(app.config["PRIVATE_UPLOAD_FOLDER"], "ids")
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
                flash(f"Error uploading image: {e}", "danger")
                return redirect(url_for("client_profile"))

        customer.discount_type = form.discount_type.data
        customer.is_verified_discount = False
        customer.discount_status = "Pending"

        try:
            db.session.commit()
            flash("Your ID has been submitted for verification.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error submitting ID: {e}", "danger")

    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {field}: {error}", "danger")

    return redirect(url_for("client_profile"))


@customer_login_required
def client_review_product(product_id):

    product = db.get_or_404(Product, product_id)
    customer_id = session["customer_id"]
    form = ReviewForm()

    if has_reviewed_product(customer_id, product_id):
        flash("You have already submitted a review for this product.", "danger")
        return redirect(url_for("client_orders"))

    has_bought = (
        db.session.query(OrderItem.order_item_id)
        .join(Order)
        .filter(
            Order.customer_id == customer_id,
            OrderItem.product_id == product_id,
            Order.status == "Completed",
        )
        .first()
    )

    if not has_bought:
        flash("You can only review products from completed orders that you purchased.", "danger")
        return redirect(url_for("client_orders"))

    if form.validate_on_submit():
        new_review = Review(
            product_id=product_id,
            customer_id=customer_id,
            rating=form.rating.data,
            comment=form.comment.data,
        )

        try:
            db.session.add(new_review)
            db.session.commit()
            flash(f"Thank you for reviewing {product.name}!", "success")
            return redirect(url_for("client_orders"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error submitting review: {e}", "danger")

    return render_template("client_review_form.html", form=form, product=product)


def add_to_cart():

    if "customer_id" not in session:
        return jsonify({"status": "login_required", "url": url_for("client_account_page")})

    cart = session.get("cart", {})

    variant_id = request.form.get("variant_id")

    try:
        quantity = int(request.form.get("quantity", 1))
        if quantity < 1:
            quantity = 1
    except (TypeError, ValueError):
        quantity = 1

    if not variant_id:
        return jsonify({"status": "error", "message": "No product size selected."}), 400

    variant = db.session.get(ProductVariant, variant_id)
    if not variant:
        return jsonify({"status": "error", "message": "Could not find that product option."}), 404

    product = variant.product

    if not product.is_active:
        return jsonify(
            {"status": "error", "message": "This product is currently unavailable."}
        ), 400

    if variant_id in cart:
        cart[variant_id]["quantity"] += quantity
    else:
        cart[variant_id] = {
            "product_id": product.product_id,
            "name": product.name,
            "variant_name": variant.size_name,
            "price": str(money(variant.price, positive=True)),
            "image": product.image_file,
            "quantity": quantity,
        }

    session["cart"] = cart

    message = f"Added {quantity} x {product.name} ({variant.size_name}) to cart!"
    return jsonify({"status": "success", "message": message})


def product_details(product_id):
    product = db.get_or_404(Product, product_id)

    buffet_cart = session.get("buffet_package", {})

    variants_data = []
    for variant in product.variants:
        current_quantity = buffet_cart.get(str(variant.variant_id), {}).get("quantity", 0)

        variants_data.append(
            {
                "id": variant.variant_id,
                "size": variant.size_name,
                "price": float(variant.price),
                "current_quantity": current_quantity,
            }
        )

    return jsonify(
        {
            "id": product.product_id,
            "name": product.name,
            "has_variants": product.has_variants,
            "variants": variants_data,
        }
    )


@customer_login_required
def client_cart():
    cart_session = session.get("cart", {})
    cart_items = []

    for item_id, item_data in cart_session.items():
        cart_items.append(
            {
                "product_id": item_data["product_id"],
                "variant_id": item_id,
                "name": item_data["name"],
                "variant_name": item_data["variant_name"],
                "image": item_data["image"],
                "price": money(item_data["price"], positive=True),
                "quantity": int(item_data["quantity"]),
                "line_total": money(item_data["price"], positive=True) * int(item_data["quantity"]),
                "is_buffet_item": item_data.get("is_buffet_item", False),
            }
        )

    customer = db.session.get(Customer, session["customer_id"])

    voucher_code = session.get("voucher_code")
    voucher_percent = session.get("discount_percentage", 0.0)

    if customer and customer.is_verified_discount and voucher_code:
        session.pop("voucher_code", None)
        session.pop("discount_percentage", None)
        voucher_code = None
        voucher_percent = 0.0
        flash(f"Your verified {customer.discount_type} discount has replaced the voucher.", "info")

    pricing_error = None
    try:
        totals = calculate_order_totals(cart_items, customer, 0, voucher_code, voucher_percent)
    except ValueError as error:
        pricing_error = str(error)
        totals = calculate_order_totals([], None)

    available_vouchers = Voucher.query.filter(
        Voucher.is_active.is_(True),
        (Voucher.max_uses.is_(None)) | (Voucher.current_uses < Voucher.max_uses),
    ).all()

    return render_template(
        "client_cart.html",
        pricing_error=pricing_error,
        cart_items=cart_items,
        total_price=totals["subtotal"],
        vatable_sales=totals["vatable_sales"],
        vat_exempt_sales=totals["vat_exempt_sales"],
        vat_amount=totals["vat_amount"],
        total_discount_amount=totals["discount_amount"],
        final_total=totals["final_total"],
        ala_carte_subtotal=0,
        buffet_subtotal=0,
        voucher_discount_amt=0,
        senior_discount_amt=totals["discount_amount"] if customer.is_verified_discount else 0,
        pwd_discount_amt=0,
        available_vouchers=available_vouchers,
        customer=customer,
    )


@customer_login_required
def clear_cart():
    session.pop("cart", None)
    session.pop("voucher_code", None)
    session.pop("discount_percentage", None)
    flash("Cart has been cleared.", "info")
    return redirect(url_for("client_cart"))


@customer_login_required
def remove_from_cart(variant_id):
    cart = session.get("cart", {})

    item_data = cart.pop(variant_id, None)

    if item_data:
        flash(f"Removed {item_data['name']} ({item_data['variant_name']}) from cart.", "info")

    session["cart"] = cart

    return redirect(url_for("client_cart"))


@customer_login_required
def update_cart_quantity():
    cart = session.get("cart", {})

    variant_id = request.form.get("variant_id")
    try:
        quantity = int(request.form.get("quantity"))
        if quantity < 1:
            quantity = 1
    except (TypeError, ValueError):
        quantity = 1

    if variant_id in cart:
        cart[variant_id]["quantity"] = quantity
        flash(f"Updated {cart[variant_id]['name']} quantity.", "success")

    session["cart"] = cart

    return redirect(url_for("client_cart"))


@customer_login_required
def apply_voucher():
    code = request.form.get("voucher_code")

    if not code:
        flash("Please enter a voucher code.", "danger")
        return redirect(url_for("client_cart"))

    voucher = Voucher.query.filter_by(code=code, is_active=True).first()

    if voucher:
        if voucher.max_uses is not None and voucher.current_uses >= voucher.max_uses:
            flash("This voucher code has reached its maximum usage limit.", "danger")
            session.pop("voucher_code", None)
            session.pop("discount_percentage", None)
            return redirect(url_for("client_cart"))

        session["voucher_code"] = voucher.code
        session["discount_percentage"] = str(voucher.discount_percentage)
        flash(f"Voucher '{voucher.code}' applied successfully!", "success")
    else:
        session.pop("voucher_code", None)
        session.pop("discount_percentage", None)
        flash("Invalid or expired voucher code.", "danger")

    return redirect(url_for("client_cart"))


@customer_login_required
def client_checkout():

    cart_session = session.get("cart", {})
    if not cart_session:
        flash("Your cart is empty.", "info")
        return redirect(url_for("client_cart"))
    if "order_type" not in session:
        flash("Please select your delivery or pickup option first.", "info")
        return redirect(url_for("client_checkout_options"))

    customer = db.session.get(Customer, session["customer_id"])
    try:
        items, totals, signature = current_quote(session, customer)
    except ValueError as error:
        flash(str(error), "warning")
        return redirect(url_for("client_cart"))
    if (
        session.get("gcash_image_file")
        and session.get("payment_method") == "GCash"
        and session.get("gcash_quote") != signature
    ):
        invalidate_quote(session)
        flash(
            "Your order total changed. Review the updated amount and upload new payment proof.",
            "warning",
        )
        return redirect(url_for("client_checkout_options"))
    session["checkout_quote"] = signature
    cart_items = [
        dict(item, name=item["product_name"], line_total=item["price"] * item["quantity"])
        for item in items
    ]
    delivery_fee = 100 if session.get("order_type") == "Delivery" else 0
    payment_method = session.get("payment_method", "COD/COP")
    gcash_uploaded = payment_method == "GCash" and session.get("gcash_image_file") is not None

    session.setdefault("checkout_token", secrets.token_hex(32))
    return render_template(
        "client_checkout.html",
        cart_items=cart_items,
        total_price=totals["subtotal"],
        vatable_sales=totals["vatable_sales"],
        vat_exempt_sales=totals["vat_exempt_sales"],
        vat_amount=totals["vat_amount"],
        total_discount_amount=totals["discount_amount"],
        delivery_fee=delivery_fee,
        final_total=totals["final_total"],
        payment_method=payment_method,
        gcash_uploaded=gcash_uploaded,
        voucher_discount_amt=0,
        senior_discount_amt=totals["discount_amount"] if customer.is_verified_discount else 0,
        pwd_discount_amt=0,
    )


@customer_login_required
def client_checkout_options():

    cart_session = session.get("cart", {})
    if not cart_session:
        flash("Your cart is empty.", "info")
        return redirect(url_for("client_cart"))

    min_days = 3

    for item in cart_session.values():
        if item.get("is_buffet_item", False):
            min_days = 7
            break

    customer = db.session.get(Customer, session["customer_id"])
    default_address = customer.address

    return render_template(
        "client_checkout_options.html",
        default_address=default_address,
        customer=customer,
        min_days=min_days,
    )


@customer_login_required
def save_checkout_options():
    event_date_str = request.form.get("event_date")
    event_time_str = request.form.get("event_time")
    order_type = request.form.get("order_type")
    delivery_address = request.form.get("delivery_address")
    landmark = request.form.get("landmark")
    payment_method = request.form.get("payment_method")
    try:
        items = validate_cart(session.get("cart"))
        validate_event_details(
            {
                "event_date_str": event_date_str,
                "event_time_str": event_time_str,
                "order_type": order_type,
                "delivery_address": delivery_address,
                "payment_method": payment_method,
            },
            items,
        )
    except ValueError as error:
        flash(str(error), "danger")
        return redirect(url_for("client_checkout_options"))
    for key in (
        "checkout_quote",
        "gcash_quote",
        "gcash_image_file",
        "gcash_reference_no",
        "final_total",
        "card_last_four",
        "card_type",
        "card_holder_name",
    ):
        session.pop(key, None)

    if order_type == "Delivery":
        if not delivery_address:
            flash("Please provide a delivery address.", "danger")
            return redirect(url_for("client_checkout_options"))

        full_address = delivery_address
        if landmark:
            full_address += f" (Landmark: {landmark})"

        session["delivery_fee"] = 100.00
        session["order_type"] = "Delivery"
        session["delivery_address"] = full_address

    else:
        session["delivery_fee"] = 0.00
        session["order_type"] = "Pickup"
        session["delivery_address"] = "Store Pickup"

    session["event_date_str"] = event_date_str
    session["event_time_str"] = event_time_str
    session["payment_method"] = payment_method

    if payment_method == "GCash":
        customer = db.session.get(Customer, session["customer_id"])
        try:
            _, totals, signature = current_quote(session, customer)
        except ValueError as error:
            flash(str(error), "warning")
            return redirect(url_for("client_cart"))
        session["checkout_quote"] = signature
        session["final_total"] = str(totals["final_total"])
        return redirect(url_for("client_gcash_upload"))

    return redirect(url_for("client_checkout"))


@customer_login_required
def client_gcash_upload():

    if session.get("payment_method") != "GCash":
        flash("Invalid checkout step.", "danger")
        return redirect(url_for("client_checkout_options"))

    customer = db.session.get(Customer, session["customer_id"])
    try:
        _, totals, signature = current_quote(session, customer)
    except ValueError as error:
        flash(str(error), "warning")
        return redirect(url_for("client_cart"))
    if session.get("checkout_quote") != signature:
        invalidate_quote(session)
        flash(
            "Your order details changed. Review the latest amount before uploading payment proof.",
            "warning",
        )
        return redirect(url_for("client_checkout_options"))
    final_total = totals["final_total"]

    form = GCashPaymentForm()

    if form.validate_on_submit():
        if form.receipt_image.data:
            try:
                image_filename = save_payment_receipt(form.receipt_image.data)
            except Exception as e:
                flash(f"Error uploading image: {e}", "danger")
                return redirect(url_for("client_gcash_upload"))

        session["gcash_quote"] = signature
        session["gcash_image_file"] = image_filename
        session["gcash_reference_no"] = form.reference_number.data

        flash("Payment proof uploaded. Proceeding to order placement.", "success")
        return redirect(url_for("client_checkout"))

    return render_template("client_gcash_upload.html", form=form, final_total=final_total)


def order_success_response(order):
    if order.checkout_token and session.get("checkout_token") == order.checkout_token:
        clear_checkout_session(session)
    return jsonify(
        {
            "status": "success",
            "message": f"Order #{order.order_id} has been placed!",
            "redirect_url": url_for("client_orders"),
        }
    )


@customer_login_required
def place_order():
    token = request.form.get("checkout_token", "")
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        return jsonify(
            {"status": "error", "message": "Please reload the checkout page before submitting."}
        ), 400
    previous = Order.query.filter_by(
        customer_id=session["customer_id"], checkout_token=token
    ).first()
    if previous:
        return order_success_response(previous)
    expected = session.get("checkout_token", "")
    if not isinstance(expected, str) or not hmac.compare_digest(token, expected):
        return jsonify(
            {"status": "error", "message": "Checkout expired. Please reload the checkout page."}
        ), 400
    try:
        items = validate_cart(session.get("cart"))
        event_date, event_time = validate_event_details(session, items)
        customer = db.session.get(Customer, session["customer_id"])
        if not customer:
            raise ValueError("Please log in again.")
        voucher_code = session.get("voucher_code")
        voucher_percent = 0
        if customer.is_verified_discount and customer.discount_status == "Approved":
            voucher_code = None
        if voucher_code:
            voucher = Voucher.query.filter_by(code=voucher_code, is_active=True).first()
            if not voucher or (
                voucher.max_uses is not None and voucher.current_uses >= voucher.max_uses
            ):
                raise ValueError("This voucher is no longer available. Please remove it.")
            voucher_percent = voucher.discount_percentage
            reserved = Voucher.query.filter(
                Voucher.voucher_id == voucher.voucher_id,
                Voucher.is_active.is_(True),
                Voucher.discount_percentage == voucher.discount_percentage,
                (Voucher.max_uses.is_(None) | (Voucher.current_uses < Voucher.max_uses)),
            ).update({Voucher.current_uses: Voucher.current_uses + 1}, synchronize_session=False)
            if reserved != 1:
                raise ValueError("This voucher is no longer available. Please remove it.")

        payment_method = session["payment_method"]
        is_gcash = payment_method == "GCash"
        proof = session.get("gcash_image_file") if is_gcash else None
        reference = session.get("gcash_reference_no") if is_gcash else None
        if is_gcash and (not proof or not reference):
            raise ValueError("GCash payment proof is missing. Please upload it first.")
        delivery_fee = 100.0 if session["order_type"] == "Delivery" else 0.0
        totals = calculate_order_totals(
            items, customer, delivery_fee, voucher_code, voucher_percent
        )
        signature = quote_signature(items, totals, session)
        if session.get("checkout_quote") != signature or (
            is_gcash and session.get("gcash_quote") != signature
        ):
            db.session.rollback()
            invalidate_quote(session)
            message = (
                "Your order details changed. Please review the latest total before confirming."
            )
            flash(message, "warning")
            return jsonify(
                {
                    "status": "error",
                    "message": message,
                    "redirect_url": url_for(
                        "client_checkout_options" if is_gcash else "client_checkout"
                    ),
                }
            ), 409
        new_order = Order(
            checkout_token=token,
            customer_id=customer.customer_id,
            total_amount=totals["subtotal"],
            discount_amount=totals["discount_amount"],
            vat_amount=totals["vat_amount"],
            final_amount=totals["final_total"],
            status="Pending Payment Verification" if is_gcash else "Pending Approval",
            event_date=event_date,
            event_time=event_time,
            order_type=session["order_type"],
            delivery_address=session.get("delivery_address") if delivery_fee else "Store Pickup",
            delivery_fee=delivery_fee,
            special_instructions=request.form.get("special_instructions"),
            payment_method=payment_method,
            payment_status="Pending Verification" if is_gcash else "Pending",
            payment_image_file=proof,
            gcash_reference_no=reference,
        )
        db.session.add(new_order)
        db.session.flush()
        for item in items:
            db.session.add(
                OrderItem(
                    order_id=new_order.order_id,
                    product_id=item["product_id"],
                    variant_id=item["variant_id"],
                    quantity=item["quantity"],
                    price_per_item=item["price"],
                    product_name_snapshot=item["product_name"],
                    variant_name_snapshot=item["variant_name"],
                )
            )
        db.session.commit()
        clear_checkout_session(session)
        return order_success_response(new_order)
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        # A concurrent request may already have committed this checkout, including its voucher.
        previous = Order.query.filter_by(
            customer_id=session["customer_id"], checkout_token=token
        ).first()
        if previous:
            return order_success_response(previous)
        if isinstance(error, ValueError):
            return jsonify({"status": "error", "message": str(error)}), 400
        app.logger.exception("Order placement failed")
        return jsonify(
            {"status": "error", "message": "Could not place your order. Please try again."}
        ), 500
    except Exception:
        db.session.rollback()
        app.logger.exception("Order placement failed")
        return jsonify(
            {"status": "error", "message": "Could not place your order. Please try again."}
        ), 500


def client_account_page():
    if "customer_id" in session:
        return redirect(url_for("client_home"))

    login_form = CustomerLoginForm()

    return render_template("client_login.html", login_form=login_form)


def client_register_page():
    if "customer_id" in session:
        return redirect(url_for("client_home"))

    register_form = CustomerRegisterForm()

    return render_template("client_register.html", register_form=register_form)


def client_logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    session.pop("customer_auth_version", None)
    clear_checkout_session(session)

    flash("You have been logged out.", "info")
    return redirect(url_for("client_home"))


def client_register():
    register_form = CustomerRegisterForm()

    if register_form.validate_on_submit():
        new_customer = Customer(
            name=register_form.name.data,
            contact_number=register_form.contact_number.data,
            address=register_form.address.data,
            landmark=register_form.landmark.data,
            email=register_form.email.data.lower(),
            birthdate=register_form.birthdate.data,
        )
        new_customer.set_password(register_form.password.data)

        db.session.add(new_customer)
        try:
            db.session.commit()
            sign_in_customer(new_customer)

            flash(f"Welcome, {new_customer.name}! Your account has been created.", "success")
            return redirect(url_for("client_home"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating account: {e}", "danger")

    return render_template("client_register.html", register_form=register_form)


def client_login():
    login_form = CustomerLoginForm()

    if login_form.validate_on_submit():
        customer = Customer.query.filter_by(email=login_form.email.data).first()

        if customer and customer.check_password(login_form.password.data):
            sign_in_customer(customer)

            flash(f"Welcome back, {customer.name}!", "success")
            return redirect(url_for("client_home"))
        else:
            flash("Invalid email or password. Please try again.", "danger")

    return render_template("client_login.html", login_form=login_form)


def send_async_email(app, msg):
    with app.app_context():
        mail.send(msg)


def send_reset_email(customer):
    token = customer.get_reset_token()

    sender_email = current_app.config.get("MAIL_USERNAME") or "noreply@demo.com"

    msg = Message("Password Reset Request", sender=sender_email, recipients=[customer.email])

    msg.html = render_template("reset_email.html", customer=customer, token=token)

    from threading import Thread

    app = current_app._get_current_object()
    thread = Thread(target=send_async_email, args=(app, msg))
    thread.start()
    return thread


def client_forgot_password():
    if "customer_id" in session:
        return redirect(url_for("client_home"))

    form = RequestResetForm()
    if form.validate_on_submit():
        customer = Customer.query.filter_by(email=form.email.data).first()
        if customer:
            send_reset_email(customer)
        flash("If an account exists with that email, a reset link has been sent.", "info")
        return redirect(url_for("client_account_page"))

    return render_template("client_forgot_password.html", form=form)


def client_reset_token(token):
    if "customer_id" in session:
        return redirect(url_for("client_home"))

    customer = Customer.verify_reset_token(token)
    if customer is None:
        flash("That is an invalid or expired token.", "danger")
        return redirect(url_for("client_forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        customer.set_password(form.password.data)
        db.session.commit()
        flash("Your password has been updated! You are now able to log in.", "success")
        return redirect(url_for("client_account_page"))

    return render_template("client_reset_password.html", form=form)


def buffet_wizard_start():
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()
    return render_template("client_buffet_step1.html", categories=categories)


def buffet_wizard_reco():
    try:
        guest_count = int(request.form.get("guest_count"))
        if guest_count < 1:
            guest_count = 1
    except (TypeError, ValueError):
        guest_count = 30

    selected_categories = request.form.getlist("categories")

    if not selected_categories:
        flash("Please select at least one category to include in your buffet.", "danger")
        return redirect(url_for("buffet_wizard_start"))

    def get_sort_index(cat_name):
        try:
            return CATEGORY_ORDER.index(cat_name)
        except ValueError:
            return 999

    selected_categories.sort(key=get_sort_index)

    recommendations = {}

    total_mains_needed = (guest_count + 9) // 10
    recommendations["Shared_Mains"] = total_mains_needed

    for category_name in selected_categories:
        if category_name in MAIN_CATEGORIES:
            continue
        elif category_name in ["Pasta & Noodles", "Vegetables", "Dessert"]:
            count = (guest_count + 14) // 15
            recommendations[category_name] = count
        else:
            recommendations[category_name] = (guest_count + 9) // 10

    session["buffet_recommendations"] = recommendations
    session["buffet_guest_count"] = guest_count
    session["buffet_package"] = {}

    session["buffet_sequence"] = selected_categories

    return redirect(url_for("buffet_wizard_select", category_name=selected_categories[0]))


@customer_login_required
def buffet_wizard_select(category_name):
    recommendations = session.get("buffet_recommendations")
    wizard_sequence = session.get("buffet_sequence")

    if not recommendations or not wizard_sequence:
        flash("Your buffet session has expired. Please start over.", "danger")
        return redirect(url_for("buffet_wizard_start"))

    category_obj = Category.query.filter_by(name=category_name, is_active=True).first_or_404()
    products = (
        Product.query.filter_by(category_id=category_obj.category_id, is_active=True)
        .order_by(Product.name.asc())
        .all()
    )

    buffet_package = session.get("buffet_package", {})

    is_main_category = category_name in MAIN_CATEGORIES

    if is_main_category:
        required_count = recommendations.get("Shared_Mains", 0)
        current_count = 0
        for item in buffet_package.values():
            if item["category"] in MAIN_CATEGORIES:
                current_count += item["quantity"]
    else:
        required_count = recommendations.get(category_name, 0)
        current_count = 0
        for item in buffet_package.values():
            if item["category"] == category_name:
                current_count += item["quantity"]

    current_selections = []
    current_total_price = ZERO

    for variant_id, item_data in buffet_package.items():
        current_total_price += money(item_data["price"], positive=True) * item_data["quantity"]

        if item_data["category"] == category_name:
            item_data["variant_id"] = variant_id
            current_selections.append(item_data)

    current_index = wizard_sequence.index(category_name)

    if current_index > 0:
        previous_category = wizard_sequence[current_index - 1]
        previous_url = url_for("buffet_wizard_select", category_name=previous_category)
    else:
        previous_url = url_for("buffet_wizard_start")

    is_final_category = current_index == len(wizard_sequence) - 1
    if is_final_category:
        next_url = url_for("buffet_wizard_checkout")
    else:
        next_category = wizard_sequence[current_index + 1]
        next_url = url_for("buffet_wizard_select", category_name=next_category)

    min_to_proceed = required_count
    if is_main_category:
        remaining_categories = wizard_sequence[current_index + 1 :]
        has_more_mains = any(cat in MAIN_CATEGORIES for cat in remaining_categories)
        if has_more_mains:
            min_to_proceed = 0
        else:
            min_to_proceed = required_count

    return render_template(
        "client_buffet_select.html",
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
        current_step=current_index + 1,
        total_steps=len(wizard_sequence),
        current_total_price=current_total_price,
    )


@customer_login_required
def buffet_wizard_checkout():
    buffet_package = session.get("buffet_package", {})

    total_price = ZERO
    for item_data in buffet_package.values():
        total_price += money(item_data["price"], positive=True) * item_data["quantity"]

    return render_template(
        "client_buffet_checkout.html", buffet_package=buffet_package, total_price=total_price
    )


@customer_login_required
def buffet_commit_package():
    buffet_package = session.get("buffet_package", {})
    if not buffet_package:
        flash("Buffet package is empty. Please start over.", "danger")
        return redirect(url_for("buffet_wizard_start"))

    main_cart = session.get("cart", {})

    for variant_id, item_data in buffet_package.items():
        cart_key = f"buffet_{variant_id}"

        if cart_key in main_cart:
            main_cart[cart_key]["quantity"] += item_data["quantity"]
        else:
            main_cart[cart_key] = {
                "product_id": item_data["product_id"],
                "name": item_data["product_name"],
                "variant_id": variant_id,
                "variant_name": item_data["variant_name"],
                "price": item_data["price"],
                "image": item_data["image"],
                "quantity": item_data["quantity"],
                "is_buffet_item": True,
            }

    session["cart"] = main_cart

    session.pop("buffet_package", None)
    session.pop("buffet_recommendations", None)
    session.pop("buffet_sequence", None)
    session.pop("buffet_guest_count", None)

    flash("Success! Your custom buffet package has been added to the cart.", "success")
    return redirect(url_for("client_cart"))


@customer_login_required
def buffet_remove_item(variant_id):
    buffet_package = session.get("buffet_package", {})

    item_data = buffet_package.pop(variant_id, None)

    if item_data:
        flash(f"Removed {item_data['product_name']} from your buffet.", "info")

    session["buffet_package"] = buffet_package

    return redirect(url_for("buffet_wizard_checkout"))


@customer_login_required
def buffet_update_quantity():
    buffet_package = session.get("buffet_package", {})
    variant_id = request.form.get("variant_id")

    try:
        quantity = int(request.form.get("quantity"))
        if quantity < 1:
            quantity = 1
    except (TypeError, ValueError):
        quantity = 1

    if variant_id in buffet_package:
        buffet_package[variant_id]["quantity"] = quantity
        flash(f"Updated {buffet_package[variant_id]['product_name']} quantity.", "success")

    session["buffet_package"] = buffet_package

    return redirect(url_for("buffet_wizard_checkout"))


@customer_login_required
def buffet_add_item():
    variant_id = request.form.get("variant_id")
    force_add = request.form.get("force", "false").lower() == "true"
    try:
        quantity = positive_quantity(request.form.get("quantity", 1))
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400

    buffet_cart = session.get("buffet_package", {})
    recommendations = session.get("buffet_recommendations", {})

    if not variant_id:
        return jsonify({"status": "error", "message": "No variant selected."}), 400

    variant = db.session.get(ProductVariant, variant_id)
    if not variant:
        return jsonify({"status": "error", "message": "Item not found."}), 404

    product = variant.product

    if not product.is_active:
        return jsonify({"status": "error", "message": "This item is currently unavailable."}), 400
    category_name = product.category.name

    if category_name in MAIN_CATEGORIES:
        current_count = 0
        for item in buffet_cart.values():
            if item["category"] in MAIN_CATEGORIES:
                current_count += item["quantity"]
        recommended_count = recommendations.get("Shared_Mains", 0)
    else:
        current_count = 0
        for item in buffet_cart.values():
            if item["category"] == category_name:
                current_count += item["quantity"]
        recommended_count = recommendations.get(category_name, 0)

    potential_new_count = current_count + quantity

    if potential_new_count > recommended_count and not force_add:
        return jsonify(
            {
                "status": "warning",
                "message": f"You've selected {potential_new_count} items for this section, but the recommendation is {recommended_count}. Add anyway?",
            }
        )

    if variant_id in buffet_cart:
        buffet_cart[variant_id]["quantity"] += quantity
    else:
        buffet_cart[variant_id] = {
            "product_id": product.product_id,
            "product_name": product.name,
            "variant_name": variant.size_name,
            "quantity": quantity,
            "category": category_name,
            "price": str(money(variant.price, positive=True)),
            "image": product.image_file,
        }

    session["buffet_package"] = buffet_cart

    new_total_price = ZERO
    for item in buffet_cart.values():
        new_total_price += money(item["price"], positive=True) * item["quantity"]

    return jsonify(
        {
            "status": "success",
            "message": f"Added {product.name}",
            "new_total_price": float(new_total_price),
        }
    )


@customer_login_required
def buffet_remove_item_from_package(variant_id, category_name):
    buffet_package = session.get("buffet_package", {})

    if variant_id in buffet_package:
        item_name = buffet_package.pop(variant_id)["product_name"]
        flash(f"Removed {item_name} from your selections.", "info")

    session["buffet_package"] = buffet_package

    return redirect(url_for("buffet_wizard_select", category_name=category_name))


@customer_login_required
def buffet_review_and_add():

    return redirect(url_for("client_cart"))


@login_required
def admin_dashboard():

    today = datetime.now(business_timezone()).date()
    today_start = utc_boundary(today)
    month_start = utc_boundary(today.replace(day=1))
    orders_today_count = Order.query.filter(
        Order.order_date >= today_start,
        Order.order_date < utc_boundary(today + timedelta(days=1)),
        Order.status != "Declined",
    ).count()
    total_sales_month = (
        db.session.query(func.sum(Order.final_amount))
        .filter(*sales_filters(today.replace(day=1), today))
        .scalar()
        or 0
    )

    new_customers_month_count = Customer.query.filter(
        Customer.registration_date >= month_start
    ).count()

    recent_pending_orders = (
        Order.query.filter_by(status="Pending Approval")
        .order_by(Order.event_date.asc())
        .limit(5)
        .all()
    )

    pending_verifications_count = Customer.query.filter(
        Customer.discount_status == "Pending"
    ).count()

    return render_template(
        "admin_dashboard.html",
        orders_today_count=orders_today_count,
        total_sales_month=total_sales_month,
        new_customers_month_count=new_customers_month_count,
        recent_pending_orders=recent_pending_orders,
        pending_verifications_count=pending_verifications_count,
    )


def verify_admin_password(password_attempt):

    if not password_attempt:
        return False

    return current_user.check_password(password_attempt)


@login_required
def admin_logout():
    logout_user()
    session.pop("admin_auth_version", None)
    flash("You have been logged out.", "danger")
    return redirect(url_for("admin_login"))


@login_required
def admin_orders():

    status_filter = request.args.get("status")
    order_query = Order.query.join(Customer).order_by(Order.order_date.desc())

    if status_filter:
        order_query = order_query.filter(Order.status == status_filter)

    orders = order_query.all()

    return render_template(
        "admin_orders.html",
        orders=orders,
        current_filter=status_filter,
        available_riders=[],
        allowed_order_statuses=allowed_order_statuses,
    )


def send_order_email(order, subject, template_name):

    msg = Message(
        subject, recipients=[order.customer.email], sender=current_app.config.get("MAIL_USERNAME")
    )
    msg.html = render_template(template_name, order=order)

    app = current_app._get_current_object()
    Thread(target=send_async_email, args=(app, msg)).start()


def notify_order_update(order):
    templates = {
        "Approved": "email_order_approved.html",
        "Declined": "email_order_declined.html",
        "In Progress": "email_order_in_progress.html",
        "Up for Delivery": "email_order_delivery.html",
        "Completed": "email_order_completed.html",
    }
    try:
        send_order_email(
            order, f"Order #{order.order_id}: {order.status} - Anjet's", templates[order.status]
        )
    except Exception:
        app.logger.exception("Could not queue order notification for order %s", order.order_id)
        flash(
            "Order updated, but the email notification could not be queued. Please contact the customer.",
            "warning",
        )
    else:
        flash(
            f"Order #{order.order_id} updated to {order.status}. Email notification queued.",
            "success",
        )


@login_required
def admin_update_order_status(order_id):
    order = db.get_or_404(Order, order_id)
    try:
        changed = transition_order(
            order, request.form.get("status"), request.form.get("decline_reason")
        )
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "warning")
    except Exception:
        db.session.rollback()
        app.logger.exception("Order status update failed")
        flash("Could not update this order. Please try again.", "danger")
    else:
        if changed:
            notify_order_update(order)
        else:
            flash("No status change submitted.", "info")
    return redirect(url_for("admin_orders"))


@login_required
def admin_delete_order(order_id):
    order = Order.query.get_or_404(order_id)

    try:
        OrderItem.query.filter_by(order_id=order.order_id).delete()

        db.session.delete(order)
        db.session.commit()
        flash(f"Order #{order.order_id} has been deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting order: {e}", "danger")

    current_filter = request.args.get("status")
    if current_filter:
        return redirect(url_for("admin_orders", status=current_filter))
    return redirect(url_for("admin_orders"))


@login_required
def admin_export_orders_json():
    try:
        orders = (
            Order.query.options(
                db.joinedload(Order.customer),
                db.joinedload(Order.items).joinedload(OrderItem.product),
                db.joinedload(Order.items).joinedload(OrderItem.variant),
            )
            .order_by(Order.order_date.desc())
            .all()
        )

        all_orders_data = []

        for order in orders:
            order_data = {
                "order_id": order.order_id,
                "customer_name": order.customer.name,
                "customer_email": order.customer.email,
                "order_date": order.order_date.isoformat(),
                "total_amount": float(order.total_amount),
                "discount_amount": float(order.discount_amount),
                "final_amount": float(order.final_amount),
                "status": order.status,
                "items": [],
            }

            for item in order.items:
                item_data = {
                    "product_name": item.product_name,
                    "variant": item.variant_name,
                    "quantity": item.quantity,
                    "price_per_item": float(item.price_per_item),
                }
                order_data["items"].append(item_data)

            all_orders_data.append(order_data)

        response = make_response(jsonify(all_orders_data))
        response.headers["Content-Disposition"] = "attachment; filename=orders_export.json"
        response.headers["Content-type"] = "application/json"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the JSON: {e}", "danger")
        return redirect(url_for("admin_orders"))


@login_required
def admin_categories():
    search_query = request.args.get("search")

    add_form = CategoryForm()
    edit_form = CategoryForm()

    category_query = Category.query

    if search_query:
        category_query = category_query.filter(Category.name.ilike(f"%{search_query}%"))

    categories = category_query.order_by(Category.name.asc()).all()

    return render_template(
        "admin_categories.html",
        add_form=add_form,
        edit_form=edit_form,
        categories=categories,
        search_query=search_query,
    )


@login_required
def admin_toggle_product_status(product_id):
    product = db.get_or_404(Product, product_id)

    product.is_active = not product.is_active

    try:
        db.session.commit()
        if product.is_active:
            flash(f"Product '{product.name}' has been Activated.", "success")
        else:
            flash(f"Product '{product.name}' has been Deactivated.", "info")
    except Exception as e:
        db.session.rollback()
        flash(f"Error changing product status: {e}", "danger")

    return redirect(url_for("admin_products"))


@login_required
def admin_edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    edit_form = CategoryForm()

    if edit_form.validate_on_submit():
        category.name = edit_form.name.data
        category.description = edit_form.description.data

        try:
            db.session.commit()
            flash(f"Category '{category.name}' updated successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating category: {e}", "danger")
    else:
        flash("Error: Could not update category. Please check form.", "danger")

    return redirect(url_for("admin_categories") + "#existing-categories-card")


@login_required
def admin_toggle_category_status(category_id):
    category = Category.query.get_or_404(category_id)

    category.is_active = not category.is_active

    try:
        db.session.commit()
        if category.is_active:
            flash(f"Category '{category.name}' has been Activated.", "success")
        else:
            flash(f"Category '{category.name}' has been Deactivated.", "info")
    except Exception as e:
        db.session.rollback()
        flash(f"Error changing category status: {e}", "danger")

    return redirect(url_for("admin_categories") + "#existing-categories-card")


@login_required
def admin_products():
    search_query = request.args.get("search")
    selected_category_id = request.args.get("category", type=int)

    all_categories = Category.query.order_by(Category.name.asc()).all()

    product_query = Product.query

    if selected_category_id:
        product_query = product_query.filter_by(category_id=selected_category_id)

    if search_query:
        product_query = product_query.filter(Product.name.ilike(f"%{search_query}%"))

    products = product_query.order_by(Product.name.asc()).all()

    return render_template(
        "admin_products.html",
        products=products,
        all_categories=all_categories,
        selected_category_id=selected_category_id,
        search_query=search_query,
    )


@login_required
def admin_add_product():
    form = ProductForm()
    form.category.choices = get_category_choices()

    if form.validate_on_submit():
        image_filename = "default.jpg"
        if form.image.data:
            try:
                # 1. Save the picture using the fixed helper
                image_filename = save_picture(form.image.data)
            except Exception as e:
                flash(f"Error uploading image: {e}", "danger")
                return redirect(url_for("admin_add_product"))

        new_product = Product(
            category_id=form.category.data,
            name=form.name.data,
            description=form.description.data,
            has_variants=form.has_variants.data,
            # 2. Assign the final filename
            image_file=image_filename,
        )
        db.session.add(new_product)

        # Logic for simple products (without variants)
        if not new_product.has_variants:
            if form.price.data is None:
                flash("Error: A simple product (no variants) must have a price.", "danger")
                return redirect(url_for("admin_add_product"))

            simple_variant = ProductVariant(
                product=new_product, size_name="Regular", price=form.price.data
            )
            db.session.add(simple_variant)

        try:
            db.session.commit()
            flash(f"Product '{new_product.name}' added successfully.", "success")
            return redirect(url_for("admin_products"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding product: {e}", "danger")

    return render_template(
        "admin_product_form.html",
        form=form,
        form_title="Add New Product",
        action_url=url_for("admin_add_product"),
    )


@login_required
def admin_edit_product(product_id):
    product = db.get_or_404(Product, product_id)

    form = ProductForm(obj=product)

    form.category.choices = get_category_choices()

    if request.method == "GET":
        form.category.data = product.category_id

        if not product.has_variants and product.variants:
            simple_variant = ProductVariant.query.filter_by(
                product_id=product.product_id, size_name="Regular"
            ).first()
            if simple_variant:
                form.price.data = simple_variant.price

    if form.validate_on_submit():
        if form.image.data:
            try:
                image_filename = save_picture(form.image.data)
                product.image_file = image_filename
            except Exception as e:
                flash(f"Error uploading image: {e}", "danger")
                return redirect(url_for("admin_edit_product", product_id=product_id))

        product.category_id = form.category.data
        product.name = form.name.data
        product.description = form.description.data
        product.has_variants = form.has_variants.data

        if not product.has_variants:
            if form.price.data is None:
                flash("Error: A simple product (no variants) must have a price.", "danger")
                return redirect(url_for("admin_edit_product", product_id=product_id))

            simple_variant = ProductVariant.query.filter_by(
                product_id=product.product_id, size_name="Regular"
            ).first()

            if simple_variant:
                simple_variant.price = form.price.data
            else:
                simple_variant = ProductVariant(
                    product=product, size_name="Regular", price=form.price.data
                )
                db.session.add(simple_variant)

        try:
            db.session.commit()
            flash(f"Product '{product.name}' updated successfully.", "success")
            return redirect(url_for("admin_products"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating product: {e}", "danger")

    return render_template(
        "admin_product_form.html",
        form=form,
        form_title=f"Edit Product: {product.name}",
        action_url=url_for("admin_edit_product", product_id=product_id),
    )


@login_required
def admin_delete_product(product_id):
    # 1. Security Check: Verify Password
    password_attempt = request.form.get("admin_confirm_password")
    if not verify_admin_password(password_attempt):
        flash("Incorrect password. Action cancelled.", "danger")
        return redirect(url_for("admin_products"))

    product = db.get_or_404(Product, product_id)

    # 2. Dependency Check: Is it in any order history? (Retains original logic)
    in_orders = OrderItem.query.filter_by(product_id=product_id).first()

    if in_orders:
        # Prevents deletion if product is in order history (Data Integrity for Sales)
        flash(
            f"Cannot delete '{product.name}' because it is part of existing order history. Please Deactivate it instead.",
            "warning",
        )

        if product.is_active:
            product.is_active = False
            db.session.commit()
            flash(f"'{product.name}' has been deactivated automatically.", "info")

        return redirect(url_for("admin_products"))

    # If not in any orders, we can safely hard delete
    try:
        # FIX ADDED: 1. Delete all associated reviews first to satisfy the Foreign Key Constraint
        Review.query.filter_by(product_id=product_id).delete()

        # Existing: 2. Delete variants
        ProductVariant.query.filter_by(product_id=product_id).delete()

        # 3. Delete the product itself
        db.session.delete(product)
        db.session.commit()
        flash(f"Product '{product.name}' deleted permanently.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting product: {e}", "danger")

    return redirect(url_for("admin_products"))


@login_required
def admin_export_products_xml():
    try:
        products = Product.query.options(
            db.joinedload(Product.category), db.joinedload(Product.variants)
        ).all()

        root = ET.Element("Menu")

        for product in products:
            product_elem = ET.SubElement(root, "Product")
            product_elem.set("id", str(product.product_id))

            ET.SubElement(product_elem, "Name").text = product.name
            ET.SubElement(product_elem, "Description").text = product.description
            ET.SubElement(product_elem, "Category").text = product.category.name
            ET.SubElement(product_elem, "HasVariants").text = str(product.has_variants)

            variants_elem = ET.SubElement(product_elem, "Variants")
            for variant in product.variants:
                variant_elem = ET.SubElement(variants_elem, "Variant")
                ET.SubElement(variant_elem, "Size").text = variant.size_name
                ET.SubElement(variant_elem, "Price").text = str(variant.price)

        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="    ")

        response = make_response(xml_str)
        response.headers["Content-Disposition"] = "attachment; filename=menu_export.xml"
        response.headers["Content-type"] = "application/xml"

        return response

    except Exception as e:
        flash(f"An error occurred while generating the XML: {e}", "danger")
        return redirect(url_for("admin_products"))


@login_required
def admin_product_variants(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.has_variants:
        flash(f"'{product.name}' is a simple product and cannot have variants.", "danger")
        return redirect(url_for("admin_products"))

    search_query = request.args.get("search")

    add_form = VariantForm()
    edit_form = VariantForm()

    variant_query = ProductVariant.query.filter_by(product_id=product.product_id)

    if search_query:
        variant_query = variant_query.filter(ProductVariant.size_name.ilike(f"%{search_query}%"))

    variants = variant_query.all()

    return render_template(
        "admin_product_variants.html",
        product=product,
        variants=variants,
        add_form=add_form,
        edit_form=edit_form,
        search_query=search_query,
    )


@login_required
def admin_add_variant(product_id):
    product = db.get_or_404(Product, product_id)
    add_form = VariantForm()

    if add_form.validate_on_submit():
        form_size_name = add_form.size_name.data

        existing_variant = ProductVariant.query.filter_by(
            product_id=product.product_id, size_name=form_size_name
        ).first()

        if existing_variant:
            flash(
                f"Error: A variant named '{form_size_name}' already exists for this product.",
                "danger",
            )
            return redirect(url_for("admin_product_variants", product_id=product.product_id))

        new_variant = ProductVariant(
            product_id=product.product_id,
            size_name=add_form.size_name.data,
            price=add_form.price.data,
        )
        db.session.add(new_variant)
        try:
            db.session.commit()
            flash(f"Variant '{new_variant.size_name}' added.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding variant: {e}", "danger")
    else:
        flash("Error: Could not add variant. Please check form.", "danger")

    return redirect(
        url_for("admin_product_variants", product_id=product.product_id) + "#add-variant-card"
    )


@login_required
def admin_delete_variant(variant_id):
    variant = db.get_or_404(ProductVariant, variant_id)
    product_id = variant.product_id

    if OrderItem.query.filter_by(variant_id=variant_id).first():
        flash(
            "Cannot delete a size used in order history. Keep it or deactivate its product.",
            "warning",
        )
        return redirect(url_for("admin_product_variants", product_id=product_id))

    try:
        db.session.delete(variant)
        db.session.commit()
        flash(f"Variant '{variant.size_name}' deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting variant: {e}", "danger")

    return redirect(
        url_for("admin_product_variants", product_id=product_id) + "#existing-variants-card"
    )


@login_required
def admin_edit_variant(variant_id):
    variant = db.get_or_404(ProductVariant, variant_id)
    product_id = variant.product_id
    edit_form = VariantForm()

    if edit_form.validate_on_submit():
        form_size_name = edit_form.size_name.data

        existing_variant = ProductVariant.query.filter(
            ProductVariant.product_id == product_id,
            ProductVariant.size_name == form_size_name,
            ProductVariant.variant_id != variant_id,
        ).first()

        if existing_variant:
            flash(
                f"Error: Cannot rename. A variant named '{form_size_name}' already exists.",
                "danger",
            )
            return redirect(url_for("admin_product_variants", product_id=product_id))

        variant.size_name = form_size_name
        variant.price = edit_form.price.data

        try:
            db.session.commit()
            flash(f"Variant '{variant.size_name}' updated successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating variant: {e}", "danger")
    else:
        for field, errors in edit_form.errors.items():
            for error in errors:
                field_name = getattr(edit_form, field).label.text
                flash(f"Error in '{field_name}': {error}", "danger")

    return redirect(
        url_for("admin_product_variants", product_id=product_id) + "#existing-variants-card"
    )


@login_required
def admin_import_products_csv():
    file = request.files.get("csv_file")
    if not file or not file.filename or not file.filename.lower().endswith(".csv"):
        flash("Please upload a CSV file.", "danger")
        return redirect(url_for("admin_products"))
    try:
        products_added, variants_added, errors = import_menu_csv(file.stream)
        db.session.commit()
    except (UnicodeDecodeError, csv.Error):
        db.session.rollback()
        flash("The CSV could not be read. Use UTF-8 encoding and valid CSV quoting.", "danger")
    except Exception:
        db.session.rollback()
        app.logger.exception("Menu CSV import failed")
        flash("The import could not be saved. No changes were applied.", "danger")
    else:
        flash(
            f"Imported {products_added} products and {variants_added} sizes.",
            "success" if variants_added else "info",
        )
        if errors:
            summary = " | ".join(errors[:3])
            if len(errors) > 3:
                summary += f" ...and {len(errors) - 3} more errors."
            flash(f"Import completed with issues: {summary}", "warning")
    return redirect(url_for("admin_products"))


@login_required
def admin_vouchers():
    add_form = VoucherForm()
    edit_form = VoucherForm()
    vouchers = Voucher.query.order_by(Voucher.code.asc()).all()

    return render_template(
        "admin_vouchers.html", add_form=add_form, edit_form=edit_form, vouchers=vouchers
    )


@login_required
def admin_add_voucher():
    add_form = VoucherForm()

    if add_form.validate_on_submit():
        form_code = add_form.code.data

        existing_voucher = Voucher.query.filter_by(code=form_code).first()
        if existing_voucher:
            flash(f"Error: A voucher with the code '{form_code}' already exists.", "danger")
            return redirect(url_for("admin_vouchers") + "#add-voucher-card")

        new_voucher = Voucher(
            code=form_code,
            discount_percentage=add_form.discount_percentage.data,
            is_active=add_form.is_active.data,
            max_uses=add_form.max_uses.data,
        )
        db.session.add(new_voucher)
        try:
            db.session.commit()
            flash(f"Voucher '{new_voucher.code}' added successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error adding voucher: {e}", "danger")
    else:
        for field, errors in add_form.errors.items():
            for error in errors:
                field_name = getattr(add_form, field).label.text
                flash(f"Error in '{field_name}': {error}", "danger")

    return redirect(url_for("admin_vouchers") + "#add-voucher-card")


@login_required
def admin_edit_voucher(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)
    edit_form = VoucherForm()

    if edit_form.validate_on_submit():
        form_code = edit_form.code.data

        existing_voucher = Voucher.query.filter(
            Voucher.code == form_code, Voucher.voucher_id != voucher_id
        ).first()
        if existing_voucher:
            flash(f"Error: Cannot rename. The code '{form_code}' is already in use.", "danger")
            return redirect(url_for("admin_vouchers") + "#existing-vouchers-card")

        voucher.code = form_code
        voucher.discount_percentage = edit_form.discount_percentage.data
        voucher.max_uses = edit_form.max_uses.data

        try:
            db.session.commit()
            flash(f"Voucher '{voucher.code}' updated successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating voucher: {e}", "danger")
    else:
        for field, errors in edit_form.errors.items():
            for error in errors:
                field_name = getattr(edit_form, field).label.text
                flash(f"Error in '{field_name}': {error}", "danger")

    return redirect(url_for("admin_vouchers") + "#existing-vouchers-card")


@login_required
def admin_delete_voucher(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)

    try:
        db.session.delete(voucher)
        db.session.commit()
        flash(f"Voucher '{voucher.code}' deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting voucher: {e}", "danger")

    return redirect(url_for("admin_vouchers") + "#existing-vouchers-card")


@login_required
def admin_toggle_voucher_status(voucher_id):
    voucher = Voucher.query.get_or_404(voucher_id)

    voucher.is_active = not voucher.is_active

    try:
        db.session.commit()
        if voucher.is_active:
            flash(f"VVoucher '{voucher.code}' has been Activated.", "success")
        else:
            flash(f"Voucher '{voucher.code}' has been Deactivated.", "info")
    except Exception as e:
        db.session.rollback()
        flash(f"Error changing voucher status: {e}", "danger")

    return redirect(url_for("admin_vouchers") + "#existing-vouchers-card")


@login_required
def admin_customers():
    search_query = request.args.get("search")

    customer_query = Customer.query

    if search_query:
        search_term = f"%{search_query}%"
        customer_query = customer_query.filter(
            db.or_(Customer.name.ilike(search_term), Customer.email.ilike(search_term))
        )

    customers = customer_query.order_by(Customer.registration_date.desc()).all()

    return render_template("admin_customers.html", customers=customers, search_query=search_query)


@login_required
def admin_delete_customer(customer_id):

    password_attempt = request.form.get("admin_confirm_password")
    if not verify_admin_password(password_attempt):
        flash("Incorrect password. Action cancelled.", "danger")
        return redirect(url_for("admin_customers"))

    customer = Customer.query.get_or_404(customer_id)

    order_count = Order.query.filter_by(customer_id=customer_id).count()

    if order_count > 0:
        flash(
            f"Cannot delete customer '{customer.name}' because they have {order_count} orders in the system. Deleting them would corrupt your Sales Reports.",
            "warning",
        )
        return redirect(url_for("admin_customers"))

    try:
        db.session.delete(customer)
        db.session.commit()
        flash(f"Customer '{customer.name}' has been deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting customer: {e}", "danger")

    return redirect(url_for("admin_customers"))


@login_required
def admin_edit_customer_page(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    form = CustomerEditForm(obj=customer)

    return render_template("admin_customer_form.html", form=form, customer=customer)


@login_required
def admin_edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    form = CustomerEditForm()

    if form.validate_on_submit():
        new_email = form.email.data
        if new_email != customer.email:
            existing_customer = Customer.query.filter_by(email=new_email).first()
            if existing_customer:
                flash("That email is already in use by another customer.", "danger")
                return render_template("admin_customer_form.html", form=form, customer=customer)

        customer.name = form.name.data
        customer.contact_number = form.contact_number.data
        customer.email = new_email

        if form.password.data:
            customer.set_password(form.password.data)
            flash(f"Customer '{customer.name}' updated successfully (password changed).", "success")
        else:
            flash(
                f"Customer '{customer.name}' updated successfully (password unchanged).", "success"
            )

        try:
            db.session.commit()
            return redirect(url_for("admin_customers"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating customer: {e}", "danger")

    return render_template("admin_customer_form.html", form=form, customer=customer)


@login_required
def admin_verifications():

    customers_to_verify = (
        Customer.query.filter(Customer.discount_status == "Pending")
        .order_by(Customer.registration_date.desc())
        .all()
    )

    gcash_orders_to_verify = (
        Order.query.filter(
            Order.payment_method == "GCash", Order.payment_status == "Pending Verification"
        )
        .order_by(Order.order_date.asc())
        .all()
    )

    riders_to_verify = []

    return render_template(
        "admin_verifications_hub.html",
        customers=customers_to_verify,
        riders=riders_to_verify,
        gcash_orders=gcash_orders_to_verify,
    )


@login_required
def admin_approve_discount(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    customer.is_verified_discount = True
    customer.discount_status = "Approved"

    try:
        db.session.commit()
        flash(f"Approved discount for {customer.name}.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error approving discount: {e}", "danger")

    return redirect(url_for("admin_verifications"))


def update_gcash_verification(order_id, approved):
    order = db.get_or_404(Order, order_id)
    try:
        verify_gcash_payment(order, approved)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "warning")
    except Exception:
        db.session.rollback()
        app.logger.exception("Payment verification failed")
        flash("Could not update this payment. Please try again.", "danger")
    else:
        notify_order_update(order)
    return redirect(url_for("admin_verifications"))


@login_required
def admin_approve_payment(order_id):
    return update_gcash_verification(order_id, approved=True)


@login_required
def admin_deny_payment(order_id):
    return update_gcash_verification(order_id, approved=False)


@login_required
def admin_deny_discount(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    customer.is_verified_discount = False
    customer.discount_status = "Denied"

    try:
        db.session.commit()
        flash(f"Denied and cleared discount request for {customer.name}.", "info")
    except Exception as e:
        db.session.rollback()
        flash(f"Error denying discount: {e}", "danger")

    return redirect(url_for("admin_verifications"))


@login_required
def admin_sales_reports():
    try:
        report = sales_report(request.args.get("start_date"), request.args.get("end_date"))
    except ValueError as error:
        flash(str(error), "warning")
        return redirect(url_for("admin_sales_reports"))
    return render_template("admin_sales_reports.html", **report)


@login_required
def admin_export_sales_csv():
    try:
        report = sales_report(request.args.get("start_date"), request.args.get("end_date"))
    except ValueError as error:
        flash(str(error), "warning")
        return redirect(url_for("admin_sales_reports"))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Date", "Total Sales (PHP)"])
    for day in report["sales_by_day"]:
        writer.writerow([day.date.isoformat(), f"{day.total_sales:.2f}"])
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=sales_report.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@login_required
def admin_users():

    staff_users = User.query.order_by(User.username.asc()).all()

    riders = []

    return render_template("admin_users.html", staff_users=staff_users, riders=riders)


@login_required
def admin_add_user():
    form = UserAddForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash("That username is already taken. Please choose a different one.", "danger")
            return render_template(
                "admin_user_form.html",
                form=form,
                form_title="Add New Staff User",
                action_url=url_for("admin_add_user"),
            )

        new_user = User(username=form.username.data, role=form.role.data)
        new_user.set_password(form.password.data)

        db.session.add(new_user)
        try:
            db.session.commit()
            flash(f"Staff user '{new_user.username}' created successfully.", "success")
            return redirect(url_for("admin_users"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error creating user: {e}", "danger")

    return render_template(
        "admin_user_form.html",
        form=form,
        form_title="Add New Staff User",
        action_url=url_for("admin_add_user"),
    )


@login_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = UserEditForm(obj=user)

    if form.validate_on_submit():
        new_username = form.username.data
        if new_username != user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user:
                flash("That username is already taken. Please choose a different one.", "danger")
                return render_template(
                    "admin_user_form.html",
                    form=form,
                    form_title=f"Edit User: {user.username}",
                    action_url=url_for("admin_edit_user", user_id=user_id),
                )

        user.username = new_username
        user.role = form.role.data

        if form.password.data:
            user.set_password(form.password.data)
            flash(f"User '{user.username}' updated successfully (password changed).", "success")
        else:
            flash(f"User '{user.username}' updated successfully (password unchanged).", "success")

        try:
            db.session.commit()
            return redirect(url_for("admin_users"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating user: {e}", "danger")

    return render_template(
        "admin_user_form.html",
        form=form,
        form_title=f"Edit User: {user.username}",
        action_url=url_for("admin_edit_user", user_id=user_id),
    )


@login_required
def admin_delete_user(user_id):

    password_attempt = request.form.get("admin_confirm_password")
    if not verify_admin_password(password_attempt):
        flash("Incorrect password. Action cancelled.", "danger")
        return redirect(url_for("admin_users"))

    if user_id == current_user.user_id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_users"))

    user = User.query.get_or_404(user_id)

    try:
        db.session.delete(user)
        db.session.commit()
        flash(f"User '{user.username}' has been deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting user: {e}", "danger")

    return redirect(url_for("admin_users"))


@customer_login_required
def remove_voucher():
    session.pop("voucher_code", None)
    session.pop("discount_percentage", None)
    flash("Voucher removed.", "info")
    return redirect(url_for("client_cart"))


def register_routes(app):
    """Register routes on each application instance."""
    app.add_url_rule("/admin/uploads/<path:filename>", view_func=admin_private_upload)
    app.add_url_rule("/login/google/complete", view_func=google_login_complete)
    app.add_url_rule("/", view_func=client_home)
    app.add_url_rule("/menu", view_func=client_menu)
    app.add_url_rule("/admin/categories/add", view_func=admin_add_category, methods=["POST"])
    app.add_url_rule(
        "/admin/categories/delete/<int:category_id>",
        view_func=admin_delete_category,
        methods=["POST"],
    )
    app.add_url_rule("/my-account/order/<int:order_id>/receipt", view_func=client_view_receipt)
    app.add_url_rule("/admin/login", view_func=admin_login, methods=["GET", "POST"])
    app.add_url_rule("/my-account", view_func=client_my_account)
    app.add_url_rule("/my-account/profile", view_func=client_profile, methods=["GET", "POST"])
    app.add_url_rule("/my-account/orders", view_func=client_orders)
    app.add_url_rule("/my-account/upload-id", view_func=client_upload_id, methods=["POST"])
    app.add_url_rule(
        "/review/product/<int:product_id>", view_func=client_review_product, methods=["GET", "POST"]
    )
    app.add_url_rule("/cart/add", view_func=add_to_cart, methods=["POST"])
    app.add_url_rule("/product_details/<int:product_id>", view_func=product_details)
    app.add_url_rule("/cart", view_func=client_cart)
    app.add_url_rule("/cart/clear", view_func=clear_cart, methods=["POST"])
    app.add_url_rule(
        "/cart/remove/<string:variant_id>", view_func=remove_from_cart, methods=["POST"]
    )
    app.add_url_rule("/cart/update", view_func=update_cart_quantity, methods=["POST"])
    app.add_url_rule("/cart/apply_voucher", view_func=apply_voucher, methods=["POST"])
    app.add_url_rule("/checkout", view_func=client_checkout)
    app.add_url_rule("/checkout/options", view_func=client_checkout_options, methods=["GET"])
    app.add_url_rule("/checkout/save_options", view_func=save_checkout_options, methods=["POST"])
    app.add_url_rule(
        "/checkout/gcash/upload", view_func=client_gcash_upload, methods=["GET", "POST"]
    )
    app.add_url_rule("/checkout/place_order", view_func=place_order, methods=["POST"])
    app.add_url_rule("/account", view_func=client_account_page, methods=["GET"])
    app.add_url_rule("/register", view_func=client_register_page, methods=["GET"])
    app.add_url_rule("/logout", view_func=client_logout, methods=["POST"])
    app.add_url_rule("/register", view_func=client_register, methods=["POST"])
    app.add_url_rule("/login", view_func=client_login, methods=["POST"])
    app.add_url_rule("/forgot-password", view_func=client_forgot_password, methods=["GET", "POST"])
    app.add_url_rule(
        "/reset-password/<token>", view_func=client_reset_token, methods=["GET", "POST"]
    )
    app.add_url_rule("/buffet-builder", view_func=buffet_wizard_start, methods=["GET"])
    app.add_url_rule("/buffet-builder/reco", view_func=buffet_wizard_reco, methods=["POST"])
    app.add_url_rule(
        "/buffet-builder/select/<string:category_name>",
        view_func=buffet_wizard_select,
        methods=["GET", "POST"],
    )
    app.add_url_rule("/buffet-builder/checkout", view_func=buffet_wizard_checkout, methods=["GET"])
    app.add_url_rule("/buffet/commit_package", view_func=buffet_commit_package, methods=["POST"])
    app.add_url_rule(
        "/buffet/remove/<string:variant_id>", view_func=buffet_remove_item, methods=["POST"]
    )
    app.add_url_rule("/buffet/update", view_func=buffet_update_quantity, methods=["POST"])
    app.add_url_rule("/buffet/add_item", view_func=buffet_add_item, methods=["POST"])
    app.add_url_rule(
        "/buffet/remove_item/<string:variant_id>/<string:category_name>",
        view_func=buffet_remove_item_from_package,
        methods=["POST"],
    )
    app.add_url_rule("/buffet/review", view_func=buffet_review_and_add)
    app.add_url_rule("/admin/dashboard", view_func=admin_dashboard)
    app.add_url_rule("/admin/logout", view_func=admin_logout, methods=["POST"])
    app.add_url_rule("/admin/orders", view_func=admin_orders)
    app.add_url_rule(
        "/admin/orders/update_status/<int:order_id>",
        view_func=admin_update_order_status,
        methods=["POST"],
    )
    app.add_url_rule(
        "/admin/orders/delete/<int:order_id>", view_func=admin_delete_order, methods=["POST"]
    )
    app.add_url_rule("/admin/export/orders_json", view_func=admin_export_orders_json)
    app.add_url_rule("/admin/categories", view_func=admin_categories, methods=["GET"])
    app.add_url_rule(
        "/admin/products/toggle/<int:product_id>",
        view_func=admin_toggle_product_status,
        methods=["POST"],
    )
    app.add_url_rule(
        "/admin/categories/edit/<int:category_id>", view_func=admin_edit_category, methods=["POST"]
    )
    app.add_url_rule(
        "/admin/categories/toggle/<int:category_id>",
        view_func=admin_toggle_category_status,
        methods=["POST"],
    )
    app.add_url_rule("/admin/products", view_func=admin_products, methods=["GET"])
    app.add_url_rule("/admin/products/add", view_func=admin_add_product, methods=["GET", "POST"])
    app.add_url_rule(
        "/admin/products/edit/<int:product_id>",
        view_func=admin_edit_product,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/admin/products/delete/<int:product_id>", view_func=admin_delete_product, methods=["POST"]
    )
    app.add_url_rule("/admin/export/products_xml", view_func=admin_export_products_xml)
    app.add_url_rule(
        "/admin/products/<int:product_id>/variants",
        view_func=admin_product_variants,
        methods=["GET"],
    )
    app.add_url_rule(
        "/admin/products/<int:product_id>/variants/add",
        view_func=admin_add_variant,
        methods=["POST"],
    )
    app.add_url_rule(
        "/admin/variants/delete/<int:variant_id>", view_func=admin_delete_variant, methods=["POST"]
    )
    app.add_url_rule(
        "/admin/variants/edit/<int:variant_id>", view_func=admin_edit_variant, methods=["POST"]
    )
    app.add_url_rule(
        "/admin/import/products_csv", view_func=admin_import_products_csv, methods=["POST"]
    )
    app.add_url_rule("/admin/vouchers", view_func=admin_vouchers, methods=["GET"])
    app.add_url_rule("/admin/vouchers/add", view_func=admin_add_voucher, methods=["POST"])
    app.add_url_rule(
        "/admin/vouchers/edit/<int:voucher_id>", view_func=admin_edit_voucher, methods=["POST"]
    )
    app.add_url_rule(
        "/admin/vouchers/delete/<int:voucher_id>", view_func=admin_delete_voucher, methods=["POST"]
    )
    app.add_url_rule(
        "/admin/vouchers/toggle/<int:voucher_id>",
        view_func=admin_toggle_voucher_status,
        methods=["POST"],
    )
    app.add_url_rule("/admin/customers", view_func=admin_customers, methods=["GET"])
    app.add_url_rule(
        "/admin/customers/delete/<int:customer_id>",
        view_func=admin_delete_customer,
        methods=["POST"],
    )
    app.add_url_rule(
        "/admin/customers/edit/<int:customer_id>",
        view_func=admin_edit_customer_page,
        methods=["GET"],
    )
    app.add_url_rule(
        "/admin/customers/edit/<int:customer_id>", view_func=admin_edit_customer, methods=["POST"]
    )
    app.add_url_rule("/admin/verifications", view_func=admin_verifications)
    app.add_url_rule(
        "/admin/approve_discount/<int:customer_id>",
        view_func=admin_approve_discount,
        methods=["POST"],
    )
    app.add_url_rule(
        "/admin/approve_payment/<int:order_id>", view_func=admin_approve_payment, methods=["POST"]
    )
    app.add_url_rule(
        "/admin/deny_payment/<int:order_id>", view_func=admin_deny_payment, methods=["POST"]
    )
    app.add_url_rule(
        "/admin/deny_discount/<int:customer_id>", view_func=admin_deny_discount, methods=["POST"]
    )
    app.add_url_rule("/admin/sales_reports", view_func=admin_sales_reports)
    app.add_url_rule("/admin/export/sales_csv", view_func=admin_export_sales_csv)
    app.add_url_rule("/admin/users", view_func=admin_users, methods=["GET"])
    app.add_url_rule("/admin/users/add", view_func=admin_add_user, methods=["GET", "POST"])
    app.add_url_rule(
        "/admin/users/edit/<int:user_id>", view_func=admin_edit_user, methods=["GET", "POST"]
    )
    app.add_url_rule(
        "/admin/users/delete/<int:user_id>", view_func=admin_delete_user, methods=["POST"]
    )
    app.add_url_rule("/cart/remove_voucher", view_func=remove_voucher, methods=["POST"])
