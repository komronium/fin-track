# Implementation Plan: Fix Critical Issues This Week

## 🔴 PHASE 1: CRITICAL FIXES (24 HOURS)

### Step 1: Environment Variables
```bash
# 1. Create .env file in root directory
# Content:
DEBUG=False
DJANGO_SECRET_KEY=django-insecure-CHANGE-THIS-IMMEDIATELY!
ALLOWED_HOSTS=localhost,127.0.0.1
SECRET_KEY_BACKUP=generate-new-in-django-shell
```

Command to generate new SECRET_KEY:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Step 2: Fix settings.py (CRITICAL)
Replace this section in config/settings.py:
```python
# Line 11-15 CURRENT (DANGEROUS):
SECRET_KEY = 'django-insecure-z_ep5k&(sd!bvz1agx_sv9@xqr8976p5(9=bd)8lcx2kg53i0&'
DEBUG = True
ALLOWED_HOSTS = ['*']

# REPLACE WITH:
import os
from pathlib import Path

SECRET_KEY = os.getenv(
    'DJANGO_SECRET_KEY', 
    'django-insecure-change-me'  # Will raise error in production
)
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost').split(',')

# Add security headers
CSRF_TRUSTED_ORIGINS = os.getenv(
    'CSRF_TRUSTED_ORIGINS',
    'http://localhost:8000'
).split(',')
```

### Step 3: Remove @csrf_exempt from Views
Create a script to identify all csrf_exempt locations:
```bash
grep -n "csrf_exempt" track/views.py
# Result should show multiple lines
```

For EVERY occurrence, do the following:

From this pattern:
```python
@method_decorator(csrf_exempt, name='dispatch')
class SomeView(LoginRequiredMixin, View):
    def post(self, request):
        # Code here
```

To this pattern:
```python
class SomeView(LoginRequiredMixin, View):
    @require_http_methods(["POST"])
    def post(self, request):
        # Code here - CSRF is now protected
```

**Alternative:** If you need csrf_exempt for mobile apps, use tokens instead:
```python
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie
def get_csrf_token(request):
    return JsonResponse({'csrfToken': get_token(request)})
```

### Step 4: Add Permission Checks Immediately
File: `track/views.py`

Find all API endpoints that modify data (POST, PUT, DELETE) and add this check:
```python
# For staff-only operations:
if not request.user.is_staff:
    return JsonResponse({'error': 'Permission denied'}, status=403)

# For superuser-only operations:
if not request.user.is_superuser:
    return JsonResponse({'error': 'Permission denied'}, status=403)
```

**Critical endpoints that need checks:**
- CreateUserAPIView
- DeleteUserAPIView  
- CreateEmployeeAPIView
- DeleteEmployeeAPIView
- CreateWarehouseItemAPIView
- WarehouseMovementAPIView
- DeleteWarehouseMovementAPIView
- DeleteWarehouseItemAPIView

