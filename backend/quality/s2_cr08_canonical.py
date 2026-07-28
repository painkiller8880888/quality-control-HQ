import math
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread, Event

from django.conf import settings
from django.db import connection, close_old_connections
from django.utils import timezone

from collections import Counter

from quality.s2_cr08_measurement import (
    poll_active_backends,
    _connection_pid,
    _sha256,
    _db_clock,
    _iso,
)
from quality.s2_cr08_shared import (
    ADVISORY_LOCK_NAMESPACE,
    ADVISORY_LOCK_MARKER_PREFIX,
    make_advisory_lock_id,
    make_application_name_marker,
)
from quality.models import Job

CANONICAL_SCHEMA_VERSION = "s2-cr-08-canonical-v1"

_LOCK_HELD = "HELD"
_LOCK_NOT_HELD = "NOT_HELD"
_LOCK_ERROR = "ERROR"
_MAX_ERROR_CODES = 32

# Known canonical baseline constants
# Must be set from a verified canonical run with approval before --live can proceed.
CANONICAL_BASELINE_APPROVED = False  # flip True only after real csv hash & unc roots are set
CANONICAL_BASELINE_KNOWN_HASH = ""
CANONICAL_BASELINE_EXPECTED_ROW_COUNT = -1
CANONICAL_BASELINE_UNC_7ROOT = ()
CANONICAL_BASELINE_EXPECTED_MASTER_COUNT = -1
CANONICAL_BASELINE_EXPECTED_CLASS_COUNT = -1
CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT = -1


def _worker_child_client_ports_recursive(worker_service_name, db_port=None):
    """Discover TCP client ports of worker child processes via recursive Windows process tree.
    Returns list of (child_pid, local_addr, local_port) tuples.
    Returns empty list on any failure (no worker, no children, no DB connections).
    """
    if db_port is None:
        db_port = connection.settings_dict.get("PORT", "5432")
    try:
        result = subprocess.run(
            ["powershell", "-Command", """
function Get-ChildProcessTree {
    param([int]$ParentId)
    $children = Get-CimInstance -Query "SELECT * FROM Win32_Process WHERE ParentProcessId=$ParentId" -ErrorAction SilentlyContinue
    $result = @()
    foreach ($child in $children) {
        $result += $child
        $result += Get-ChildProcessTree -ParentId $child.ProcessId
    }
    return $result
}
$worker = Get-CimInstance Win32_Service -Filter "Name='$env:WORKER_SVC'" -ErrorAction SilentlyContinue
if (-not $worker) { exit 1 }
$parent = Get-Process -Id $worker.ProcessId -ErrorAction SilentlyContinue
if (-not $parent) { exit 1 }
$allDescendants = Get-ChildProcessTree -ParentId $parent.Id
$result = @()
foreach ($child in $allDescendants) {
    $connections = Get-NetTCPConnection -OwningProcess $child.ProcessId -ErrorAction SilentlyContinue |
        Where-Object { $_.RemotePort -eq $env:DB_PORT -and $_.State -eq 'Established' }
    foreach ($conn in $connections) {
        $result += [PSCustomObject]@{ ChildPid = $child.ProcessId; LocalAddress = $conn.LocalAddress; LocalPort = $conn.LocalPort }
    }
}
if ($result.Count -eq 0) { exit 1 }
return $result | ConvertTo-Json -Compress
"""],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "WORKER_SVC": worker_service_name, "DB_PORT": str(db_port)},
        )
        if result.returncode != 0:
            return []
        import json as _json
        data = _json.loads(result.stdout.strip())
        if isinstance(data, dict):
            return [(int(data["ChildPid"]), str(data.get("LocalAddress", "")), int(data["LocalPort"]))]
        return [(int(d["ChildPid"]), str(d.get("LocalAddress", "")), int(d["LocalPort"])) for d in data]
    except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError, KeyError):
        return []


def _backend_baseline():
    rows = poll_active_backends()
    return {(r["pid"], r["client_port"]) for r in rows}


def _match_backend_by_client_port(client_port, current=None):
    if current is None:
        current = poll_active_backends()
    matches = [b for b in current if b["client_port"] == client_port and b["xact_start"] is not None]
    return matches


