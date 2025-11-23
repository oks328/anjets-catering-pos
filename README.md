# Anjet's Catering - POS & Online Ordering System

A complete web-based catering management system designed for "Made-to-Order" food businesses. It features a sophisticated Buffet Builder, event scheduling logic, and a full Admin approval workflow.

## 🚀 Key Features

### 🍽️ Client-Side (Customer)
* **Buffet Builder Wizard:**
    * Step-by-step wizard for building custom catering packages.
    * **Smart Logic:** "Shared Mains" quota system (e.g., mix and match Pork/Beef/Chicken to reach the required total).
    * **Real-Time UI:** Floating total price badge and visual progress bar.
    * **Smart Recommendations:** Suggests quantities based on guest count.
* **Event-Based Ordering:**
    * Customers select an **Event Date & Time** instead of immediate delivery.
    * **Dynamic Lead Time:** Enforces a 3-day minimum for standard orders and a 7-day minimum for buffet packages.
* **Order Tracking:**
    * "My Orders" dashboard showing real-time status (Pending, Approved, Kitchen, Out for Delivery).
    * Visual badges for status updates.
    * View decline reasons if an order is rejected.
* **Official Receipts:** Generate and print digital receipts for approved/completed orders.

### 🛠️ Admin-Side (Management)
* **Approval Workflow:**
    * New orders arrive as **"Pending Approval"**.
    * Admins can **Approve** (confirms schedule) or **Decline** (requires a reason text).
    * Status tracking: Approved $\rightarrow$ In Progress (Kitchen) $\rightarrow$ Up for Delivery $\rightarrow$ Completed.
* **Dashboard:** Daily overview of new requests, confirmed sales, and pending verifications.
* **Menu Management:**
    * Manage Categories and Products.
    * Support for **Product Variants** (e.g., Small Bilao vs. Family Tray).
    * **CSV Import:** Bulk upload menu items with auto-category matching.
* **Sales Reports:** Filterable sales data exportable to CSV.

### 📧 Automated Email Notifications
The system sends transactional emails using **Flask-Mail** for key events:
* **Order Confirmed:** Sent when Admin approves the request.
* **Order Declined:** Sent with the specific reason for rejection.
* **Out for Delivery:** Sent when the rider leaves.
* **Order Completed:** Sent with a link to the final receipt.

---

## ⚙️ Installation & Setup

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/yourusername/anjets-catering-pos.git](https://github.com/yourusername/anjets-catering-pos.git)
    cd anjets-catering-pos
    ```

2.  **Create a Virtual Environment**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**
    Create a `.env` file in the root directory:
    ```ini
    FLASK_APP=run.py
    FLASK_ENV=development
    SECRET_KEY=your_secret_key_here
    DATABASE_URL=sqlite:///site.db
    
    # Email Settings (Required for Notifications)
    MAIL_USERNAME=your_email@gmail.com
    MAIL_PASSWORD=your_app_password
    ```

5.  **Initialize the Database**
    If starting fresh, delete any existing `site.db` and let Flask recreate it on first run, or run:
    ```bash
    flask shell
    >>> from app import db
    >>> db.create_all()
    >>> exit()
    ```

6.  **Run the Application**
    ```bash
    python run.py
    ```
    Access the site at `http://127.0.0.1:5000`.

---

## 📖 Usage Guide

### 1. Setting Up the Menu (First Run)
* Log in as an **Admin**.
* Go to **Categories** and create the required standard categories: `Pork`, `Beef`, `Chicken`, `Seafood`, `Vegetables`, `Pasta & Noodles`, `Dessert`.
* Go to **Products** and click "Import from CSV". Upload your `menu_import.csv` to populate the database.

### 2. The Buffet Logic
* The system sorts categories logically: Mains $\rightarrow$ Carbs $\rightarrow$ Sides $\rightarrow$ Dessert.
* **Shared Mains:** The wizard sums up all selected items from Pork, Beef, Chicken, and Seafood. The user must meet the *total* required count (e.g., 10 trays for 100 pax) but can distribute them however they like (e.g., 5 Pork, 5 Chicken).

### 3. Order Lifecycle
1.  **Customer** places order $\rightarrow$ Status: `Pending Approval`.
2.  **Admin** reviews date/capacity $\rightarrow$ Clicks `Approve`.
    * *Email sent to Customer.*
3.  **Kitchen** starts cooking $\rightarrow$ Admin sets status to `In Progress`.
4.  **Delivery** starts $\rightarrow$ Admin sets status to `Up for Delivery`.
    * *Email sent to Customer.*
5.  **Transaction done** $\rightarrow$ Admin sets status to `Completed`.
    * *Receipt becomes available to Customer.*

---

## 📦 Tech Stack
* **Backend:** Python, Flask
* **Database:** SQLAlchemy (SQLite for dev)
* **Frontend:** HTML5, CSS3, JavaScript (Vanilla)
* **Email:** Flask-Mail