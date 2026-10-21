from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hospitality", "0006_delete_medication"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="caretask",
            name="staff",
        ),
        migrations.DeleteModel(
            name="StaffMember",
        ),
        migrations.DeleteModel(
            name="StoreNotice",
        ),
    ]
