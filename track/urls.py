from django.urls import path

from .views import (
    DashboardView,
    UsersView,
    TransactionListAPIView,
    StatsAPIView,
    CreateTransactionAPIView,
    TransactionDetailAPIView,
    DeleteTransactionAPIView,
    UsersListAPIView,
    CreateUserAPIView,
    UserDetailAPIView,
    DeleteUserAPIView,
)

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('users/', UsersView.as_view(), name='users'),
    
    # Transaction API endpoints
    path('api/transactions/', TransactionListAPIView.as_view(), name='api_transactions'),
    path('api/stats/', StatsAPIView.as_view(), name='api_stats'),
    path('api/transaction/create/', CreateTransactionAPIView.as_view(), name='api_create_transaction'),
    path('api/transaction/<int:transaction_id>/', TransactionDetailAPIView.as_view(), name='api_transaction_detail'),
    path('api/transaction/<int:transaction_id>/update/', TransactionDetailAPIView.as_view(), name='api_update_transaction'),
    path('api/transaction/<int:transaction_id>/delete/', DeleteTransactionAPIView.as_view(), name='api_delete_transaction'),
    
    # Users API endpoints
    path('api/users/', UsersListAPIView.as_view(), name='api_users'),
    path('api/user/create/', CreateUserAPIView.as_view(), name='api_create_user'),
    path('api/user/<int:user_id>/', UserDetailAPIView.as_view(), name='api_user_detail'),
    path('api/user/<int:user_id>/update/', UserDetailAPIView.as_view(), name='api_update_user'),
    path('api/user/<int:user_id>/delete/', DeleteUserAPIView.as_view(), name='api_delete_user'),
]
