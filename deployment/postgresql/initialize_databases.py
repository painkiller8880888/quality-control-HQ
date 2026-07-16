import argparse
import os
import re
from pathlib import Path

import psycopg
from psycopg import sql


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def load_env_file(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def required(name):
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("replace-with-"):
        raise SystemExit(f"Set {name} in the bootstrap environment file.")
    return value


def safe_name(name):
    value = required(name)
    if not NAME_PATTERN.fullmatch(value):
        raise SystemExit(f"{name} must be a lowercase PostgreSQL identifier.")
    return value


def ensure_role(connection, role_name, password):
    exists = connection.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,)
    ).fetchone()
    if not exists:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role_name), sql.Literal(password)
            )
        )
    connection.execute(
        sql.SQL(
            "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )


def ensure_database(connection, database_name, owner_name):
    existing_owner = connection.execute(
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
        (database_name,),
    ).fetchone()
    if existing_owner:
        if existing_owner[0] != owner_name:
            raise SystemExit(
                f"Database {database_name} already exists with another owner."
            )
        return
    connection.execute(
        sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(database_name), sql.Identifier(owner_name)
        )
    )


def grant_runtime_permissions(connection, database_name, owner_name, app_name):
    connection.execute(
        sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
            sql.Identifier(database_name)
        )
    )
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database_name), sql.Identifier(owner_name)
        )
    )
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database_name), sql.Identifier(app_name)
        )
    )
    connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
            sql.Identifier(app_name)
        )
    )
    connection.execute(
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
        ).format(sql.Identifier(app_name))
    )
    connection.execute(
        sql.SQL(
            "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}"
        ).format(sql.Identifier(app_name))
    )
    connection.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(sql.Identifier(owner_name), sql.Identifier(app_name))
    )
    connection.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}"
        ).format(sql.Identifier(owner_name), sql.Identifier(app_name))
    )


def main():
    parser = argparse.ArgumentParser(
        description="Create isolated development and pseudoproduction databases."
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument(
        "--pseudoprod-only",
        action="store_true",
        help="Keep the existing development database unchanged.",
    )
    args = parser.parse_args()
    load_env_file(args.env_file.resolve())

    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    admin_user = safe_name("POSTGRES_ADMIN_USER")
    admin_password = required("POSTGRES_ADMIN_PASSWORD")

    environments = [
        {
            "database": safe_name("PSEUDOPROD_DB_NAME"),
            "app_user": safe_name("PSEUDOPROD_DB_USER"),
            "app_password": required("PSEUDOPROD_DB_PASSWORD"),
            "owner": safe_name("PSEUDOPROD_MIGRATION_USER"),
            "owner_password": required("PSEUDOPROD_MIGRATION_PASSWORD"),
        }
    ]
    if not args.pseudoprod_only:
        environments.append(
            {
            "database": safe_name("DEV_DB_NAME"),
            "app_user": safe_name("DEV_DB_USER"),
            "app_password": required("DEV_DB_PASSWORD"),
            "owner": safe_name("DEV_MIGRATION_USER"),
            "owner_password": required("DEV_MIGRATION_PASSWORD"),
            }
        )

    admin_connection = psycopg.connect(
        host=host,
        port=port,
        dbname="postgres",
        user=admin_user,
        password=admin_password,
        autocommit=True,
    )
    try:
        for environment in environments:
            ensure_role(
                admin_connection,
                environment["owner"],
                environment["owner_password"],
            )
            ensure_role(
                admin_connection,
                environment["app_user"],
                environment["app_password"],
            )
            ensure_database(
                admin_connection, environment["database"], environment["owner"]
            )
    finally:
        admin_connection.close()

    for environment in environments:
        connection = psycopg.connect(
            host=host,
            port=port,
            dbname=environment["database"],
            user=admin_user,
            password=admin_password,
            autocommit=True,
        )
        try:
            grant_runtime_permissions(
                connection,
                environment["database"],
                environment["owner"],
                environment["app_user"],
            )
        finally:
            connection.close()

    if args.pseudoprod_only:
        print("Pseudoproduction database is isolated and ready.")
    else:
        print("Development and pseudoproduction databases are isolated and ready.")


if __name__ == "__main__":
    main()
