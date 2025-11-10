from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, BooleanField, DecimalField, SelectField
from wtforms.validators import DataRequired, Length, Optional, EqualTo, ValidationError, NumberRange, Email
from flask_wtf.file import FileField, FileAllowed, FileSize
from app.models import Customer

def password_complexity(form, field):
    """
    Custom validator to ensure password contains letters and numbers.
    """
    password = field.data
    if password: # Only run if password is not empty
        has_letter = any(c.isalpha() for c in password)
        has_number = any(c.isdigit() for c in password)
        
        if not (has_letter and has_number):
            raise ValidationError('Password must contain a combination of letters and numbers.')
        
def email_exists(form, field):

    customer = Customer.query.filter_by(email=field.data).first()
    if customer:
        raise ValidationError('That email address is already in use. Please log in.')
    
class AdminLoginForm(FlaskForm):
    """
    Form for admin users to log in.
    """
    username = StringField(
        'Username',
        validators=[DataRequired(), Length(min=3, max=100)]
    )
    password = PasswordField(
        'Password',
        # This is the corrected 'validators=' list
        validators=[DataRequired(), password_complexity] 
    )
    submit = SubmitField('Log In')


class CategoryForm(FlaskForm):
    """
    Form for admin to add or edit a category.
    """
    name = StringField(
        'Category Name',
        validators=[DataRequired(), Length(min=3, max=100)]
    )
    description = TextAreaField(
        'Description (Optional)',
        validators=[Length(max=500)]
    )
    submit = SubmitField('Save Category')

    # ... CategoryForm is above ...

class ProductForm(FlaskForm):
    """
    Form for admin to add or edit a product.
    """
    # We'll populate 'choices' in our route
    category = SelectField(
        'Category',
        coerce=int,
        validators=[DataRequired()]
    )
    name = StringField(
        'Product Name',
        validators=[DataRequired(), Length(min=3, max=255)]
    )
    description = TextAreaField(
        'Description (Optional)'
    )
    has_variants = BooleanField(
        'This product has multiple sizes/prices (e.g., S, M, L)'
    )

    # This price is for SIMPLE products (when has_variants is False)
    # 'Optional()' means it's not required
    price = DecimalField(
        'Price (if no variants)',
        places=2,
        validators=[Optional()]
    )

    image = FileField(
        'Product Image',
        validators=[
            FileAllowed(['jpg', 'png', 'jpeg', 'webp'], 'Images only! (jpg, png, jpeg, webp)'),
            FileSize(max_size=2 * 1024 * 1024)  # 2MB max size
        ]
    )
    submit = SubmitField('Save Product')

class VariantForm(FlaskForm):
    """
    Form for adding/editing a product variant.
    """
    size_name = StringField(
        'Size / Name',
        validators=[DataRequired(), Length(min=1, max=50)],
        description="e.g., 'Small', 'Medium', '100 pcs'"
    )
    price = DecimalField(
        'Price',
        places=2,
        validators=[DataRequired()]
        
    )
    submit = SubmitField('Save Variant')

class VoucherForm(FlaskForm):
    """
    Form for adding/editing a voucher.
    """
    code = StringField(
        'Voucher Code',
        validators=[DataRequired(), Length(min=3, max=50)],
        description="e.g., 'Kamag-anak' or 'SALE10'"
    )

class VoucherForm(FlaskForm):
    """
    Form for adding/editing a voucher.
    """
    code = StringField(
        'Voucher Code',
        validators=[DataRequired(), Length(min=3, max=50)],
        description="e.g., 'Kamag-anak' or 'SALE10'"
    )
    discount_percentage = DecimalField(
        'Discount Percentage',
        places=2,
        validators=[
            DataRequired(),
            NumberRange(min=0.01, max=20.0, message="Discount must be between 0.01%% and 20%%.")
        ],
        description="e.g., Enter 10 for 10%. Max is 20%."
    )
    # This will be a checkbox
    is_active = BooleanField(
        'Active',
        default=True
    )
    submit = SubmitField('Save Voucher')
class UserAddForm(FlaskForm):
    """
    Form for admin to add a new staff user.
    Password is required.
    """
    username = StringField(
        'Username',
        validators=[DataRequired(), Length(min=4, max=100)]
    )
    # We'll add a dropdown for role, e.g., 'Admin' or 'Staff'
    role = SelectField(
        'Account Type (Role)',
        choices=[('Admin', 'Admin'), ('Staff', 'Staff')],
        validators=[DataRequired()]
    )
    password = PasswordField(
        'Password',
        validators=[DataRequired(), Length(min=6), password_complexity] # <-- Add it here too
    )
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match.')]
    )
    submit = SubmitField('Create User')


class UserEditForm(FlaskForm):
    """
    Form for admin to edit an existing staff user.
    Password is optional (only if they want to change it).
    """
    username = StringField(
        'Username',
        validators=[DataRequired(), Length(min=4, max=100)]
    )
    role = SelectField(
        'Account Type (Role)',
        choices=[('Admin', 'Admin'), ('Staff', 'Staff')],
        validators=[DataRequired()]
    )
    # 'Optional()' validator allows this field to be blank
    password = PasswordField(
        'New Password (Optional)',
        validators=[Optional(), Length(min=8), password_complexity] # <-- ADDED HERE
    )
    confirm_password = PasswordField(
        'Confirm New Password',
        validators=[EqualTo('password', message='Passwords must match.')]
    )
    submit = SubmitField('Update User')

    # ... UserEditForm is above ...

class CustomerRegisterForm(FlaskForm):
    """
    Form for new customers to register.
    """
    name = StringField(
        'Full Name',
        validators=[DataRequired(), Length(min=3, max=255)]
    )
    contact_number = StringField(
        'Contact Number',
        validators=[DataRequired(), Length(min=7, max=20)]
    )
    email = StringField(
        'Email Address',
        validators=[DataRequired(), Email(), email_exists] # email_exists checks for duplicates
    )
    password = PasswordField(
        'Password',
        validators=[DataRequired(), Length(min=6), password_complexity]
    )
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match.')]
    )
    submit = SubmitField('Create Account')


class CustomerLoginForm(FlaskForm):
    """
    Form for existing customers to log in.
    """
    email = StringField(
        'Email Address',
        validators=[DataRequired(), Email()]
    )
    password = PasswordField(
        'Password',
        validators=[DataRequired()]
    )
    submit = SubmitField('Log In')