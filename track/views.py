from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
from datetime import datetime
from decimal import Decimal

from track.models import Transaction, PaymentMethod, Employee, MonthlyEntry, MonthlyProduct, MonthlyPayment, WarehouseItem, WarehouseMovement


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_transactions(self):
        return Transaction.objects.all()

    def set_balance(self, transactions, kwargs):
        """Stats per currency: UZS, USD, AFN"""
        for curr in ['uzs', 'usd', 'afn']:
            qs = transactions.filter(currency=curr)
            inc = qs.filter(type=Transaction.TYPE_INCOME).aggregate(
                total=Coalesce(Sum('amount'), 0)
            )['total']
            exp = qs.filter(type=Transaction.TYPE_EXPENSE).aggregate(
                total=Coalesce(Sum('amount'), 0)
            )['total']
            kwargs[f'incomes_{curr}'] = inc
            kwargs[f'expenses_{curr}'] = exp
            kwargs[f'balance_{curr}'] = inc - exp

    def get_context_data(self, **kwargs):
        transactions = self.get_transactions()
        payment_methods = PaymentMethod.objects.all()
        kwargs['transactions'] = transactions
        kwargs['payment_methods'] = payment_methods

        self.set_balance(transactions, kwargs)
        return super().get_context_data(**kwargs)


class UsersView(LoginRequiredMixin, TemplateView):
    template_name = 'users.html'

    def get_context_data(self, **kwargs):
        users = User.objects.all()
        kwargs['users'] = users
        return super().get_context_data(**kwargs)


class TransactionListAPIView(LoginRequiredMixin, View):
    """API endpoint to list transactions with filters"""
    
    def get(self, request):
        transactions = Transaction.objects.all()
        
        # Filter by type
        transaction_type = request.GET.get('type')
        if transaction_type:
            transactions = transactions.filter(type=transaction_type)
        
        # Filter by method
        method_id = request.GET.get('method')
        if method_id:
            transactions = transactions.filter(method_id=method_id)
        
        # Filter by date range
        date_from = request.GET.get('date_from')
        if date_from:
            transactions = transactions.filter(date__gte=date_from)
        
        date_to = request.GET.get('date_to')
        if date_to:
            transactions = transactions.filter(date__lte=date_to)
        
        # Filter by currency
        currency = request.GET.get('currency')
        if currency and currency in ('uzs', 'usd', 'afn'):
            transactions = transactions.filter(currency=currency)
        
        data = {
            'transactions': [
                {
                    'id': t.id,
                    'type': t.type,
                    'currency': t.currency,
                    'amount': t.amount,
                    'description': t.description,
                    'date': t.date.isoformat(),
                    'method_id': t.method_id,
                    'method_name': t.method.name,
                }
                for t in transactions
            ]
        }
        
        return JsonResponse(data)


class StatsAPIView(LoginRequiredMixin, View):
    """API endpoint to get stats with filters"""
    
    def get(self, request):
        transactions = Transaction.objects.all()
        
        # Filter by type
        transaction_type = request.GET.get('type')
        if transaction_type:
            transactions = transactions.filter(type=transaction_type)
        
        # Filter by method
        method_id = request.GET.get('method')
        if method_id:
            transactions = transactions.filter(method_id=method_id)
        
        # Filter by date range
        date_from = request.GET.get('date_from')
        if date_from:
            transactions = transactions.filter(date__gte=date_from)
        
        date_to = request.GET.get('date_to')
        if date_to:
            transactions = transactions.filter(date__lte=date_to)
        
        # Filter by currency
        currency = request.GET.get('currency')
        if currency and currency in ('uzs', 'usd', 'afn'):
            transactions = transactions.filter(currency=currency)
        
        result = {}
        for curr in ['uzs', 'usd', 'afn']:
            qs = transactions.filter(currency=curr)
            inc = qs.filter(type=Transaction.TYPE_INCOME).aggregate(
                total=Coalesce(Sum('amount'), 0)
            )['total']
            exp = qs.filter(type=Transaction.TYPE_EXPENSE).aggregate(
                total=Coalesce(Sum('amount'), 0)
            )['total']
            result[f'incomes_{curr}'] = inc
            result[f'expenses_{curr}'] = exp
            result[f'balance_{curr}'] = inc - exp
        
        return JsonResponse(result)


