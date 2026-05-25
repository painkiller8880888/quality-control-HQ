from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="master",
            name="node_type",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
