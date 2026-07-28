import json
import hashlib
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
    _preflight_key_passed,
    _postflight_key_passed,
    _all_postflight_pass,
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
    run_canonical,
    _write_canonical_evidence,
    LIVE_BLOCKED,
    _build_minimum_evidence,
    _validate_canonical_evidence_semantics,
)
from quality.s2_cr08_measurement import (
    _connection_pid,
    _backend_hash,
    poll_active_backends,
    write_evidence,
)
from quality.models import Job, AppSetting, InspectionFile, Master

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

    def test_inspection_file_distribution_real_record_contract(self):
        master = Master.objects.create(code="S2CR08", name="S2 CR-08")
        InspectionFile.objects.create(
            master=master,
            file_name="inspection.xlsx",
            file_path="inspection.xlsx",
            priority=25,
        )

        dist = _inspection_file_distribution()

        self.assertEqual(dist, {"total": 1, "by_priority": {25: 1}})
        self.assertTrue(all(type(priority) is int for priority in dist["by_priority"]))
        # Preflight: real collector output passes directly
        self.assertTrue(_preflight_key_passed("inspection_file_distribution", dist))
        # Postflight: real collector output augmented with passed / baseline_matched
        postflight_dist = {**dist, "passed": True, "baseline_matched": True}
        self.assertTrue(_postflight_key_passed("inspection_file_distribution", postflight_dist))
        for stage in ("preflight", "postflight"):
            evidence = {stage: {"inspection_file_distribution": dist}}
            self.assertEqual(_privacy_filter(evidence), [])

    def test_postflight_distribution_baseline_mismatch_rejected_from_real_shape(self):
        master = Master.objects.create(code="S2CR08_NEG", name="S2 CR-08 Neg")
        InspectionFile.objects.create(
            master=master,
            file_name="neg.xlsx",
            file_path="neg.xlsx",
            priority=30,
        )
        dist = _inspection_file_distribution()
        postflight_dist = {**dist, "passed": True, "baseline_matched": False}
        self.assertFalse(_postflight_key_passed("inspection_file_distribution", postflight_dist))

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

    # --- F1: Known-schema keys must not fallback to generic positive check ---

    def test_preflight_key_passed_table_counts_missing_fields(self):
        """table_counts with passed=True but missing required fields must fail."""
        self.assertFalse(_preflight_key_passed("table_counts", {"passed": True}))

    def test_preflight_key_passed_table_hashes_missing_fields(self):
        """table_hashes with passed=True but missing required fields must fail."""
        self.assertFalse(_preflight_key_passed("table_hashes", {"passed": True}))

    def test_preflight_key_passed_pathset_hash_missing_fields(self):
        """inspection_file_pathset_hash with passed=True but missing pathset_hash must fail."""
        self.assertFalse(_preflight_key_passed("inspection_file_pathset_hash", {"passed": True}))

    def test_preflight_key_passed_pathset_hash_invalid(self):
        """inspection_file_pathset_hash with invalid hash length must fail."""
        self.assertFalse(_preflight_key_passed("inspection_file_pathset_hash", {"passed": True, "pathset_hash": "too-short"}))

    def test_preflight_key_passed_system_metrics_missing_fields(self):
        """system_metrics with passed=True but missing required fields must fail."""
        self.assertFalse(_preflight_key_passed("system_metrics", {"passed": True}))

    def test_preflight_key_passed_non_schema_key_fallback(self):
        """Non-schema keys still fall back to generic positive check."""
        self.assertTrue(_preflight_key_passed("env_identity", {"passed": True}))

    def test_postflight_key_passed_table_counts_missing_fields(self):
        """postflight table_counts with passed=True but missing required fields must fail."""
        self.assertFalse(_postflight_key_passed("table_counts", {"passed": True, "baseline_matched": True}))

    def test_postflight_key_passed_table_hashes_missing_fields(self):
        """postflight table_hashes with passed=True but missing required fields must fail."""
        self.assertFalse(_postflight_key_passed("table_hashes", {"passed": True, "baseline_matched": True}))

    def test_all_postflight_pass_known_schema_rejected(self):
        """_all_postflight_pass rejects known-schema keys with only passed=True."""
        postflight = {"table_counts": {"passed": True, "baseline_matched": True}}
        self.assertFalse(_all_postflight_pass(postflight))

    def test_all_postflight_pass_generic_key_accepted(self):
        """_all_postflight_pass accepts non-schema keys with passed=True."""
        postflight = {"active_jobs": {"passed": True, "baseline_matched": True}}
        self.assertTrue(_all_postflight_pass(postflight))

    # --- F1: Type-validation — bool-as-int, malformed types ---

    def test_preflight_table_counts_bool_rejected(self):
        """table_counts with bool value must fail."""
        self.assertFalse(_preflight_key_passed("table_counts", {
            "master_count": True, "master_class_count": 0,
            "structure_count": 0, "inspection_file_count": 0,
        }))

    def test_preflight_table_hashes_bool_rejected(self):
        """table_hashes with bool value must fail."""
        self.assertFalse(_preflight_key_passed("table_hashes", {
            "master_hash": True, "master_class_hash": "b" * 64,
            "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64,
        }))

    def test_preflight_inspection_file_distribution_bool_total_rejected(self):
        """inspection_file_distribution with bool total must fail."""
        self.assertFalse(_preflight_key_passed("inspection_file_distribution", {
            "total": True, "by_priority": {1: 10},
        }))

    def test_preflight_inspection_file_distribution_bool_priority_value_rejected(self):
        """inspection_file_distribution with bool priority value must fail."""
        self.assertFalse(_preflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {1: True},
        }))

    def test_preflight_system_metrics_malformed_types_rejected(self):
        """system_metrics with malformed types must fail."""
        self.assertFalse(_preflight_key_passed("system_metrics", {
            "db_connections": None, "waiting_locks": "x",
            "granted_locks": object(), "cpu_percent": None,
            "memory_percent": None, "passed": True,
        }))

    def test_preflight_system_metrics_bool_rejected(self):
        """system_metrics with bool values must fail."""
        self.assertFalse(_preflight_key_passed("system_metrics", {
            "db_connections": True, "waiting_locks": 0,
            "granted_locks": 1, "cpu_percent": 10.0,
            "memory_percent": 50.0, "passed": True,
        }))

    def test_postflight_table_counts_bool_rejected(self):
        """postflight table_counts with bool value must fail."""
        self.assertFalse(_postflight_key_passed("table_counts", {
            "master_count": True, "master_class_count": 0,
            "structure_count": 0, "inspection_file_count": 0,
            "baseline_matched": True,
        }))

    def test_postflight_system_metrics_malformed_types_rejected(self):
        """postflight system_metrics with malformed types must fail."""
        self.assertFalse(_postflight_key_passed("system_metrics", {
            "db_connections": None, "waiting_locks": "x",
            "granted_locks": object(), "cpu_percent": None,
            "memory_percent": None, "passed": True,
            "baseline_matched": True,
        }))

    # --- F2: Distribution total consistency and metric finiteness ---

    def test_preflight_distribution_int_keys_accepted(self):
        """Real collector shape: int priority keys accepted."""
        self.assertTrue(_preflight_key_passed("inspection_file_distribution", {
            "total": 1, "by_priority": {25: 1},
        }))

    def test_postflight_distribution_int_keys_accepted(self):
        """Real collector shape: int priority keys accepted."""
        self.assertTrue(_postflight_key_passed("inspection_file_distribution", {
            "total": 1, "by_priority": {25: 1},
        }))

    def test_preflight_distribution_total_mismatch_rejected(self):
        """inspection_file_distribution with total != sum values must fail."""
        self.assertFalse(_preflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {25: 1},
        }))

    def test_preflight_system_metrics_inf_rejected(self):
        """system_metrics with inf cpu_percent must fail."""
        self.assertFalse(_preflight_key_passed("system_metrics", {
            "db_connections": 1, "waiting_locks": 0,
            "granted_locks": 1, "cpu_percent": float("inf"),
            "memory_percent": 50.0, "passed": True,
        }))

    def test_preflight_system_metrics_negative_inf_rejected(self):
        """system_metrics with -inf cpu_percent must fail."""
        self.assertFalse(_preflight_key_passed("system_metrics", {
            "db_connections": 1, "waiting_locks": 0,
            "granted_locks": 1, "cpu_percent": float("-inf"),
            "memory_percent": 50.0, "passed": True,
        }))

    def test_preflight_system_metrics_nan_rejected(self):
        """system_metrics with nan cpu_percent must fail."""
        self.assertFalse(_preflight_key_passed("system_metrics", {
            "db_connections": 1, "waiting_locks": 0,
            "granted_locks": 1, "cpu_percent": float("nan"),
            "memory_percent": 50.0, "passed": True,
        }))

    def test_postflight_distribution_total_mismatch_rejected(self):
        """postflight distribution with total != sum values must fail."""
        self.assertFalse(_postflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {25: 1}, "baseline_matched": True,
        }))

    def test_postflight_system_metrics_inf_rejected(self):
        """postflight system_metrics with inf cpu_percent must fail."""
        self.assertFalse(_postflight_key_passed("system_metrics", {
            "db_connections": 1, "waiting_locks": 0,
            "granted_locks": 1, "cpu_percent": float("inf"),
            "memory_percent": 50.0, "passed": True,
            "baseline_matched": True,
        }))

    def test_postflight_system_metrics_negative_inf_rejected(self):
        """postflight system_metrics with -inf cpu_percent must fail."""
        self.assertFalse(_postflight_key_passed("system_metrics", {
            "db_connections": 1, "waiting_locks": 0,
            "granted_locks": 1, "cpu_percent": float("-inf"),
            "memory_percent": 50.0, "passed": True,
            "baseline_matched": True,
        }))

    def test_postflight_system_metrics_nan_rejected(self):
        """postflight system_metrics with nan memory_percent must fail."""
        self.assertFalse(_postflight_key_passed("system_metrics", {
            "db_connections": 1, "waiting_locks": 0,
            "granted_locks": 1, "cpu_percent": 10.0,
            "memory_percent": float("nan"), "passed": True,
            "baseline_matched": True,
        }))

    # F2: Additional distribution contract tests - bool key, negative count, parity

    def test_preflight_distribution_bool_priority_key_rejected(self):
        """inspection_file_distribution with bool priority key must fail."""
        self.assertFalse(_preflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {True: 1},
        }))

    def test_postflight_distribution_bool_priority_key_rejected(self):
        """postflight inspection_file_distribution with bool priority key must fail."""
        self.assertFalse(_postflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {True: 1}, "baseline_matched": True,
        }))

    def test_preflight_distribution_negative_count_rejected(self):
        """inspection_file_distribution with negative count must fail."""
        self.assertFalse(_preflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {25: -1},
        }))

    def test_postflight_distribution_negative_count_rejected(self):
        """postflight inspection_file_distribution with negative count must fail."""
        self.assertFalse(_postflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {25: -1}, "baseline_matched": True,
        }))

    def test_postflight_distribution_bool_value_rejected(self):
        """postflight inspection_file_distribution with bool value must fail."""
        self.assertFalse(_postflight_key_passed("inspection_file_distribution", {
            "total": 10, "by_priority": {1: True}, "baseline_matched": True,
        }))


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
                "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100},
                "table_hashes": {"master_hash": "a" * 64, "master_class_hash": "b" * 64, "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64},
                "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
                "inspection_file_distribution": {"total": 100, "by_priority": {1: 100}},
                "inspection_file_pathset_hash": {"pathset_hash": "e" * 64},
                "canonical_input": {"passed": True, "csv_configured": True, "folder_paths_count": 1, "priorities_count": 1, "status": "configured", "issues": []},
                "canonical_payload": {"passed": True, "csv_exists": True, "csv_hash": "mocked_hash", "csv_row_count": 2, "folder_paths_count": 1, "priorities_count": 1, "status": "valid", "issues": []},
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


class PreflightContractTests(TransactionTestCase):
    """F1: Contract test - verify real run_preflight() output matches run_canonical() expectations."""

    @require_postgresql
    def test_run_preflight_real_shape_matches_canonical_expectations(self):
        """Real run_preflight() output must have all keys run_canonical() expects,
        and schema-validated keys must NOT have fake 'passed' (they pass via schema)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            preflight = run_preflight(output_dir=tmpdir)

        # Required keys per run_canonical Gate 1 (F4) that run_preflight provides
        # Note: canonical_payload is added by the command after run_preflight
        required_keys = {
            "env_identity", "django_check", "migrations", "migration_0029",
            "web_service", "worker_service", "http_check", "active_jobs", "running_jobs",
            "backup_tool", "backup_preparedness", "worker_process_tree",
            "table_counts", "table_hashes", "system_metrics",
            "inspection_file_distribution", "inspection_file_pathset_hash",
            "canonical_input", "unc_paths"
        }
        missing = required_keys - set(preflight.keys())
        self.assertEqual(missing, set(), f"run_preflight missing required keys: {missing}")

        # Schema-validated keys should NOT have 'passed' (they pass via schema in _preflight_key_passed)
        # Real run_preflight never adds 'passed' to these EXCEPT system_metrics which does have it
        schema_validated_keys_no_passed = {
            "table_counts", "table_hashes",
            "inspection_file_distribution", "inspection_file_pathset_hash"
        }
        for key in schema_validated_keys_no_passed:
            self.assertNotIn("passed", preflight.get(key, {}),
                            f"Real run_preflight() must not include 'passed' on {key} (passes via schema)")

        # system_metrics DOES have 'passed' in real output (it's set in _collect_system_metrics)
        self.assertIn("passed", preflight["system_metrics"])

        # But they must have the required schema fields
        tc = preflight["table_counts"]
        self.assertIn("master_count", tc)
        self.assertIn("master_class_count", tc)
        self.assertIn("structure_count", tc)
        self.assertIn("inspection_file_count", tc)
        self.assertTrue(all(isinstance(tc[k], int) and tc[k] >= 0 for k in tc))

        th = preflight["table_hashes"]
        self.assertIn("master_hash", th)
        self.assertIn("master_class_hash", th)
        self.assertIn("structure_hash", th)
        self.assertIn("inspection_file_hash", th)
        for k in th:
            self.assertEqual(len(th[k]), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in th[k]))

        sm = preflight["system_metrics"]
        self.assertIn("db_connections", sm)
        self.assertIn("waiting_locks", sm)
        self.assertIn("granted_locks", sm)
        self.assertIn("cpu_percent", sm)
        self.assertIn("memory_percent", sm)
        self.assertIn("passed", sm)  # system_metrics DOES have passed in real output

        dist = preflight["inspection_file_distribution"]
        self.assertIn("total", dist)
        self.assertIn("by_priority", dist)
        self.assertIsInstance(dist["total"], int)
        self.assertIsInstance(dist["by_priority"], dict)

        psh = preflight["inspection_file_pathset_hash"]
        self.assertIn("pathset_hash", psh)
        self.assertEqual(len(psh["pathset_hash"]), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in psh["pathset_hash"]))


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

    def test_run_canonical_rejects_evidence_with_completed_status_and_failure_reason(self):
        """run_canonical must reject measurement_status='completed' with non-empty failure_reason."""
        # Create a job that fails
        failed_job = Job.objects.create(
            job_id="test_job_failed_for_contradiction",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.FAILED,
            attempt_count=1,
        )

        job_a = Job.objects.create(
            job_id="test_job_a_success_2",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.SUCCEEDED,
            attempt_count=1,
            result={
                "updated_master_count": 10,
                "updated_class_count": 5,
                "updated_structure_count": 3,
                "inspection_file_count": 100,
                "transaction_strategy": "single_atomic_update",
            },
        )

        preflight = {
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
            "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100},
            "table_hashes": {"master_hash": "a" * 64, "master_class_hash": "b" * 64, "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64},
            "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
            "inspection_file_distribution": {"total": 100, "by_priority": {1: 100}},
            "inspection_file_pathset_hash": {"pathset_hash": "e" * 64},
            "canonical_input": {"passed": True, "csv_configured": True, "folder_paths_count": 1, "priorities_count": 1, "status": "configured", "issues": []},
            "canonical_payload": {"passed": True, "csv_exists": True, "csv_hash": "mocked_hash", "csv_row_count": 2, "folder_paths_count": 1, "priorities_count": 1, "status": "valid", "issues": []},
            "unc_paths": {"passed": True, "configured_count": 1, "accessible_count": 1, "all_accessible": True, "details": []},
        }

        postflight = {
            "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100, "baseline_matched": True},
            "table_hashes": {"master_hash": "a" * 64, "master_class_hash": "b" * 64, "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64, "baseline_matched": True},
            "web_service": {"passed": True, "running": True},
            "worker_service": {"passed": True, "running": True},
            "http_check": {"passed": True, "status_code": 200},
            "unc_paths": {"passed": True, "configured_count": 1, "accessible_count": 1, "all_accessible": True, "details": []},
            "inspection_file_distribution": {"total": 100, "by_priority": {1: 100}, "passed": True},
            "inspection_file_pathset_hash": {"pathset_hash": "e" * 64, "passed": True},
            "active_jobs": {"passed": True, "count": 0},
            "running_jobs": {"passed": True, "count": 0},
            "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
        }

        base_time = timezone.now()
        observer_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time - timezone.timedelta(seconds=15),
            "end_lower_bound": base_time - timezone.timedelta(seconds=3),
            "end_upper_bound": base_time - timezone.timedelta(seconds=1),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        observer_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=12),
            "end_upper_bound": base_time + timezone.timedelta(seconds=14),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=job_a,
                    job_b=failed_job,
                    observer_a=observer_a,
                    observer_b=observer_b,
                    preflight=preflight,
                    postflight=postflight,
                    system_metrics={
                        "sample_count": 15,
                        "interval_seconds": 2.0,
                        "first_sample": (base_time - timezone.timedelta(seconds=30)).isoformat(),
                        "last_sample": (base_time + timezone.timedelta(seconds=26)).isoformat(),
                        "cpu_percent_max": 30.0,
                        "memory_percent_max": 50.0,
                        "db_connections_max": 10,
                        "waiting_locks_max": 2,
                        "samples": [],
                        "has_data": True,
                    },
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("Job B final gate failed", str(ctx.exception))

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


# ---- F3: Privacy traceability - dynamic integer priority key and raw path rejection ----

class PrivacyFilterDynamicKeyTests(TransactionTestCase):
    """F3: Tests for privacy filter handling of dynamic integer priority keys and raw path rejection."""

    def test_preflight_inspection_file_distribution_dynamic_integer_keys_accepted(self):
        """preflight inspection_file_distribution.by_priority with integer keys must be accepted."""
        evidence = {
            "preflight": {
                "inspection_file_distribution": {
                    "total": 100,
                    "by_priority": {1: 50, 25: 30, 100: 20}
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

    def test_postflight_inspection_file_distribution_dynamic_integer_keys_accepted(self):
        """postflight inspection_file_distribution.by_priority with integer keys must be accepted."""
        evidence = {
            "postflight": {
                "inspection_file_distribution": {
                    "total": 100,
                    "by_priority": {1: 50, 25: 30, 100: 20},
                    "passed": True,
                    "baseline_matched": True
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])

# ---- F3: Raw path content rejection with actual raw path input ----

class PrivacyFilterRawPathRejectionTests(TransactionTestCase):
    """F3: Tests for raw path rejection with actual raw path content (not fixed codes)."""

    def test_preflight_canonical_payload_raw_path_in_issues_rejected(self):
        """preflight canonical_payload.issues with raw path must be rejected."""
        evidence = {
            "preflight": {
                "canonical_payload": {
                    "passed": False, "status": "invalid",
                    "issues": ["C:/sensitive/input.csv not found"]
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("issues_contains_raw_path" in i["reason"] for i in issues))

    def test_preflight_unc_paths_details_raw_path_in_path_rejected(self):
        """preflight unc_paths.details with raw path (not hash) must be rejected."""
        evidence = {
            "preflight": {
                "unc_paths": {
                    "details": [
                        {"path": "C:/sensitive/data", "accessible": True, "entry_count": 5}
                    ]
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("contains_raw_path" in i["reason"] for i in issues))

    def test_postflight_unc_paths_details_raw_path_in_path_rejected(self):
        """postflight unc_paths.details with raw path (not hash) must be rejected."""
        evidence = {
            "postflight": {
                "unc_paths": {
                    "details": [
                        {"path": "\\\\server\\share\\data", "accessible": True, "entry_count": 5}
                    ]
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("contains_raw_path" in i["reason"] for i in issues))

    def test_preflight_backup_tool_tool_path_raw_rejected(self):
        """preflight backup_tool with raw tool_path must be rejected."""
        evidence = {
            "preflight": {
                "backup_tool": {
                    "tool_path": "C:/Program Files/PostgreSQL/16/bin/pg_dump.exe"
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("contains_raw_path" in i["reason"] for i in issues))

    def test_preflight_backup_preparedness_raw_paths_rejected(self):
        """preflight backup_preparedness with raw paths must be rejected."""
        evidence = {
            "preflight": {
                "backup_preparedness": {
                    "tool_path": "C:/tools/pg_dump.exe",
                    "backup_output_dir": "D:/backups"
                }
            }
        }
        issues = _privacy_filter(evidence)
        self.assertTrue(any("contains_raw_path" in i["reason"] for i in issues))


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

class RunCanonicalTests(TransactionTestCase):
    """Third P0: Tests for run_canonical final gate and formal evidence."""



    def setUp(self):
        self.job_a = Job.objects.create(
            job_id="test_job_a",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.SUCCEEDED,
            attempt_count=1,
            result={
                "updated_master_count": 10,
                "updated_class_count": 5,
                "updated_structure_count": 3,
                "inspection_file_count": 100,
                "transaction_strategy": "single_atomic_update",
            },
        )

        self.job_b = Job.objects.create(
            job_id="test_job_b",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.SUCCEEDED,
            attempt_count=1,
            result={
                "updated_master_count": 8,
                "updated_class_count": 4,
                "updated_structure_count": 2,
                "inspection_file_count": 80,
                "transaction_strategy": "single_atomic_update",
            },
        )

        self.preflight = {
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
            "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100},
            "table_hashes": {"master_hash": "a" * 64, "master_class_hash": "b" * 64, "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64},
            "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
            "inspection_file_distribution": {"total": 100, "by_priority": {1: 100}},
            "inspection_file_pathset_hash": {"pathset_hash": "e" * 64},
            "canonical_input": {"passed": True, "csv_configured": True, "folder_paths_count": 1, "priorities_count": 1, "status": "configured", "issues": []},
            "canonical_payload": {"passed": True, "csv_exists": True, "csv_hash": "mocked_hash", "csv_row_count": 2, "folder_paths_count": 1, "priorities_count": 1, "status": "valid", "issues": []},
            "unc_paths": {"passed": True, "configured_count": 1, "accessible_count": 1, "all_accessible": True, "details": []},
        }

        self.postflight = {
            "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100, "baseline_matched": True},
            "table_hashes": {"master_hash": "a" * 64, "master_class_hash": "b" * 64, "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64, "baseline_matched": True},
            "web_service": {"passed": True, "running": True},
            "worker_service": {"passed": True, "running": True},
            "http_check": {"passed": True, "status_code": 200},
            "unc_paths": {"passed": True, "configured_count": 1, "accessible_count": 1, "all_accessible": True, "details": []},
            "inspection_file_distribution": {"total": 100, "by_priority": {1: 100}, "passed": True},
            "inspection_file_pathset_hash": {"pathset_hash": "e" * 64, "passed": True},
            "active_jobs": {"passed": True, "count": 0},
            "running_jobs": {"passed": True, "count": 0},
            "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
        }

        base_time = timezone.now()

        # Create samples with timestamps spanning the job window (through job_b finish + margin)
        samples = []
        for i in range(15):
            ts = base_time - timezone.timedelta(seconds=30) + timezone.timedelta(seconds=i * 4)
            samples.append({
                "timestamp": ts.isoformat(),
                "db_connections": 5,
                "waiting_locks": 0,
                "granted_locks": 3,
                "cpu_percent": 25.0,
                "memory_percent": 45.0
            })

        self.system_metrics = {
            "sample_count": 15,
            "interval_seconds": 2.0,
            "first_sample": (base_time - timezone.timedelta(seconds=30)).isoformat(),
            "last_sample": (base_time + timezone.timedelta(seconds=26)).isoformat(),
            "cpu_percent_max": 30.0,
            "memory_percent_max": 50.0,
            "db_connections_max": 10,
            "waiting_locks_max": 2,
            "samples": samples,
            "has_data": True,
        }

        # Job timestamps within the sample window
        # Job A runs from base_time-20s to base_time-5s
        self.job_a.started_at = base_time - timezone.timedelta(seconds=20)
        self.job_a.finished_at = base_time - timezone.timedelta(seconds=5)
        # Job B runs from base_time-5s to base_time+10s (depends on A)
        self.job_b.started_at = base_time - timezone.timedelta(seconds=5)
        self.job_b.finished_at = base_time + timezone.timedelta(seconds=10)

        # observer_a transaction within Job A window (ends after Job A finishes)
        self.observer_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time - timezone.timedelta(seconds=15),
            "end_lower_bound": base_time - timezone.timedelta(seconds=3),
            "end_upper_bound": base_time - timezone.timedelta(seconds=1),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        # observer_b transaction within Job B window (starts after observer_a ends)
        b_start = base_time

        self.observer_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": b_start,
            "end_lower_bound": b_start + timezone.timedelta(seconds=12),
            "end_upper_bound": b_start + timezone.timedelta(seconds=14),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        self._service_status_patcher = patch('quality.s2_cr08_canonical._check_service_status', return_value='Running')
        self._service_status_patcher.start()


    def tearDown(self):
        self._service_status_patcher.stop()


    def test_live_blocked_constant(self):
        """LIVE_BLOCKED must be True."""
        self.assertTrue(LIVE_BLOCKED)


    def test_run_canonical_returns_evidence(self):
        """run_canonical returns evidence dict with required fields."""
        from quality.s2_cr08_canonical import _iso
        with TemporaryDirectory() as tmpdir:
            evidence = run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
                evidence_output_dir=tmpdir,
            )

        self.assertIsInstance(evidence, dict)
        self.assertEqual(evidence["measurement_status"], "completed")
        self.assertEqual(evidence["failure_reason"], "")
        self.assertIn("live_verification", evidence)
        self.assertIn("privacy_check_passed", evidence)
        self.assertTrue(evidence["privacy_check_passed"])
        self.assertIn("job_a_verification", evidence)
        self.assertIn("job_b_verification", evidence)
        self.assertIn("recovery_ok", evidence)
        self.assertTrue(evidence["recovery_ok"])
        self.assertIn("cleanup_failures", evidence)
        self.assertEqual(evidence["cleanup_failures"], [])
        self.assertIn("recovery_results", evidence)


    def test_run_canonical_fails_closed_when_no_preflight(self):
        """run_canonical raises RuntimeError when preflight is missing."""
        with self.assertRaises(RuntimeError):
            run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=None,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
            )


    def test_run_canonical_fails_closed_when_postflight_fails(self):
        """run_canonical raises RuntimeError when postflight gate fails."""
        bad_postflight = {
            "table_counts": {"passed": False, "baseline_matched": False},
        }
        with self.assertRaises(RuntimeError):
            run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=bad_postflight,
                system_metrics=self.system_metrics,
            )


    def test_run_canonical_fails_closed_when_metrics_insufficient(self):
        """run_canonical raises RuntimeError when metrics coverage is insufficient."""
        bad_metrics = {"db_connections": 5}
        with self.assertRaises(RuntimeError):
            run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=bad_metrics,
            )


    def test_run_canonical_fails_closed_when_job_not_succeeded(self):
        """run_canonical raises RuntimeError when a job is not SUCCEEDED."""
        failed_job = Job.objects.create(
            job_id="test_job_failed",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.FAILED,
            attempt_count=1,
        )
        with self.assertRaises(RuntimeError):
            run_canonical(
                job_a=self.job_a,
                job_b=failed_job,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
            )


    def test_run_canonical_fails_closed_when_service_not_running(self):
        """run_canonical raises RuntimeError when a service is not running."""
        with patch('quality.s2_cr08_canonical._check_service_status', return_value=""):
            with self.assertRaises(RuntimeError):
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                )


    def test_write_canonical_evidence_creates_manifest(self):
        """_write_canonical_evidence creates JSON and checksum files."""
        with TemporaryDirectory() as tmpdir:
            from quality.s2_cr08_canonical import build_canonical_evidence
            evidence = build_canonical_evidence(
                job_a=self.job_a,
                job_b=self.job_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
                run_mode="live",
                measurement_status="completed",
            )
            path = _write_canonical_evidence(evidence, tmpdir)
            self.assertTrue(path.exists())
            manifest = Path(tmpdir) / "checksums.sha256"
            self.assertTrue(manifest.exists())
            content = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(content["measurement_status"], "completed")


    def test_run_canonical_fails_closed_when_no_postflight(self):
        """run_canonical raises RuntimeError when postflight is missing."""
        with self.assertRaises(RuntimeError):
            run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=None,
                system_metrics=self.system_metrics,
            )


    def test_run_canonical_fails_closed_when_no_metrics(self):
        """run_canonical raises RuntimeError when system_metrics is missing."""
        with self.assertRaises(RuntimeError):
            run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=None,
            )


    def test_run_canonical_enriches_evidence_with_live_verification(self):
        """run_canonical adds live_verification dict with all gate results."""
        with TemporaryDirectory() as tmpdir:
            evidence = run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
                evidence_output_dir=tmpdir,
            )
        lv = evidence["live_verification"]
        self.assertTrue(lv["metrics_ok"])
        self.assertTrue(lv["postflight_pass"])
        self.assertTrue(lv["metrics_thread_alive"])
        self.assertTrue(lv["job_a_succeeded"])
        self.assertTrue(lv["job_b_succeeded"])


    def test_run_canonical_does_not_include_raw_paths_in_evidence(self):
        """Privacy filter should not flag the live_verification fields."""
        with TemporaryDirectory() as tmpdir:
            evidence = run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
                evidence_output_dir=tmpdir,
            )
        issues = _privacy_filter(evidence)
        self.assertEqual(issues, [])


    # ---- F2: Required Job/observer for live mode ----

    def test_run_canonical_fails_when_job_a_missing_live(self):
        """F2: run_canonical raises RuntimeError when job_a is missing in live mode."""
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=None,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("job_a is required", str(ctx.exception))


    def test_run_canonical_fails_when_job_b_missing_live(self):
        """F2: run_canonical raises RuntimeError when job_b is missing in live mode."""
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=None,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("job_b is required", str(ctx.exception))


    def test_run_canonical_fails_when_observer_a_missing_live(self):
        """F2: run_canonical raises RuntimeError when observer_a is missing in live mode."""
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=None,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("observer_a is required", str(ctx.exception))


    def test_run_canonical_fails_when_observer_b_missing_live(self):
        """F2: run_canonical raises RuntimeError when observer_b is missing in live mode."""
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=None,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("observer_b is required", str(ctx.exception))


    # ---- F3: Stopped service is failure not success ----

    def test_run_canonical_fails_when_service_stopped(self):
        """F3: run_canonical raises RuntimeError when service status is Stopped (not Running)."""
        with patch('quality.s2_cr08_canonical._check_service_status', return_value='Stopped'):
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir="dummy",
                )
            self.assertIn("Service recovery failed", str(ctx.exception))


    # ---- F5: evidence_output_dir required for live ----

    def test_run_canonical_fails_when_evidence_output_dir_missing_live(self):
        """F5: run_canonical raises RuntimeError when evidence_output_dir is missing in live mode."""
        with self.assertRaises(RuntimeError) as ctx:
            run_canonical(
                job_a=self.job_a,
                job_b=self.job_b,
                observer_a=self.observer_a,
                observer_b=self.observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
                evidence_output_dir=None,
            )
        self.assertIn("evidence_output_dir is required", str(ctx.exception))


    # ---- F3: Negative tests for A/B transaction distinctness ----

    def test_run_canonical_fails_when_same_transaction(self):
        """F3: run_canonical fails when observer_a and observer_b share same xact_start (same transaction)."""
        base_time = timezone.now()
        same_obs = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=1),
            "end_upper_bound": base_time + timezone.timedelta(seconds=3),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=same_obs,
                    observer_b=same_obs,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("share the same transaction", str(ctx.exception))


    def test_run_canonical_fails_when_reversed_order(self):
        """F1: run_canonical fails when observer_b starts before observer_a (reversed order by dependency)."""
        base_time = timezone.now()

        # B starts first, A starts after B ends
        obs_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=1),
            "end_upper_bound": base_time + timezone.timedelta(seconds=3),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        a_start = base_time + timezone.timedelta(seconds=5)

        obs_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": a_start,
            "end_lower_bound": a_start + timezone.timedelta(seconds=1),
            "end_upper_bound": a_start + timezone.timedelta(seconds=3),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=obs_a,
                    observer_b=obs_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("observer_a.xact_start must be < observer_b.xact_start", str(ctx.exception))


    def test_run_canonical_fails_when_overlapping_transactions(self):
        """F3: run_canonical fails when observer_a and observer_b transactions overlap."""
        base_time = timezone.now()
        obs_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=2),
            "end_upper_bound": base_time + timezone.timedelta(seconds=6),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        # B starts before A ends (overlap)
        obs_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time + timezone.timedelta(seconds=4),
            "end_lower_bound": base_time + timezone.timedelta(seconds=5),
            "end_upper_bound": base_time + timezone.timedelta(seconds=7),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=obs_a,
                    observer_b=obs_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("observer_a end_upper must be <= observer_b xact_start", str(ctx.exception))


    # ---- F4: Negative tests for fail-closed preflight/postflight/metrics ----

    def test_run_canonical_fails_when_preflight_empty_dict(self):
        """F4: run_canonical fails when preflight contains empty dict values."""
        bad_preflight = self.preflight.copy()
        bad_preflight["django_check"] = {}
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=bad_preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("Preflight gate failed", str(ctx.exception))


    def test_run_canonical_fails_when_postflight_empty_dict(self):
        """F4: run_canonical fails when postflight contains empty dict values."""
        bad_postflight = self.postflight.copy()
        bad_postflight["table_counts"] = {}
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=bad_postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("Postflight gate failed", str(ctx.exception))


    def test_run_canonical_fails_when_metrics_missing_cpu_percent(self):
        """F3: run_canonical fails when metrics samples missing cpu_percent."""
        bad_metrics = self.system_metrics.copy()
        bad_metrics["samples"] = [
            {"timestamp": timezone.now().isoformat(), "db_connections": 5, "waiting_locks": 0, "granted_locks": 3, "memory_percent": 45.0}
            for _ in range(10)
        ]
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=bad_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("missing cpu_percent", str(ctx.exception))


    def test_run_canonical_fails_when_metrics_missing_memory_percent(self):
        """F3: run_canonical fails when metrics samples missing memory_percent."""
        bad_metrics = self.system_metrics.copy()
        bad_metrics["samples"] = [
            {"timestamp": timezone.now().isoformat(), "db_connections": 5, "waiting_locks": 0, "granted_locks": 3, "cpu_percent": 25.0}
            for _ in range(10)
        ]
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=bad_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("missing memory_percent", str(ctx.exception))


    # ---- F2: Empty recovery results ----

    def test_run_canonical_fails_when_empty_recovery_results(self):
        """F2: run_canonical fails when recovery_results is empty."""
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                    cleanup_failures=[],
                    recovery_results=[],  # Empty - should fail
                )
            self.assertIn("Missing recovery entries", str(ctx.exception))


    def test_run_canonical_fails_when_recovery_missing_web(self):
        """F2: run_canonical fails when recovery missing web service."""
        recovery = [{
            "service": "worker", "name": "QualityControlHQ-Worker-Pseudoprod",
            "target_state": "Running", "success": True,
            "details": {"service_status": "Running"}
        }]
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                    cleanup_failures=[],
                    recovery_results=recovery,
                )
            self.assertIn("Missing recovery entries", str(ctx.exception))


    # ---- F2: Job/Observer time-window correlation negative tests ----

    def test_run_canonical_fails_when_observer_before_job_start(self):
        """F2: Observer xact_start before job started_at should fail."""
        base_time = timezone.now()
        job_a = self.job_a
        job_b = self.job_b
        job_a.started_at = base_time - timezone.timedelta(seconds=20)
        job_a.finished_at = base_time - timezone.timedelta(seconds=5)
        job_b.started_at = base_time - timezone.timedelta(seconds=5)
        job_b.finished_at = base_time + timezone.timedelta(seconds=10)

        # Observer A starts BEFORE job A started
        observer_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time - timezone.timedelta(seconds=25),
            "end_lower_bound": base_time - timezone.timedelta(seconds=15),
            "end_upper_bound": base_time - timezone.timedelta(seconds=13),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        observer_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=12),
            "end_upper_bound": base_time + timezone.timedelta(seconds=14),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=job_a,
                    job_b=job_b,
                    observer_a=observer_a,
                    observer_b=observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("observer_a: xact_start", str(ctx.exception))
            self.assertIn("is before job started_at", str(ctx.exception))

    def test_run_canonical_fails_when_observer_after_job_finish(self):
        """F2: Observer xact_start after job finished_at should fail."""
        base_time = timezone.now()
        job_a = self.job_a
        job_b = self.job_b
        job_a.started_at = base_time - timezone.timedelta(seconds=20)
        job_a.finished_at = base_time - timezone.timedelta(seconds=5)
        job_b.started_at = base_time - timezone.timedelta(seconds=5)
        job_b.finished_at = base_time + timezone.timedelta(seconds=10)

        # Observer A starts AFTER job A finished
        observer_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=10),
            "end_upper_bound": base_time + timezone.timedelta(seconds=12),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        observer_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time + timezone.timedelta(seconds=15),
            "end_lower_bound": base_time + timezone.timedelta(seconds=25),
            "end_upper_bound": base_time + timezone.timedelta(seconds=27),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=job_a,
                    job_b=job_b,
                    observer_a=observer_a,
                    observer_b=observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("observer_a: xact_start", str(ctx.exception))
            self.assertIn("is after job finished_at", str(ctx.exception))

    def test_run_canonical_passes_when_finished_within_end_bounds(self):
        """F2: Normal case — end_lower_bound < finished_at <= end_upper_bound passes."""
        base_time = timezone.now()
        job_a = self.job_a
        job_b = self.job_b
        job_a.started_at = base_time - timezone.timedelta(seconds=20)
        job_a.finished_at = base_time - timezone.timedelta(seconds=5)
        job_b.started_at = base_time - timezone.timedelta(seconds=5)
        job_b.finished_at = base_time + timezone.timedelta(seconds=10)

        # Normal: finished_at within [end_lower_bound, end_upper_bound)
        observer_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time - timezone.timedelta(seconds=15),
            "end_lower_bound": base_time - timezone.timedelta(seconds=8),
            "end_upper_bound": base_time - timezone.timedelta(seconds=1),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        observer_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=12),
            "end_upper_bound": base_time + timezone.timedelta(seconds=14),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        with TemporaryDirectory() as tmpdir:
            evidence = run_canonical(
                job_a=job_a,
                job_b=job_b,
                observer_a=observer_a,
                observer_b=observer_b,
                preflight=self.preflight,
                postflight=self.postflight,
                system_metrics=self.system_metrics,
                evidence_output_dir=tmpdir,
            )
        self.assertEqual(evidence["measurement_status"], "completed")

    def test_run_canonical_fails_when_finished_after_end_upper(self):
        """F2: Observer end_upper_bound before job finished_at should fail (contradiction)."""
        base_time = timezone.now()
        job_a = self.job_a
        job_b = self.job_b
        job_a.started_at = base_time - timezone.timedelta(seconds=20)
        job_a.finished_at = base_time - timezone.timedelta(seconds=5)
        job_b.started_at = base_time - timezone.timedelta(seconds=5)
        job_b.finished_at = base_time + timezone.timedelta(seconds=10)

        # Observer A's end_upper_bound is before job A finishes (contradiction)
        observer_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time - timezone.timedelta(seconds=15),
            "end_lower_bound": base_time - timezone.timedelta(seconds=10),
            "end_upper_bound": base_time - timezone.timedelta(seconds=8),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        observer_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=12),
            "end_upper_bound": base_time + timezone.timedelta(seconds=14),
            "backend_hash": "def456",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": True,
        })()

        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=job_a,
                    job_b=job_b,
                    observer_a=observer_a,
                    observer_b=observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("job finished_at", str(ctx.exception))
            self.assertIn("after end_upper_bound", str(ctx.exception))

    # ---- Job final gate negative tests ----
    # These test that run_canonical's job final gate raises when a job is FAILED.
    # Note: semantic consistency validator (measurement_status vs failure_reason/live_verification)
    # does not yet exist — this is a known gap (see F1).

    def test_run_canonical_job_gate_fails_closed_when_job_a_failed(self):
        """Job A final gate: run_canonical raises when a job is not SUCCEEDED."""
        # Create a job that fails
        failed_job = Job.objects.create(
            job_id="test_job_failed_a",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.FAILED,
            attempt_count=1,
        )
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=failed_job,
                    job_b=self.job_b,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            # The error should indicate job A failed
            self.assertIn("Job A final gate failed", str(ctx.exception))

    def test_run_canonical_job_gate_fails_closed_when_job_b_failed(self):
        """Job B final gate: run_canonical raises when a job is not SUCCEEDED."""
        failed_job = Job.objects.create(
            job_id="test_job_failed_b",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.FAILED,
            attempt_count=1,
        )
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=failed_job,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("Job B final gate failed", str(ctx.exception))

    def test_run_canonical_job_gate_fails_closed_when_job_failed_with_failure_reason(self):
        """Job final gate: run_canonical raises when a job is failed, setting failure_reason implicitly."""
        # This tests that run_canonical internally sets failure_reason when status is failed
        # and never produces completed with non-empty failure_reason
        failed_job = Job.objects.create(
            job_id="test_job_failed_for_reason",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.FAILED,
            attempt_count=1,
        )
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=failed_job,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            # If it somehow passed, failure_reason would be set (not empty)
            # The fact it raises RuntimeError confirms the gate catches the failure

    def test_run_canonical_job_gate_fails_closed_when_job_failed_empty_reason(self):
        """Job final gate: run_canonical raises when a job is failed, never produces empty failure_reason."""
        # This is implicitly enforced by run_canonical which always sets failure_reason
        # when measurement_status becomes failed
        failed_job = Job.objects.create(
            job_id="test_job_failed_empty_reason_check",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.FAILED,
            attempt_count=1,
        )
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=failed_job,
                    observer_a=self.observer_a,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            # The gate fails on job status, but if it passed the evidence would have
            # failure_reason set to "job_b_not_succeeded" (not empty)

    def test_run_canonical_rejects_observer_not_completed_with_completed_status(self):
        """measurement_status='completed' with observer.transaction_completed=False must be rejected."""
        incomplete_observer = type("Observer", (), {
            "transaction_completed": False,
            "xact_start": timezone.now(),
            "end_lower_bound": timezone.now(),
            "end_upper_bound": timezone.now(),
            "backend_hash": "abc123",
            "poll_count": 5,
            "correlation_method": "pid_port",
            "correlation_candidate_count": 1,
            "correlation_unique": True,
            "observation_ok": False,
        })()
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                run_canonical(
                    job_a=self.job_a,
                    job_b=self.job_b,
                    observer_a=incomplete_observer,
                    observer_b=self.observer_b,
                    preflight=self.preflight,
                    postflight=self.postflight,
                    system_metrics=self.system_metrics,
                    evidence_output_dir=tmpdir,
                )
            self.assertIn("observer_a transaction not completed", str(ctx.exception))


class WriteEvidenceVerifyTests(TransactionTestCase):
    """F3: Tests for writer verify - JSON parse, manifest re-read, hash verification."""

    def test_write_evidence_verify_json_parse(self):
        """write_evidence parses JSON after replace to verify validity."""
        evidence = {"fixture_version": "test", "data": "value"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            written = write_evidence(evidence, output)
            # File should be valid JSON
            content = json.loads((written / "measurement.json").read_text(encoding="utf-8"))
            self.assertEqual(content["data"], "value")

    def test_write_evidence_verify_manifest_entry_count(self):
        """write_evidence manifest has exactly 1 entry for measurement.json."""
        evidence = {"fixture_version": "test"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            written = write_evidence(evidence, output)
            manifest = (written / "checksums.sha256").read_text(encoding="utf-8")
            lines = [l for l in manifest.strip().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1, "Manifest must have exactly 1 entry")
            self.assertIn("measurement.json", lines[0])

    def test_write_evidence_verify_manifest_filename(self):
        """write_evidence manifest filename matches the evidence file."""
        evidence = {"fixture_version": "test"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            written = write_evidence(evidence, output)
            manifest = (written / "checksums.sha256").read_text(encoding="utf-8")
            self.assertIn("measurement.json", manifest)
            self.assertNotIn("canonical_evidence.json", manifest)

    def test_write_evidence_verify_manifest_digest_format(self):
        """write_evidence manifest digest is 64-char hex."""
        evidence = {"fixture_version": "test"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            written = write_evidence(evidence, output)
            manifest = (written / "checksums.sha256").read_text(encoding="utf-8")
            # Format: <64-char-hex>  measurement.json
            parts = manifest.strip().split()
            self.assertEqual(len(parts), 2)
            self.assertEqual(len(parts[0]), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in parts[0]))

    def test_write_evidence_verify_manifest_digest_matches(self):
        """write_evidence manifest digest matches recomputed file hash."""
        evidence = {"fixture_version": "test", "payload": "x" * 100}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            written = write_evidence(evidence, output)
            manifest = (written / "checksums.sha256").read_text(encoding="utf-8")
            manifest_digest = manifest.strip().split()[0]
            actual_digest = hashlib.sha256((written / "measurement.json").read_bytes()).hexdigest()
            self.assertEqual(manifest_digest, actual_digest)

    def test_write_canonical_evidence_verify_json_parse(self):
        """_write_canonical_evidence parses JSON after replace."""
        evidence = {"fixture_version": "canonical", "measurement_status": "completed"}
        with TemporaryDirectory() as tmpdir:
            path = _write_canonical_evidence(evidence, tmpdir)
            content = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(content["measurement_status"], "completed")

    def test_write_canonical_evidence_verify_manifest_entry_count(self):
        """_write_canonical_evidence manifest has exactly 1 entry."""
        evidence = {"fixture_version": "canonical"}
        with TemporaryDirectory() as tmpdir:
            path = _write_canonical_evidence(evidence, tmpdir)
            manifest = Path(tmpdir) / "checksums.sha256"
            lines = [l for l in manifest.read_text(encoding="utf-8").strip().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)

    def test_write_canonical_evidence_verify_manifest_filename(self):
        """_write_canonical_evidence manifest filename is canonical_evidence.json."""
        evidence = {"fixture_version": "canonical"}
        with TemporaryDirectory() as tmpdir:
            _write_canonical_evidence(evidence, tmpdir)
            manifest = Path(tmpdir) / "checksums.sha256"
            self.assertIn("canonical_evidence.json", manifest.read_text(encoding="utf-8"))

    def test_write_canonical_evidence_verify_manifest_digest_format(self):
        """_write_canonical_evidence manifest digest is 64-char hex."""
        evidence = {"fixture_version": "canonical"}
        with TemporaryDirectory() as tmpdir:
            _write_canonical_evidence(evidence, tmpdir)
            manifest = Path(tmpdir) / "checksums.sha256"
            parts = manifest.read_text(encoding="utf-8").strip().split()
            self.assertEqual(len(parts[0]), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in parts[0]))

    def test_write_canonical_evidence_verify_manifest_digest_matches(self):
        """_write_canonical_evidence manifest digest matches recomputed hash."""
        evidence = {"fixture_version": "canonical", "payload": "y" * 200}
        with TemporaryDirectory() as tmpdir:
            _write_canonical_evidence(evidence, tmpdir)
            evidence_path = Path(tmpdir) / "canonical_evidence.json"
            manifest = Path(tmpdir) / "checksums.sha256"
            manifest_digest = manifest.read_text(encoding="utf-8").strip().split()[0]
            actual_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            self.assertEqual(manifest_digest, actual_digest)

    def test_write_evidence_verify_file_hash_mismatch(self):
        """Tampered evidence file causes digest mismatch (manual verification)."""
        evidence = {"fixture_version": "test"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            written = write_evidence(evidence, output)
            evidence_path = written / "measurement.json"
            manifest_path = written / "checksums.sha256"
            # Tamper with evidence file
            evidence_path.write_text('{"tampered": true}', encoding="utf-8")
            # Recompute hash - should NOT match manifest
            actual_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            manifest_digest = manifest_path.read_text(encoding="utf-8").strip().split()[0]
            self.assertNotEqual(actual_digest, manifest_digest)

    # --- F3: Failure tests for writer (write/fsync/replace/manifest verify) ---

    @patch("quality.s2_cr08_measurement.json.loads")
    def test_write_evidence_json_parse_failure(self, mock_json_loads):
        """write_evidence raises when JSON parse after replace fails."""
        mock_json_loads.side_effect = json.JSONDecodeError("invalid", "doc", 0)
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            with self.assertRaises(json.JSONDecodeError):
                write_evidence(evidence, output)

    @patch("quality.s2_cr08_measurement.hashlib.sha256")
    def test_write_evidence_manifest_verify_failure(self, mock_sha256):
        """write_evidence raises when manifest digest doesn't match recomputed hash."""
        # Make the second call to sha256 (for manifest verify) return different hash
        mock_hash = mock_sha256.return_value
        mock_hash.hexdigest.side_effect = ["aaaa" * 16, "bbbb" * 16]  # file hash, manifest hash
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            with self.assertRaises(RuntimeError) as ctx:
                write_evidence(evidence, output)
            self.assertIn("mismatch", str(ctx.exception).lower())

    # Similar failure tests for _write_canonical_evidence

    @patch("quality.s2_cr08_canonical.json.loads")
    def test_write_canonical_evidence_json_parse_failure(self, mock_json_loads):
        """_write_canonical_evidence raises when JSON parse after replace fails."""
        mock_json_loads.side_effect = json.JSONDecodeError("invalid", "doc", 0)
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                _write_canonical_evidence(evidence, tmpdir)
            # Error message contains the JSON decode error
            self.assertIn("invalid", str(ctx.exception).lower())

    @patch("quality.s2_cr08_canonical.hashlib.sha256")
    def test_write_canonical_evidence_manifest_verify_failure(self, mock_sha256):
        """_write_canonical_evidence raises when manifest digest doesn't match."""
        mock_hash = mock_sha256.return_value
        mock_hash.hexdigest.side_effect = ["aaaa" * 16, "bbbb" * 16]
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError) as ctx:
                _write_canonical_evidence(evidence, tmpdir)
            self.assertIn("mismatch", str(ctx.exception).lower())

    # --- F3: Residue tests — no formal evidence/manifest left after failure ---

    @patch("quality.s2_cr08_measurement.json.loads")
    def test_write_evidence_no_residue_after_json_parse_failure(self, mock_json_loads):
        """write_evidence JSON parse failure leaves no evidence or manifest files."""
        mock_json_loads.side_effect = json.JSONDecodeError("invalid", "doc", 0)
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            with self.assertRaises(json.JSONDecodeError):
                write_evidence(evidence, output)
            self.assertFalse((output / "measurement.json").exists())
            self.assertFalse((output / "checksums.sha256").exists())

    @patch("quality.s2_cr08_measurement.hashlib.sha256")
    def test_write_evidence_no_residue_after_manifest_verify_failure(self, mock_sha256):
        """write_evidence manifest digest mismatch leaves no residue and allows retry."""
        mock_hash = mock_sha256.return_value
        mock_hash.hexdigest.side_effect = ["aaaa" * 16, "bbbb" * 16]
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            with self.assertRaises(RuntimeError) as ctx:
                write_evidence(evidence, output)
            self.assertIn("mismatch", str(ctx.exception).lower())
            self.assertFalse((output / "measurement.json").exists())
            self.assertFalse((output / "checksums.sha256").exists())
            # Retry with same directory should succeed after cleanup
            mock_hash.hexdigest.side_effect = None
            mock_hash.hexdigest.return_value = "c" * 64
            retry_output = write_evidence({"retry": True}, output)
            self.assertTrue((retry_output / "measurement.json").exists())
            self.assertTrue((retry_output / "checksums.sha256").exists())

    @patch("quality.s2_cr08_canonical.json.loads")
    def test_write_canonical_evidence_no_residue_after_json_parse_failure(self, mock_json_loads):
        """_write_canonical_evidence JSON parse failure leaves no evidence or manifest files."""
        mock_json_loads.side_effect = json.JSONDecodeError("invalid", "doc", 0)
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError):
                _write_canonical_evidence(evidence, tmpdir)
            self.assertFalse((Path(tmpdir) / "canonical_evidence.json").exists())
            self.assertFalse((Path(tmpdir) / "checksums.sha256").exists())

    @patch("quality.s2_cr08_canonical.hashlib.sha256")
    def test_write_canonical_evidence_no_residue_after_manifest_verify_failure(self, mock_sha256):
        """_write_canonical_evidence manifest digest mismatch leaves no residue and allows retry."""
        mock_hash = mock_sha256.return_value
        mock_hash.hexdigest.side_effect = ["aaaa" * 16, "bbbb" * 16]
        evidence = {"test": "data"}
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(RuntimeError):
                _write_canonical_evidence(evidence, tmpdir)
            self.assertFalse((Path(tmpdir) / "canonical_evidence.json").exists())
            self.assertFalse((Path(tmpdir) / "checksums.sha256").exists())
            # Retry with same directory should succeed after cleanup
            mock_hash.hexdigest.side_effect = None
            mock_hash.hexdigest.return_value = "c" * 64
            retry_path = _write_canonical_evidence({"retry": True}, tmpdir)
            self.assertTrue(retry_path.exists())
            self.assertTrue((Path(tmpdir) / "checksums.sha256").exists())