def check_staff_permission(user):
    """Check if user has staff permission for write operations"""
    if not user.is_staff:
        return JsonResponse({
            'success': False,
            'error': 'Permission denied. Only staff users can perform this action.',
        }, status=403)
    return None


@method_decorator(csrf_exempt, name='dispatch')
class CreateTransactionAPIView(LoginRequiredMixin, View):
    """API endpoint to create a transaction"""
    
    def post(self, request):
        # Check staff permission
        perm_check = check_staff_permission(request.user)
        if perm_check:
            return perm_check
            
        try:
            data = json.loads(request.body)
            
            currency = data.get('currency', 'uzs')
            if currency not in ('uzs', 'usd', 'afn'):
                currency = 'uzs'
            transaction = Transaction.objects.create(
                type=data.get('type'),
                amount=int(data.get('amount')),
                description=data.get('description', ''),
                date=data.get('date'),
                method_id=int(data.get('method')),
                currency=currency,
            )
            
            return JsonResponse({
                'success': True,
                'id': transaction.id,
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class TransactionDetailAPIView(LoginRequiredMixin, View):
    """API endpoint to get, update, or delete a transaction"""
    
    def get(self, request, transaction_id):
        try:
            transaction = Transaction.objects.get(id=transaction_id)
            return JsonResponse({
                'id': transaction.id,
                'type': transaction.type,
                'currency': transaction.currency,
                'amount': transaction.amount,
                'description': transaction.description,
                'date': transaction.date.isoformat(),
                'method': transaction.method_id,
            })
        except Transaction.DoesNotExist:
            return JsonResponse({
                'error': 'Transaction not found'
            }, status=404)
    
    def post(self, request, transaction_id):
        # Check staff permission
        perm_check = check_staff_permission(request.user)
        if perm_check:
            return perm_check
            
        try:
            data = json.loads(request.body)
            transaction = Transaction.objects.get(id=transaction_id)
            
            transaction.type = data.get('type', transaction.type)
            transaction.amount = int(data.get('amount', transaction.amount))
            transaction.description = data.get('description', transaction.description)
            transaction.date = data.get('date', transaction.date)
            transaction.method_id = int(data.get('method', transaction.method_id))
            curr = data.get('currency')
            if curr in ('uzs', 'usd', 'afn'):
                transaction.currency = curr
            transaction.save()
            
            return JsonResponse({
                'success': True,
                'id': transaction.id,
            })
        except Transaction.DoesNotExist:
            return JsonResponse({
                'error': 'Transaction not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class DeleteTransactionAPIView(LoginRequiredMixin, View):
    """API endpoint to delete a transaction"""
    
    def post(self, request, transaction_id):
        # Check staff permission
        perm_check = check_staff_permission(request.user)
        if perm_check:
            return perm_check
            
        try:
            transaction = Transaction.objects.get(id=transaction_id)
            transaction.delete()
            return JsonResponse({
                'success': True,
            })
        except Transaction.DoesNotExist:
            return JsonResponse({
                'error': 'Transaction not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


class UsersListAPIView(LoginRequiredMixin, View):
    """API endpoint to list users"""
    
    def get(self, request):
        users = User.objects.all()
        data = {
            'users': [
                {
                    'id': u.id,
                    'username': u.username,
                    'first_name': u.first_name,
                    'last_name': u.last_name,
                    'email': u.email,
                    'is_active': u.is_active,
                    'is_staff': u.is_staff,
                }
                for u in users
            ]
        }
        return JsonResponse(data)


@method_decorator(csrf_exempt, name='dispatch')
class CreateUserAPIView(LoginRequiredMixin, View):
    """API endpoint to create a user"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Check if username already exists
            if User.objects.filter(username=data.get('username')).exists():
                return JsonResponse({
                    'success': False,
                    'error': 'Username already exists',
                }, status=400)
            
            user = User.objects.create_user(
                username=data.get('username'),
                password=data.get('password'),
                first_name=data.get('first_name', ''),
                last_name=data.get('last_name', ''),
                email=data.get('email', ''),
                is_staff=data.get('is_staff', False),
                is_active=data.get('is_active', True),
            )
            
            return JsonResponse({
                'success': True,
                'id': user.id,
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class UserDetailAPIView(LoginRequiredMixin, View):
    """API endpoint to get, update, or delete a user"""
    
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            return JsonResponse({
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'is_active': user.is_active,
                'is_staff': user.is_staff,
            })
        except User.DoesNotExist:
            return JsonResponse({
                'error': 'User not found'
            }, status=404)
    
    def post(self, request, user_id):
        try:
            data = json.loads(request.body)
            user = User.objects.get(id=user_id)
            
            user.first_name = data.get('first_name', user.first_name)
            user.last_name = data.get('last_name', user.last_name)
            user.email = data.get('email', user.email)
            user.is_staff = data.get('is_staff', user.is_staff)
            user.is_active = data.get('is_active', user.is_active)
            
            # Update password if provided
            password = data.get('password')
            if password:
                user.set_password(password)
            
            user.save()
            
            return JsonResponse({
                'success': True,
                'id': user.id,
            })
        except User.DoesNotExist:
            return JsonResponse({
                'error': 'User not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class DeleteUserAPIView(LoginRequiredMixin, View):
    """API endpoint to delete a user"""
    
    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.delete()
            return JsonResponse({
                'success': True,
            })
        except User.DoesNotExist:
            return JsonResponse({
                'error': 'User not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


class MonthlyView(LoginRequiredMixin, TemplateView):
    template_name = 'monthly.html'

    def get_context_data(self, **kwargs):
        from django.utils import timezone
        
        employees = Employee.objects.filter(is_active=True)
        kwargs['employees'] = employees
        
        # Get or create monthly entry for current month
        today = timezone.now().date()
        first_day = today.replace(day=1)
        
        monthly_entries = {}
        for emp in employees:
            entry, created = MonthlyEntry.objects.get_or_create(
                employee=emp,
                month=first_day
            )
            monthly_entries[emp.id] = entry
        
        kwargs['monthly_entries'] = monthly_entries
        return super().get_context_data(**kwargs)


class EmployeeListAPIView(LoginRequiredMixin, View):
    """API endpoint to list employees"""
    
    def get(self, request):
        employees = Employee.objects.all()
        data = {
            'employees': [
                {
                    'id': e.id,
                    'first_name': e.first_name,
                    'last_name': e.last_name,
                    'position': e.position,
                    'is_active': e.is_active,
                }
                for e in employees
            ]
        }
        return JsonResponse(data)


@method_decorator(csrf_exempt, name='dispatch')
class CreateEmployeeAPIView(LoginRequiredMixin, View):
    """API endpoint to create an employee"""
    
    def post(self, request):
        try:
            # Check if it's form data or JSON
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                data = json.loads(request.body)
            else:
                # Form data
                data = request.POST.dict()
            
            employee = Employee.objects.create(
                first_name=data.get('first_name'),
                last_name=data.get('last_name'),
                position=data.get('position', ''),
                phone=data.get('phone', ''),
                email=data.get('email', ''),
                is_active=data.get('is_active', True),
            )
            
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': True,
                    'id': employee.id,
                })
            return redirect('monthly')
        except Exception as e:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                }, status=400)
            return redirect('monthly')


@method_decorator(csrf_exempt, name='dispatch')
class EmployeeDetailAPIView(LoginRequiredMixin, View):
    """API endpoint to get, update, or delete an employee"""
    
    def get(self, request, employee_id):
        try:
            employee = Employee.objects.get(id=employee_id)
            return JsonResponse({
                'id': employee.id,
                'first_name': employee.first_name,
                'last_name': employee.last_name,
                'position': employee.position,
                'phone': employee.phone,
                'email': employee.email,
                'is_active': employee.is_active,
            })
        except Employee.DoesNotExist:
            return JsonResponse({
                'error': 'Employee not found'
            }, status=404)
    
    def post(self, request, employee_id):
        try:
            data = json.loads(request.body)
            employee = Employee.objects.get(id=employee_id)
            
            employee.first_name = data.get('first_name', employee.first_name)
            employee.last_name = data.get('last_name', employee.last_name)
            employee.position = data.get('position', employee.position)
            employee.phone = data.get('phone', employee.phone)
            employee.email = data.get('email', employee.email)
            employee.is_active = data.get('is_active', employee.is_active)
            employee.save()
            
            return JsonResponse({
                'success': True,
                'id': employee.id,
            })
        except Employee.DoesNotExist:
            return JsonResponse({
                'error': 'Employee not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


class DeleteEmployeeAPIView(LoginRequiredMixin, View):
    """API endpoint to delete an employee"""
    
    def post(self, request, employee_id):
        if not request.user.is_staff:
            return JsonResponse({'error': 'Not authorized'}, status=403)
        
        try:
            employee = Employee.objects.get(id=employee_id)
            employee.delete()
            
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': True,
                    'message': 'Employee deleted successfully',
                })
            return redirect('monthly')
        except Employee.DoesNotExist:
            return JsonResponse({'error': 'Employee not found'}, status=404)
        except Exception as e:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                }, status=400)
            return redirect('monthly')


class MonthlyEntryListAPIView(LoginRequiredMixin, View):
    """API endpoint to list monthly entries"""
    
    def get(self, request):
        employee_id = request.GET.get('employee_id')
        
        entries = MonthlyEntry.objects.all()
        if employee_id:
            entries = entries.filter(employee_id=employee_id)
        
        data = {
            'entries': [
                {
                    'id': e.id,
                    'employee_id': e.employee_id,
                    'employee_name': str(e.employee),
                    'month': e.month.isoformat(),
                    'balance': str(e.balance),
                }
                for e in entries
            ]
        }
        return JsonResponse(data)


@method_decorator(csrf_exempt, name='dispatch')
class CreateMonthlyEntryAPIView(LoginRequiredMixin, View):
    """API endpoint to create a monthly entry"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            employee_id = int(data.get('employee_id'))
            month = data.get('month')
            
            # Check if entry already exists
            existing_entry = MonthlyEntry.objects.filter(
                employee_id=employee_id,
                month=month
            ).first()
            
            if existing_entry:
                return JsonResponse({
                    'success': False,
                    'error': 'Monthly entry already exists for this employee and month',
                }, status=400)
            
            entry = MonthlyEntry.objects.create(
                employee_id=employee_id,
                month=month,
                balance=Decimal('0')
            )
            
            return JsonResponse({
                'success': True,
                'id': entry.id,
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class MonthlyEntryDetailAPIView(LoginRequiredMixin, View):
    """API endpoint to get monthly entry details with products and payments"""
    
    def get(self, request, entry_id):
        try:
            entry = MonthlyEntry.objects.get(id=entry_id)
            
            products = entry.products.all()
            payments = entry.payments.all()
            
            # Calculate totals
            products_total = sum(p.total_amount for p in products)
            payments_total = sum(p.amount for p in payments)
            
            return JsonResponse({
                'id': entry.id,
                'employee_id': entry.employee_id,
                'employee_name': str(entry.employee),
                'month': entry.month.isoformat(),
                'balance': str(entry.balance),
                'products': [
                    {
                        'id': p.id,
                        'product_name': p.product_name,
                        'quantity': p.quantity,
                        'price_per_unit': str(p.price_per_unit),
                        'total_amount': str(p.total_amount),
                    }
                    for p in products
                ],
                'payments': [
                    {
                        'id': p.id,
                        'amount': str(p.amount),
                        'description': p.description,
                        'payment_date': p.payment_date.isoformat(),
                    }
                    for p in payments
                ],
                'products_total': str(products_total),
                'payments_total': str(payments_total),
            })
        except MonthlyEntry.DoesNotExist:
            return JsonResponse({
                'error': 'Monthly entry not found'
            }, status=404)


@method_decorator(csrf_exempt, name='dispatch')
class AddProductAPIView(LoginRequiredMixin, View):
    """API endpoint to add a product to monthly entry"""
    
    def post(self, request):
        try:
            # Check if it's form data or JSON
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                data = json.loads(request.body)
            else:
                # Form data
                data = request.POST.dict()
            
            entry_id = int(data.get('entry_id'))
            product_name = data.get('product_name')
            quantity = int(data.get('quantity'))
            price_per_unit = Decimal(data.get('price_per_unit'))
            
            entry = MonthlyEntry.objects.get(id=entry_id)
            
            total_amount = quantity * price_per_unit
            
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
            
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': True,
                    'id': product.id,
                    'new_balance': str(entry.balance),
                })
            return redirect(f'/monthly/?emp_id={entry.employee_id}')
        except Exception as e:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                }, status=400)
            return redirect('monthly')


@method_decorator(csrf_exempt, name='dispatch')
class DeleteProductAPIView(LoginRequiredMixin, View):
    """API endpoint to delete a product"""
    
    def post(self, request, product_id):
        try:
            product = MonthlyProduct.objects.get(id=product_id)
            entry = product.monthly_entry
            
            # Subtract from balance
            entry.balance -= product.total_amount
            entry.save()
            
            product.delete()
            
            return JsonResponse({
                'success': True,
                'new_balance': str(entry.balance),
            })
        except MonthlyProduct.DoesNotExist:
            return JsonResponse({
                'error': 'Product not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class AddPaymentAPIView(LoginRequiredMixin, View):
    """API endpoint to add a payment (deduct from balance)"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            entry_id = int(data.get('entry_id'))
            amount = Decimal(data.get('amount'))
            description = data.get('description', '')
            payment_date = data.get('payment_date')
            
            entry = MonthlyEntry.objects.get(id=entry_id)
            
            payment = MonthlyPayment.objects.create(
                monthly_entry=entry,
                amount=amount,
                description=description,
                payment_date=payment_date
            )
            
            # Deduct from balance
            entry.balance -= amount
            entry.save()
            
            return JsonResponse({
                'success': True,
                'id': payment.id,
                'new_balance': str(entry.balance),
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class DeletePaymentAPIView(LoginRequiredMixin, View):
    """API endpoint to delete a payment"""
    
    def post(self, request, payment_id):
        try:
            payment = MonthlyPayment.objects.get(id=payment_id)
            entry = payment.monthly_entry
            
            # Add back to balance
            entry.balance += payment.amount
            entry.save()
            
            payment.delete()
            
            return JsonResponse({
                'success': True,
                'new_balance': str(entry.balance),
            })
        except MonthlyPayment.DoesNotExist:
            return JsonResponse({
                'error': 'Payment not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


class WarehouseView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """View for warehouse inventory management"""
    template_name = 'warehouse.html'
    
    def test_func(self):
        return self.request.user.is_staff
    
    def get_context_data(self, **kwargs):
        items = WarehouseItem.objects.all()
        movements = WarehouseMovement.objects.all().select_related('item').order_by('-created_at')
        
        # Apply filters
        item_id = self.request.GET.get('item_id')
        movement_type = self.request.GET.get('type')
        
        filtered_movements = movements
        
        if item_id:
            filtered_movements = filtered_movements.filter(item_id=item_id)
        
        if movement_type:
            filtered_movements = filtered_movements.filter(type=movement_type)
        
        kwargs['items'] = items
        kwargs['movements'] = movements
        kwargs['filtered_movements'] = filtered_movements
        return super().get_context_data(**kwargs)


@method_decorator(csrf_exempt, name='dispatch')
class WarehouseItemListAPIView(LoginRequiredMixin, View):
    """Get all warehouse items with their movements"""
    
    def get(self, request):
        if not request.user.is_staff:
            return JsonResponse({'error': 'Not authorized'}, status=403)
        
        items = WarehouseItem.objects.all()
        data = {
            'items': []
        }
        
        for item in items:
            movements = WarehouseMovement.objects.filter(item=item).order_by('-date')
            movements_list = []
            for m in movements:
                movements_list.append({
                    'id': m.id,
                    'type': m.type,
                    'quantity': m.quantity,
                    'quantity_kg': str(m.quantity_kg),
                    'date': m.date.isoformat() if hasattr(m.date, 'isoformat') else str(m.date),
                    'description': m.description or ''
                })
            
            data['items'].append({
                'id': item.id,
                'name': item.name,
                'description': item.description or '',
                'quantity': item.quantity,
                'quantity_kg': str(item.quantity_kg),
                'movements': movements_list
            })
        
        return JsonResponse(data)


@method_decorator(csrf_exempt, name='dispatch')
class CreateWarehouseItemAPIView(LoginRequiredMixin, View):
    """Create a new warehouse item"""
    
    def post(self, request):
        if not request.user.is_staff:
            if request.content_type == 'application/json':
                return JsonResponse({'error': 'Not authorized'}, status=403)
            return redirect('warehouse')
        
        try:
            # Check if it's form data or JSON
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                data = json.loads(request.body)
                name = data.get('name', '').strip()
                quantity = int(data.get('quantity', 0))
                quantity_kg = Decimal(str(data.get('quantity_kg', 0)))
                description = data.get('description', '').strip()
            else:
                # Form data
                name = request.POST.get('name', '').strip()
                quantity = int(request.POST.get('quantity', 0))
                quantity_kg = Decimal(str(request.POST.get('quantity_kg', 0) or 0))
                description = request.POST.get('description', '').strip()
            
            if not name:
                if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                    return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)
                return redirect('warehouse')
            
            item = WarehouseItem.objects.create(
                name=name,
                quantity=quantity,
                quantity_kg=quantity_kg,
                description=description
            )
            
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': True,
                    'id': item.id,
                    'name': item.name,
                    'quantity': item.quantity,
                })
            return redirect('warehouse')
        except Exception as e:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                }, status=400)
            return redirect('warehouse')


@method_decorator(csrf_exempt, name='dispatch')
class WarehouseMovementAPIView(LoginRequiredMixin, View):
    """Add a warehouse movement (in/out)"""
    
    def post(self, request):
        if not request.user.is_staff:
            return JsonResponse({'error': 'Not authorized'}, status=403)
        
        try:
            # Check if it's form data or JSON
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                data = json.loads(request.body)
                item_id = int(data.get('item_id'))
                movement_type = data.get('type')  # 'in' or 'out'
                quantity = int(data.get('quantity', 0))
                quantity_kg = Decimal(str(data.get('quantity_kg', 0) or 0))
                date = data.get('date', datetime.now().date())
                description = data.get('description', '').strip()
            else:
                # Form data
                item_id = int(request.POST.get('item_id'))
                movement_type = request.POST.get('type')
                quantity = int(request.POST.get('quantity', 0))
                quantity_kg = Decimal(str(request.POST.get('quantity_kg', 0) or 0))
                date = request.POST.get('date', str(datetime.now().date()))
                description = request.POST.get('description', '').strip()
            
            if not item_id or not movement_type or (quantity <= 0 and quantity_kg <= 0):
                if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                    return JsonResponse({'success': False, 'error': 'Invalid data'}, status=400)
                return redirect('warehouse')
            
            if movement_type not in ['in', 'out']:
                if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                    return JsonResponse({'success': False, 'error': 'Type must be "in" or "out"'}, status=400)
                return redirect('warehouse')
            
            item = WarehouseItem.objects.get(id=item_id)
            
            # Create movement record
            movement = WarehouseMovement.objects.create(
                item=item,
                type=movement_type,
                quantity=quantity,
                quantity_kg=quantity_kg,
                date=date,
                description=description
            )
            
            # Update item quantity and quantity_kg
            if movement_type == 'in':
                item.quantity += quantity
                item.quantity_kg += quantity_kg
            else:
                item.quantity = max(0, item.quantity - quantity)
                item.quantity_kg = max(Decimal('0'), item.quantity_kg - quantity_kg)
            
            item.save()
            
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': True,
                    'id': movement.id,
                    'new_quantity': item.quantity,
                })
            return redirect('warehouse')
        except WarehouseItem.DoesNotExist:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({'error': 'Item not found'}, status=404)
            return redirect('warehouse')
        except Exception as e:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                }, status=400)
            return redirect('warehouse')


@method_decorator(csrf_exempt, name='dispatch')
class DeleteWarehouseMovementAPIView(LoginRequiredMixin, View):
    """Delete a warehouse movement"""
    
    def post(self, request, movement_id):
        if not request.user.is_staff:
            return JsonResponse({'error': 'Not authorized'}, status=403)
        
        try:
            movement = WarehouseMovement.objects.get(id=movement_id)
            item = movement.item
            
            # Reverse the quantity and quantity_kg update
            if movement.type == 'in':
                item.quantity -= movement.quantity
                item.quantity_kg -= movement.quantity_kg
            else:
                item.quantity += movement.quantity
                item.quantity_kg += movement.quantity_kg
            
            item.quantity = max(0, item.quantity)
            item.quantity_kg = max(Decimal('0'), item.quantity_kg)
            item.save()
            
            movement.delete()
            
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': True,
                    'new_quantity': item.quantity,
                })
            return redirect('warehouse')
        except WarehouseMovement.DoesNotExist:
            return JsonResponse({'error': 'Movement not found'}, status=404)
        except Exception as e:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                }, status=400)
            return redirect('warehouse')


class DeleteWarehouseItemAPIView(LoginRequiredMixin, View):
    """Delete a warehouse item"""
    
    def post(self, request, item_id):
        if not request.user.is_staff:
            return JsonResponse({'error': 'Not authorized'}, status=403)
        
        try:
            item = WarehouseItem.objects.get(id=item_id)
            item.delete()
            
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': True,
                    'message': 'Item deleted successfully',
                })
            return redirect('warehouse')
        except WarehouseItem.DoesNotExist:
            return JsonResponse({'error': 'Item not found'}, status=404)
        except Exception as e:
            if request.content_type == 'application/json' or 'application/json' in request.META.get('CONTENT_TYPE', ''):
                return JsonResponse({
                    'success': False,
                    'error': str(e),
                }, status=400)
            return redirect('warehouse')
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


class UpdateWarehouseItemAPIView(LoginRequiredMixin, View):
    """Update a warehouse item"""
    
    def post(self, request, item_id):
        if not request.user.is_staff:
            return JsonResponse({'error': 'Not authorized'}, status=403)
        
        try:
            item = WarehouseItem.objects.get(id=item_id)
            data = json.loads(request.body)
            
            if 'name' in data:
                item.name = data['name']
            if 'description' in data:
                item.description = data['description']
            if 'quantity' in data:
                item.quantity = int(data['quantity'])
            if 'quantity_kg' in data:
                item.quantity_kg = Decimal(str(data['quantity_kg']))
            
            item.save()
            
            return JsonResponse({
                'success': True,
                'item': {
                    'id': item.id,
                    'name': item.name,
                    'description': item.description,
                    'quantity': item.quantity,
                    'quantity_kg': str(item.quantity_kg),
                }
            })
        except WarehouseItem.DoesNotExist:
            return JsonResponse({'error': 'Item not found'}, status=404)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e),
            }, status=400)


