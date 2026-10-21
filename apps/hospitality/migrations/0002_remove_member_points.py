from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("hospitality", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(name="PointLedger"),
        migrations.DeleteModel(name="MemberAccount"),
    ]
