import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.db import connection

django.setup()

with connection.cursor() as cursor:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """
    )
    tables = [row[0] for row in cursor.fetchall()]

print("Tables:", tables)

for table in tables:
    if "machine" not in table.lower():
        continue
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            [table],
        )
        print(f"\n{table} columns:", cursor.fetchall())
