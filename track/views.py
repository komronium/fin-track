import json
import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction as db_transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView, View

from track.models import (
    Employee, MonthlyEntry, MonthlyPayment, MonthlyProduct, PaymentMethod,
    Transaction, WarehouseItem, WarehouseMovement,
)

logger = logging.getLogger(__name__)

CURRENCIES = ('uzs', 'usd', 'afn')
UNIT_TYPES = (MonthlyProduct.UNIT_DONA, MonthlyProduct.UNIT_KG)
TRANSACTION_TYPES = (Transaction.TYPE_INCOME, Transaction.TYPE_EXPENSE)
MOVEMENT_TYPES = (WarehouseMovement.IN, WarehouseMovement.OUT)

MONEY_STEP = Decimal('0.01')
MAX_AMOUNT = Decimal('999999999999.99')   # Transaction.amount: 14 digits, 2 decimals
MAX_TOTAL = Decimal('9999999999.99')      # monthly products / payments: 12 digits, 2 decimals
MAX_UNIT_PRICE = Decimal('99999999.99')   # MonthlyProduct.price_per_unit: 10 digits, 2 decimals
MAX_STOCK_KG = Decimal('9999999999.99')
MAX_STOCK_QTY = 2_000_000_000

TRANSACTION_PAGE_SIZE = 200      # rows rendered / returned by default
MAX_TRANSACTION_LIMIT = 1000
WAREHOUSE_MOVEMENT_PAGE_SIZE = 200  # rows of history rendered before "Show all"
DEFAULT_DASHBOARD_DAYS = 5      # the dashboard opens on the last N days


# --------------------------------------------------------------------------- #
# Errors and input parsing
# --------------------------------------------------------------------------- #

