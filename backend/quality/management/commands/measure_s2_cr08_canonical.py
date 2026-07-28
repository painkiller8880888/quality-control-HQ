from pathlib import Path
import time as _time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from quality.job_queue import MASTER_RESOURCE, enqueue_job
from quality.models import Job
from quality.s2_cr08_canonical import (
    ExternalWorkerObserver,
    TransactionCollector,
    SystemMetricsMonitor,
    build_canonical_evidence,
    run_preflight,
    run_postflight,
    run_canonical,
    _privacy_check_passed,
    _all_preflight_pass,
    _table_counts,
    _table_stable_hashes,
    _active_job_count,
    _running_job_count,
    _collect_system_metrics,
    _inspection_file_distribution,
    _inspection_file_pathset_hash,
    _canonical_job_section,
    _canonical_transaction_section,
    _privacy_safe_str,
    _verify_canonical_payload,
    _verify_job_result,
    _execute_live_backup,
    _check_canonical_baseline_configured,
    _start_service_with_health_check,
    _sanitize_recovery_results,
    _build_minimum_evidence,
    _sha256,
    CANONICAL_BASELINE_KNOWN_HASH,
    CANONICAL_BASELINE_EXPECTED_ROW_COUNT,
    CANONICAL_BASELINE_UNC_7ROOT,
    CANONICAL_BASELINE_EXPECTED_MASTER_COUNT,
    CANONICAL_BASELINE_EXPECTED_CLASS_COUNT,
    CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT,
)
from quality.s2_cr08_measurement import write_evidence


LIVE_BLOCKED = True
LIVE_BLOCK_REASON = (
    "--live is temporarily disabled until all reviewer findings (Iteration 9 v2) are resolved. "
    "See .reviewer/HANDOFF.md findings 1-10."
)


