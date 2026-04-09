import sqlite3

conn = sqlite3.connect('lifeoptimization.db')
conn.execute('PRAGMA foreign_keys = ON')

conn.executescript("""
CREATE TABLE IF NOT EXISTS sidebar_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL,
    label TEXT NOT NULL,
    page_key TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    is_builtin INTEGER DEFAULT 0,
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
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO sidebar_sections (group_name, label, page_key, sort_order, is_builtin) VALUES
    ('Overview', 'Dashboard', 'dashboard', 1, 1),
    ('Overview', 'All Purchases', 'purchases', 2, 1),
    ('Appearance', 'Fashion', 'fashion', 10, 1),
    ('Appearance', 'Skincare', 'skincare', 11, 1),
    ('Appearance', 'Pharmacology', 'pharmacology', 12, 1),
    ('Life Areas', 'Goals', 'goals', 20, 1);
""")
conn.commit()

rows = conn.execute('SELECT * FROM sidebar_sections ORDER BY sort_order').fetchall()
for r in rows:
    print(r)
conn.close()
print('Done')
