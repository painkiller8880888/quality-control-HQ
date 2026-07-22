from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("quality", "0026_appsetting_inspection_folder_priorities_and_inspectionfile_selection_fields")]

    operations = [
        migrations.AddField(
            model_name="job",
            name="attempt_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="job",
            name="available_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="job",
            name="blocked_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="job",
            name="depends_on",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="dependent_jobs",
                to="quality.job",
            ),
        ),
        migrations.AddField(
            model_name="job",
            name="heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="job",
            name="idempotency_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="job",
            name="lease_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="job",
            name="resource_key",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="job",
            name="timeout_seconds",
            field=models.PositiveIntegerField(default=900),
        ),
        migrations.AddField(
            model_name="job",
            name="worker_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                condition=(
                    models.Q(status__in=["queued", "running"])
                    & ~models.Q(resource_key="")
                    & ~models.Q(idempotency_key="")
                ),
                fields=("resource_key", "idempotency_key"),
                name="active_job_idempotency_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["status", "available_at", "job_id"], name="quality_job_status_20f666_idx"),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["resource_key", "status"], name="quality_job_resourc_e86681_idx"),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["lease_until", "status"], name="quality_job_lease_u_99dd18_idx"),
        ),
    ]
