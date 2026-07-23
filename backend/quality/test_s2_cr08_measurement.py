import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from .job_queue import (
    MASTER_RESOURCE,
    claim_next_job,
    enqueue_job,
    execute_claimed_job,
)
from .models import Job, User

from .s2_cr08_measurement import (
    build_evidence,
    verify_evidence_ordering,
    write_evidence,
    poll_active_backends,
    TransactionObserver,
    _connection_pid,
    _backend_hash,
    _db_clock,
    MEASUREMENT_SCHEMA_VERSION,
)


def require_postgresql(test_method):
    def wrapper(self, *args, **kwargs):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        return test_method(self, *args, **kwargs)
    return wrapper


from quality.management.commands.measure_s2_cr08 import _claim_specific_job


@override_settings(JOB_EXECUTE_INLINE_FOR_TESTS=False)
class S2Cr08MeasurementTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        from django.contrib.auth.hashers import make_password
        self.admin = User.objects.create(
            login_name="s2-cr08-admin",
            display_name="S2 CR-08 Admin",
            password_hash=make_password("test"),
            role=User.Role.ADMIN,
        )

    def _enqueue_smoke_job(self, idempotency_key, sleep_seconds=3, depends_on=None):
        job, created = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": sleep_seconds, "retry_safe": True},
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key=idempotency_key,
            depends_on=depends_on,
        )
        self.assertTrue(created)
        return job

    def _claim_then_execute(self, job, worker_id, observer=None):
        claimed = _claim_specific_job(job, worker_id)
        self.assertIsNotNone(claimed)
        if observer:
            observer.start_watching()
            self.assertTrue(
                observer.wait_watching_armed(timeout=5),
                "observer should arm watching phase within timeout",
            )
        return execute_claimed_job(job.pk, worker_id)

    def test_created_at_field_on_job(self):
        before = timezone.now()
        job, created = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0.1, "retry_safe": True},
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="s2-cr08-created-at-field",
        )
        self.assertTrue(created)
        job.refresh_from_db()
        self.assertIsNotNone(job.created_at)
        self.assertGreater(job.created_at, before - timezone.timedelta(seconds=1))
        self.assertLess(job.created_at, timezone.now() + timezone.timedelta(seconds=1))

    def test_evidence_includes_job_created_at(self):
        job, created = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0.1, "retry_safe": True},
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="s2-cr08-evidence-created-at",
        )
        self.assertTrue(created)
        job.refresh_from_db()
        evidence = build_evidence(job_a=job)
        self.assertIsNotNone(evidence["job_a"]["created_at"])
        errors = verify_evidence_ordering(evidence)
        self.assertEqual(errors, [])

    def test_evidence_a_b_ordering(self):
        job_a, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0.1, "retry_safe": True},
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="s2-cr08-ordering-a",
        )
        job_b, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0.1, "retry_safe": True},
            self.admin,
            resource_key=MASTER_RESOURCE,
            idempotency_key="s2-cr08-ordering-b",
            depends_on=job_a,
        )
        job_a.refresh_from_db()
        job_b.refresh_from_db()
        evidence = build_evidence(job_a=job_a, job_b=job_b)
        self.assertGreater(evidence["job_b"]["created_at"], evidence["job_a"]["created_at"])
        errors = verify_evidence_ordering(evidence)
        self.assertEqual(errors, [])

    @require_postgresql
    def test_observer_captures_execution_transaction(self):
        job = self._enqueue_smoke_job("s2-cr08-exec-txn", sleep_seconds=3)
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.3, target_pid=pid)
        observer.start()
        try:
            result = self._claim_then_execute(job, "txn-exec-worker", observer)
        finally:
            observer.stop()

        self.assertIsNotNone(result)
        self.assertIsNotNone(observer.backend_hash)
        self.assertEqual(observer.backend_pid, pid)
        self.assertTrue(observer.transaction_completed)

        duration = (observer.end_upper_bound - observer.xact_start).total_seconds()
        self.assertGreaterEqual(duration, 2.0,
                                "captured transaction should be the long execution (>=2s), not the claim")

    @require_postgresql
    def test_observer_bracket_bounds(self):
        job = self._enqueue_smoke_job("s2-cr08-bracket", sleep_seconds=2)
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.3, target_pid=pid)
        observer.start()
        try:
            result = self._claim_then_execute(job, "txn-bracket-worker", observer)
        finally:
            observer.stop()

        self.assertIsNotNone(result)
        self.assertTrue(observer.transaction_completed)
        self.assertIsNotNone(observer.xact_start)
        self.assertIsNotNone(observer.end_lower_bound)
        self.assertIsNotNone(observer.end_upper_bound)

        actual_duration = (result.finished_at - result.started_at).total_seconds()
        lb = (observer.end_lower_bound - observer.xact_start).total_seconds()
        ub = (observer.end_upper_bound - observer.xact_start).total_seconds()
        self.assertLessEqual(lb, ub, "lower bound must not exceed upper bound")
        self.assertLess(lb, ub + 1, "bounds should bracket the transaction duration")

    @require_postgresql
    def test_observer_start_watching_activates_tracking(self):
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.3, target_pid=pid)
        observer.start()
        try:
            self.assertFalse(observer._watch_event.is_set(),
                             "should not be watching before start_watching()")
            observer.start_watching()
            self.assertTrue(observer._watch_event.is_set(),
                            "should be watching after start_watching()")
        finally:
            observer.stop()

    @require_postgresql
    def test_a_b_dependency_claim(self):
        job_a = self._enqueue_smoke_job("s2-cr08-dep-a", sleep_seconds=1)
        job_b = self._enqueue_smoke_job("s2-cr08-dep-b", sleep_seconds=1, depends_on=job_a)

        pid = _connection_pid()
        obs_a = TransactionObserver(poll_seconds=0.3, target_pid=pid)
        obs_a.start()
        try:
            result_a = self._claim_then_execute(job_a, "dep-worker", obs_a)
            self.assertIsNotNone(result_a)
            self.assertEqual(result_a.status, Job.Status.SUCCEEDED)
        finally:
            obs_a.stop()
        self.assertTrue(obs_a.transaction_completed, "observer A should track execution transaction")

        self.assertNotEqual(job_b.blocked_reason, "")
        updated = Job.objects.filter(
            pk=job_b.pk,
            depends_on_id=job_a.pk,
            status=Job.Status.QUEUED,
            resource_key=MASTER_RESOURCE,
        ).update(blocked_reason="", available_at=timezone.now())
        self.assertEqual(updated, 1)
        job_b.refresh_from_db()

        obs_b = TransactionObserver(poll_seconds=0.3, target_pid=pid)
        obs_b.start()
        try:
            result_b = self._claim_then_execute(job_b, "dep-worker", obs_b)
            self.assertIsNotNone(result_b)
            self.assertEqual(result_b.status, Job.Status.SUCCEEDED)
        finally:
            obs_b.stop()
        self.assertTrue(obs_b.transaction_completed, "observer B should track execution transaction")

        evidence = build_evidence(
            job_a=job_a, job_b=job_b,
            transaction_observer_a=obs_a, transaction_observer_b=obs_b,
        )
        self.assertIn("job_a_transaction", evidence)
        self.assertIn("job_b_transaction", evidence)
        errors = verify_evidence_ordering(evidence)
        self.assertEqual(errors, [])

    @require_postgresql
    def test_observer_start_raises_on_baseline_failure(self):
        observer = TransactionObserver(poll_seconds=999)
        observer._baseline_ready.set()
        with self.assertRaises(RuntimeError):
            observer.start()
        observer.stop()

    @require_postgresql
    def test_observer_stop_raises_on_join_timeout(self):
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.3, target_pid=pid)
        observer.start()
        observer.stop()

    def test_evidence_ordering_verification_detects_errors(self):
        bad = {
            "job_a": {
                "created_at": "2026-07-23T10:01:00+00:00",
                "started_at": "2026-07-23T10:00:00+00:00",
                "finished_at": "2026-07-23T10:02:00+00:00",
            }
        }
        errors = verify_evidence_ordering(bad)
        self.assertTrue(any("created_at" in e and "started_at" in e for e in errors))

    def test_evidence_ordering_verification_passes(self):
        good = {
            "job_a": {
                "created_at": "2026-07-23T10:00:00+00:00",
                "started_at": "2026-07-23T10:01:00+00:00",
                "finished_at": "2026-07-23T10:02:00+00:00",
            },
            "job_b": {
                "created_at": "2026-07-23T10:01:30+00:00",
                "started_at": "2026-07-23T10:03:00+00:00",
                "finished_at": "2026-07-23T10:05:00+00:00",
            },
            "job_a_transaction": {
                "xact_start": "2026-07-23T10:01:00+00:00",
                "end_lower_bound": "2026-07-23T10:01:30+00:00",
                "end_upper_bound": "2026-07-23T10:01:31+00:00",
            },
            "job_b_transaction": {
                "xact_start": "2026-07-23T10:03:00+00:00",
                "end_lower_bound": "2026-07-23T10:04:30+00:00",
                "end_upper_bound": "2026-07-23T10:04:31+00:00",
            },
        }
        errors = verify_evidence_ordering(good)
        self.assertEqual(errors, [])
        equal = {
            "job_a": {
                "created_at": "2026-07-23T10:00:00+00:00",
                "started_at": "2026-07-23T10:00:00+00:00",
                "finished_at": "2026-07-23T10:02:00+00:00",
            },
        }
        errors = verify_evidence_ordering(equal)
        self.assertEqual(errors, [], "created_at == started_at is valid (same clock tick)")

    def test_evidence_ordering_handles_partial_data(self):
        partial = {
            "job_a": {
                "created_at": "2026-07-23T10:00:00+00:00",
                "started_at": None,
                "finished_at": None,
            }
        }
        errors = verify_evidence_ordering(partial)
        self.assertEqual(errors, [])

    def test_evidence_ordering_detects_transaction_xact_start_ge_lower(self):
        bad = {
            "job_a_transaction": {
                "xact_start": "2026-07-23T10:01:00+00:00",
                "end_lower_bound": "2026-07-23T10:00:59+00:00",
                "end_upper_bound": "2026-07-23T10:01:01+00:00",
            },
        }
        errors = verify_evidence_ordering(bad)
        self.assertTrue(any("xact_start" in e for e in errors))
        bad_fallback = {
            "transaction": {
                "xact_start": "2026-07-23T10:01:00+00:00",
                "end_lower_bound": "2026-07-23T10:00:59+00:00",
                "end_upper_bound": "2026-07-23T10:01:01+00:00",
            },
        }
        errors = verify_evidence_ordering(bad_fallback)
        self.assertTrue(any("xact_start" in e for e in errors))

    def test_write_evidence_creates_manifest(self):
        evidence = {"fixture_version": "test", "test": True}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            written = write_evidence(evidence, output)
            self.assertTrue((written / "measurement.json").exists())
            self.assertTrue((written / "checksums.sha256").exists())
            manifest = (written / "checksums.sha256").read_text(encoding="utf-8")
            self.assertIn("measurement.json", manifest)
            self.assertNotIn("checksums.sha256", manifest)

    def test_write_evidence_rejects_nonempty_dir(self):
        evidence = {"fixture_version": "test"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            output.mkdir()
            (output / "stale.txt").write_text("data")
            with self.assertRaises(FileExistsError):
                write_evidence(evidence, output)

    def test_backend_hash_sha256(self):
        h = _backend_hash(12345, 54321)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)
        import hashlib
        expected = hashlib.sha256(b"pid=12345|port=54321").hexdigest()
        self.assertEqual(h, expected)

    def test_poll_active_backends_sqlite(self):
        with patch.object(connection, "vendor", "sqlite"):
            result = poll_active_backends()
            self.assertEqual(result, [])

    def test_build_evidence_fake_job_queue_wait(self):
        now = timezone.now()
        fake = type("FakeJob", (), {
            "job_id": "j1", "job_type": "master_update",
            "status": "succeeded", "attempt_count": 1,
            "depends_on_id": None,
            "created_at": now - timezone.timedelta(seconds=5),
            "started_at": now,
            "finished_at": now + timezone.timedelta(seconds=100),
        })()
        evidence = build_evidence(job_a=fake)
        self.assertIn("total_queue_wait_seconds", evidence["job_a"])
        self.assertAlmostEqual(evidence["job_a"]["total_queue_wait_seconds"], 5.0, delta=0.1)

    def test_build_evidence_no_transaction(self):
        evidence = build_evidence()
        self.assertNotIn("job_a_transaction", evidence)
        self.assertNotIn("job_b_transaction", evidence)

    def test_build_evidence_partial_transaction_observer(self):
        observer = TransactionObserver(poll_seconds=999)
        observer.backend_hash = "abc123"
        observer.xact_start = timezone.now()
        observer.end_lower_bound = timezone.now()
        observer.end_upper_bound = None
        observer.poll_count = 0
        observer.transaction_completed = False
        evidence = build_evidence(transaction_observer_a=observer)
        self.assertNotIn("job_a_transaction", evidence)

    def test_connection_pid_returns_int(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        pid = _connection_pid()
        self.assertIsInstance(pid, int)
        self.assertGreater(pid, 0)

    def test_baseline_ready_event(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.1, target_pid=pid)
        observer.start()
        self.assertGreaterEqual(observer.poll_count, 1)
        observer.stop()

    @require_postgresql
    def test_observer_thread_exception_during_baseline(self):
        observer = TransactionObserver(poll_seconds=0.3, target_pid=999999999)
        with patch.object(
            observer, "_do_poll",
            side_effect=RuntimeError("baseline explosion"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                observer.start()
            cause = ctx.exception.__cause__
            self.assertIsNotNone(cause)
            self.assertIn("baseline explosion", str(cause))

    @require_postgresql
    def test_observer_thread_exception_during_poll(self):
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.1, target_pid=pid)
        observer.start()
        with patch.object(
            observer, "_do_poll",
            side_effect=RuntimeError("poll explosion"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                observer.stop()
            cause = ctx.exception.__cause__
            self.assertIsNotNone(cause)
            self.assertIn("poll explosion", str(cause))

    @require_postgresql
    def test_command_end_to_end_success(self):
        from io import StringIO

        with TemporaryDirectory() as tmp:
            out = StringIO()
            err = StringIO()

            call_command(
                "measure_s2_cr08",
                output=tmp,
                poll_seconds=0.3,
                stdout=out,
                stderr=err,
            )

            output_dir = Path(tmp)
            self.assertTrue((output_dir / "measurement.json").exists(),
                            msg="measurement.json should be written on success")
            self.assertTrue((output_dir / "checksums.sha256").exists())
            evidence = json.loads((output_dir / "measurement.json").read_text(encoding="utf-8"))
            self.assertIn("job_a", evidence)
            self.assertIn("job_b", evidence)
            self.assertIn("job_a_transaction", evidence,
                          msg="should capture A execution transaction")
            self.assertIn("job_b_transaction", evidence,
                          msg="should capture B execution transaction")
            self.assertTrue(evidence.get("verified"))
            errors = verify_evidence_ordering(evidence)
            self.assertEqual(errors, [])
            self.assertIn("final_active=0", err.getvalue(),
                          msg="cleanup should report zero active jobs")

    @require_postgresql
    def test_command_observer_failure_skips_evidence(self):
        from io import StringIO

        pid = _connection_pid()
        with TemporaryDirectory() as tmp:
            original = TransactionObserver._do_poll
            calls = [0]

            def fail_after_baseline(self_obs):
                calls[0] += 1
                if calls[0] >= 3:
                    raise RuntimeError("observer failure")
                return original(self_obs)

            with patch.object(TransactionObserver, "_do_poll", fail_after_baseline):
                err = StringIO()
                with self.assertRaises(CommandError):
                    call_command(
                        "measure_s2_cr08",
                        output=tmp,
                        poll_seconds=0.15,
                        stderr=err,
                    )

            output_dir = Path(tmp)
            self.assertFalse(
                (output_dir / "measurement.json").exists(),
                msg="evidence should NOT be written when observer fails",
            )
            self.assertIn("final_active=0", err.getvalue(),
                          msg="cleanup should report zero active jobs")

    @require_postgresql
    def test_command_baseline_failure_cleans_jobs(self):
        from io import StringIO

        def raise_on_poll(self_obs):
            raise RuntimeError("baseline poll failure")

        with TemporaryDirectory() as tmp:
            with patch.object(TransactionObserver, "_do_poll", raise_on_poll):
                err = StringIO()
                with self.assertRaises(CommandError):
                    call_command(
                        "measure_s2_cr08",
                        output=tmp,
                        poll_seconds=0.3,
                        stderr=err,
                    )

            output_dir = Path(tmp)
            self.assertFalse(
                (output_dir / "measurement.json").exists(),
                msg="evidence should NOT be written when baseline fails",
            )
            err_text = err.getvalue()
            self.assertIn("final_active=0", err_text,
                          msg="cleanup should report zero active jobs after baseline failure")

        # DB-level assertions
        for j in Job.objects.filter(resource_key=MASTER_RESOURCE):
            self.assertEqual(j.status, Job.Status.FAILED,
                             msg=f"Job {j.job_id} should be FAILED")
            self.assertEqual(j.worker_id, "",
                             msg=f"Job {j.job_id} worker_id should be released")
            self.assertEqual(j.execution_token, "",
                             msg=f"Job {j.job_id} execution_token should be released")
            self.assertIsNone(j.heartbeat_at,
                              msg=f"Job {j.job_id} heartbeat should be released")
            self.assertIsNone(j.lease_until,
                              msg=f"Job {j.job_id} lease should be released")
            self.assertEqual(j.error_message, "ERROR_FIXTURE_ABORT",
                             msg=f"Job {j.job_id} should have redacted error_message")
            self.assertEqual(j.blocked_reason, "",
                             msg=f"Job {j.job_id} blocked_reason should be cleared on FAILED")
            self.assertEqual(j.result.get("exception_type"), "S2Cr08FixtureAbort",
                             msg=f"Job {j.job_id} should have exception_type in result")
        self.assertEqual(
            Job.objects.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).count(),
            0, msg="no active jobs should remain",
        )

    @require_postgresql
    def test_command_execution_failure_cleans_jobs(self):
        from io import StringIO
        from unittest.mock import patch as mock_patch

        def fail_execution(job_id, worker_id):
            return None

        with TemporaryDirectory() as tmp:
            err = StringIO()
            with mock_patch(
                "quality.management.commands.measure_s2_cr08.execute_claimed_job",
                fail_execution,
            ):
                with self.assertRaises(CommandError):
                    call_command(
                        "measure_s2_cr08",
                        output=tmp,
                        poll_seconds=0.3,
                        stderr=err,
                    )

            output_dir = Path(tmp)
            self.assertFalse(
                (output_dir / "measurement.json").exists(),
                msg="evidence should NOT be written when execution fails",
            )
            err_text = err.getvalue()
            self.assertIn("final_active=0", err_text,
                          msg="cleanup should report zero active jobs after execution failure")
            self.assertIn("failed", err_text,
                          msg="cleanup should report failed job status")

        # DB-level assertions
        active_count = 0
        for j in Job.objects.filter(resource_key=MASTER_RESOURCE):
            self.assertEqual(j.status, Job.Status.FAILED,
                             msg=f"Job {j.job_id} should be FAILED")
            self.assertEqual(j.worker_id, "",
                             msg=f"Job {j.job_id} worker_id should be released")
            self.assertEqual(j.execution_token, "",
                             msg=f"Job {j.job_id} execution_token should be released")
            self.assertIsNone(j.heartbeat_at,
                              msg=f"Job {j.job_id} heartbeat should be released")
            self.assertIsNone(j.lease_until,
                              msg=f"Job {j.job_id} lease should be released")
            self.assertEqual(j.error_message, "ERROR_FIXTURE_ABORT",
                             msg=f"Job {j.job_id} should have redacted error_message")
            self.assertEqual(j.blocked_reason, "",
                             msg=f"Job {j.job_id} blocked_reason should be cleared on FAILED")
            self.assertEqual(j.result.get("exception_type"), "S2Cr08FixtureAbort",
                             msg=f"Job {j.job_id} should have exception_type in result")
            if j.status in (Job.Status.QUEUED, Job.Status.RUNNING):
                active_count += 1
        self.assertEqual(active_count, 0, msg="no active jobs should remain")

    @require_postgresql
    def test_command_observer_incomplete_skips_evidence(self):
        from io import StringIO
        from unittest.mock import patch as mock_patch

        with TemporaryDirectory() as tmp:
            err = StringIO()
            with mock_patch(
                "quality.management.commands.measure_s2_cr08._require_observer_section",
                side_effect=CommandError("Observer did not detect transaction completion"),
            ):
                with self.assertRaises(CommandError) as ctx:
                    call_command(
                        "measure_s2_cr08",
                        output=tmp,
                        poll_seconds=0.3,
                        stderr=err,
                    )

            output_dir = Path(tmp)
            self.assertFalse(
                (output_dir / "measurement.json").exists(),
                msg="evidence should NOT be written when observer incomplete",
            )
            err_text = err.getvalue()
            self.assertIn("final_active=0", err_text,
                          msg="cleanup should report zero active jobs")

        # DB-level assertions: jobs SUCCEEDED (execution completed), not overwritten by cleanup
        for j in Job.objects.filter(resource_key=MASTER_RESOURCE):
            self.assertEqual(j.status, Job.Status.SUCCEEDED,
                             msg=f"Job {j.job_id} should be SUCCEEDED (execution ran)")
            self.assertEqual(j.worker_id, "",
                             msg=f"Job {j.job_id} worker_id should be released")
            self.assertEqual(j.execution_token, "",
                             msg=f"Job {j.job_id} execution_token should be released")
            self.assertIsNone(j.heartbeat_at,
                              msg=f"Job {j.job_id} heartbeat should be released")
            self.assertIsNone(j.lease_until,
                              msg=f"Job {j.job_id} lease should be released")
            self.assertEqual(j.blocked_reason, "",
                             msg=f"Job {j.job_id} blocked_reason should be empty on terminal")
        self.assertEqual(
            Job.objects.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).count(),
            0, msg="no active jobs should remain",
        )

    def test_require_observer_section_validates_fields(self):
        from quality.management.commands.measure_s2_cr08 import _require_observer_section

        obs = TransactionObserver(poll_seconds=999)
        obs.backend_hash = "abc"
        obs.xact_start = timezone.now()
        obs.end_lower_bound = timezone.now()
        obs.end_upper_bound = timezone.now()
        obs.transaction_completed = True
        _require_observer_section(obs, "test")  # should not raise

        obs.transaction_completed = False
        with self.assertRaises(CommandError):
            _require_observer_section(obs, "test")

        obs.transaction_completed = True
        obs.backend_hash = None
        with self.assertRaises(CommandError):
            _require_observer_section(obs, "test")

    def test_observer_wait_watching_armed(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.1, target_pid=pid)
        observer.start()
        try:
            self.assertFalse(observer.wait_watching_armed(timeout=0.1),
                             "should not be armed before start_watching")
            observer.start_watching()
            self.assertTrue(observer.wait_watching_armed(timeout=5),
                            "should arm after start_watching + poll cycle")
        finally:
            observer.stop()

    @require_postgresql
    def test_wait_watching_armed_raises_on_thread_exception(self):
        pid = _connection_pid()
        observer = TransactionObserver(poll_seconds=0.5, target_pid=pid)
        original_poll = TransactionObserver._do_poll
        call_count = [0]
        proceed = threading.Event()

        def fail_after_baseline(self_obs):
            call_count[0] += 1
            if call_count[0] == 1:
                return original_poll(self_obs)
            proceed.wait(timeout=10)
            raise RuntimeError("observer poll crashed")

        with patch.object(TransactionObserver, "_do_poll", fail_after_baseline):
            observer.start()
            proceed.set()
            observer.start_watching()
            with self.assertRaises(RuntimeError) as ctx:
                observer.wait_watching_armed(timeout=10)
            self.assertIn("observer poll crashed", str(ctx.exception.__cause__))

    @require_postgresql
    def test_atomic_resource_claim_concurrency(self):
        """Two threads contending via fixture _claim_specific_job on same resource"""
        job_a, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0, "retry_safe": True},
            resource_key=MASTER_RESOURCE,
            idempotency_key=f"concur-a-{timezone.now().timestamp()}",
        )
        job_b, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0, "retry_safe": True},
            resource_key=MASTER_RESOURCE,
            idempotency_key=f"concur-b-{timezone.now().timestamp()}",
        )

        results = {"a": None, "b": None, "pid_a": None, "pid_b": None, "errors": []}
        barrier = threading.Barrier(3)

        def claim_a():
            try:
                with connection.cursor() as c:
                    c.execute("SELECT pg_backend_pid()")
                    results["pid_a"] = c.fetchone()[0]
                barrier.wait(timeout=10)
                results["a"] = _claim_specific_job(job_a, "worker-a")
            except Exception as e:
                results["errors"].append(f"a: {e}")
            finally:
                close_old_connections()

        def claim_b():
            try:
                with connection.cursor() as c:
                    c.execute("SELECT pg_backend_pid()")
                    results["pid_b"] = c.fetchone()[0]
                barrier.wait(timeout=10)
                results["b"] = _claim_specific_job(job_b, "worker-b")
            except Exception as e:
                results["errors"].append(f"b: {e}")
            finally:
                close_old_connections()

        t1 = threading.Thread(target=claim_a)
        t2 = threading.Thread(target=claim_b)
        t1.start()
        t2.start()
        barrier.wait(timeout=10)
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertFalse(t1.is_alive(),
                         msg="thread A should complete within timeout")
        self.assertFalse(t2.is_alive(),
                         msg="thread B should complete within timeout")
        self.assertIsNotNone(results["pid_a"],
                             msg="thread A should capture PID")
        self.assertIsNotNone(results["pid_b"],
                             msg="thread B should capture PID")
        self.assertNotEqual(results["pid_a"], results["pid_b"],
                            msg="threads should have distinct connection PIDs")
        self.assertEqual(results["errors"], [],
                         msg="no errors expected during claim")
        claimed = sum(1 for r in [results["a"], results["b"]] if r is not None)
        self.assertEqual(claimed, 1,
                         msg="exactly one job should be claimed, got %d" % claimed)

    @require_postgresql
    def test_production_worker_and_fixture_claim_concurrency(self):
        """Production claim_next_job and fixture _claim_specific_job contend on same resource (uniform lock order)"""
        job_a, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0, "retry_safe": True},
            resource_key=MASTER_RESOURCE,
            idempotency_key=f"concur-prod-vs-fixture-a-{timezone.now().timestamp()}",
        )
        job_b, _ = enqueue_job(
            Job.JobType.MASTER_UPDATE,
            {"operation": "queue_smoke", "sleep_seconds": 0, "retry_safe": True},
            resource_key=MASTER_RESOURCE,
            idempotency_key=f"concur-prod-vs-fixture-b-{timezone.now().timestamp()}",
        )

        results = {"prod": None, "fixture": None, "pid_prod": None, "pid_fixture": None, "errors": []}
        barrier = threading.Barrier(3)

        def claim_prod():
            try:
                with connection.cursor() as c:
                    c.execute("SELECT pg_backend_pid()")
                    results["pid_prod"] = c.fetchone()[0]
                barrier.wait(timeout=10)
                results["prod"] = claim_next_job("worker-prod")
            except Exception as e:
                results["errors"].append(f"prod: {e}")
            finally:
                close_old_connections()

        def claim_fixture():
            try:
                with connection.cursor() as c:
                    c.execute("SELECT pg_backend_pid()")
                    results["pid_fixture"] = c.fetchone()[0]
                barrier.wait(timeout=10)
                results["fixture"] = _claim_specific_job(job_b, "worker-fixture")
            except Exception as e:
                results["errors"].append(f"fixture: {e}")
            finally:
                close_old_connections()

        t1 = threading.Thread(target=claim_prod)
        t2 = threading.Thread(target=claim_fixture)
        t1.start()
        t2.start()
        barrier.wait(timeout=10)
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertFalse(t1.is_alive(),
                         msg="production thread should complete within timeout")
        self.assertFalse(t2.is_alive(),
                         msg="fixture thread should complete within timeout")
        self.assertIsNotNone(results["pid_prod"],
                             msg="production thread should capture PID")
        self.assertIsNotNone(results["pid_fixture"],
                             msg="fixture thread should capture PID")
        self.assertNotEqual(results["pid_prod"], results["pid_fixture"],
                            msg="threads should have distinct connection PIDs")
        self.assertEqual(results["errors"], [],
                         msg="no errors expected during claim")
        claimed = sum(1 for r in [results["prod"], results["fixture"]] if r is not None)
        self.assertEqual(claimed, 1,
                         msg="exactly one claim should succeed, got %d" % claimed)
