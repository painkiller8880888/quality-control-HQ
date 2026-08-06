"""Stage B process bridge for the two approved PostgreSQL operations.

This module deliberately has no database, service, network, or runtime-provider
dependency.  The runner is injected for tests; the product runner is the only
place that knows how to start a child process.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO


SUPPORTED_OPERATIONS = ("pg_dump", "pg_restore_list")
ALLOWED_ENVIRONMENT_KEYS = frozenset(
    {
        "PGDATABASE",
        "PGHOST",
        "PGPASSWORD",
        "PGPORT",
        "PGSSLMODE",
        "PGUSER",
    }
)
PG_DUMP_ARGUMENTS = ("--format=custom", "--no-owner", "--no-acl")
PG_RESTORE_LIST_ARGUMENTS = ("--list",)
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MAX_INT64 = (1 << 63) - 1
MAX_TIMEOUT_SECONDS = 3600


class BridgeError(Exception):
    """An error whose string is always a fixed, privacy-safe reason code."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RunnerResult:
    """The narrow result contract between a runner and this bridge."""

    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False


Runner = Callable[[str, Sequence[str], Mapping[str, str], int], RunnerResult]
FileHasher = Callable[[Path], tuple[int, str]]


def _is_plain_object(value: object) -> bool:
    return type(value) is dict


def _is_string(value: object) -> bool:
    return type(value) is str


def _is_integer(value: object) -> bool:
    return type(value) is int


def _fail(reason: str) -> None:
    raise BridgeError(reason)


def _validate_artifact_path(value: object) -> str:
    if not _is_string(value) or not value.strip():
        _fail("stage_b_bridge_request_invalid")
    try:
        if not Path(value).is_absolute():
            _fail("stage_b_bridge_request_invalid")
    except (OSError, ValueError):
        _fail("stage_b_bridge_request_invalid")
    return value


def _validate_request(request: object) -> dict[str, object]:
    if not _is_plain_object(request):
        _fail("stage_b_bridge_request_invalid")

    if set(request) != {"operation", "arguments", "environment", "artifact"}:
        _fail("stage_b_bridge_request_invalid")

    operation = request["operation"]
    if not _is_string(operation):
        _fail("stage_b_bridge_request_invalid")
    if operation not in SUPPORTED_OPERATIONS:
        _fail("stage_b_bridge_operation_unsupported")

    arguments = request["arguments"]
    if type(arguments) is not list or any(not _is_string(item) for item in arguments):
        _fail("stage_b_bridge_request_invalid")
    expected_arguments = (
        PG_DUMP_ARGUMENTS
        if operation == "pg_dump"
        else PG_RESTORE_LIST_ARGUMENTS
    )
    if tuple(arguments) != expected_arguments:
        _fail("stage_b_bridge_request_invalid")

    environment = request["environment"]
    if not _is_plain_object(environment):
        _fail("stage_b_bridge_request_invalid")
    if any(
        not _is_string(key)
        or key not in ALLOWED_ENVIRONMENT_KEYS
        or not _is_string(value)
        for key, value in environment.items()
    ):
        _fail("stage_b_bridge_request_invalid")

    artifact = request["artifact"]
    if not _is_plain_object(artifact):
        _fail("stage_b_bridge_request_invalid")
    expected_artifact_keys = (
        {"path", "timeout_seconds"}
        if operation == "pg_dump"
        else {"path", "expected_sha256", "timeout_seconds"}
    )
    if set(artifact) != expected_artifact_keys:
        _fail("stage_b_bridge_request_invalid")

    path = _validate_artifact_path(artifact["path"])
    timeout_seconds = artifact["timeout_seconds"]
    if (
        not _is_integer(timeout_seconds)
        or timeout_seconds < 1
        or timeout_seconds > MAX_TIMEOUT_SECONDS
    ):
        _fail("stage_b_bridge_request_invalid")

    normalized_artifact: dict[str, object] = {
        "path": path,
        "timeout_seconds": timeout_seconds,
    }
    if operation == "pg_restore_list":
        expected_hash = artifact["expected_sha256"]
        if not _is_string(expected_hash) or not SHA256_PATTERN.fullmatch(expected_hash):
            _fail("stage_b_bridge_request_invalid")
        normalized_artifact["expected_sha256"] = expected_hash

    return {
        "operation": operation,
        "arguments": list(arguments),
        "environment": dict(environment),
        "artifact": normalized_artifact,
    }


def _hash_file(path: Path) -> tuple[int, str]:
    try:
        stat_result = path.stat()
        if not path.is_file() or stat_result.st_size <= 0:
            _fail("stage_b_artifact_invalid")
        if stat_result.st_size > MAX_INT64:
            _fail("stage_b_artifact_invalid")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return int(stat_result.st_size), digest.hexdigest()
    except BridgeError:
        raise
    except Exception:
        _fail("stage_b_artifact_invalid")


def _validate_runner_result(result: object) -> RunnerResult:
    if type(result) is not RunnerResult:
        _fail("stage_b_runner_result_invalid")
    if (
        (result.exit_code is not None and not _is_integer(result.exit_code))
        or type(result.stdout) is not bytes
        or type(result.stderr) is not bytes
        or type(result.timed_out) is not bool
    ):
        _fail("stage_b_runner_result_invalid")
    return result


