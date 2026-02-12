# Django Fin-Track Security Remediation Guide

## Quick Fix Priority

### 1. ENVIRONMENT VARIABLES SETUP

Create `.env` file:
```bash
DEBUG=False
DJANGO_SECRET_KEY=your-super-secret-key-here-change-this
ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com
DATABASE_URL=postgresql://user:password@localhost/fin_track
CSRF_TRUSTED_ORIGINS=https://your-domain.com
```

### 2. UPDATE settings.py

Replace the dangerous hardcoded values:

```python
# config/settings.py
import os
from pathlib import Path
from decouple import config, Csv  # pip install python-decouple

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY: Load from environment
SECRET_KEY = config('DJANGO_SECRET_KEY')
if SECRET_KEY == 'django-insecure-xxx':
    raise ValueError("DJANGO_SECRET_KEY environment variable is required!")

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost', cast=Csv())

# CSRF Configuration
CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS', 
    default='http://localhost:8000', 
    cast=Csv()
)

# In production, require HTTPS for CSRF
if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_HTTPONLY = True
    SESSION_COOKIE_HTTPONLY = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    
    'track.apps.TrackConfig',
    'django_ratelimit',  # Add for rate limiting
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.security.SecurityMiddleware',
]

# Additional security settings for production
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    X_FRAME_OPTIONS = 'DENY'

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
        },
        'console': {
            'level': 'INFO' if DEBUG else 'WARNING',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'track': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': True,
        },
    },
}

# Database - Support PostgreSQL for production
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql' if not DEBUG else 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3' if DEBUG else config('DB_NAME', default='fin_track'),
        'USER': config('DB_USER', default=''),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default=''),
        'PORT': config('DB_PORT', default=''),
    }
}
```

### 3. CREATE AUTHENTICATION & PERMISSION UTILITIES

Create `track/auth_utils.py`:
```python
# track/auth_utils.py
from functools import wraps
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import logging

logger = logging.getLogger(__name__)

def require_staff(view_func):
    """Decorator to require staff permission"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            logger.warning(f"Unauthenticated access attempt to {view_func.__name__}")
            return JsonResponse(
                {'error': 'Authentication required'}, 
                status=401
            )
        if not request.user.is_staff:
            logger.warning(
                f"Unauthorized access attempt by {request.user.username} "
                f"to {view_func.__name__}"
            )
            return JsonResponse(
                {'error': 'Permission denied. Staff access required'}, 
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper

def require_superuser(view_func):
    """Decorator to require superuser permission"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {'error': 'Authentication required'}, 
                status=401
            )
        if not request.user.is_superuser:
            logger.warning(
                f"Unauthorized superuser access attempt by {request.user.username}"
            )
            return JsonResponse(
                {'error': 'Permission denied. Superuser access required'}, 
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper

def log_action(action_type, user, model_name, object_id=None, details=None):
    """Log security-relevant actions"""
    message = f"{action_type} | User: {user.username} | Model: {model_name}"
    if object_id:
        message += f" | ID: {object_id}"
    if details:
        message += f" | Details: {details}"
    logger.info(message)
```

### 4. CREATE VALIDATION UTILITIES

Create `track/validators.py`:
```python
# track/validators.py
from decimal import Decimal, InvalidOperation
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

def validate_amount(value):
    """Validate monetary amounts"""
    try:
        amount = Decimal(str(value))
        if amount <= 0:
            raise ValidationError("Amount must be greater than 0")
        if amount > Decimal('999999999.99'):
            raise ValidationError("Amount exceeds maximum allowed value")
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Invalid amount format")

def validate_quantity(value):
    """Validate positive integer quantities"""
    try:
        qty = int(value)
        if qty < 0:
            raise ValidationError("Quantity cannot be negative")
        if qty > 999999:
            raise ValidationError("Quantity exceeds maximum allowed value")
        return qty
    except (ValueError, TypeError):
        raise ValidationError("Invalid quantity format")

def validate_name(value, max_length=100):
    """Validate names"""
    if not value or not isinstance(value, str):
        raise ValidationError("Name is required")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"Name exceeds {max_length} characters")
    if len(value) < 2:
        raise ValidationError("Name must be at least 2 characters")
    if not all(c.isalnum() or c.isspace() or c in '-_ñ' for c in value):
        raise ValidationError("Name contains invalid characters")
    return value

def validate_email_address(value):
    """Validate email addresses"""
    if not value:
        return None
    try:
        validate_email(value)
        return value
    except ValidationError:
        raise ValidationError("Invalid email format")

def validate_phone(value):
    """Validate phone numbers"""
    if not value:
        return None
    value = value.strip()
    if not all(c.isdigit() or c in '+-() ' for c in value):
        raise ValidationError("Invalid phone number format")
    if len(value) < 7:
        raise ValidationError("Phone number too short")
    return value
```

