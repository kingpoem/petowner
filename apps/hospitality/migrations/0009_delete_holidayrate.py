from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hospitality", "0008_remove_caretask_and_supply"),
    ]

    operations = [
        migrations.DeleteModel(
            name="HolidayRate",
        ),
    ]
