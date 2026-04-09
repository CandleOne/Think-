import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'lifeoptimization.db')

# Remove old DB if exists for clean build
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
conn.execute('PRAGMA foreign_keys = ON')

# Run schema
schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
with open(schema_path, 'r') as f:
    conn.executescript(f.read())
print('Schema created.')

# Run seed
seed_path = os.path.join(os.path.dirname(__file__), 'seed.sql')
with open(seed_path, 'r') as f:
    conn.executescript(f.read())
print('Data seeded.')

# Verify
cur = conn.cursor()
tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print(f'\nTables: {[t[0] for t in tables]}')

for table in tables:
    count = cur.execute(f'SELECT COUNT(*) FROM [{table[0]}]').fetchone()[0]
    print(f'  {table[0]}: {count} rows')

print('\nViews:')
views = cur.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
for v in views:
    print(f'  {v[0]}')

# Show all purchases view
print('\n--- All Items (v_all_purchases) ---')
rows = cur.execute("SELECT item_type, name, status_color, category FROM v_all_purchases").fetchall()
for r in rows:
    print(f'  [{r[0]}] {r[1]} | Status: {r[2]} | Category: {r[3]}')

conn.close()
print(f'\nDatabase created: {db_path}')
