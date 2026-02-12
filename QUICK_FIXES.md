# Quick Reference: Exact Fixes by Location

## File: config/settings.py

### Issue 1: Exposed SECRET_KEY (Line 11)
```diff
- SECRET_KEY = 'django-insecure-z_ep5k&(sd!bvz1agx_sv9@xqr8976p5(9=bd)8lcx2kg53i0&'
+ import os
+ from pathlib import Path
+ SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'change-me-in-production')
+ if SECRET_KEY == 'change-me-in-production':
+     raise ValueError("DJANGO_SECRET_KEY not set in environment")
```

### Issue 2: DEBUG = True (Line 14)
```diff
- DEBUG = True
+ DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')
```

### Issue 3: ALLOWED_HOSTS = ['*'] (Line 15)
```diff
- ALLOWED_HOSTS = ['*']
+ ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost').split(',')
+ # Also add at end of file:
+ if not DEBUG:
+     CSRF_COOKIE_SECURE = True
+     SESSION_COOKIE_SECURE = True
+     CSRF_COOKIE_HTTPONLY = True
+     SESSION_COOKIE_HTTPONLY = True
```

### Add Missing Imports (Line 1)
```diff
  from pathlib import Path
+ import os
+ import logging
```

### Add Logging Configuration (End of file, after line 115)
```python
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
        'django': {'handlers': ['file', 'console'], 'level': 'INFO'},
        'track': {'handlers': ['file', 'console'], 'level': 'DEBUG' if DEBUG else 'WARNING'},
    },
}
```

---

## File: track/views.py

### Issue 1: @csrf_exempt on CreateTransactionAPIView (Line 147)
```diff
- @method_decorator(csrf_exempt, name='dispatch')
  class CreateTransactionAPIView(LoginRequiredMixin, View):
      """API endpoint to create a transaction"""
      
      def post(self, request):
          # Check staff permission
          perm_check = check_staff_permission(request.user)
          if perm_check:
              return perm_check
```

**FIX:** Delete line 147. CSRF is now protected by middleware.

### Issue 2: Missing permission check in CreateUserAPIView (Line 256-275)
```diff
+ @method_decorator(csrf_exempt, name='dispatch')
  class CreateUserAPIView(LoginRequiredMixin, View):
      """API endpoint to create a user"""
      
      def post(self, request):
+         # Only superusers can create users
+         if not request.user.is_superuser:
+             return JsonResponse({
+                 'success': False,
+                 'error': 'Permission denied. Superuser access required.',
+             }, status=403)
          try:
              data = json.loads(request.body)
```

### Issue 3: Bare except at line 172
```diff
        except Exception as e:
-           return JsonResponse({
+           logger.error(f"Error creating transaction: {str(e)}")
+           return JsonResponse({
                'success': False,
-               'error': str(e),
+               'error': 'Transaction creation failed',
            }, status=400)
```

Add import at top:
```python
import logging
logger = logging.getLogger(__name__)
```

### Issue 4: Missing int() → Decimal conversion (Line 165)
**CURRENT (WRONG):**
```python
transaction = Transaction.objects.create(
    type=data.get('type'),
    amount=int(data.get('amount')),  # ← LOSES DECIMALS!
```

**FIX:**
```python
from decimal import Decimal, InvalidOperation

try:
    amount_str = str(data.get('amount', '0')).strip()
    amount = Decimal(amount_str)
    if amount <= 0:
        raise ValueError("Amount must be positive")
    if amount > Decimal('999999999.99'):
        raise ValueError("Amount too large")
except (InvalidOperation, ValueError, TypeError) as e:
    return JsonResponse({
        'success': False,
        'error': f'Invalid amount: {str(e)}'
    }, status=400)

transaction = Transaction.objects.create(
    type=data.get('type'),
    amount=amount,  # Now properly handles decimals
```

### Issue 5: Unreachable code in DeleteWarehouseItemAPIView (Lines 1078-1085)
```diff
      except Exception as e:
          if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
              return JsonResponse({
                  'success': False,
                  'error': str(e),
              }, status=400)
          return redirect('warehouse')
-         return JsonResponse({
-             'success': False,
-             'error': str(e),
-         }, status=400)
```