class APIError(Exception):
    """A problem with the request that should be reported to the user as-is."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def error_response(message, status=400):
    return JsonResponse({'success': False, 'error': message}, status=status)


def session_expired_response(message, status):
    """Marked so the page script can send the person to the sign-in page instead of showing an error."""
    response = error_response(message, status=status)
    response['X-Session-Expired'] = '1'
    return response


def csrf_failure(request, reason=''):
    """Friendly handling of a stale page / expired session (instead of Django's technical 403 page)."""
    if request.META.get('HTTP_ACCEPT', '').startswith('application/json') or wants_json(request) \
            or request.META.get('HTTP_X_CSRFTOKEN'):
        return session_expired_response('Your session has expired. Please sign in again.', status=403)
    from urllib.parse import quote, urlparse
    path = urlparse(request.META.get('HTTP_REFERER', '')).path
    return redirect(f"/login/?next={quote(path if path.startswith('/') else '/')}")


def wants_json(request):
    return 'application/json' in request.META.get('CONTENT_TYPE', '')


def load_json(request):
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        raise APIError('Invalid JSON body.')
    if not isinstance(data, dict):
        raise APIError('Invalid JSON body.')
    return data


def load_data(request):
    """JSON body for fetch() callers, form fields for classic form posts."""
    if wants_json(request):
        return load_json(request)
    return request.POST.dict()


def blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def parse_text(value, field, max_len, required=False):
    if blank(value):
        if required:
            raise APIError(f'{field} is required.')
        return ''
    if isinstance(value, (dict, list, bool)):
        raise APIError(f'{field} is not valid.')
    text = str(value).strip()
    if len(text) > max_len:
        raise APIError(f'{field} must be at most {max_len} characters.')
    return text


def parse_choice(value, choices, field):
    if value not in choices:
        raise APIError(f'{field} must be one of: {", ".join(choices)}.')
    return value


def parse_int(value, field, minimum=None, maximum=None, default=None):
    if blank(value):
        if default is not None:
            return default
        raise APIError(f'{field} is required.')
    if isinstance(value, bool):
        raise APIError(f'{field} must be a whole number.')
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise APIError(f'{field} must be a whole number.')
    if not number.is_finite() or number != number.to_integral_value():
        raise APIError(f'{field} must be a whole number.')
    number = int(number)
    if minimum is not None and number < minimum:
        raise APIError(f'{field} must be at least {minimum}.')
    if maximum is not None and number > maximum:
        raise APIError(f'{field} is too large.')
    return number


def parse_decimal(value, field, minimum=MONEY_STEP, maximum=MAX_AMOUNT, default=None):
    if blank(value):
        if default is not None:
            return default
        raise APIError(f'{field} is required.')
    if isinstance(value, (bool, dict, list)):
        raise APIError(f'{field} must be a number.')
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise APIError(f'{field} must be a number.')
    if not number.is_finite():
        raise APIError(f'{field} must be a number.')
    if abs(number) > maximum * 10:
        raise APIError(f'{field} is too large.')
    number = number.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
    if number < minimum:
        raise APIError(f'{field} must be at least {minimum}.')
    if number > maximum:
        raise APIError(f'{field} is too large.')
    return number


def parse_date(value, field, allow_future=False):
    if blank(value):
        raise APIError(f'{field} is required.')
    try:
        parsed = datetime.strptime(str(value).strip(), '%Y-%m-%d').date()
    except ValueError:
        raise APIError(f'{field} must be a valid date (YYYY-MM-DD).')
    if not allow_future and parsed > timezone.localdate() + timedelta(days=1):
        raise APIError(f'{field} cannot be in the future.')
    return parsed


def parse_bool(value, field, default=True):
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('1', 'true', 'on', 'yes'):
        return True
    if text in ('0', 'false', 'off', 'no'):
        return False
    raise APIError(f'{field} must be true or false.')


def parse_email(value):
    email = parse_text(value, 'Email', 254)
    if email:
        try:
            validate_email(email)
        except DjangoValidationError:
            raise APIError('Enter a valid email address.')
    return email


def get_or_404(source, pk, label):
    """`source` is a model class or a queryset (e.g. with select_related / select_for_update)."""
    queryset = source._default_manager.all() if isinstance(source, type) else source
    try:
        return queryset.get(pk=pk)
    except queryset.model.DoesNotExist:
        raise APIError(f'{label} not found.', status=404)


def num(value):
    """Decimal -> int when whole, else float, so JSON stays a plain number."""
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


def money_str(value):
    return str(Decimal(value).quantize(MONEY_STEP))


def current_month_start():
    return timezone.localdate().replace(day=1)


# --------------------------------------------------------------------------- #
# Base class for JSON endpoints
# --------------------------------------------------------------------------- #

class ApiView(View):
    """Login required; selected methods staff-only; APIError -> JSON; surprises are logged, not leaked."""

    staff_methods = ('POST',)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return session_expired_response('Authentication required.', status=401)
        try:
            if request.method in self.staff_methods and not request.user.is_staff:
                raise APIError('Permission denied. Only staff users can perform this action.', status=403)
            return super().dispatch(request, *args, **kwargs)
        except APIError as exc:
            return self.handle_api_error(request, exc)
        except Exception:
            logger.exception('Unhandled error in %s', self.__class__.__name__)
            return self.handle_api_error(request, APIError('Something went wrong. Please try again.', status=500))

    def handle_api_error(self, request, exc):
        return error_response(exc.message, status=exc.status)


class FormOrApiView(ApiView):
    """Endpoints used both by fetch() and by plain HTML forms (errors become flash messages)."""

    redirect_to = 'warehouse'

    def handle_api_error(self, request, exc):
        if wants_json(request):
            return error_response(exc.message, status=exc.status)
        messages.error(request, exc.message)
        return redirect(self.redirect_to)


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #

def filter_transactions(params):
    qs = Transaction.objects.select_related('method')
    if params.get('type'):
        qs = qs.filter(type=parse_choice(params['type'], TRANSACTION_TYPES, 'Type'))
    if params.get('method'):
        qs = qs.filter(method_id=parse_int(params['method'], 'Method', minimum=1))
    if params.get('date_from'):
        qs = qs.filter(date__gte=parse_date(params['date_from'], 'Start date', allow_future=True))
    if params.get('date_to'):
        qs = qs.filter(date__lte=parse_date(params['date_to'], 'End date', allow_future=True))
    if params.get('currency'):
        qs = qs.filter(currency=parse_choice(params['currency'], CURRENCIES, 'Currency'))
    return qs


def transaction_stats(qs):
    """Income / expense / balance for every currency, as plain numbers."""
    totals = {(row['currency'], row['type']): row['total']
              for row in qs.order_by().values('currency', 'type').annotate(total=Sum('amount'))}
    result = {}
    for curr in CURRENCIES:
        inc = totals.get((curr, Transaction.TYPE_INCOME)) or Decimal('0')
        exp = totals.get((curr, Transaction.TYPE_EXPENSE)) or Decimal('0')
        result[f'incomes_{curr}'] = num(inc)
        result[f'expenses_{curr}'] = num(exp)
        result[f'balance_{curr}'] = num(inc - exp)
    return result


def clean_transaction(data, current=None):
    """Validated field values for a Transaction; `current` supplies defaults when updating."""
    def pick(key, fallback):
        return data[key] if key in data else fallback

    method_id = parse_int(pick('method', current.method_id if current else None), 'Payment method', minimum=1)
    if not PaymentMethod.objects.filter(id=method_id).exists():
        raise APIError('Unknown payment method.')
    return {
        'type': parse_choice(pick('type', current.type if current else None), TRANSACTION_TYPES, 'Type'),
        'currency': parse_choice(pick('currency', current.currency if current else 'uzs'), CURRENCIES, 'Currency'),
        'amount': parse_decimal(pick('amount', current.amount if current else None), 'Amount', maximum=MAX_AMOUNT),
        'description': parse_text(pick('description', current.description if current else ''), 'Description', 255),
        'date': parse_date(pick('date', current.date.isoformat() if current else None), 'Date'),
        'method_id': method_id,
    }


def dashboard_filters(params):
    """Filters for the first paint: the URL's, or the last DEFAULT_DASHBOARD_DAYS days when none are given."""
    today = timezone.localdate()
    defaults = {
        'type': '', 'currency': '',
        'date_from': (today - timedelta(days=DEFAULT_DASHBOARD_DAYS)).isoformat(),
        'date_to': today.isoformat(),
    }
    if not any(key in params for key in defaults):
        return defaults
    filters = {key: params.get(key, '') for key in defaults}
    try:
        filter_transactions(filters)
    except APIError:
        return defaults
    return filters


def period_label(filters):
    """Words for the period the stat cards cover, e.g. '2026-10-24 \u2013 2026-10-29'."""
    start, end = filters.get('date_from'), filters.get('date_to')
    if start and end:
        return f'Totals for {start} \u2013 {end}'
    if start:
        return f'Totals from {start}'
    if end:
        return f'Totals up to {end}'
    return 'Totals for all time'


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_context_data(self, **kwargs):
        filters = dashboard_filters(self.request.GET)
        transactions = filter_transactions(filters)
        kwargs['filters'] = filters
        kwargs['period_label'] = period_label(filters)
        kwargs['transactions'] = transactions.order_by('-date', 'id')[:TRANSACTION_PAGE_SIZE]
        kwargs['transactions_total'] = transactions.count()
        kwargs['payment_methods'] = PaymentMethod.objects.all()
        kwargs.update(transaction_stats(transactions))
        return super().get_context_data(**kwargs)


class TransactionListAPIView(ApiView):
    """API endpoint to list transactions with filters"""

    def get(self, request):
        queryset = filter_transactions(request.GET)
        limit = parse_int(request.GET.get('limit'), 'Limit', minimum=1, maximum=MAX_TRANSACTION_LIMIT,
                          default=TRANSACTION_PAGE_SIZE)
        return JsonResponse({
            'total': queryset.count(),
            'transactions': [
                {
                    'id': t.id,
                    'type': t.type,
                    'currency': t.currency,
                    'amount': num(t.amount),
                    'description': t.description,
                    'date': t.date.isoformat(),
                    'method_id': t.method_id,
                    'method_name': t.method.name,
                }
                for t in queryset.order_by('-date', 'id')[:limit]
            ]
        })


class StatsAPIView(ApiView):
    """API endpoint to get stats with filters"""

    def get(self, request):
        return JsonResponse(transaction_stats(filter_transactions(request.GET)))


class CreateTransactionAPIView(ApiView):
    """API endpoint to create a transaction"""

    def post(self, request):
        created = Transaction.objects.create(**clean_transaction(load_json(request)))
        return JsonResponse({'success': True, 'id': created.id})


class TransactionDetailAPIView(ApiView):
    """API endpoint to get or update a transaction"""

    def get(self, request, transaction_id):
        t = get_or_404(Transaction, transaction_id, 'Transaction')
        return JsonResponse({
            'id': t.id,
            'type': t.type,
            'currency': t.currency,
            'amount': num(t.amount),
            'description': t.description,
            'date': t.date.isoformat(),
            'method': t.method_id,
        })

    def post(self, request, transaction_id):
        t = get_or_404(Transaction, transaction_id, 'Transaction')
        for field, value in clean_transaction(load_json(request), current=t).items():
            setattr(t, field, value)
        t.save()
        return JsonResponse({'success': True, 'id': t.id})


class DeleteTransactionAPIView(ApiView):
    """API endpoint to delete a transaction"""

    def post(self, request, transaction_id):
        get_or_404(Transaction, transaction_id, 'Transaction').delete()
        return JsonResponse({'success': True})


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #

def user_payload(user):
    return {
        'id': user.id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'is_active': user.is_active,
        'is_staff': user.is_staff,
    }


def password_error(password, user=None):
    """Return a human readable message if the password is rejected, else None."""
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        return ' '.join(exc.messages)
    return None


class UsersView(LoginRequiredMixin, TemplateView):
    template_name = 'users.html'

    def get_context_data(self, **kwargs):
        kwargs['users'] = User.objects.all()
        return super().get_context_data(**kwargs)


class UsersListAPIView(ApiView):
    """API endpoint to list users"""

    def get(self, request):
        return JsonResponse({'users': [user_payload(u) for u in User.objects.all()]})


class CreateUserAPIView(ApiView):
    """API endpoint to create a user"""

    def post(self, request):
        data = load_json(request)
        username = parse_text(data.get('username'), 'Username', 150, required=True)
        password = data.get('password') or ''
        if User.objects.filter(username__iexact=username).exists():
            raise APIError('Username already exists.')
        message = password_error(password, User(username=username))
        if message:
            raise APIError(message)

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=parse_text(data.get('first_name'), 'First name', 150),
            last_name=parse_text(data.get('last_name'), 'Last name', 150),
            email=parse_email(data.get('email')),
            is_staff=parse_bool(data.get('is_staff'), 'Staff flag', default=False),
            is_active=parse_bool(data.get('is_active'), 'Active flag', default=True),
        )
        return JsonResponse({'success': True, 'id': user.id})


