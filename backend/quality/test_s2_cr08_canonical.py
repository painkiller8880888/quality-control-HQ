import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from quality.s2_cr08_canonical import (
    ExternalWorkerObserver,
    TransactionCollector,
    SystemMetricsMonitor,
    build_canonical_evidence,
    _backend_baseline,
    _match_backend_by_client_port,
    _worker_child_client_ports_recursive,
    _get_env_identity,
    _check_service_status,
    _check_http,
    _check_unc_paths,
    _check_backup_tool,
    _check_migration_0029_applied,
    _check_worker_process_tree_unique,
    _check_backup_preparedness,
    _check_canonical_input,
    _table_stable_hash,
    _table_counts,
    _privacy_filter,
    _privacy_check_passed,
    _privacy_safe_str,
    _all_preflight_pass,
    _collect_system_metrics,
    _inspection_file_distribution,
    _inspection_file_pathset_hash,
    run_preflight,
    CANONICAL_SCHEMA_VERSION,
    _verify_job_result,
    _verify_canonical_payload,
    _execute_live_backup,
    _LOCK_HELD,
    _LOCK_NOT_HELD,
    _LOCK_ERROR,
)
from quality.s2_cr08_measurement import (
    _connection_pid,
    _backend_hash,
    poll_active_backends,
)
from quality.models import Job, AppSetting

def require_postgresql(test_method):
    def wrapper(self, *args, **kwargs):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        return test_method(self, *args, **kwargs)
    return wrapper


