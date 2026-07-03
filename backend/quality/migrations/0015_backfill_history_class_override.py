from django.db import migrations
from django.db.models import Exists, OuterRef


def backfill_class_override(apps, schema_editor):
    History = apps.get_model("quality", "History")
    InspectionTarget = apps.get_model("quality", "InspectionTarget")
    InspectionSession = apps.get_model("quality", "InspectionSession")

    class9_targets = InspectionTarget.objects.filter(
        class_override=9,
        master__isnull=False,
        session__status="open",
    ).select_related("session", "master")

    for target in class9_targets:
        History.objects.filter(
            date=target.session.target_date,
            master=target.master,
        ).update(class_override=9)


def reverse_backfill(apps, schema_editor):
    History = apps.get_model("quality", "History")
    InspectionTarget = apps.get_model("quality", "InspectionTarget")
    InspectionSession = apps.get_model("quality", "InspectionSession")

    class9_targets = InspectionTarget.objects.filter(
        class_override=9,
        master__isnull=False,
        session__status="open",
    ).select_related("session", "master")

    for target in class9_targets:
        History.objects.filter(
            date=target.session.target_date,
            master=target.master,
            class_override=9,
        ).update(class_override=None)


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0014_remove_history_unique_history_date_master_slot_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_class_override, reverse_backfill),
    ]