class UserDetailAPIView(ApiView):
    """API endpoint to get or update a user"""

    def get(self, request, user_id):
        return JsonResponse(user_payload(get_or_404(User, user_id, 'User')))

    def post(self, request, user_id):
        user = get_or_404(User, user_id, 'User')

        # Only superusers may modify superuser accounts (prevents staff -> superuser takeover).
        if user.is_superuser and not request.user.is_superuser:
            raise APIError('Only a superuser can modify a superuser.', status=403)

        data = load_json(request)
        is_staff = parse_bool(data.get('is_staff'), 'Staff flag', default=user.is_staff)
        is_active = parse_bool(data.get('is_active'), 'Active flag', default=user.is_active)
        if user.id == request.user.id and (not is_staff or not is_active):
            raise APIError('You cannot remove your own staff access or deactivate yourself.')

        password = data.get('password')
        if password:
            message = password_error(password, user)
            if message:
                raise APIError(message)
            user.set_password(password)

        user.first_name = parse_text(data.get('first_name', user.first_name), 'First name', 150)
        user.last_name = parse_text(data.get('last_name', user.last_name), 'Last name', 150)
        user.email = parse_email(data.get('email', user.email))
        user.is_staff = is_staff
        user.is_active = is_active
        user.save()
        return JsonResponse({'success': True, 'id': user.id})


