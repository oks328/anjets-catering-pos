from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt       
from flask_login import LoginManager
from flask_mail import Mail  # <-- 1. IMPORT MAIL
from flask_migrate import Migrate

# Initialize our database
db = SQLAlchemy()

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'admin_login'
login_manager.login_message_category = 'info'

migrate = Migrate()
mail = Mail() # <-- 2. CREATE MAIL INSTANCE

def create_app(config_class=Config):
    """Create and configure the Flask app."""
    
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions (like the database)
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app) # <-- 3. INITIALIZE MAIL
    migrate.init_app(app, db)

    # Register our 'routes' (the URLs)
    with app.app_context():
        from . import routes
        from . import models

        @login_manager.user_loader
        def load_user(user_id):
            return models.User.query.get(int(user_id))
        
        # This registers your models with flask shell
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
        
    return app # <-- IMPORTANT: Return app OUTSIDE the 'with' block