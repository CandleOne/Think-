-- LifeOptimization Database Schema
-- Status colors: green=currently_have, blue=next_purchase, orange=eventual_purchase, red=needs_replacing

PRAGMA foreign_keys = ON;

-- ============================================================
-- CORE TABLES
-- ============================================================

-- Life areas: Academic, Career, Hobbies, Fitness, Appearance
CREATE TABLE IF NOT EXISTS life_areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Status tracking for items
-- green = Currently Have | blue = Next Purchase | orange = Eventual Purchase | red = Needs Replacing/Refilling
CREATE TABLE IF NOT EXISTS statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL,
    description TEXT
);

-- ============================================================
-- APPEARANCE: FASHION
-- ============================================================

-- Fashion sub-categories: Hats, Tops, Bottoms, Shoes, Accessories
CREATE TABLE IF NOT EXISTS fashion_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fashion_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES fashion_categories(id),
    name TEXT NOT NULL,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    link TEXT,
    rep_link TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- APPEARANCE: SKINCARE
-- ============================================================

-- Skincare routines: Morning (Face), Morning (Body), Night
CREATE TABLE IF NOT EXISTS skincare_routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS skincare_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER REFERENCES skincare_routines(id),
    name TEXT NOT NULL,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    link TEXT,
    step_order INTEGER DEFAULT 0,
    is_wanted INTEGER DEFAULT 0,  -- 1 if in "Wanted Products" list
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- APPEARANCE: PHARMACOLOGY
-- ============================================================

CREATE TABLE IF NOT EXISTS pharmacology_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    dosage TEXT,
    frequency TEXT,
    link TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- GOALS & TASKS (Academic, Career, Hobbies, Fitness)
-- ============================================================

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    life_area_id INTEGER NOT NULL REFERENCES life_areas(id),
    title TEXT NOT NULL,
    description TEXT,
    target_date TEXT,
    is_completed INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,  -- 0=low, 1=medium, 2=high
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER REFERENCES goals(id),
    life_area_id INTEGER NOT NULL REFERENCES life_areas(id),
    title TEXT NOT NULL,
    description TEXT,
    is_completed INTEGER DEFAULT 0,
    due_date TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- MISCELLANEOUS ITEMS (catch-all for anything else)
-- ============================================================

CREATE TABLE IF NOT EXISTS misc_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    life_area_id INTEGER REFERENCES life_areas(id),
    name TEXT NOT NULL,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    category TEXT,  -- free-form sub-category
    link TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- SIDEBAR SECTIONS (dynamic navigation)
-- ============================================================

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

-- ============================================================
-- CUSTOM SECTION ITEMS (items for user-created sections)
-- ============================================================

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
    objective_completed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- PURCHASES / WISHLIST (unified view across fashion, skincare, etc.)
-- ============================================================

CREATE VIEW IF NOT EXISTS v_all_purchases AS
SELECT 'fashion' AS item_type, f.name, s.color AS status_color, s.description AS status_desc, 
       fc.name AS category, f.link, f.rep_link, f.notes, f.created_at
FROM fashion_items f
JOIN statuses s ON f.status_id = s.id
JOIN fashion_categories fc ON f.category_id = fc.id

UNION ALL

SELECT 'skincare' AS item_type, sp.name, s.color AS status_color, s.description AS status_desc,
       sr.name AS category, sp.link, NULL AS rep_link, sp.notes, sp.created_at
FROM skincare_products sp
JOIN statuses s ON sp.status_id = s.id
LEFT JOIN skincare_routines sr ON sp.routine_id = sr.id

UNION ALL

SELECT 'pharmacology' AS item_type, p.name, s.color AS status_color, s.description AS status_desc,
       NULL AS category, p.link, NULL AS rep_link, p.notes, p.created_at
FROM pharmacology_items p
JOIN statuses s ON p.status_id = s.id

UNION ALL

SELECT 'misc' AS item_type, m.name, s.color AS status_color, s.description AS status_desc,
       m.category, m.link, NULL AS rep_link, m.notes, m.created_at
FROM misc_items m
JOIN statuses s ON m.status_id = s.id;