### Step 5: Fix Unreachable Code
File: [track/views.py](track/views.py#L1070-L1090)

Find DeleteWarehouseItemAPIView around line 1070:
```python
# CURRENT (HAS UNREACHABLE CODE):
except Exception as e:
    if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
        return JsonResponse({...})
    return redirect('warehouse')
    return JsonResponse({...})  # THIS LINE IS UNREACHABLE!

# FIX:
except Exception as e:
    if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=400)
    return redirect('warehouse')
```

### Step 6: Test the Critical Fixes
```bash
# Create a test admin user
python manage.py shell
>>> from django.contrib.auth.models import User
>>> User.objects.create_superuser('admin', 'admin@test.com', 'testpass123')

# Run tests
python manage.py test

# Run server with DEBUG=False to test
DEBUG=False python manage.py runserver
```

---

## 🟠 PHASE 2: HIGH PRIORITY FIXES (THIS WEEK)

### Add Input Validation Module
Create file: `track/validators.py`
```python
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError

def validate_amount(value):
    """Validate monetary amounts"""
    try:
        amount = Decimal(str(value))
        if amount <= 0:
            raise ValidationError("Amount must be greater than 0")
        if amount > Decimal('999999999.99'):
            raise ValidationError("Amount too large")
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Invalid amount format")

def validate_name(value, max_length=100):
    """Validate names"""
    if not value or not isinstance(value, str):
        raise ValidationError("Name is required")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"Name too long (max {max_length} chars)")
    if len(value) < 2:
        raise ValidationError("Name too short (min 2 chars)")
    return value

def validate_quantity(value):
    """Validate positive quantities"""
    try:
        qty = int(value)
        if qty < 0:
            raise ValidationError("Quantity cannot be negative")
        return qty
    except (ValueError, TypeError):
        raise ValidationError("Invalid quantity")
```

### Update Views to Use Validators
Example - CreateEmployeeAPIView:
```python
# CURRENT (NO VALIDATION):
employee = Employee.objects.create(
    first_name=data.get('first_name'),
    last_name=data.get('last_name'),
    ...
)

# FIXED (WITH VALIDATION):
from track.validators import validate_name, validate_email_address

try:
    first_name = validate_name(data.get('first_name'))
    last_name = validate_name(data.get('last_name'))
    email = validate_email_address(data.get('email', ''))
except ValidationError as e:
    return JsonResponse({'error': str(e)}, status=400)

employee = Employee.objects.create(
    first_name=first_name,
    last_name=last_name,
    email=email,
    ...
)
```

### Add Logging
File: `config/settings.py`

Add this at the end:
```python
import logging

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} - {name} - {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO' if DEBUG else 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'track': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG' if DEBUG else 'WARNING',
            'propagate': False,
        },
    },
}
```

Then create logs directory:
```bash
mkdir -p logs
touch logs/django.log
```

### Fix Decimal Handling
**EVERYWHERE** you see `int(data.get('amount'))`, change to:
```python
# WRONG:
amount = int(data.get('amount'))  # Loses decimals!

# CORRECT:
try:
    amount = Decimal(str(data.get('amount')))
    if amount <= 0 or amount > Decimal('999999999.99'):
        raise ValueError("Invalid amount")
except (InvalidOperation, ValueError, TypeError):
    return JsonResponse({'error': 'Invalid amount'}, status=400)
```

### Add Transaction Safety
File: `track/views.py`

Find AddProductAPIView and change:
```python
# CURRENT (NOT ATOMIC):
product = MonthlyProduct.objects.create(...)
entry.balance += total_amount
entry.save()

# FIXED (ATOMIC):
from django.db import transaction

@transaction.atomic
def post(self, request):
    product = MonthlyProduct.objects.create(...)
    entry.balance += total_amount
    entry.save()
    # If anything fails, EVERYTHING rolls back
```

### Implement Pagination
File: `track/views.py`

For WarehouseItemListAPIView:
```python
# CURRENT (NO PAGINATION):
items = WarehouseItem.objects.all()
data = {'items': [...]}  # Could be 10000+ items!

# FIXED:
from django.core.paginator import Paginator

page_num = request.GET.get('page', 1)
paginator = Paginator(WarehouseItem.objects.all(), 50)
page_obj = paginator.get_page(page_num)

data = {
    'count': paginator.count,
    'page': page_obj.number,
    'total_pages': paginator.num_pages,
    'items': [...]
}
```

---

## 📋 TEST CHECKLIST

After each fix, test:

```python
# Test 1: Admin can create users
POST /api/user/create/
{
    "username": "newuser",
    "password": "securepass123",
    "email": "test@example.com"
}
# Result: Should succeed for superuser, fail for others

# Test 2: CSRF protection works
POST /api/transaction/create/ (without CSRF token)
# Result: Should get 403 Forbidden

# Test 3: Invalid amounts rejected
POST /api/monthly/product/add/
{
    "entry_id": 1,
    "product_name": "Test",
    "quantity": -5,  # Invalid!
    "price_per_unit": "abc"  # Invalid!
}
# Result: Should return 400 with error message

# Test 4: Pagination works
GET /api/warehouse/items/?page=1
# Result: Should show first 50 items, not all

# Test 5: Logging works
# Check logs/django.log file
# Should contain entries like: [WARNING] 2026-02-09 10:00:00 - track - ...
```

---

## DEPLOYMENT CHECKLIST

Before deploying to production:

- [ ] Create .env file with real secrets
- [ ] Set DEBUG=False
- [ ] Update ALLOWED_HOSTS with actual domain
- [ ] Add real SECRET_KEY (use: python manage.py shell)
- [ ] Migrate to PostgreSQL (not SQLite)
- [ ] Run: `python manage.py check --deploy`
- [ ] Create backup: `pg_dump fin_track > backup.sql`
- [ ] Test on staging environment
- [ ] Set up monitoring (check Django logs daily)
- [ ] Set up daily backups
- [ ] Enable HTTPS only
- [ ] Test all critical workflows

---

## MONITORING AFTER DEPLOYMENT

Watch these files for issues:
```bash
# Daily check
tail -f logs/django.log

# Check for permission errors
grep "Permission denied\|Not authorized" logs/django.log

# Check for validation errors
grep "Invalid" logs/django.log

# Check for exceptions
grep "ERROR\|Exception" logs/django.log
```

---

## EMERGENCY ROLLBACK

If something breaks in production:
```bash
# Stop the application
sudo systemctl stop fin_track

# Restore database backup
psql fin_track < backup.sql

# Check code is clean
git status

# Restart
sudo systemctl start fin_track
```

---

**Timeline:** 
- Phase 1: 1-2 days
- Phase 2: 3-4 days  
- Ready for production: 1 week