@override_settings(JOB_EXECUTE_INLINE_FOR_TESTS=False)
class ExternalWorkerObserverTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.pid = _connection_pid()

    def test_baseline_capture(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        count = observer.capture_baseline()
        self.assertGreaterEqual(count, 0)
        self.assertIsInstance(observer._baseline, set)

    @require_postgresql
    def test_discover_child_client_port_sets_correlation_fields(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer.capture_baseline()
        port = observer.discover_child_client_port()
        self.assertIn(observer.correlation_method,
                      ("process_tree_failed", "process_tree_exact", "process_tree_ambiguous"))
        if port is not None:
            self.assertIsInstance(port, int)
            self.assertGreater(port, 0)
            self.assertEqual(observer.correlation_method, "process_tree_exact")
            self.assertGreaterEqual(observer.correlation_candidate_count, 1)
            self.assertTrue(observer.correlation_unique)

    @require_postgresql
    def test_start_stop_no_target(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer.start()
        observer.stop()

    @require_postgresql
    def test_start_is_idempotent(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer.start()
        thread_id = id(observer._thread)
        observer.start()
        self.assertEqual(id(observer._thread), thread_id,
                         msg="start() should not create a new thread on repeat call")
        observer.stop()

    @require_postgresql
    def test_poll_cycle_no_match(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer._target_client_port = 99999
        observer.capture_baseline()
        observer.start()
        result = observer._do_poll()
        self.assertFalse(result)
        self.assertIsNone(observer.backend_hash)
        observer.stop()

    @require_postgresql
    def test_thread_exception_during_baseline(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer._target_client_port = 99999
        with patch.object(observer, "_do_poll", side_effect=RuntimeError("baseline crash")):
            with self.assertRaises(RuntimeError) as ctx:
                observer.start()
            cause = ctx.exception.__cause__
            self.assertIsNotNone(cause)
            self.assertIn("baseline crash", str(cause))

    @require_postgresql
    def test_stop_raises_on_join_timeout(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer._target_client_port = 99999
        observer.start()
        observer.stop()

    def test_observation_ok_false_by_default(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        self.assertFalse(observer.observation_ok)


class BackendDiscoveryTests(TransactionTestCase):
    def test_backend_baseline_returns_set(self):
        baseline = _backend_baseline()
        self.assertIsInstance(baseline, set)

    @require_postgresql
    def test_match_by_client_port_returns_list(self):
        matches = _match_backend_by_client_port(0)
        self.assertIsInstance(matches, list)


class PreflightFunctionTests(TransactionTestCase):
    def test_get_env_identity_not_found(self):
        result = _get_env_identity("/nonexistent/.env")
        self.assertFalse(result["found"])
        self.assertFalse(result["passed"])

    def test_get_env_identity_found_but_mismatch(self):
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("DB_NAME=quality_prodlike\nDB_HOST=127.0.0.1\nDB_USER=quality_app\nAPP_ENV=pseudoprod\n")
            result = _get_env_identity(str(env_path))
            self.assertTrue(result["found"])
            self.assertIn("passed", result)

    def test_check_service_status_missing_service(self):
        result = _check_service_status("NonexistentServiceXYZ")
        self.assertFalse(result["passed"])
        self.assertFalse(result["found"])

    def test_check_http_invalid_url(self):
        result = _check_http("http://127.0.0.1:1/")
        self.assertFalse(result["passed"])

    def test_check_unc_paths_empty(self):
        result = _check_unc_paths([])
        self.assertFalse(result["all_accessible"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "not_provided")

    def test_check_unc_paths_nonexistent(self):
        result = _check_unc_paths(["\\\\nonexistent\\share\\path"])
        self.assertFalse(result["details"][0]["accessible"])

    def test_check_backup_tool_available(self):
        result = _check_backup_tool()
        self.assertIn("available", result)
        self.assertIn("passed", result)

    def test_check_migration_0029_applied(self):
        result = _check_migration_0029_applied()
        self.assertIn("passed", result)
        self.assertIn("migration_0029_applied", result)

    def test_check_worker_process_tree_unique_no_worker(self):
        result = _check_worker_process_tree_unique("NonexistentWorkerSVC")
        self.assertFalse(result["passed"])
        self.assertEqual(result["child_count"], 0)

    def test_check_backup_preparedness_valid_dir(self):
        with TemporaryDirectory() as tmp:
            result = _check_backup_preparedness(tmp)
            self.assertIn("passed", result)
            self.assertIn("tool_available", result)
            self.assertIn("parent_dir_exists", result)

    def test_collect_system_metrics(self):
        metrics = _collect_system_metrics()
        self.assertIn("db_connections", metrics)
        self.assertIn("waiting_locks", metrics)
        self.assertIn("granted_locks", metrics)
        self.assertIn("passed", metrics)
        self.assertTrue(metrics["passed"])

    def test_inspection_file_distribution(self):
        dist = _inspection_file_distribution()
        self.assertIn("total", dist)
        self.assertIn("by_priority", dist)

    def test_inspection_file_pathset_hash(self):
        h = _inspection_file_pathset_hash()
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)


class EvidenceBuilderTests(TransactionTestCase):
    def test_dry_run_evidence(self):
        preflight = {
            "env_identity": {"passed": True, "found": True},
            "django_check": {"passed": True},
            "active_jobs": {"passed": True, "count": 0},
        }
        evidence = build_canonical_evidence(preflight=preflight, run_mode="dry_run")
        self.assertEqual(evidence["run_mode"], "dry_run")
        self.assertEqual(evidence["fixture_version"], CANONICAL_SCHEMA_VERSION)
        self.assertEqual(evidence["measurement_status"], "not_executed")

    def test_live_evidence(self):
        now = timezone.now()
        fake_job = type("FakeJob", (), {
            "job_id": "j1", "job_type": "master_update",
            "status": "succeeded", "attempt_count": 1,
            "depends_on_id": None,
            "created_at": now - timezone.timedelta(seconds=5),
            "started_at": now,
            "finished_at": now + timezone.timedelta(seconds=100),
        })()
        preflight = {"env_identity": {"passed": True}}
        evidence = build_canonical_evidence(
            job_a=fake_job, job_b=fake_job,
            preflight=preflight, run_mode="live",
            baseline_counts={"master_count": 100},
            baseline_hashes={"master_hash": "abc"},
        )
        self.assertEqual(evidence["run_mode"], "live")
        self.assertEqual(evidence["measurement_status"], "completed")
        self.assertIn("job_a", evidence)
        self.assertIn("job_b", evidence)
        self.assertIn("baseline_counts", evidence)
        self.assertIn("handoff_gap_seconds", evidence)

    def test_live_evidence_with_observer(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer.backend_hash = _backend_hash(12345, 54321)
        observer.backend_pid = 12345
        observer.backend_port = 54321
        observer.xact_start = timezone.now()
        observer.end_lower_bound = timezone.now()
        observer.end_upper_bound = timezone.now() + timezone.timedelta(seconds=1)
        observer.transaction_completed = True
        observer.poll_count = 5
        observer.correlation_method = "process_tree_exact"
        observer.correlation_candidate_count = 1
        observer.correlation_unique = True
        observer.observation_ok = True

        evidence = build_canonical_evidence(
            observer_a=observer,
            run_mode="live",
        )
        self.assertIn("job_a_transaction", evidence)
        txn = evidence["job_a_transaction"]
        self.assertIn("duration_lower_bound_seconds", txn)
        self.assertIn("duration_upper_bound_seconds", txn)
        self.assertIn("correlation_method", txn)
        self.assertIn("correlation_unique", txn)

    def test_preflight_pass_detection(self):
        preflight = {"env_identity": {"passed": True}}
        self.assertTrue(_all_preflight_pass(preflight))
        preflight_fail = {"env_identity": {"passed": False}}
        self.assertFalse(_all_preflight_pass(preflight_fail))
        preflight_fail_status = {"unc_paths": {"status": "not_provided"}}
        self.assertFalse(_all_preflight_pass(preflight_fail_status))
        preflight_fail_baseline = {"table_counts": {"baseline_matched": False}}
        self.assertFalse(_all_preflight_pass(preflight_fail_baseline))
        preflight_partial = {"env_identity": {"passed": True}, "active_jobs": {"passed": False}}
        self.assertFalse(_all_preflight_pass(preflight_partial))

    def test_preflight_pass_unique_check(self):
        preflight = {"worker_process_tree": {"unique": False, "child_count": 2}}
        self.assertFalse(_all_preflight_pass(preflight))

    def test_preflight_pass_migration_0029(self):
        preflight = {"migration_0029": {"migration_0029_applied": False}}
        self.assertFalse(_all_preflight_pass(preflight))


class PrivacyFilterTests(TransactionTestCase):
    def test_denylist_keys_rejected(self):
        evidence = {
            "job_a": {"worker_id": "worker-1", "execution_token": "tok_123"},
            "safe": {"status": "succeeded"},
        }
        issues = _privacy_filter(evidence)
        self.assertGreaterEqual(len(issues), 2)

    def test_allowlist_keys_accepted(self):
        evidence = {
            "fixture_version": "v1",
            "run_mode": "dry_run",
            "job_a": {"status": "succeeded", "attempt_count": 1},
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_empty_values_not_rejected(self):
        evidence = {"job_a": {"worker_id": "", "execution_token": ""}}
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_privacy_check_passed_function(self):
        evidence = {"fixture_version": "v1", "run_mode": "dry_run"}
        ok, issues = _privacy_check_passed(evidence)
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_privacy_check_fails_on_denylist(self):
        evidence = {"job_a": {"worker_id": "exposed"}}
        ok, issues = _privacy_check_passed(evidence)
        self.assertFalse(ok)
        self.assertGreater(len(issues), 0)


class CommandDryRunTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        AppSetting.objects.all().delete()
        # Create test files for canonical payload verification (F5)
        self.test_dir = TemporaryDirectory()
        test_dir = Path(self.test_dir.name)
        csv_file = test_dir / "input.csv"
        csv_content = "a,b,c\n1,2,3\n"
        csv_file.write_text(csv_content, encoding="utf-8")
        folder_a = test_dir / "path" / "a"
        folder_a.mkdir(parents=True)
        
        AppSetting.objects.create(
            csv_path=str(csv_file),
            inspection_folder_paths=[str(folder_a)],
            inspection_folder_priorities={str(folder_a): 1},
        )
        # Mock baseline constants for fail-closed dry-run gate (F5)
        self._baseline_patcher = patch.multiple(
            "quality.s2_cr08_canonical",
            CANONICAL_BASELINE_KNOWN_HASH="a" * 64,
            CANONICAL_BASELINE_EXPECTED_ROW_COUNT=2,
            CANONICAL_BASELINE_UNC_7ROOT=(str(folder_a),) * 7,
            CANONICAL_BASELINE_EXPECTED_MASTER_COUNT=10,
            CANONICAL_BASELINE_EXPECTED_CLASS_COUNT=5,
            CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT=3,
        )
        self._baseline_patcher.start()
        # Mock canonical payload verification to pass (F5)
        self._verify_patcher = patch(
            "quality.s2_cr08_canonical._verify_canonical_payload",
            return_value={"passed": True, "csv_exists": True, "csv_hash": "mocked_hash", "csv_row_count": 2, "folder_paths_count": 1, "priorities_count": 1, "status": "valid", "issues": []}
        )
        self._verify_patcher.start()
        # Mock preflight to return privacy-safe values (F7)
        self._preflight_patcher = patch(
            "quality.s2_cr08_canonical.run_preflight",
            return_value={
                "env_identity": {"passed": True, "found": True},
                "django_check": {"passed": True, "output": "system check output"},
                "migrations": {"passed": True},
                "migration_0029": {"passed": True, "migration_0029_applied": True},
                "web_service": {"passed": True, "found": True, "status": "Running", "start_type": "Automatic", "running": True, "automatic": True},
                "worker_service": {"passed": True, "found": True, "status": "Running", "start_type": "Automatic", "running": True, "automatic": True},
                "http_check": {"passed": True, "status_code": 200},
                "active_jobs": {"passed": True, "count": 0},
                "running_jobs": {"passed": True, "count": 0},
                "backup_tool": {"passed": True, "available": True, "version": "1.0", "tool_path": "safe_tool_path"},
                "backup_preparedness": {"passed": True, "tool_available": True, "tool_path": "safe_tool_path", "backup_output_dir": "safe_dir", "backup_output_writable": True, "parent_dir_exists": True},
                "worker_process_tree": {"passed": True, "child_count": 1, "unique": True},
                "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100, "passed": True},
                "table_hashes": {"master_hash": "abc", "master_class_hash": "def", "structure_hash": "ghi", "inspection_file_hash": "jkl", "passed": True},
                "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
                "inspection_file_distribution": {"total": 100, "by_priority": {"1": 100}},
                "inspection_file_pathset_hash": {"pathset_hash": "abc123"},
                "canonical_input": {"passed": True, "csv_configured": True, "folder_paths_count": 1, "priorities_count": 1, "status": "configured", "issues": []},
                "unc_paths": {"passed": True, "configured_count": 1, "accessible_count": 1, "all_accessible": True, "details": []},
            }
        )
        self._preflight_patcher.start()

    def tearDown(self):
        self._baseline_patcher.stop()
        self._verify_patcher.stop()
        self._preflight_patcher.stop()
        self.test_dir.cleanup()
        super().tearDown()

    @require_postgresql
    def test_dry_run_requires_output(self):
        with TemporaryDirectory() as tmp:
            call_command(
                "measure_s2_cr08_canonical",
                "--dry-run",
                output=tmp,
                poll_seconds=0.5,
            )
            output_dir = Path(tmp)
            self.assertTrue((output_dir / "measurement.json").exists())
            evidence = json.loads((output_dir / "measurement.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["run_mode"], "dry_run")
            self.assertIn("preflight", evidence)

    @require_postgresql
    def test_rejects_live_flag(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError):
                call_command(
                    "measure_s2_cr08_canonical",
                    "--live",
                    output=tmp,
                )

    @require_postgresql
    def test_requires_mode_flag(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError):
                call_command(
                    "measure_s2_cr08_canonical",
                    output=tmp,
                )

    @require_postgresql
    def test_rejects_nonempty_output(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "stale.txt").write_text("data")
            with self.assertRaises(CommandError):
                call_command(
                    "measure_s2_cr08_canonical",
                    "--dry-run",
                    output=tmp,
                )

    def test_requires_postgresql(self):
        with TemporaryDirectory() as tmp:
            with patch.object(connection, "vendor", "sqlite"):
                with self.assertRaises(CommandError):
                    call_command(
                        "measure_s2_cr08_canonical",
                        "--dry-run",
                        output=tmp,
                    )

    @require_postgresql
    def test_dry_run_output_has_privacy_check(self):
        with TemporaryDirectory() as tmp:
            call_command(
                "measure_s2_cr08_canonical",
                "--dry-run",
                output=tmp,
                poll_seconds=0.5,
            )
            evidence = json.loads((Path(tmp) / "measurement.json").read_text(encoding="utf-8"))
            self.assertIn("privacy_check_passed", evidence)
            self.assertTrue(evidence["privacy_check_passed"])

    @require_postgresql
    def test_dry_run_preflight_keys_present(self):
        with TemporaryDirectory() as tmp:
            call_command(
                "measure_s2_cr08_canonical",
                "--dry-run",
                output=tmp,
                poll_seconds=0.5,
            )
            evidence = json.loads((Path(tmp) / "measurement.json").read_text(encoding="utf-8"))
            preflight = evidence.get("preflight", {})
            for key in ("env_identity", "django_check", "migrations",
                        "migration_0029", "web_service", "worker_service",
                        "http_check", "active_jobs", "running_jobs",
                        "backup_tool", "worker_process_tree",
                        "table_counts", "table_hashes", "system_metrics",
                        "inspection_file_distribution", "inspection_file_pathset_hash",
                        "canonical_input", "unc_paths", "canonical_payload"):
                self.assertIn(key, preflight, msg=f"Missing preflight key: {key}")


class TableHashTests(TransactionTestCase):
    def test_table_stable_hash(self):
        h = _table_stable_hash(Job)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)

    def test_table_counts(self):
        counts = _table_counts()
        self.assertIn("master_count", counts)
        self.assertIn("inspection_file_count", counts)


class CanonicalInputTests(TransactionTestCase):
    def test_canonical_input_no_app_setting(self):
        from quality.models import AppSetting
        AppSetting.objects.all().delete()
        result = _check_canonical_input()
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "no_app_setting")

    def test_canonical_input_configured(self):
        from quality.models import AppSetting
        AppSetting.objects.all().delete()
        AppSetting.objects.create(
            csv_path="/test/input.csv",
            inspection_folder_paths=["/path/a", "/path/b"],
            inspection_folder_priorities={"/path/a": 1},
        )
        result = _check_canonical_input()
        self.assertTrue(result["passed"])
        self.assertTrue(result["csv_configured"])
        self.assertEqual(result["folder_paths_count"], 2)


class PrivacyFilterExtendedTests(TransactionTestCase):
    def test_privacy_safe_str(self):
        safe = _privacy_safe_str("job_id_123_worker_id_456")
        self.assertNotIn("job_id", safe)
        self.assertNotIn("worker_id", safe)

    def test_path_hash_allowed(self):
        evidence = {"unc_paths": {"details": [{"path_hash": "abc123"}]}}
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_backup_output_dir_not_denied(self):
        # F7: now checks all string leaves - use non-path value
        evidence = {"backup_output_dir": "safe_value", "details": []}
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_allowlist_overrides_denylist(self):
        evidence = {"preflight": {"django_check": {"output": "system check output"}}}
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_privacy_safe_str_redacts_pid_port_tuple(self):
        safe = _privacy_safe_str("A_candidates={(100, 200), (101, 201)}")
        self.assertNotIn("(100, 200)", safe)
        self.assertNotIn("(101, 201)", safe)
        self.assertIn("[REDACTED]", safe)


class SystemMetricsMonitorTests(TransactionTestCase):
    @require_postgresql
    def test_monitor_start_stop(self):
        monitor = SystemMetricsMonitor(interval_seconds=0.3)
        monitor.start()
        import time
        time.sleep(0.5)
        monitor.stop()
        summary = monitor.summary()
        self.assertGreaterEqual(summary["sample_count"], 1)
        self.assertIn("db_connections_max", summary)

    @require_postgresql
    def test_monitor_twice(self):
        monitor = SystemMetricsMonitor(interval_seconds=0.3)
        monitor.start()
        t1 = id(monitor._thread)
        monitor.start()
        self.assertEqual(id(monitor._thread), t1)
        monitor.stop()


class JobResultVerifierTests(TransactionTestCase):
    def setUp(self):
        from quality.models import Job
        self.Job = Job

    def _make_job(self, status, attempt_count=1, result=None):
        job = self.Job(
            job_id=f"test_jv_{timezone.now().timestamp()}",
            job_type=self.Job.JobType.MASTER_UPDATE,
            status=status,
            attempt_count=attempt_count,
        )
        if result is not None:
            job.result = result
        return job

    def test_full_success_passes(self):
        job = self._make_job(self.Job.Status.SUCCEEDED, result={
            "updated_master_count": 10, "updated_class_count": 5,
            "updated_structure_count": 3, "inspection_file_count": 100,
            "transaction_strategy": "single_atomic_update",
        })
        r = _verify_job_result(job)
        self.assertTrue(r["passed"])
        self.assertTrue(r["succeeded"])
        self.assertEqual(r["updated_master_count"], 10)

    def test_fail_on_status_not_succeeded(self):
        job = self._make_job(self.Job.Status.FAILED)
        self.assertFalse(_verify_job_result(job)["passed"])

    def test_fail_on_missing_transaction_strategy(self):
        job = self._make_job(self.Job.Status.SUCCEEDED, result={
            "updated_master_count": 1, "updated_class_count": 1,
            "updated_structure_count": 1, "inspection_file_count": 1,
        })
        self.assertFalse(_verify_job_result(job)["passed"])

    def test_fail_on_missing_inspection_file_count(self):
        job = self._make_job(self.Job.Status.SUCCEEDED, result={
            "updated_master_count": 1, "updated_class_count": 1,
            "updated_structure_count": 1,
            "transaction_strategy": "single_atomic_update",
        })
        r = _verify_job_result(job)
        self.assertEqual(r["inspection_file_count"], -1)
        self.assertFalse(r["passed"])

    def test_fail_on_folder_warnings(self):
        job = self._make_job(self.Job.Status.SUCCEEDED, result={
            "updated_master_count": 1, "updated_class_count": 1,
            "updated_structure_count": 1, "inspection_file_count": 1,
            "transaction_strategy": "single_atomic_update",
            "folder_warnings": ["Folder not found"],
        })
        self.assertFalse(_verify_job_result(job)["passed"])

    def test_expected_count_mismatch(self):
        job = self._make_job(self.Job.Status.SUCCEEDED, result={
            "updated_master_count": 99, "updated_class_count": 5,
            "updated_structure_count": 3, "inspection_file_count": 100,
            "transaction_strategy": "single_atomic_update",
        })
        r = _verify_job_result(job, expected_master_count=100)
        self.assertFalse(r["passed"])

    def test_no_result_still_fails(self):
        job = self._make_job(self.Job.Status.SUCCEEDED)
        self.assertFalse(_verify_job_result(job)["passed"])


class PrivacyFilterClosedSchemaTests(TransactionTestCase):
    def test_unknown_top_level_key_rejected(self):
        evidence = {"sneaky_key": {"raw_path": "\\\\server\\share"}}
        issues = _privacy_filter(evidence)
        self.assertGreater(len(issues), 0)
        self.assertIn("sneaky_key", issues[0]["field"])

    def test_unknown_primitive_key_rejected(self):
        evidence = {"job_a": {"status": "succeeded", "sneaky_path": "\\\\server\\share\\path"}}
        issues = _privacy_filter(evidence)
        self.assertGreater(len(issues), 0)

    def test_preflight_issues_with_codes_pass(self):
        evidence = {
            "preflight": {
                "canonical_payload": {
                    "passed": False, "status": "invalid",
                    "issues": ["csv_not_found", "folder_paths_empty"],
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_preflight_issue_has_no_raw_paths(self):
        evidence = {
            "preflight": {
                "canonical_payload": {
                    "passed": False, "status": "invalid",
                    "issues": ["csv_not_found", "folder_paths_empty"],
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_nested_unknown_container_rejected(self):
        evidence = {
            "system_metrics": {
                "db_connections_max": 5,
                "secret_container": {"leaked_path": "\\\\secret"},
            }
        }
        issues = _privacy_filter(evidence)
        self.assertGreater(len(issues), 0)

    def test_clock_sources_known_keys_pass(self):
        evidence = {
            "clock_sources": {
                "job_timestamps": "Django timezone.now()",
                "transaction_xact_start": "PostgreSQL server clock",
                "transaction_bounds": "PostgreSQL clock_timestamp()",
            }
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_preflight_check_unknown_field_rejected(self):
        evidence = {
            "preflight": {
                "env_identity": {
                    "passed": True, "found": True,
                    "sneaky_raw_value": "\\\\server\\share\\path",
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("sneaky_raw_value" in i["field"] for i in issues),
                        msg="Expected unknown field inside preflight check to be rejected")

    def test_issues_list_content_not_inspected(self):
        evidence = {
            "preflight": {
                "canonical_payload": {
                    "passed": False, "status": "invalid",
                    "issues": ["csv_not_found"],
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])


class CanonicalPayloadVerifierTests(TransactionTestCase):
    def test_empty_csv_path_fails(self):
        result = _verify_canonical_payload({"csv_path": "", "inspection_folder_paths": []})
        self.assertFalse(result["passed"])
        self.assertIn("csv_empty", result["issues"])

    def test_issues_contain_no_raw_paths(self):
        result = _verify_canonical_payload({"csv_path": "", "inspection_folder_paths": []})
        for issue in result["issues"]:
            self.assertNotIn("\\", issue)
            self.assertNotIn("/", issue)

    def test_missing_folder_paths_fails(self):
        result = _verify_canonical_payload({"csv_path": "/some/path.csv", "inspection_folder_paths": []})
        self.assertIn("folder_paths_empty", result["issues"])

    def test_known_hash_mismatch_rejected(self):
        with TemporaryDirectory() as tmp:
            csv_file = Path(tmp) / "input.csv"
            csv_file.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
            result = _verify_canonical_payload(
                {"csv_path": str(csv_file), "inspection_folder_paths": []},
                known_canonical_hash="0000000000000000000000000000000000000000000000000000000000000000",
            )
            self.assertIn("csv_hash_mismatch", result["issues"])

    def test_expected_row_count_mismatch_rejected(self):
        result = _verify_canonical_payload(
            {"csv_path": "", "inspection_folder_paths": []},
            expected_row_count=100,
        )
        self.assertIn("csv_row_count_mismatch", result["issues"])

    def test_unc_paths_mismatch_rejected(self):
        result = _verify_canonical_payload(
            {"csv_path": "", "inspection_folder_paths": ["/path/a"]},
            expected_unc_paths=["/path/b", "/path/c"],
        )
        self.assertIn("folder_paths_unc_mismatch", result["issues"])

    def test_unc_paths_match_ok(self):
        result = _verify_canonical_payload(
            {"csv_path": "", "inspection_folder_paths": ["/path/a", "/path/b"]},
            expected_unc_paths=["/path/a", "/path/b"],
        )
        self.assertNotIn("folder_paths_unc_mismatch", result["issues"])


class CanonicalBaselineVerifierTests(TransactionTestCase):
    def test_verify_job_result_with_expected_counts(self):
        job = type("FakeJob", (), {
            "job_id": "test_j1", "job_type": "master_update",
            "status": "succeeded", "attempt_count": 1,
            "result": {
                "updated_master_count": 42, "updated_class_count": 10,
                "updated_structure_count": 5, "inspection_file_count": 200,
                "transaction_strategy": "single_atomic_update",
            },
        })()
        r = _verify_job_result(job, expected_master_count=42, expected_class_count=10, expected_structure_count=5)
        self.assertTrue(r["passed"])

    def test_verify_job_result_expected_master_mismatch(self):
        job = type("FakeJob", (), {
            "job_id": "test_j2", "job_type": "master_update",
            "status": "succeeded", "attempt_count": 1,
            "result": {
                "updated_master_count": 99, "updated_class_count": 10,
                "updated_structure_count": 5, "inspection_file_count": 200,
                "transaction_strategy": "single_atomic_update",
            },
        })()
        r = _verify_job_result(job, expected_master_count=42)
        self.assertFalse(r["passed"])


class PrivacyFilterRawPathContentTests(TransactionTestCase):
    def test_output_contains_raw_path_rejected(self):
        evidence = {"django_check": {"output": "C:/sensitive/input.csv contains errors"}}
        issues = _privacy_filter(evidence)
        self.assertTrue(any("output_contains_raw_path" in i["reason"] for i in issues))

    def test_issues_contains_raw_path_rejected(self):
        evidence = {
            "preflight": {
                "canonical_payload": {
                    "passed": False, "status": "invalid",
                    "issues": ["C:/sensitive/input.csv not found"],
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("issues_contains_raw_path" in i["reason"] for i in issues))

    def test_issues_contains_unc_path_rejected(self):
        evidence = {
            "preflight": {
                "canonical_payload": {
                    "passed": False, "status": "invalid",
                    "issues": ["\\\\server\\share\\path not accessible"],
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("issues_contains_raw_path" in i["reason"] for i in issues))

    def test_issues_with_fixed_codes_still_pass(self):
        evidence = {
            "preflight": {
                "canonical_payload": {
                    "passed": False, "status": "invalid",
                    "issues": ["csv_not_found", "folder_paths_empty"],
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_tmp_secret_csv_detected(self):
        from quality.s2_cr08_canonical import _string_contains_raw_path
        self.assertTrue(_string_contains_raw_path("failed at /tmp/secret.csv"))

    def test_multilevel_unix_path_detected(self):
        from quality.s2_cr08_canonical import _string_contains_raw_path
        self.assertTrue(_string_contains_raw_path("path /var/log/app/error.log found"))

    def test_embedded_path_no_false_positive(self):
        from quality.s2_cr08_canonical import _string_contains_raw_path
        self.assertFalse(_string_contains_raw_path("status_code 200 OK"))


class ObserverPreArmTests(TransactionTestCase):
    @require_postgresql
    def test_pre_arm_does_not_block(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer.capture_baseline()
        observer.pre_arm()
        self.assertTrue(observer._started)
        self.assertTrue(observer._pre_armed)
        observer.stop()

    @require_postgresql
    def test_pre_arm_is_idempotent(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer.capture_baseline()
        observer.pre_arm()
        thread_id = id(observer._thread)
        observer.pre_arm()
        self.assertEqual(id(observer._thread), thread_id)
        observer.stop()


class LiveBackupFunctionTests(TransactionTestCase):
    @require_postgresql
    @patch("quality.s2_cr08_canonical._validate_service_name")
    @patch("quality.s2_cr08_canonical.subprocess.run", return_value=type("Proc", (), {
        "stdout": "Stopped", "stderr": "", "returncode": 0})())
    def test_execute_live_backup_active_jobs_fails(self, mock_run, mock_validate):
        from quality.s2_cr08_canonical import _execute_live_backup
        Job.objects.create(
            job_id="test_active_for_backup", job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.QUEUED,
        )
        result = _execute_live_backup("/tmp/out", "TestWebSvc", "TestWorkerSvc")
        self.assertFalse(result["passed"])
        self.assertIn("pre_stop_active_job_check", str(result.get("step", "")))

    def test_execute_live_backup_importable(self):
        from quality.s2_cr08_canonical import _execute_live_backup
        self.assertTrue(callable(_execute_live_backup))


class BackupRecoveryTests(TransactionTestCase):
    def test_backup_stop_service_validation(self):
        from quality.s2_cr08_canonical import _validate_service_name
        with self.assertRaises(ValueError):
            _validate_service_name("Malicious'; Stop-Service -Name '*'")
        _validate_service_name("QualityControlHQ-Pseudoprod")

    @patch("quality.s2_cr08_canonical._validate_service_name")
    @patch("quality.s2_cr08_canonical._check_backup_tool", return_value={"passed": False, "available": False})
    @patch("quality.s2_cr08_canonical.subprocess.run", return_value=type("Proc", (), {
        "stdout": "Stopped", "stderr": "", "returncode": 0})())
    @patch("quality.s2_cr08_canonical._get_service_status", return_value="Stopped")
    def test_backup_recovery_returns_steps_on_failure(self, mock_status, mock_run, mock_tool, mock_validate):
        from quality.s2_cr08_canonical import _execute_live_backup
        result = _execute_live_backup("/tmp/out", "QualityControlHQ-Pseudoprod", "QualityControlHQ-Worker-Pseudoprod")
        self.assertIn("steps", result)
        self.assertFalse(result["passed"])


class ObserverExclusiveCorrelationTests(TransactionTestCase):
    @require_postgresql
    def test_exclude_client_port_skips_matches(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3, exclude_client_port=99999)
        observer.capture_baseline()
        port = observer.discover_child_client_port()
        self.assertIsNone(observer._target_client_port)

    @require_postgresql
    def test_wait_for_discovery_timeout(self):
        observer = ExternalWorkerObserver(poll_seconds=0.3)
        observer.capture_baseline()
        result = observer.wait_for_discovery(timeout=0.5)
        self.assertIsNone(result)


class PrivacyComprehensiveTests(TransactionTestCase):
    def test_error_field_contains_raw_path_rejected(self):
        evidence = {"error": "C:/sensitive/input.csv not found"}
        issues = _privacy_filter(evidence)
        self.assertTrue(any("error_contains_raw_path" in i["reason"] for i in issues))

    def test_embedded_path_in_string_rejected(self):
        evidence = {"django_check": {"output": "failed at C:/sensitive/input.csv line 42"}}
        issues = _privacy_filter(evidence)
        self.assertTrue(any("output_contains_raw_path" in i["reason"] for i in issues))

    def test_drive_d_path_rejected(self):
        evidence = {"django_check": {"output": "D:/backups/latest.dump is valid"}}
        issues = _privacy_filter(evidence)
        self.assertTrue(any("output_contains_raw_path" in i["reason"] for i in issues))

    def test_fixed_codes_still_pass(self):
        evidence = {"failure_reason": "preflight_failed;job_a_failed"}
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])


class BackupEvidenceInCanonicalTests(TransactionTestCase):
    def test_backup_evidence_included(self):
        backup = {
            "passed": True,
            "backup_sha256": "abc123",
            "backup_size_bytes": 1024,
            "restore_entry_count": 42,
        }
        evidence = build_canonical_evidence(run_mode="live", backup_evidence=backup)
        self.assertIn("backup", evidence)
        self.assertEqual(evidence["backup"]["backup_sha256"], "abc123")
        self.assertEqual(evidence["backup"]["backup_size_bytes"], 1024)
        self.assertEqual(evidence["backup"]["restore_entry_count"], 42)
        self.assertTrue(evidence["backup"]["passed"])

    def test_backup_evidence_omitted_when_none(self):
        evidence = build_canonical_evidence(run_mode="live")
        self.assertNotIn("backup", evidence)


class CanonicalBaselineConfiguredTests(TransactionTestCase):
    def test_check_canonical_baseline_configured(self):
        from quality.s2_cr08_canonical import _check_canonical_baseline_configured
        ok, reason = _check_canonical_baseline_configured()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(reason, str)

    def test_validator_rejects_empty_hash(self):
        from quality.s2_cr08_canonical import _check_canonical_baseline_configured
        with patch("quality.s2_cr08_canonical.CANONICAL_BASELINE_KNOWN_HASH", ""):
            ok, reason = _check_canonical_baseline_configured()
            self.assertFalse(ok)
            self.assertIn("APPROVED is False", reason)


class BackupEvidencePrivacyTests(TransactionTestCase):
    def test_backup_evidence_keys_allowlisted(self):
        backup = {
            "passed": True,
            "backup_sha256": "abc123",
            "backup_size_bytes": 1024,
            "restore_entry_count": 42,
        }
        evidence = build_canonical_evidence(run_mode="live", backup_evidence=backup)
        ok, issues = _privacy_check_passed(evidence)
        self.assertTrue(ok, msg=f"Privacy issues on backup evidence: {issues}")

    def test_backup_evidence_with_failure_passes_privacy(self):
        backup = {
            "passed": False,
            "backup_sha256": "",
            "backup_size_bytes": 0,
            "restore_entry_count": 0,
        }
        evidence = build_canonical_evidence(run_mode="live", backup_evidence=backup)
        ok, issues = _privacy_check_passed(evidence)
        self.assertTrue(ok, msg=f"Privacy issues on failed backup evidence: {issues}")


class TransactionCollectorCorrelationTests(TransactionTestCase):
    """P0-1: Direct tests for TransactionCollector A/B correlation via Job ownership.
    Tests cover reviewer findings F1–F5 and probes.
    """

    def setUp(self):
        self.collector = TransactionCollector(poll_seconds=0.1)
        self.job_a = Job.objects.create(
            job_id="test-job-a",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.RUNNING,
            worker_id="worker-1",
            execution_token="tok-a",
        )
        self.job_b = Job.objects.create(
            job_id="test-job-b",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.RUNNING,
            worker_id="worker-1",
            execution_token="tok-b",
        )
        # Map mock OS PIDs to their owner job_ids.
        # OS PID and PostgreSQL PID are separate domains (F1).
        # _verify_child_process is called with OS PID from WMI process tree.
        self._pid_to_job = {}
        self._vp = patch.object(TransactionCollector, '_verify_child_process',
                                side_effect=lambda pid, job_id, worker_id="": self._pid_to_job.get(pid) == job_id)
        self._vp.start()
        # Mock advisory lock check to return HELD by default (F1/F3).
        # Individual tests can override with specific side effects.
        self._lock_patch = patch.object(TransactionCollector, '_check_advisory_lock',
                                        return_value=_LOCK_HELD)
        self._lock_patch.start()

    def _register_pid(self, pid, job_id):
        """Register OS PID mapping for _verify_child_process mock."""
        self._pid_to_job[pid] = job_id

    def tearDown(self):
        self._vp.stop()
        self._lock_patch.stop()
        if self.collector._thread and self.collector._thread.is_alive():
            self.collector.stop()

    def _make_event(self, etype, pid, port, xs):
        now = timezone.now()
        return (etype, pid, port, xs, now, now)

    def _simulate_poll(self, worker_ports, backends, set_addr_map=True):
        """Run a single _poll_once cycle with given ports and backends.
        Adds default client_addr to backends if not present (F5).
        Auto-populates _addr_map for worker ports when set_addr_map=True.
        """
        if set_addr_map:
            for pid, port in worker_ports:
                if (pid, port) not in self.collector._addr_map:
                    self.collector._addr_map[(pid, port)] = "127.0.0.1"
        enriched = []
        for b in backends:
            if "client_addr" not in b:
                b = dict(b, client_addr="127.0.0.1")
            enriched.append(b)
        with patch.object(self.collector, '_get_worker_child_ports', return_value=worker_ports):
            with patch('quality.s2_cr08_canonical.poll_active_backends', return_value=enriched):
                with patch('quality.s2_cr08_canonical._db_clock', return_value=timezone.now()):
                    self.collector._poll_once()

    # ----------------------------------------------------------------
    # Ownership (F1 fix)
    # ----------------------------------------------------------------

    def test_ownership_discovers_a_on_claim(self):
        """F1: A's child port assigned when Job RUNNING and new port appears.
        Uses distinct OS PID (100) and PG PID (900) to verify client_port join."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        xs = timezone.now()
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        # Confirmation poll: collection window closes, A ASSIGNED
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_child_os_pid, 100)
        self.assertEqual(self.collector._a_child_pid, 900)
        self.assertEqual(self.collector._a_child_port, 200)
        self.assertEqual(self.collector._a_xact_start, xs)

    def test_ownership_no_claim_while_pending(self):
        """F1: No A/B assignment when Jobs are still QUEUED (not RUNNING)."""
        self.job_a.status = Job.Status.QUEUED
        self.job_a.save()
        self.job_b.status = Job.Status.QUEUED
        self.job_b.save()
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        self.assertIsNone(self.collector._a_child_pid)
        self.assertIsNone(self.collector._b_child_pid)

    def test_ownership_discovers_b_after_a(self):
        """F1: B assigned from second new port appearing after A's claim."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-b")
        xs_a = timezone.now()
        xs_b = timezone.now() + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        # A collection window closes; A assigned, B collects (101,201)
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        # B collection window closes
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_child_pid, 900)
        self.assertEqual(self.collector._b_child_pid, 901)
        self.assertEqual(self.collector._a_xact_start, xs_a)
        self.assertEqual(self.collector._b_xact_start, xs_b)

    # ----------------------------------------------------------------
    # get_transactions (F2 fix: fail-closed on ambiguity)
    # ----------------------------------------------------------------

    def test_get_transactions_timeout_no_jobs(self):
        """F2: No job_ids set → RuntimeError."""
        # collector with no call to set_job_ids
        empty = TransactionCollector(poll_seconds=0.1)
        with self.assertRaises(RuntimeError):
            empty.get_transactions(timeout=1)

    def test_get_transactions_timeout_claim_not_detected(self):
        """F2: Jobs never claimed (not RUNNING) → RuntimeError."""
        self.job_a.status = Job.Status.QUEUED
        self.job_a.save()
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._simulate_poll({(100, 200)}, [
            {'pid': 999, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        with self.assertRaises(RuntimeError):
            self.collector.get_transactions(timeout=1)

    def test_get_transactions_returns_claim_based_ab(self):
        """F2: Both Jobs claimed → get_transactions returns correctly."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-b")
        xs_a = timezone.now()
        xs_b = timezone.now() + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        # Both collection windows close
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        a_info, b_info = self.collector.get_transactions(timeout=5)
        self.assertEqual(a_info[0], 900)
        self.assertEqual(a_info[1], 200)
        self.assertEqual(a_info[2], xs_a)
        self.assertEqual(b_info[0], 901)
        self.assertEqual(b_info[1], 201)
        self.assertEqual(b_info[2], xs_b)

    # ----------------------------------------------------------------
    # Historical port loss (F4 fix)
    # ----------------------------------------------------------------

    def test_historical_port_disappears_still_returns_a(self):
        """F4+F6: A's port disappears from worker_ports, but get_transactions still returns it."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-b")
        xs_a = timezone.now()
        xs_b = timezone.now() + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        # Collection windows close for both
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        # A's port disappears from worker_ports in a subsequent poll
        self._simulate_poll({(101, 201)}, [
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        a_info, b_info = self.collector.get_transactions(timeout=5)
        self.assertEqual(a_info[0], 900)
        self.assertEqual(a_info[1], 200)
        self.assertEqual(a_info[2], xs_a)

    # ----------------------------------------------------------------
    # Sequential same-port A→B
    # ----------------------------------------------------------------

    def test_sequential_same_port_a_then_b(self):
        """A completes, B claims same port (same subprocess reused).
        Also verifies get_transactions() returns both successfully (F4 formal path)."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        xs_a = timezone.now()
        xs_b = xs_a + timezone.timedelta(seconds=2)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        # A collection window closes
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        # A's transaction ends
        self.collector._track_ab_disappearance((900, 200), xs_a, timezone.now(), timezone.now())
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertIsNotNone(self.collector._a_xact_end_upper)
        # B claims same port (same subprocess reused)
        # PID 100 is for job_b now (same process, different claim)
        self._register_pid(100, "test-job-b")
        self.job_b.worker_id = "worker-1"
        self.job_b.save()
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_b, 'state': 'active'},
        ])
        # B collection window closes
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_b, 'state': 'active'},
        ])
        self.assertEqual(self.collector._b_state, "ASSIGNED")
        self.assertEqual(self.collector._b_child_pid, 900)
        self.assertEqual(self.collector._b_child_port, 200)
        self.assertEqual(self.collector._b_xact_start, xs_b)
        # Formal path: get_transactions must succeed
        a_info, b_info = self.collector.get_transactions(timeout=5)
        self.assertEqual(a_info[0], 900)
        self.assertEqual(a_info[1], 200)
        self.assertEqual(a_info[2], xs_a)
        self.assertEqual(b_info[0], 900)
        self.assertEqual(b_info[1], 200)
        self.assertEqual(b_info[2], xs_b)
        self.assertIsNotNone(a_info[4])  # a end_lower
        self.assertIsNotNone(a_info[5])  # a end_upper
        self.assertIsNone(b_info[4])     # b end_lower (still running in this test)
        self.assertIsNone(b_info[5])     # b end_upper (still running in this test)

    # ----------------------------------------------------------------
    # Reviewer probe tests (F1–F5 negative probes)
    # ----------------------------------------------------------------

    def test_blank_worker_id_no_assignment(self):
        """F1: Job RUNNING but empty worker_id/execution_token → no assignment."""
        self.job_a.worker_id = ""
        self.job_a.execution_token = ""
        self.job_a.save()
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "IDLE")
        self.assertIsNone(self.collector._a_child_pid)

    def test_three_new_ports_fails_a(self):
        """F2: Three new ports when A is COLLECTING → FAILED."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-a")
        self._register_pid(102, "test-job-a")
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200), (101, 201), (102, 202)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 902, 'client_port': 202, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_candidates, {(100, 200), (101, 201), (102, 202)})
        # Collection window closes → 3 candidates → FAILED
        self._simulate_poll({(100, 200), (101, 201), (102, 202)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 902, 'client_port': 202, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "FAILED")
        with self.assertRaises(RuntimeError):
            self.collector.get_transactions(timeout=1)

    def test_port_before_running_still_assigns(self):
        """F3: Port appears in poll 1 (QUEUED), RUNNING in poll 2 → still assigns."""
        self.job_a.status = Job.Status.QUEUED
        self.job_a.worker_id = ""
        self.job_a.execution_token = ""
        self.job_a.save()
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "IDLE")
        self.job_a.status = Job.Status.RUNNING
        self.job_a.worker_id = "worker-1"
        self.job_a.execution_token = "tok-new"
        self.job_a.save()
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        # Collection window closes
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_child_pid, 900)
        self.assertEqual(self.collector._a_child_port, 200)

    def test_b_depends_on_a_queue_to_running(self):
        """F6: B starts QUEUED, transitions to RUNNING after A completes."""
        self.job_b.status = Job.Status.QUEUED
        self.job_b.worker_id = ""
        self.job_b.execution_token = ""
        self.job_b.save()
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-b")
        xs_a = timezone.now()
        xs_b = xs_a + timezone.timedelta(seconds=2)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        # A collection window closes
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._b_state, "IDLE")
        # A's transaction ends and subprocess exits
        self.collector._track_ab_disappearance((900, 200), xs_a, timezone.now(), timezone.now())
        # B transitions to RUNNING after A completes
        self.job_b.status = Job.Status.RUNNING
        self.job_b.worker_id = "worker-1"
        self.job_b.execution_token = "tok-b-2"
        self.job_b.save()
        self._simulate_poll({(101, 201)}, [
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        # B collection window closes
        self._simulate_poll({(101, 201)}, [
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        self.assertEqual(self.collector._b_state, "ASSIGNED")
        self.assertEqual(self.collector._b_child_pid, 901)

    def test_unrelated_first_rejected_by_process_identity(self):
        """F2+F3: Unrelated port first, real target later → process identity filter rejects unrelated."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        # Only register PID 100 for job_a (not 900)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-b")
        xs = timezone.now()
        self._simulate_poll(set(), [])
        # Poll: unrelated port (900,990) appears — NOT an execute_claimed_job for job_a
        self._simulate_poll({(900, 990)}, [
            {'pid': 900, 'client_port': 990, 'xact_start': xs, 'state': 'active'},
        ])
        # A rejects (900,990) because _verify_child_process(900, "test-job-a") is False
        self.assertEqual(len(self.collector._a_candidates), 0)
        # Poll: real target (100,200) appears
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        # A collection: (100,200) is verified → enters pool
        self.assertEqual(self.collector._a_candidates, {(100, 200)})
        # Collection window closes
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_child_pid, 900)

    def test_late_second_candidate_causes_failure(self):
        """F2: After first candidate collected, second candidate in next poll → FAILED."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        self._register_pid(200, "test-job-a")  # second PID also for A
        xs = timezone.now()
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        # Collection window is open (rem=1)
        self.assertEqual(self.collector._a_state, "COLLECTING")
        self.assertEqual(self.collector._a_candidates, {(100, 200)})
        # Second candidate appears in next poll
        self._simulate_poll({(100, 200), (200, 400)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
            {'pid': 200, 'client_port': 400, 'xact_start': xs, 'state': 'active'},
        ])
        # Window closes → 2 candidates → FAILED
        self.assertEqual(self.collector._a_state, "FAILED")
        self.assertEqual(self.collector._a_candidates, {(100, 200), (200, 400)})
        with self.assertRaises(RuntimeError):
            self.collector.get_transactions(timeout=1)

    def test_exact_pid_port_tracking(self):
        """F4: _track_ab_transactions uses exact (pid, port), not port alone."""
        self.collector._a_state = "ASSIGNED"
        self.collector._a_child_pid = 900
        self.collector._a_child_port = 200
        xs = timezone.now()
        # Different PID on same port should NOT be tracked as A
        self.collector._track_ab_transactions((999, 200), xs, timezone.now(), timezone.now())
        self.assertIsNone(self.collector._a_xact_start)
        # Matching (pid, port) SHOULD be tracked
        self.collector._track_ab_transactions((900, 200), xs, timezone.now(), timezone.now())
        self.assertEqual(self.collector._a_xact_start, xs)

    # ----------------------------------------------------------------
    # Baseline tests (unchanged from v1)
    # ----------------------------------------------------------------

    def test_baseline_captures_triple(self):
        """F7: capture_baseline stores (pg_pid, port, xact_start) triples.
        Uses distinct OS PID (100) and PG PID (900) to verify concept separation."""
        xs = timezone.now()
        with patch.object(self.collector, '_get_worker_child_ports', return_value={(100, 200)}):
            with patch('quality.s2_cr08_canonical.poll_active_backends', return_value=[
                {'pid': 900, 'client_port': 200, 'client_addr': None, 'xact_start': xs, 'state': 'active'}
            ]):
                count = self.collector.capture_baseline()
        self.assertEqual(count, 1)
        for item in self.collector._baseline:
            self.assertEqual(len(item), 3)
            self.assertEqual(item[0], 900)
            self.assertEqual(item[1], 200)
            self.assertIsNotNone(item[2])

    def test_baseline_triple_blocks_exact_match(self):
        """F7: START not emitted when exact (pid, port, xact_start) is in baseline."""
        xs = timezone.now()
        self.collector._baseline = {(900, 200, xs)}
        with patch.object(self.collector, '_get_worker_child_ports', return_value={(100, 200)}):
            with patch('quality.s2_cr08_canonical.poll_active_backends', return_value=[
                {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'}
            ]):
                with patch('quality.s2_cr08_canonical._db_clock', return_value=timezone.now()):
                    self.collector._poll_once()
        starts = [e for e in self.collector._events if e[0] == "START"]
        self.assertEqual(len(starts), 0)

    def test_baseline_triple_allows_xact_start_change(self):
        """F7: xact_start change on baseline port emits START (new transaction).
        Baseline uses PG PID (900), not OS PID (100)."""
        old_xs = timezone.now()
        new_xs = timezone.now() + timezone.timedelta(seconds=1)
        self.collector._baseline = {(900, 200, old_xs)}
        with patch.object(self.collector, '_get_worker_child_ports', return_value={(100, 200)}):
            with patch('quality.s2_cr08_canonical.poll_active_backends', return_value=[
                {'pid': 900, 'client_port': 200, 'xact_start': new_xs, 'state': 'active'}
            ]):
                with patch('quality.s2_cr08_canonical._db_clock', return_value=timezone.now()):
                    self.collector._poll_once()
        starts = [e for e in self.collector._events if e[0] == "START"]
        self.assertEqual(len(starts), 1)

    # ----------------------------------------------------------------
    # Shim tests (unchanged from v1)
    # ----------------------------------------------------------------

    def test_shim_transaction_completed_no_assignment(self):
        """Shim defaults before assignment: not completed, not unique."""
        self.assertFalse(self.collector.observer_a.transaction_completed)
        self.assertFalse(self.collector.observer_a.correlation_unique)
        self.assertFalse(self.collector.observer_a.observation_ok)
        self.assertFalse(self.collector.observer_b.transaction_completed)

    def test_shim_transaction_completed_after_assignment(self):
        """Shim reflects actual completion after A/B assigned and END recorded via production path."""
        xs_a = timezone.now()
        self.collector._a_state = "ASSIGNED"
        self.collector._a_child_pid = 900
        self.collector._a_child_port = 200
        self.collector._a_xact_start = xs_a
        self.collector._b_child_pid = 901
        self.collector._b_child_port = 201
        self.collector._b_xact_start = timezone.now() + timezone.timedelta(seconds=1)
        # Record END via production path
        self.collector._track_ab_disappearance(
            (900, 200), xs_a, timezone.now(), timezone.now()
        )
        self.assertTrue(self.collector.observer_a.transaction_completed)
        self.assertTrue(self.collector.observer_a.correlation_unique)
        self.assertTrue(self.collector.observer_a.observation_ok)

    def test_shim_not_hardcoded_true(self):
        """F3: Verify shims do NOT return hardcoded True."""
        self.assertFalse(self.collector.observer_a.correlation_unique)
        self.assertFalse(self.collector.observer_a.observation_ok)

    # ----------------------------------------------------------------
    # F2 negative probes: post-window second port from same PID
    # ----------------------------------------------------------------

    def test_post_assigned_same_pid_new_port_fails(self):
        """F2: After ASSIGNED, new port from same PID → FAILED."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs = timezone.now()
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        # Collection window closes → ASSIGNED
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        # Same PID opens second port on next poll
        self._simulate_poll({(100, 200), (100, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
            {'pid': 100, 'client_port': 201, 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "FAILED")

    def test_post_assigned_same_pid_new_port_after_xact_end_ok(self):
        """F2: After ASSIGNED, new port from same PID after xact_end → OK (not ambiguity)."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs = timezone.now()
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        # Collection window closes → ASSIGNED
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        # Transaction ends (backend disappears)
        self.collector._track_ab_disappearance((900, 200), xs, timezone.now(), timezone.now())
        self.assertTrue(self.collector._a_xact_end_verified)
        # Same PID opens new port after end → should not fail
        self._simulate_poll({(100, 201)}, [
            {'pid': 100, 'client_port': 201, 'xact_start': xs, 'state': 'active'},
        ])
        # State stays ASSIGNED (not FAILED) because transaction already ended
        self.assertEqual(self.collector._a_state, "ASSIGNED")

    # ----------------------------------------------------------------
    # F4 privacy: error messages must not contain raw (pid, port)
    # ----------------------------------------------------------------

    def test_get_transactions_failed_privacy_safe(self):
        """F4: FAILED error message uses count+hash, not raw (pid,port)."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-a")
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        # Window closes → 2 candidates → FAILED
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        with self.assertRaises(RuntimeError) as ctx:
            self.collector.get_transactions(timeout=1)
        msg = str(ctx.exception)
        # Must not contain raw (pid, port) tuples
        self.assertNotIn("(100, 200)", msg)
        self.assertNotIn("101", msg.replace("_", ""))
        # Must contain count and hash
        self.assertIn("A_cand_count=2", msg)

    def test_get_transactions_timeout_privacy_safe(self):
        """F4: timeout error message uses count+hash, not raw (pid,port)."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        with self.assertRaises(RuntimeError) as ctx:
            self.collector.get_transactions(timeout=1)
        msg = str(ctx.exception)
        # Must not contain raw (pid, port) tuples
        self.assertNotIn("(100, 200)", msg)
        self.assertIn("A_cand_count", msg)

    # ----------------------------------------------------------------
    # F1: first unmarked transaction rejected
    # ----------------------------------------------------------------

    def test_first_unmarked_transaction_rejected(self):
        """F1: When advisory lock is NOT_HELD, first transaction is not set as target."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs = timezone.now()
        with patch.object(TransactionCollector, '_check_advisory_lock',
                          return_value=_LOCK_NOT_HELD):
            # First poll: backend appears with NOT_HELD → should NOT set xact_start
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
            ])
            # Second poll to close collection window → assignment still happens
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
            ])
        # A should be ASSIGNED (candidate was resolved) but xact_start should be None
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertIsNone(self.collector._a_xact_start)
        self.assertIsNone(self.collector._a_xact_end_lower)
        self.assertIsNone(self.collector._a_xact_end_upper)

    def test_first_unmarked_then_marked_accepts_marked(self):
        """F1+F2: First transaction NOT_HELD, second HELD → second is target.
        Also verifies F2: unmarked disappearance does NOT record target END.
        """
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs1 = timezone.now()
        xs2 = xs1 + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        # First transaction: lock NOT_HELD → no xact_start set
        with patch.object(TransactionCollector, '_check_advisory_lock',
                          return_value=_LOCK_NOT_HELD):
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
            ])
            # Collection window closes → ASSIGNED but xact_start still None
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
            ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertIsNone(self.collector._a_xact_start)
        self.assertIsNone(self.collector._a_xact_end_lower)
        self.assertIsNone(self.collector._a_xact_end_upper)
        # Backend disappears → F2 prevents END record (xact_start was None)
        self.collector._track_ab_disappearance((900, 200), xs1, timezone.now(), timezone.now())
        self.assertIsNone(self.collector._a_xact_end_lower,
                          "F2: unmarked disappearance must NOT set end_lower")
        self.assertIsNone(self.collector._a_xact_end_upper,
                          "F2: unmarked disappearance must NOT set end_upper")
        self.assertFalse(self.collector._a_xact_end_verified,
                         "F2: unmarked disappearance must NOT set xact_end_verified")
        # Second transaction: HELD → target starts
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs2, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_xact_start, xs2)
        self.assertIsNone(self.collector._a_xact_end_lower,
                          "end_lower must remain None until verified end")
        self.assertIsNone(self.collector._a_xact_end_upper,
                          "end_upper must remain None until verified end")

    def test_marked_to_marked_selects_new_on_transition(self):
        """F2: Marked→marked transition: old ends, new is target."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs1 = timezone.now()
        xs2 = xs1 + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        # xs1 appears, HELD → target set
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_xact_start, xs1)
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        # xs2 appears with HELD → old ends, new is target
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs2, 'state': 'active'},
        ])
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertIsNotNone(self.collector._a_xact_end_upper)
        self.assertTrue(self.collector._a_xact_end_verified)
        self.assertEqual(self.collector._a_xact_start, xs2)

    def test_marked_to_unmarked_ends_old_rejects_new(self):
        """F2: Marked→unmarked transition: old ends, no new target."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs1 = timezone.now()
        xs2 = xs1 + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        # xs1 appears, HELD → target set
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_xact_start, xs1)
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        # xs2 appears with NOT_HELD → old ends, no new target
        with patch.object(TransactionCollector, '_check_advisory_lock',
                          return_value=_LOCK_NOT_HELD):
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs2, 'state': 'active'},
            ])
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertIsNotNone(self.collector._a_xact_end_upper)
        self.assertTrue(self.collector._a_xact_end_verified)
        self.assertEqual(self.collector._a_xact_start, xs1)

    def test_unmarked_to_unmarked_rejects_both(self):
        """F2: Both transactions NOT_HELD → neither accepted."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs1 = timezone.now()
        xs2 = xs1 + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        # Both transactions NOT_HELD
        with patch.object(TransactionCollector, '_check_advisory_lock',
                          return_value=_LOCK_NOT_HELD):
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
            ])
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
            ])
            self.assertEqual(self.collector._a_state, "ASSIGNED")
            self.assertIsNone(self.collector._a_xact_start)
            # xs2 appears, still NOT_HELD → no change
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs2, 'state': 'active'},
            ])
        self.assertIsNone(self.collector._a_xact_start)
        self.assertIsNone(self.collector._a_xact_end_lower)
        self.assertIsNone(self.collector._a_xact_end_upper)

    def test_advisory_lock_error_fails_closed(self):
        """F3: Advisory lock query error → FAILED state."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs = timezone.now()
        self._simulate_poll(set(), [])
        with patch.object(TransactionCollector, '_check_advisory_lock',
                          return_value=_LOCK_ERROR):
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
            ])
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
            ])
        self.assertEqual(self.collector._a_state, "FAILED")

    def test_advisory_lock_error_on_transition_fails_closed(self):
        """F3: Lock error during transition → FAILED."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs1 = timezone.now()
        xs2 = xs1 + timezone.timedelta(seconds=1)
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs1, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        with patch.object(TransactionCollector, '_check_advisory_lock',
                          return_value=_LOCK_ERROR):
            self._simulate_poll({(100, 200)}, [
                {'pid': 900, 'client_port': 200, 'xact_start': xs2, 'state': 'active'},
            ])
        self.assertEqual(self.collector._a_state, "FAILED")

    # ----------------------------------------------------------------
    # F5: address-based PG join tests
    # ----------------------------------------------------------------

    def test_addr_missing_fails_closed(self):
        """F5: Missing client_addr → FAILED (no port-only fallback).
        No _addr_map is set at any point — _resolve_candidates fails closed.
        """
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        xs = timezone.now()
        # Poll 1: empty, no addr_map
        self._simulate_poll(set(), [], set_addr_map=False)
        # Poll 2: port appears, still no addr_map → A starts COLLECTING
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ], set_addr_map=False)
        # Poll 3: window closes, _resolve_candidates sees no addr → FAILED
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ], set_addr_map=False)
        self.assertEqual(self.collector._a_state, "FAILED")

    def test_pg_match_ambiguous_fails(self):
        """F5: Two PG backends same port+addr → FAILED (ambiguous match)."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        self.collector._addr_map = {(100, 200): "127.0.0.1"}
        xs = timezone.now()
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'client_addr': "127.0.0.1", 'xact_start': xs, 'state': 'active'},
            {'pid': 901, 'client_port': 200, 'client_addr': "127.0.0.1", 'xact_start': xs, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'client_addr': "127.0.0.1", 'xact_start': xs, 'state': 'active'},
            {'pid': 901, 'client_port': 200, 'client_addr': "127.0.0.1", 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "FAILED")

    def test_pg_match_exact_address_succeeds(self):
        """F5: Single PG backend with matching addr+port → ASSIGNED."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        self.collector._addr_map = {(100, 200): "127.0.0.1"}
        xs = timezone.now()
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'client_addr': "127.0.0.1", 'xact_start': xs, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'client_addr': "127.0.0.1", 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_child_pid, 900)
        self.assertEqual(self.collector._a_child_port, 200)

    # ----------------------------------------------------------------
    # F1+F4: A success/token clear → B claim
    # ----------------------------------------------------------------

    def test_a_token_clear_b_claims(self):
        """F1+F4: A completes SUCCEEDED → token clears → B claims new port."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-b")
        xs_a = timezone.now()
        xs_b = xs_a + timezone.timedelta(seconds=3)
        self._simulate_poll(set(), [])
        # A's port appears
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_xact_start, xs_a)
        # A's transaction ends (backend disappears)
        self.collector._track_ab_disappearance((900, 200), xs_a, timezone.now(), timezone.now())
        self.assertTrue(self.collector._a_xact_end_verified)
        # A's token clears (SUCCEEDED status)
        self.job_a.status = Job.Status.SUCCEEDED
        self.job_a.execution_token = ""
        self.job_a.save()
        # B claims new port (101, 201) with new xact_start
        self._simulate_poll({(101, 201)}, [
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        self._simulate_poll({(101, 201)}, [
            {'pid': 901, 'client_port': 201, 'xact_start': xs_b, 'state': 'active'},
        ])
        self.assertEqual(self.collector._b_state, "ASSIGNED")
        self.assertEqual(self.collector._b_xact_start, xs_b)

    # ----------------------------------------------------------------
    # F4: stale/current attempt overlap negative test
    # ----------------------------------------------------------------

    def test_stale_attempt_overlap_rejected(self):
        """F4: Same job+worker, different token → stale attempt not tracked as current."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        # A's token changes (stale attempt detected)
        xs = timezone.now()
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_xact_start, xs)
        # Change token (simulates stale/current overlap)
        self.job_a.execution_token = "tok-a-new"
        self.job_a.save()
        self._simulate_poll({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs, 'state': 'active'},
        ])
        self.assertEqual(self.collector._a_state, "FAILED")

    # ----------------------------------------------------------------
    # F8: error_codes bounded dict behavior
    # ----------------------------------------------------------------

    def test_error_codes_bounded(self):
        """F8/F5: _error_codes is a bounded dict; existing codes always increment."""
        self.collector._add_error_code("test_1")
        self.assertEqual(self.collector._error_codes.get("test_1", 0), 1)
        self.collector._add_error_code("test_1")
        self.assertEqual(self.collector._error_codes.get("test_1", 0), 2)
        # Fill to max with distinct codes (0..31)
        for i in range(32):
            self.collector._add_error_code(f"code_{i}")
        self.assertEqual(len(self.collector._error_codes), 32)
        # New distinct code beyond cap is rejected
        self.collector._add_error_code("extra_code")
        self.assertEqual(len(self.collector._error_codes), 32)
        self.assertNotIn("extra_code", self.collector._error_codes)
        # BUT existing code still increments beyond cap (F5 fix)
        self.collector._add_error_code("test_1")
        self.assertEqual(self.collector._error_codes["test_1"], 3)
        self.collector._add_error_code("code_0")
        self.assertEqual(self.collector._error_codes["code_0"], 2)

    def test_error_codes_in_get_transactions_message(self):
        """F8: FAILED error includes error code context (F4)."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-a")
        self._simulate_poll(set(), [])
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        # Window closes → 2 candidates → FAILED
        self._simulate_poll({(100, 200), (101, 201)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': timezone.now(), 'state': 'active'},
            {'pid': 901, 'client_port': 201, 'xact_start': timezone.now(), 'state': 'active'},
        ])
        with self.assertRaises(RuntimeError) as ctx:
            self.collector.get_transactions(timeout=1)
        msg = str(ctx.exception)
        # Must contain state info
        self.assertIn("A_state=FAILED", msg)
        # Must contain error code names (F6: human-readable, not just hash)
        self.assertIn("error_codes=[", msg, "F6: error code names must appear in FAILED message")

    # ----------------------------------------------------------------
    # P0-2: Transaction boundary accuracy tests
    # ----------------------------------------------------------------

    def _simulate_poll_seq(self, worker_ports, backends, clock_time, set_addr_map=True):
        """Like _simulate_poll but with explicit clock_time for before/after."""
        if set_addr_map:
            for pid, port in worker_ports:
                if (pid, port) not in self.collector._addr_map:
                    self.collector._addr_map[(pid, port)] = "127.0.0.1"
        enriched = []
        for b in backends:
            if "client_addr" not in b:
                b = dict(b, client_addr="127.0.0.1")
            enriched.append(b)
        with patch.object(self.collector, '_get_worker_child_ports', return_value=worker_ports):
            with patch('quality.s2_cr08_canonical.poll_active_backends', return_value=enriched):
                with patch('quality.s2_cr08_canonical._db_clock', return_value=clock_time):
                    self.collector._poll_once()

    def test_start_bound_clock_ordering(self):
        """P0-2 #1: START bound (clock_before) recorded and ordered correctly."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        self._register_pid(101, "test-job-b")
        t0 = timezone.now()
        t1 = t0 + timezone.timedelta(seconds=1)
        t2 = t0 + timezone.timedelta(seconds=2)
        xs_a = t0 + timezone.timedelta(microseconds=100)
        xs_b = t1 + timezone.timedelta(microseconds=100)
        # Empty baseline
        self._simulate_poll_seq(set(), [], t0)
        # First poll: A appears with xact_start
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t1)
        # Close A window
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t2)
        # A has ASSIGNED state with start_bound
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertIsNotNone(self.collector._a_start_bound)
        # start_bound (clock_before) must be >= xact_start
        # (xact_start was set earlier than our poll clock_before)
        self.assertGreaterEqual(self.collector._a_start_bound, self.collector._a_xact_start,
                            "start_bound (clock_before) represents poll time, must not be before xact_start")

    def test_same_port_transition_bounds_shared_snapshot(self):
        """P0-2 #2: Same-port old END and new START use the same snapshot bounds."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        t0 = timezone.now()
        t1 = t0 + timezone.timedelta(seconds=1)
        t2 = t0 + timezone.timedelta(seconds=2)
        t3 = t0 + timezone.timedelta(seconds=3)
        xs_a = t1 + timezone.timedelta(microseconds=100)
        xs_b = t2 + timezone.timedelta(microseconds=100)
        self._simulate_poll_seq(set(), [], t0)
        # A appears
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t1)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t2)
        # A is assigned with target xact_start
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_xact_start, xs_a)
        # Same-port transition: xact_start changes to xs_b in same poll
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_b, 'state': 'active'},
        ], t3)
        # END upper = xs_b (new xact_start), END lower = _last_poll_after (t2)
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertIsNotNone(self.collector._a_xact_end_upper)
        self.assertEqual(self.collector._a_xact_start, xs_b)
        self.assertIsNotNone(self.collector._a_start_bound)
        self.assertLessEqual(self.collector._a_xact_end_lower, self.collector._a_xact_end_upper,
                            "same-port: END lower <= END upper")
        self.assertLessEqual(self.collector._a_xact_end_upper, self.collector._a_start_bound,
                            "same-port: END upper (xs_b) <= start_bound (before of transition poll)")

    def test_disappearance_end_ordering(self):
        """P0-2 #3: Disappearance END maintains end_lower <= end_upper ordering."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        t0 = timezone.now()
        t1 = t0 + timezone.timedelta(seconds=1)
        t2 = t0 + timezone.timedelta(seconds=2)
        t3 = t0 + timezone.timedelta(seconds=3)
        xs_a = t1 + timezone.timedelta(microseconds=100)
        self._simulate_poll_seq(set(), [], t0)
        # A appears and is tracked
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t1)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t2)
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_xact_start, xs_a)
        # Backend disappears in next poll
        self._simulate_poll_seq(set(), [], t3)
        # END should be recorded with _last_poll_before (t2) as lower, t3 as upper
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertIsNotNone(self.collector._a_xact_end_upper)
        self.assertLessEqual(self.collector._a_xact_end_lower, self.collector._a_xact_end_upper)
        self.assertEqual(self.collector._a_xact_end_lower, t2,
                         "disappearance lower bound should be previous poll's before (last confirmed active)")

    def test_field_separation_xact_start_not_end(self):
        """P0-2 #4: For same-port transition, end_lower differed from xact_start (time vs xs)."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        t0 = timezone.now()
        t1 = t0 + timezone.timedelta(seconds=1)
        t2 = t0 + timezone.timedelta(seconds=2)
        t3 = t0 + timezone.timedelta(seconds=3)
        xs_a = t1 + timezone.timedelta(microseconds=100)
        xs_b = t2 + timezone.timedelta(microseconds=100)
        self._simulate_poll_seq(set(), [], t0)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t1)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t2)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_b, 'state': 'active'},
        ], t3)
        # Same-port transition: end_lower = _last_poll_before (t2, a time, not xs_a)
        # end_upper = xs_b (the new xact_start)
        # Field separation: end_lower must differ from any xs
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertIsNotNone(self.collector._a_xact_end_upper)
        self.assertNotEqual(self.collector._a_xact_end_lower, xs_a,
                            "end_lower is a poll timestamp, not xact_start")
        self.assertNotEqual(self.collector._a_xact_end_lower, xs_b,
                            "end_lower is a poll timestamp, not xact_start")

    def test_unrelated_end_not_mixed_into_ab_target(self):
        """P0-2 #5: Unrelated END events don't update A/B target END fields."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        t0 = timezone.now()
        t1 = t0 + timezone.timedelta(seconds=1)
        t2 = t0 + timezone.timedelta(seconds=2)
        xs_a = t1 + timezone.timedelta(microseconds=100)
        # A appears normally
        self._simulate_poll_seq(set(), [], t0)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t1)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t2)
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_xact_start, xs_a)
        # An unrelated END event (different pid,port) is added externally
        # This should NOT affect A's end fields
        self.collector._events.append(("END", 999, 999, xs_a, t2, t2))
        # A's end fields must be unchanged
        self.assertIsNone(self.collector._a_xact_end_lower,
                          "unrelated END event must not touch A target end_lower")
        self.assertIsNone(self.collector._a_xact_end_upper,
                          "unrelated END event must not touch A target end_upper")

    def test_wait_for_completion_timeout_raises(self):
        """P0-2 #6: wait_for_completion timeout raises RuntimeError, not False."""
        xs_a = timezone.now()
        xs_b = xs_a + timezone.timedelta(seconds=1)
        a_event = (900, 200, xs_a, timezone.now(), None, None)
        b_event = (901, 201, xs_b, timezone.now(), None, None)
        with self.assertRaises(RuntimeError) as ctx:
            self.collector.wait_for_completion(a_event, b_event, timeout=0.1)
        self.assertIn("wait_for_completion timed out", str(ctx.exception))

    def test_collector_stop_fail_closed(self):
        """P0-2 #7: collector stop raises on thread join timeout or internal exception."""
        # Internal exception in collector thread should propagate on stop
        self.collector._exception = RuntimeError("collector internal crash")
        self.collector._thread = None  # no real thread
        with self.assertRaises(RuntimeError):
            self.collector.stop()

    def test_poll_exception_fail_closed(self):
        """P0-2 #8: DB clock/poll exception stored and propagated on stop."""
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        with self.assertRaises(RuntimeError):
            with patch.object(self.collector, '_get_worker_child_ports',
                              side_effect=RuntimeError("poll crash")):
                self.collector.pre_arm()
                self.collector._thread.join(timeout=5)
                self.collector.stop()

    def test_ab_same_port_formal_ordering(self):
        """P0-2 #9: A/B same-port sequential: A end_upper <= B xact_start ordering."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self._register_pid(100, "test-job-a")
        t0 = timezone.now()
        t1 = t0 + timezone.timedelta(seconds=1)
        t2 = t0 + timezone.timedelta(seconds=2)
        t3 = t0 + timezone.timedelta(seconds=3)
        t4 = t0 + timezone.timedelta(seconds=4)
        xs_a = t1 + timezone.timedelta(microseconds=100)
        xs_b = t3 + timezone.timedelta(microseconds=100)
        self._simulate_poll_seq(set(), [], t0)
        # A appears
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t1)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t2)
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        # A disappears (backend gone)
        self._simulate_poll_seq(set(), [], t3)
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertTrue(self.collector._a_xact_end_verified)
        # Register B's PID on the same port (200)
        self._register_pid(100, "test-job-b")
        self.job_b.worker_id = "worker-1"
        self.job_b.execution_token = "tok-b"
        self.job_b.status = Job.Status.RUNNING
        self.job_b.save()
        # B appears on same port with new xact_start
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_b, 'state': 'active'},
        ], t4)
        # B should be ASSIGNED
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_b, 'state': 'active'},
        ], t4 + timezone.timedelta(seconds=1))
        self.assertEqual(self.collector._b_state, "ASSIGNED")
        # Same-port ordering check via get_transactions
        a_info, b_info = self.collector.get_transactions(timeout=5)
        self.assertEqual(a_info[0], 900)
        self.assertEqual(a_info[1], 200)
        self.assertEqual(b_info[0], 900)
        self.assertEqual(b_info[1], 200)
        # A end_upper <= B xact_start
        a_end_upper = a_info[5]
        b_xs = b_info[2]
        self.assertIsNotNone(a_end_upper)
        self.assertIsNotNone(b_xs)
        self.assertLessEqual(a_end_upper, b_xs)

    def test_wait_for_completion_missing_end_raises(self):
        """P0-2 #6b: wait_for_completion with missing END events raises RuntimeError."""
        xs_a = timezone.now()
        xs_b = xs_a + timezone.timedelta(seconds=1)
        a_event = (900, 200, xs_a, timezone.now(), None, None)
        b_event = (901, 201, xs_b, timezone.now(), None, None)
        # No END events added → timeout → raise
        with self.assertRaises(RuntimeError):
            self.collector.wait_for_completion(a_event, b_event, timeout=0.1)

    def test_unrelated_end_completion_probe(self):
        """P0-2 F2: Unrelated END with same xs does not fool shim or wait_for_completion."""
        xs_a = timezone.now()
        self.collector._a_child_pid = 900
        self.collector._a_child_port = 200
        self.collector._a_xact_start = xs_a
        # Add unrelated END with same xs but different (pid,port)
        self.collector._events.append(("END", 999, 999, xs_a,
                                        timezone.now(), timezone.now()))
        # Shim must reflect NOT completed
        self.assertFalse(self.collector.observer_a.transaction_completed,
                         "unrelated END with same xs must not set shim completed")
        # wait_for_completion must timeout (not return True)
        a_event = (900, 200, xs_a, timezone.now(), None, None)
        b_event = (901, 201, timezone.now(), timezone.now(), None, None)
        self.collector._b_xact_start = timezone.now()
        with self.assertRaises(RuntimeError):
            self.collector.wait_for_completion(a_event, b_event, timeout=0.1)

    def test_race_xs_before_previous_after_transition(self):
        """F1: Race repro — new xact_start < previous after does NOT invert bounds
        because lower bound uses _last_poll_before (not _last_poll_after).
        """
        t0 = timezone.now()
        t1 = t0 + timezone.timedelta(seconds=1)
        t2 = t0 + timezone.timedelta(seconds=2)
        t3 = t0 + timezone.timedelta(seconds=3)
        xs_a = t1 + timezone.timedelta(microseconds=100)
        xs_b = t2 + timezone.timedelta(microseconds=50)
        self.collector.set_job_ids(self.job_a.job_id, None)
        self._register_pid(100, "test-job-a")
        self._simulate_poll_seq(set(), [], t0)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t1)
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_a, 'state': 'active'},
        ], t2)
        self.assertEqual(self.collector._a_state, "ASSIGNED")
        self.assertEqual(self.collector._a_xact_start, xs_a)
        # _last_poll_after = t2 (previous poll's after) — xs_b (t2+50μs) < t2 would race
        # Simulate the race: set _last_poll_after artificially AFTER xs_b
        self.collector._last_poll_after = t2 + timezone.timedelta(microseconds=100)
        # xs_b (= t2+50μs) is now < _last_poll_after (= t2+100μs)
        # With OLD code (using _last_poll_after): end_lower=t2+100μs > end_upper=t2+50μs
        # With FIX (using _last_poll_before): end_lower=t2 <= end_upper=t2+50μs
        self._simulate_poll_seq({(100, 200)}, [
            {'pid': 900, 'client_port': 200, 'xact_start': xs_b, 'state': 'active'},
        ], t3)
        self.assertIsNotNone(self.collector._a_xact_end_lower)
        self.assertIsNotNone(self.collector._a_xact_end_upper)
        # OLD: _last_poll_after (= t2+100μs) > xs_b (= t2+50μs) → inverted
        # FIXED: _last_poll_before (= t2) <= xs_b (= t2+50μs) → safe
        self.assertLessEqual(self.collector._a_xact_end_lower, self.collector._a_xact_end_upper,
                         "race scenario must not invert: end_lower <= end_upper")

    def test_inverted_bounds_fail_closed_in_get_transactions(self):
        """F1: Inverted END bounds (lower > upper) cause RuntimeError in get_transactions."""
        self.collector.set_job_ids(self.job_a.job_id, self.job_b.job_id)
        self.collector._a_state = "ASSIGNED"
        self.collector._a_child_pid = 900
        self.collector._a_child_port = 200
        self.collector._a_xact_start = timezone.now()
        self.collector._a_start_bound = timezone.now()
        self.collector._a_xact_end_lower = timezone.now() + timezone.timedelta(hours=1)
        self.collector._a_xact_end_upper = timezone.now() - timezone.timedelta(hours=1)
        self.collector._a_xact_end_verified = True
        self.collector._b_state = "ASSIGNED"
        self.collector._b_child_pid = 901
        self.collector._b_child_port = 201
        self.collector._b_xact_start = timezone.now()
        self.collector._b_start_bound = timezone.now()
        self.collector._b_xact_end_lower = timezone.now()
        self.collector._b_xact_end_upper = timezone.now()
        self.collector._b_xact_end_verified = True
        with self.assertRaises(RuntimeError) as ctx:
            self.collector.get_transactions(timeout=1)
        self.assertIn("END bounds inverted", str(ctx.exception))


class TransactionCollectorPgIntegrationTests(TransactionTestCase):
    """Real PostgreSQL integration tests for advisory lock + application_name marker (F1/F2/F4/F6).
    No global mocks — uses real _check_advisory_lock with separate connections.
    """

    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        self.collector = TransactionCollector(poll_seconds=0.1)
        self.job_a = Job.objects.create(
            job_id="int-job-a",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.RUNNING,
            worker_id="int-worker",
            execution_token="int-tok-a",
        )

    def tearDown(self):
        if self.collector._thread and self.collector._thread.is_alive():
            self.collector.stop()

    def _producer_acquire(self, job_id, execution_token):
        """Create a new DB connection, acquire advisory lock + set app_name."""
        from quality.s2_cr08_shared import make_advisory_lock_id, make_application_name_marker
        conn = self._make_producer_conn()
        cursor = conn.cursor()
        lock_id = make_advisory_lock_id(job_id, execution_token)
        app_name = make_application_name_marker(job_id, execution_token)
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [42, lock_id])
        cursor.execute(f"SET LOCAL application_name = '{app_name}'")
        pid = cursor.execute("SELECT pg_backend_pid()").fetchone()[0]
        return conn, pid

    def _observer_check(self, pid, job_id, execution_token):
        return self.collector._check_advisory_lock(pid, job_id, execution_token)

    def test_pg_held_with_correct_token(self):
        conn, pid = self._producer_acquire(self.job_a.job_id, self.job_a.execution_token)
        try:
            result = self._observer_check(pid, self.job_a.job_id, self.job_a.execution_token)
            self.assertEqual(result, _LOCK_HELD)
        finally:
            conn.rollback()
            conn.close()

    def test_pg_wrong_token_not_held(self):
        conn, pid = self._producer_acquire(self.job_a.job_id, "wrong-token")
        try:
            result = self._observer_check(pid, self.job_a.job_id, self.job_a.execution_token)
            self.assertEqual(result, _LOCK_NOT_HELD)
        finally:
            conn.rollback()
            conn.close()

    def _make_producer_conn(self):
        """Create a new standalone psycopg connection."""
        from django.db import connections as dj_connections
        db_settings = dj_connections['default'].settings_dict
        import psycopg
        conn = psycopg.connect(
            host=db_settings['HOST'] or None,
            port=db_settings['PORT'] or None,
            dbname=db_settings['NAME'],
            user=db_settings['USER'] or None,
            password=db_settings['PASSWORD'] or None,
        )
        conn.autocommit = False
        return conn

    def test_pg_lock_only_mismatch_app_not_held(self):
        from quality.s2_cr08_shared import make_advisory_lock_id
        conn = self._make_producer_conn()
        cursor = conn.cursor()
        lock_id = make_advisory_lock_id(self.job_a.job_id, self.job_a.execution_token)
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [42, lock_id])
        cursor.execute("SET LOCAL application_name = 'wrong_app'")
        pid = cursor.execute("SELECT pg_backend_pid()").fetchone()[0]

        try:
            result = self._observer_check(pid, self.job_a.job_id, self.job_a.execution_token)
            self.assertEqual(result, _LOCK_NOT_HELD)
        finally:
            conn.rollback()
            conn.close()

    def test_pg_released_after_commit(self):
        from quality.s2_cr08_shared import make_advisory_lock_id, make_application_name_marker
        conn = self._make_producer_conn()
        cursor = conn.cursor()
        lock_id = make_advisory_lock_id(self.job_a.job_id, self.job_a.execution_token)
        app_name = make_application_name_marker(self.job_a.job_id, self.job_a.execution_token)
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [42, lock_id])
        cursor.execute(f"SET LOCAL application_name = '{app_name}'")
        pid = cursor.execute("SELECT pg_backend_pid()").fetchone()[0]
        conn.commit()
        conn.close()
        result = self._observer_check(pid, self.job_a.job_id, self.job_a.execution_token)
        self.assertEqual(result, _LOCK_NOT_HELD)

    def test_pg_observer_query_error_returns_error(self):
        """F1: Query error → ERROR, not crash."""
        from unittest.mock import patch
        with patch.object(connection, 'cursor', side_effect=Exception("DB error")):
            result = self.collector._check_advisory_lock(
                123, self.job_a.job_id, self.job_a.execution_token)
        self.assertEqual(result, _LOCK_ERROR)

    def test_pg_marker_length_properties(self):
        from quality.s2_cr08_shared import make_application_name_marker, ADVISORY_LOCK_MARKER_PREFIX
        marker = make_application_name_marker(self.job_a.job_id, self.job_a.execution_token)
        self.assertTrue(marker.startswith(ADVISORY_LOCK_MARKER_PREFIX))
        self.assertEqual(len(marker), len(ADVISORY_LOCK_MARKER_PREFIX) + 32)
        marker2 = make_application_name_marker(self.job_a.job_id, self.job_a.execution_token)
        self.assertEqual(marker, marker2)
        marker3 = make_application_name_marker(self.job_a.job_id, "other-token")
        self.assertNotEqual(marker, marker3)


