from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0024_inspectiontarget_registration_route")]

    operations = [
        migrations.RemoveConstraint(
            model_name="inspectiontarget",
            name="inspection_target_route_class_check",
        ),
        migrations.AddConstraint(
            model_name="inspectiontarget",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(master__isnull=True)
                    | models.Q(registration_route="legacy")
                    | models.Q(registration_route="special", class_override=9)
                    | models.Q(registration_route="ocr", class_override__in=[1, 2, 3, 4, 5, 8])
                    | models.Q(registration_route="factory_map", class_override__range=(1, 5))
                    | models.Q(registration_route__in=["excel", "manual_code"], class_override__in=[6, 7])
                ),
                name="inspection_target_route_class_check",
            ),
        ),
    ]
