from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("hospitality", "0002_remove_member_points"),
    ]

    operations = [
        migrations.DeleteModel(name="Coupon"),
    ]