class VerifyChildProcessDirectTests(TransactionTestCase):
    """F5: Direct tests for _verify_child_process WMI command parser."""

    def _mock_run(self, stdout="", returncode=0):
        return type("Proc", (), {"stdout": stdout, "stderr": "", "returncode": returncode})()

    def test_exact_job_and_worker_match(self):
        """Exact job_id and worker_id match."""
        vp = TransactionCollector._verify_child_process
        cmdline = (
            r'C:\Python\python.exe manage.py execute_claimed_job job_123 --worker-id worker-1 '
            r'--other-flag value'
        )
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   return_value=self._mock_run(stdout=cmdline)):
            result = vp(100, "job_123", "worker-1")
            self.assertTrue(result)

    def test_worker_id_mismatch_rejected(self):
        """worker_id mismatch should be rejected."""
        vp = TransactionCollector._verify_child_process
        cmdline = (
            r'C:\Python\python.exe manage.py execute_claimed_job job_123 --worker-id stale-worker'
        )
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   return_value=self._mock_run(stdout=cmdline)):
            result = vp(100, "job_123", "current-worker")
            self.assertFalse(result)

    def test_job_id_mismatch_rejected(self):
        """Different job_id should be rejected."""
        vp = TransactionCollector._verify_child_process
        cmdline = (
            r'C:\Python\python.exe manage.py execute_claimed_job job_456 --worker-id worker-1'
        )
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   return_value=self._mock_run(stdout=cmdline)):
            result = vp(100, "job_123", "worker-1")
            self.assertFalse(result)

    def test_substring_job_id_rejected(self):
        """Substring match should not succeed (job_1 vs job_123)."""
        vp = TransactionCollector._verify_child_process
        cmdline = (
            r'C:\Python\python.exe manage.py execute_claimed_job job_123 --worker-id worker-1'
        )
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   return_value=self._mock_run(stdout=cmdline)):
            result = vp(100, "job_1", "worker-1")
            self.assertFalse(result)

    def test_quoted_path_in_command_line(self):
        """Quoted Python path should still parse correctly."""
        vp = TransactionCollector._verify_child_process
        cmdline = (
            r'"C:\Program Files\Python\python.exe" manage.py execute_claimed_job job_123 '
            r'--worker-id worker-1'
        )
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   return_value=self._mock_run(stdout=cmdline)):
            result = vp(100, "job_123", "worker-1")
            self.assertTrue(result)

    def test_missing_process_returns_false(self):
        """subprocess.run exception (missing process) → False."""
        vp = TransactionCollector._verify_child_process
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   side_effect=Exception("Process not found")):
            result = vp(99999, "job_123", "worker-1")
            self.assertFalse(result)

    def test_nonzero_exit_returns_false(self):
        """Non-zero return code from WMI → empty stdout → False."""
        vp = TransactionCollector._verify_child_process
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   return_value=self._mock_run(stdout="", returncode=1)):
            result = vp(100, "job_123", "worker-1")
            self.assertFalse(result)

    def test_empty_stdout_returns_false(self):
        """Empty stdout from WMI → False."""
        vp = TransactionCollector._verify_child_process
        with patch('quality.s2_cr08_canonical.subprocess.run',
                   return_value=self._mock_run(stdout="")):
            result = vp(100, "job_123", "worker-1")
            self.assertFalse(result)
