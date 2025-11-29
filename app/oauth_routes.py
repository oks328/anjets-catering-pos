# Custom Google OAuth routes
# This file contains the custom OAuth implementation to replace Flask-Dance

from flask import current_app as app, redirect, url_for, flash, request, session
from app import db
from app.models import Customer

@app.route('/auth/google')
def google_login():
    """Initiate Google OAuth flow"""
    from google_auth_oauthlib.flow import Flow
    
    # Determine the correct redirect URI based on the request
    # This ensures we match whatever domain the user is accessing from
    if 'localhost' in request.host:
        redirect_uri = "http://localhost:5000/auth/google/callback"
    else:
        redirect_uri = "http://127.0.0.1:5000/auth/google/callback"
    
    print(f"DEBUG: Request Host: {request.host}")
    print(f"DEBUG: Selected Redirect URI: {redirect_uri}")
    
    # Create flow instance
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": app.config.get('GOOGLE_OAUTH_CLIENT_ID'),
                "client_secret": app.config.get('GOOGLE_OAUTH_CLIENT_SECRET'),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        },
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
    )
    
    # Use the determined redirect URI
    flow.redirect_uri = redirect_uri
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='select_account'  # Force account selection every time
    )
    
    print(f"DEBUG: Authorization URL generated with redirect_uri: {redirect_uri}")
    
    # Store state AND redirect_uri in session for CSRF protection and consistency
    session['oauth_state'] = state
    session['oauth_redirect_uri'] = redirect_uri
    
    return redirect(authorization_url)

@app.route('/auth/google/callback')
def google_callback():
    """Handle Google OAuth callback"""
    from google_auth_oauthlib.flow import Flow
    import requests
    
    # Verify state to prevent CSRF
    state = session.get('oauth_state')
    print(f"DEBUG: Callback received. State: {state}, Request State: {request.args.get('state')}")
    
    if not state or state != request.args.get('state'):
        flash("Invalid state parameter. Please try again.", 'danger')
        return redirect(url_for('client_account_page'))
    
    # Get the redirect URI that was used in the initial request
    redirect_uri = session.get('oauth_redirect_uri', "http://127.0.0.1:5000/auth/google/callback")
    print(f"DEBUG: Callback using redirect_uri from session: {redirect_uri}")
    
    try:
        # Create flow instance with the SAME redirect_uri as the initial request
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": app.config.get('GOOGLE_OAUTH_CLIENT_ID'),
                    "client_secret": app.config.get('GOOGLE_OAUTH_CLIENT_SECRET'),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri]
                }
            },
            scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'],
            state=state
        )
        
        # Use the same redirect URI
        flow.redirect_uri = redirect_uri
        
        # Exchange authorization code for tokens
        flow.fetch_token(authorization_response=request.url)
        
        # Get user info from Google
        credentials = flow.credentials
        user_info_response = requests.get(
            'https://www.googleapis.com/oauth2/v1/userinfo',
            headers={'Authorization': f'Bearer {credentials.token}'}
        )
        
        if not user_info_response.ok:
            flash("Failed to fetch user data from Google.", 'danger')
            return redirect(url_for('client_account_page'))
        
        google_data = user_info_response.json()
        google_id = google_data.get('id')
        email = google_data.get('email', '').lower()
        name = google_data.get('name', 'Customer')
        
        if not google_id or not email:
            flash("Google did not provide a valid ID or email. Cannot log you in.", 'danger')
            return redirect(url_for('client_account_page'))
        
        # 1. Try to find user by Google ID (Best case: already linked)
        customer = Customer.query.filter_by(google_id=google_id).first()
        
        if customer is None:
            # 2. Try to find user by email (Existing account needs linking)
            customer = Customer.query.filter_by(email=email).first()
            
            if customer is None:
                # 3. Create a new account
                new_customer = Customer(
                    name=name,
                    email=email,
                    google_id=google_id,
                    password_hash="google_oauth_user_placeholder" 
                )
                db.session.add(new_customer)
                db.session.commit()
                customer = new_customer
                flash(f"Welcome, {customer.name}! Account created via Google.", 'success')
            else:
                # 4. Link existing account to Google ID
                customer.google_id = google_id
                db.session.commit()
                flash(f"Welcome back, {customer.name}! Your account is now linked to Google.", 'success')
        
        # Log the customer in
        session['customer_id'] = customer.customer_id
        session['customer_name'] = customer.name
        
        # Clear OAuth state and redirect URI
        session.pop('oauth_state', None)
        session.pop('oauth_redirect_uri', None)
        
        # Check if profile is complete
        if not customer.contact_number or not customer.address or not customer.birthdate:
             flash("Please complete your profile to continue.", 'info')
             return redirect(url_for('complete_profile'))

        return redirect(url_for('client_home', welcome='google'))
        
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred during Google login: {str(e)}", 'danger')
        return redirect(url_for('client_account_page'))
