import hashlib
import json
import shutil
import socket
import threading
import time
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from .models import AppSetting, Job, User


MASTER_RESOURCE = "quality_master"
MASTER_DEPENDENT_TYPES = {Job.JobType.PLANS_IMPORT}
RETRY_SAFE_TYPES = {
    Job.JobType.MASTER_UPDATE,
    Job.JobType.PLANS_IMPORT,
    Job.JobType.DAILY_REPORT_GENERATE,
}


def _canonical_hash(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_uploaded_file(uploaded_file, job_token, field_name):
    if uploaded_file is None:
        return None
    target_dir = Path(settings.JOB_INPUT_ROOT) / job_token
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(uploaded_file.name).name or field_name
    target = target_dir / f"{field_name}-{safe_name}"
    with target.open("wb") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)
    return {
        "path": str(target),
        "name": safe_name,
        "sha256": _file_hash(target),
        "size": target.stat().st_size,
    }


def remove_job_inputs(payload):
    paths = []
    for value in payload.values():
        if isinstance(value, dict) and value.get("path"):
            paths.append(Path(value["path"]))
    for path in paths:
        try:
            resolved = path.resolve()
            root = Path(settings.JOB_INPUT_ROOT).resolve()
            if root in resolved.parents:
                shutil.rmtree(resolved.parent, ignore_errors=True)
        except OSError:
            continue


