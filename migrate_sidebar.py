import sqlite3
import os

db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lifeoptimization.db')
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA foreign_keys = ON')

conn.executescript("""
CREATE TABLE IF NOT EXISTS sidebar_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL,
    label TEXT NOT NULL,
    page_key TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    is_builtin INTEGER DEFAULT 0,
    is_schedule INTEGER DEFAULT 0,
    is_long_term_section INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS custom_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section_key TEXT NOT NULL,
    name TEXT NOT NULL,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    link TEXT,
    notes TEXT,
    sort_order INTEGER DEFAULT 0,
    is_task INTEGER DEFAULT 0,
    task_time TEXT,
    task_count INTEGER,
    task_interval TEXT,
    subgroup TEXT,
    is_quick_objective INTEGER DEFAULT 0,
    is_long_term_objective INTEGER DEFAULT 0,
    is_goal INTEGER DEFAULT 0,
    objective_completed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO sidebar_sections (group_name, label, page_key, sort_order, is_builtin) VALUES
    ('Overview', 'Dashboard', 'dashboard', 1, 1),
    ('Overview', 'All Purchases', 'purchases', 2, 1),
    ('Appearance', 'Fashion', 'fashion', 10, 1),
    ('Appearance', 'Skincare', 'skincare', 11, 1),
    ('Appearance', 'Pharmacology', 'pharmacology', 12, 1),
    ('Life Areas', 'Goals', 'goals', 20, 1),
    ('Goals', 'Goal Archive', 'goal_archive', 21, 1),
    ('AI', 'AI Interface', 'ai_interface', 30, 1);
""")
conn.commit()

# Ensure is_schedule and is_long_term_section columns exist on older DBs
for col, default in [('is_schedule', 0), ('is_long_term_section', 0)]:
    try:
        conn.execute(f'ALTER TABLE sidebar_sections ADD COLUMN {col} INTEGER DEFAULT {default}')
        conn.commit()
        print(f'  Added column sidebar_sections.{col}')
    except sqlite3.OperationalError:
        pass  # column already exists

for col, default in [('is_task', 0), ('task_time', 'NULL'), ('task_count', 'NULL'),
                      ('task_interval', 'NULL'), ('subgroup', 'NULL'),
                      ('is_quick_objective', 0), ('is_long_term_objective', 0),
                      ('is_goal', 0), ('objective_completed', 0)]:
    try:
        coltype = 'TEXT' if default == 'NULL' else 'INTEGER'
        conn.execute(f'ALTER TABLE custom_items ADD COLUMN {col} {coltype} DEFAULT {default}')
        conn.commit()
        print(f'  Added column custom_items.{col}')
    except sqlite3.OperationalError:
        pass  # column already exists

rows = conn.execute('SELECT * FROM sidebar_sections ORDER BY sort_order').fetchall()
for r in rows:
    print(r)
conn.close()
print('Done')
