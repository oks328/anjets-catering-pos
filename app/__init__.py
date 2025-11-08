from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt       
from flask_login import LoginManager  

# Initialize our database (we'll uncomment this later)
db = SQLAlchemy()

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'admin_login' # <-- This is the function name of our future login route
login_manager.login_message_category = 'info' # <-- (Optional) For flashing messages

def create_app(config_class=Config):
    """Create and configure the Flask app."""
    
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions (like the database)
    db.init_app(app)
    bcrypt.init_app(app)         # <-- Add this
    login_manager.init_app(app)  # <-- Add this

    # Register our 'routes' (the URLs)
    with app.app_context():
        from . import routes
        from . import models

        @login_manager.user_loader
        def load_user(user_id):
            return models.User.query.get(int(user_id))
        
        return app