class DeleteUserAPIView(ApiView):
    """API endpoint to delete a user"""

    def post(self, request, user_id):
        user = get_or_404(User, user_id, 'User')
        if user.id == request.user.id:
            raise APIError('You cannot delete your own account.')
        if user.is_superuser and not request.user.is_superuser:
            raise APIError('Only a superuser can delete a superuser.', status=403)
        user.delete()
        return JsonResponse({'success': True})


# --------------------------------------------------------------------------- #
# Employees and monthly accounts
# --------------------------------------------------------------------------- #

def entry_balances(entry_ids):
    """{entry_id: {'uzs': Decimal, 'usd': Decimal, 'afn': Decimal}} = products - payments per currency."""
    balances = {eid: {curr: Decimal('0') for curr in CURRENCIES} for eid in entry_ids}
    products = (MonthlyProduct.objects.filter(monthly_entry_id__in=entry_ids)
                .order_by().values('monthly_entry_id', 'currency').annotate(total=Sum('total_amount')))
    payments = (MonthlyPayment.objects.filter(monthly_entry_id__in=entry_ids)
                .order_by().values('monthly_entry_id', 'currency').annotate(total=Sum('amount')))
    for row in products:
        balances[row['monthly_entry_id']][row['currency']] += row['total']
    for row in payments:
        balances[row['monthly_entry_id']][row['currency']] -= row['total']
    return balances