Delete the last 4 lines (1082-1085) - they're unreachable!

### Issue 6: Missing @csrf_exempt on DeleteWarehouseItemAPIView (Line 1065)
```diff
+ @method_decorator(csrf_exempt, name='dispatch')
  class DeleteWarehouseItemAPIView(LoginRequiredMixin, View):
      """Delete a warehouse item"""
      
      def post(self, request, item_id):
```

### Issue 7: Negative inventory issue in WarehouseMovementAPIView (Line 966)
```diff
      # Update item quantity
      if movement_type == 'in':
          item.quantity += quantity
      else:
-         item.quantity = max(0, item.quantity - quantity)
+         if item.quantity < quantity:
+             return JsonResponse({
+                 'success': False,
+                 'error': f'Insufficient stock. Available: {item.quantity}, Requested: {quantity}'
+             }, status=400)
+         item.quantity -= quantity
```

### Issue 8: Missing permission check in CreateUserAPIView (Line ~310)
```diff
  @method_decorator(csrf_exempt, name='dispatch')
  class CreateUserAPIView(LoginRequiredMixin, View):
      """API endpoint to create a user"""
      
      def post(self, request):
+         if not request.user.is_superuser:
+             logger.warning(f"Unauthorized user creation attempt by {request.user.username}")
+             return JsonResponse({
+                 'success': False,
+                 'error': 'Permission denied',
+             }, status=403)
```

### Issue 9: No input validation on emails (Multiple locations)
Add at top of file:
```python
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
```

Then in CreateUserAPIView:
```python
email = data.get('email', '').strip()
if email:
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid email format'
        }, status=400)
```

### Issue 10: Add transaction.atomic to multi-step operations (Line ~752 for AddProductAPIView)
```diff
  @method_decorator(csrf_exempt, name='dispatch')
  class AddProductAPIView(LoginRequiredMixin, View):
      """API endpoint to add a product to monthly entry"""
      
      def post(self, request):
+         from django.db import transaction
+         
+         @transaction.atomic
+         def create_product():
          try:
              # Check if it's form data or JSON
              # ... existing code ...
              
              product = MonthlyProduct.objects.create(
                  monthly_entry=entry,
                  product_name=product_name,
                  quantity=quantity,
                  price_per_unit=price_per_unit,
                  total_amount=total_amount
              )
              
              # Update balance
              entry.balance += total_amount
              entry.save()
+             return product
+         
+         try:
+             product = create_product()
```

### Issue 11: Add pagination to list views (Line ~573 for WarehouseItemListAPIView)
```diff
  class WarehouseItemListAPIView(LoginRequiredMixin, View):
      """Get all warehouse items with their movements"""
      
      def get(self, request):
          if not request.user.is_staff:
              return JsonResponse({'error': 'Not authorized'}, status=403)
          
+         from django.core.paginator import Paginator
+         
          items = WarehouseItem.objects.all()
+         
+         page = request.GET.get('page', 1)
+         paginator = Paginator(items, 50)  # 50 items per page
+         try:
+             page_obj = paginator.page(page)
+         except:
+             page_obj = paginator.page(1)
+         
          data = {
+             'count': paginator.count,
+             'page': page_obj.number,
+             'total_pages': paginator.num_pages,
              'items': []
          }
          
-         for item in items:
+         for item in page_obj.object_list:
```

---

## File: track/models.py

### Add database indexes (After class definitions)
```python
class Transaction(models.Model):
    type = models.CharField(max_length=100, choices=TYPE_CHOICES, db_index=True)
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name='transactions', db_index=True)
    amount = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)
    date = models.DateField(db_index=True)  # Add index
    created_at = models.DateTimeField(auto_now_add=True)

class MonthlyEntry(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='monthly_entries', db_index=True)
    month = models.DateField(db_index=True)  # Add index
    # ... rest of fields ...
    
    class Meta:
        db_table = 'monthly_entries'
        ordering = ['-month', 'employee']
        unique_together = ('employee', 'month')
        indexes = [
            models.Index(fields=['employee', 'month']),  # Add composite index
        ]
```

