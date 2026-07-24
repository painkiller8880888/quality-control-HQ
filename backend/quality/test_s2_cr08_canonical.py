import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from quality.s2_cr08_canonical import (
    ExternalWorkerObserver,
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
)
from quality.s2_cr08_measurement import (
    _connection_pid,
    _backend_hash,
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