def clean_employee(data, current=None):
    def pick(key, fallback):
        return data[key] if key in data else fallback

    return {
        'first_name': parse_text(pick('first_name', current.first_name if current else None), 'First name', 100, required=True),
        'last_name': parse_text(pick('last_name', current.last_name if current else None), 'Last name', 100, required=True),
        'position': parse_text(pick('position', current.position if current else ''), 'Position', 100),
        'phone': parse_text(pick('phone', current.phone if current else ''), 'Phone', 20),
        'email': parse_email(pick('email', current.email if current else '')),
        'is_active': parse_bool(data.get('is_active'), 'Active flag', default=current.is_active if current else True),
    }


class MonthlyView(LoginRequiredMixin, TemplateView):
    template_name = 'monthly.html'

    def get_context_data(self, **kwargs):
        kwargs['employees'] = Employee.objects.filter(is_active=True)
        return super().get_context_data(**kwargs)


class EmployeeListAPIView(ApiView):
    """API endpoint to list employees"""

    def get(self, request):
        return JsonResponse({
            'employees': [
                {
                    'id': e.id,
                    'first_name': e.first_name,
                    'last_name': e.last_name,
                    'position': e.position,
                    'is_active': e.is_active,
                }
                for e in Employee.objects.all()
            ]
        })


class CreateEmployeeAPIView(ApiView):
    """API endpoint to create an employee"""

    def post(self, request):
        employee = Employee.objects.create(**clean_employee(load_json(request)))
        return JsonResponse({'success': True, 'id': employee.id})


class EmployeeDetailAPIView(ApiView):
    """API endpoint to get or update an employee"""

    def get(self, request, employee_id):
        e = get_or_404(Employee, employee_id, 'Employee')
        return JsonResponse({
            'id': e.id,
            'first_name': e.first_name,
            'last_name': e.last_name,
            'position': e.position,
            'phone': e.phone,
            'email': e.email,
            'is_active': e.is_active,
        })

    def post(self, request, employee_id):
        employee = get_or_404(Employee, employee_id, 'Employee')
        for field, value in clean_employee(load_json(request), current=employee).items():
            setattr(employee, field, value)
        employee.save()
        return JsonResponse({'success': True, 'id': employee.id})


class DeleteEmployeeAPIView(ApiView):
    """API endpoint to delete an employee (and, by cascade, their monthly records)"""

    def post(self, request, employee_id):
        get_or_404(Employee, employee_id, 'Employee').delete()
        return JsonResponse({'success': True, 'message': 'Employee deleted successfully'})


