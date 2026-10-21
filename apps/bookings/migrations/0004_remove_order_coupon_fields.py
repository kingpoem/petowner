from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0003_remove_order_member_points"),
    ]

    operations = [
        migrations.RemoveField(model_name="order", name="coupon_code"),
        migrations.RemoveField(model_name="order", name="coupon_discount"),
    ]
