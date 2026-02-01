from django.db import models


class PaymentMethod(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        db_table = 'payment_methods'
        ordering = ['name']


class Transaction(models.Model):

    TYPE_INCOME = 'income'
    TYPE_EXPENSE = 'expense'
    TYPE_CHOICES = [
        (TYPE_INCOME, 'Income'),
        (TYPE_EXPENSE, 'Expense'),
    ]

    type = models.CharField(max_length=100, choices=TYPE_CHOICES)
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name='transactions')
    amount = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)

    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transactions'
        ordering = ['-date']
