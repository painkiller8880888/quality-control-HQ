from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0028_job_execution_token")]

    operations = [
        migrations.AddField(
            model_name="job",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
    ]
