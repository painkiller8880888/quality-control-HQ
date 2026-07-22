from django.core.management.base import BaseCommand

from quality.job_queue import execute_claimed_job


class Command(BaseCommand):
    help = "Execute one job that has already been claimed by a worker supervisor."

    def add_arguments(self, parser):
        parser.add_argument("job_id")
        parser.add_argument("--worker-id", required=True)

    def handle(self, *args, **options):
        job = execute_claimed_job(options["job_id"], options["worker_id"])
        if job is None:
            self.stdout.write("The claimed job was already executing or completed; skipped.")