class MonthlyEntryListAPIView(ApiView):
    """API endpoint to list monthly entries"""

    def get(self, request):
        entries = MonthlyEntry.objects.select_related('employee')
        if request.GET.get('employee_id'):
            entries = entries.filter(employee_id=parse_int(request.GET['employee_id'], 'Employee', minimum=1))
        entries = list(entries)
        balances = entry_balances([e.id for e in entries])
        return JsonResponse({
            'entries': [
                {
                    'id': e.id,
                    'employee_id': e.employee_id,
                    'employee_name': str(e.employee),
                    'month': e.month.isoformat(),
                    **{f'balance_{curr}': money_str(balances[e.id][curr]) for curr in CURRENCIES},
                }
                for e in entries
            ]
        })


class CreateMonthlyEntryAPIView(ApiView):
    """API endpoint to create a monthly entry (defaults to the current month)"""

    def post(self, request):
        data = load_json(request)
        employee = get_or_404(Employee, parse_int(data.get('employee_id'), 'Employee', minimum=1), 'Employee')
        month = parse_date(data['month'], 'Month', allow_future=True).replace(day=1) if data.get('month') else current_month_start()
        try:
            with db_transaction.atomic():
                entry, created = MonthlyEntry.objects.get_or_create(employee=employee, month=month)
        except IntegrityError:
            created = False
        if not created:
            raise APIError('Monthly entry already exists for this employee and month.')
        return JsonResponse({'success': True, 'id': entry.id})


class MonthlyEntryDetailAPIView(ApiView):
    """API endpoint to get monthly entry details with products and payments"""

    def get(self, request, entry_id):
        entry = get_or_404(MonthlyEntry.objects.select_related('employee'), entry_id, 'Monthly entry')
        balances = entry_balances([entry.id])[entry.id]
        return JsonResponse({
            'id': entry.id,
            'employee_id': entry.employee_id,
            'employee_name': str(entry.employee),
            'month': entry.month.isoformat(),
            **{f'balance_{curr}': money_str(balances[curr]) for curr in CURRENCIES},
            'products': [
                {
                    'id': p.id,
                    'product_name': p.product_name,
                    'quantity': str(p.quantity),
                    'unit_type': p.unit_type,
                    'price_per_unit': str(p.price_per_unit),
                    'currency': p.currency,
                    'total_amount': str(p.total_amount),
                }
                for p in entry.products.all()
            ],
            'payments': [
                {
                    'id': p.id,
                    'amount': str(p.amount),
                    'currency': p.currency,
                    'description': p.description,
                    'payment_date': p.payment_date.isoformat(),
                }
                for p in entry.payments.all()
            ],
        })


class AddProductAPIView(ApiView):
    """API endpoint to add a product to a monthly entry"""

    def post(self, request):
        data = load_json(request)
        entry = get_or_404(MonthlyEntry, parse_int(data.get('entry_id'), 'Entry', minimum=1), 'Monthly entry')
        quantity = parse_decimal(data.get('quantity'), 'Quantity', maximum=MAX_TOTAL)
        price = parse_decimal(data.get('price_per_unit'), 'Price per unit', maximum=MAX_UNIT_PRICE)
        total = (quantity * price).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
        if total > MAX_TOTAL:
            raise APIError('Total amount is too large.')
        product = MonthlyProduct.objects.create(
            monthly_entry=entry,
            product_name=parse_text(data.get('product_name'), 'Product name', 255, required=True),
            quantity=quantity,
            unit_type=parse_choice(data.get('unit_type', MonthlyProduct.UNIT_DONA), UNIT_TYPES, 'Unit type'),
            price_per_unit=price,
            currency=parse_choice(data.get('currency', 'uzs'), CURRENCIES, 'Currency'),
            total_amount=total,
        )
        return JsonResponse({'success': True, 'id': product.id})


class DeleteProductAPIView(ApiView):
    """API endpoint to delete a product"""

    def post(self, request, product_id):
        get_or_404(MonthlyProduct, product_id, 'Product').delete()
        return JsonResponse({'success': True})


