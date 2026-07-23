import hashlib
import json
import time
from pathlib import Path
from threading import Thread, Event

from django.db import connection, close_old_connections


TRANSACTION_SNAPSHOT_QUERY = """
SELECT
    pid,
    client_port,
    xact_start,
    state
FROM pg_stat_activity
WHERE datname = current_database()
  AND state != 'idle'
  AND pid != pg_backend_pid()
"""

CLOCK_QUERY = "SELECT clock_timestamp()"
PID_QUERY = "SELECT pg_backend_pid()"


def _db_clock():
    with connection.cursor() as cursor:
        cursor.execute(CLOCK_QUERY)
        return cursor.fetchone()[0]


def _connection_pid():
    with connection.cursor() as cursor:
        cursor.execute(PID_QUERY)
        return cursor.fetchone()[0]


def _sha256(data):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _backend_hash(pid, client_port):
    raw = f"pid={pid}|port={client_port}"
    return _sha256(raw)


def poll_active_backends():
    if connection.vendor != "postgresql":
        return []
    with connection.cursor() as cursor:
        cursor.execute(TRANSACTION_SNAPSHOT_QUERY)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


class TransactionObserver:
    def __init__(self, poll_seconds=2.0, target_pid=None):
        self.poll_seconds = poll_seconds
        self.target_pid = target_pid
        self.backend_hash = None
        self.backend_pid = None
        self.backend_port = None
        self.xact_start = None
        self.end_lower_bound = None
        self.end_upper_bound = None
        self.poll_count = 0
        self.transaction_completed = False
        self._stop = Event()
        self._watch_event = Event()
        self._watch_armed = Event()
        self._baseline_ready = Event()
        self._thread = None
        self._prev_backend_ids = set()
        self._baseline_ok = False
        self._exception = None

    def start_watching(self):
        self._watch_event.set()

    def wait_watching_armed(self, timeout=10):
        deadline = time.monotonic() + timeout
        while not self._watch_armed.is_set():
            if self._exception:
                raise RuntimeError(
                    "TransactionObserver thread failed while waiting for arm"
                ) from self._exception
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._watch_armed.wait(min(remaining, 0.05))
        return True

    def _do_poll(self):
        before = _db_clock()
        current = poll_active_backends()
        after = _db_clock()
        self.poll_count += 1

        if self.target_pid is not None:
            ours = next(
                (b for b in current if b["pid"] == self.target_pid),
                None,
            )
            if not self._watch_event.is_set():
                self._prev_backend_ids = {(b["pid"], b["client_port"]) for b in current}
                return False
            if not self._watch_armed.is_set():
                ours_for_arm = next(
                    (b for b in current if b["pid"] == self.target_pid),
                    None,
                )
                if ours_for_arm and ours_for_arm.get("xact_start") is not None:
                    return False
                self._watch_armed.set()
            if ours and ours.get("xact_start") is not None:
                current_xs = ours["xact_start"]
                if self.backend_hash is None or current_xs != self.xact_start:
                    self.backend_pid = ours["pid"]
                    self.backend_port = ours["client_port"]
                    self.backend_hash = _backend_hash(ours["pid"], ours["client_port"])
                    self.xact_start = current_xs
                    self.end_lower_bound = before
                else:
                    self.end_lower_bound = before
            elif self.backend_hash is not None and self.end_lower_bound is not None:
                self.end_upper_bound = after
                self.transaction_completed = True
                return True
        else:
            current_ids = {(b["pid"], b["client_port"]) for b in current}
            if self.backend_hash is None:
                new_ids = current_ids - self._prev_backend_ids
                new_with_txn = [
                    b for b in current
                    if (b["pid"], b["client_port"]) in new_ids
                    and b["xact_start"] is not None
                ]
                if len(new_with_txn) == 1:
                    b = new_with_txn[0]
                    self.backend_pid = b["pid"]
                    self.backend_port = b["client_port"]
                    self.backend_hash = _backend_hash(b["pid"], b["client_port"])
                    self.xact_start = b["xact_start"]
                    self.end_lower_bound = before
            else:
                ours = next(
                    (b for b in current
                     if b["pid"] == self.backend_pid
                     and b["client_port"] == self.backend_port),
                    None,
                )
                if ours and ours.get("xact_start") == self.xact_start:
                    self.end_lower_bound = before
                elif self.end_lower_bound is not None:
                    self.end_upper_bound = after
                    self.transaction_completed = True
                    return True
            self._prev_backend_ids = current_ids
        return False

    def _observe(self):
        close_old_connections()
        try:
            self._do_poll()
            self._baseline_ok = self.poll_count >= 1
            self._baseline_ready.set()
            while not self._stop.is_set() and self._baseline_ok:
                if self._do_poll():
                    return
                if self._stop.wait(self.poll_seconds):
                    self._do_poll()
                    return
        except Exception as e:
            self._exception = e
            self._baseline_ready.set()

    @property
    def last_active_observation(self):
        return self.end_lower_bound

    @last_active_observation.setter
    def last_active_observation(self, value):
        self.end_lower_bound = value

    @property
    def first_absent_observation(self):
        return self.end_upper_bound

    @first_absent_observation.setter
    def first_absent_observation(self, value):
        self.end_upper_bound = value

    def start(self):
        self._thread = Thread(target=self._observe, daemon=True)
        self._thread.start()
        if not self._baseline_ready.wait(timeout=30):
            raise RuntimeError("TransactionObserver baseline poll did not complete within 30s")
        if self._exception:
            raise RuntimeError("TransactionObserver thread failed during baseline") from self._exception
        if not self._baseline_ok:
            raise RuntimeError("TransactionObserver baseline poll failed")
        return self

    def stop(self):
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise RuntimeError("TransactionObserver thread did not stop within 30s")
        if self._exception:
            raise RuntimeError("TransactionObserver thread failed") from self._exception


