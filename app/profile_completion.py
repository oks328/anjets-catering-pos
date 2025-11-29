"""
Complete Profile Route for Google OAuth Users
Add this to app/__init__.py after importing routes:
    from app.profile_completion import register_profile_routes
    register_profile_routes(app)
"""
from flask import render_template, redirect, url_for, flash, request, session
from app import db
from app.models import Customer
from app.forms import CompleteProfileForm
from functools import wraps

def customer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'customer_id' not in session:
            flash("You must be logged in to view that page.", 'danger')
            return redirect(url_for('client_account_page'))
        return f(*args, **kwargs)
    return decorated_function

def register_profile_routes(app):
    """Register profile completion routes with the Flask app"""
    
    @app.route('/complete_profile', methods=['GET', 'POST'])
    @customer_login_required
    def complete_profile():
        """Complete profile for Google OAuth users"""
        customer = Customer.query.get_or_404(session['customer_id'])
        
        # If profile is already complete, redirect to home
        if customer.contact_number and customer.address and customer.birthdate:
            return redirect(url_for('client_home'))

        form = CompleteProfileForm()

        if form.validate_on_submit():
            customer.contact_number = form.contact_number.data
            customer.address = form.address.data
            customer.landmark = form.landmark.data
            customer.birthdate = form.birthdate.data
            
            try:
                db.session.commit()
                flash('Profile completed successfully! Welcome!', 'success')
                return redirect(url_for('client_home'))
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating profile: {e}", 'danger')

        return render_template('complete_profile.html', form=form)