def path_identity(path):
    candidate = Path(path)
    if not candidate.is_file():
        return {"path": str(path), "missing": True}
    stat = candidate.stat()
    return {
        "path": str(candidate.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def upload_identity(stored_file):
    if not stored_file:
        return None
    return {
        "name": stored_file.get("name"),
        "sha256": stored_file.get("sha256"),
        "size": stored_file.get("size"),
    }


def build_idempotency_key(job_type, payload):
    identity = {"job_type": job_type, "payload": payload}
    return _canonical_hash(identity)


def active_master_job():
    return (
        Job.objects.filter(
            resource_key=MASTER_RESOURCE,
            status__in=[Job.Status.QUEUED, Job.Status.RUNNING],
        )
        .order_by("available_at", "job_id")
        .first()
    )


def enqueue_job(
    job_type,
    payload,
    user=None,
    *,
    resource_key="",
    idempotency_key=None,
    timeout_seconds=900,
    depends_on=None,
):
    idempotency_key = idempotency_key or build_idempotency_key(job_type, payload)
    if depends_on is None and job_type in MASTER_DEPENDENT_TYPES:
        depends_on = active_master_job()
    blocked_reason = ""
    if depends_on:
        blocked_reason = f"先行Job {depends_on.job_id} の完了待ち"

    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    job_id = f"job_{timestamp}_{uuid4().hex[:8]}"
    try:
        with transaction.atomic():
            job = Job.objects.create(
                job_id=job_id,
                job_type=job_type,
                request_payload=payload,
                resource_key=resource_key,
                idempotency_key=idempotency_key,
                blocked_reason=blocked_reason,
                depends_on=depends_on,
                timeout_seconds=timeout_seconds,
                created_by=user,
                updated_by=user,
            )
            return job, True
    except IntegrityError:
        existing = Job.objects.filter(
            resource_key=resource_key,
            idempotency_key=idempotency_key,
            status__in=[Job.Status.QUEUED, Job.Status.RUNNING],
        ).first()
        if existing is None:
            raise
        return existing, False


def _retry_delay(attempt_count):
    delays = settings.JOB_RETRY_DELAYS_SECONDS
    if not delays:
        return 0
    return delays[min(max(attempt_count - 1, 0), len(delays) - 1)]


def reschedule_or_fail_interrupted_job(job, message, exception_type):
    job.refresh_from_db()
    if job.status != Job.Status.RUNNING:
        return job
    retry_safe = job.job_type in RETRY_SAFE_TYPES and job.request_payload.get(
        "retry_safe", True
    )
    now = timezone.now()
    if retry_safe and job.attempt_count < settings.JOB_MAX_ATTEMPTS:
        job.status = Job.Status.QUEUED
        job.available_at = now + timedelta(seconds=_retry_delay(job.attempt_count))
        job.blocked_reason = message
        job.worker_id = ""
        job.execution_token = ""
        job.heartbeat_at = None
        job.lease_until = None
        job.save(
            update_fields=[
                "status",
                "available_at",
                "blocked_reason",
                "worker_id",
                "execution_token",
                "heartbeat_at",
                "lease_until",
                "updated_at",
            ]
        )
    else:
        job.status = Job.Status.FAILED
        job.error_message = message
        job.result = {
            "status": "failed",
            "error_message": message,
            "exception_type": exception_type,
        }
        job.finished_at = now
        job.worker_id = ""
        job.execution_token = ""
        job.heartbeat_at = None
        job.lease_until = None
        job.save(
            update_fields=[
                "status",
                "error_message",
                "result",
                "finished_at",
                "worker_id",
                "execution_token",
                "heartbeat_at",
                "lease_until",
                "updated_at",
            ]
        )
    return job


def recover_expired_jobs(now=None):
    now = now or timezone.now()
    expired = Job.objects.filter(
        status=Job.Status.RUNNING,
        lease_until__lt=now,
    )
    recovered = 0
    for job in expired:
        reschedule_or_fail_interrupted_job(
            job,
            "worker lease失効後の再試行待ち",
            "WorkerLeaseExpired",
        )
        recovered += 1
    return recovered


def _fail_dependency(job, dependency):
    job.status = Job.Status.FAILED
    job.error_message = f"先行Job {dependency.job_id} が失敗したため実行しませんでした。"
    job.result = {
        "status": "failed",
        "error_message": job.error_message,
        "exception_type": "JobDependencyFailed",
        "depends_on_job_id": dependency.job_id,
    }
    job.finished_at = timezone.now()
    job.blocked_reason = ""
    job.save(
        update_fields=[
            "status",
            "error_message",
            "result",
            "finished_at",
            "blocked_reason",
            "updated_at",
        ]
    )


def claim_next_job(worker_id):
    now = timezone.now()
    recover_expired_jobs(now)
    while True:
        with transaction.atomic():
            candidates = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(status=Job.Status.QUEUED, available_at__lte=now)
                .order_by("available_at", "job_id")
            )
            job = None
            failed_dependency = False
            for candidate in candidates[:100]:
                if candidate.depends_on_id:
                    dependency = Job.objects.get(pk=candidate.depends_on_id)
                    if dependency.status == Job.Status.FAILED:
                        _fail_dependency(candidate, dependency)
                        failed_dependency = True
                        break
                    if dependency.status != Job.Status.SUCCEEDED:
                        if not candidate.blocked_reason:
                            candidate.blocked_reason = f"先行Job {candidate.depends_on_id} の完了待ち"
                            candidate.save(update_fields=["blocked_reason", "updated_at"])
                        continue
                if candidate.resource_key and Job.objects.filter(
                    resource_key=candidate.resource_key,
                    status=Job.Status.RUNNING,
                ).exclude(pk=candidate.pk).exists():
                    continue
                job = candidate
                break
            if failed_dependency:
                continue
            if job is None:
                return None
            job.status = Job.Status.RUNNING
            job.attempt_count += 1
            job.started_at = job.started_at or now
            job.heartbeat_at = now
            job.lease_until = now + timedelta(seconds=settings.JOB_LEASE_SECONDS)
            job.worker_id = worker_id
            job.blocked_reason = ""
            job.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "started_at",
                    "heartbeat_at",
                    "lease_until",
                    "worker_id",
                    "blocked_reason",
                    "updated_at",
                ]
            )
            return job


