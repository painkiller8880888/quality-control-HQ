from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0025_allow_explicit_class8_for_ocr")]

    operations = [
        migrations.AddField(
            model_name="appsetting",
            name="inspection_folder_priorities",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="inspectionfile",
            name="file_created",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="inspectionfile",
            name="priority",
            field=models.IntegerField(default=0),
        ),
    ]
