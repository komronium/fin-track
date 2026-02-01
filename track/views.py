from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import json
from datetime import datetime

from track.models import Transaction, PaymentMethod


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard.html'

    def get_transactions(self):
        return Transaction.objects.all()

    def set_balance(self, transaction, kwargs):
        kwargs['incomes'] = transaction.filter(
            type=Transaction.TYPE_INCOME
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        kwargs['expenses'] = transaction.filter(
            type=Transaction.TYPE_EXPENSE
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        kwargs['balance'] = kwargs['incomes'] - kwargs['expenses']

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
        
        data = {
            'transactions': [
                {
                    'id': t.id,
                    'type': t.type,
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
        
        incomes = transactions.filter(
            type=Transaction.TYPE_INCOME
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        
        expenses = transactions.filter(
            type=Transaction.TYPE_EXPENSE
        ).aggregate(total=Coalesce(Sum('amount'), 0))['total']
        
        balance = incomes - expenses
        
        return JsonResponse({
            'incomes': incomes,
            'expenses': expenses,
            'balance': balance,
        })


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
            
            transaction = Transaction.objects.create(
                type=data.get('type'),
                amount=int(data.get('amount')),
                description=data.get('description', ''),
                date=data.get('date'),
                method_id=int(data.get('method')),
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