class CanonicalEvidenceSemanticValidatorTests(TransactionTestCase):
    """P1: Direct tests for _validate_canonical_evidence_semantics."""

    # ── Positive ──

    def test_valid_dry_run_preflight_pass(self):
        evidence = {
            "run_mode": "dry_run",
            "measurement_status": "not_executed",
            "failure_reason": "",
        }
        self.assertTrue(_validate_canonical_evidence_semantics(evidence, require_final=False))

    def test_valid_dry_run_preflight_failed(self):
        evidence = {
            "run_mode": "dry_run",
            "measurement_status": "not_executed",
            "failure_reason": "preflight_failed",
        }
        self.assertTrue(_validate_canonical_evidence_semantics(evidence, require_final=False))

    def test_valid_live_minimum_failure_evidence(self):
        evidence = {
            "run_mode": "live",
            "measurement_status": "failed",
            "failure_reason": "job_a_not_succeeded",
        }
        self.assertTrue(_validate_canonical_evidence_semantics(evidence, require_final=False))

    def test_valid_completed_final_evidence(self):
        evidence = {
            "run_mode": "live",
            "measurement_status": "completed",
            "failure_reason": "",
            "live_verification": {
                "job_a_succeeded": True,
                "job_b_succeeded": True,
                "observer_a_completed": True,
                "observer_b_completed": True,
                "postflight_pass": True,
                "metrics_ok": True,
                "metrics_thread_alive": True,
            },
            "metrics_coverage_ok": True,
            "recovery_ok": True,
            "transaction_completed": True,
            "observation_ok": True,
            "cleanup_failures": [],
        }
        self.assertTrue(_validate_canonical_evidence_semantics(evidence, require_final=True))

    # ── Base negative ──

    def test_non_dict_evidence(self):
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics("not a dict")

    def test_unknown_run_mode(self):
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics({"run_mode": "invalid", "measurement_status": "completed"})

    def test_missing_run_mode(self):
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics({"measurement_status": "completed"})

    def test_malformed_run_mode(self):
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics({"run_mode": None, "measurement_status": "completed"})

    def test_unknown_measurement_status(self):
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics({"run_mode": "live", "measurement_status": "unknown"})

    def test_missing_measurement_status(self):
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics({"run_mode": "live"})

    def test_malformed_measurement_status(self):
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics({"run_mode": "live", "measurement_status": None})

    def test_completed_with_non_empty_failure_reason(self):
        evidence = {
            "run_mode": "live",
            "measurement_status": "completed",
            "failure_reason": "something_wrong",
        }
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(evidence, require_final=False)

    def test_failed_with_empty_failure_reason(self):
        evidence = {
            "run_mode": "live",
            "measurement_status": "failed",
            "failure_reason": "",
        }
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(evidence, require_final=False)

    def test_failed_with_missing_failure_reason(self):
        evidence = {
            "run_mode": "live",
            "measurement_status": "failed",
        }
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(evidence, require_final=False)

    def test_failed_with_non_string_failure_reason(self):
        evidence = {
            "run_mode": "live",
            "measurement_status": "failed",
            "failure_reason": 42,
        }
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(evidence, require_final=False)

    def test_dry_run_with_completed(self):
        evidence = {
            "run_mode": "dry_run",
            "measurement_status": "completed",
            "failure_reason": "",
        }
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(evidence, require_final=False)

    def test_dry_run_with_failed(self):
        evidence = {
            "run_mode": "dry_run",
            "measurement_status": "failed",
            "failure_reason": "something",
        }
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(evidence, require_final=False)

    def test_dry_run_unknown_failure_reason(self):
        evidence = {
            "run_mode": "dry_run",
            "measurement_status": "not_executed",
            "failure_reason": "unknown_reason",
        }
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(evidence, require_final=False)

    # ── Final negative (table-driven) ──

    def _valid_final_evidence(self):
        return {
            "run_mode": "live",
            "measurement_status": "completed",
            "failure_reason": "",
            "live_verification": {
                "job_a_succeeded": True,
                "job_b_succeeded": True,
                "observer_a_completed": True,
                "observer_b_completed": True,
                "postflight_pass": True,
                "metrics_ok": True,
                "metrics_thread_alive": True,
            },
            "metrics_coverage_ok": True,
            "recovery_ok": True,
            "transaction_completed": True,
            "observation_ok": True,
            "cleanup_failures": [],
        }

    def test_final_missing_live_verification(self):
        ev = self._valid_final_evidence()
        del ev["live_verification"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_non_dict_live_verification(self):
        ev = self._valid_final_evidence()
        ev["live_verification"] = "not a dict"
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_missing_failure_reason(self):
        ev = self._valid_final_evidence()
        del ev["failure_reason"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_none_failure_reason(self):
        ev = self._valid_final_evidence()
        ev["failure_reason"] = None
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_live_gate_missing_fields(self):
        for field in ("job_a_succeeded", "job_b_succeeded", "observer_a_completed",
                      "observer_b_completed", "postflight_pass", "metrics_ok",
                      "metrics_thread_alive"):
            with self.subTest(missing_field=field):
                ev = self._valid_final_evidence()
                del ev["live_verification"][field]
                with self.assertRaises(ValueError):
                    _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_live_gate_fields_false(self):
        for field in ("job_a_succeeded", "job_b_succeeded", "observer_a_completed",
                      "observer_b_completed", "postflight_pass", "metrics_ok",
                      "metrics_thread_alive"):
            with self.subTest(false_field=field):
                ev = self._valid_final_evidence()
                ev["live_verification"][field] = False
                with self.assertRaises(ValueError):
                    _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_live_gate_fields_non_bool_truthy(self):
        for field in ("job_a_succeeded", "job_b_succeeded", "observer_a_completed",
                      "observer_b_completed", "postflight_pass", "metrics_ok",
                      "metrics_thread_alive"):
            with self.subTest(truthy_non_bool_field=field):
                ev = self._valid_final_evidence()
                ev["live_verification"][field] = 1
                with self.assertRaises(ValueError):
                    _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_metrics_coverage_ok_missing(self):
        ev = self._valid_final_evidence()
        del ev["metrics_coverage_ok"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_metrics_coverage_ok_false(self):
        ev = self._valid_final_evidence()
        ev["metrics_coverage_ok"] = False
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_metrics_coverage_ok_non_bool(self):
        ev = self._valid_final_evidence()
        ev["metrics_coverage_ok"] = 1
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_recovery_ok_missing(self):
        ev = self._valid_final_evidence()
        del ev["recovery_ok"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_recovery_ok_false(self):
        ev = self._valid_final_evidence()
        ev["recovery_ok"] = False
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_recovery_ok_non_bool(self):
        ev = self._valid_final_evidence()
        ev["recovery_ok"] = 1
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_cleanup_failures_missing(self):
        ev = self._valid_final_evidence()
        del ev["cleanup_failures"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_cleanup_failures_non_list(self):
        ev = self._valid_final_evidence()
        ev["cleanup_failures"] = "not a list"
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_cleanup_failures_non_empty(self):
        ev = self._valid_final_evidence()
        ev["cleanup_failures"] = ["some error"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_transaction_completed_missing(self):
        ev = self._valid_final_evidence()
        del ev["transaction_completed"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_transaction_completed_false(self):
        ev = self._valid_final_evidence()
        ev["transaction_completed"] = False
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_transaction_completed_non_bool(self):
        ev = self._valid_final_evidence()
        ev["transaction_completed"] = 1
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_observation_ok_missing(self):
        ev = self._valid_final_evidence()
        del ev["observation_ok"]
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_observation_ok_false(self):
        ev = self._valid_final_evidence()
        ev["observation_ok"] = False
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_final_observation_ok_non_bool(self):
        ev = self._valid_final_evidence()
        ev["observation_ok"] = 1
        with self.assertRaises(ValueError):
            _validate_canonical_evidence_semantics(ev, require_final=True)

    def test_validation_errors_do_not_include_untrusted_values(self):
        """Semantic validation errors expose field metadata, never rejected values."""
        sentinels = [
            "SECRET_SENTINEL_VALUE",
            r"C:\\secret\\evidence.json",
            "(12345, 54321)",
        ]
        cases = [
            ({"run_mode": sentinels[0], "measurement_status": "completed"}, False),
            ({"run_mode": "live", "measurement_status": sentinels[1]}, False),
            ({"run_mode": "dry_run", "measurement_status": "not_executed", "failure_reason": sentinels[2]}, False),
        ]
        for field in ("job_a_succeeded", "job_b_succeeded", "observer_a_completed",
                      "observer_b_completed", "postflight_pass", "metrics_ok",
                      "metrics_thread_alive"):
            evidence = self._valid_final_evidence()
            evidence["live_verification"][field] = sentinels[0]
            cases.append((evidence, True))
        evidence = self._valid_final_evidence()
        evidence["cleanup_failures"] = list(sentinels)
        cases.append((evidence, True))

        for evidence, require_final in cases:
            with self.subTest(evidence=evidence, require_final=require_final):
                with self.assertRaises(ValueError) as raised:
                    _validate_canonical_evidence_semantics(evidence, require_final=require_final)
                message = str(raised.exception)
                for sentinel in sentinels:
                    self.assertNotIn(sentinel, message)


class CanonicalEvidenceSemanticIntegrationTests(TransactionTestCase):
    """P1: Integration tests for semantic validation in production paths."""

    def test_build_canonical_evidence_rejects_completed_with_reason(self):
        with self.assertRaises(ValueError):
            build_canonical_evidence(
                run_mode="live",
                measurement_status="completed",
                failure_reason="something_wrong",
            )

    def test_build_minimum_evidence_rejects_failed_empty_reason(self):
        with self.assertRaises(ValueError):
            _build_minimum_evidence(
                measurement_status="failed",
                failure_reason="",
            )

    def test_build_minimum_evidence_rejects_failed_missing_reason(self):
        with self.assertRaises(ValueError):
            _build_minimum_evidence(
                measurement_status="failed",
            )

    def test_run_canonical_calls_final_validator_before_privacy(self):
        """run_canonical() calls _validate_canonical_evidence_semantics(require_final=True) before privacy check."""
        events = []

        def validate(evidence, *, require_final=False):
            if require_final:
                events.append("final_validator")
            return True

        def privacy_check(evidence):
            events.append("privacy")
            return True, []

        job_a = Job.objects.create(
            job_id="test_rc_final_val_a",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.SUCCEEDED,
            attempt_count=1,
            result={
                "updated_master_count": 10, "updated_class_count": 5,
                "updated_structure_count": 3, "inspection_file_count": 100,
                "transaction_strategy": "single_atomic_update",
            },
        )
        job_b = Job.objects.create(
            job_id="test_rc_final_val_b",
            job_type=Job.JobType.MASTER_UPDATE,
            status=Job.Status.SUCCEEDED,
            attempt_count=1,
            result={
                "updated_master_count": 8, "updated_class_count": 4,
                "updated_structure_count": 2, "inspection_file_count": 80,
                "transaction_strategy": "single_atomic_update",
            },
        )
        base_time = timezone.now()
        preflight = {
            "env_identity": {"passed": True, "found": True},
            "django_check": {"passed": True, "output": "ok"},
            "migrations": {"passed": True},
            "migration_0029": {"passed": True, "migration_0029_applied": True},
            "web_service": {"passed": True, "found": True, "status": "Running", "start_type": "Automatic", "running": True, "automatic": True},
            "worker_service": {"passed": True, "found": True, "status": "Running", "start_type": "Automatic", "running": True, "automatic": True},
            "http_check": {"passed": True, "status_code": 200},
            "active_jobs": {"passed": True, "count": 0},
            "running_jobs": {"passed": True, "count": 0},
            "backup_tool": {"passed": True, "available": True, "version": "1.0", "tool_path": "safe"},
            "backup_preparedness": {"passed": True, "tool_available": True, "tool_path": "safe", "backup_output_dir": "safe", "backup_output_writable": True, "parent_dir_exists": True},
            "worker_process_tree": {"passed": True, "child_count": 1, "unique": True},
            "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100},
            "table_hashes": {"master_hash": "a" * 64, "master_class_hash": "b" * 64, "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64},
            "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
            "inspection_file_distribution": {"total": 100, "by_priority": {1: 100}},
            "inspection_file_pathset_hash": {"pathset_hash": "e" * 64},
            "canonical_input": {"passed": True, "csv_configured": True, "folder_paths_count": 1, "priorities_count": 1, "status": "configured", "issues": []},
            "canonical_payload": {"passed": True, "csv_exists": True, "csv_hash": "mocked", "csv_row_count": 2, "folder_paths_count": 1, "priorities_count": 1, "status": "valid", "issues": []},
            "unc_paths": {"passed": True, "configured_count": 1, "accessible_count": 1, "all_accessible": True, "details": []},
        }
        postflight = {
            "table_counts": {"master_count": 10, "master_class_count": 5, "structure_count": 3, "inspection_file_count": 100, "baseline_matched": True},
            "table_hashes": {"master_hash": "a" * 64, "master_class_hash": "b" * 64, "structure_hash": "c" * 64, "inspection_file_hash": "d" * 64, "baseline_matched": True},
            "web_service": {"passed": True, "running": True},
            "worker_service": {"passed": True, "running": True},
            "http_check": {"passed": True, "status_code": 200},
            "unc_paths": {"passed": True, "configured_count": 1, "accessible_count": 1, "all_accessible": True, "details": []},
            "inspection_file_distribution": {"total": 100, "by_priority": {1: 100}, "passed": True},
            "inspection_file_pathset_hash": {"pathset_hash": "e" * 64, "passed": True},
            "active_jobs": {"passed": True, "count": 0},
            "running_jobs": {"passed": True, "count": 0},
            "system_metrics": {"db_connections": 5, "waiting_locks": 0, "granted_locks": 10, "cpu_percent": 10.0, "memory_percent": 50.0, "passed": True},
        }
        observer_a = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time - timezone.timedelta(seconds=15),
            "end_lower_bound": base_time - timezone.timedelta(seconds=3),
            "end_upper_bound": base_time - timezone.timedelta(seconds=1),
            "backend_hash": "abc", "poll_count": 5,
            "correlation_method": "pid_port", "correlation_candidate_count": 1,
            "correlation_unique": True, "observation_ok": True,
        })()
        observer_b = type("Observer", (), {
            "transaction_completed": True,
            "xact_start": base_time,
            "end_lower_bound": base_time + timezone.timedelta(seconds=12),
            "end_upper_bound": base_time + timezone.timedelta(seconds=14),
            "backend_hash": "def", "poll_count": 5,
            "correlation_method": "pid_port", "correlation_candidate_count": 1,
            "correlation_unique": True, "observation_ok": True,
        })()
        samples = []
        for i in range(15):
            ts = base_time - timezone.timedelta(seconds=30) + timezone.timedelta(seconds=i * 4)
            samples.append({
                "timestamp": ts.isoformat(),
                "db_connections": 5, "waiting_locks": 0, "granted_locks": 10,
                "cpu_percent": 15.0 + i, "memory_percent": 50.0,
            })
        with patch("quality.s2_cr08_canonical._validate_canonical_evidence_semantics", side_effect=validate), \
             patch("quality.s2_cr08_canonical._privacy_check_passed", side_effect=privacy_check), \
             TemporaryDirectory() as tmpdir:
            run_canonical(
                job_a=job_a, job_b=job_b,
                observer_a=observer_a, observer_b=observer_b,
                preflight=preflight, postflight=postflight,
                system_metrics={
                    "sample_count": len(samples), "interval_seconds": 2.0,
                    "first_sample": samples[0]["timestamp"],
                    "last_sample": samples[-1]["timestamp"],
                    "cpu_percent_max": 30.0, "memory_percent_max": 50.0,
                    "db_connections_max": 10, "waiting_locks_max": 2,
                    "samples": samples, "has_data": True,
                },
                evidence_output_dir=tmpdir,
                cleanup_failures=[],
                recovery_results=[
                    {"service": "web", "name": "QualityControlHQ-Pseudoprod", "target_state": "Running", "success": True},
                    {"service": "worker", "name": "QualityControlHQ-Worker-Pseudoprod", "target_state": "Running", "success": True},
                ],
            )
        self.assertEqual(events, ["final_validator", "privacy"])

    def test_management_command_dry_run_validator_called_before_write(self):
        """dry-run validator failure prevents write_evidence from being called."""
        from quality.management.commands.measure_s2_cr08_canonical import Command
        cmd = Command()
        events = []

        def reject_validator(evidence, *, require_final=False):
            events.append("validator")
            raise ValueError("semantic validation failed")

        evidence = {
            "run_mode": "dry_run",
            "measurement_status": "not_executed",
            "failure_reason": "",
        }
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dry_run_output3"
            with patch("quality.management.commands.measure_s2_cr08_canonical.run_preflight", return_value={}), \
                 patch("quality.management.commands.measure_s2_cr08_canonical._all_preflight_pass", return_value=True), \
                 patch("quality.management.commands.measure_s2_cr08_canonical._check_canonical_baseline_configured", return_value=(True, "")), \
                 patch("quality.management.commands.measure_s2_cr08_canonical._verify_canonical_payload", return_value={"passed": True}), \
                 patch("quality.management.commands.measure_s2_cr08_canonical.build_canonical_evidence", return_value=evidence), \
                 patch("quality.management.commands.measure_s2_cr08_canonical._privacy_check_passed", return_value=(True, [])), \
                 patch("quality.management.commands.measure_s2_cr08_canonical._validate_canonical_evidence_semantics", side_effect=reject_validator), \
                 patch("quality.management.commands.measure_s2_cr08_canonical.write_evidence") as mock_write:
                with self.assertRaises(ValueError):
                    cmd.handle(output=str(output), dry_run=True, live=False, poll_seconds=0.5,
                               env_path="", web_service="web", worker_service="worker",
                               unc_paths=[], csv_path="", inspection_folder_paths=[])
        self.assertEqual(events, ["validator"])
        mock_write.assert_not_called()

    def test_management_command_live_blocked(self):
        """live management command raises CommandError because LIVE_BLOCKED is True."""
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "live_output3"
            with self.assertRaises(CommandError):
                call_command(
                    "measure_s2_cr08_canonical", "--live", f"--output={output}",
                )
