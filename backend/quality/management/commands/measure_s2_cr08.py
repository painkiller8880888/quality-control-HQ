from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from quality.job_queue import (
    MASTER_RESOURCE,
    claim_resource_advisory_lock,
    enqueue_job,
    execute_claimed_job,
)
from quality.models import Job
from quality.s2_cr08_measurement import (
    build_evidence,
    verify_evidence_ordering,
    write_evidence,
    TransactionObserver,
    _connection_pid,
    _sha256,
)


_LABELS = ("a", "b")
ERROR_FIXTURE_ABORT = "ERROR_FIXTURE_ABORT"


def _claim_specific_job(job, worker_id):
    now = timezone.now()
    try:
        with transaction.atomic():
            locked = Job.objects.select_for_update().get(pk=job.pk)
            claim_resource_advisory_lock(MASTER_RESOURCE)
            if locked.status != Job.Status.QUEUED or locked.available_at > now:
                return None
            if MASTER_RESOURCE and Job.objects.filter(
                resource_key=MASTER_RESOURCE,
                status=Job.Status.RUNNING,
            ).exclude(pk=job.pk).exists():
                return None
            locked.status = Job.Status.RUNNING
            locked.started_at = now
            locked.attempt_count += 1
            locked.worker_id = worker_id
            locked.heartbeat_at = now
            locked.lease_until = now + timezone.timedelta(
                seconds=settings.JOB_LEASE_SECONDS
            )
            locked.blocked_reason = ""
            locked.save(update_fields=[
                "status", "started_at", "attempt_count", "worker_id",
                "heartbeat_at", "lease_until", "blocked_reason", "updated_at",
            ])
            job.refresh_from_db()
            return job
    except Job.DoesNotExist:
        return None


def _report_job(label, job):
    if job is None:
        return ""
    wid = job.worker_id or ""
    safe_wid = _sha256(wid) if wid else ""
    items = [
        f"{label}.job_id={job.job_id}",
        f"status={job.status}",
        f"worker_id_hash={safe_wid}",
        f"attempt_count={job.attempt_count}",
    ]
    return "  ".join(items)


def _finalize_job(j, status, finished_at=None, error_message="", exception_type=""):
    if j is None:
        return
    try:
        j.refresh_from_db()
        had_token = bool(j.execution_token)
        j.execution_token = ""
        if j.status in (Job.Status.QUEUED, Job.Status.RUNNING):
            j.status = status
            j.finished_at = finished_at or timezone.now()
            j.worker_id = ""
            j.heartbeat_at = None
            j.lease_until = None
            if error_message:
                j.error_message = error_message
            j.blocked_reason = ""
            if status == Job.Status.FAILED and exception_type:
                j.result = {
                    "status": "failed",
                    "error_message": error_message or "",
                    "exception_type": exception_type,
                }
            j.save(update_fields=[
                "status", "finished_at", "updated_at",
                "execution_token", "worker_id", "heartbeat_at", "lease_until",
                "error_message", "blocked_reason", "result",
            ])
        elif had_token:
            j.save(update_fields=["execution_token", "updated_at"])
    except Job.DoesNotExist:
        pass


def _require_observer_section(obs, label):
    if obs is None:
        raise CommandError(f"Observer {label} missing. Evidence not written.")
    if not obs.transaction_completed:
        raise CommandError(
            f"Observer {label} did not detect transaction completion. "
            "Evidence not written."
        )
    for field in ("backend_hash", "xact_start", "end_lower_bound", "end_upper_bound"):
        if getattr(obs, field, None) is None:
            raise CommandError(
                f"Observer {label} missing required field '{field}'. "
                "Evidence not written."
            )