class AddPaymentAPIView(ApiView):
    """API endpoint to record a payment against a monthly entry"""

    def post(self, request):
        data = load_json(request)
        entry = get_or_404(MonthlyEntry, parse_int(data.get('entry_id'), 'Entry', minimum=1), 'Monthly entry')
        payment = MonthlyPayment.objects.create(
            monthly_entry=entry,
            amount=parse_decimal(data.get('amount'), 'Amount', maximum=MAX_TOTAL),
            currency=parse_choice(data.get('currency', 'uzs'), CURRENCIES, 'Currency'),
            description=parse_text(data.get('description'), 'Description', 255),
            payment_date=parse_date(data.get('payment_date'), 'Payment date'),
        )
        return JsonResponse({'success': True, 'id': payment.id})


class DeletePaymentAPIView(ApiView):
    """API endpoint to delete a payment"""

    def post(self, request, payment_id):
        get_or_404(MonthlyPayment, payment_id, 'Payment').delete()
        return JsonResponse({'success': True})


# --------------------------------------------------------------------------- #
# Warehouse
# --------------------------------------------------------------------------- #

def apply_stock_change(item, movement_type, quantity, quantity_kg):
    """Apply a movement to the item's running stock; refuse to go below zero."""
    sign = 1 if movement_type == WarehouseMovement.IN else -1
    new_quantity = item.quantity + sign * quantity
    new_kg = item.quantity_kg + sign * quantity_kg
    if new_quantity < 0 or new_kg < 0:
        raise APIError(
            f'Not enough stock for "{item.name}": {item.quantity} pcs / {item.quantity_kg} kg available.')
    item.quantity, item.quantity_kg = new_quantity, new_kg
    item.save()


class WarehouseView(LoginRequiredMixin, TemplateView):
    """View for warehouse inventory management"""
    template_name = 'warehouse.html'

    def get_context_data(self, **kwargs):
        movements = WarehouseMovement.objects.select_related('item').order_by('-created_at')
        filtered = movements

        item_id = self.request.GET.get('item_id')
        if item_id and item_id.isdigit():
            filtered = filtered.filter(item_id=int(item_id))
        movement_type = self.request.GET.get('type')
        if movement_type in MOVEMENT_TYPES:
            filtered = filtered.filter(type=movement_type)

        total = filtered.count()
        capped = total > WAREHOUSE_MOVEMENT_PAGE_SIZE and self.request.GET.get('all') != '1'
        if capped:
            filtered = filtered[:WAREHOUSE_MOVEMENT_PAGE_SIZE]
        show_all = self.request.GET.copy()
        show_all['all'] = '1'

        kwargs['items'] = WarehouseItem.objects.all()
        kwargs['filtered_movements'] = filtered
        kwargs['movements_total'] = total
        kwargs['movements_capped'] = capped
        kwargs['movements_shown'] = WAREHOUSE_MOVEMENT_PAGE_SIZE
        kwargs['show_all_query'] = show_all.urlencode()
        return super().get_context_data(**kwargs)


class WarehouseItemListAPIView(ApiView):
    """Get all warehouse items with their movements (staff only)"""

    staff_methods = ('GET',)

    def get(self, request):
        items = WarehouseItem.objects.prefetch_related('movements')
        return JsonResponse({
            'items': [
                {
                    'id': item.id,
                    'name': item.name,
                    'description': item.description or '',
                    'quantity': item.quantity,
                    'quantity_kg': str(item.quantity_kg),
                    'movements': [
                        {
                            'id': m.id,
                            'type': m.type,
                            'quantity': m.quantity,
                            'quantity_kg': str(m.quantity_kg),
                            'date': m.date.isoformat(),
                            'description': m.description or '',
                        }
                        for m in sorted(item.movements.all(), key=lambda m: m.date, reverse=True)
                    ],
                }
                for item in items
            ]
        })


