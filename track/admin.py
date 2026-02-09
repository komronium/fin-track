from django.contrib import admin

from track.models import PaymentMethod, Transaction, Employee


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    pass


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id','description','amount','type','method','date')
    list_filter = ('type','method')
    search_fields = ('description','category')