class Command(BaseCommand):
    help = (
        "Canonical S2-CR-08 measurement via external Windows worker. "
        "Use --dry-run for non-mutating preflight validation. "
    )

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--poll-seconds", type=float, default=2.0)
        parser.add_argument("--env-path", default="")
        parser.add_argument("--web-service", default="QualityControlHQ-Pseudoprod")
        parser.add_argument("--worker-service", default="QualityControlHQ-Worker-Pseudoprod")
        parser.add_argument("--unc-paths", nargs="*", default=[])
        parser.add_argument("--csv-path", default="")
        parser.add_argument("--inspection-folder-paths", nargs="*", default=[])

    def _build_canonical_payload(self, options, require_values=False):
        from quality.models import AppSetting
        app_setting = AppSetting.objects.first()
        payload = {
            "operation": "master_update",
            "retry_safe": True,
        }
        csv_path = options.get("csv_path") or ""
        if csv_path:
            payload["csv_path"] = csv_path
        elif app_setting and app_setting.csv_path:
            payload["csv_path"] = app_setting.csv_path
        elif require_values:
            raise CommandError("csv_path is required (provide --csv-path or configure AppSetting.csv_path)")
        folder_paths = options.get("inspection_folder_paths") or []
        if folder_paths:
            payload["inspection_folder_paths"] = list(folder_paths)
        elif app_setting and app_setting.inspection_folder_paths:
            payload["inspection_folder_paths"] = list(app_setting.inspection_folder_paths)
        elif require_values:
            raise CommandError("inspection_folder_paths are required (provide --inspection-folder-paths or configure AppSetting)")
        if app_setting and app_setting.inspection_folder_priorities:
            payload["inspection_folder_priorities"] = dict(app_setting.inspection_folder_priorities)
        else:
            payload["inspection_folder_priorities"] = {}
        return payload

    def _validate_canonical_payload(self, payload):
        issues = []
        if not payload.get("csv_path"):
            issues.append("csv_path missing in payload")
        if not payload.get("inspection_folder_paths"):
            issues.append("inspection_folder_paths missing in payload")
        if not payload.get("retry_safe"):
            issues.append("retry_safe must be true")
        return {"passed": len(issues) == 0, "status": "valid" if not issues else "invalid", "issues": issues}

    def _wait_for_job_with_observer(self, job, observer, poll_seconds, timeout_extra=120):
        timeout = job.timeout_seconds + timeout_extra
        deadline = timezone.now() + timezone.timedelta(seconds=timeout)
        while timezone.now() < deadline:
            job.refresh_from_db()
            if job.status in (Job.Status.SUCCEEDED, Job.Status.FAILED):
                break
            _time.sleep(poll_seconds)
        else:
            observer.stop()
            raise CommandError(
                f"Job {job.job_id} did not complete within {timeout}s. "
                f"Final status: {job.status}"
            )
        observer.stop()
        return job

    def handle(self, *args, **options):
        output = Path(options["output"])
        dry_run = options["dry_run"]
        live = options["live"]
        poll_seconds = max(options["poll_seconds"], 0.5)

        if live:
            raise CommandError(LIVE_BLOCK_REASON)

        if dry_run and live:
            raise CommandError("Cannot specify both --dry-run and --live.")
        if not dry_run and not live:
            raise CommandError("Specify either --dry-run or --live.")

        if connection.vendor != "postgresql":
            raise CommandError("This command requires PostgreSQL.")

        if output.exists() and any(output.iterdir()):
            raise CommandError(
                f"Output directory already exists and is not empty: {output}"
            )

        env_path = options["env_path"] or str(
            Path(settings.BASE_DIR).parent / "deployment" / "pseudoprod" / ".env"
        )

        payload = self._build_canonical_payload(options, require_values=live)
        payload_verification = _verify_canonical_payload(payload)

        self.stdout.write("Running preflight checks...")
        preflight = run_preflight(
            env_path=env_path,
            web_service_name=options["web_service"],
            worker_service_name=options["worker_service"],
            unc_paths=options["unc_paths"] or None,
            output_dir=str(output),
        )
        preflight["canonical_payload"] = payload_verification

        for key, value in preflight.items():
            status = "PASS" if _check_passed(value) else "FAIL"
            self.stdout.write(f"  {key}: {status}")

        preflight_pass = _all_preflight_pass(preflight)

        baseline_ok, baseline_reason = _check_canonical_baseline_configured()

        if dry_run:
            if not baseline_ok:
                self.stderr.write(f"WARNING: Baseline not configured: {baseline_reason}")
                self.stderr.write("Dry-run proceeding without baseline (live requires approved baseline).")
            else:
                self.stdout.write("Baseline configured: OK")

            payload_verification = _verify_canonical_payload(
                payload,
                known_canonical_hash=CANONICAL_BASELINE_KNOWN_HASH if CANONICAL_BASELINE_KNOWN_HASH else None,
                expected_row_count=CANONICAL_BASELINE_EXPECTED_ROW_COUNT if CANONICAL_BASELINE_EXPECTED_ROW_COUNT >= 0 else None,
                expected_unc_paths=list(CANONICAL_BASELINE_UNC_7ROOT) if CANONICAL_BASELINE_UNC_7ROOT else None,
            )
            preflight["canonical_payload"] = payload_verification
            if not payload_verification["passed"]:
                self.stderr.write(f"Canonical payload verification failed: {payload_verification['issues']}")
                raise CommandError("Dry-run aborted: canonical payload verification failed (fail-closed gate).")

            evidence = build_canonical_evidence(
                preflight=preflight,
                poll_seconds=poll_seconds,
                run_mode="dry_run",
            )
            evidence["system_metrics"] = preflight.get("system_metrics")
            privacy_ok, privacy_issues = _privacy_check_passed(evidence)
            evidence["privacy_check_passed"] = privacy_ok
            if not privacy_ok:
                for issue in privacy_issues:
                    self.stderr.write(f"Privacy issue: {issue['field']} - {issue['reason']}")
                self.stderr.write("Privacy check failed. Evidence will not be written.")
                if preflight_pass:
                    self.stderr.write("Correct privacy issues and re-run.")
                raise CommandError("Dry-run aborted: privacy check failed.")
            write_evidence(evidence, output)
            self.stdout.write(f"Dry-run evidence written to: {output}")
            if not preflight_pass:
                raise CommandError("Preflight checks failed. See evidence for details.")
            return

        if live:
            if not preflight_pass:
                raise CommandError("Preflight checks failed. Cannot proceed with live measurement.")

            if not baseline_ok:
                raise CommandError(f"Canonical baseline not configured: {baseline_reason}")

            baseline_counts = _table_counts()
            baseline_hashes = _table_stable_hashes()
            active_before = _active_job_count()
            if active_before != 0:
                raise CommandError(f"Cannot proceed: {active_before} active job(s) in queue.")

            # Live measurement with unified recovery scope
            backup_result = None
            job_a = None
            job_b = None
            coordinator = None
            metrics_monitor = None
            restart_results = []
            _live_exception = None
            cleanup_failures = []
            measurement_status = "completed"
            failure_reason = ""

            try:
                backup_result = _execute_live_backup(
                    str(output), options["web_service"], options["worker_service"],
                )
                if not backup_result["passed"]:
                    raise CommandError(
                        f"Mandatory live backup failed at step '{backup_result.get('step', 'unknown')}': "
                        f"{backup_result.get('error', 'unknown error')}"
                    )
                self.stdout.write(f"Live backup completed: {backup_result['backup_path']} "
                                  f"(SHA-256: {backup_result['backup_sha256'][:16]}...)")

                payload_verification = _verify_canonical_payload(
                    payload,
                    known_canonical_hash=CANONICAL_BASELINE_KNOWN_HASH if CANONICAL_BASELINE_KNOWN_HASH else None,
                    expected_row_count=CANONICAL_BASELINE_EXPECTED_ROW_COUNT if CANONICAL_BASELINE_EXPECTED_ROW_COUNT >= 0 else None,
                    expected_unc_paths=list(CANONICAL_BASELINE_UNC_7ROOT) if CANONICAL_BASELINE_UNC_7ROOT else None,
                )
                if not payload_verification["passed"]:
                    raise CommandError(
                        f"Canonical payload verification failed: {payload_verification['issues']}"
                    )
                preflight["canonical_payload"] = payload_verification

                self.stdout.write("Initializing transaction collector...")
                coordinator = TransactionCollector(
                    poll_seconds=poll_seconds,
                    worker_service_name=options["worker_service"],
                )
                coordinator.capture_baseline()

                self.stdout.write("Pre-arming collector (non-blocking)...")
                coordinator.pre_arm()

                self.stdout.write("Enqueuing canonical Job A and Job B (worker stopped)...")

                a_idempotency_key = f"s2-cr08-canonical-a-{timezone.now().timestamp()}"
                b_idempotency_key = f"s2-cr08-canonical-b-{timezone.now().timestamp()}"

                if Job.objects.filter(
                    idempotency_key__in=[a_idempotency_key, b_idempotency_key],
                    status__in=[Job.Status.QUEUED, Job.Status.RUNNING],
                ).exists():
                    raise CommandError("Idempotency key collision detected. Clean up pending jobs before retry.")

                job_a, a_created = enqueue_job(
                    Job.JobType.MASTER_UPDATE, payload,
                    resource_key=MASTER_RESOURCE,
                    idempotency_key=a_idempotency_key,
                )
                if not a_created:
                    raise CommandError("Job A already existed (deduplicated).")

                job_b, b_created = enqueue_job(
                    Job.JobType.MASTER_UPDATE, payload,
                    resource_key=MASTER_RESOURCE,
                    idempotency_key=b_idempotency_key,
                    depends_on=job_a,
                )
                if not b_created:
                    Job.objects.filter(job_id=job_a.job_id, status=Job.Status.QUEUED).update(
                        status=Job.Status.FAILED,
                        error_message="Cancelled: Job B deduplicated during canonical measurement",
                    )
                    raise CommandError(
                        "Job B already existed (deduplicated). Job A cancelled (if still queued)."
                    )

                # Tell the collector which job IDs to track for A/B correlation
                coordinator.set_job_ids(job_a.job_id, job_b.job_id)

                self.stdout.write("Starting metrics monitor (before service start)...")
                metrics_monitor = SystemMetricsMonitor(interval_seconds=poll_seconds)
                metrics_monitor.start()

                self.stdout.write("Starting worker and web services...")
                restart_results = []
                for svc_name, label in [(options["worker_service"], "worker"), (options["web_service"], "web")]:
                    success, details = _start_service_with_health_check(svc_name, label)
                    restart_results.append({"service": label, "name": svc_name, "success": success, "details": details})
                    if not success:
                        raise CommandError(f"Service restart verification failed for {label} ({svc_name}): {details.get('error', 'unknown')}")
                self.stdout.write("Services restarted and verified healthy.")

                self.stdout.write("Starting transaction observation baselines...")
                coordinator.wait_baseline()

                self.stdout.write("Waiting for A/B transaction assignment...")
                a_event, b_event = coordinator.get_transactions()
                # a_event = (pid, port, xact_start, start_bound, end_lower, end_upper)
                port_a, port_b = a_event[1], b_event[1]
                self.stdout.write(f"Transaction A: pid={a_event[0]}, port={port_a}, xact_start={a_event[2]}")
                self.stdout.write(f"Transaction B: pid={b_event[0]}, port={port_b}, xact_start={b_event[2]}")

                self.stdout.write("Job B created with depends_on=A, will wait while A runs.")
                try:
                    self.stdout.write("Waiting for external worker to claim and execute Job A...")
                    job_a = self._wait_for_job_with_observer(job_a, coordinator.observer_a, poll_seconds)

                    self.stdout.write("Waiting for external worker to execute Job B...")
                    job_b = self._wait_for_job_with_observer(job_b, coordinator.observer_b, poll_seconds)

                    # Wait for both transactions to complete
                    coordinator.wait_for_completion(a_event, b_event)
                except Exception:
                    measurement_status = "failed"
                    failure_reason = "job_observation_failed"
                    raise
            except Exception as e:
                self.stderr.write(f"Live measurement failed: {e}")
                if "failed" not in measurement_status:
                    measurement_status = "failed"
                if not failure_reason:
                    failure_reason = str(e)
                _live_exception = e
            finally:
                # 1. Stop monitoring/coordinator (protected)
                if metrics_monitor:
                    # Capture thread alive state before stopping (for final gate)
                    metrics_thread_alive = metrics_monitor._thread.is_alive() if metrics_monitor._thread else False
                    try:
                        metrics_monitor.stop()
                    except Exception as e:
                        cleanup_failures.append(f"metrics_monitor.stop: {e}")
                else:
                    metrics_thread_alive = False
                if coordinator:
                    try:
                        coordinator.stop()
                    except Exception as e:
                        cleanup_failures.append(f"coordinator.stop: {e}")
                if cleanup_failures:
                    for msg in cleanup_failures:
                        self.stderr.write(f"Cleanup failure: {msg}")

                # 2. Build MINIMUM evidence FIRST (always succeeds, privacy-safe)
                from quality.s2_cr08_canonical import _privacy_safe_str
                min_failure_reason = _privacy_safe_str(failure_reason) if failure_reason else ""
                evidence = _build_minimum_evidence(
                    job_a=job_a, job_b=job_b,
                    measurement_status=measurement_status,
                    failure_reason=min_failure_reason,
                    backup_evidence=backup_result,
                )

                # 3. Job cleanup (atomic CAS) - after backup only
                if backup_result and backup_result.get("passed"):
                    self.stdout.write("Cleaning up enqueued jobs after backup completion...")
                    for job in (job_a, job_b):
                        if job is None:
                            continue
                        job_id = job.job_id
                        try:
                            # Atomic CAS: only cancel QUEUED
                            updated = Job.objects.filter(job_id=job_id, status=Job.Status.QUEUED).update(
                                status=Job.Status.FAILED,
                                error_message="Cancelled due to measurement failure"
                            )
                            if updated:
                                self.stdout.write(f"Cancelled queued job {job_id}")
                            else:
                                job.refresh_from_db()
                                if job.status == Job.Status.RUNNING:
                                    self.stdout.write(f"Monitoring running job {job_id} to terminal state...")
                                    deadline = timezone.now() + timezone.timedelta(seconds=120)
                                    timeout_hit = False
                                    while timezone.now() < deadline:
                                        job.refresh_from_db()
                                        if job.status in (Job.Status.SUCCEEDED, Job.Status.FAILED):
                                            break
                                        time.sleep(poll_seconds)
                                    else:
                                        timeout_hit = True
                                    if timeout_hit:
                                        cleanup_failures.append(f"job_{_sha256(job_id)[:16]}_running_timeout")
                                        self.stderr.write(f"Job {job_id} still running after 120s timeout")
                                    else:
                                        self.stdout.write(f"Job {job_id} reached {job.status}")
                                elif job.status in (Job.Status.SUCCEEDED, Job.Status.FAILED):
                                    pass
                        except Exception as je:
                            cleanup_failures.append(f"job_{_sha256(job_id)[:16]}_cleanup_error: {_privacy_safe_str(str(je))}")
                            self.stderr.write(f"Job cleanup error: {je}")

                # 4. Service recovery (always, with read-back verification)
                recovery_results = []
                if backup_result and backup_result.get("passed"):
                    original_states = backup_result.get("original_states", {})
                    self.stdout.write("Restoring original service states...")
                    for svc_name, label in [(options["worker_service"], "worker"), (options["web_service"], "web")]:
                        original = original_states.get(svc_name, "Unknown")
                        try:
                            if original == "Running":
                                self.stdout.write(f"Restoring {label} ({svc_name}) to Running...")
                                success, details = _start_service_with_health_check(svc_name, label)
                                recovery_results.append({
                                    "service": label, "name": svc_name,
                                    "target_state": "Running", "success": success,
                                    "details": details if not success else None
                                })
                            elif original == "Stopped":
                                self.stdout.write(f"Ensuring {label} ({svc_name}) stays Stopped...")
                                import subprocess as _sp
                                stop_result = _sp.run(
                                    ["powershell", "-Command",
                                     f"Stop-Service -Name '{svc_name}' -Force -ErrorAction SilentlyContinue; "
                                     f"(Get-Service -Name '{svc_name}').Status"],
                                    capture_output=True, text=True, timeout=60,
                                )
                                stopped_ok = "Stopped" in stop_result.stdout
                                recovery_results.append({
                                    "service": label, "name": svc_name,
                                    "target_state": "Stopped", "success": stopped_ok,
                                    "details": {"stdout": stop_result.stdout.strip(), "stderr": stop_result.stderr.strip()} if not stopped_ok else None
                                })
                                if not stopped_ok:
                                    self.stderr.write(f"Stop read-back failed for {svc_name}: {stop_result.stdout.strip()}")
                            else:
                                recovery_results.append({
                                    "service": label, "name": svc_name,
                                    "target_state": original, "success": False,
                                    "error": f"Unknown original state: {original}"
                                })
                        except Exception as rec_e:
                            recovery_results.append({
                                "service": label, "name": svc_name,
                                "target_state": original, "success": False,
                                "error": str(rec_e)
                            })
                            self.stderr.write(f"Recovery failed for {label} ({svc_name}): {rec_e}")
                else:
                    recovery_results.append({
                        "note": "Backup not completed - no original states to restore", "success": True
                    })

                # 5. All enrichment steps (individually protected)
                enrichment_errors = []

                # System metrics
                try:
                    evidence["system_metrics"] = metrics_monitor.summary() if metrics_monitor else {}
                except Exception as e:
                    enrichment_errors.append(f"system_metrics: {_privacy_safe_str(str(e))}")

                # Postflight
                try:
                    postflight = run_postflight(
                        baseline_counts, baseline_hashes,
                        unc_paths=options["unc_paths"] or None,
                        web_service_name=options["web_service"],
                        worker_service_name=options["worker_service"],
                        inspection_baseline_dist=preflight.get("inspection_file_distribution"),
                        inspection_baseline_hash=preflight.get("inspection_file_pathset_hash", {}).get("pathset_hash"),
                    )
                    evidence["postflight"] = postflight
                except Exception as e:
                    enrichment_errors.append(f"postflight: {_privacy_safe_str(str(e))}")

                # Table snapshots
                try:
                    evidence["postflight_counts"] = _table_counts()
                    evidence["postflight_hashes"] = _table_stable_hashes()
                except Exception as e:
                    enrichment_errors.append(f"table_snapshots: {_privacy_safe_str(str(e))}")

                # Job verification
                try:
                    def _verify_job_safe(job, label):
                        if job is None:
                            return {"status": "not_created", "attempt_count": 0, "succeeded": False,
                                    "single_attempt": False, "has_result": False,
                                    "updated_master_count": -1, "updated_class_count": -1,
                                    "updated_structure_count": -1, "inspection_file_count": -1,
                                    "transaction_strategy": "", "folder_warnings": [], "passed": False}
                        return _verify_job_result(
                            job, label,
                            expected_master_count=emc if emc >= 0 else None,
                            expected_class_count=ecc if ecc >= 0 else None,
                            expected_structure_count=esc if esc >= 0 else None,
                        )
                    emc = CANONICAL_BASELINE_EXPECTED_MASTER_COUNT
                    ecc = CANONICAL_BASELINE_EXPECTED_CLASS_COUNT
                    esc = CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT
                    job_a_result = _verify_job_safe(job_a, "job_a")
                    job_b_result = _verify_job_safe(job_b, "job_b")
                    evidence["job_a_verification"] = job_a_result
                    evidence["job_b_verification"] = job_b_result
                except Exception as e:
                    enrichment_errors.append(f"job_verification: {_privacy_safe_str(str(e))}")

                # Observer info
                try:
                    if coordinator:
                        evidence["observer_a"] = {
                            "transaction_completed": coordinator.observer_a.transaction_completed,
                            "correlation_unique": coordinator.observer_a.correlation_unique,
                            "observation_ok": coordinator.observer_a.observation_ok,
                        }
                        evidence["observer_b"] = {
                            "transaction_completed": coordinator.observer_b.transaction_completed,
                            "correlation_unique": coordinator.observer_b.correlation_unique,
                            "observation_ok": coordinator.observer_b.observation_ok,
                        }
                except Exception as e:
                    enrichment_errors.append(f"observer_info: {_privacy_safe_str(str(e))}")

                # Cleanup failures
                try:
                    evidence["cleanup_failures"] = [_privacy_safe_str(str(f)) for f in cleanup_failures]
                except Exception as e:
                    enrichment_errors.append(f"cleanup_failures: {_privacy_safe_str(str(e))}")

                # Recovery results
                try:
                    evidence["recovery_results"] = _sanitize_recovery_results(recovery_results)
                except Exception as e:
                    enrichment_errors.append(f"recovery_results: {_privacy_safe_str(str(e))}")

                # Live verification
                try:
                    if coordinator:
                        evidence["live_verification"] = {
                            "job_a_succeeded": job_a_ok,
                            "job_b_succeeded": job_b_ok,
                            "attempt_count_a": job_a.attempt_count if job_a else 0,
                            "attempt_count_b": job_b.attempt_count if job_b else 0,
                            "observer_a_completed": obs_a_ok,
                            "observer_b_completed": obs_b_ok,
                            "postflight_pass": postflight_pass,
                            "metrics_ok": metrics_ok,
                            "metrics_thread_alive": metrics_monitor._thread and metrics_monitor._thread.is_alive() if metrics_monitor else False,
                            "metrics_coverage_ok": coverage_ok,
                            "recovery_ok": recovery_ok,
                        }
                except Exception as e:
                    enrichment_errors.append(f"live_verification: {_privacy_safe_str(str(e))}")

                evidence["enrichment_errors"] = enrichment_errors

                # 6. Final gate and formal evidence via run_canonical()
                try:
                    evidence = run_canonical(
                        job_a=job_a,
                        job_b=job_b,
                        observer_a=coordinator.observer_a if coordinator else None,
                        observer_b=coordinator.observer_b if coordinator else None,
                        preflight=preflight,
                        postflight=postflight,
                        system_metrics=evidence.get("system_metrics", {}),
                        baseline_counts=baseline_counts,
                        baseline_hashes=baseline_hashes,
                        postflight_counts=evidence.get("postflight_counts"),
                        postflight_hashes=evidence.get("postflight_hashes"),
                        correlation_info=None,
                        backup_evidence=backup_result,
                        poll_seconds=poll_seconds,
                        evidence_output_dir=str(output) if output else None,
                        web_service_name=options["web_service"],
                        worker_service_name=options["worker_service"],
                        metrics_thread_alive=metrics_thread_alive,
                        cleanup_failures=cleanup_failures,
                        recovery_results=recovery_results,
                    )
                    self.stdout.write("Final gate passed. Evidence finalized.")
                except RuntimeError as gate_err:
                    raise CommandError(f"Final gate failed: {gate_err}") from gate_err

                # Evidence write: fail-closed on write failure
                try:
                    write_evidence(evidence, output)
                    self.stdout.write(f"Evidence written to: {output}")
                except Exception as e:
                    raise CommandError(f"Evidence write failed: {_privacy_safe_str(str(e))}") from e

                if _live_exception:
                    raise CommandError(f"Live measurement failed: {failure_reason}") from _live_exception


def _check_passed(value):
    if not isinstance(value, dict):
        return bool(value)
    if value.get("passed") is False:
        return False
    if value.get("available") is False:
        return False
    if value.get("all_accessible") is False:
        return False
    if value.get("found") is False and value.get("status") != "not_found":
        return False
    if value.get("unique") is False:
        return False
    if value.get("migration_0029_applied") is False:
        return False
    if value.get("status") in ("not_provided", "no_app_setting", "incomplete", "error"):
        return False
    if value.get("baseline_matched") is False:
        return False
    return True