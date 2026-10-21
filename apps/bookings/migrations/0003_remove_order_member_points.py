from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0002_order_addon_amount_order_coupon_code_and_more"),
    ]

    operations = [
        migrations.RemoveField(model_name="order", name="member_discount"),
        migrations.RemoveField(model_name="order", name="points_discount"),
        migrations.RemoveField(model_name="order", name="points_redeemed"),
    ]
