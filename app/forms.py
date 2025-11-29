from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, BooleanField, DecimalField, SelectField, DateField, IntegerField
from wtforms.validators import DataRequired, Length, Optional, EqualTo, ValidationError, NumberRange, Email, Regexp
from flask_wtf.file import FileField, FileAllowed, FileSize
from app.models import Customer
from datetime import date, timedelta


def password_complexity(form, field):
    
    password = field.data
    if password: 
        if len(password) < 12: 
            raise ValidationError('Password must be at least 12 characters long.')

        has_lower = any(c.islower() for c in password)
        has_upper = any(c.isupper() for c in password)
        has_number = any(c.isdigit() for c in password)
        has_symbol = any(not c.isalnum() for c in password) 
        
        if not (has_lower and has_upper and has_number and has_symbol):
            raise ValidationError(
                'Password must contain at least one lowercase letter, one uppercase letter, one digit, and one symbol.'
            )


def validate_age_and_future_date(form, field): 
    birthdate = field.data
    
    if birthdate:
        today = date.today()
        
        if birthdate > today:
            raise ValidationError('Birthdate cannot be in the future.')
            
        required_age_date = today.replace(year=today.year - 12)
        
        if birthdate > required_age_date:
            raise ValidationError('You must be at least 12 years old to create an account.')


def email_exists(form, field):

    customer = Customer.query.filter_by(email=field.data).first()
    if customer:
        raise ValidationError('That email address is already in use. Please log in.')
    
    

class AdminLoginForm(FlaskForm):
    
    username = StringField(
        'Username',
        validators=[DataRequired()]
    )
    password = PasswordField(
        'Password',
        validators=[DataRequired(), password_complexity] 
    )
    submit = SubmitField('Log In')


class CategoryForm(FlaskForm):
    
    name = StringField(
        'Category Name',
        validators=[DataRequired(), Length(min=3, max=100)]
    )
    description = TextAreaField(
        'Description (Optional)',
        validators=[Length(max=500)]
    )
    submit = SubmitField('Save Category')


class ProductForm(FlaskForm):
    
    
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

    
    price = DecimalField(
        'Price (if no variants)',
        places=2,
        validators=[Optional()]
    )

    image = FileField(
        'Product Image',
        validators=[
            FileAllowed(['jpg', 'png', 'jpeg', 'webp'], 'Images only! (jpg, png, jpeg, webp)'),
            FileSize(max_size=2 * 1024 * 1024)
        ]
    )
    submit = SubmitField('Save Product')

class VariantForm(FlaskForm):
    
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
    
    is_active = BooleanField(
        'Active',
        default=True
    )

    max_uses = IntegerField(
        'Max Uses (Optional)',
        validators=[Optional(), NumberRange(min=1)],
        description="Leave blank for unlimited uses."
    )

    submit = SubmitField('Save Voucher')

class UserAddForm(FlaskForm):
    
    username = StringField(
        'Username',
        validators=[DataRequired(), Length(min=4, max=100)]
    )
    role = SelectField(
        'Account Type (Role)',
        choices=[('Admin', 'Admin')],
        validators=[DataRequired()]
    )
    password = PasswordField(
        'Password',
        validators=[DataRequired(), Length(min=12), password_complexity] 
    )
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match.')]
    )
    submit = SubmitField('Create User')


class UserEditForm(FlaskForm):
    
    username = StringField(
        'Username',
        validators=[DataRequired(), Length(min=4, max=100)]
    )
    role = SelectField(
        'Account Type (Role)',
        choices=[('Admin', 'Admin')],
        validators=[DataRequired()]
    )
    password = PasswordField(
        'New Password (Optional)',
        validators=[Optional(), Length(min=12), password_complexity] 
    )
    confirm_password = PasswordField(
        'Confirm New Password',
        validators=[EqualTo('password', message='Passwords must match.')]
    )
    submit = SubmitField('Update User')

