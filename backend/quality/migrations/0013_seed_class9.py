from django.db import migrations


def seed_class9(apps, schema_editor):
    ClassMaster = apps.get_model("quality", "ClassMaster")
    ClassMaster.objects.get_or_create(class_no=9, defaults={"class_name": "特殊検査"})


def reverse_seed_class9(apps, schema_editor):
    ClassMaster = apps.get_model("quality", "ClassMaster")
    ClassMaster.objects.filter(class_no=9).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0012_remove_inspectiontarget_unique_target_per_session_code_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_class9, reverse_seed_class9),
    ]
