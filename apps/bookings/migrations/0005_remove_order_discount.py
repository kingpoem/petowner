from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0004_remove_order_coupon_fields"),
    ]

    operations = [
        migrations.RemoveField(model_name="order", name="discount"),
    ]
