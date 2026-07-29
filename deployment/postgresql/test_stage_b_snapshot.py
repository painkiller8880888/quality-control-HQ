import datetime as dt
import decimal
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("stage_b_snapshot", Path(__file__).with_name("stage_b_snapshot.py"))
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


class Cursor:
    def __init__(self, rows, columns=("value",)):
        self.rows, self.description = rows, [type("Column", (), {"name": c}) for c in columns]
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0]


class Connection:
    def execute(self, query, parameters=None):
        if query.startswith("SELECT current_database"): return Cursor([("restore_db", 22, "owner")])
        if query == "SHOW server_version_num": return Cursor([("160002",)])
        if "GROUP BY c.relkind" in query: return Cursor([])
        if "django_migrations')" in query: return Cursor([(False,)])
        if "n.nspname='public'" in query: return Cursor([], ("relkind", "relname"))
        if query.startswith("SELECT to_regclass"): return Cursor([(None,)])
        raise AssertionError(query)


class SnapshotTests(unittest.TestCase):
    def test_canonical_stable_unicode_and_scalars(self):
        left = {"z": None, "a": [True, 2, "日本語", decimal.Decimal("1.20"), dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)]}
        right = {"a": [True, 2, "日本語", decimal.Decimal("1.20"), dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)], "z": None}
        self.assertEqual(snapshot.canonical_json_bytes(left), snapshot.canonical_json_bytes(right))
        with self.assertRaises(ValueError): snapshot.canonical_json_bytes({"bad": float("nan")})

    def test_row_and_path_contracts(self):
        self.assertEqual(snapshot.rows_hash([(1, "x")], ["id", "name"]), snapshot.rows_hash([(1, "x")], ["id", "name"]))
        self.assertEqual(snapshot.digest(sorted({"z", "a", "a"})), snapshot.digest(["a", "z"]))

    def test_identity_normalization(self):
        result = snapshot.identity(" DB.EXAMPLE. ", "05432", "restore_db", 22, "owner", "160002")
        self.assertEqual(result["endpoint_hash"], snapshot.digest("db.example\n5432"))
        with self.assertRaises(ValueError): snapshot.identity("http://bad", "5432", "restore_db", 22, "owner", "1")

    def test_restore_requires_distinct_oid_and_no_output_on_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(snapshot.psycopg, "connect") as connect, patch.dict("os.environ", {"STAGE_B_DB_NAME":"restore_db","STAGE_B_DB_HOST":"db","STAGE_B_DB_PORT":"5432","STAGE_B_DB_USER":"u","STAGE_B_DB_PASSWORD":"p"}, clear=False):
            connect.return_value.__enter__.return_value = Connection()
            target = Path(temp) / "result.json"
            with patch("sys.argv", ["snapshot", "--output", str(target), "--identity-mode", "restore", "--expected-distinct-oid-hash", snapshot.digest(22)]):
                with self.assertRaises(SystemExit): snapshot.main()
            self.assertFalse(target.exists())

    def test_source_snapshot_is_privacy_safe(self):
        data = snapshot.snapshot(Connection(), "db.example.", "5432")
        self.assertNotIn("restore_db", str(data))
        self.assertTrue(data["empty_proof"]["is_empty"])


if __name__ == "__main__": unittest.main()
