from django import forms
from .models import Transaction, PaymentMethod
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth.models import User


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['amount', 'date', 'description', 'type', 'method']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'input-field'}),
            'description': forms.TextInput(attrs={'class': 'input-field', 'placeholder': 'Description'}),
            'amount': forms.NumberInput(attrs={'class': 'input-field', 'step': '1'}),
            'type': forms.Select(attrs={'class': 'input-field'}),
            'method': forms.Select(attrs={'class': 'input-field'}),
        }


class AdminUserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'is_staff', 'is_active')


class AdminUserChangeForm(UserChangeForm):
    password = None

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'is_staff', 'is_active')
