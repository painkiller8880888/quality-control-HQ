from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quality', '0010_inspection_session_history_and_history_file_path'),
    ]

    operations = [
        migrations.AddField(
            model_name='machineassignment',
            name='assignment_class',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='machine',
                    name='machine_class',
                    field=models.PositiveSmallIntegerField(blank=True, null=True),
                ),
            ],
            database_operations=[],
        ),
    ]
