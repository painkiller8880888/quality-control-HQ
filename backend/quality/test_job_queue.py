from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from pathlib import Path
from threading import Event, Lock
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .job_queue import (
    MASTER_RESOURCE,
    claim_next_job,
    enqueue_job,
    execute_claimed_job,
    recover_expired_jobs,
)
from .models import InspectionFile, Job, Master, MasterClass, Structure, User
from .services import import_master_csv, scan_and_classify_files


def create_admin(login_name):
    return User.objects.create(
        login_name=login_name,
        display_name=login_name,
        password_hash="!",
        role=User.Role.ADMIN,
    )


def execute_claimed_job_in_thread(job_id, worker_id):
    try:
        return execute_claimed_job(job_id, worker_id)
    finally:
        close_old_connections()


@override_settings(JOB_EXECUTE_INLINE_FOR_TESTS=False)
class PersistentJobQueueApiTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.first_admin = create_admin("queue-admin-1")
        self.second_admin = create_admin("queue-admin-2")
        self.client = APIClient()
        self.client.force_authenticate(self.first_admin)

    def test_master_update_returns_queued_without_running_in_request(self):
        with TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "master.csv"
            csv_path.write_text("header\n", encoding="utf-8")
            response = self.client.post(
                "/api/master/update/",
                {"force": False},
                format="json",
            )

        self.assertEqual(response.status_code, 202)
        job = Job.objects.get(pk=response.json()["job_id"])
        self.assertEqual(job.status, Job.Status.QUEUED)
        self.assertEqual(job.attempt_count, 0)
        self.assertIsNone(job.started_at)

    def test_same_active_master_request_is_deduplicated_across_users(self):
        first = self.client.post("/api/master/update/", {"force": False}, format="json")
        self.client.force_authenticate(self.second_admin)
        second = self.client.post("/api/master/update/", {"force": False}, format="json")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["job_id"], second.json()["job_id"])
        self.assertTrue(second.json()["deduplicated"])
        self.assertEqual(Job.objects.filter(resource_key=MASTER_RESOURCE).count(), 1)
        detail = self.client.get(f"/api/jobs/{first.json()['job_id']}/")
        self.assertEqual(detail.status_code, 200)

    def test_plan_import_waits_for_active_master_job(self):
        master, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "master_update"},
            self.first_admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="master-1",
        )
        response = self.client.post(
            "/api/plans/import/",
            {"target_date": "2026-07-16"},
            format="multipart",
        )

        job = Job.objects.get(pk=response.json()["job_id"])
        self.assertEqual(job.depends_on_id, master.job_id)
        self.assertIn(master.job_id, job.blocked_reason)
        self.assertEqual(claim_next_job("worker-1").job_id, master.job_id)

    def test_blocked_job_sorting_before_dependency_does_not_starve_dependency(self):
        master = Job.objects.create(
            job_id="job_z_master",
            job_type=Job.JobType.MASTER_UPDATE,
            request_payload={"operation": "queue_smoke"},
            resource_key=MASTER_RESOURCE,
            idempotency_key="master-z",
            created_by=self.first_admin,
        )
        Job.objects.create(
            job_id="job_a_dependent",
            job_type=Job.JobType.PLANS_IMPORT,
            request_payload={"operation": "queue_smoke"},
            resource_key="dependent-a",
            idempotency_key="dependent-a",
            depends_on=master,
            blocked_reason=f"先行Job {master.job_id} の完了待ち",
            created_by=self.first_admin,
        )

        claimed = claim_next_job("worker-1")

        self.assertEqual(claimed.job_id, master.job_id)