MEASUREMENT_SCHEMA_VERSION = "s2-cr-08-measurement-v3"


def build_evidence(
    job_a=None,
    job_b=None,
    transaction_observer=None,
    transaction_observer_a=None,
    transaction_observer_b=None,
    poll_seconds=2.0,
    fixture_version=MEASUREMENT_SCHEMA_VERSION,
):
    evidence = {
        "fixture_version": fixture_version,
        "measurement_date": timezone_now().isoformat(),
        "clock_sources": {
            "job_timestamps": "Django timezone.now() (Python process clock, UTC)",
            "transaction_xact_start": "pg_stat_activity.xact_start (PostgreSQL server clock, UTC)",
            "transaction_bounds": "PostgreSQL clock_timestamp() bracketed before/after snapshot (PostgreSQL server clock, UTC)",
        },
        "poll_interval_seconds": poll_seconds,
        "measurement_method": "Job.created_at (auto_now_add=True) for creation timestamp; pg_stat_activity poll bracketed by clock_timestamp() lower/upper bounds",
    }
    if job_a:
        evidence["job_a"] = _job_section(job_a)
    if job_b:
        evidence["job_b"] = _job_section(job_b)
    if job_a and job_b and job_a.finished_at and job_b.started_at:
        evidence["job_b_handoff_gap_seconds"] = round(
            (job_b.started_at - job_a.finished_at).total_seconds(), 6
        )

    obs_a = transaction_observer_a or transaction_observer
    obs_b = transaction_observer_b
    for label, obs in [("job_a_transaction", obs_a), ("job_b_transaction", obs_b)]:
        if obs and obs.transaction_completed:
            evidence[label] = _transaction_section(obs)
    return evidence


def _transaction_section(obs):
    txn = {
        "backend_hash": obs.backend_hash,
        "xact_start": _iso(obs.xact_start),
        "end_lower_bound": _iso(obs.end_lower_bound),
        "end_upper_bound": _iso(obs.end_upper_bound),
        "poll_count": obs.poll_count,
    }
    if obs.xact_start and obs.end_lower_bound:
        txn["duration_lower_bound_seconds"] = round(
            (obs.end_lower_bound - obs.xact_start).total_seconds(), 6
        )
    if obs.xact_start and obs.end_upper_bound:
        txn["duration_upper_bound_seconds"] = round(
            (obs.end_upper_bound - obs.xact_start).total_seconds(), 6
        )
    if obs.end_lower_bound and obs.end_upper_bound:
        txn["max_measurement_error_seconds"] = round(
            (obs.end_upper_bound - obs.end_lower_bound).total_seconds(), 6
        )
    return txn


def _iso(value):
    return value.isoformat() if value else None


def _job_section(job):
    section = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "depends_on_id": job.depends_on_id,
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


def timezone_now():
    from django.utils import timezone
    return timezone.now()


def verify_evidence_ordering(evidence):
    errors = []
    for key in ("job_a", "job_b"):
        job = evidence.get(key)
        if not job:
            continue
        created = job.get("created_at")
        started = job.get("started_at")
        finished = job.get("finished_at")
        if created and started:
            if _parse_dt(created) > _parse_dt(started):
                errors.append(f"{key}: created_at ({created}) > started_at ({started})")
        if started and finished:
            if _parse_dt(started) > _parse_dt(finished):
                errors.append(f"{key}: started_at ({started}) > finished_at ({finished})")
    for txn_key in ("job_a_transaction", "job_b_transaction", "transaction"):
        txn = evidence.get(txn_key)
        if not txn:
            continue
        xs = txn.get("xact_start")
        lb = txn.get("end_lower_bound")
        ub = txn.get("end_upper_bound")
        if xs and lb:
            if _parse_dt(xs) >= _parse_dt(lb):
                errors.append(f"{txn_key}: xact_start ({xs}) >= end_lower_bound ({lb})")
        if lb and ub:
            if _parse_dt(lb) > _parse_dt(ub):
                errors.append(f"{txn_key}: end_lower_bound ({lb}) > end_upper_bound ({ub})")
        if xs and ub:
            if _parse_dt(xs) > _parse_dt(ub):
                errors.append(f"{txn_key}: xact_start ({xs}) > end_upper_bound ({ub})")
    return errors


def _parse_dt(value):
    from datetime import datetime
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return value


def write_evidence(evidence, output_dir):
    path = Path(output_dir)
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"Output directory already exists and is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    evidence_path = path / "measurement.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    manifest_path = path / "checksums.sha256"
    manifest_path.write_text(f"{digest}  measurement.json\n", encoding="utf-8")
    return path