class Command(BaseCommand):
    help = (
        "Measure S2-CR-08 transaction timing indicators via inline queue_smoke jobs. "
        "This is a smoke-test fixture: it runs queue_smoke operations synchronously on "
        "this connection, NOT via external worker/child backend. Does not support "
        "canonical master_update observation."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument(
            "--poll-seconds", type=float, default=2.0,
            help="Poll interval for transaction observer (seconds)",
        )

    def handle(self, *args, **options):
        output = Path(options["output"])
        poll_seconds = max(options["poll_seconds"], 0.5)

        if connection.vendor != "postgresql":
            raise CommandError("This command requires PostgreSQL.")

        if output.exists() and any(output.iterdir()):
            raise CommandError(
                f"Output directory already exists and is not empty: {output}"
            )

        active = Job.objects.filter(
            status__in=[Job.Status.QUEUED, Job.Status.RUNNING]
        ).count()
        if active != 0:
            raise CommandError(
                f"Cannot proceed: {active} active job(s) in queue. "
                "All jobs must be completed before measurement."
            )

        job_a = job_b = None
        observers = {}
        error = None
        pid = _connection_pid()
        worker_id = f"measure-{timezone.now().strftime('%Y%m%d%H%M%S')}"

        def _measure_job(label, job):
            obs = TransactionObserver(poll_seconds=poll_seconds, target_pid=pid)
            observers[label] = obs
            obs.start()
            claimed = _claim_specific_job(job, worker_id)
            if claimed is None:
                raise CommandError(f"Failed to claim Job {label}: {job.job_id}")
            obs.start_watching()
            try:
                armed = obs.wait_watching_armed(timeout=poll_seconds + 5)
            except RuntimeError as e:
                raise CommandError(
                    f"Observer {label} thread failed before arming"
                ) from e
            if not armed:
                raise CommandError(
                    f"Observer {label} did not arm watching phase within timeout."
                )
            result = execute_claimed_job(job.job_id, worker_id)
            if result is None or result.status != Job.Status.SUCCEEDED:
                raise CommandError(f"Job {label} did not succeed.")
            obs.stop()
            return obs, result

        try:
            job_a, a_created = enqueue_job(
                Job.JobType.MASTER_UPDATE,
                {
                    "operation": "queue_smoke",
                    "sleep_seconds": 5,
                    "retry_safe": True,
                },
                resource_key=MASTER_RESOURCE,
                idempotency_key=f"s2-cr08-a-{timezone.now().timestamp()}",
            )
            if not a_created:
                raise CommandError(
                    "Job A already existed (deduplicated). Cannot measure."
                )
            self.stdout.write(f"Job A created: {job_a.job_id}")

            job_b, b_created = enqueue_job(
                Job.JobType.MASTER_UPDATE,
                {
                    "operation": "queue_smoke",
                    "sleep_seconds": 3,
                    "retry_safe": True,
                },
                resource_key=MASTER_RESOURCE,
                idempotency_key=f"s2-cr08-b-{timezone.now().timestamp()}",
                depends_on=job_a,
            )
            if not b_created:
                raise CommandError(
                    "Job B already existed (deduplicated). Cannot measure."
                )
            self.stdout.write(f"Job B created: {job_b.job_id}")

            obs_a, _ = _measure_job("a", job_a)

            updated = Job.objects.filter(
                pk=job_b.pk,
                depends_on_id=job_a.pk,
                status=Job.Status.QUEUED,
                resource_key=MASTER_RESOURCE,
            ).update(blocked_reason="", available_at=timezone.now())
            if updated != 1:
                raise CommandError("Job B not in expected dependency state.")
            job_b.refresh_from_db()

            obs_b, _ = _measure_job("b", job_b)
        except Exception as e:
            error = e if isinstance(e, CommandError) else CommandError(str(e))
        finally:
            for obs in observers.values():
                try:
                    obs.stop()
                except RuntimeError:
                    pass
            if error:
                now = timezone.now()
                for label in _LABELS:
                    j = locals().get(f"job_{label}")
                    _finalize_job(
                        j, Job.Status.FAILED, finished_at=now,
                        error_message=ERROR_FIXTURE_ABORT,
                        exception_type="S2Cr08FixtureAbort",
                    )
            if job_a is not None:
                try:
                    job_a.refresh_from_db()
                except Job.DoesNotExist:
                    pass
            if job_b is not None:
                try:
                    job_b.refresh_from_db()
                except Job.DoesNotExist:
                    pass
            self.stderr.write(_report_job("A", job_a))
            self.stderr.write(_report_job("B", job_b))
            final_active = Job.objects.filter(
                status__in=[Job.Status.QUEUED, Job.Status.RUNNING]
            ).count()
            self.stderr.write(f"final_active={final_active}")

        if error:
            raise error

        final_active = Job.objects.filter(
            status__in=[Job.Status.QUEUED, Job.Status.RUNNING]
        ).count()
        if final_active != 0:
            raise CommandError(
                f"Postcondition failed: {final_active} active job(s) remain."
            )

        obs_a = observers.get("a")
        obs_b = observers.get("b")
        _require_observer_section(obs_a, "a")
        _require_observer_section(obs_b, "b")

        evidence = build_evidence(
            job_a=job_a,
            job_b=job_b,
            transaction_observer_a=obs_a,
            transaction_observer_b=obs_b,
            poll_seconds=poll_seconds,
        )
        errors = verify_evidence_ordering(evidence)
        if errors:
            for e in errors:
                self.stderr.write(f"Ordering error: {e}")
            raise CommandError(f"Evidence ordering verification failed: {errors}")

        evidence["verified"] = True
        out_path = write_evidence(evidence, output)
        self.stdout.write(f"Evidence written to: {out_path}")
