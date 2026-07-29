"""Read-only, privacy-safe PostgreSQL snapshot helper for Stage B."""
import argparse
import datetime as dt
import decimal
import hashlib
import json
import math
import os
import re
from pathlib import Path

import psycopg

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _scalar(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite scalar")
        return decimal.Decimal(str(value))
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            raise ValueError("non-finite scalar")
        return value
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                raise ValueError("naive timestamp")
            value = value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            value = value.isoformat()
        return value
    raise ValueError("unsupported scalar")


def _canonical(value):
    if isinstance(value, dict):
        return {str(k): _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    value = _scalar(value)
    if isinstance(value, decimal.Decimal):
        return format(value.normalize(), "f")
    return value


def canonical_json_bytes(value):
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def write_json(path, value):
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit("required protected connection setting is missing")
    return value


def normalized_host(value):
    value = value.strip().lower().rstrip(".")
    if not value or any(c.isspace() for c in value) or any(c in value for c in ":/@\\\\"):
        raise ValueError("invalid host")
    return value


def normalized_port(value):
    if not re.fullmatch(r"[0-9]+", str(value).strip()):
        raise ValueError("invalid port")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return str(port)


def identity(host, port, database, oid, role, server_version_num):
    host, port, database = normalized_host(host), normalized_port(port), database.lower()
    if not IDENTIFIER.fullmatch(database):
        raise ValueError("invalid database")
    return {"host_hash": digest(host), "port_hash": digest(port), "endpoint_hash": digest(host + "\n" + port), "database_hash": digest(database), "oid_hash": digest(oid), "role_hash": digest(role), "server_version_num_hash": digest(server_version_num)}


def rows_hash(rows, columns):
    ordered = [[_scalar(row[index]) for index, _ in enumerate(columns)] for row in rows]
    return {"count": len(ordered), "stable_hash": digest(ordered)}


def scalar_hash(connection, query):
    cursor = connection.execute(query)
    return rows_hash(cursor.fetchall(), [item.name for item in cursor.description])


def snapshot(connection, host, port):
    database, oid, role = connection.execute("SELECT current_database(), oid, pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()").fetchone()
    version = connection.execute("SHOW server_version_num").fetchone()[0]
    objects = connection.execute("SELECT c.relkind,count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','v','m','S','f') GROUP BY c.relkind ORDER BY c.relkind").fetchall()
    migrations = connection.execute("SELECT to_regclass('public.django_migrations') IS NOT NULL").fetchone()[0]
    inventory_cursor = connection.execute("SELECT c.relkind,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relkind,c.relname")
    inventory = inventory_cursor.fetchall()
    result = {"identity": identity(host, port, database, oid, role, version), "empty_proof": {"object_counts": dict(objects), "django_migrations_present": bool(migrations), "is_empty": not objects and not migrations}, "schema_inventory": rows_hash(inventory, [item.name for item in inventory_cursor.description]), "migrations": scalar_hash(connection, "SELECT app,name FROM django_migrations ORDER BY app,name") if migrations else {"count": 0, "stable_hash": digest([])}}
    for table in ("quality_master", "quality_masterclass", "quality_structure", "quality_inspectionfile", "quality_appsetting"):
        exists = connection.execute("SELECT to_regclass(%s)", ("public." + table,)).fetchone()[0]
        result[table] = scalar_hash(connection, "SELECT * FROM " + table + " ORDER BY id") if exists else {"count": 0, "stable_hash": digest([])}
    paths = connection.execute("SELECT file_path FROM quality_inspectionfile WHERE file_path IS NOT NULL ORDER BY file_path").fetchall() if result["quality_inspectionfile"]["count"] else []
    result["inspection_file_path_set_hash"] = digest(sorted({row[0] for row in paths}))
    return result


def main():
    parser = argparse.ArgumentParser(description="Stage B privacy-safe read-only snapshot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity-mode", choices=("source", "restore"), required=True)
    parser.add_argument("--expected-distinct-oid-hash")
    args = parser.parse_args()
    if args.identity_mode == "restore" and not args.expected_distinct_oid_hash:
        raise SystemExit("restore snapshot requires expected distinct OID hash")
    if args.identity_mode == "source" and args.expected_distinct_oid_hash:
        raise SystemExit("source snapshot cannot accept expected distinct OID hash")
    name, host, port = required("STAGE_B_DB_NAME"), required("STAGE_B_DB_HOST"), required("STAGE_B_DB_PORT")
    if not IDENTIFIER.fullmatch(name):
        raise SystemExit("database identifier must be lowercase PostgreSQL identifier")
    try:
        with psycopg.connect(host=host, port=port, dbname=name, user=required("STAGE_B_DB_USER"), password=required("STAGE_B_DB_PASSWORD"), options="-c default_transaction_read_only=on") as connection:
            result = snapshot(connection, host, port)
    except SystemExit:
        raise
    except Exception:
        raise SystemExit("read-only snapshot failed")
    if args.identity_mode == "restore" and result["identity"]["oid_hash"] == args.expected_distinct_oid_hash:
        raise SystemExit("restore identity is not distinct")
    write_json(args.output, result)


if __name__ == "__main__":
    main()
