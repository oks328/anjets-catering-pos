import os
from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt       
from flask_login import LoginManager
from flask_mail import Mail

# Allow insecure HTTP for OAuth in development (REMOVE IN PRODUCTION!)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

db = SQLAlchemy()

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'admin_login'
login_manager.login_message_category = 'info'

mail = Mail()

def create_app(config_class=Config):
    """Create and configure the Flask app."""
    
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    with app.app_context():
        from . import routes
        from . import models
        from . import oauth_routes  # Import custom OAuth routes

        @login_manager.user_loader
        def load_user(user_id):
            return models.User.query.get(int(user_id))
        
        @app.shell_context_processor
        def make_shell_context():
            return {
                'db': db,
                'User': models.User,
                'Category': models.Category,
                'Product': models.Product,
                'ProductVariant': models.ProductVariant,
                'Voucher': models.Voucher,
                'Customer': models.Customer,
                'Order': models.Order,
                'OrderItem': models.OrderItem
            }
        
    return app