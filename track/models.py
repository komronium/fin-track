from django.db import models
from django.utils import timezone


class PaymentMethod(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "payment_methods"
        ordering = ["name"]


class Transaction(models.Model):
    TYPE_INCOME = "income"
    TYPE_EXPENSE = "expense"
    TYPE_CHOICES = [
        (TYPE_INCOME, "Income"),
        (TYPE_EXPENSE, "Expense"),
    ]

    CURRENCY_UZS = "uzs"
    CURRENCY_USD = "usd"
    CURRENCY_AFN = "afn"
    CURRENCY_CHOICES = [
        (CURRENCY_UZS, "UZS"),
        (CURRENCY_USD, "USD"),
        (CURRENCY_AFN, "AFN"),
    ]

    type = models.CharField(max_length=100, choices=TYPE_CHOICES)
    currency = models.CharField(
        max_length=10, choices=CURRENCY_CHOICES, default=CURRENCY_UZS
    )
    method = models.ForeignKey(
        PaymentMethod, on_delete=models.PROTECT, related_name="transactions"
    )
    amount = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)

    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "transactions"
        ordering = ["-date"]


class Employee(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    position = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    hired_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "employees"
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class MonthlyEntry(models.Model):
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="monthly_entries"
    )
    month = models.DateField()  # First day of the month
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "monthly_entries"
        ordering = ["-month", "employee"]
        unique_together = ("employee", "month")

    def __str__(self):
        return f"{self.employee} - {self.month.strftime('%B %Y')}"


class MonthlyProduct(models.Model):
    monthly_entry = models.ForeignKey(
        MonthlyEntry, on_delete=models.CASCADE, related_name="products"
    )
    product_name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "monthly_products"
        ordering = ["monthly_entry", "-created_at"]

    def __str__(self):
        return f"{self.product_name} x{self.quantity}"


class MonthlyPayment(models.Model):
    monthly_entry = models.ForeignKey(
        MonthlyEntry, on_delete=models.CASCADE, related_name="payments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    payment_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "monthly_payments"
        ordering = ["-payment_date", "-created_at"]

    def __str__(self):
        return f"Payment {self.amount} on {self.payment_date}"


class WarehouseItem(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField(default=0)
    quantity_kg = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Quantity (kg)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "warehouse_items"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (qty: {self.quantity})"


class WarehouseMovement(models.Model):
    IN = "in"
    OUT = "out"
    MOVEMENT_CHOICES = [
        (IN, "Items In"),
        (OUT, "Items Out"),
    ]

    item = models.ForeignKey(
        WarehouseItem, on_delete=models.CASCADE, related_name="movements"
    )
    type = models.CharField(max_length=10, choices=MOVEMENT_CHOICES)
    quantity = models.PositiveIntegerField()
    quantity_kg = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Quantity (kg)"
    )
    date = models.DateField()
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "warehouse_movements"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.item.name} - {self.type}: {self.quantity}"