---

## File: Create new file - track/validators.py

```python
# track/validators.py
from decimal import Decimal, InvalidOperation
from django.core.validators import validate_email as django_validate_email
from django.core.exceptions import ValidationError

def validate_amount(value):
    """Validate monetary amounts"""
    try:
        amount = Decimal(str(value))
        if amount <= 0:
            raise ValidationError("Amount must be greater than 0")
        if amount > Decimal('999999999.99'):
            raise ValidationError("Amount exceeds maximum (999,999,999.99)")
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
            raise ValidationError("Quantity exceeds maximum (999,999)")
        return qty
    except (ValueError, TypeError):
        raise ValidationError("Invalid quantity - must be a number")

def validate_name(value, max_length=100):
    """Validate names for employees, products, etc."""
    if not value or not isinstance(value, str):
        raise ValidationError("Name is required")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"Name exceeds {max_length} characters")
    if len(value) < 2:
        raise ValidationError("Name must be at least 2 characters")
    return value

def validate_email_address(value):
    """Validate email addresses"""
    if not value:
        return None
    value = value.strip()
    try:
        django_validate_email(value)
        return value
    except ValidationError:
        raise ValidationError("Invalid email format")

def validate_phone(value):
    """Validate phone numbers"""
    if not value:
        return None
    value = value.strip()
    if not all(c.isdigit() or c in '+-() ' for c in value):
        raise ValidationError("Invalid phone number characters")
    if len(value) < 7:
        raise ValidationError("Phone number too short")
    return value
```

---

## File: Create .env (in project root)

```bash
# Security Settings
DEBUG=False
DJANGO_SECRET_KEY=your-secret-key-here-CHANGE-THIS-IMMEDIATELY!
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (for PostgreSQL)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=fin_track
DB_USER=postgres
DB_PASSWORD=your-password-here
DB_HOST=localhost
DB_PORT=5432

# CORS & CSRF
CSRF_TRUSTED_ORIGINS=http://localhost:8000,https://yourdomain.com
CORS_ALLOWED_ORIGINS=http://localhost:8000,https://yourdomain.com
```

---

## File: requirements.txt (Update)

```diff
  Django==6.0.1
+ python-decouple==3.8
+ psycopg2-binary==2.9.9
+ djangorestframework==3.14.0
+ django-ratelimit==4.1.0
+ sentry-sdk==1.40.0
```

---

## Commands to Run

```bash
# 1. Create logs directory
mkdir -p logs
touch logs/django.log

# 2. Create .env file
# (copy template from above)

# 3. Install new packages
pip install -r requirements.txt

# 4. Test with DEBUG=False
DEBUG=False python manage.py check --deploy

# 5. Run tests
python manage.py test

# 6. Create database migrations
python manage.py makemigrations

# 7. Apply migrations
python manage.py migrate
```

---

## Testing Checklist

```bash
# Test 1: Verify settings are secure
python manage.py shell
>>> from django.conf import settings
>>> print(f"DEBUG: {settings.DEBUG}")  # Should be False
>>> print(f"ALLOWED_HOSTS: {settings.ALLOWED_HOSTS}")  # Should have your domain
>>> print(f"SECRET_KEY: {len(settings.SECRET_KEY)} chars")  # Should be >50

# Test 2: Verify permissions work
curl -X POST http://localhost:8000/api/user/create/ \
  -H "Content-Type: application/json" \
  -d '{"username": "test"}'
# Should get 403 Forbidden (not 200)

# Test 3: Verify input validation
curl -X POST http://localhost:8000/api/transaction/create/ \
  -H "Content-Type: application/json" \
  -d '{"amount": "abc"}'
# Should get 400 Bad Request with error message

# Test 4: Verify logging works
tail -f logs/django.log
# Should see entries when you make requests
```

---

**Total estimated time for all fixes: 8-10 hours**  
**Priority: COMPLETE THIS WEEK before running in production**