class CustomerRegisterForm(FlaskForm):
    
    name = StringField(
        'Full Name',
        validators=[DataRequired(), Length(min=3, max=255)]
    )
    
    
    contact_number = StringField(
        'Contact Number',
        validators=[
            DataRequired(), 
            Length(min=11, max=11, message="Phone number must be exactly 11 digits."), 
            Regexp(r'^\d+$', message="Phone number must contain only digits.")
        ]
    )

    address = TextAreaField(
        'Address',
        validators=[DataRequired(), Length(min=10, max=500)],
        description="Please enter your full delivery address."
    )

    landmark = StringField(
        'Landmark (Optional)',
        validators=[Optional(), Length(max=255)],
        description="e.g., Near 7-Eleven, Blue Gate, etc."
    )

    birthdate = DateField('Birthdate', validators=[DataRequired(), validate_age_and_future_date]) 
    email = StringField(
        'Email Address',
        validators=[DataRequired(), Email(), email_exists]
    )

    password = PasswordField(
        'Password',
        validators=[DataRequired(), Length(min=12), password_complexity] 
    )
    
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match.')]
    )
    
    submit = SubmitField('Create Account')
    
class CustomerLoginForm(FlaskForm):
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Log In')

class CustomerEditForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(min=3, max=255)])
    
    
    contact_number = StringField(
        'Contact Number',
        validators=[
            DataRequired(), 
            Length(min=11, max=11, message="Phone number must be exactly 11 digits."),
            Regexp(r'^\d+$', message="Phone number must contain only digits.")
        ]   
    )
    
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('New Password (Optional)', validators=[Optional(), Length(min=12), password_complexity])
    confirm_password = PasswordField('Confirm New Password', validators=[EqualTo('password', message='Passwords must match.')])
    submit = SubmitField('Update Customer')

class CustomerProfileForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(min=3, max=255)])
    
    
    contact_number = StringField(
        'Contact Number',
        validators=[
            DataRequired(), 
            Length(min=11, max=11, message="Phone number must be exactly 11 digits."),
            Regexp(r'^\d+$', message="Phone number must contain only digits.")
        ]
    )
    
    landmark = StringField('Landmark (Optional)', validators=[Optional(), Length(max=255)])
    
    birthdate = DateField('Birthdate', validators=[DataRequired(), validate_age_and_future_date])
    submit = SubmitField('Update Profile')

class DiscountVerificationForm(FlaskForm):
    
    
    discount_type = SelectField(
        'Discount Type',
        choices=[('Senior', 'Senior Citizen'), ('PWD', 'PWD')],
        validators=[DataRequired()]
    )
    id_image = FileField(
        'Upload ID Image',
        validators=[
            DataRequired(),
            FileAllowed(['jpg', 'png', 'jpeg'], 'Images only! (jpg, png, jpeg)'),
            FileSize(max_size=2 * 1024 * 1024)
        ]
    )
    submit = SubmitField('Submit for Verification')

class GCashPaymentForm(FlaskForm):
    
    
    reference_number = StringField(
        'GCash Reference Number',
        validators=[
            DataRequired(), 
            Length(min=13, max=14, message="Reference number must be 13-14 digits."),
            Regexp(r'^\d{13,14}$', message="Reference number must contain only digits.")
        ],
        description="The 13-14 digit reference number from the GCash receipt."
    )
    receipt_image = FileField(
        'Upload GCash Receipt Screenshot',
        validators=[
            DataRequired(),
            FileAllowed(['jpg', 'png', 'jpeg'], 'Images only! (jpg, png, jpeg)'),
            FileSize(max_size=3 * 1024 * 1024)
        ]
    )
    submit = SubmitField('Submit Payment Proof')

class RequestResetForm(FlaskForm):
    
    email = StringField(
        'Email Address',
        validators=[DataRequired(), Email()]
    )
    submit = SubmitField('Request Password Reset')

    def validate_email(self, email):
        customer = Customer.query.filter_by(email=email.data).first()
        if customer is None:
            raise ValidationError('There is no account with that email. You must register first.')

class ResetPasswordForm(FlaskForm):
    
    password = PasswordField(
        'New Password',
        validators=[DataRequired(), Length(min=12), password_complexity] 
    )
    confirm_password = PasswordField(
        'Confirm New Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match.')]
    )
    submit = SubmitField('Reset Password')

class ReviewForm(FlaskForm):
    
    
    rating = IntegerField(
        'Rating (1-5 Stars)', 
        validators=[
            DataRequired(), 
            NumberRange(min=1, max=5, message="Rating must be between 1 and 5.")
        ]
    )
    comment = TextAreaField(
        'Short Comment (Optional)',
        validators=[Length(max=200)],
        description="Max 200 characters."
    )
    submit = SubmitField('Submit Review')