from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("pets", "0004_owner_avatar"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="pet",
            name="deworm_expiry",
        ),
    ]
