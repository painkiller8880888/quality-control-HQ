from django.db import migrations, models
import django.db.models.deletion


def backfill_registration_route(apps, schema_editor):
    InspectionTarget = apps.get_model("quality", "InspectionTarget")
    InspectionTarget.objects.filter(class_override=9).update(registration_route="special")


class Migration(migrations.Migration):
    dependencies = [("quality", "0023_inspectionsession_note")]

    operations = [
        migrations.AddField(
            model_name="inspectiontarget",
            name="registration_route",
            field=models.CharField(
                choices=[
                    ("ocr", "OCR"),
                    ("excel", "Excel"),
                    ("manual_code", "Manual code"),
                    ("factory_map", "Factory map"),
                    ("special", "Special"),
                    ("legacy", "Legacy"),
                ],
                default="legacy",
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_registration_route, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="inspectiontarget",
            constraint=models.CheckConstraint(
                condition=models.Q(class_override__isnull=True) | models.Q(class_override__range=(1, 9)),
                name="inspection_target_class_range_check",
            ),
        ),
        migrations.AddConstraint(
            model_name="inspectiontarget",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(master__isnull=True)
                    | models.Q(registration_route="legacy")
                    | models.Q(registration_route="special", class_override=9)
                    | models.Q(registration_route__in=["ocr", "factory_map"], class_override__range=(1, 5))
                    | models.Q(registration_route__in=["excel", "manual_code"], class_override__in=[6, 7])
                ),
                name="inspection_target_route_class_check",
            ),
        ),
    ]
