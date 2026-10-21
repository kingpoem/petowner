from django.db import migrations, models


def merge_allergies(apps, schema_editor):
    Pet = apps.get_model("pets", "Pet")
    for pet in Pet.objects.exclude(allergies="").iterator():
        allergy = (pet.allergies or "").strip()
        if not allergy:
            continue
        diet = (pet.diet_notes or "").strip()
        if allergy in diet:
            combined = diet
        elif diet:
            combined = f"{diet}；{allergy}"
        else:
            combined = allergy
        pet.diet_notes = combined[:300]
        pet.save(update_fields=["diet_notes"])


class Migration(migrations.Migration):

    dependencies = [
        ("pets", "0002_remove_vaccine"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pet",
            name="diet_notes",
            field=models.CharField(
                blank=True,
                help_text="可选。如：每日两餐每餐 150g 狗粮；对鸡肉过敏",
                max_length=300,
                verbose_name="饮食习惯",
            ),
        ),
        migrations.RunPython(merge_allergies, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="pet",
            name="allergies",
        ),
    ]
