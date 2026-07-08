from django.db import migrations


def delete_class9_masterclass(apps, schema_editor):
    MasterClass = apps.get_model("quality", "MasterClass")
    ClassMaster = apps.get_model("quality", "ClassMaster")
    class9 = ClassMaster.objects.filter(class_no=9).first()
    if class9:
        MasterClass.objects.filter(class_master=class9).delete()


def recreate_class9_masterclass(apps, schema_editor):
    MasterClass = apps.get_model("quality", "MasterClass")
    ClassMaster = apps.get_model("quality", "ClassMaster")
    class9 = ClassMaster.objects.filter(class_no=9).first()
    if class9:
        for mc in MasterClass.objects.filter(class_master=class9):
            mc.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("quality", "0016_specialinspectionclass9"),
    ]

    operations = [
        migrations.RunPython(delete_class9_masterclass, recreate_class9_masterclass),
    ]
