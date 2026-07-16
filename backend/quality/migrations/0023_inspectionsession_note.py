from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0022_user_avatar")]

    operations = [
        migrations.AddField(
            model_name="inspectionsession",
            name="note",
            field=models.TextField(blank=True, default=""),
        ),
    ]
