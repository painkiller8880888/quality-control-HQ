import json
import time
from pathlib import Path

import psutil
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from quality.models import Job


class Command(BaseCommand):
    help = "Record CPU, memory, DB connections, locks, and job wait/run timing."

    def add_arguments(self, parser):
        parser.add_argument("job_id")
        parser.add_argument("--interval-seconds", type=float, default=5.0)
        parser.add_argument("--output", required=True)

    def database_metrics(self):
        if connection.vendor != "postgresql":
            return {"connections": None, "waiting_locks": None, "granted_locks": None}
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
            connections = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT
                    count(*) FILTER (WHERE NOT granted),
                    count(*) FILTER (WHERE granted)
                FROM pg_locks
                WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
                """
            )
            waiting_locks, granted_locks = cursor.fetchone()
        return {
            "connections": connections,
            "waiting_locks": waiting_locks,
            "granted_locks": granted_locks,
        }

    def handle(self, *args, **options):
        try:
            job = Job.objects.get(pk=options["job_id"])
        except Job.DoesNotExist as exc:
            raise CommandError("Job not found.") from exc
        samples = []
        interval = max(options["interval_seconds"], 0.25)
        while True:
            job.refresh_from_db()
            memory = psutil.virtual_memory()
            samples.append(
                {
                    "sampled_at": timezone.now().isoformat(),
                    "status": job.status,
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "memory_used_bytes": memory.used,
                    "memory_percent": memory.percent,
                    **self.database_metrics(),
                }
            )
            if job.status in [Job.Status.SUCCEEDED, Job.Status.FAILED]:
                break
            time.sleep(interval)
        evidence = {
            "job_id": job.job_id,
            "job_type": job.job_type,
            "resource_key": job.resource_key,
            "created_at": job.available_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "attempt_count": job.attempt_count,
            "final_status": job.status,
            "samples": samples,
        }
        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.stdout.write(str(output))
