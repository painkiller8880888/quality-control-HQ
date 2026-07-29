import datetime as dt
import decimal
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("stage_b_snapshot", Path(__file__).with_name("stage_b_snapshot.py"))
snapshot = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(snapshot)

class Cursor:
    def __init__(self, rows, columns=("value",)): self.rows, self.description = rows, [type("Column", (), {"name": c}) for c in columns]
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
    def test_canonical_golden_unicode_decimal_time(self):
        value = {"z": None, "a": [True, 2, "日本語", decimal.Decimal("1.20"), dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)]}
        self.assertEqual(snapshot.digest(value), "5da2618377a0ae442c3c0cd87af286fcb60ecb89902a6eb1f41f64ea79092ab7")
        self.assertEqual(snapshot.canonical_json_bytes(value), snapshot.canonical_json_bytes(dict(reversed(list(value.items())))))

    def test_row_shape_excludes_updated_at_and_preserves_duplicate_paths(self):
        self.assertEqual(snapshot.rows_hash([(1, "x", "volatile")], ["id", "name", "updated_at"]), {"count": 1, "stable_hash": "a61793f8ec74bdeada7a7f9a4f8b1de35719aaf2bc867a9c75ec9f2a10420dde", "fields": ["id", "name"]})
        self.assertEqual(snapshot.digest(sorted(["z", "a", "a"])), "1083f9182b5913e7df6d35f8b8382e55e0d70a2523460db161f9e915bdb8c7ef")

    def test_django_foreign_key_dictionary_names_have_golden_hash(self):
        # DB columns are master_id/class_master_id; canonical dictionaries use Django names.
        row = snapshot.rows_hash([(1, 7, None, "日本語")], ["id", "master", "class_master", "inspection_sheet_path"])
        self.assertEqual(row, {"count": 1, "stable_hash": "3eb56d95102832d24c444e3cd93842bd6a7018479292c5409c4f1752b196b77e", "fields": ["id", "master", "class_master", "inspection_sheet_path"]})
        self.assertEqual(snapshot.TABLE_FIELDS["quality_inspectionfile"][1], ("master", "master_id"))

    def test_identity_is_direct_normalized_text_hash(self):
        result = snapshot.identity(" DB.EXAMPLE. ", "05432", "restore_db", 22, "owner", "160002")
        self.assertEqual(result["endpoint_hash"], "ef6cea1eb186f0c9dd952eba0f2d66c425294d06dc4ea1b3050d4a88d7235908")
        self.assertEqual(result["oid_hash"], "785f3ec7eb32f30b90cd0fcf3657d388b5ff4297f2f9716ff66e9b69c05ddd09")
        with self.assertRaises(ValueError): snapshot.identity("http://bad", "5432", "restore_db", 22, "owner", "1")

    def test_restore_requires_valid_distinct_source_oid_and_no_output(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(snapshot.psycopg, "connect") as connect, patch.dict("os.environ", {"STAGE_B_DB_NAME":"restore_db","STAGE_B_DB_HOST":"db","STAGE_B_DB_PORT":"5432","STAGE_B_DB_USER":"u","STAGE_B_DB_PASSWORD":"p"}, clear=False):
            connect.return_value.__enter__.return_value = Connection(); target = Path(temp) / "result.json"
            for supplied in (None, "not-a-hash", snapshot.identity("db", "5432", "restore_db", 22, "owner", "160002")["oid_hash"]):
                argv=["snapshot", "--output", str(target), "--identity-mode", "restore"] + ([] if supplied is None else ["--expected-source-oid-hash", supplied])
                with patch("sys.argv", argv):
                    with self.assertRaises(SystemExit): snapshot.main()
                self.assertFalse(target.exists())

    def test_snapshot_is_privacy_safe(self):
        data = snapshot.snapshot(Connection(), "db.example.", "5432")
        self.assertNotIn("restore_db", str(data)); self.assertTrue(data["empty_proof"]["is_empty"])

if __name__ == "__main__": unittest.main()
