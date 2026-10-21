from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hospitality", "0005_remove_vaccine"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Medication",
        ),
    ]
