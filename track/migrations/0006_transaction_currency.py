# Generated manually for currency support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('track', '0005_alter_monthlyentry_balance_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='currency',
            field=models.CharField(
                choices=[('uzs', 'UZS'), ('usd', 'USD'), ('afn', 'AFN')],
                default='uzs',
                max_length=10,
            ),
        ),
    ]
