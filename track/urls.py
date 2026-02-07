from django.urls import path

from .views import (
    DashboardView,
    UsersView,
    MonthlyView,
    WarehouseView,
    TransactionListAPIView,
    StatsAPIView,
    CreateTransactionAPIView,
    TransactionDetailAPIView,
    DeleteTransactionAPIView,
    UsersListAPIView,
    CreateUserAPIView,
    UserDetailAPIView,
    DeleteUserAPIView,
    EmployeeListAPIView,
    CreateEmployeeAPIView,
    EmployeeDetailAPIView,
    DeleteEmployeeAPIView,
    MonthlyEntryListAPIView,
    CreateMonthlyEntryAPIView,
    MonthlyEntryDetailAPIView,
    AddProductAPIView,
    DeleteProductAPIView,
    AddPaymentAPIView,
    DeletePaymentAPIView,
    WarehouseItemListAPIView,
    CreateWarehouseItemAPIView,
    WarehouseMovementAPIView,
    DeleteWarehouseMovementAPIView,
    DeleteWarehouseItemAPIView,
    UpdateWarehouseItemAPIView,
)

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('users/', UsersView.as_view(), name='users'),
    path('monthly/', MonthlyView.as_view(), name='monthly'),
    path('warehouse/', WarehouseView.as_view(), name='warehouse'),
    
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
    
    # Employee API endpoints
    path('api/employees/', EmployeeListAPIView.as_view(), name='api_employees'),
    path('api/employee/create/', CreateEmployeeAPIView.as_view(), name='api_create_employee'),
    path('api/employee/<int:employee_id>/', EmployeeDetailAPIView.as_view(), name='api_employee_detail'),
    path('api/employee/<int:employee_id>/delete/', DeleteEmployeeAPIView.as_view(), name='api_delete_employee'),
    
    # Monthly API endpoints
    path('api/monthly/entries/', MonthlyEntryListAPIView.as_view(), name='api_monthly_entries'),
    path('api/monthly/entry/create/', CreateMonthlyEntryAPIView.as_view(), name='api_create_monthly_entry'),
    path('api/monthly/entry/<int:entry_id>/', MonthlyEntryDetailAPIView.as_view(), name='api_monthly_entry_detail'),
    path('api/monthly/product/add/', AddProductAPIView.as_view(), name='api_add_product'),
    path('api/monthly/product/<int:product_id>/delete/', DeleteProductAPIView.as_view(), name='api_delete_product'),
    path('api/monthly/payment/add/', AddPaymentAPIView.as_view(), name='api_add_payment'),
    path('api/monthly/payment/<int:payment_id>/delete/', DeletePaymentAPIView.as_view(), name='api_delete_payment'),
    
    # Warehouse API endpoints
    path('api/warehouse/items/', WarehouseItemListAPIView.as_view(), name='api_warehouse_items'),
    path('api/warehouse/item/create/', CreateWarehouseItemAPIView.as_view(), name='api_warehouse_create_item'),
    path('api/warehouse/item/<int:item_id>/update/', UpdateWarehouseItemAPIView.as_view(), name='api_warehouse_update_item'),
    path('api/warehouse/item/<int:item_id>/delete/', DeleteWarehouseItemAPIView.as_view(), name='api_warehouse_delete_item'),
    path('api/warehouse/entry/add/', WarehouseMovementAPIView.as_view(), name='api_warehouse_add_movement'),
    path('api/warehouse/entry/<int:movement_id>/delete/', DeleteWarehouseMovementAPIView.as_view(), name='api_warehouse_delete_movement'),
]
