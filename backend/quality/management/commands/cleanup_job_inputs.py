import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from quality.models import Job


class Command(BaseCommand):
    help = "Delete completed job input directories after the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=max(options["days"], 0))
        root = Path(settings.JOB_INPUT_ROOT).resolve()
        removed = 0
        jobs = Job.objects.filter(
            status__in=[Job.Status.SUCCEEDED, Job.Status.FAILED],
            finished_at__lt=cutoff,
        )
        for job in jobs:
            for value in job.request_payload.values():
                if not isinstance(value, dict) or not value.get("path"):
                    continue
                path = Path(value["path"]).resolve()
                if root in path.parents and path.parent.exists():
                    shutil.rmtree(path.parent, ignore_errors=True)
                    removed += 1
                    break
        self.stdout.write(f"removed {removed} job input directories")
