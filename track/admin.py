from django.contrib import admin

from track.models import PaymentMethod, Transaction, Employee, WarehouseItem, WarehouseMovement


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    pass

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'description', 'amount', 'currency', 'type', 'method', 'date')
    list_filter = ('type', 'currency', 'method')
    search_fields = ('description',)


@admin.register(WarehouseItem)
class WarehouseItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'quantity', 'quantity_kg', 'description')
    list_filter = ()
    search_fields = ('name', 'description')


@admin.register(WarehouseMovement)
class WarehouseMovementAdmin(admin.ModelAdmin):
    list_display = ('item', 'type', 'quantity', 'quantity_kg', 'date', 'description')
    list_filter = ('type',)
    search_fields = ('item__name', 'description')

