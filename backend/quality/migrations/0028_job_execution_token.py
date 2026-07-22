from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0027_job_queue_fields")]

    operations = [
        migrations.AddField(
            model_name="job",
            name="execution_token",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
