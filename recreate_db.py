"""
Script to recreate the database tables
Run this with: python recreate_db.py
"""
from app import create_app, db

app = create_app()

with app.app_context():
    print("Creating all database tables...")
    db.create_all()
    print("[SUCCESS] Database tables created successfully!")
    print("\nTables created:")
    print("- Categories")
    print("- Products")
    print("- Product_Variants")
    print("- Customers")
    print("- Users")
    print("- Orders (with card_last_four and card_type fields)")
    print("- Order_Items")
    print("- Vouchers")
    print("- Reviews")
    print("\nYou can now run the application!")

