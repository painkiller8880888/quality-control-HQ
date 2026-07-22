import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from django.core.management.base import BaseCommand

from quality.job_queue import (
    claim_next_job,
    heartbeat,
    recover_expired_jobs,
    reschedule_or_fail_interrupted_job,
)


class Command(BaseCommand):
    help = "Run the persistent PostgreSQL-backed job worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll-seconds", type=float, default=2.0)
        parser.add_argument("--worker-id", default="")

    def handle(self, *args, **options):
        worker_id = options["worker_id"] or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        self.stdout.write(f"job worker started: {worker_id}")
        manage_py = Path(__file__).resolve().parents[3] / "manage.py"
        while True:
            recover_expired_jobs()
            job = claim_next_job(worker_id)
            if job:
                command = [
                    sys.executable,
                    str(manage_py),
                    "execute_claimed_job",
                    job.job_id,
                    "--worker-id",
                    worker_id,
                ]
                with heartbeat(job.job_id, worker_id):
                    try:
                        result = subprocess.run(
                            command,
                            timeout=job.timeout_seconds,
                            check=False,
                        )
                    except subprocess.TimeoutExpired:
                        reschedule_or_fail_interrupted_job(
                            job,
                            f"実行timeout ({job.timeout_seconds}秒) 後の再試行待ち",
                            "JobTimeout",
                        )
                    else:
                        if result.returncode != 0:
                            reschedule_or_fail_interrupted_job(
                                job,
                                "Job実行プロセスが異常終了しました。",
                                "JobProcessFailed",
                            )
                self.stdout.write(f"processed {job.job_id}")
            if options["once"]:
                return
            if job is None:
                time.sleep(max(options["poll_seconds"], 0.1))
