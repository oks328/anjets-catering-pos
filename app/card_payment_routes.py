"""
Credit/Debit Card Payment Routes
Add this import to routes.py: from app.card_payment_routes import *
"""
from flask import render_template, redirect, url_for, flash, request, session
from app import db
from app.models import Customer, Order
from app.forms import CreditCardPaymentForm
from functools import wraps

# Import the decorator from routes
def customer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'customer_id' not in session:
            flash("You must be logged in to view that page.", 'danger')
            return redirect(url_for('client_account_page'))
        return f(*args, **kwargs)
    return decorated_function

def get_card_type(card_number):
    """Detect card type from card number"""
    if card_number.startswith('4'):
        return 'Visa'
    elif card_number.startswith(('51', '52', '53', '54', '55')):
        return 'Mastercard'
    elif card_number.startswith(('34', '37')):
        return 'American Express'
    elif card_number.startswith('6011') or card_number.startswith(('644', '645', '646', '647', '648', '649', '65')):
        return 'Discover'
    else:
        return 'Unknown'

def register_card_payment_routes(app):
    """Register card payment routes with the Flask app"""
    
    @app.route('/checkout/card/payment', methods=['GET', 'POST'])
    @customer_login_required
    def client_card_payment():
        """Handle credit/debit card payment form"""
        if session.get('payment_method') != 'Credit/Debit Card':
            flash("Invalid checkout step.", 'danger')
            return redirect(url_for('client_checkout_options'))
            
        final_total = session.get('final_total', 0.0)
        if final_total <= 0:
            flash("Final total missing. Please restart checkout.", 'danger')
            return redirect(url_for('client_checkout_options'))

        form = CreditCardPaymentForm()
        
        if form.validate_on_submit():
            # Extract card info
            card_number = ''.join(filter(str.isdigit, form.card_number.data))
            
            # Determine card type
            card_type = get_card_type(card_number)
            
            # Store only last 4 digits and card type
            session['card_last_four'] = card_number[-4:]
            session['card_type'] = card_type
            session['card_holder_name'] = form.card_holder_name.data
            
            flash("Card validated successfully. Proceeding to order placement.", 'success')
            return redirect(url_for('client_checkout'))

        return render_template(
            'client_card_payment.html',
            form=form,
            final_total=final_total
        )
