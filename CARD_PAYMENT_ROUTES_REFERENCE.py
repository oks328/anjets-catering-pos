# Credit/Debit Card Payment Routes and Helper Functions
# Add these to app/routes.py

# 1. Add to imports (line 25):
# from app.forms import RequestResetForm, ResetPasswordForm, GCashPaymentForm, CreditCardPaymentForm

# 2. Add helper function (after save_payment_receipt function or near other helper functions):

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

# 3. Update save_checkout_options route (around line 910, after GCash handling):
# Add this elif block after the "if payment_method == 'GCash':" block:

    elif payment_method == 'Credit/Debit Card':
        # Calculate totals for card payment
        cart_items = []
        for item_id, item_data in cart_session.items():
            cart_items.append({
                'price': float(item_data['price']),
                'quantity': int(item_data['quantity'])
            })
        customer = Customer.query.get(session['customer_id'])
        delivery_fee = session.get('delivery_fee', 0.0)
        voucher_code = session.get('voucher_code')
        voucher_percent = session.get('discount_percentage', 0.0)
        totals = calculate_order_totals(cart_items, customer, delivery_fee, voucher_code, voucher_percent)
        session['final_total'] = totals['final_total']
        
        # Redirect to card payment form
        return redirect(url_for('client_card_payment'))

# 4. Add new route (after client_gcash_upload route, around line 967):

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

# 5. Update place_order route (around line 1004):
# Add this elif block after the "if payment_method == 'GCash':" block:

    elif payment_method == 'Credit/Debit Card':
        initial_order_status = "Pending Approval"
        initial_payment_status = "Card Payment Confirmed"
        
        # Get card info from session
        card_last_four = session.get('card_last_four')
        card_type = session.get('card_type')
        
        if not card_last_four:
            return jsonify({'status': 'error', 'message': "Card information missing. Please restart the payment process."}), 400

# 6. Update Order creation (around line 1038):
# Add these fields to the Order constructor:
#     card_last_four=session.get('card_last_four'),
#     card_type=session.get('card_type')

# 7. Update session cleanup (around line 1075):
# Add to keys_to_clear list:
#     'card_last_four', 'card_type', 'card_holder_name'