class PersistentJobQueueRecoveryTests(TransactionTestCase):
    def setUp(self):
        self.admin = create_admin("recovery-admin")

    @override_settings(JOB_MAX_ATTEMPTS=3, JOB_RETRY_DELAYS_SECONDS=[30, 120, 300])
    def test_expired_retry_safe_job_is_requeued(self):
        job, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "master_update", "retry_safe": True},
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="retry-safe",
        )
        job.status = Job.Status.RUNNING
        job.attempt_count = 1
        job.execution_token = "stale-execution"
        job.lease_until = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["status", "attempt_count", "execution_token", "lease_until"])

        recovered = recover_expired_jobs()

        job.refresh_from_db()
        self.assertEqual(recovered, 1)
        self.assertEqual(job.status, Job.Status.QUEUED)
        self.assertEqual(job.execution_token, "")
        self.assertIn("再試行", job.blocked_reason)
        self.assertGreater(job.available_at, timezone.now())

    def test_expired_external_side_effect_job_fails_without_retry(self):
        job, _ = enqueue_job(
            Job.JobType.INSPECTION_SHEET_ISSUE,
            {"operation": "inspection_sheet_issue", "retry_safe": False},
            self.admin,
            resource_key="inspection_sheet:2026-07-16",
            idempotency_key="unsafe",
        )
        job.status = Job.Status.RUNNING
        job.attempt_count = 1
        job.execution_token = "stale-execution"
        job.lease_until = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["status", "attempt_count", "execution_token", "lease_until"])

        recover_expired_jobs()

        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertEqual(job.execution_token, "")
        self.assertEqual(job.result["exception_type"], "WorkerLeaseExpired")

    def test_duplicate_delivery_of_same_master_job_does_not_double_apply(self):
        rows = [
            {
                "code": "CAP0001",
                "name": "duplicate-delivery-result",
                "department": "quality",
                "parent_code": "",
                "root_code": "CAP0001",
                "level": 1,
                "quantity": 0,
            }
        ]
        job, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {
                "operation": "master_update",
                "csv_path": "ignored.csv",
                "inspection_folder_paths": [],
            },
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="duplicate-delivery",
        )
        claimed = claim_next_job("worker-1")
        counts_before = (
            Master.objects.count(),
            MasterClass.objects.count(),
            Structure.objects.count(),
            InspectionFile.objects.count(),
        )

        with patch("quality.services.load_master_rows_from_csv", return_value=rows), patch(
            "quality.services.scan_and_classify_files",
            return_value=({}, []),
        ), patch(
            "quality.services.import_master_csv",
            wraps=import_master_csv,
        ) as import_master:
            first_delivery = execute_claimed_job(claimed.pk, "worker-1")
            duplicate_delivery = execute_claimed_job(claimed.pk, "worker-1")

        job.refresh_from_db()
        self.assertIsNotNone(first_delivery)
        self.assertIsNone(duplicate_delivery)
        self.assertEqual(import_master.call_count, 1)
        self.assertEqual(counts_before, (0, 0, 0, 0))
        self.assertEqual(Master.objects.filter(code="CAP0001").count(), 1)
        self.assertEqual(Master.objects.get(code="CAP0001").name, "duplicate-delivery-result")
        self.assertEqual(MasterClass.objects.count(), 0)
        self.assertEqual(Structure.objects.count(), 0)
        self.assertEqual(InspectionFile.objects.count(), 0)
        self.assertEqual(job.status, Job.Status.SUCCEEDED)
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.worker_id, "")
        self.assertEqual(job.execution_token, "")
        self.assertIsNone(job.heartbeat_at)
        self.assertIsNone(job.lease_until)

    def test_concurrent_delivery_of_same_job_acquires_one_execution_token(self):
        job, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {
                "operation": "master_update",
                "csv_path": "ignored.csv",
                "inspection_folder_paths": [],
            },
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="concurrent-duplicate-delivery",
        )
        claim_next_job("worker-1")
        business_started = Event()
        release_business = Event()

        def slow_import(**kwargs):
            business_started.set()
            if not release_business.wait(timeout=5):
                raise TimeoutError("test did not release the business function")
            return {"updated_master_count": 0}

        with patch(
            "quality.services.import_master_csv",
            side_effect=slow_import,
        ) as import_master, ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(execute_claimed_job_in_thread, job.pk, "worker-1")
            self.assertTrue(business_started.wait(timeout=5))
            duplicate_delivery = execute_claimed_job(job.pk, "worker-1")
            release_business.set()
            first_delivery = first.result(timeout=5)

        job.refresh_from_db()
        self.assertIsNotNone(first_delivery)
        self.assertIsNone(duplicate_delivery)
        self.assertEqual(import_master.call_count, 1)
        self.assertEqual(job.status, Job.Status.SUCCEEDED)
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.execution_token, "")
        self.assertEqual(job.worker_id, "")
        self.assertIsNone(job.heartbeat_at)
        self.assertIsNone(job.lease_until)

    @override_settings(
        JOB_HEARTBEAT_SECONDS=60,
        JOB_RETRY_DELAYS_SECONDS=[0],
    )
    def test_stale_executor_cannot_commit_or_overwrite_recovered_attempt(self):
        for stale_outcome in ("success", "failure"):
            with self.subTest(stale_outcome=stale_outcome):
                job, _ = enqueue_job(
                    Job.JobType.MASTER_UPDATE,
                    {
                        "operation": "master_update",
                        "csv_path": "ignored.csv",
                        "inspection_folder_paths": [],
                    },
                    self.admin,
                    resource_key=MASTER_RESOURCE,
                    idempotency_key=f"stale-{stale_outcome}",
                )
                claim_next_job(f"worker-old-{stale_outcome}")
                old_started = Event()
                allow_old_finish = Event()
                call_lock = Lock()
                call_number = 0
                code = f"CAP-{stale_outcome}"

                def raced_import(**kwargs):
                    nonlocal call_number
                    with call_lock:
                        call_number += 1
                        current_call = call_number
                    if current_call == 1:
                        old_started.set()
                        if not allow_old_finish.wait(timeout=10):
                            raise TimeoutError("test did not release stale execution")
                        Master.objects.update_or_create(
                            code=code,
                            defaults={"name": "stale-attempt"},
                        )
                        if stale_outcome == "failure":
                            raise RuntimeError("stale attempt failed after recovery")
                        return {"winner": "stale-attempt"}
                    Master.objects.update_or_create(
                        code=code,
                        defaults={"name": "recovered-attempt"},
                    )
                    return {"winner": "recovered-attempt"}

                with patch(
                    "quality.services.import_master_csv",
                    side_effect=raced_import,
                ) as import_master, ThreadPoolExecutor(max_workers=1) as executor:
                    old = executor.submit(
                        execute_claimed_job_in_thread,
                        job.pk,
                        f"worker-old-{stale_outcome}",
                    )
                    self.assertTrue(old_started.wait(timeout=5))
                    Job.objects.filter(pk=job.pk).update(
                        lease_until=timezone.now() - timedelta(seconds=1)
                    )
                    self.assertEqual(recover_expired_jobs(), 1)
                    recovered_claim = claim_next_job(f"worker-new-{stale_outcome}")
                    self.assertEqual(recovered_claim.pk, job.pk)
                    recovered_delivery = execute_claimed_job(
                        job.pk,
                        f"worker-new-{stale_outcome}",
                    )
                    allow_old_finish.set()
                    stale_delivery = old.result(timeout=10)

                job.refresh_from_db()
                self.assertIsNotNone(recovered_delivery)
                self.assertIsNone(stale_delivery)
                self.assertEqual(import_master.call_count, 2)
                self.assertEqual(Master.objects.filter(code=code).count(), 1)
                self.assertEqual(Master.objects.get(code=code).name, "recovered-attempt")
                self.assertEqual(job.status, Job.Status.SUCCEEDED)
                self.assertEqual(job.attempt_count, 2)
                self.assertEqual(job.result["winner"], "recovered-attempt")
                self.assertEqual(job.execution_token, "")
                self.assertEqual(job.worker_id, "")
                self.assertIsNone(job.heartbeat_at)
                self.assertIsNone(job.lease_until)

    def test_owned_execution_failure_is_finalized_and_releases_token(self):
        job, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {
                "operation": "master_update",
                "csv_path": "ignored.csv",
                "inspection_folder_paths": [],
            },
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="owned-failure",
        )
        claim_next_job("worker-1")

        with patch(
            "quality.services.import_master_csv",
            side_effect=RuntimeError("owned execution failed"),
        ):
            delivery = execute_claimed_job(job.pk, "worker-1")

        job.refresh_from_db()
        self.assertIsNotNone(delivery)
        self.assertEqual(job.status, Job.Status.FAILED)
        self.assertEqual(job.result["exception_type"], "RuntimeError")
        self.assertEqual(job.execution_token, "")
        self.assertEqual(job.worker_id, "")
        self.assertIsNone(job.heartbeat_at)
        self.assertIsNone(job.lease_until)

    def test_failed_dependency_prevents_business_execution(self):
        dependency, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "master_update"},
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="failed-master",
        )
        dependency.status = Job.Status.FAILED
        dependency.finished_at = timezone.now()
        dependency.save(update_fields=["status", "finished_at"])
        dependent, _ = enqueue_job(
            Job.JobType.PLANS_IMPORT,
            {"operation": "plans_import"},
            self.admin,
            resource_key="plans:2026-07-16",
            idempotency_key="dependent",
            depends_on=dependency,
        )

        claimed = claim_next_job("worker-1")

        self.assertIsNone(claimed)
        dependent.refresh_from_db()
        self.assertEqual(dependent.status, Job.Status.FAILED)
        self.assertEqual(dependent.result["exception_type"], "JobDependencyFailed")

    def test_inaccessible_inspection_folder_is_reported_as_warning(self):
        files, warnings = scan_and_classify_files([r"Z:\definitely-not-accessible"])

        self.assertEqual(files, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("inaccessible", warnings[0])

    def test_all_inaccessible_folders_preserve_existing_inspection_files(self):
        master = Master.objects.create(code="CAP0001", name="existing")
        InspectionFile.objects.create(
            master=master,
            file_name="CAP0001.xlsx",
            file_path=r"\\server\share\CAP0001.xlsx",
        )
        rows = [
            {
                "code": "CAP0001",
                "name": "updated",
                "department": "quality",
                "parent_code": "",
                "root_code": "CAP0001",
                "level": 1,
                "quantity": 0,
            }
        ]
        with patch("quality.services.load_master_rows_from_csv", return_value=rows), patch(
            "quality.services.scan_and_classify_files",
            return_value=({}, ["Folder not found or inaccessible: \\\\server\\share"]),
        ):
            result = import_master_csv(
                master_file="ignored.csv",
                inspection_folder_paths=[r"\\server\share"],
            )

        self.assertEqual(InspectionFile.objects.count(), 1)
        self.assertTrue(result["inspection_files_preserved"])

    def test_scan_start_oserror_fails_even_when_no_files_were_detected(self):
        with TemporaryDirectory() as temp_dir, patch.object(
            Path,
            "rglob",
            side_effect=OSError("share disconnected before first entry"),
        ):
            with self.assertRaisesRegex(
                OSError,
                r"^Inspection folder scan failed or became inaccessible\.$",
            ):
                scan_and_classify_files([temp_dir])

    def test_partial_folder_scan_failure_does_not_commit_partial_inspection_index(self):
        existing_master = Master.objects.create(code="CAP0001", name="existing")
        InspectionFile.objects.create(
            master=existing_master,
            file_name="CAP0001.xlsx",
            file_path=r"\\server\existing\CAP0001.xlsx",
        )
        rows = [
            {
                "code": "CAP0001",
                "name": "updated",
                "department": "quality",
                "parent_code": "",
                "root_code": "CAP0001",
                "level": 1,
                "quantity": 0,
            }
        ]
        scan_error = None
        with TemporaryDirectory() as temp_dir:
            available = Path(temp_dir) / "available"
            disconnected = Path(temp_dir) / "disconnected"
            available.mkdir()
            disconnected.mkdir()
            (available / "CAP0001-new.xlsx").touch()
            original_rglob = Path.rglob

            def rglob_with_disconnect(path, pattern):
                if path == disconnected:
                    raise OSError("share disconnected during scan")
                return original_rglob(path, pattern)

            with patch("quality.services.load_master_rows_from_csv", return_value=rows), patch.object(
                Path,
                "rglob",
                new=rglob_with_disconnect,
            ):
                try:
                    import_master_csv(
                        master_file="ignored.csv",
                        inspection_folder_paths=[str(available), str(disconnected)],
                    )
                except OSError as exc:
                    scan_error = exc

        existing_master.refresh_from_db()
        self.assertEqual(
            {
                "exception_type": type(scan_error).__name__ if scan_error else None,
                "master_name": existing_master.name,
                "inspection_file_paths": list(
                    InspectionFile.objects.values_list("file_path", flat=True)
                ),
            },
            {
                "exception_type": "OSError",
                "master_name": "existing",
                "inspection_file_paths": [r"\\server\existing\CAP0001.xlsx"],
            },
        )

    def test_reachable_empty_folder_and_inaccessible_folder_fails_the_update(self):
        with patch("quality.services.load_master_rows_from_csv", return_value=[]), patch(
            "quality.services.scan_and_classify_files",
            return_value=({}, [r"Folder not found or inaccessible: \\server\inaccessible"]),
        ):
            with self.assertRaisesRegex(
                OSError,
                r"^Inspection folder scan failed or became inaccessible\.$",
            ):
                import_master_csv(
                    master_file="ignored.csv",
                    inspection_folder_paths=[r"\\server\empty", r"\\server\inaccessible"],
                )
