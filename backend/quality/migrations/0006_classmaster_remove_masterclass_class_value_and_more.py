import django.db.models.deletion
from django.db import migrations, models


CLASS_MASTER_DATA = [
    (1, "自動機"),
    (2, "半自動機"),
    (3, "セッター"),
    (4, "プレス"),
    (5, "二次加工"),
    (6, "製品検査(1)"),
    (7, "製品検査(2)"),
    (8, "手動"),
]


def seed_class_master(apps, schema_editor):
    ClassMaster = apps.get_model("quality", "ClassMaster")
    for class_no, class_name in CLASS_MASTER_DATA:
        ClassMaster.objects.update_or_create(class_no=class_no, defaults={"class_name": class_name})


def migrate_class_values(apps, schema_editor):
    ClassMaster = apps.get_model("quality", "ClassMaster")
    MasterClass = apps.get_model("quality", "MasterClass")
    cm_map = {cm.class_no: cm for cm in ClassMaster.objects.all()}
    for mc in MasterClass.objects.iterator():
        old_val = getattr(mc, "class_value", None)
        if old_val is not None and old_val in cm_map:
            MasterClass.objects.filter(pk=mc.pk).update(class_master=cm_map[old_val])


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0005_appsetting_erp_path'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassMaster',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('class_no', models.PositiveSmallIntegerField(unique=True)),
                ('class_name', models.CharField(max_length=64)),
            ],
        ),
        migrations.RunPython(seed_class_master, migrations.RunPython.noop),
        migrations.AddField(
            model_name='masterclass',
            name='class_master',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='master_classes', to='quality.classmaster'),
        ),
        migrations.RunPython(migrate_class_values, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='masterclass',
            name='class_value',
        ),
    ]
