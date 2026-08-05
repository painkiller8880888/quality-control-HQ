import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "stage_b_process_bridge", Path(__file__).with_name("stage_b_process_bridge.py")
)
bridge_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge_module
SPEC.loader.exec_module(bridge_module)


class FakeRunner:
    def __init__(self, result=None, action=None):
        self.calls = []
        self.result = result
        self.action = action

    def __call__(self, executable, argv, environment, timeout_seconds):
        self.calls.append((executable, list(argv), dict(environment), timeout_seconds))
        if self.action is not None:
            self.action(argv)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class StaticBridge:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def invoke(self, request):
        if self.error is not None:
            raise self.error
        return self.result


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dump = self.root / "approved.dump"
        self.dump.write_bytes(b"approved dump")
        self.environment = {
            "PGHOST": "raw-host.example",
            "PGPORT": "5432",
            "PGUSER": "sentinel-role",
            "PGPASSWORD": "sentinel-credential",
        }

    def tearDown(self):
        self.temp.cleanup()

    def request(self, operation="pg_dump", path=None, **overrides):
        path = str(path or self.root / "output.dump")
        request = {
            "operation": operation,
            "arguments": list(
                bridge_module.PG_DUMP_ARGUMENTS
                if operation == "pg_dump"
                else bridge_module.PG_RESTORE_LIST_ARGUMENTS
            ),
            "environment": dict(self.environment),
            "artifact": {
                "path": path,
                "timeout_seconds": 17,
            },
        }
        if operation == "pg_restore_list":
            request["artifact"]["expected_sha256"] = hashlib.sha256(
                self.dump.read_bytes()
            ).hexdigest()
        request.update(overrides)
        return request

    def invoke_error(self, bridge, request):
        with self.assertRaises(bridge_module.BridgeError) as context:
            bridge.invoke(request)
        self.assertRegex(str(context.exception), r"^[a-z0-9_]+$")
        return context.exception.reason

    def test_both_operations_use_expected_argv_environment_timeout_and_exact_result(self):
        dump_runner = FakeRunner(
            bridge_module.RunnerResult(0, b"", b""),
            action=lambda argv: Path(argv[-1]).write_bytes(b"new dump"),
        )
        dump_bridge = bridge_module.StageBProcessBridge(
            runner=dump_runner,
            executables={"pg_dump": "pg_dump.exe", "pg_restore_list": "pg_restore.exe"},
        )
        dump_result = dump_bridge.invoke(self.request())
        self.assertEqual(
            dump_runner.calls,
            [
                (
                    "pg_dump.exe",
                    [*bridge_module.PG_DUMP_ARGUMENTS, "--file", str(self.root / "output.dump")],
                    self.environment,
                    17,
                )
            ],
        )
        self.assertEqual(set(dump_result), {"success", "exit_code", "size", "hash"})
        self.assertIs(type(dump_result["success"]), bool)
        self.assertIs(type(dump_result["exit_code"]), int)
        self.assertIs(type(dump_result["size"]), int)
        self.assertEqual(dump_result["exit_code"], 0)
        self.assertEqual(dump_result["size"], len(b"new dump"))
        self.assertRegex(dump_result["hash"], r"^[a-f0-9]{64}$")

        list_runner = FakeRunner(bridge_module.RunnerResult(0, b"TABLE public.x\n", b""))
        list_bridge = bridge_module.StageBProcessBridge(
            runner=list_runner,
            executables={"pg_dump": "pg_dump.exe", "pg_restore_list": "pg_restore.exe"},
        )
        list_result = list_bridge.invoke(
            self.request("pg_restore_list", path=self.dump)
        )
        self.assertEqual(
            list_runner.calls,
            [
                (
                    "pg_restore.exe",
                    [*bridge_module.PG_RESTORE_LIST_ARGUMENTS, str(self.dump)],
                    self.environment,
                    17,
                )
            ],
        )
        self.assertEqual(list_result["size"], len(b"TABLE public.x\n"))
        self.assertEqual(
            list_result["hash"], hashlib.sha256(b"TABLE public.x\n").hexdigest()
        )

    def test_request_boundary_rejects_null_non_object_missing_extra_bad_types_and_unsupported(self):
        runner = FakeRunner(bridge_module.RunnerResult(0, b"list", b""))
        bridge = bridge_module.StageBProcessBridge(runner=runner)
        valid = self.request("pg_restore_list", path=self.dump)
        invalid_requests = [
            None,
            [],
            {"operation": "pg_dump"},
            {**valid, "extra": "sentinel"},
            {**valid, "artifact": None},
            {**valid, "arguments": "--list"},
            {**valid, "arguments": None},
            {**valid, "environment": None},
            {**valid, "environment": {"PGHOST": None}},
            {**valid, "environment": {"SENTINEL": "credential"}},
            {**valid, "operation": None},
            {**valid, "artifact": {"path": str(self.dump), "timeout_seconds": None, "expected_sha256": "a" * 64}},
            {**valid, "operation": "pg_restore"},
            {**valid, "operation": "retained_dump"},
            {**valid, "operation": "unknown"},
        ]
        reasons = [self.invoke_error(bridge, request) for request in invalid_requests]
        self.assertEqual(reasons[-3:], ["stage_b_bridge_operation_unsupported"] * 3)
        self.assertEqual(runner.calls, [])

        empty_list_runner = FakeRunner(bridge_module.RunnerResult(0, b"", b""))
        empty_list_bridge = bridge_module.StageBProcessBridge(runner=empty_list_runner)
        self.assertEqual(
            self.invoke_error(
                empty_list_bridge, self.request("pg_restore_list", path=self.dump)
            ),
            "stage_b_artifact_invalid",
        )

        zero_output = self.root / "zero-output.dump"
        zero_runner = FakeRunner(
            bridge_module.RunnerResult(0, b"", b""),
            action=lambda argv: Path(argv[-1]).touch(),
        )
        zero_bridge = bridge_module.StageBProcessBridge(runner=zero_runner)
        self.assertEqual(
            self.invoke_error(zero_bridge, self.request(path=zero_output)),
            "stage_b_artifact_invalid",
        )
        self.assertTrue(zero_output.exists())

        directory_output = self.root / "directory-output.dump"
        directory_output.mkdir()
        directory_runner = FakeRunner(bridge_module.RunnerResult(0, b"", b""))
        directory_bridge = bridge_module.StageBProcessBridge(runner=directory_runner)
        self.assertEqual(
            self.invoke_error(directory_bridge, self.request(path=directory_output)),
            "stage_b_artifact_invalid",
        )

        missing_output = self.root / "missing-output.dump"
        missing_runner = FakeRunner(bridge_module.RunnerResult(0, b"", b""))
        missing_bridge = bridge_module.StageBProcessBridge(runner=missing_runner)
        self.assertEqual(
            self.invoke_error(missing_bridge, self.request(path=missing_output)),
            "stage_b_artifact_invalid",
        )

    def test_runner_failures_are_fail_closed_and_do_not_expose_diagnostics(self):
        cases = [
            (RuntimeError("SENTINEL raw command private path"), "stage_b_runner_failed"),
            (bridge_module.RunnerResult(None, b"partial", b"SENTINEL", True), "stage_b_runner_timeout"),
            (bridge_module.RunnerResult(1, b"partial", b"SENTINEL"), "stage_b_runner_nonzero"),
            (bridge_module.RunnerResult(-9, b"partial", b"SENTINEL"), "stage_b_runner_nonzero"),
            ({"exit_code": 0, "stdout": b"ok", "stderr": b""}, "stage_b_runner_result_invalid"),
            (bridge_module.RunnerResult(0, "not bytes", b""), "stage_b_runner_result_invalid"),
            (bridge_module.RunnerResult(0, b"ok", "not bytes"), "stage_b_runner_result_invalid"),
        ]
        for runner_result, reason in cases:
            runner = FakeRunner(runner_result)
            bridge = bridge_module.StageBProcessBridge(runner=runner)
            message = self.invoke_error(bridge, self.request())
            self.assertEqual(message, reason)
            self.assertNotIn("SENTINEL", message)
            self.assertNotIn("raw", message)
            self.assertNotIn("private", message)

    def test_artifact_boundaries_fail_closed_and_partial_dump_is_retained(self):
        missing = self.root / "missing.dump"
        runner = FakeRunner(bridge_module.RunnerResult(0, b"list", b""))
        bridge = bridge_module.StageBProcessBridge(runner=runner)
        self.assertEqual(
            self.invoke_error(bridge, self.request("pg_restore_list", path=missing)),
            "stage_b_artifact_invalid",
        )
        directory = self.root / "directory"
        directory.mkdir()
        self.assertEqual(
            self.invoke_error(bridge, self.request("pg_restore_list", path=directory)),
            "stage_b_artifact_invalid",
        )
        empty = self.root / "empty.dump"
        empty.touch()
        self.assertEqual(
            self.invoke_error(bridge, self.request("pg_restore_list", path=empty)),
            "stage_b_artifact_invalid",
        )
        self.assertEqual(runner.calls, [])

        mismatch = self.request("pg_restore_list", path=self.dump)
        mismatch["artifact"]["expected_sha256"] = "0" * 64
        self.assertEqual(self.invoke_error(bridge, mismatch), "stage_b_artifact_hash_mismatch")
        self.assertEqual(runner.calls, [])

        partial = self.root / "partial.dump"

        def write_partial(argv):
            partial.write_bytes(b"partial dump")

        nonzero_runner = FakeRunner(bridge_module.RunnerResult(2, b"", b"raw stderr"), write_partial)
        nonzero_bridge = bridge_module.StageBProcessBridge(runner=nonzero_runner)
        failed_request = self.request(path=partial)
        self.assertEqual(self.invoke_error(nonzero_bridge, failed_request), "stage_b_runner_nonzero")
        self.assertTrue(partial.exists())
        self.assertEqual(partial.read_bytes(), b"partial dump")

        timeout_runner = FakeRunner(
            bridge_module.RunnerResult(None, b"", b"raw stderr", True), write_partial
        )
        timeout_bridge = bridge_module.StageBProcessBridge(runner=timeout_runner)
        self.assertEqual(self.invoke_error(timeout_bridge, failed_request), "stage_b_runner_timeout")
        self.assertTrue(partial.exists())

    def test_hash_failure_is_fail_closed(self):
        runner = FakeRunner(bridge_module.RunnerResult(0, b"", b""))

        def failing_hasher(path):
            raise OSError("SENTINEL private path")

        bridge = bridge_module.StageBProcessBridge(runner=runner, hasher=failing_hasher)
        self.assertEqual(self.invoke_error(bridge, self.request()), "stage_b_artifact_invalid")
        self.assertEqual(len(runner.calls), 1)

        oversized_bridge = bridge_module.StageBProcessBridge(
            runner=FakeRunner(bridge_module.RunnerResult(0, b"", b"")),
            hasher=lambda path: (bridge_module.MAX_INT64 + 1, "a" * 64),
        )
        self.assertEqual(
            self.invoke_error(oversized_bridge, self.request()),
            "stage_b_artifact_invalid",
        )

    def test_cli_success_is_one_json_object_and_errors_are_fixed_stderr_only(self):
        result = {"success": True, "exit_code": 0, "size": 7, "hash": "a" * 64}
        output = io.StringIO()
        diagnostics = io.StringIO()
        code = bridge_module.main(
            io.StringIO(json.dumps(self.request())),
            output,
            diagnostics,
            bridge=StaticBridge(result=result),
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), result)
        self.assertEqual(output.getvalue().count("\n"), 1)
        self.assertEqual(diagnostics.getvalue(), "")
        invalid_bridge = bridge_module.StageBProcessBridge(
            runner=FakeRunner(bridge_module.RunnerResult(0, b"", b""))
        )
        for payload in ("", "null", "{} {}", json.dumps(self.request()) + json.dumps(self.request())):
            output = io.StringIO()
            diagnostics = io.StringIO()
            code = bridge_module.main(
                io.StringIO(payload), output, diagnostics, bridge=invalid_bridge
            )
            self.assertEqual(code, 1)
            self.assertEqual(output.getvalue(), "")
            self.assertRegex(diagnostics.getvalue(), r"^[a-z0-9_]+\n$")
            self.assertNotIn("sentinel", diagnostics.getvalue().lower())

        output = io.StringIO()
        diagnostics = io.StringIO()
        code = bridge_module.main(
            io.StringIO(json.dumps(self.request())),
            output,
            diagnostics,
            bridge=StaticBridge(error=RuntimeError("SENTINEL stack trace raw host")),
        )
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(diagnostics.getvalue(), "stage_b_bridge_failure\n")
        self.assertNotIn("SENTINEL", diagnostics.getvalue())

        output = io.StringIO()
        diagnostics = io.StringIO()
        malformed_result = {**result, "diagnostic": "SENTINEL raw output"}
        code = bridge_module.main(
            io.StringIO(json.dumps(self.request())),
            output,
            diagnostics,
            bridge=StaticBridge(result=malformed_result),
        )
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(diagnostics.getvalue(), "stage_b_bridge_result_invalid\n")
        self.assertNotIn("SENTINEL", diagnostics.getvalue())


if __name__ == "__main__":
    unittest.main()
