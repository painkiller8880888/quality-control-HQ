from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("quality", "0021_remove_history_unique_history_date_master_slot_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(blank=True, null=True, upload_to="avatars/"),
        ),
    ]
