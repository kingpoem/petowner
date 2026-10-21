import apps.images
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("pets", "0003_merge_allergies_into_diet_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="owner",
            name="avatar",
            field=apps.images.OptimizedImageField(
                blank=True,
                max_side=640,
                upload_to="avatars/%Y/%m/",
                verbose_name="头像",
            ),
        ),
    ]
