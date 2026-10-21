from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("hospitality", "0003_delete_coupon"),
    ]

    operations = [
        migrations.DeleteModel(name="WaitlistEntry"),
    ]