@contextmanager
def heartbeat(job_id, worker_id, execution_token=None):
    if not execution_token:
        yield
        return
    stop = threading.Event()

    def update_heartbeat():
        close_old_connections()
        while not stop.wait(settings.JOB_HEARTBEAT_SECONDS):
            now = timezone.now()
            Job.objects.filter(
                pk=job_id,
                status=Job.Status.RUNNING,
                worker_id=worker_id,
                execution_token=execution_token,
            ).update(
                heartbeat_at=now,
                lease_until=now + timedelta(seconds=settings.JOB_LEASE_SECONDS),
            )
        close_old_connections()

    thread = threading.Thread(target=update_heartbeat, name=f"heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def execute_job(job, worker_id=None, execution_token=None):
    from .services import (
        generate_daily_report,
        import_master_csv,
        import_plan_targets,
        issue_daily_report,
        issue_inspection_sheets,
        run_erp_automation,
        run_job,
    )

    payload = job.request_payload
    user = User.objects.filter(pk=job.created_by_id).first()
    operation = payload.get("operation")

    def run():
        if operation == "queue_smoke":
            if payload.get("sleep_seconds"):
                time.sleep(float(payload["sleep_seconds"]))
            return {"status": "succeeded", "message": "persistent queue smoke passed"}
        if operation == "master_update":
            setting = AppSetting.objects.first()
            upload = payload.get("master_file") or {}
            return import_master_csv(
                master_file=upload.get("path"),
                csv_path=payload.get("csv_path"),
                inspection_folder_paths=payload.get("inspection_folder_paths", []),
                inspection_folder_priorities=payload.get("inspection_folder_priorities", {}),
            )
        if operation == "erp_automation":
            return run_erp_automation(payload["erp_path"], payload["csv_path"])
        if operation == "plans_import":
            scan = payload.get("scan_file") or {}
            excel = payload.get("excel_file") or {}
            with ExitStack() as stack:
                scan_handle = (
                    stack.enter_context(Path(scan["path"]).open("rb"))
                    if scan.get("path")
                    else None
                )
                excel_handle = (
                    stack.enter_context(Path(excel["path"]).open("rb"))
                    if excel.get("path")
                    else None
                )
                return import_plan_targets(
                    payload["target_date"],
                    scan_file=scan_handle,
                    excel_file=excel_handle,
                    sheet_name=payload.get("sheet_name", ""),
                    user=user,
                )
        if operation == "inspection_sheet_issue":
            return issue_inspection_sheets(target_date=payload.get("date"), user=user)
        if operation == "daily_report_generate":
            return generate_daily_report(payload["date"], user)
        if operation == "daily_report_issue":
            return issue_daily_report(payload["date"], user)
        raise RuntimeError(f"Unsupported job operation: {operation}")

    return run_job(
        job,
        run,
        mark_running=False,
        worker_id=worker_id,
        execution_token=execution_token,
    )


def execute_claimed_job(job_id, worker_id):
    from .services import StaleJobExecution

    execution_token = uuid4().hex
    acquired = Job.objects.filter(
        pk=job_id,
        status=Job.Status.RUNNING,
        worker_id=worker_id,
        execution_token="",
    ).update(execution_token=execution_token)
    if acquired != 1:
        return None
    job = Job.objects.get(pk=job_id)
    try:
        with heartbeat(job_id, worker_id, execution_token), transaction.atomic():
            execute_job(job, worker_id=worker_id, execution_token=execution_token)
    except StaleJobExecution:
        return None
    job.refresh_from_db()
    return job


def process_next_job(worker_id=None):
    worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
    job = claim_next_job(worker_id)
    if job is None:
        return None
    try:
        execute_claimed_job(job.job_id, worker_id)
    except Exception:
        pass
    return job


def execute_inline_if_enabled(job, created):
    if settings.JOB_EXECUTE_INLINE_FOR_TESTS and created:
        worker_id = "inline-test-worker"
        claimed = claim_next_job(worker_id)
        if claimed and claimed.pk == job.pk:
            try:
                execute_claimed_job(claimed.job_id, worker_id)
            except Exception:
                pass
        job.refresh_from_db()
    return job