class CreateWarehouseItemAPIView(FormOrApiView):
    """Create a new warehouse item; any starting stock is booked as an 'in' movement"""

    def post(self, request):
        data = load_data(request)
        name = parse_text(data.get('name'), 'Name', 255, required=True)
        description = parse_text(data.get('description'), 'Description', 2000)
        quantity = parse_int(data.get('quantity'), 'Quantity', minimum=0, maximum=MAX_STOCK_QTY, default=0)
        quantity_kg = parse_decimal(data.get('quantity_kg'), 'Quantity (kg)', minimum=Decimal('0'),
                                    maximum=MAX_STOCK_KG, default=Decimal('0'))

        with db_transaction.atomic():
            item = WarehouseItem.objects.create(name=name, description=description)
            if quantity > 0 or quantity_kg > 0:
                WarehouseMovement.objects.create(
                    item=item, type=WarehouseMovement.IN, quantity=quantity, quantity_kg=quantity_kg,
                    date=timezone.localdate(), description='Initial stock')
                apply_stock_change(item, WarehouseMovement.IN, quantity, quantity_kg)

        if wants_json(request):
            return JsonResponse({'success': True, 'id': item.id, 'name': item.name, 'quantity': item.quantity})
        return redirect('warehouse')


class WarehouseMovementAPIView(FormOrApiView):
    """Add a warehouse movement (in/out)"""

    def post(self, request):
        data = load_data(request)
        movement_type = parse_choice(data.get('type'), MOVEMENT_TYPES, 'Type')
        quantity = parse_int(data.get('quantity'), 'Quantity', minimum=0, maximum=MAX_STOCK_QTY, default=0)
        quantity_kg = parse_decimal(data.get('quantity_kg'), 'Quantity (kg)', minimum=Decimal('0'),
                                    maximum=MAX_STOCK_KG, default=Decimal('0'))
        if quantity <= 0 and quantity_kg <= 0:
            raise APIError('Enter a quantity or a weight greater than zero.')
        date = parse_date(data.get('date') or timezone.localdate().isoformat(), 'Date')
        description = parse_text(data.get('description'), 'Notes', 255)
        item_id = parse_int(data.get('item_id'), 'Item', minimum=1)

        with db_transaction.atomic():
            item = get_or_404(WarehouseItem.objects.select_for_update(), item_id, 'Item')
            apply_stock_change(item, movement_type, quantity, quantity_kg)
            movement = WarehouseMovement.objects.create(
                item=item, type=movement_type, quantity=quantity, quantity_kg=quantity_kg,
                date=date, description=description)

        if wants_json(request):
            return JsonResponse({'success': True, 'id': movement.id, 'new_quantity': item.quantity})
        return redirect('warehouse')


class DeleteWarehouseMovementAPIView(FormOrApiView):
    """Delete a warehouse movement and reverse its effect on the stock"""

    def post(self, request, movement_id):
        with db_transaction.atomic():
            movement = get_or_404(WarehouseMovement.objects.select_related('item'), movement_id, 'Movement')
            item = WarehouseItem.objects.select_for_update().get(pk=movement.item_id)
            reverse = WarehouseMovement.OUT if movement.type == WarehouseMovement.IN else WarehouseMovement.IN
            try:
                apply_stock_change(item, reverse, movement.quantity, movement.quantity_kg)
            except APIError:
                raise APIError('This movement cannot be deleted because the stock it added has already been used.')
            movement.delete()

        if wants_json(request):
            return JsonResponse({'success': True, 'new_quantity': item.quantity})
        return redirect('warehouse')


class DeleteWarehouseItemAPIView(FormOrApiView):
    """Delete a warehouse item"""

    def post(self, request, item_id):
        get_or_404(WarehouseItem, item_id, 'Item').delete()
        if wants_json(request):
            return JsonResponse({'success': True, 'message': 'Item deleted successfully'})
        return redirect('warehouse')


class UpdateWarehouseItemAPIView(ApiView):
    """Rename / re-describe a warehouse item (stock only changes through movements)"""

    def post(self, request, item_id):
        item = get_or_404(WarehouseItem, item_id, 'Item')
        data = load_json(request)
        if 'quantity' in data or 'quantity_kg' in data:
            raise APIError('Stock can only be changed by adding a stock movement.')
        if 'name' in data:
            item.name = parse_text(data['name'], 'Name', 255, required=True)
        if 'description' in data:
            item.description = parse_text(data['description'], 'Description', 2000)
        item.save()
        return JsonResponse({
            'success': True,
            'item': {
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'quantity': item.quantity,
                'quantity_kg': str(item.quantity_kg),
            },
        })
