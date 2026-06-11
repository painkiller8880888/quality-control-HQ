import sqlite3
conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print("Tables:", tables)
for t in tables:
    if 'machine' in t[0].lower():
        c.execute(f"PRAGMA table_info({t[0]})")
        print(f"\n{t[0]} columns:", c.fetchall())
