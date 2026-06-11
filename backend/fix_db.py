import sqlite3
conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# Add missing columns to quality_machine
columns_to_add = [
    ("shape_type", "varchar(16) NOT NULL DEFAULT 'rectangle'"),
    ("map_x", "float NOT NULL DEFAULT 0"),
    ("map_y", "float NOT NULL DEFAULT 0"),
    ("width", "float NOT NULL DEFAULT 100"),
    ("height", "float NOT NULL DEFAULT 100"),
]

for col_name, col_def in columns_to_add:
    try:
        c.execute(f"ALTER TABLE quality_machine ADD COLUMN {col_name} {col_def}")
        print(f"Added {col_name}")
    except sqlite3.OperationalError as e:
        print(f"Skip {col_name}: {e}")

# Remove extra columns (SQLite doesn't support DROP COLUMN directly, need to recreate table)
# But for now, we can leave them as they don't hurt

conn.commit()
print("Done")
c.execute("PRAGMA table_info(quality_machine)")
print("New columns:", c.fetchall())
