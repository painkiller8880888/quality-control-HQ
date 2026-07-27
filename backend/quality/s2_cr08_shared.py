import hashlib

ADVISORY_LOCK_NAMESPACE = 42
ADVISORY_LOCK_MARKER_PREFIX = "qcs208_"


def make_advisory_lock_id(job_id, execution_token):
    """Deterministic int4-safe lock id from job_id + execution_token (F4/F6)."""
    marker_input = f"{job_id}:{execution_token}"
    return int(hashlib.sha256(marker_input.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF


def make_application_name_marker(job_id, execution_token):
    """Application_name marker for DB session verification (F6).

    Used with SET LOCAL application_name inside the work transaction.
    The observer verifies this matches in pg_stat_activity alongside the advisory lock.
    7-char prefix + 32-hex-char hash = 39 chars total, well within application_name limits.
    Hash is 128-bit to minimize collision risk vs the 31-bit lock ID.
    """
    marker_input = f"{job_id}:{execution_token}"
    return ADVISORY_LOCK_MARKER_PREFIX + hashlib.sha256(marker_input.encode()).hexdigest()[:32]