class ExternalWorkerObserver:
    """Observe an external worker child process transaction by client_port correlation.
    Single-shot: start() may only be called once. Repeated calls are no-ops.
    """

    def __init__(self, poll_seconds=2.0, worker_service_name="QualityControlHQ-Worker-Pseudoprod",
                 exclude_client_port=None):
        self.poll_seconds = poll_seconds
        self.worker_service_name = worker_service_name
        self.exclude_client_port = exclude_client_port
        self.backend_hash = None
        self.backend_pid = None
        self.backend_port = None
        self.xact_start = None
        self.end_lower_bound = None
        self.end_upper_bound = None
        self.poll_count = 0
        self.transaction_completed = False
        self.correlation_method = None
        self.correlation_candidate_count = 0
        self.correlation_unique = False
        self.observation_ok = False
        self._started = False
        self._stop = Event()
        self._baseline = set()
        self._baseline_ready = Event()
        self._thread = None
        self._exception = None
        self._baseline_ok = False
        self._target_client_port = None
        self._pre_armed = False
        self._discovery_attempts = 0
        self._label = None  # "A" or "B" for debugging
        self._excluded_ports = None

    def add_excluded_port(self, port):
        """Dynamically add an additional port to exclude from discovery."""
        if self._excluded_ports is None:
            self._excluded_ports = set()
        self._excluded_ports.add(port)

    def reset_discovery(self):
        """Reset discovery state so observer can search again with new exclusions."""
        self._target_client_port = None
        self.backend_hash = None
        self.backend_pid = None
        self.backend_port = None
        self.xact_start = None
        self.end_lower_bound = None
        self.end_upper_bound = None
        self.transaction_completed = False
        self.correlation_method = None
        self.correlation_candidate_count = 0
        self.correlation_unique = False
        self.observation_ok = False
        self._baseline_ok = False
        self._baseline_ready.clear()

    def restart(self):
        """Stop current thread and restart observer fresh with same settings."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise RuntimeError("ExternalWorkerObserver previous thread did not stop within 30s")
        self._stop = Event()
        self._started = False
        self._pre_armed = False
        self._thread = None
        self._exception = None
        self.reset_discovery()
        return self

    def capture_baseline(self):
        self._baseline = _backend_baseline()
        return len(self._baseline)

    def discover_child_client_port(self):
        db_port = connection.settings_dict.get("PORT", "5432")
        ports = _worker_child_client_ports_recursive(self.worker_service_name, db_port=db_port)
        if not ports:
            self.correlation_method = "process_tree_failed"
            self.correlation_candidate_count = 0
            self.correlation_unique = False
            return None
        all_unique_matches = {}
        for pid, addr, port in ports:
            matches = _match_backend_by_client_port(port)
            active = [m for m in matches if (m["pid"], m["client_port"]) not in self._baseline]
            for m in active:
                cp = m["client_port"]
                if self.exclude_client_port is not None and cp == self.exclude_client_port:
                    continue
                if self._excluded_ports is not None and cp in self._excluded_ports:
                    continue
                if cp not in all_unique_matches:
                    all_unique_matches[cp] = m
        self.correlation_candidate_count = len(all_unique_matches)
        if len(all_unique_matches) == 1:
            only_port = next(iter(all_unique_matches))
            self._target_client_port = only_port
            self.correlation_method = "process_tree_exact"
            self.correlation_unique = True
            return self._target_client_port
        self.correlation_method = "process_tree_ambiguous"
        self.correlation_unique = False
        return None

    def _do_poll(self):
        before = _db_clock()
        current = poll_active_backends()
        after = _db_clock()
        self.poll_count += 1
        ours = next(
            (b for b in current if b["client_port"] == self._target_client_port),
            None,
        )
        if ours is None:
            if self.backend_hash is not None and self.end_lower_bound is not None:
                self.end_upper_bound = after
                self.transaction_completed = True
                return True
            return False
        current_xs = ours.get("xact_start")
        if current_xs is None:
            if self.backend_hash is not None and self.end_lower_bound is not None:
                self.end_upper_bound = after
                self.transaction_completed = True
                return True
            return False
        if self.backend_hash is None:
            self.backend_pid = ours["pid"]
            self.backend_port = ours["client_port"]
            from quality.s2_cr08_measurement import _backend_hash as _bh
            self.backend_hash = _bh(ours["pid"], ours["client_port"])
            self.xact_start = current_xs
            self.end_lower_bound = before
        elif current_xs == self.xact_start:
            self.end_lower_bound = before
        else:
            self.end_upper_bound = after
            self.transaction_completed = True
            return True
        return False

    def _observe(self):
        close_old_connections()
        try:
            if self._target_client_port is None and self._pre_armed:
                while not self._stop.is_set():
                    self._discovery_attempts += 1
                    port = self.discover_child_client_port()
                    if port is not None:
                        break
                    if self._stop.wait(self.poll_seconds):
                        self._baseline_ready.set()
                        return
            if self._target_client_port is None:
                self._baseline_ready.set()
                return
            self._do_poll()
            self._baseline_ok = self.poll_count >= 1
            self._baseline_ready.set()
            while not self._stop.is_set() and self._baseline_ok:
                if self._do_poll():
                    self.observation_ok = True
                    return
                if self._stop.wait(self.poll_seconds):
                    self._do_poll()
                    return
        except Exception as e:
            self._exception = e
            self._baseline_ready.set()

    def pre_arm(self):
        if self._started:
            return self
        self._started = True
        self._pre_armed = True
        self._thread = Thread(target=self._observe, daemon=True)
        self._thread.start()
        return self

    def wait_for_discovery(self, timeout=30):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._target_client_port is not None:
                return self._target_client_port
            time.sleep(0.1)
        return None

    def start(self):
        if self._started:
            return self
        self._started = True
        self._thread = Thread(target=self._observe, daemon=True)
        self._thread.start()
        if not self._baseline_ready.wait(timeout=30):
            raise RuntimeError("ExternalWorkerObserver baseline poll did not complete within 30s")
        if self._exception:
            raise RuntimeError("ExternalWorkerObserver thread failed during baseline") from self._exception
        if not self._baseline_ok:
            if self._target_client_port is None:
                return self
            raise RuntimeError("ExternalWorkerObserver baseline poll failed")
        return self

    def stop(self):
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise RuntimeError("ExternalWorkerObserver thread did not stop within 30s")
        if self._exception:
            raise RuntimeError("ExternalWorkerObserver thread failed") from self._exception


class TransactionCollector:
    """Continuous transaction event collector: tracks worker-only backend transactions.

    Pre-arms a collector thread that polls ONLY worker child process backends.
    Emits START on new xact_start (including same-port xact_start change).
    Returns A/B events in temporal order. Works with same-port zero-gap sequential.
    Correlates A/B to exact child process that executes target Jobs.
    """

    def __init__(self, poll_seconds=2.0, worker_service_name="QualityControlHQ-Worker-Pseudoprod"):
        self.poll_seconds = poll_seconds
        self.worker_service_name = worker_service_name
        self._baseline = None
        self._events = []  # (event_type, pid, port, xact_start, start_bound, end_bound)
        self._current_backends = {}  # (pid, port) -> xact_start
        self._thread = None
        self._stop = Event()
        self._exception = None
        self._baseline_ready = Event()
        self._baseline_ok = False
        self._collector_started = False
        # Port tracking for Job-based correlation
        self._all_seen_ports = set()
        self._prev_worker_ports = set()
        self._new_ports_since_last_poll = set()
        self._pre_enqueue_ports = None
        # Job correlation fields
        self._a_job_id = None
        self._b_job_id = None
        self._a_worker_id = None
        self._b_worker_id = None
        self._a_execution_token = None
        self._b_execution_token = None
        # OS child PID (from WMI process tree) - used for process ownership
        self._a_child_os_pid = None
        self._b_child_os_pid = None
        # PostgreSQL backend PID (from pg_stat_activity) - used for transaction tracking
        self._a_child_pid = None
        self._a_child_port = None
        self._b_child_pid = None
        self._b_child_port = None
        self._a_xact_start = None
        self._b_xact_start = None
        self._a_xact_end_lower = None
        self._a_xact_end_upper = None
        self._b_xact_end_lower = None
        self._b_xact_end_upper = None
        self._a_xact_end_verified = False
        self._b_xact_end_verified = False
        self._a_start_bound = None
        self._b_start_bound = None
        self._last_poll_before = None
        self._last_poll_after = None
        # Assignment state machine (IDLE/COLLECTING/ASSIGNED/FAILED)
        self._a_state = "IDLE"
        self._a_candidates = set()
        self._a_collection_remaining = 0
        self._b_state = "IDLE"
        self._b_candidates = set()
        self._b_collection_remaining = 0
        # Error tracking (F8: bounded dict with counter)
        self._error_codes = {}
        # Addr mapping for (pid, port) → local_addr (F3)
        self._addr_map = {}

    def _get_worker_child_ports(self):
        """Get set of (pid, port) for worker child processes."""
        db_port = connection.settings_dict.get("PORT", "5432")
        ports = _worker_child_client_ports_recursive(self.worker_service_name, db_port=db_port)
        if not ports:
            return set()
        self._addr_map = {(pid, port): addr for pid, addr, port in ports}
        return {(pid, port) for pid, _, port in ports}

    def set_job_ids(self, a_job_id, b_job_id):
        """Set Job A and B IDs for transaction correlation via Job ownership.
        Freezes pre-enqueue ports so that only ports appearing after enqueue
        (subprocesses spawned by worker claim) are considered for A/B assignment.
        """
        self._a_job_id = a_job_id
        self._b_job_id = b_job_id
        self._pre_enqueue_ports = self._all_seen_ports.copy()

    def capture_baseline(self):
        """Capture baseline of worker child backends before services start.
        Stores (pid, client_port, xact_start) triples for exact identity matching.
        """
        worker_ports = self._get_worker_child_ports()
        current = poll_active_backends()
        self._baseline = set()
        for _, port in worker_ports:
            xs = None
            pg_pid = None
            for b in current:
                if b["client_port"] == port:
                    pg_pid = b["pid"]
                    xs = b.get("xact_start")
                    break
            if pg_pid is not None:
                self._baseline.add((pg_pid, port, xs))
        self._baseline_ok = True
        self._baseline_ready.set()
        return len(worker_ports)

    def pre_arm(self):
        """Start collector thread immediately - non-blocking."""
        if self._collector_started:
            return
        self._collector_started = True
        self._stop.clear()
        self._thread = Thread(target=self._collect_loop, daemon=True)
        self._thread.start()

    def wait_baseline(self, timeout=30):
        """Wait for baseline capture to complete."""
        if not self._baseline_ready.wait(timeout=timeout):
            raise RuntimeError("TransactionCollector: baseline capture timeout")
        if self._exception:
            raise RuntimeError("TransactionCollector: collector thread failed during baseline") from self._exception
        if not self._baseline_ok:
            raise RuntimeError("TransactionCollector: baseline capture failed")
        return len(self._baseline)

    def _collect_loop(self):
        close_old_connections()
        try:
            # Baseline is captured externally by the command before pre_arm().
            # The thread polls immediately without overwriting baseline.
            while not self._stop.is_set():
                self._poll_once()
                self._stop.wait(self.poll_seconds)
        except Exception as e:
            self._exception = e
            self._baseline_ready.set()

    def _poll_once(self):
        """Poll worker child backends and detect transaction transitions.
        Tracks new worker ports, checks Job claim status for A/B correlation,
        and records START/END events.

        OS child PID (from WMI process tree) and PostgreSQL backend PID
        (from pg_stat_activity) are separate domains. Joining is done by
        client_port, not by PID.
        """
        worker_ports = self._get_worker_child_ports()
        self._all_seen_ports.update(worker_ports)
        self._new_ports_since_last_poll = worker_ports - self._prev_worker_ports
        self._prev_worker_ports = worker_ports.copy()

        # Build set of client_ports for pg_stat_activity join
        _worker_client_ports = {cp for _, cp in worker_ports}

        # Check Job claim status for A/B correlation via ownership
        self._check_job_claims(worker_ports)

        before = _db_clock()
        current = poll_active_backends()
        after = _db_clock()

        # Filter to ONLY worker child backends with xact_start.
        # Join by client_port (not PID) because OS PID and PG PID differ.
        seen = {}
        for b in current:
            if b["client_port"] not in _worker_client_ports:
                continue
            key = (b["pid"], b["client_port"])
            xs = b["xact_start"]
            if xs is not None:
                seen[key] = xs

        # Detect new transactions (START) and same-port xact_start changes
        for key, xs in seen.items():
            # A/B transaction tracking from owned ports (always, regardless of baseline)
            self._track_ab_transactions(key, xs, before, after)

            # Baseline check for event emission
            if self._baseline:
                baseline_key = (key[0], key[1], xs)
                if baseline_key in self._baseline:
                    if key not in self._current_backends:
                        self._current_backends[key] = xs
                    continue

            if key not in self._current_backends:
                self._events.append(("START", key[0], key[1], xs, before, after))
                self._current_backends[key] = xs
            else:
                old_xs = self._current_backends[key]
                if xs != old_xs:
                    self._events.append(("END", key[0], key[1], old_xs, before, after))
                    self._events.append(("START", key[0], key[1], xs, before, after))
                    self._current_backends[key] = xs

        # Detect ended transactions (backend disappeared)
        for key in list(self._current_backends.keys()):
            if key not in seen:
                xs = self._current_backends.pop(key)
                end_lower = self._last_poll_before or before
                end_upper = after
                self._track_ab_disappearance(key, xs, end_lower, end_upper)
                self._events.append(("END", key[0], key[1], xs, end_lower, end_upper))
        self._last_poll_before = before
        self._last_poll_after = after

    @staticmethod
    def _verify_child_process(pid, job_id, worker_id=""):
        """Verify that the process with PID is an execute_claimed_job for the given job_id
        and worker_id. Checks the process command line via WMI. Returns True only if the
        command line contains 'execute_claimed_job' followed by the exact job_id argument
        and '--worker-id' followed by the exact worker_id argument.
        Fail-closed: returns False on any error.
        """
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | Select-Object -ExpandProperty CommandLine"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return False
            cmdline = result.stdout.strip()
            parts = cmdline.split()
            found_job = False
            found_worker = False
            for i, p in enumerate(parts):
                if p == "execute_claimed_job" and i + 1 < len(parts) and parts[i + 1] == job_id:
                    found_job = True
                if p == "--worker-id" and i + 1 < len(parts):
                    if worker_id and parts[i + 1] == worker_id:
                        found_worker = True
                    elif not worker_id:
                        found_worker = True
            return found_job and found_worker
        except Exception:
            return False

    def _check_job_claims(self, worker_ports):
        """Detect Job ownership from execution tokens and accumulate port candidates.
        State machine per job: IDLE → COLLECTING → ASSIGNED | FAILED.

        COLLECTING uses a bounded window (_collection_remaining polls). Only PIDs
        whose command line matches `execute_claimed_job <job_id>` are admitted.
        When the window closes:
          - 1 → ASSIGNED (immutable)
          - 0 at deadline → FAILED; 0 before deadline → keeps waiting
          - 2+ → FAILED
        """
        from quality.models import Job
        try:
            close_old_connections()
            pre = self._pre_enqueue_ports or set()

            def _active_assigned_ports():
                s = set()
                if self._a_state == "ASSIGNED" and self._a_child_os_pid is not None and self._a_xact_end_lower is None:
                    s.add((self._a_child_os_pid, self._a_child_port))
                if self._b_state == "ASSIGNED" and self._b_child_os_pid is not None and self._b_xact_end_lower is None:
                    s.add((self._b_child_os_pid, self._b_child_port))
                return s

            def _collect(job_id, worker_id, cand_attr, rem_attr):
                current = getattr(self, cand_attr)
                raw = self._new_ports_since_last_poll - pre - _active_assigned_ports() if current else (worker_ports - pre - _active_assigned_ports())
                verified = {(p, pt) for p, pt in raw if self._verify_child_process(p, job_id, worker_id)}
                current.update(verified)
                setattr(self, cand_attr, current)
                rem = getattr(self, rem_attr)
                if current and rem == 0:
                    setattr(self, rem_attr, 1)
                    return False
                if rem > 0:
                    rem -= 1
                    setattr(self, rem_attr, rem)
                    if rem == 0:
                        return True
                return False

            # ── Job A ──
            if self._a_job_id is not None and self._a_state == "IDLE":
                try:
                    job = Job.objects.get(job_id=self._a_job_id)
                    if (job.status == Job.Status.RUNNING
                            and job.worker_id
                            and job.execution_token):
                        self._a_state = "COLLECTING"
                        self._a_worker_id = job.worker_id
                        self._a_execution_token = job.execution_token
                        self._a_collection_remaining = 0
                except Job.DoesNotExist:
                    self._add_error_code("A_job_not_found")

            if self._a_state == "COLLECTING":
                if _collect(self._a_job_id, self._a_worker_id, "_a_candidates", "_a_collection_remaining"):
                    self._resolve_candidates(self, "A", worker_ports)

            # ── Job B (processed after A) ──
            if self._b_job_id is not None and self._b_state == "IDLE":
                try:
                    job = Job.objects.get(job_id=self._b_job_id)
                    if (job.status == Job.Status.RUNNING
                            and job.worker_id
                            and job.execution_token):
                        self._b_state = "COLLECTING"
                        self._b_worker_id = job.worker_id
                        self._b_execution_token = job.execution_token
                        self._b_collection_remaining = 0
                except Job.DoesNotExist:
                    self._add_error_code("B_job_not_found")

            if self._b_state == "COLLECTING":
                if _collect(self._b_job_id, self._b_worker_id, "_b_candidates", "_b_collection_remaining"):
                    self._resolve_candidates(self, "B", worker_ports)

            # ── Post-ASSIGNMENT monitoring ──
            # After ASSIGNED, verify execution token still matches.
            # If the Job reached a terminal state (SUCCEEDED/FAILED), the
            # token clear is a normal terminal transition, not a failure.
            if self._a_state == "ASSIGNED" and self._a_job_id is not None:
                try:
                    job = Job.objects.get(job_id=self._a_job_id)
                    if job.status in (Job.Status.SUCCEEDED, Job.Status.FAILED):
                        pass
                    elif job.execution_token != self._a_execution_token:
                        self._a_state = "FAILED"
                        self._add_error_code("A_token_changed")
                except Job.DoesNotExist:
                    self._a_state = "FAILED"
                    self._add_error_code("A_job_gone")
                # Also detect new ports from same OS PID (F2 ambiguity)
                if (self._a_state == "ASSIGNED" and self._a_child_os_pid is not None
                        and not self._a_xact_end_verified):
                    same_pid_new = {(p, pt) for p, pt in worker_ports
                                    if p == self._a_child_os_pid and pt != self._a_child_port}
                    if same_pid_new:
                        self._a_state = "FAILED"
                        self._a_candidates.update(same_pid_new)
                        self._add_error_code("A_same_pid_new_port")
            if self._b_state == "ASSIGNED" and self._b_job_id is not None:
                try:
                    job = Job.objects.get(job_id=self._b_job_id)
                    if job.status in (Job.Status.SUCCEEDED, Job.Status.FAILED):
                        pass
                    elif job.execution_token != self._b_execution_token:
                        self._b_state = "FAILED"
                        self._add_error_code("B_token_changed")
                except Job.DoesNotExist:
                    self._b_state = "FAILED"
                    self._add_error_code("B_job_gone")
                if (self._b_state == "ASSIGNED" and self._b_child_os_pid is not None
                        and not self._b_xact_end_verified):
                    same_pid_new = {(p, pt) for p, pt in worker_ports
                                    if p == self._b_child_os_pid and pt != self._b_child_port}
                    if same_pid_new:
                        self._b_state = "FAILED"
                        self._b_candidates.update(same_pid_new)
                        self._add_error_code("B_same_pid_new_port")

        except Exception as e:
            self._add_error_code(f"check_job_claims_error:{type(e).__name__}")

    @staticmethod
    def _resolve_candidates(instance, label, worker_ports=None):
        """Check candidate count and transition state.
        Exactly 1 → ASSIGNED with (os_pid, port) and PG backend PID.
        0 → keep COLLECTING. 2+ → FAILED.

        Stores OS PID as `_child_os_pid` (from WMI process tree).
        Looks up PostgreSQL backend PID from active backends by
        (client_addr, client_port) when candidate addr is available
        via _addr_map, falling back to client_port-only join.
        """
        lo = label.lower()
        os_pid_field = f"_{lo}_child_os_pid"
        pg_pid_field = f"_{lo}_child_pid"
        port_field = f"_{lo}_child_port"
        state_field = f"_{lo}_state"
        candidates_field = f"_{lo}_candidates"

        candidates = getattr(instance, candidates_field)
        if len(candidates) == 1:
            os_pid, port = next(iter(candidates))
            setattr(instance, os_pid_field, os_pid)
            setattr(instance, port_field, port)
            addr = getattr(instance, '_addr_map', {}).get((os_pid, port), "")
            # Look up PostgreSQL backend PID by (client_addr, client_port).
            # OS PID and PG PID are separate domains — never fallback.
            # Require exactly 1 match; 0 or 2+ → FAILED.
            # Address missing → fail closed (F5).
            if not addr:
                instance._add_error_code(f"{label}_addr_missing")
                setattr(instance, state_field, "FAILED")
                return
            try:
                current = poll_active_backends()
                pg_backends = [b for b in current
                               if b["client_port"] == port
                               and str(b.get("client_addr") or "") == addr]
                if len(pg_backends) == 1:
                    setattr(instance, pg_pid_field, pg_backends[0]["pid"])
                    setattr(instance, state_field, "ASSIGNED")
                elif len(pg_backends) > 1:
                    instance._add_error_code(f"{label}_pg_match_ambiguous")
                    setattr(instance, state_field, "FAILED")
                else:
                    instance._add_error_code(f"{label}_pg_match_not_found")
                    setattr(instance, state_field, "FAILED")
            except Exception:
                instance._add_error_code(f"{label}_pg_lookup_error")
                setattr(instance, state_field, "FAILED")
        elif len(candidates) > 1:
            setattr(instance, state_field, "FAILED")

    def _check_advisory_lock(self, pid, job_id, execution_token=""):
        """Check if the backend with PID holds the advisory lock for the target job (F3/F4).
        Returns HELD / NOT_HELD / ERROR — never collapses errors to False.
        Uses two-arg advisory lock (namespace=42, objsubid=2) + application_name marker (F1/F6).
        """
        try:
            lock_id = make_advisory_lock_id(job_id, execution_token)
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 1 FROM pg_locks
                    WHERE locktype = 'advisory'
                      AND pid = %s AND classid = %s AND objid = %s AND objsubid = 2 AND granted
                """, [pid, ADVISORY_LOCK_NAMESPACE, lock_id])
                if cursor.fetchone() is None:
                    return _LOCK_NOT_HELD
                # Secondary verification: check application_name marker (F6)
                expected_app = make_application_name_marker(job_id, execution_token)
                cursor.execute("""
                    SELECT 1 FROM pg_stat_activity
                    WHERE pid = %s AND application_name = %s
                """, [pid, expected_app])
                return _LOCK_HELD if cursor.fetchone() is not None else _LOCK_NOT_HELD
        except Exception:
            return _LOCK_ERROR

    def _add_error_code(self, code):
        """Bounded error code storage (F8/F5).
        Existing codes always increment. New codes are capped at _MAX_ERROR_CODES distinct codes.
        """
        if code in self._error_codes:
            self._error_codes[code] += 1
        elif len(self._error_codes) < _MAX_ERROR_CODES:
            self._error_codes[code] = 1

    def _track_ab_transactions(self, key, xs, before, after):
        """Track A/B transaction state from owned child ports using exact (pid, port).
        Called for each seen backend on every poll, regardless of baseline.
        Records xact_start and detects END when transaction changes on owned port.
        Same-port transition: old END upper bound = new xs (definitive end before new start).
        Lower bound = _last_poll_before (previous poll's before, safe from race with after).

        Uses pg_advisory_xact_lock marker set by services.run_job() during the
        main work transaction. Target assignment requires POSITIVE marker observation:
        - First xact_start is never accepted without advisory lock (F1).
        - Transaction transitions only declare target END when a lock state is observed (F2).
        - Query errors fail closed via tri-state HELD/NOT_HELD/ERROR (F3).
        - Marker includes execution_token for attempt-unique identity (F4).
        """
        # Track A
        if (self._a_state == "ASSIGNED" and self._a_child_pid == key[0]
                and self._a_child_port == key[1]):
            if self._a_xact_start is None:
                lock_state = self._check_advisory_lock(key[0], self._a_job_id, self._a_execution_token)
                if lock_state == _LOCK_HELD:
                    self._a_xact_start = xs
                    self._a_start_bound = before
                elif lock_state == _LOCK_ERROR:
                    self._a_state = "FAILED"
                    self._add_error_code("A_advisory_lock_error")
            elif xs != self._a_xact_start:
                if self._a_xact_end_lower is None:
                    lock_state = self._check_advisory_lock(key[0], self._a_job_id, self._a_execution_token)
                    if lock_state == _LOCK_HELD:
                        self._a_xact_end_lower = self._last_poll_before or before
                        self._a_xact_end_upper = xs
                        self._a_xact_end_verified = True
                        self._a_xact_start = xs
                        self._a_start_bound = before
                    elif lock_state == _LOCK_NOT_HELD:
                        self._a_xact_end_lower = self._last_poll_before or before
                        self._a_xact_end_upper = xs
                        self._a_xact_end_verified = True
                    else:
                        self._a_state = "FAILED"
                        self._add_error_code("A_advisory_lock_error")
        # Track B
        if (self._b_state == "ASSIGNED" and self._b_child_pid == key[0]
                and self._b_child_port == key[1]):
            if self._b_xact_start is None:
                lock_state = self._check_advisory_lock(key[0], self._b_job_id, self._b_execution_token)
                if lock_state == _LOCK_HELD:
                    self._b_xact_start = xs
                    self._b_start_bound = before
                elif lock_state == _LOCK_ERROR:
                    self._b_state = "FAILED"
                    self._add_error_code("B_advisory_lock_error")
            elif xs != self._b_xact_start:
                if self._b_xact_end_lower is None:
                    lock_state = self._check_advisory_lock(key[0], self._b_job_id, self._b_execution_token)
                    if lock_state == _LOCK_HELD:
                        self._b_xact_end_lower = self._last_poll_before or before
                        self._b_xact_end_upper = xs
                        self._b_xact_end_verified = True
                        self._b_xact_start = xs
                        self._b_start_bound = before
                    elif lock_state == _LOCK_NOT_HELD:
                        self._b_xact_end_lower = self._last_poll_before or before
                        self._b_xact_end_upper = xs
                        self._b_xact_end_verified = True
                    else:
                        self._b_state = "FAILED"
                        self._add_error_code("B_advisory_lock_error")

    def _track_ab_disappearance(self, key, xs, end_lower, end_upper):
        """Track A/B END when owned backend disappears using exact (pid, port).
        Only records END when target START was confirmed by positive marker (F2).
        Requires xs matches saved _a_xact_start to ensure we end the correct transaction.
        Uses end_lower (previous poll before) and end_upper (current poll after)
        as disappearance bounds (P0-2 #5).
        """
        if (self._a_state == "ASSIGNED" and self._a_child_pid == key[0]
                and self._a_child_port == key[1] and self._a_xact_end_lower is None
                and self._a_xact_start is not None and xs == self._a_xact_start):
            self._a_xact_end_lower = end_lower
            self._a_xact_end_upper = end_upper
            self._a_xact_end_verified = True
        if (self._b_state == "ASSIGNED" and self._b_child_pid == key[0]
                and self._b_child_port == key[1] and self._b_xact_end_lower is None
                and self._b_xact_start is not None and xs == self._b_xact_start):
            self._b_xact_end_lower = end_lower
            self._b_xact_end_upper = end_upper
            self._b_xact_end_verified = True

    def get_transactions(self, timeout=120):
        """Wait for and return A/B transaction info determined by Job ownership.

        Collector uses a state machine per job: IDLE → COLLECTING → ASSIGNED/FAILED.
        Assignment requires exactly 1 port candidate per job, verified via
        execution ownership (worker_id + execution_token non-empty) and
        exact (pid, port) backend identity.

        Raises RuntimeError on:
        - timeout (A/B not both ASSIGNED within deadline)
        - FAILED state (0 or 2+ candidates for either job)
        - A/B port collision

        Returns (a_info, b_info) where each is (pid, port, xact_start, start_bound, end_bound)
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._a_state == "FAILED" or self._b_state == "FAILED":
                a_count = len(self._a_candidates)
                b_count = len(self._b_candidates)
                a_hash = _sha256(str(sorted(self._a_candidates))) if self._a_candidates else ""
                b_hash = _sha256(str(sorted(self._b_candidates))) if self._b_candidates else ""
                err_codes = ",".join(sorted(self._error_codes.keys()))
                err_counts = ",".join(f"{k}:{v}" for k, v in sorted(self._error_codes.items()))
                raise RuntimeError(
                    f"Candidate assignment failed: "
                    f"A_state={self._a_state}, A_cand_count={a_count}, A_cand_hash={a_hash}, "
                    f"B_state={self._b_state}, B_cand_count={b_count}, B_cand_hash={b_hash}, "
                    f"error_codes=[{err_codes}], errors=[{err_counts}]"
                )
            if self._a_state == "ASSIGNED" and self._b_state == "ASSIGNED":
                if self._a_xact_start is not None and self._b_xact_start is not None:
                    # Same (pid, port) is allowed for same-port sequential if
                    # A and B have different xact_start and A ended before B started.
                    if (self._a_child_pid, self._a_child_port) == (self._b_child_pid, self._b_child_port):
                        if not (self._a_xact_start != self._b_xact_start
                                and self._a_xact_end_verified
                                and self._a_xact_end_upper <= self._b_xact_start):
                            raise RuntimeError(
                                f"A/B collision: same port but A end not verified "
                                f"or ordering not satisfied"
                            )
                    # Invariant: END bounds must never be inverted (F1 race guard)
                    for label, lo, hi in [("A", self._a_xact_end_lower, self._a_xact_end_upper),
                                          ("B", self._b_xact_end_lower, self._b_xact_end_upper)]:
                        if lo is not None and hi is not None and lo > hi:
                            raise RuntimeError(
                                f"{label} END bounds inverted: lower={lo} > upper={hi}"
                            )
                    a_info = (self._a_child_pid, self._a_child_port, self._a_xact_start,
                              self._a_start_bound, self._a_xact_end_lower, self._a_xact_end_upper)
                    b_info = (self._b_child_pid, self._b_child_port, self._b_xact_start,
                              self._b_start_bound, self._b_xact_end_lower, self._b_xact_end_upper)
                    return a_info, b_info
            time.sleep(0.1)
        a_count = len(self._a_candidates)
        b_count = len(self._b_candidates)
        a_hash = _sha256(str(sorted(self._a_candidates))) if self._a_candidates else ""
        b_hash = _sha256(str(sorted(self._b_candidates))) if self._b_candidates else ""
        err_codes = ",".join(sorted(self._error_codes.keys()))
        err_counts = ",".join(f"{k}:{v}" for k, v in sorted(self._error_codes.items()))
        raise RuntimeError(
            f"Timed out waiting for A/B transactions. "
            f"A_state={self._a_state}, A_cand_count={a_count}, A_cand_hash={a_hash}, "
            f"B_state={self._b_state}, B_cand_count={b_count}, B_cand_hash={b_hash}, "
            f"error_codes=[{err_codes}], errors=[{err_counts}]"
        )

    def wait_for_completion(self, a_event, b_event, timeout=120):
        """Wait for both transactions to complete via verified END state.
        Uses _xact_end_verified per target identity (pid, port, xact_start, marker).
        Raises RuntimeError on timeout — caller must treat as failure (P0-2 #7).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._a_xact_end_verified and self._b_xact_end_verified:
                return True
            time.sleep(0.5)
        raise RuntimeError(
            f"wait_for_completion timed out after {timeout}s: "
            f"A verified={self._a_xact_end_verified}, "
            f"B verified={self._b_xact_end_verified}"
        )

    def stop(self):
        """Stop collector thread. Fail-closed: raises on join timeout or internal exception (P0-2 #8)."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise RuntimeError("TransactionCollector thread did not stop within 30s")
        if self._exception:
            raise RuntimeError("TransactionCollector failed") from self._exception

    # Backward compatibility properties for evidence
    @property
    def observer_a(self):
        class Shim:
            def __init__(self, collector):
                self._collector = collector
            def stop(self):
                """No-op: the collector manages the thread lifetime."""
                pass
            @property
            def xact_start(self):
                return self._collector._a_xact_start
            @property
            def transaction_completed(self):
                return self._collector._a_xact_end_verified
            @property
            def correlation_unique(self):
                return self._collector._a_xact_start is not None and self._collector._b_xact_start is not None
            @property
            def observation_ok(self):
                return self.transaction_completed
            @property
            def _target_client_port(self):
                return self._collector._a_child_port
            @property
            def end_lower_bound(self):
                return self._collector._a_xact_end_lower
            @property
            def end_upper_bound(self):
                return self._collector._a_xact_end_upper
            @property
            def backend_hash(self):
                return None
            @property
            def poll_count(self):
                return 0
            @property
            def correlation_method(self):
                return None
            @property
            def correlation_candidate_count(self):
                return 0
            @property
            def correlation_unique_shim(self):
                return False
        return Shim(self)

    @property
    def observer_b(self):
        class Shim:
            def __init__(self, collector):
                self._collector = collector
            def stop(self):
                """No-op: the collector manages the thread lifetime."""
                pass
            @property
            def xact_start(self):
                return self._collector._b_xact_start
            @property
            def transaction_completed(self):
                return self._collector._b_xact_end_verified
            @property
            def correlation_unique(self):
                return self._collector._a_xact_start is not None and self._collector._b_xact_start is not None
            @property
            def observation_ok(self):
                return self.transaction_completed
            @property
            def _target_client_port(self):
                return self._collector._b_child_port
            @property
            def end_lower_bound(self):
                return self._collector._b_xact_end_lower
            @property
            def end_upper_bound(self):
                return self._collector._b_xact_end_upper
            @property
            def backend_hash(self):
                return None
            @property
            def poll_count(self):
                return 0
            @property
            def correlation_method(self):
                return None
            @property
            def correlation_candidate_count(self):
                return 0
            @property
            def correlation_unique_shim(self):
                return False
        return Shim(self)

# Backward compatibility alias
TransactionCoordinator = TransactionCollector


class SystemMetricsMonitor:
    """Sample system metrics at regular intervals during measurement."""

    def __init__(self, interval_seconds=2.0):
        # F2: Enforce max 5s interval for gate coverage check
        self.interval_seconds = min(max(interval_seconds, 0.5), 5.0)
        self._samples = []
        self._stop = Event()
        self._thread = None
        self._exception = None

    def start(self):
        if self._thread is not None:
            return self
        self._stop.clear()
        self._thread = Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._thread:
            self._stop.set()
            # F6: Take a final sample before joining
            final_sample = self._take_sample()
            self._samples.append(final_sample)
            self._thread.join(timeout=60)
            if self._thread.is_alive():
                raise RuntimeError("SystemMetricsMonitor thread did not stop within 60s")
        if self._exception:
            raise RuntimeError("SystemMetricsMonitor failed") from self._exception

    def _sample_loop(self):
        close_old_connections()
        try:
            while not self._stop.is_set():
                sample = self._take_sample()
                self._samples.append(sample)
                self._stop.wait(self.interval_seconds)
        except Exception as e:
            self._exception = e

    def _take_sample(self):
        import psutil
        sample = {"timestamp": timezone.now().isoformat()}
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            sample["db_connections"] = cursor.fetchone()[0]
            cursor.execute("""
                SELECT count(*) FROM pg_locks
                WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
                  AND NOT granted
            """)
            sample["waiting_locks"] = cursor.fetchone()[0]
            cursor.execute("""
                SELECT count(*) FROM pg_locks
                WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
                  AND granted
            """)
            sample["granted_locks"] = cursor.fetchone()[0]
        try:
            sample["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            sample["memory_percent"] = round(mem.percent, 1)
        except Exception:
            pass
        return sample

    def summary(self):
        if not self._samples:
            return {"samples": [], "sample_count": 0}
        cpu_vals = [s.get("cpu_percent") for s in self._samples if s.get("cpu_percent") is not None]
        mem_vals = [s.get("memory_percent") for s in self._samples if s.get("memory_percent") is not None]
        db_vals = [s.get("db_connections") for s in self._samples]
        waiting_vals = [s.get("waiting_locks") for s in self._samples]
        return {
            "sample_count": len(self._samples),
            "interval_seconds": self.interval_seconds,
            "first_sample": self._samples[0]["timestamp"],
            "last_sample": self._samples[-1]["timestamp"],
            "cpu_percent_max": max(cpu_vals) if cpu_vals else None,
            "memory_percent_max": max(mem_vals) if mem_vals else None,
            "db_connections_max": max(db_vals) if db_vals else None,
            "waiting_locks_max": max(waiting_vals) if waiting_vals else None,
            "samples": self._samples,
            "has_data": bool(cpu_vals or mem_vals),
        }


def _table_stable_hash(model_class, field_names=None):
    if field_names is None:
        field_names = [f.name for f in model_class._meta.fields if f.name not in ("updated_at",)]
    rows = list(model_class.objects.all().order_by("pk").values(*field_names))
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _table_counts():
    from quality.models import Master, MasterClass, Structure, InspectionFile
    return {
        "master_count": Master.objects.count(),
        "master_class_count": MasterClass.objects.count(),
        "structure_count": Structure.objects.count(),
        "inspection_file_count": InspectionFile.objects.count(),
    }


def _table_stable_hashes():
    from quality.models import Master, MasterClass, Structure, InspectionFile
    return {
        "master_hash": _table_stable_hash(Master),
        "master_class_hash": _table_stable_hash(MasterClass),
        "structure_hash": _table_stable_hash(Structure),
        "inspection_file_hash": _table_stable_hash(InspectionFile),
    }


def _active_job_count():
    return Job.objects.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).count()


def _running_job_count():
    return Job.objects.filter(status=Job.Status.RUNNING).count()


def _check_django():
    from django.core.management import call_command
    from io import StringIO
    out = StringIO()
    err = StringIO()
    try:
        call_command("check", stdout=out, stderr=err)
        return {"passed": True, "output": out.getvalue() + err.getvalue()}
    except SystemExit as e:
        return {"passed": False, "output": out.getvalue() + err.getvalue(), "code": e.code}
    except Exception as e:
        return {"passed": False, "output": str(e)}


def _check_migrations():
    from django.core.management import call_command
    from io import StringIO
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
        return {"passed": True}
    except SystemExit as e:
        return {"passed": False, "output": out.getvalue(), "code": e.code}
    except Exception as e:
        return {"passed": False, "output": str(e)}


def _check_migration_0029_applied():
    from django.db.migrations.recorder import MigrationRecorder
    applied = MigrationRecorder.Migration.objects.filter(
        app="quality", name="0029_job_created_at"
    ).exists()
    return {"passed": applied, "migration_0029_applied": applied}


def _get_env_identity(env_path=None):
    if env_path is None:
        env_path = Path(settings.BASE_DIR).parent / "deployment" / "pseudoprod" / ".env"
    env_path = Path(env_path)
    if not env_path.exists():
        return {"passed": False, "found": False, "status": "not_found"}
    lines = env_path.read_text(encoding="utf-8").strip().splitlines()
    env_vars = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env_vars[k.strip()] = v.strip()
    expected_db_name = env_vars.get("DB_NAME", "")
    expected_db_host = env_vars.get("DB_HOST", "")
    expected_db_user = env_vars.get("DB_USER", "")
    env_file_app_env = env_vars.get("APP_ENV", "")
    runtime_app_env = getattr(settings, "APP_ENV", "")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), inet_server_addr(), inet_server_port(), current_user")
        row = cursor.fetchone()
        server_db_name = row[0] if row else ""
        server_addr = str(row[1]) if row and row[1] else ""
        server_port = str(row[2]) if row and row[2] else ""
        server_user = row[3] if row else ""
    runtime_env_match = runtime_app_env == "pseudoprod"
    env_file_env_match = env_file_app_env == "pseudoprod"
    name_match = server_db_name == expected_db_name
    host_match = server_addr == expected_db_host or (
        server_addr in ("127.0.0.1", "localhost") and expected_db_host in ("127.0.0.1", "localhost")
    )
    user_match = server_user == expected_db_user
    passed = name_match and host_match and user_match and runtime_env_match and env_file_env_match
    result = {
        "passed": passed,
        "found": True,
        "runtime_app_env": runtime_app_env,
        "env_file_app_env": env_file_app_env,
        "runtime_env_mismatch": not runtime_env_match,
        "env_file_env_mismatch": not env_file_env_match,
        "db_name_matched": name_match,
        "db_host_matched": host_match,
        "db_user_matched": user_match,
    }
    return result


def _check_service_status(service_name):
    try:
        result = subprocess.run(
            ["powershell", "-Command", f"""
$svc = Get-Service -Name '{service_name}' -ErrorAction SilentlyContinue
if (-not $svc) {{ exit 1 }}
Write-Output "$($svc.Status)|$($svc.StartType)"
"""],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"passed": False, "found": False, "status": "not_found"}
        parts = result.stdout.strip().split("|")
        status = parts[0] if len(parts) > 0 else ""
        start_type = parts[1] if len(parts) > 1 else ""
        running = status == "Running"
        automatic = start_type == "Automatic"
        return {
            "passed": running and automatic,
            "found": True,
            "status": status,
            "start_type": start_type,
            "running": running,
            "automatic": automatic,
        }
    except (subprocess.TimeoutExpired, IndexError):
        return {"passed": False, "found": False, "status": "error"}


def _check_http(url=None):
    import urllib.request
    if url is None:
        host = getattr(settings, "APP_PUBLIC_HOST", "127.0.0.1")
        port = getattr(settings, "APP_PUBLIC_PORT", "8080")
        url = f"http://{host}:{port}/"
    from urllib.request import Request, urlopen
    from urllib.error import URLError
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=10) as resp:
            return {"passed": resp.status == 200, "status_code": resp.status}
    except URLError as e:
        return {"passed": False, "status_code": getattr(e, "code", None), "error": str(e)}
    except Exception as e:
        return {"passed": False, "error": str(e)}


def _start_service_with_health_check(svc_name, label):
    """Start a Windows service and verify it's Running with HTTP health check.
    Returns (success: bool, details: dict).
    F6: Verifies service status and HTTP health, not just fire-and-forget.
    """
    _validate_service_name(svc_name)
    steps = []
    try:
        # Start service
        r = subprocess.run(
            ["powershell", "-Command",
             f"Start-Service -Name '{svc_name}' -ErrorAction SilentlyContinue; "
             f"(Get-Service -Name '{svc_name}').Status"],
            capture_output=True, text=True, timeout=60,
        )
        running = "Running" in r.stdout
        steps.append({"step": f"start_{label}_service", "passed": running, "output": r.stdout.strip()})
        if not running:
            return False, {"steps": steps, "error": "Service did not reach Running state"}

        # Wait a moment for service to fully initialize
        import time as _time
        _time.sleep(3)

        # Verify service status again (read-back)
        r2 = subprocess.run(
            ["powershell", "-Command", f"(Get-Service -Name '{svc_name}').Status"],
            capture_output=True, text=True, timeout=15,
        )
        running_readback = "Running" in r2.stdout
        steps.append({"step": f"verify_{label}_service_status", "passed": running_readback, "output": r2.stdout.strip()})
        if not running_readback:
            return False, {"steps": steps, "error": "Service status read-back not Running"}

        # HTTP health check (web service only)
        if label == "web":
            http_result = _check_http()
            steps.append({"step": "http_health_check", "passed": http_result.get("passed", False),
                          "status_code": http_result.get("status_code"), "error": http_result.get("error")})
            if not http_result.get("passed"):
                return False, {"steps": steps, "error": "HTTP health check failed"}

        return True, {"steps": steps}
    except Exception as e:
        steps.append({"step": f"start_{label}_service", "passed": False, "error": str(e)})
        return False, {"steps": steps, "error": str(e)}


def _check_unc_paths(unc_paths):
    if not unc_paths:
        return {"passed": False, "configured_count": 0, "accessible_count": 0, "all_accessible": False, "details": [], "status": "not_provided"}
    results = []
    accessible_count = 0
    for path in unc_paths:
        p = Path(path)
        try:
            entries = list(p.iterdir()) if p.is_dir() else []
            accessible = p.exists()
        except (OSError, PermissionError):
            accessible = False
            entries = []
        results.append({
            "path_hash": _sha256(path),
            "accessible": accessible,
            "entry_count": len(entries) if accessible else 0,
        })
        if accessible:
            accessible_count += 1
    all_accessible = accessible_count == len(unc_paths)
    return {
        "passed": all_accessible,
        "configured_count": len(unc_paths),
        "accessible_count": accessible_count,
        "all_accessible": all_accessible,
        "details": results,
    }


def _check_backup_tool():
    candidates = ["pg_dump", r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe", r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe", r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"]
    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return {"passed": True, "available": True, "version": result.stdout.strip(), "tool_path": candidate}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return {"passed": False, "available": False}


def _check_backup_preparedness(output_dir):
    tool = _check_backup_tool()
    if not tool["passed"]:
        return {"passed": False, "tool_available": False}
    out = Path(output_dir)
    backup_dir = out.parent / f"{out.name}-backup"
    parent = backup_dir.parent
    parent_ok = parent.exists()
    parent_writable = False
    if parent_ok:
        try:
            parent_writable = os.access(str(parent), os.W_OK)
        except OSError:
            parent_writable = False
    return {
        "passed": parent_ok and parent_writable,
        "tool_available": True,
        "tool_path": tool.get("path", ""),
        "backup_output_dir": str(backup_dir),
        "backup_output_writable": parent_writable,
        "parent_dir_exists": parent_ok,
    }


_ALLOWED_SERVICE_NAMES = frozenset({
    "QualityControlHQ-Pseudoprod",
    "QualityControlHQ-Worker-Pseudoprod",
})


def _validate_service_name(name):
    if name not in _ALLOWED_SERVICE_NAMES:
        raise ValueError(f"Service name not in allowed set: {name}")


def _get_service_status(svc_name):
    _validate_service_name(svc_name)
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             f"(Get-Service -Name '{svc_name}').Status"],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip()
    except Exception:
        return "Unknown"


def _execute_live_backup(output_dir, web_service_name, worker_service_name):
    _validate_service_name(web_service_name)
    _validate_service_name(worker_service_name)
    steps = []
    out = Path(output_dir)
    backup_dir = out.parent / f"{out.name}-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"s2-cr08-canonical-{timestamp}.dump"

    # Pre-stop state tracking (F2: preserve original service state for correct recovery)
    original_states = {}
    backup_sha256 = ""
    backup_size = 0
    restore_entries = 0
    failed = False
    fail_step = ""
    fail_msg = ""
    callers_stopped_services = []
    exception_occurred = False

    try:
        original_states[web_service_name] = _get_service_status(web_service_name)
        original_states[worker_service_name] = _get_service_status(worker_service_name)

        active = _active_job_count()
        if active != 0:
            failed = True
            fail_step = "pre_stop_active_job_check"
            fail_msg = f"{active} active job(s)"
        else:
            steps.append({"step": "pre_stop_active_job_check", "passed": True})

        if not failed:
            for svc_name, label in [(web_service_name, "web"), (worker_service_name, "worker")]:
                r = subprocess.run(
                    ["powershell", "-Command",
                     f"Stop-Service -Name '{svc_name}' -Force -ErrorAction SilentlyContinue; "
                     f"(Get-Service -Name '{svc_name}').Status"],
                    capture_output=True, text=True, timeout=30,
                )
                stopped = "Stopped" in r.stdout
                steps.append({"step": f"stop_{label}_service", "passed": stopped, "output": r.stdout.strip()})
                # F2: Only track services we actually stopped that were originally Running
                if stopped and original_states.get(svc_name) == "Running":
                    callers_stopped_services.append(svc_name)
                if not stopped:
                    failed = True
                    fail_step = f"stop_{label}_service"
                    fail_msg = r.stdout.strip()
                    break

        if not failed:
            active = _active_job_count()
            if active != 0:
                failed = True
                fail_step = "post_stop_active_job_check"
                fail_msg = f"{active} active job(s)"
            else:
                steps.append({"step": "post_stop_active_job_check", "passed": True})

        if not failed:
            tool = _check_backup_tool()
            if not tool["available"]:
                failed = True
                fail_step = "backup_tool"
                fail_msg = "pg_dump not available"
            else:
                steps.append({"step": "backup_tool", "passed": True, "tool_path": tool["tool_path"]})

        if not failed:
            db = settings.DATABASES["default"]
            env = {**os.environ, "PGPASSWORD": db.get("PASSWORD", "")}
            dump_args = [
                tool["tool_path"], "-h", db.get("HOST", "localhost"), "-p", str(db.get("PORT", "5432")),
                "-U", db.get("USER", ""), "-Fc", "-f", str(backup_file), db.get("NAME", ""),
            ]
            r = subprocess.run(dump_args, capture_output=True, text=True, timeout=300, env=env)
            dump_ok = r.returncode == 0 and backup_file.exists()
            steps.append({"step": "pg_dump", "passed": dump_ok, "backup_path": str(backup_file),
                          "returncode": r.returncode, "stderr": r.stderr.strip() if not dump_ok else ""})
            if not dump_ok:
                failed = True
                fail_step = "pg_dump"
                fail_msg = r.stderr.strip()

        if not failed:
            raw = backup_file.read_bytes()
            backup_sha256 = hashlib.sha256(raw).hexdigest()
            backup_size = len(raw)
            steps.append({"step": "sha256", "passed": True, "sha256": backup_sha256, "size_bytes": backup_size})

            pg_restore_path = tool["tool_path"].replace("pg_dump", "pg_restore")
            r = subprocess.run([pg_restore_path, "--list", str(backup_file)],
                               capture_output=True, text=True, timeout=60)
            restore_ok = r.returncode == 0
            restore_entries = len(r.stdout.strip().splitlines()) if restore_ok else 0
            steps.append({"step": "pg_restore_list", "passed": restore_ok,
                          "entry_count": restore_entries, "stderr": r.stderr.strip() if not restore_ok else ""})
            if not restore_ok:
                failed = True
                fail_step = "pg_restore_list"
                fail_msg = r.stderr.strip()
    except Exception:
        exception_occurred = True
        raise
    finally:
        # F1/F2: Single recovery scope - restore ONLY services we stopped that were originally Running
        if failed or exception_occurred:
            for svc_name in reversed(callers_stopped_services):
                try:
                    r = subprocess.run(
                        ["powershell", "-Command",
                         f"Start-Service -Name '{svc_name}' -ErrorAction SilentlyContinue; "
                         f"(Get-Service -Name '{svc_name}').Status"],
                        capture_output=True, text=True, timeout=60,
                    )
                    running = "Running" in r.stdout
                    steps.append({"step": f"recovery_start_{svc_name}", "passed": running})
                except Exception:
                    steps.append({"step": f"recovery_start_{svc_name}", "passed": False})
        # On success, do NOT restart in finally — caller starts services after enqueue
        # This ensures worker stays stopped during A/B creation (F2)

    if failed:
        if callers_stopped_services:
            web_s = _check_service_status(web_service_name)
            worker_s = _check_service_status(worker_service_name)
            steps.append({"step": "recovery_health", "passed": web_s["running"] and worker_s["running"],
                          "web_running": web_s["running"], "worker_running": worker_s["running"]})
        return {
            "passed": False,
            "step": fail_step,
            "error": fail_msg,
            "backup_sha256": backup_sha256,
            "backup_size_bytes": backup_size,
            "restore_entry_count": restore_entries,
            "steps": steps,
        }

    # On success, services remain stopped — caller enqueues A/B then starts them
    steps.append({"step": "backup_complete_services_stopped", "passed": True,
                  "stopped_services": callers_stopped_services})

    return {
        "passed": True,
        "backup_path": str(backup_file),
        "backup_sha256": backup_sha256,
        "backup_size_bytes": backup_size,
        "restore_entry_count": restore_entries,
        "stopped_services": callers_stopped_services,
        "original_states": original_states,
        "steps": steps,
    }


def _check_worker_process_tree_unique(worker_service_name):
    db_port = connection.settings_dict.get("PORT", "5432")
    ports = _worker_child_client_ports_recursive(worker_service_name, db_port=db_port)
    if not ports:
        return {"passed": False, "child_count": 0, "unique": False}
    unique = len(ports) == 1
    return {
        "passed": unique,
        "child_count": len(ports),
        "unique": unique,
    }


def _collect_system_metrics():
    import psutil
    metrics = {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        metrics["db_connections"] = cursor.fetchone()[0]
        cursor.execute("""
            SELECT count(*) FROM pg_locks
            WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND NOT granted
        """)
        metrics["waiting_locks"] = cursor.fetchone()[0]
        cursor.execute("""
            SELECT count(*) FROM pg_locks
            WHERE database = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND granted
        """)
        metrics["granted_locks"] = cursor.fetchone()[0]
    try:
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        metrics["memory_percent"] = round(mem.percent, 1)
    except Exception:
        pass
    all_db_fields = all(k in metrics for k in ("db_connections", "waiting_locks", "granted_locks"))
    has_cpu = metrics.get("cpu_percent") is not None
    has_mem = metrics.get("memory_percent") is not None
    metrics["passed"] = all_db_fields and has_cpu and has_mem
    return metrics


def _inspection_file_distribution():
    from quality.models import InspectionFile
    rows = InspectionFile.objects.values("master_id", "priority").order_by("master_id")
    counts_by_priority = {}
    total = 0
    for row in rows:
        prio = row["priority"]
        counts_by_priority[prio] = counts_by_priority.get(prio, 0) + 1
        total += 1
    return {"total": total, "by_priority": counts_by_priority}


def _inspection_file_pathset_hash():
    from quality.models import InspectionFile
    paths = sorted(InspectionFile.objects.values_list("file_path", flat=True))
    raw = json.dumps(paths, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


PRIVACY_ALLOWLIST = {
    "fixture_version", "schema_version", "measurement_date",
    "run_mode", "clock_sources", "poll_interval_seconds",
    "measurement_method", "preflight", "postflight",
    "job_a", "job_b", "job_a_transaction", "job_b_transaction",
    "total_queue_wait_seconds", "handoff_gap_seconds",
    "execution_seconds", "duration_lower_bound_seconds",
    "duration_upper_bound_seconds", "max_measurement_error_seconds",
    "attempt_count", "status", "created_at", "started_at",
    "finished_at", "xact_start", "end_lower_bound", "end_upper_bound",
    "poll_count", "backend_hash", "correlation_method",
    "correlation_candidate_count", "correlation_unique",
    "measurement_status", "failure_reason",
    "master_count", "master_class_count", "structure_count",
    "inspection_file_count", "all_accessible",
    "master_hash", "master_class_hash", "structure_hash",
    "inspection_file_hash", "worker_service_name",
    "web_service_name", "evidence_output_dir",
    "db_connections", "waiting_locks", "granted_locks",
    "cpu_percent", "memory_percent",
    "passed", "available", "found", "running", "automatic",
    "status_code", "found", "configured_count", "accessible_count",
    "migration_0029_applied", "app_env",
    "privacy_check_passed", "handoff_gap_seconds",
    "total", "by_priority", "pathset_hash",
    "path_hash", "details", "entry_count", "accessible",
    "status", "start_type", "output",
    "backup_output_dir", "backup_output_writable",
    "parent_dir_exists", "tool_available", "tool_path",
    # live verification gates
    "live_verification", "job_a_succeeded", "job_b_succeeded",
    "attempt_count_a", "attempt_count_b",
    "observer_a_completed", "observer_b_completed",
    "postflight_pass", "metrics_ok",
    "metrics_thread_alive",
    # baseline / postflight table snapshots
    "baseline_counts", "baseline_hashes",
    "postflight_counts", "postflight_hashes",
    # system metrics summary
    "sample_count", "has_data", "interval_seconds",
    "first_sample", "last_sample",
    "cpu_percent_max", "memory_percent_max",
    "db_connections_max", "waiting_locks_max",
    "samples",
    # sample fields
    "timestamp", "db_connections", "waiting_locks", "granted_locks",
    "cpu_percent", "memory_percent",
    # preflight / postflight top-level keys
    "unc_paths", "system_metrics",
    # canonical payload verification fields
    "csv_exists", "csv_hash", "csv_row_count",
    "folder_paths_count", "priorities_count", "issues",
    # error detail
    "error",
    # clock source descriptions
    "job_timestamps", "transaction_xact_start", "transaction_bounds",
    # env_identity result fields
    "runtime_app_env", "env_file_app_env",
    "runtime_env_mismatch", "env_file_env_mismatch",
    "db_name_matched", "db_host_matched", "db_user_matched",
    # job counts
    "count",
    # backup tool
    "version",
    # worker process tree
    "child_count", "unique",
    # canonical input
    "csv_configured",
    # backup evidence (F4: reviewer finding #4)
    "backup",
    "backup_sha256",
    "backup_size_bytes",
    "restore_entry_count",
    # cleanup/recovery tracking
    "cleanup_failures",
    "recovery_results",
    "service",
    "name",
    "target_state",
    "success",
    "details",
    "error",
    # preflight check names
    "env_identity", "django_check", "migrations", "migration_0029",
    "web_service", "worker_service", "http_check", "active_jobs",
    "running_jobs", "backup_tool", "backup_preparedness",
    "worker_process_tree", "table_counts", "table_hashes",
    "inspection_file_distribution", "inspection_file_pathset_hash",
    "canonical_input", "canonical_payload",
    # sanitized hash fields (from _sanitize_preflight_for_evidence)
    "tool_path_hash",
    "backup_output_dir_hash",
    "csv_path_hash",
# cleanup/recovery tracking
    "cleanup_failures",
    "recovery_results",
    "service",
    "name",
    "target_state",
    "success",
    "details",
    "error",
    "note",
    # minimum evidence enrichment fields
    "enrichment_errors",
    "job_a_verification",
    "job_b_verification",
    "observer_a",
    "observer_b",
    "transaction_completed",
    "observation_ok",
    "live_verification",
    "recovery_ok",
    "job_a_succeeded",
    "job_b_succeeded",
    "attempt_count_a",
    "attempt_count_b",
    "observer_a_completed",
    "observer_b_completed",
    "postflight_pass",
    "metrics_ok",
    "metrics_thread_alive",
    "metrics_coverage_ok",
    # job verification nested fields
    "succeeded",
    "single_attempt",
    "has_result",
    "updated_master_count",
    "updated_class_count",
    "updated_structure_count",
    "inspection_file_count",
    "transaction_strategy",
    "folder_warnings",
    "status",
    "job_hash",
    "job_type",
    "baseline_matched",
    "service_status",
}

PRIVACY_PASSTHROUGH_CONTAINERS = {"preflight", "postflight"}

# Containers with dynamic keys that are allowed if they match a pattern
# Full schema path: allowed_key_pattern (regex) or True for any key
PRIVACY_DYNAMIC_CONTAINERS = {
    "preflight.inspection_file_distribution.by_priority": r"^\d+$",
    "postflight.inspection_file_distribution.by_priority": r"^\d+$",
    "preflight.unc_paths.details": None,
    "postflight.unc_paths.details": None,
    "recovery_results": None,  # recovery result entries
}

PRIVACY_DENYLIST = {
    "pid", "client_port", "application_name", "usename", "datname",
    "worker_id", "execution_token", "job_id", "depends_on_id",
    "request_payload", "error_message", "blocked_reason",
    "idempotency_key", "resource_key",
    "path", "raw_path",
    "csv_path", "inspection_folder_paths", "inspection_folder_priorities",
    "server_db_name", "server_addr", "server_port", "server_user",
}


import re

_PRIVACY_PATH_PATTERN = re.compile(
    r'(?:^|[^\w/\\])(?:(?:[a-zA-Z]:[\\/])|(?:\\\\[^\\]+\\[^\\])|(?:/[a-zA-Z]/)|(?:/[a-z]+/))',
    re.UNICODE,
)


def _string_contains_raw_path(value):
    if not isinstance(value, str):
        return False
    return bool(_PRIVACY_PATH_PATTERN.search(value))


def _privacy_filter(evidence):
    issues = []
    def _scan(obj, path="", passthrough_level=0, parent_allowlisted=False):
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{path}.{k}" if path else k
                # Check denylist FIRST - always check regardless of parent
                if k in PRIVACY_DENYLIST:
                    if v is not None and v != "" and v != 0:
                        issues.append({"field": full_key, "reason": "denylist_key"})
                    new_level = max(passthrough_level - 1, 0)
                    _scan(v, full_key, passthrough_level=new_level, parent_allowlisted=False)
                    continue
                # Check if key is allowlisted
                key_allowlisted = k in PRIVACY_ALLOWLIST
                # Check if parent container allows dynamic keys (match by full schema path)
                is_dynamic_container = path in PRIVACY_DYNAMIC_CONTAINERS
                dynamic_key_ok = False
                if is_dynamic_container:
                    pattern = PRIVACY_DYNAMIC_CONTAINERS[path]
                    if pattern is None:
                        dynamic_key_ok = True
                    elif isinstance(k, str):
                        import re
                        if re.match(pattern, k):
                            dynamic_key_ok = True
                    else:
                        dynamic_key_ok = True
                if key_allowlisted or dynamic_key_ok:
                    # Check ALL string values for raw paths
                    if isinstance(v, str) and _string_contains_raw_path(v):
                        if k in ("output", "error", "failure_reason"):
                            issues.append({"field": full_key, "reason": f"{k}_contains_raw_path"})
                        elif k == "issues":
                            issues.append({"field": full_key, "reason": "issues_contains_raw_path"})
                        else:
                            issues.append({"field": full_key, "reason": "contains_raw_path"})
                    new_level = 1 if k in PRIVACY_PASSTHROUGH_CONTAINERS else max(passthrough_level - 1, 0)
                    _scan(v, full_key, passthrough_level=new_level, parent_allowlisted=False)
                elif passthrough_level > 0:
                    _scan(v, full_key, passthrough_level=passthrough_level - 1, parent_allowlisted=False)
                else:
                    issues.append({"field": full_key, "reason": "unknown_key"})
                    _scan(v, full_key, parent_allowlisted=False)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, str) and _string_contains_raw_path(v):
                    key_name = path.rpartition(".")[2].partition("[")[0]
                    if key_name == "issues":
                        issues.append({"field": f"{path}[{i}]", "reason": "issues_contains_raw_path"})
                    else:
                        issues.append({"field": f"{path}[{i}]", "reason": "contains_raw_path"})
                _scan(v, f"{path}[{i}]", passthrough_level=passthrough_level, parent_allowlisted=False)
        elif isinstance(obj, str):
            if _string_contains_raw_path(obj):
                issues.append({"field": path, "reason": "contains_raw_path"})
    _scan(evidence)
    return issues


def _privacy_check_passed(evidence):
    issues = _privacy_filter(evidence)
    return len(issues) == 0, issues


def _privacy_safe_str(text, replacement="[REDACTED]"):
    """Redact sensitive information from strings.
    Redacts: denylist keys, Windows paths, UNC paths, POSIX paths,
    and numeric (pid, port) tuples.
    """
    result = text
    # Redact denylist keys
    denylist_lower = {k.lower() for k in PRIVACY_DENYLIST}
    for key in denylist_lower:
        result = result.replace(key, replacement)
    # Redact Windows paths (C:\..., D:\...)
    result = re.sub(r'[A-Za-z]:\\[^\s]*', replacement, result)
    # Redact UNC paths (\\server\share\...)
    # Match \\server\share\folder\... (at least server\share)
    result = re.sub(r'\\\\[^\\\s]+(\\[^\\\s]+)+', replacement, result)
    # Redact POSIX paths (/path/...)
    result = re.sub(r'/[^\s]+', replacement, result)
    # Redact numeric (pid, port) tuples
    result = re.sub(r'\(\d+,\s*\d+\)', replacement, result)
    return result


def _validate_canonical_evidence_semantics(evidence, *, require_final=False):
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be a dict")

    run_mode = evidence.get("run_mode")
    if run_mode not in ("dry_run", "live"):
        raise ValueError(
            "run_mode must be 'dry_run' or 'live'; "
            f"received type {type(run_mode).__name__}"
        )

    measurement_status = evidence.get("measurement_status")
    allowed_statuses = {"not_executed"} if run_mode == "dry_run" else {"completed", "failed"}
    if measurement_status not in allowed_statuses:
        raise ValueError(
            "measurement_status is not allowed for the declared run_mode; "
            f"received type {type(measurement_status).__name__}"
        )

    failure_reason = evidence.get("failure_reason")
    if failure_reason is not None and not isinstance(failure_reason, str):
        raise ValueError("failure_reason must be a string when present")

    if run_mode == "dry_run":
        if measurement_status in ("completed", "failed"):
            raise ValueError("dry_run must not have measurement_status=completed or failed")
        if failure_reason not in ("", "preflight_failed"):
            raise ValueError(
                "dry_run failure_reason must be '' or 'preflight_failed'; "
                f"received type {type(failure_reason).__name__}"
            )
        return True

    if run_mode == "live":
        if measurement_status == "completed":
            if failure_reason:
                raise ValueError("completed evidence must have empty failure_reason")
        elif measurement_status == "failed":
            if not failure_reason:
                raise ValueError("failed evidence must have non-empty failure_reason")

    if require_final and run_mode == "live":
        if measurement_status != "completed":
            raise ValueError("final live evidence must have measurement_status='completed'")
        if "failure_reason" not in evidence or failure_reason != "":
            raise ValueError("final live evidence must have failure_reason=''")

        live_verification = evidence.get("live_verification")
        if not isinstance(live_verification, dict):
            raise ValueError("final live evidence requires live_verification as dict")

        required_bool_fields = [
            "job_a_succeeded", "job_b_succeeded",
            "observer_a_completed", "observer_b_completed",
            "postflight_pass", "metrics_ok", "metrics_thread_alive",
        ]
        for field in required_bool_fields:
            val = live_verification.get(field)
            if type(val) is not bool:
                raise ValueError(
                    f"final live evidence: live_verification.{field} must be bool, "
                    f"received type {type(val).__name__}"
                )
            if val is not True:
                raise ValueError(
                    f"final live evidence: live_verification.{field} must be True"
                )

        for field in ("metrics_coverage_ok", "recovery_ok", "transaction_completed", "observation_ok"):
            val = evidence.get(field)
            if type(val) is not bool or val is not True:
                raise ValueError(
                    f"final live evidence: {field} must be True; "
                    f"received type {type(val).__name__}"
                )

        cleanup = evidence.get("cleanup_failures")
        if not isinstance(cleanup, list) or cleanup:
            raise ValueError(
                f"final live evidence: cleanup_failures must be empty list, "
                f"received type {type(cleanup).__name__}"
            )

    return True


def _build_minimum_evidence(
    job_a=None, job_b=None,
    measurement_status=None,
    failure_reason="",
    backup_evidence=None,
):
    """Build minimum privacy-safe evidence payload that always succeeds.
    Contains only essential fields: status, failure_reason, backup, minimal job identifiers (hashed).
    """
    evidence = {
        "fixture_version": CANONICAL_SCHEMA_VERSION,
        "measurement_date": timezone.now().isoformat(),
        "run_mode": "live",
        "measurement_status": measurement_status or "completed",
        "failure_reason": _privacy_safe_str(failure_reason or ""),
    }
    if job_a:
        evidence["job_a"] = {"job_hash": _sha256(job_a.job_id), "status": job_a.status}
    if job_b:
        evidence["job_b"] = {"job_hash": _sha256(job_b.job_id), "status": job_b.status}
    if backup_evidence:
        evidence["backup"] = {
            "backup_sha256": backup_evidence.get("backup_sha256", ""),
            "backup_size_bytes": backup_evidence.get("backup_size_bytes", 0),
            "restore_entry_count": backup_evidence.get("restore_entry_count", 0),
            "passed": backup_evidence.get("passed", False),
        }
    _validate_canonical_evidence_semantics(evidence, require_final=False)
    return evidence


def build_canonical_evidence(
    job_a=None, job_b=None,
    observer_a=None, observer_b=None,
    preflight=None, postflight=None,
    poll_seconds=2.0,
    run_mode="dry_run",
    measurement_date=None,
    baseline_counts=None,
    baseline_hashes=None,
    postflight_counts=None,
    postflight_hashes=None,
    correlation_info=None,
    system_metrics=None,
    measurement_status=None,
    failure_reason="",
    backup_evidence=None,
):
    evidence = {
        "fixture_version": CANONICAL_SCHEMA_VERSION,
        "measurement_date": (measurement_date or timezone.now()).isoformat(),
        "run_mode": run_mode,
        "clock_sources": {
            "job_timestamps": "Django timezone.now() (Python process clock, UTC)",
            "transaction_xact_start": "pg_stat_activity.xact_start (PostgreSQL server clock, UTC)",
            "transaction_bounds": "PostgreSQL clock_timestamp() bracketed before/after snapshot (PostgreSQL server clock, UTC)",
        },
        "poll_interval_seconds": poll_seconds,
        "measurement_method": "external_worker_master_update",
    }
    if run_mode == "dry_run":
        evidence["preflight"] = _sanitize_preflight_for_evidence(preflight) if preflight else {}
        evidence["measurement_status"] = "not_executed"
        evidence["failure_reason"] = "" if _all_preflight_pass(preflight) else "preflight_failed"
        _validate_canonical_evidence_semantics(evidence, require_final=False)
        return evidence

    if job_a:
        evidence["job_a"] = _canonical_job_section(job_a)
    if job_b:
        evidence["job_b"] = _canonical_job_section(job_b)
    if job_a and job_b and job_a.finished_at and job_b.started_at:
        evidence["handoff_gap_seconds"] = round(
            (job_b.started_at - job_a.finished_at).total_seconds(), 6
        )
    for label, obs in [("job_a_transaction", observer_a), ("job_b_transaction", observer_b)]:
        if obs and obs.transaction_completed:
            evidence[label] = _canonical_transaction_section(obs)
    if correlation_info:
        evidence["backend_correlation"] = correlation_info
    if preflight:
        # F4: Sanitize preflight to remove raw paths
        evidence["preflight"] = _sanitize_preflight_for_evidence(preflight)
    if postflight:
        evidence["postflight"] = postflight
    if baseline_counts:
        evidence["baseline_counts"] = baseline_counts
    if baseline_hashes:
        evidence["baseline_hashes"] = baseline_hashes
    if postflight_counts:
        evidence["postflight_counts"] = postflight_counts
    if postflight_hashes:
        evidence["postflight_hashes"] = postflight_hashes
    if system_metrics:
        evidence["system_metrics"] = system_metrics
    if backup_evidence:
        safe_backup = {
            "backup_sha256": backup_evidence.get("backup_sha256", ""),
            "backup_size_bytes": backup_evidence.get("backup_size_bytes", 0),
            "restore_entry_count": backup_evidence.get("restore_entry_count", 0),
            "passed": backup_evidence.get("passed", False),
        }
        evidence["backup"] = safe_backup
    evidence["measurement_status"] = measurement_status or "completed"
    if failure_reason:
        evidence["failure_reason"] = failure_reason
    _validate_canonical_evidence_semantics(evidence, require_final=False)
    return evidence


def _canonical_job_section(job):
    section = {
        "job_type": job.job_type,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
    }
    created = getattr(job, "created_at", None)
    section["created_at"] = _iso(created)
    if created and job.started_at:
        section["total_queue_wait_seconds"] = round(
            (job.started_at - created).total_seconds(), 6
        )
    if job.started_at and job.finished_at:
        section["execution_seconds"] = round(
            (job.finished_at - job.started_at).total_seconds(), 6
        )
    return section


def _canonical_transaction_section(obs):
    if obs.end_lower_bound and obs.end_upper_bound and obs.end_lower_bound > obs.end_upper_bound:
        raise RuntimeError(
            f"END bounds inverted: lower={obs.end_lower_bound} > upper={obs.end_upper_bound}"
        )
    if obs.xact_start is not None and obs.end_upper_bound is not None and obs.end_upper_bound < obs.xact_start:
        raise RuntimeError(
            f"end_upper={obs.end_upper_bound} is before xact_start={obs.xact_start}"
        )
    txn = {
        "backend_hash": obs.backend_hash,
        "xact_start": _iso(obs.xact_start),
        "end_lower_bound": _iso(obs.end_lower_bound),
        "end_upper_bound": _iso(obs.end_upper_bound),
        "poll_count": obs.poll_count,
        "correlation_method": obs.correlation_method,
        "correlation_candidate_count": obs.correlation_candidate_count,
        "correlation_unique": obs.correlation_unique,
    }
    if obs.xact_start and obs.end_lower_bound:
        duration_lower = (obs.end_lower_bound - obs.xact_start).total_seconds()
        txn["duration_lower_bound_seconds"] = round(max(0, duration_lower), 6)
    if obs.xact_start and obs.end_upper_bound:
        txn["duration_upper_bound_seconds"] = round(
            (obs.end_upper_bound - obs.xact_start).total_seconds(), 6
        )
    if obs.end_lower_bound and obs.end_upper_bound:
        txn["max_measurement_error_seconds"] = round(
            (obs.end_upper_bound - obs.end_lower_bound).total_seconds(), 6
        )
    return txn





def _preflight_key_passed(key, value):
    """Check if a single preflight key passes validation.
    Returns True if the key passes, False otherwise.
    """
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
    # Per-key schema validation for informational keys
    schema_passed = False
    if key == "table_counts":
        required = {"master_count", "master_class_count", "structure_count", "inspection_file_count"}
        if all(k in value for k in required):
            if all(type(value[k]) is int and value[k] >= 0 for k in required):
                schema_passed = True
    elif key == "table_hashes":
        required = {"master_hash", "master_class_hash", "structure_hash", "inspection_file_hash"}
        if all(k in value for k in required):
            if all(isinstance(value[k], str) and len(value[k]) == 64 and all(c in "0123456789abcdef" for c in value[k]) for k in required):
                schema_passed = True
    elif key == "inspection_file_distribution":
        if all(k in value for k in ("total", "by_priority")):
            total = value["total"]
            if type(total) is int and total >= 0:
                bp = value["by_priority"]
                if isinstance(bp, dict):
                    if (all(type(k) is int for k in bp) and
                        all(type(v) is int and v >= 0 for v in bp.values()) and
                        total == sum(bp.values())):
                        schema_passed = True
    elif key == "inspection_file_pathset_hash":
        if isinstance(value.get("pathset_hash"), str) and len(value["pathset_hash"]) == 64 and all(c in "0123456789abcdef" for c in value["pathset_hash"]):
            schema_passed = True
    elif key == "system_metrics":
        required = {"db_connections", "waiting_locks", "granted_locks", "cpu_percent", "memory_percent", "passed"}
        if all(k in value for k in required):
            if value.get("passed") is True:
                dc = value["db_connections"]
                wl = value["waiting_locks"]
                gl = value["granted_locks"]
                cp = value["cpu_percent"]
                mp = value["memory_percent"]
                if (type(dc) is int and dc >= 0 and
                    type(wl) is int and wl >= 0 and
                    type(gl) is int and gl >= 0 and
                    isinstance(cp, (int, float)) and type(cp) is not bool and cp >= 0 and math.isfinite(cp) and
                    isinstance(mp, (int, float)) and type(mp) is not bool and mp >= 0 and math.isfinite(mp)):
                    schema_passed = True
    # Known schema keys: return schema result directly, no fallback to generic positive
    known_schema_keys = {"table_counts", "table_hashes", "inspection_file_distribution", "inspection_file_pathset_hash", "system_metrics"}
    if key in known_schema_keys:
        return schema_passed
    # Fail-closed on empty dicts or missing positive indicator
    if not value:
        return False
    has_positive = False
    for v in value.values():
        if v is True:
            has_positive = True
            break
    if not has_positive and "status" not in value:
        return False
    return True


def _all_preflight_pass(preflight):
    """Fail-closed: return True only when all preflight checks have positive pass results."""
    if not preflight:
        return False
    for key, value in preflight.items():
        if not _preflight_key_passed(key, value):
            return False
    return True


def run_preflight(env_path=None, web_service_name="QualityControlHQ-Pseudoprod",
                  worker_service_name="QualityControlHQ-Worker-Pseudoprod",
                  unc_paths=None, output_dir=None):
    results = {}
    results["env_identity"] = _get_env_identity(env_path)
    results["django_check"] = _check_django()
    results["migrations"] = _check_migrations()
    results["migration_0029"] = _check_migration_0029_applied()
    results["web_service"] = _check_service_status(web_service_name)
    results["worker_service"] = _check_service_status(worker_service_name)
    results["http_check"] = _check_http()
    results["active_jobs"] = {"passed": _active_job_count() == 0, "count": _active_job_count()}
    results["running_jobs"] = {"passed": _running_job_count() == 0, "count": _running_job_count()}
    results["backup_tool"] = _check_backup_tool()
    if output_dir:
        results["backup_preparedness"] = _check_backup_preparedness(output_dir)
    results["worker_process_tree"] = _check_worker_process_tree_unique(worker_service_name)
    results["table_counts"] = _table_counts()
    results["table_hashes"] = _table_stable_hashes()
    results["system_metrics"] = _collect_system_metrics()
    results["inspection_file_distribution"] = _inspection_file_distribution()
    results["inspection_file_pathset_hash"] = {"pathset_hash": _inspection_file_pathset_hash()}
    if unc_paths:
        results["unc_paths"] = _check_unc_paths(unc_paths)
    else:
        results["unc_paths"] = {"passed": False, "configured_count": 0, "accessible_count": 0, "all_accessible": False, "details": [], "status": "not_provided"}
    results["canonical_input"] = _check_canonical_input()
    return results


def _check_canonical_input():
    from quality.models import AppSetting
    try:
        app_setting = AppSetting.objects.first()
        if not app_setting:
            return {"passed": False, "status": "no_app_setting"}
        csv_path = app_setting.csv_path or ""
        folder_paths = app_setting.inspection_folder_paths or []
        priorities = app_setting.inspection_folder_priorities or {}
        issues = []
        if not csv_path:
            issues.append("csv_path is empty")
        if not folder_paths:
            issues.append("inspection_folder_paths is empty")
        if not priorities:
            issues.append("inspection_folder_priorities is empty")
        return {
            "passed": len(issues) == 0,
            "csv_configured": bool(csv_path),
            "folder_paths_count": len(folder_paths),
            "priorities_count": len(priorities),
            "status": "configured" if not issues else "incomplete",
            "issues": issues,
        }
    except Exception as e:
        return {"passed": False, "status": "error", "error": str(e)}


def run_postflight(baseline_counts=None, baseline_hashes=None,
                    preflight_unc_paths=None, preflight_unc_details=None,
                    web_service_name="QualityControlHQ-Pseudoprod",
                    worker_service_name="QualityControlHQ-Worker-Pseudoprod",
                    unc_paths=None,
                    inspection_baseline_dist=None, inspection_baseline_hash=None):
    results = {}
    postflight_counts = _table_counts()
    postflight_hashes = _table_stable_hashes()
    counts_match = True
    hashes_match = True
    if baseline_counts:
        for k, v in baseline_counts.items():
            if postflight_counts.get(k) != v:
                counts_match = False
                break
    if baseline_hashes:
        for k, v in baseline_hashes.items():
            if postflight_hashes.get(k) != v:
                hashes_match = False
                break
    results["table_counts"] = {**postflight_counts, "passed": counts_match, "baseline_matched": counts_match}
    results["table_hashes"] = {**postflight_hashes, "passed": hashes_match, "baseline_matched": hashes_match}
    results["web_service"] = _check_service_status(web_service_name)
    results["worker_service"] = _check_service_status(worker_service_name)
    results["http_check"] = _check_http()
    if unc_paths:
        results["unc_paths"] = _check_unc_paths(unc_paths)
    else:
        results["unc_paths"] = {"passed": False, "status": "not_provided", "configured_count": 0, "accessible_count": 0, "all_accessible": False, "details": []}
    inspection_post_dist = _inspection_file_distribution()
    inspection_post_hash = _inspection_file_pathset_hash()
    insp_dist_matched = True
    insp_hash_matched = True
    if inspection_baseline_dist:
        insp_dist_matched = inspection_post_dist.get("total") == inspection_baseline_dist.get("total")
    if inspection_baseline_hash:
        insp_hash_matched = inspection_post_hash == inspection_baseline_hash
    results["inspection_file_distribution"] = {**inspection_post_dist, "passed": insp_dist_matched, "baseline_matched": insp_dist_matched}
    results["inspection_file_pathset_hash"] = {"pathset_hash": inspection_post_hash, "passed": insp_hash_matched, "baseline_matched": insp_hash_matched}
    if baseline_counts:
        for k, v in baseline_counts.items():
            match_key = f"{k}_baseline_matched"
            results["table_counts"][match_key] = postflight_counts.get(k) == v
    results["active_jobs"] = {"passed": _active_job_count() == 0, "count": _active_job_count()}
    results["running_jobs"] = {"passed": _running_job_count() == 0, "count": _running_job_count()}
    results["system_metrics"] = _collect_system_metrics()
    return results


def _check_canonical_baseline_configured():
    """Fail-closed: return True only if baseline constants are approved and populated."""
    if not CANONICAL_BASELINE_APPROVED:
        return False, "CANONICAL_BASELINE_APPROVED is False; real approved values required before --live"
    if not CANONICAL_BASELINE_KNOWN_HASH:
        return False, "CANONICAL_BASELINE_KNOWN_HASH is empty"
    if len(CANONICAL_BASELINE_KNOWN_HASH) != 64:
        return False, "CANONICAL_BASELINE_KNOWN_HASH must be 64-char hex"
    if CANONICAL_BASELINE_EXPECTED_ROW_COUNT < 0:
        return False, "CANONICAL_BASELINE_EXPECTED_ROW_COUNT is not set"
    if not CANONICAL_BASELINE_UNC_7ROOT:
        return False, "CANONICAL_BASELINE_UNC_7ROOT is empty"
    if len(CANONICAL_BASELINE_UNC_7ROOT) != 7:
        return False, "CANONICAL_BASELINE_UNC_7ROOT must have exactly 7 roots"
    if CANONICAL_BASELINE_EXPECTED_MASTER_COUNT < 0:
        return False, "CANONICAL_BASELINE_EXPECTED_MASTER_COUNT is not set"
    if CANONICAL_BASELINE_EXPECTED_CLASS_COUNT < 0:
        return False, "CANONICAL_BASELINE_EXPECTED_CLASS_COUNT is not set"
    if CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT < 0:
        return False, "CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT is not set"
    return True, ""


def _sanitize_preflight_for_evidence(preflight):
    """Convert raw paths in preflight to hashes/booleans for privacy compliance."""
    if not isinstance(preflight, dict):
        return preflight
    
    sanitized = {}
    for key, value in preflight.items():
        if isinstance(value, dict):
            if key == "backup_tool":
                sanitized[key] = {
                    "passed": value.get("passed"),
                    "available": value.get("available"),
                    "version": value.get("version"),
                    "tool_path_hash": _sha256(value.get("tool_path", "")) if value.get("tool_path") else "",
                }
            elif key == "backup_preparedness":
                sanitized[key] = {
                    "passed": value.get("passed"),
                    "tool_available": value.get("tool_available"),
                    "tool_path_hash": _sha256(value.get("tool_path", "")) if value.get("tool_path") else "",
                    "backup_output_dir_hash": _sha256(value.get("backup_output_dir", "")) if value.get("backup_output_dir") else "",
                    "backup_output_writable": value.get("backup_output_writable"),
                    "parent_dir_exists": value.get("parent_dir_exists"),
                }
            elif key == "unc_paths":
                details = value.get("details", [])
                sanitized[key] = {
                    "passed": value.get("passed"),
                    "configured_count": value.get("configured_count"),
                    "accessible_count": value.get("accessible_count"),
                    "all_accessible": value.get("all_accessible"),
                    "details": [{"path_hash": d.get("path_hash"), "accessible": d.get("accessible"), "entry_count": d.get("entry_count")} for d in details],
                }
            else:
                sanitized[key] = _sanitize_dict_recursive(value)
        elif isinstance(value, list):
            sanitized[key] = [_sanitize_preflight_for_evidence(v) if isinstance(v, dict) else v for v in value]
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_dict_recursive(value):
    """Recursively sanitize nested dicts to replace raw path fields with hashes."""
    result = {}
    for k, v in value.items():
        if k in ("tool_path", "backup_output_dir", "csv_path") and isinstance(v, str) and v:
            result[k + "_hash"] = _sha256(v) if v else ""
            result[k] = True
        elif isinstance(v, dict):
            result[k] = _sanitize_dict_recursive(v)
        elif isinstance(v, list):
            result[k] = [_sanitize_dict_recursive(item) if isinstance(item, dict) else item for item in v]
        else:
            result[k] = v
    return result


def _sanitize_recovery_results(recovery_results):
    """Sanitize recovery results for privacy-safe evidence.
    Converts raw paths, service names, and exception text to safe forms.
    """
    if not isinstance(recovery_results, list):
        return recovery_results
    sanitized = []
    for r in recovery_results:
        if isinstance(r, dict):
            safe = {
                "service": r.get("service"),
                "name": r.get("name"),
                "target_state": r.get("target_state"),
                "success": r.get("success"),
            }
            if r.get("error"):
                # Sanitize error message - remove raw paths
                safe["error"] = _privacy_safe_str(str(r["error"]))
            if r.get("details"):
                # Sanitize details - convert _start_service_with_health_check dict
                details = r["details"]
                if isinstance(details, dict):
                    safe["details"] = {
                        "passed": details.get("passed"),
                        "service_status": details.get("service_status"),
                        "steps": [
                            {"step": s.get("step"), "passed": s.get("passed")}
                            for s in details.get("steps", [])
                        ] if details.get("steps") else None,
                    }
            if r.get("note"):
                safe["note"] = r["note"]
            sanitized.append(safe)
        else:
            sanitized.append(r)
    return sanitized


def _sanitize_cleanup_failures(cleanup_failures):
    """Sanitize cleanup failure messages for privacy."""
    if not isinstance(cleanup_failures, list):
        return cleanup_failures
    return [_privacy_safe_str(str(f)) for f in cleanup_failures]


def _verify_canonical_payload(payload, known_canonical_hash=None, expected_row_count=None, expected_unc_paths=None):
    """Validate resolved canonical payload (CSV path, folder paths, priorities, identity).
    Optionally compare against known canonical baseline values."""
    from pathlib import Path
    import hashlib
    issues = []
    csv_path = payload.get("csv_path", "")
    if not csv_path:
        issues.append("csv_empty")
    csv_hash = ""
    csv_row_count = -1
    if csv_path:
        p = Path(csv_path)
        if not p.is_file():
            issues.append("csv_not_found")
        else:
            raw = p.read_bytes()
            csv_hash = hashlib.sha256(raw).hexdigest()
            csv_row_count = raw.count(b"\n")
            if csv_row_count == 0:
                issues.append("csv_empty_content")
    if known_canonical_hash and csv_hash and csv_hash != known_canonical_hash:
        issues.append("csv_hash_mismatch")
    if expected_row_count is not None and expected_row_count >= 0 and csv_row_count != expected_row_count:
        issues.append("csv_row_count_mismatch")
    folder_paths = payload.get("inspection_folder_paths") or []
    if not folder_paths:
        issues.append("folder_paths_empty")
    else:
        for idx, fp in enumerate(folder_paths):
            if not Path(fp).is_dir():
                issues.append(f"folder_not_found_{idx}")
    if expected_unc_paths is not None:
        expected_set = set(str(p) for p in expected_unc_paths)
        actual_set = set(folder_paths)
        if expected_set and actual_set != expected_set:
            issues.append("folder_paths_unc_mismatch")
    priorities = payload.get("inspection_folder_priorities") or {}
    if priorities:
        uncovered = set(folder_paths) - set(priorities.keys())
        if uncovered:
            issues.append("folder_no_priority")
    from quality.models import AppSetting
    app_setting = AppSetting.objects.first()
    if app_setting:
        if csv_path and app_setting.csv_path and Path(csv_path).resolve() != Path(app_setting.csv_path).resolve():
            issues.append("csv_path_mismatch")
        app_folders = set(str(f) for f in (app_setting.inspection_folder_paths or []))
        payload_folders = set(folder_paths)
        if app_folders and payload_folders and app_folders != payload_folders:
            issues.append("folder_paths_mismatch")
    return {
        "passed": len(issues) == 0,
        "csv_exists": bool(csv_path) and Path(csv_path).is_file(),
        "csv_hash": csv_hash,
        "csv_row_count": csv_row_count,
        "folder_paths_count": len(folder_paths),
        "priorities_count": len(priorities),
        "status": "valid" if not issues else "invalid",
        "issues": issues,
    }


def _verify_job_result(job, label="job", expected_master_count=None, expected_class_count=None, expected_structure_count=None):
    """Check a single job's canonical result for expected outcome."""
    from quality.models import Job as JobModel
    succeeded = job.status == JobModel.Status.SUCCEEDED
    single_attempt = job.attempt_count == 1
    has_result = bool(job.result) if hasattr(job, "result") else False
    result = {
        "status": job.status,
        "attempt_count": job.attempt_count,
        "succeeded": succeeded,
        "single_attempt": single_attempt,
        "has_result": has_result,
        "updated_master_count": -1,
        "updated_class_count": -1,
        "updated_structure_count": -1,
        "inspection_file_count": -1,
        "transaction_strategy": "",
        "folder_warnings": [],
    }
    if has_result and isinstance(job.result, dict):
        result["updated_master_count"] = job.result.get("updated_master_count", -1)
        result["updated_class_count"] = job.result.get("updated_class_count", -1)
        result["updated_structure_count"] = job.result.get("updated_structure_count", -1)
        result["inspection_file_count"] = job.result.get("inspection_file_count", -1)
        result["transaction_strategy"] = job.result.get("transaction_strategy", "")
        result["folder_warnings"] = job.result.get("folder_warnings", [])
    counts_present = all(v >= 0 for v in (
        result["updated_master_count"],
        result["updated_class_count"],
        result["updated_structure_count"],
    ))
    insp_count_ok = result["inspection_file_count"] >= 0
    strategy_ok = result["transaction_strategy"] == "single_atomic_update"
    warnings_ok = len(result["folder_warnings"]) == 0
    expected_ok = True
    if expected_master_count is not None and result["updated_master_count"] != expected_master_count:
        expected_ok = False
    if expected_class_count is not None and result["updated_class_count"] != expected_class_count:
        expected_ok = False
    if expected_structure_count is not None and result["updated_structure_count"] != expected_structure_count:
        expected_ok = False
    result["passed"] = all([succeeded, single_attempt, counts_present, insp_count_ok, strategy_ok, warnings_ok, expected_ok])
    return result


LIVE_BLOCKED = True


def run_canonical(
    job_a=None,
    job_b=None,
    observer_a=None,
    observer_b=None,
    preflight=None,
    postflight=None,
    system_metrics=None,
    baseline_counts=None,
    baseline_hashes=None,
    postflight_counts=None,
    postflight_hashes=None,
    correlation_info=None,
    backup_evidence=None,
    poll_seconds=2.0,
    measurement_date=None,
    evidence_output_dir=None,
    web_service_name="QualityControlHQ-Pseudoprod",
    worker_service_name="QualityControlHQ-Worker-Pseudoprod",
    metrics_thread_alive=True,
    cleanup_failures=None,
    recovery_results=None,
    run_mode="live",
):
    """Third P0: Final gate and formal evidence orchestration.

    Runs all final gate checks in sequence and produces privacy-safe
    formal evidence. Fail-closed: any insufficiency, inconsistency or
    exception is treated as failure (RuntimeError). Success is only
    returned when all gates pass.

    LIVE_BLOCKED = True is maintained throughout; pseudoprod live,
    real Job execution, service operations, and backup/restore are
    out of scope for this function.
    """
    if not LIVE_BLOCKED:
        raise RuntimeError("LIVE_BLOCKED must be True before running canonical evidence")

    if run_mode == "live":
        if job_a is None:
            raise RuntimeError("job_a is required for live final gate")
        if job_b is None:
            raise RuntimeError("job_b is required for live final gate")
        if observer_a is None:
            raise RuntimeError("observer_a is required for live final gate")
        if observer_b is None:
            raise RuntimeError("observer_b is required for live final gate")
        if not evidence_output_dir:
            raise RuntimeError("evidence_output_dir is required for live final gate")

    enrichment_errors = []

    # ── Gate 1: Preflight ──
    if preflight is None:
        raise RuntimeError("preflight is required for final gate")
    # F4: Required preflight keys per planner spec
    required_preflight_keys = {
        "env_identity", "django_check", "migrations", "migration_0029",
        "web_service", "worker_service", "http_check", "active_jobs", "running_jobs",
        "backup_tool", "backup_preparedness", "worker_process_tree",
        "table_counts", "table_hashes", "system_metrics",
        "inspection_file_distribution", "inspection_file_pathset_hash",
        "canonical_input", "canonical_payload", "unc_paths"
    }
    missing_preflight_keys = required_preflight_keys - set(preflight.keys())
    if missing_preflight_keys:
        raise RuntimeError(f"Preflight missing required keys: {missing_preflight_keys}")
    if not _all_preflight_pass(preflight):
        failed_keys = [k for k, v in preflight.items() if not _preflight_key_passed(k, v)]
        raise RuntimeError(f"Preflight gate failed: {failed_keys}")

    # ── Gate 2: Job A/B results (required for live) ──
    job_a_verification = None
    job_b_verification = None
    if job_a is None:
        raise RuntimeError("job_a is required for final gate")
    if job_b is None:
        raise RuntimeError("job_b is required for final gate")
    # F5: Pass expected baseline counts for approved baseline validation
    job_a_verification = _verify_job_result(
        job_a, label="job_a",
        expected_master_count=CANONICAL_BASELINE_EXPECTED_MASTER_COUNT if CANONICAL_BASELINE_EXPECTED_MASTER_COUNT >= 0 else None,
        expected_class_count=CANONICAL_BASELINE_EXPECTED_CLASS_COUNT if CANONICAL_BASELINE_EXPECTED_CLASS_COUNT >= 0 else None,
        expected_structure_count=CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT if CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT >= 0 else None,
    )
    if not job_a_verification.get("passed"):
        raise RuntimeError(f"Job A final gate failed: status={job_a.status}, result={job_a.result}")
    job_b_verification = _verify_job_result(
        job_b, label="job_b",
        expected_master_count=CANONICAL_BASELINE_EXPECTED_MASTER_COUNT if CANONICAL_BASELINE_EXPECTED_MASTER_COUNT >= 0 else None,
        expected_class_count=CANONICAL_BASELINE_EXPECTED_CLASS_COUNT if CANONICAL_BASELINE_EXPECTED_CLASS_COUNT >= 0 else None,
        expected_structure_count=CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT if CANONICAL_BASELINE_EXPECTED_STRUCTURE_COUNT >= 0 else None,
    )
    if not job_b_verification.get("passed"):
        raise RuntimeError(f"Job B final gate failed: status={job_b.status}, result={job_b.result}")

    # ── Gate 3: Observer A/B final state (required for live) ──
    if observer_a is None:
        raise RuntimeError("observer_a is required for final gate")
    if observer_b is None:
        raise RuntimeError("observer_b is required for final gate")
    for label, obs in [("observer_a", observer_a), ("observer_b", observer_b)]:
        if not obs.transaction_completed:
            raise RuntimeError(f"{label} transaction not completed")
        if obs.xact_start is None:
            raise RuntimeError(f"{label} xact_start is None")
        if obs.correlation_unique is not True:
            raise RuntimeError(f"{label} correlation is not unique")
        if not obs.observation_ok:
            raise RuntimeError(f"{label} observation not ok")
        if obs.end_lower_bound is not None and obs.end_upper_bound is not None:
            if obs.end_lower_bound > obs.end_upper_bound:
                raise RuntimeError(f"{label} END bounds inverted")
        if obs.xact_start is not None and obs.end_upper_bound is not None:
            if obs.end_upper_bound < obs.xact_start:
                raise RuntimeError(f"{label} end_upper < xact_start")
        if obs.end_lower_bound is None or obs.end_upper_bound is None:
            raise RuntimeError(f"{label} END bounds not fully observed")
    # A/B transaction identity must be distinct (F3)
    if observer_a.xact_start == observer_b.xact_start:
        raise RuntimeError("observer_a and observer_b share the same transaction (A.xact_start == B.xact_start)")
    # F1: Dependency semantics require A→B ordering ALWAYS, not just non-overlap.
    # The earlier-starting transaction MUST be A (observer_a).
    if observer_a.xact_start >= observer_b.xact_start:
        raise RuntimeError(
            "observer_a.xact_start must be < observer_b.xact_start (A must start before B by dependency)"
        )
    # Normal order: A starts before B, and A must end before B starts
    if observer_a.end_upper_bound is not None and observer_a.end_upper_bound > observer_b.xact_start:
        raise RuntimeError("observer_a end_upper must be <= observer_b xact_start (A must end before B starts)")
    # Verify A end <= B start via Job dependency ordering
    if job_a.finished_at and job_b.started_at and job_a.finished_at > job_b.started_at:
        raise RuntimeError("Job A finished_at must be <= Job B started_at (dependency ordering)")

    # ── F2: Job/Observer time-window correlation ──
    # Each observer's transaction must fall within its job's execution window.
    # Job A -> Observer A, Job B -> Observer B
    for label, job, obs in [("observer_a", job_a, observer_a), ("observer_b", job_b, observer_b)]:
        if job.started_at is not None and obs.xact_start is not None:
            if job.started_at > obs.xact_start:
                raise RuntimeError(f"{label}: xact_start ({obs.xact_start.isoformat()}) is before job started_at ({job.started_at.isoformat()})")
        if job.finished_at is not None and obs.xact_start is not None:
            if obs.xact_start > job.finished_at:
                raise RuntimeError(f"{label}: xact_start ({obs.xact_start.isoformat()}) is after job finished_at ({job.finished_at.isoformat()})")
        # END bounds: finished_at must be within [end_lower_bound, end_upper_bound)
        if job.finished_at is not None and obs.end_upper_bound is not None:
            if job.finished_at > obs.end_upper_bound:
                raise RuntimeError(f"{label}: job finished_at ({job.finished_at.isoformat()}) is after end_upper_bound ({obs.end_upper_bound.isoformat()})")

    # ── Gate 4: Postflight ──
    if postflight is None:
        raise RuntimeError("postflight is required for final gate")
    # F4: Required postflight keys per planner spec
    required_postflight_keys = {
        "table_counts", "table_hashes", "web_service", "worker_service",
        "http_check", "unc_paths", "inspection_file_distribution",
        "inspection_file_pathset_hash", "active_jobs", "running_jobs",
        "system_metrics"
    }
    missing_postflight_keys = required_postflight_keys - set(postflight.keys())
    if missing_postflight_keys:
        raise RuntimeError(f"Postflight missing required keys: {missing_postflight_keys}")
    if not _all_postflight_pass(postflight):
        failed_keys = [k for k, v in postflight.items() if not _postflight_key_passed(k, v)]
        raise RuntimeError(f"Postflight gate failed: {failed_keys}")

    # ── Gate 5: Metrics coverage (summary schema from SystemMetricsMonitor) ──
    if system_metrics is None:
        raise RuntimeError("system_metrics is required for final gate")
    if not system_metrics.get("has_data"):
        enrichment_errors.append("system_metrics has no data")
    sample_count = system_metrics.get("sample_count", 0)
    samples = system_metrics.get("samples") or []
    # F2: sample_count must equal len(samples), min 2 samples
    if sample_count != len(samples):
        enrichment_errors.append(f"sample_count ({sample_count}) != len(samples) ({len(samples)})")
    if sample_count < 2:
        enrichment_errors.append(f"system_metrics sample_count must be >= 2, got {sample_count}")
    # F2: Validate each sample has required fields and parseable timestamp
    first_sample_ts = None
    last_sample_ts = None
    for i, s in enumerate(samples):
        ts = s.get("timestamp")
        if not ts:
            enrichment_errors.append(f"sample[{i}] missing timestamp")
        else:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if first_sample_ts is None:
                    first_sample_ts = dt
                last_sample_ts = dt
            except (ValueError, TypeError):
                enrichment_errors.append(f"sample[{i}] timestamp parse failed: {ts}")
        # Required fields per sample
        for req in ("db_connections", "waiting_locks", "granted_locks"):
            if s.get(req) is None:
                enrichment_errors.append(f"sample[{i}] missing {req}")
    # F2: Check timestamp monotonic and max 5s gap
    if len(samples) >= 2:
        for i in range(1, len(samples)):
            prev_ts = samples[i - 1].get("timestamp")
            curr_ts = samples[i].get("timestamp")
            if prev_ts and curr_ts:
                try:
                    prev_dt = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                    curr_dt = datetime.fromisoformat(curr_ts.replace("Z", "+00:00"))
                    delta = (curr_dt - prev_dt).total_seconds()
                    if delta <= 0:
                        enrichment_errors.append(f"system_metrics timestamp not monotonic at sample[{i}]")
                    if delta > 5.0:
                        enrichment_errors.append(f"system_metrics interval gap {delta:.1f}s exceeds 5s between samples")
                except (ValueError, TypeError):
                    enrichment_errors.append(f"system_metrics timestamp parse failed for gap check at sample[{i}]")
    # F2: Coverage - first sample <= A enqueue/start, last sample >= B completion
    if first_sample_ts and job_a and job_a.created_at:
        if first_sample_ts > job_a.created_at:
            enrichment_errors.append(f"first sample {first_sample_ts.isoformat()} > job_a created_at {job_a.created_at.isoformat()}")
    if last_sample_ts and job_b and job_b.finished_at:
        if last_sample_ts < job_b.finished_at:
            enrichment_errors.append(f"last sample {last_sample_ts.isoformat()} < job_b finished_at {job_b.finished_at.isoformat()}")
    # F3: Require cpu_percent and memory_percent in each sample
    for i, s in enumerate(samples):
        if s.get("cpu_percent") is None:
            enrichment_errors.append(f"sample[{i}] missing cpu_percent")
        if s.get("memory_percent") is None:
            enrichment_errors.append(f"sample[{i}] missing memory_percent")
    for required_max_field in ("cpu_percent_max", "memory_percent_max", "db_connections_max", "waiting_locks_max"):
        if system_metrics.get(required_max_field) is None:
            enrichment_errors.append(f"system_metrics missing {required_max_field}")
    if enrichment_errors:
        raise RuntimeError(f"Metrics coverage insufficient: {enrichment_errors}")

    # ── Gate 6: Cleanup and service recovery (F5) ──
    # Use command-provided results when available; validate them fail-closed.
    # When not provided, perform a fresh re-check (backward compatibility).
    if cleanup_failures is not None and recovery_results is not None:
        if cleanup_failures:
            raise RuntimeError(f"Cleanup failures reported by command: {cleanup_failures}")
        # F2: Validate recovery entries - require web and worker matching backup original_states
        if backup_evidence and backup_evidence.get("original_states"):
            original_states = backup_evidence["original_states"]
            required_services = set(original_states.keys())
        else:
            required_services = {web_service_name, worker_service_name}

        found_services = set()
        for entry in recovery_results:
            if isinstance(entry, dict):
                svc_name = entry.get("name")
                if svc_name in required_services:
                    if svc_name in found_services:
                        raise RuntimeError(f"Duplicate recovery entry for {svc_name}")
                    found_services.add(svc_name)
                    # Validate target_state matches expected
                    expected_state = original_states.get(svc_name, "Running") if backup_evidence and backup_evidence.get("original_states") else "Running"
                    if entry.get("target_state") != expected_state:
                        raise RuntimeError(f"Recovery entry for {svc_name} has target_state={entry.get('target_state')} but expected {expected_state}")
                    if not entry.get("success"):
                        raise RuntimeError(f"Service recovery failed for {svc_name}: target_state={entry.get('target_state')}, success=False")
                else:
                    raise RuntimeError(f"Unknown service in recovery: {svc_name}")

        missing = required_services - found_services
        if missing:
            raise RuntimeError(f"Missing recovery entries for: {missing}")
    else:
        cleanup_failures = []
        recovery_results = []
        for svc_name, label in [(web_service_name, "web"), (worker_service_name, "worker")]:
            status = _check_service_status(svc_name)
            is_running = status == "Running"
            if not is_running:
                cleanup_failures.append(f"{label} service not Running (status={status})")
            recovery_results.append({
                "service": "service",
                "name": svc_name,
                "target_state": "Running",
                "success": is_running,
                "details": {"service_status": status},
            })
        if cleanup_failures:
            raise RuntimeError(f"Service recovery failed: {cleanup_failures}")

    # ── Determine measurement_status and failure_reason (fail-closed) ──
    measurement_status = "completed"
    failure_reason = ""

    if job_a and job_a.status != Job.Status.SUCCEEDED:
        measurement_status = "failed"
        failure_reason = "job_a_not_succeeded"
    if job_b and job_b.status != Job.Status.SUCCEEDED:
        measurement_status = "failed"
        failure_reason = "job_b_not_succeeded"

    for label, obs in [("observer_a", observer_a), ("observer_b", observer_b)]:
        if obs is not None and not obs.transaction_completed:
            measurement_status = "failed"
            failure_reason = f"{label}_not_completed"

    for label, obs in [("observer_a", observer_a), ("observer_b", observer_b)]:
        if obs is not None and hasattr(obs, '_exception') and obs._exception is not None:
            measurement_status = "failed"
            failure_reason = f"{label}_collector_exception"

    # ── Build formal evidence ──
    evidence = build_canonical_evidence(
        job_a=job_a,
        job_b=job_b,
        observer_a=observer_a,
        observer_b=observer_b,
        preflight=preflight,
        postflight=postflight,
        poll_seconds=poll_seconds,
        run_mode="live",
        measurement_date=measurement_date,
        baseline_counts=baseline_counts,
        baseline_hashes=baseline_hashes,
        postflight_counts=postflight_counts,
        postflight_hashes=postflight_hashes,
        correlation_info=correlation_info,
        system_metrics=system_metrics,
        measurement_status=measurement_status,
        failure_reason=failure_reason,
        backup_evidence=backup_evidence,
    )

    # ── Enrichment fields for formal evidence ──
    evidence["job_a_verification"] = job_a_verification if job_a_verification else {}
    evidence["job_b_verification"] = job_b_verification if job_b_verification else {}
    evidence["observer_a"] = {
        "transaction_completed": bool(observer_a and observer_a.transaction_completed),
        "xact_start": _iso(observer_a.xact_start) if observer_a and observer_a.xact_start else None,
        "end_lower_bound": _iso(observer_a.end_lower_bound) if observer_a and observer_a.end_lower_bound else None,
        "end_upper_bound": _iso(observer_a.end_upper_bound) if observer_a and observer_a.end_upper_bound else None,
        "poll_count": observer_a.poll_count if observer_a else 0,
        "observation_ok": bool(observer_a and observer_a.transaction_completed),
    } if observer_a else {}
    evidence["observer_b"] = {
        "transaction_completed": bool(observer_b and observer_b.transaction_completed),
        "xact_start": _iso(observer_b.xact_start) if observer_b and observer_b.xact_start else None,
        "end_lower_bound": _iso(observer_b.end_lower_bound) if observer_b and observer_b.end_lower_bound else None,
        "end_upper_bound": _iso(observer_b.end_upper_bound) if observer_b and observer_b.end_upper_bound else None,
        "poll_count": observer_b.poll_count if observer_b else 0,
        "observation_ok": bool(observer_b and observer_b.transaction_completed),
    } if observer_b else {}
    evidence["transaction_completed"] = bool(
        (observer_a and observer_a.transaction_completed) and
        (observer_b and observer_b.transaction_completed)
    )
    evidence["observation_ok"] = bool(evidence["transaction_completed"])
    evidence["recovery_ok"] = len(cleanup_failures) == 0
    evidence["cleanup_failures"] = cleanup_failures
    evidence["recovery_results"] = recovery_results

    # Gate 7: Live verification
    metrics_ok = bool(
        system_metrics.get("has_data")
        and system_metrics.get("sample_count", 0) > 0
        and system_metrics.get("cpu_percent_max") is not None
        and system_metrics.get("memory_percent_max") is not None
        and system_metrics.get("db_connections_max") is not None
        and system_metrics.get("waiting_locks_max") is not None
    )
    if not metrics_thread_alive:
        raise RuntimeError("Metrics thread is not alive")
    live_verification = {
        "job_a_succeeded": bool(job_a and job_a_verification and job_a_verification.get("succeeded")),
        "job_b_succeeded": bool(job_b and job_b_verification and job_b_verification.get("succeeded")),
        "attempt_count_a": job_a.attempt_count if job_a else 0,
        "attempt_count_b": job_b.attempt_count if job_b else 0,
        "observer_a_completed": bool(observer_a and observer_a.transaction_completed),
        "observer_b_completed": bool(observer_b and observer_b.transaction_completed),
        "postflight_pass": _all_postflight_pass(postflight),
        "metrics_ok": metrics_ok,
        "metrics_thread_alive": metrics_thread_alive,
    }
    evidence["live_verification"] = live_verification
    evidence["metrics_coverage_ok"] = metrics_ok and metrics_thread_alive
    evidence["measurement_status"] = measurement_status
    evidence["failure_reason"] = failure_reason

    _validate_canonical_evidence_semantics(evidence, require_final=True)

    # ── Gate 8: Privacy check (fail-closed) ──
    privacy_ok, privacy_issues = _privacy_check_passed(evidence)
    evidence["privacy_check_passed"] = privacy_ok
    if not privacy_ok:
        raise RuntimeError(f"Privacy check failed: {privacy_issues}")

    # ── Evidence write: omitted from run_canonical().
    # The management command writes evidence via write_evidence() as the single writer.

    return evidence


def _postflight_key_passed(key, value):
    """Check if a single postflight key passes validation.
    Returns True if the key passes, False otherwise.
    """
    if not isinstance(value, dict):
        return bool(value)
    if value.get("passed") is False:
        return False
    if value.get("baseline_matched") is False:
        return False
    # Per-key schema validation for informational keys
    schema_passed = False
    if key == "table_counts":
        required = {"master_count", "master_class_count", "structure_count", "inspection_file_count"}
        if all(k in value for k in required):
            if all(type(value[k]) is int and value[k] >= 0 for k in required):
                schema_passed = True
    elif key == "table_hashes":
        required = {"master_hash", "master_class_hash", "structure_hash", "inspection_file_hash"}
        if all(k in value for k in required):
            if all(isinstance(value[k], str) and len(value[k]) == 64 and all(c in "0123456789abcdef" for c in value[k]) for k in required):
                schema_passed = True
    elif key == "inspection_file_distribution":
        if all(k in value for k in ("total", "by_priority")):
            total = value["total"]
            if type(total) is int and total >= 0:
                bp = value["by_priority"]
                if isinstance(bp, dict):
                    if (all(type(k) is int for k in bp) and
                        all(type(v) is int and v >= 0 for v in bp.values()) and
                        total == sum(bp.values())):
                        schema_passed = True
    elif key == "inspection_file_pathset_hash":
        if isinstance(value.get("pathset_hash"), str) and len(value["pathset_hash"]) == 64 and all(c in "0123456789abcdef" for c in value["pathset_hash"]):
            schema_passed = True
    elif key == "system_metrics":
        required = {"db_connections", "waiting_locks", "granted_locks", "cpu_percent", "memory_percent", "passed"}
        if all(k in value for k in required):
            if value.get("passed") is True:
                dc = value["db_connections"]
                wl = value["waiting_locks"]
                gl = value["granted_locks"]
                cp = value["cpu_percent"]
                mp = value["memory_percent"]
                if (type(dc) is int and dc >= 0 and
                    type(wl) is int and wl >= 0 and
                    type(gl) is int and gl >= 0 and
                    isinstance(cp, (int, float)) and type(cp) is not bool and cp >= 0 and math.isfinite(cp) and
                    isinstance(mp, (int, float)) and type(mp) is not bool and mp >= 0 and math.isfinite(mp)):
                    schema_passed = True
    # Known schema keys: return schema result directly, no fallback to generic positive
    known_schema_keys = {"table_counts", "table_hashes", "inspection_file_distribution", "inspection_file_pathset_hash", "system_metrics"}
    if key in known_schema_keys:
        return schema_passed
    # Fail-closed on empty dicts or missing positive indicator
    if not value:
        return False
    has_positive = False
    for v in value.values():
        if v is True:
            has_positive = True
            break
    if not has_positive and "status" not in value:
        return False
    return True


def _all_postflight_pass(postflight):
    """Fail-closed: return True only when all postflight checks have positive pass results."""
    if not postflight:
        return False
    for key, value in postflight.items():
        if not _postflight_key_passed(key, value):
            return False
    return True


def _write_canonical_evidence(evidence, output_dir):
    """Write canonical evidence to disk with SHA-256 checksum.

    Fail-closed: raises RuntimeError on write failure.
    Atomic write: temp file -> flush -> fsync -> atomic replace.
    """
    path = Path(output_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        evidence_path = path / "canonical_evidence.json"
        manifest_path = path / "checksums.sha256"
        # Atomic write: temp file -> flush -> fsync -> atomic replace
        tmp_path = path / ".canonical_evidence.json.tmp"
        try:
            with tmp_path.open("wb") as f:
                f.write(json.dumps(evidence, ensure_ascii=False, indent=2, default=str).encode("utf-8"))
                f.flush()
                import os
                os.fsync(f.fileno())
            os.replace(tmp_path, evidence_path)
            # Verify JSON after replace: parse to ensure valid JSON
            json.loads(evidence_path.read_text(encoding="utf-8"))
            # Manifest
            digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            tmp_manifest = path / ".checksums.sha256.tmp"
            try:
                with tmp_manifest.open("wb") as f:
                    f.write(f"{digest}  canonical_evidence.json\n".encode("utf-8"))
                    f.flush()
                    import os
                    os.fsync(f.fileno())
                os.replace(tmp_manifest, manifest_path)
            except Exception:
                if tmp_manifest.exists():
                    tmp_manifest.unlink()
                raise
            # Verify manifest: re-read and validate
            manifest_content = manifest_path.read_text(encoding="utf-8").strip()
            manifest_lines = manifest_content.splitlines()
            if len(manifest_lines) != 1:
                raise RuntimeError(f"Manifest must have exactly 1 entry, got {len(manifest_lines)}")
            parts = manifest_lines[0].split()
            if len(parts) != 2:
                raise RuntimeError(f"Manifest line must have 2 parts (digest filename), got {len(parts)}")
            manifest_digest, manifest_filename = parts
            if manifest_filename != "canonical_evidence.json":
                raise RuntimeError(f"Manifest filename mismatch: expected 'canonical_evidence.json', got '{manifest_filename}'")
            if len(manifest_digest) != 64 or not all(c in "0123456789abcdef" for c in manifest_digest):
                raise RuntimeError(f"Manifest digest must be 64-char hex, got '{manifest_digest}'")
            if manifest_digest != digest:
                raise RuntimeError(f"Manifest digest does not match computed digest")
            # Re-compute file hash and verify against manifest
            recomputed = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            if recomputed != manifest_digest:
                raise RuntimeError(f"File hash mismatch: recomputed={recomputed}, manifest={manifest_digest}")
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            if evidence_path.exists():
                evidence_path.unlink()
            if manifest_path.exists():
                manifest_path.unlink()
            raise
        return evidence_path
    except Exception as e:
        raise RuntimeError(f"Failed to write canonical evidence: {e}") from e