### 5. UPDATE VIEWS WITH PROPER SECURITY

Create `track/views_secure.py` (example for key views):

```python
# track/views_secure.py - Secure version of critical views
import logging
import json
from decimal import Decimal
from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator

from track.models import Transaction, Employee, MonthlyEntry
from track.validators import (
    validate_amount, validate_name, validate_quantity, 
    validate_email_address, validate_phone
)
from track.auth_utils import log_action, require_staff

logger = logging.getLogger(__name__)

class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to require staff permission"""
    def test_func(self):
        return self.user.is_staff
    
    def handle_no_permission(self):
        logger.warning(f"Staff access denied for {self.request.user}")
        return JsonResponse({'error': 'Permission denied'}, status=403)

class SuperuserRequiredMixin(UserPassesTestMixin):
    """Mixin to require superuser permission"""
    def test_func(self):
        return self.user.is_superuser
    
    def handle_no_permission(self):
        logger.warning(f"Superuser access denied for {self.request.user}")
        return JsonResponse({'error': 'Permission denied'}, status=403)

class TransactionListAPIView(LoginRequiredMixin, View):
    """SECURE: List transactions with pagination and proper filtering"""
    
    def get(self, request):
        try:
            # Get all user's transactions (or admin sees all)
            transactions = Transaction.objects.all()
            
            # Validate and apply filters
            transaction_type = request.GET.get('type')
            if transaction_type and transaction_type in [Transaction.TYPE_INCOME, Transaction.TYPE_EXPENSE]:
                transactions = transactions.filter(type=transaction_type)
            
            method_id = request.GET.get('method')
            if method_id:
                try:
                    method_id = int(method_id)
                    transactions = transactions.filter(method_id=method_id)
                except (ValueError, TypeError):
                    pass
            
            # Date range validation
            date_from = request.GET.get('date_from')
            if date_from:
                try:
                    transactions = transactions.filter(date__gte=date_from)
                except ValidationError:
                    pass
            
            date_to = request.GET.get('date_to')
            if date_to:
                try:
                    transactions = transactions.filter(date__lte=date_to)
                except ValidationError:
                    pass
            
            # Pagination
            page = request.GET.get('page', 1)
            paginator = Paginator(transactions.order_by('-date'), 50)
            try:
                page_obj = paginator.page(page)
            except:
                page_obj = paginator.page(1)
            
            data = {
                'count': paginator.count,
                'page': page_obj.number,
                'total_pages': paginator.num_pages,
                'transactions': [
                    {
                        'id': t.id,
                        'type': t.type,
                        'amount': str(t.amount),
                        'description': t.description[:255],  # Limit output
                        'date': t.date.isoformat(),
                        'method_name': t.method.name,
                    }
                    for t in page_obj.object_list
                ]
            }
            
            return JsonResponse(data)
        except Exception as e:
            logger.error(f"Error listing transactions: {str(e)}", exc_info=True)
            return JsonResponse(
                {'error': 'Failed to retrieve transactions'}, 
                status=500
            )

class CreateTransactionAPIView(StaffRequiredMixin, LoginRequiredMixin, View):
    """SECURE: Create transaction with full validation and audit logging"""
    
    @method_decorator(require_http_methods(["POST"]))
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate all inputs
            if data.get('type') not in [Transaction.TYPE_INCOME, Transaction.TYPE_EXPENSE]:
                return JsonResponse({'error': 'Invalid transaction type'}, status=400)
            
            try:
                amount = validate_amount(data.get('amount'))
            except ValidationError as e:
                return JsonResponse({'error': str(e)}, status=400)
            
            method_id = data.get('method')
            if not method_id:
                return JsonResponse({'error': 'Payment method required'}, status=400)
            
            # Use transaction to ensure atomicity
            with transaction.atomic():
                trans = Transaction.objects.create(
                    type=data['type'],
                    amount=amount,
                    description=data.get('description', '')[:255],
                    date=data.get('date'),
                    method_id=int(method_id),
                )
                
                # Log the action
                log_action(
                    'TRANSACTION_CREATED',
                    request.user,
                    'Transaction',
                    trans.id,
                    f"Type: {trans.type}, Amount: {trans.amount}"
                )
            
            return JsonResponse({
                'success': True,
                'id': trans.id,
                'message': 'Transaction created successfully'
            }, status=201)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid transaction creation attempt: {str(e)}")
            return JsonResponse({'error': 'Invalid input format'}, status=400)
        except Exception as e:
            logger.error(f"Error creating transaction: {str(e)}", exc_info=True)
            return JsonResponse({'error': 'Server error'}, status=500)

class CreateUserAPIView(SuperuserRequiredMixin, LoginRequiredMixin, View):
    """SECURE: Only superusers can create users"""
    
    @transaction.atomic
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Validate username
            username = data.get('username', '').strip()
            if not username or len(username) < 3:
                return JsonResponse(
                    {'error': 'Username must be at least 3 characters'}, 
                    status=400
                )
            
            if User.objects.filter(username=username).exists():
                return JsonResponse({'error': 'Username already exists'}, status=400)
            
            # Validate email
            email = data.get('email', '').strip()
            if email:
                try:
                    validate_email_address(email)
                except ValidationError as e:
                    return JsonResponse({'error': str(e)}, status=400)
            
            # Validate password
            password = data.get('password')
            if not password or len(password) < 8:
                return JsonResponse(
                    {'error': 'Password must be at least 8 characters'}, 
                    status=400
                )
            
            from django.contrib.auth.password_validation import validate_password
            try:
                validate_password(password)
            except ValidationError as e:
                return JsonResponse({'error': e.messages[0]}, status=400)
            
            # Create user
            user = User.objects.create_user(
                username=username,
                password=password,
                first_name=data.get('first_name', '')[:50],
                last_name=data.get('last_name', '')[:50],
                email=email,
                is_staff=data.get('is_staff', False),
                is_active=data.get('is_active', True),
            )
            
            log_action('USER_CREATED', request.user, 'User', user.id, username)
            
            return JsonResponse({
                'success': True,
                'id': user.id,
                'username': user.username,
                'message': 'User created successfully'
            }, status=201)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}", exc_info=True)
            return JsonResponse({'error': 'Server error'}, status=500)
```

### 6. UPDATE requirements.txt

```
Django==6.0.1
psycopg2-binary==2.9.9  # PostgreSQL adapter
python-decouple==3.8    # Environment variable management
djangorestframework==3.14.0  # Better API support
django-ratelimit==4.1.0  # Rate limiting
django-cors-headers==4.3.1  # CORS handling
sentry-sdk==1.40.0  # Error tracking
```

### 7. CREATE A FIX SCRIPT

Run this to generate a fixed views.py file.

```bash
# Create logs directory
mkdir -p logs

# Install packages
pip install -r requirements.txt

# Create .env file
echo "DEBUG=False
DJANGO_SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=fin_track
DB_USER=postgres
DB_PASSWORD=password
DB_HOST=localhost
DB_PORT=5432" > .env

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

---

## WHAT TO DO NEXT

1. **Stop current application**
2. **Backup database**: `cp db.sqlite3 db.sqlite3.backup`
3. **Create .env file** with proper secrets
4. **Apply the security patches** (view decorators, validators, etc.)
5. **Test thoroughly** on staging
6. **Run migration to PostgreSQL** if needed
7. **Deploy with monitoring** (Sentry, NewRelic, etc.)

---

**Critical: After applying these fixes, change ALL hardcoded secrets immediately!**