def _validate_public_result(result: object) -> dict[str, object]:
    if not _is_plain_object(result) or set(result) != {
        "success",
        "exit_code",
        "size",
        "hash",
    }:
        _fail("stage_b_bridge_result_invalid")
    if (
        type(result["success"]) is not bool
        or result["success"] is not True
        or not _is_integer(result["exit_code"])
        or result["exit_code"] != 0
        or not _is_integer(result["size"])
        or not 1 <= result["size"] <= MAX_INT64
        or not _is_string(result["hash"])
        or not SHA256_PATTERN.fullmatch(result["hash"])
    ):
        _fail("stage_b_bridge_result_invalid")
    return {
        "success": True,
        "exit_code": 0,
        "size": int(result["size"]),
        "hash": result["hash"],
    }


def run_process(
    executable: str,
    argv: Sequence[str],
    environment: Mapping[str, str],
    timeout_seconds: int,
) -> RunnerResult:
    """Run one executable with argv and an allowlisted, non-inherited env."""

    try:
        process_environment: dict[str, str] = {}
        if os.name == "nt":
            system_root = os.environ.get("SystemRoot")
            if not _is_string(system_root) or not system_root:
                raise OSError("SystemRoot is unavailable")
            process_environment["SystemRoot"] = system_root
        for key, value in environment.items():
            if (
                not _is_string(key)
                or key not in ALLOWED_ENVIRONMENT_KEYS
                or not _is_string(value)
            ):
                raise ValueError("invalid process environment")
            process_environment[key] = value
        completed = subprocess.run(
            [executable, *argv],
            shell=False,
            env=process_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if type(error.stdout) is bytes else b""
        stderr = error.stderr if type(error.stderr) is bytes else b""
        return RunnerResult(None, stdout, stderr, True)
    except Exception:
        raise
    return RunnerResult(completed.returncode, completed.stdout, completed.stderr)


class StageBProcessBridge:
    """Validate a request, invoke one injected runner, and return exact result."""

    def __init__(
        self,
        runner: Runner = run_process,
        executables: Mapping[str, str] | None = None,
        hasher: FileHasher = _hash_file,
    ):
        self._runner = runner
        self._executables = dict(
            executables
            if executables is not None
            else {"pg_dump": "pg_dump", "pg_restore_list": "pg_restore"}
        )
        if set(self._executables) != set(SUPPORTED_OPERATIONS) or any(
            not _is_string(value) or not value.strip()
            for value in self._executables.values()
        ):
            raise ValueError("invalid executable configuration")
        self._hasher = hasher

    def invoke(self, request: object) -> dict[str, object]:
        normalized = _validate_request(request)
        operation = normalized["operation"]
        arguments = normalized["arguments"]
        environment = normalized["environment"]
        artifact = normalized["artifact"]
        assert isinstance(operation, str)
        assert isinstance(arguments, list)
        assert isinstance(environment, dict)
        assert isinstance(artifact, dict)
        path = Path(artifact["path"])
        timeout_seconds = artifact["timeout_seconds"]
        assert isinstance(timeout_seconds, int)

        if operation == "pg_restore_list":
            try:
                _, input_hash = self._hasher(path)
            except BridgeError:
                raise
            except Exception:
                _fail("stage_b_artifact_invalid")
            if input_hash != artifact["expected_sha256"]:
                _fail("stage_b_artifact_hash_mismatch")
            argv = [*arguments, str(path)]
        else:
            try:
                if path.exists():
                    _fail("stage_b_artifact_invalid")
            except BridgeError:
                raise
            except Exception:
                _fail("stage_b_artifact_invalid")
            argv = [*arguments, "--file", str(path)]

        try:
            runner_result = self._runner(
                self._executables[operation],
                argv,
                environment,
                timeout_seconds,
            )
        except Exception:
            _fail("stage_b_runner_failed")

        result = _validate_runner_result(runner_result)
        if result.timed_out:
            _fail("stage_b_runner_timeout")
        if result.exit_code != 0:
            _fail("stage_b_runner_nonzero")

        if operation == "pg_dump":
            size, digest = self._hash_artifact(path)
        else:
            if len(result.stdout) <= 0 or len(result.stdout) > MAX_INT64:
                _fail("stage_b_artifact_invalid")
            try:
                digest = hashlib.sha256(result.stdout).hexdigest()
            except Exception:
                _fail("stage_b_artifact_invalid")
            size = len(result.stdout)

        return {
            "success": True,
            "exit_code": 0,
            "size": int(size),
            "hash": digest,
        }

    def _hash_artifact(self, path: Path) -> tuple[int, str]:
        try:
            size, digest = self._hasher(path)
        except BridgeError:
            raise
        except Exception:
            _fail("stage_b_artifact_invalid")
        if (
            not _is_integer(size)
            or size <= 0
            or size > MAX_INT64
            or not _is_string(digest)
            or not SHA256_PATTERN.fullmatch(digest)
        ):
            _fail("stage_b_artifact_invalid")
        return size, digest


def _read_one_json_object(text: str) -> object:
    try:
        decoder = json.JSONDecoder()
        leading = len(text) - len(text.lstrip())
        value, end = decoder.raw_decode(text, leading)
        if text[end:].strip():
            _fail("stage_b_bridge_request_invalid")
        return value
    except BridgeError:
        raise
    except Exception:
        _fail("stage_b_bridge_request_invalid")


def main(
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    bridge: StageBProcessBridge | None = None,
) -> int:
    """CLI entry point; stdout is either one result object or empty."""

    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    bridge = StageBProcessBridge() if bridge is None else bridge
    try:
        request = _read_one_json_object(stdin.read())
        result = _validate_public_result(bridge.invoke(request))
        stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0
    except BridgeError as error:
        stderr.write(error.reason + "\n")
        return 1
    except Exception:
        stderr.write("stage_b_bridge_failure\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
