"""
LifeOptimization Web App
Flask backend serving API + frontend for managing the life optimization database.
"""
import sqlite3
import os
from datetime import date
from flask import Flask, request, jsonify, send_from_directory


def load_local_env(env_path='.env'):
    """Load KEY=VALUE pairs from a local .env file without external dependencies."""
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                os.environ.setdefault(key, value)
    except OSError:
        # If .env cannot be read, continue with process environment only.
        pass


load_local_env()

import re

from ai_brain import optimize_schedule, build_routine_plan, apply_schedule_updates, get_ai_runtime_info, query_ai, query_ai_empowered, analyze_goals, build_today_plan, research_and_create_goals, web_search


def parse_lto_sessions(name, notes):
    """Extract the number of study sessions/days required from LTO name and notes.

    Returns an integer >= 1.
    """
    if not notes:
        notes = ''
    # Pattern 1: "3 days / 4.5h"  or  "1 review day / 1.5h"
    m = re.search(r'(\d+)\s+(?:review\s+)?days?\s*[/·]', notes)
    if m:
        return int(m.group(1))
    # Pattern 2: Count explicit "Day N" labels in notes (e.g. "Day 1 ... Day 2 ... Day 7")
    day_labels = re.findall(r'\bDay\s+(\d+)\b', notes)
    if len(day_labels) >= 2:
        return len(set(day_labels))
    # Pattern 3: Name has "Weeks X-Y" or "Week X-Y" → weeks * 5 working days
    m = re.search(r'Weeks?\s+(\d+)\s*[-–]\s*(\d+)', name)
    if m:
        weeks = int(m.group(2)) - int(m.group(1)) + 1
        return max(1, weeks * 5)
    # Pattern 4: Parse total hours from notes — "Prep 40-60h" or "~100h" → hours / 1.5
    m = re.search(r'(?:Prep|Add|~)\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*h', notes, re.IGNORECASE)
    if m:
        hours = int(m.group(2) or m.group(1))  # use upper bound
        return max(1, round(hours / 1.5))
    # Pattern 5: Checkpoint or single session
    if name and re.search(r'checkpoint|review sprint', name, re.IGNORECASE):
        return 1
    return 1

app = Flask(__name__, static_folder='static')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lifeoptimization.db')


def ensure_schema_compatibility():
    """Apply lightweight, idempotent schema updates for older local databases."""
    if not os.path.exists(DB_PATH):
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(custom_items)").fetchall()}
        if 'is_long_term_objective' not in columns:
            conn.execute('ALTER TABLE custom_items ADD COLUMN is_long_term_objective INTEGER DEFAULT 0')
        if 'objective_completed' not in columns:
            conn.execute('ALTER TABLE custom_items ADD COLUMN objective_completed INTEGER DEFAULT 0')
        if 'is_goal' not in columns:
            conn.execute('ALTER TABLE custom_items ADD COLUMN is_goal INTEGER DEFAULT 0')
        if 'sessions_completed' not in columns:
            conn.execute('ALTER TABLE custom_items ADD COLUMN sessions_completed INTEGER DEFAULT 0')

        sidebar_columns = {row[1] for row in conn.execute("PRAGMA table_info(sidebar_sections)").fetchall()}
        if 'is_long_term_section' not in sidebar_columns:
            conn.execute('ALTER TABLE sidebar_sections ADD COLUMN is_long_term_section INTEGER DEFAULT 0')

        ai_section = conn.execute(
            "SELECT id FROM sidebar_sections WHERE page_key='ai_interface'"
        ).fetchone()
        if not ai_section:
            max_order = conn.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
            conn.execute(
                """
                INSERT INTO sidebar_sections (
                    group_name, label, page_key, sort_order, is_builtin, is_schedule, is_long_term_section
                ) VALUES ('AI', 'AI Interface', 'ai_interface', ?, 1, 0, 0)
                """,
                (max_order + 1,),
            )

        archive_section = conn.execute(
            "SELECT id FROM sidebar_sections WHERE page_key='goal_archive'"
        ).fetchone()
        if not archive_section:
            max_order = conn.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
            conn.execute(
                """
                INSERT INTO sidebar_sections (
                    group_name, label, page_key, sort_order, is_builtin, is_schedule, is_long_term_section
                ) VALUES ('Goals', 'Goal Archive', 'goal_archive', ?, 1, 0, 0)
                """,
                (max_order + 1,),
            )

        tasks_section = conn.execute(
            "SELECT id FROM sidebar_sections WHERE page_key='tasks'"
        ).fetchone()
        if not tasks_section:
            max_order = conn.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
            conn.execute(
                """
                INSERT INTO sidebar_sections (
                    group_name, label, page_key, sort_order, is_builtin, is_schedule, is_long_term_section
                ) VALUES ('Life Areas', 'Tasks', 'tasks', ?, 1, 0, 0)
                """,
                (max_order + 1,),
            )

        misc_section = conn.execute(
            "SELECT id FROM sidebar_sections WHERE page_key='misc'"
        ).fetchone()
        if not misc_section:
            max_order = conn.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
            conn.execute(
                """
                INSERT INTO sidebar_sections (
                    group_name, label, page_key, sort_order, is_builtin, is_schedule, is_long_term_section
                ) VALUES ('Overview', 'Misc Items', 'misc', ?, 1, 0, 0)
                """,
                (max_order + 1,),
            )

        # For existing Financial Theory data, ensure section is marked long-term.
        conn.execute('''
            UPDATE sidebar_sections
            SET is_long_term_section = 1
            WHERE page_key = 'custom_financial_theory'
              AND COALESCE(is_long_term_section, 0) = 0
        ''')
        conn.execute('''
            UPDATE custom_items
            SET is_goal = 1
            WHERE COALESCE(is_goal, 0) = 0
              AND (COALESCE(is_task, 0) = 1 OR COALESCE(is_long_term_objective, 0) = 1)
        ''')

        goal_columns = {row[1] for row in conn.execute("PRAGMA table_info(goals)").fetchall()}
        _GOAL_MIGRATIONS = [
            ('difficulty', 'INTEGER'),
            ('time_commitment_hours', 'REAL'),
            ('price_estimate', 'REAL'),
            ('ai_priority_score', 'INTEGER'),
            ('ai_reasoning', 'TEXT'),
        ]
        _VALID_COLTYPES = {'INTEGER', 'REAL', 'TEXT', 'BLOB'}
        for col, coltype in _GOAL_MIGRATIONS:
            if col not in goal_columns:
                # col/coltype are from the hardcoded list above; validate as extra safety.
                assert coltype in _VALID_COLTYPES and col.isidentifier()
                conn.execute(f'ALTER TABLE goals ADD COLUMN {col} {coltype}')

        conn.commit()
    except sqlite3.OperationalError:
        # Database may not be initialized yet; init scripts can create full schema.
        pass
    finally:
        conn.close()


ensure_schema_compatibility()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


def parse_iso_date(value):
    """Parse a YYYY-MM-DD string into a date; return None on invalid values."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def api_error(message, status=400):
    return jsonify({'error': message}), status


def get_json_payload(required_fields=None):
    if not request.is_json:
        return None, api_error('Expected application/json request body', 400)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, api_error('Invalid JSON body', 400)
    if required_fields:
        missing = [field for field in required_fields if field not in data]
        if missing:
            return None, api_error(f"Missing required fields: {', '.join(missing)}", 400)
    return data, None


def normalize_fashion_payload(data):
    try:
        category_id = int(data['category_id'])
        status_id = int(data['status_id'])
    except (TypeError, ValueError):
        return None, api_error('category_id and status_id must be integers', 400)

    name = str(data.get('name', '')).strip()
    if not name:
        return None, api_error('name is required', 400)

    normalized = {
        'category_id': category_id,
        'name': name,
        'status_id': status_id,
        'link': data.get('link'),
        'rep_link': data.get('rep_link'),
        'notes': data.get('notes')
    }
    return normalized, None


def normalize_skincare_payload(data):
    try:
        status_id = int(data['status_id'])
        step_order = int(data.get('step_order', 0) or 0)
        is_wanted = int(data.get('is_wanted', 0) or 0)
    except (TypeError, ValueError):
        return None, api_error('status_id, step_order, and is_wanted must be integers', 400)

    routine_id = data.get('routine_id')
    if routine_id in ('', None):
        routine_id = None
    else:
        try:
            routine_id = int(routine_id)
        except (TypeError, ValueError):
            return None, api_error('routine_id must be an integer when provided', 400)

    name = str(data.get('name', '')).strip()
    if not name:
        return None, api_error('name is required', 400)

    return {
        'routine_id': routine_id,
        'name': name,
        'status_id': status_id,
        'step_order': step_order,
        'is_wanted': is_wanted,
        'link': data.get('link'),
        'notes': data.get('notes')
    }, None


def normalize_pharmacology_payload(data):
    try:
        status_id = int(data['status_id'])
    except (TypeError, ValueError):
        return None, api_error('status_id must be an integer', 400)

    name = str(data.get('name', '')).strip()
    if not name:
        return None, api_error('name is required', 400)

    return {
        'name': name,
        'status_id': status_id,
        'dosage': data.get('dosage'),
        'frequency': data.get('frequency'),
        'link': data.get('link'),
        'notes': data.get('notes')
    }, None


def normalize_goal_payload(data):
    try:
        life_area_id = int(data['life_area_id'])
        priority = int(data.get('priority', 0) or 0)
        is_completed = int(data.get('is_completed', 0) or 0)
    except (TypeError, ValueError):
        return None, api_error('life_area_id, priority, and is_completed must be integers', 400)

    title = str(data.get('title', '')).strip()
    if not title:
        return None, api_error('title is required', 400)

    return {
        'life_area_id': life_area_id,
        'title': title,
        'description': data.get('description'),
        'target_date': data.get('target_date'),
        'priority': priority,
        'is_completed': is_completed
    }, None


def normalize_task_payload(data):
    try:
        life_area_id = int(data['life_area_id'])
        is_completed = int(data.get('is_completed', 0) or 0)
    except (TypeError, ValueError):
        return None, api_error('life_area_id and is_completed must be integers', 400)

    goal_id = data.get('goal_id')
    if goal_id in ('', None):
        goal_id = None
    else:
        try:
            goal_id = int(goal_id)
        except (TypeError, ValueError):
            return None, api_error('goal_id must be an integer when provided', 400)

    title = str(data.get('title', '')).strip()
    if not title:
        return None, api_error('title is required', 400)

    return {
        'goal_id': goal_id,
        'life_area_id': life_area_id,
        'title': title,
        'description': data.get('description'),
        'is_completed': is_completed,
        'due_date': data.get('due_date'),
    }, None


def normalize_misc_payload(data):
    try:
        status_id = int(data['status_id'])
    except (TypeError, ValueError):
        return None, api_error('status_id must be an integer', 400)

    life_area_id = data.get('life_area_id')
    if life_area_id in ('', None):
        life_area_id = None
    else:
        try:
            life_area_id = int(life_area_id)
        except (TypeError, ValueError):
            return None, api_error('life_area_id must be an integer when provided', 400)

    name = str(data.get('name', '')).strip()
    if not name:
        return None, api_error('name is required', 400)

    return {
        'life_area_id': life_area_id,
        'name': name,
        'status_id': status_id,
        'category': data.get('category'),
        'link': data.get('link'),
        'notes': data.get('notes'),
    }, None


def normalize_custom_payload(data):
    try:
        status_id = int(data['status_id'])
        sort_order = int(data.get('sort_order', 0) or 0)
        is_task = int(data.get('is_task', 0) or 0)
        is_quick_objective = int(data.get('is_quick_objective', 0) or 0)
        is_long_term_objective = int(data.get('is_long_term_objective', 0) or 0)
        is_goal = int(data.get('is_goal', 0) or 0)
    except (TypeError, ValueError):
        return None, api_error('status_id, sort_order, is_task, is_quick_objective, is_long_term_objective, and is_goal must be integers', 400)

    task_count = data.get('task_count')
    if task_count in ('', None):
        task_count = None
    else:
        try:
            task_count = int(task_count)
        except (TypeError, ValueError):
            return None, api_error('task_count must be an integer when provided', 400)

    name = str(data.get('name', '')).strip()
    if not name:
        return None, api_error('name is required', 400)

    return {
        'name': name,
        'status_id': status_id,
        'link': data.get('link'),
        'notes': data.get('notes'),
        'sort_order': sort_order,
        'is_task': is_task,
        'task_time': data.get('task_time'),
        'task_count': task_count,
        'task_interval': data.get('task_interval'),
        'subgroup': data.get('subgroup'),
        'is_quick_objective': is_quick_objective,
        'is_long_term_objective': is_long_term_objective,
        'is_goal': 1 if (is_goal or is_task or is_long_term_objective) else 0,
    }, None


# ── Static files ──────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ── Statuses ──────────────────────────────────────────────

@app.route('/api/statuses')
def get_statuses():
    db = get_db()
    rows = db.execute('SELECT * FROM statuses').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


# ── Life Areas ────────────────────────────────────────────

@app.route('/api/life-areas')
def get_life_areas():
    db = get_db()
    rows = db.execute('SELECT * FROM life_areas ORDER BY sort_order').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


# ── Fashion ───────────────────────────────────────────────

@app.route('/api/fashion/categories')
def get_fashion_categories():
    db = get_db()
    rows = db.execute('SELECT * FROM fashion_categories ORDER BY sort_order').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/fashion', methods=['GET'])
def get_fashion_items():
    db = get_db()
    rows = db.execute('''
        SELECT f.*, fc.name as category_name, s.color as status_color, s.name as status_name
        FROM fashion_items f
        JOIN fashion_categories fc ON f.category_id = fc.id
        JOIN statuses s ON f.status_id = s.id
        ORDER BY fc.sort_order, f.name
    ''').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/fashion', methods=['POST'])
def add_fashion_item():
    data, error = get_json_payload(required_fields=['category_id', 'name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_fashion_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        db.execute(
            'INSERT INTO fashion_items (category_id, name, status_id, link, rep_link, notes) VALUES (?,?,?,?,?,?)',
            (normalized['category_id'], normalized['name'], normalized['status_id'],
             normalized['link'], normalized['rep_link'], normalized['notes']))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fashion/<int:item_id>', methods=['PUT'])
def update_fashion_item(item_id):
    data, error = get_json_payload(required_fields=['category_id', 'name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_fashion_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        cur = db.execute('''UPDATE fashion_items 
                            SET category_id=?, name=?, status_id=?, link=?, rep_link=?, notes=?, updated_at=datetime('now')
                            WHERE id=?''',
                         (normalized['category_id'], normalized['name'], normalized['status_id'],
                          normalized['link'], normalized['rep_link'], normalized['notes'], item_id))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Fashion item not found', 404)
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/fashion/<int:item_id>', methods=['DELETE'])
def delete_fashion_item(item_id):
    db = get_db()
    try:
        cur = db.execute('DELETE FROM fashion_items WHERE id=?', (item_id,))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Fashion item not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


# ── Skincare ──────────────────────────────────────────────

@app.route('/api/skincare/routines')
def get_skincare_routines():
    db = get_db()
    rows = db.execute('SELECT * FROM skincare_routines ORDER BY sort_order').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/skincare/routines', methods=['POST'])
def add_skincare_routine():
    data, error = get_json_payload(required_fields=['name'])
    if error:
        return error
    name = data.get('name', '').strip()
    if not name:
        return api_error('name required', 400)
    db = get_db()
    try:
        existing = db.execute('SELECT id FROM skincare_routines WHERE name=?', (name,)).fetchone()
        if existing:
            return api_error('Routine already exists', 409)
        max_order = db.execute('SELECT MAX(sort_order) FROM skincare_routines').fetchone()[0] or 0
        db.execute('INSERT INTO skincare_routines (name, sort_order) VALUES (?,?)', (name, max_order + 1))
        db.commit()
        new_id = db.execute('SELECT id FROM skincare_routines WHERE name=?', (name,)).fetchone()['id']
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True, 'id': new_id}), 201


@app.route('/api/skincare/routines/<int:routine_id>', methods=['DELETE'])
def delete_skincare_routine(routine_id):
    db = get_db()
    try:
        routine = db.execute('SELECT id FROM skincare_routines WHERE id=?', (routine_id,)).fetchone()
        if not routine:
            return api_error('Skincare routine not found', 404)
        # Move products from this routine to "wanted" (unassigned)
        db.execute('UPDATE skincare_products SET routine_id=NULL, is_wanted=1 WHERE routine_id=?', (routine_id,))
        db.execute('DELETE FROM skincare_routines WHERE id=?', (routine_id,))
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/skincare', methods=['GET'])
def get_skincare_products():
    db = get_db()
    rows = db.execute('''
        SELECT sp.*, sr.name as routine_name, s.color as status_color, s.name as status_name
        FROM skincare_products sp
        LEFT JOIN skincare_routines sr ON sp.routine_id = sr.id
        JOIN statuses s ON sp.status_id = s.id
        ORDER BY sp.is_wanted, sr.sort_order, sp.step_order
    ''').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/skincare', methods=['POST'])
def add_skincare_product():
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_skincare_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        db.execute(
            'INSERT INTO skincare_products (routine_id, name, status_id, step_order, is_wanted, link, notes) VALUES (?,?,?,?,?,?,?)',
            (normalized['routine_id'], normalized['name'], normalized['status_id'],
             normalized['step_order'], normalized['is_wanted'],
             normalized['link'], normalized['notes']))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/skincare/<int:item_id>', methods=['PUT'])
def update_skincare_product(item_id):
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_skincare_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        cur = db.execute('''UPDATE skincare_products 
                            SET routine_id=?, name=?, status_id=?, step_order=?, is_wanted=?, link=?, notes=?, updated_at=datetime('now')
                            WHERE id=?''',
                         (normalized['routine_id'], normalized['name'], normalized['status_id'],
                          normalized['step_order'], normalized['is_wanted'],
                          normalized['link'], normalized['notes'], item_id))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Skincare product not found', 404)
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/skincare/<int:item_id>', methods=['DELETE'])
def delete_skincare_product(item_id):
    db = get_db()
    try:
        cur = db.execute('DELETE FROM skincare_products WHERE id=?', (item_id,))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Skincare product not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


# ── Pharmacology ──────────────────────────────────────────

@app.route('/api/pharmacology', methods=['GET'])
def get_pharmacology():
    db = get_db()
    rows = db.execute('''
        SELECT p.*, s.color as status_color, s.name as status_name
        FROM pharmacology_items p
        JOIN statuses s ON p.status_id = s.id
        ORDER BY p.name
    ''').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/pharmacology', methods=['POST'])
def add_pharmacology():
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_pharmacology_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        db.execute(
            'INSERT INTO pharmacology_items (name, status_id, dosage, frequency, link, notes) VALUES (?,?,?,?,?,?)',
            (normalized['name'], normalized['status_id'], normalized['dosage'],
             normalized['frequency'], normalized['link'], normalized['notes']))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/pharmacology/<int:item_id>', methods=['PUT'])
def update_pharmacology(item_id):
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_pharmacology_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        cur = db.execute('''UPDATE pharmacology_items 
                            SET name=?, status_id=?, dosage=?, frequency=?, link=?, notes=?, updated_at=datetime('now')
                            WHERE id=?''',
                         (normalized['name'], normalized['status_id'], normalized['dosage'],
                          normalized['frequency'], normalized['link'], normalized['notes'], item_id))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Pharmacology item not found', 404)
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/pharmacology/<int:item_id>', methods=['DELETE'])
def delete_pharmacology(item_id):
    db = get_db()
    try:
        cur = db.execute('DELETE FROM pharmacology_items WHERE id=?', (item_id,))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Pharmacology item not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


# ── Goals ─────────────────────────────────────────────────

@app.route('/api/goals', methods=['GET'])
def get_goals():
    db = get_db()
    rows = db.execute('''
        SELECT g.*, la.name as area_name
        FROM goals g
        JOIN life_areas la ON g.life_area_id = la.id
        ORDER BY la.sort_order, g.priority DESC, g.title
    ''').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/goals', methods=['POST'])
def add_goal():
    data, error = get_json_payload(required_fields=['life_area_id', 'title'])
    if error:
        return error
    normalized, validation_error = normalize_goal_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        db.execute(
            'INSERT INTO goals (life_area_id, title, description, target_date, priority) VALUES (?,?,?,?,?)',
            (normalized['life_area_id'], normalized['title'], normalized['description'],
             normalized['target_date'], normalized['priority']))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/goals/<int:goal_id>', methods=['PUT'])
def update_goal(goal_id):
    data, error = get_json_payload(required_fields=['life_area_id', 'title'])
    if error:
        return error
    normalized, validation_error = normalize_goal_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        cur = db.execute('''UPDATE goals 
                            SET life_area_id=?, title=?, description=?, target_date=?, priority=?, is_completed=?, updated_at=datetime('now')
                            WHERE id=?''',
                         (normalized['life_area_id'], normalized['title'], normalized['description'],
                          normalized['target_date'], normalized['priority'],
                          normalized['is_completed'], goal_id))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Goal not found', 404)
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/goals/<int:goal_id>', methods=['DELETE'])
def delete_goal(goal_id):
    db = get_db()
    try:
        cur = db.execute('DELETE FROM goals WHERE id=?', (goal_id,))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Goal not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


# ── Tasks ─────────────────────────────────────────────────

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    db = get_db()
    rows = db.execute('''
        SELECT t.*, la.name as area_name, g.title as goal_title
        FROM tasks t
        JOIN life_areas la ON t.life_area_id = la.id
        LEFT JOIN goals g ON t.goal_id = g.id
        ORDER BY t.is_completed, t.due_date, t.title
    ''').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/tasks', methods=['POST'])
def add_task():
    data, error = get_json_payload(required_fields=['life_area_id', 'title'])
    if error:
        return error
    normalized, validation_error = normalize_task_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        db.execute(
            'INSERT INTO tasks (goal_id, life_area_id, title, description, is_completed, due_date) VALUES (?,?,?,?,?,?)',
            (normalized['goal_id'], normalized['life_area_id'], normalized['title'],
             normalized['description'], normalized['is_completed'], normalized['due_date']))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    data, error = get_json_payload(required_fields=['life_area_id', 'title'])
    if error:
        return error
    normalized, validation_error = normalize_task_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        cur = db.execute('''UPDATE tasks 
                            SET goal_id=?, life_area_id=?, title=?, description=?, is_completed=?, due_date=?, updated_at=datetime('now')
                            WHERE id=?''',
                         (normalized['goal_id'], normalized['life_area_id'], normalized['title'],
                          normalized['description'], normalized['is_completed'],
                          normalized['due_date'], task_id))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Task not found', 404)
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    db = get_db()
    try:
        cur = db.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Task not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


# ── Misc Items ────────────────────────────────────────────

@app.route('/api/misc', methods=['GET'])
def get_misc_items():
    db = get_db()
    rows = db.execute('''
        SELECT m.*, s.color as status_color, s.name as status_name, la.name as area_name
        FROM misc_items m
        JOIN statuses s ON m.status_id = s.id
        LEFT JOIN life_areas la ON m.life_area_id = la.id
        ORDER BY m.category, m.name
    ''').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/misc', methods=['POST'])
def add_misc_item():
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_misc_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        db.execute(
            'INSERT INTO misc_items (life_area_id, name, status_id, category, link, notes) VALUES (?,?,?,?,?,?)',
            (normalized['life_area_id'], normalized['name'], normalized['status_id'],
             normalized['category'], normalized['link'], normalized['notes']))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/misc/<int:item_id>', methods=['PUT'])
def update_misc_item(item_id):
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_misc_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        cur = db.execute('''UPDATE misc_items 
                            SET life_area_id=?, name=?, status_id=?, category=?, link=?, notes=?, updated_at=datetime('now')
                            WHERE id=?''',
                         (normalized['life_area_id'], normalized['name'], normalized['status_id'],
                          normalized['category'], normalized['link'], normalized['notes'], item_id))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Misc item not found', 404)
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/misc/<int:item_id>', methods=['DELETE'])
def delete_misc_item(item_id):
    db = get_db()
    try:
        cur = db.execute('DELETE FROM misc_items WHERE id=?', (item_id,))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Misc item not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/goals/archive', methods=['GET'])
def get_goals_archive():
    """Return all goal-like items (goals, tasks, long-term objectives) with term buckets."""
    from datetime import date as _date
    today = _date.today()
    db = get_db()

    goal_rows = rows_to_list(db.execute('''
        SELECT g.*, la.name as area_name
        FROM goals g
        JOIN life_areas la ON g.life_area_id = la.id
        ORDER BY la.sort_order, g.priority DESC, g.title
    ''').fetchall())

    task_rows = rows_to_list(db.execute('''
        SELECT
            t.id,
            t.title,
            t.description,
            t.due_date AS target_date,
            t.is_completed,
            1 AS priority,
            la.name AS area_name,
            NULL AS task_time,
            NULL AS task_interval
        FROM tasks t
        JOIN life_areas la ON t.life_area_id = la.id
        ORDER BY la.sort_order, t.title
    ''').fetchall())

    custom_rows = rows_to_list(db.execute('''
        SELECT
            ci.id,
            ci.name AS title,
            ci.notes AS description,
            NULL AS target_date,
            CASE
                WHEN COALESCE(ci.is_long_term_objective, 0) = 1 THEN COALESCE(ci.objective_completed, 0)
                WHEN s.color = 'green' THEN 1
                ELSE 0
            END AS is_completed,
            CASE
                WHEN COALESCE(ci.is_long_term_objective, 0) = 1 THEN 2
                WHEN COALESCE(ci.is_task, 0) = 1 THEN 1
                ELSE 0
            END AS priority,
            COALESCE(ss.label, ci.section_key) AS area_name,
            COALESCE(ss.is_schedule, 0) AS is_schedule_section,
            ci.task_time,
            ci.task_interval,
            ci.section_key,
            ci.sort_order,
            COALESCE(ci.is_task, 0) AS is_task,
            COALESCE(ci.is_long_term_objective, 0) AS is_long_term_objective,
            COALESCE(ci.is_goal, 0) AS is_goal
        FROM custom_items ci
        JOIN statuses s ON ci.status_id = s.id
        LEFT JOIN sidebar_sections ss ON ss.page_key = ci.section_key
        WHERE COALESCE(ci.is_goal, 0) = 1
           OR COALESCE(ci.is_task, 0) = 1
           OR COALESCE(ci.is_long_term_objective, 0) = 1
        ORDER BY ci.section_key, ci.sort_order, ci.name
    ''').fetchall())

    db.close()

    # Build LTO lock map: for each section, walk in sort_order;
    # once we hit the first incomplete LTO, everything after it is locked.
    lto_locked = set()  # set of item ids that are locked
    sections_lto = {}  # section_key -> list of (id, is_completed) in order
    for row in custom_rows:
        if int(row.get('is_long_term_objective') or 0) != 1:
            continue
        sk = row.get('section_key', '')
        sections_lto.setdefault(sk, []).append((row['id'], int(row.get('is_completed') or 0)))
    for sk, items in sections_lto.items():
        first_incomplete_seen = False
        for item_id, is_completed in items:
            if first_incomplete_seen:
                lto_locked.add(item_id)
            elif not is_completed:
                first_incomplete_seen = True

    rows = []
    for row in goal_rows:
        rows.append({
            'archive_id': f"goal:{row['id']}",
            'source_type': 'goal',
            'item_kind': 'goal',
            'is_goal': 1,
            'is_schedule_section': 0,
            'task_time': None,
            'task_interval': None,
            **row,
        })

    for row in task_rows:
        rows.append({
            'archive_id': f"task:{row['id']}",
            'source_type': 'task',
            'item_kind': 'task',
            'is_goal': 1,
            'is_schedule_section': 0,
            **row,
        })

    for row in custom_rows:
        entry = {
            'archive_id': f"custom_item:{row['id']}",
            'source_type': 'custom_item',
            'item_kind': 'long_term_objective' if int(row.get('is_long_term_objective') or 0) else ('task' if int(row.get('is_task') or 0) else 'goal_item'),
            **row,
        }
        if int(row.get('is_long_term_objective') or 0):
            entry['sessions_required'] = parse_lto_sessions(row.get('title', ''), row.get('description', ''))
            entry['is_locked'] = 1 if row['id'] in lto_locked else 0
        rows.append(entry)

    def term_bucket(row):
        td = (row.get('target_date') or '').strip()
        if td:
            try:
                t = _date.fromisoformat(td)
                days = (t - today).days
                if days < 0:
                    return 'overdue'
                if days <= 90:
                    return 'short'
                if days <= 365:
                    return 'medium'
                return 'long'
            except ValueError:
                pass
        if row.get('item_kind') == 'long_term_objective':
            return 'long'
        if row.get('item_kind') == 'task':
            return 'short'
        # No date — fall back on priority
        p = int(row.get('priority') or 0)
        if p >= 2:
            return 'short'
        if p == 1:
            return 'medium'
        return 'long'

    for row in rows:
        row['term'] = term_bucket(row)

    rows.sort(key=lambda r: (
        {'overdue': 0, 'short': 1, 'medium': 2, 'long': 3}.get(r.get('term'), 9),
        int(r.get('is_completed') or 0),
        -(int(r.get('priority') or 0)),
        str(r.get('title') or '').lower(),
    ))

    return jsonify(rows)


# ── All Purchases View ────────────────────────────────────

@app.route('/api/purchases')
def get_all_purchases():
    db = get_db()
    rows = db.execute('SELECT * FROM v_all_purchases').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/insights/overview', methods=['GET'])
def get_insights_overview():
    """Return high-level progress and urgency metrics for the dashboard."""
    try:
        window_days = int(request.args.get('window_days', 14) or 14)
    except (TypeError, ValueError):
        window_days = 14
    window_days = max(1, min(90, window_days))

    today = date.today()
    db = get_db()
    try:
        purchases = rows_to_list(db.execute('SELECT status_color FROM v_all_purchases').fetchall())
        goals = rows_to_list(db.execute('''
            SELECT g.id, g.title, g.target_date, g.is_completed, g.priority, la.name as area_name
            FROM goals g
            JOIN life_areas la ON g.life_area_id = la.id
            ORDER BY g.priority DESC, g.title
        ''').fetchall())
        tasks = rows_to_list(db.execute('''
            SELECT t.id, t.title, t.due_date, t.is_completed, la.name as area_name
            FROM tasks t
            JOIN life_areas la ON t.life_area_id = la.id
            ORDER BY t.due_date, t.title
        ''').fetchall())
        lto_items = rows_to_list(db.execute('''
            SELECT ci.id, ci.name, ci.notes, ci.objective_completed, ci.sort_order,
                   ci.task_count, ci.sessions_completed, ci.section_key,
                   ss.label as section_label
            FROM custom_items ci
            JOIN sidebar_sections ss ON ss.page_key = ci.section_key
            WHERE COALESCE(ci.is_long_term_objective, 0) = 1
            ORDER BY ci.section_key, ci.sort_order, ci.id
        ''').fetchall())
    finally:
        db.close()

    purchase_counts = {'green': 0, 'blue': 0, 'orange': 0, 'red': 0}
    for row in purchases:
        color = str(row.get('status_color') or '').lower()
        if color in purchase_counts:
            purchase_counts[color] += 1

    goal_total = len(goals)
    goal_completed = sum(1 for g in goals if int(g.get('is_completed') or 0) == 1)
    task_total = len(tasks)
    task_completed = sum(1 for t in tasks if int(t.get('is_completed') or 0) == 1)

    overdue_goals = 0
    upcoming_goals = 0
    overdue_tasks = 0
    upcoming_tasks = 0
    focus_items = []

    for g in goals:
        if int(g.get('is_completed') or 0):
            continue
        target = parse_iso_date(g.get('target_date'))
        if not target:
            continue
        days = (target - today).days
        if days < 0:
            overdue_goals += 1
            focus_items.append({
                'source': 'goal',
                'id': g['id'],
                'title': g['title'],
                'area_name': g.get('area_name'),
                'due_date': target.isoformat(),
                'days_to_due': days,
                'urgency': 'overdue',
            })
        elif days <= window_days:
            upcoming_goals += 1
            focus_items.append({
                'source': 'goal',
                'id': g['id'],
                'title': g['title'],
                'area_name': g.get('area_name'),
                'due_date': target.isoformat(),
                'days_to_due': days,
                'urgency': 'upcoming',
            })

    for t in tasks:
        if int(t.get('is_completed') or 0):
            continue
        due = parse_iso_date(t.get('due_date'))
        if not due:
            continue
        days = (due - today).days
        if days < 0:
            overdue_tasks += 1
            focus_items.append({
                'source': 'task',
                'id': t['id'],
                'title': t['title'],
                'area_name': t.get('area_name'),
                'due_date': due.isoformat(),
                'days_to_due': days,
                'urgency': 'overdue',
            })
        elif days <= window_days:
            upcoming_tasks += 1
            focus_items.append({
                'source': 'task',
                'id': t['id'],
                'title': t['title'],
                'area_name': t.get('area_name'),
                'due_date': due.isoformat(),
                'days_to_due': days,
                'urgency': 'upcoming',
            })

    lto_by_section = {}
    for item in lto_items:
        lto_by_section.setdefault(item.get('section_key') or '', []).append(item)

    for section_items in lto_by_section.values():
        first_incomplete_seen = False
        for item in section_items:
            done = int(item.get('objective_completed') or 0) == 1
            if done:
                continue
            if first_incomplete_seen:
                # Later long-term objectives are blocked by earlier incomplete ones.
                continue
            first_incomplete_seen = True
            sessions_required = int(item.get('task_count') or 0) or parse_lto_sessions(
                item.get('name', ''), item.get('notes', '')
            )
            sessions_completed = int(item.get('sessions_completed') or 0)
            focus_items.append({
                'source': 'long_term_objective',
                'id': item['id'],
                'title': item.get('name'),
                'area_name': item.get('section_label'),
                'sessions_required': sessions_required,
                'sessions_completed': sessions_completed,
                'urgency': 'long_term',
            })

    urgency_rank = {'overdue': 0, 'upcoming': 1, 'long_term': 2}
    focus_items.sort(key=lambda x: (
        urgency_rank.get(str(x.get('urgency') or ''), 9),
        int(x.get('days_to_due') or 9999),
        str(x.get('title') or '').lower(),
    ))

    return jsonify({
        'ok': True,
        'generated_at': today.isoformat(),
        'window_days': window_days,
        'purchases': {
            'total': len(purchases),
            **purchase_counts,
        },
        'goals': {
            'total': goal_total,
            'completed': goal_completed,
            'active': goal_total - goal_completed,
            'overdue': overdue_goals,
            'upcoming': upcoming_goals,
        },
        'tasks': {
            'total': task_total,
            'completed': task_completed,
            'open': task_total - task_completed,
            'overdue': overdue_tasks,
            'upcoming': upcoming_tasks,
        },
        'completion_rates': {
            'goals': round((goal_completed / goal_total) * 100, 1) if goal_total else 0.0,
            'tasks': round((task_completed / task_total) * 100, 1) if task_total else 0.0,
        },
        'focus_items': focus_items[:12],
    })


@app.route('/api/search', methods=['GET'])
def search_all_items():
    """Global fuzzy search across goals, tasks, purchases, and custom sections."""
    query = str(request.args.get('q') or '').strip()
    if len(query) < 2:
        return api_error('q must be at least 2 characters', 400)

    try:
        limit = int(request.args.get('limit', 40) or 40)
    except (TypeError, ValueError):
        limit = 40
    limit = max(1, min(100, limit))

    like = f"%{query.lower()}%"
    db = get_db()
    results = []
    try:
        results.extend(rows_to_list(db.execute('''
            SELECT 'goal' AS source, g.id AS item_id, g.title AS title,
                   COALESCE(la.name, '') AS subtitle, 'goals' AS page_key,
                   NULL AS section_key
            FROM goals g
            LEFT JOIN life_areas la ON la.id = g.life_area_id
            WHERE LOWER(g.title) LIKE ? OR LOWER(COALESCE(g.description, '')) LIKE ?
            LIMIT 50
        ''', (like, like)).fetchall()))

        results.extend(rows_to_list(db.execute('''
            SELECT 'task' AS source, t.id AS item_id, t.title AS title,
                   COALESCE(la.name, '') AS subtitle, 'tasks' AS page_key,
                   NULL AS section_key
            FROM tasks t
            LEFT JOIN life_areas la ON la.id = t.life_area_id
            WHERE LOWER(t.title) LIKE ? OR LOWER(COALESCE(t.description, '')) LIKE ?
            LIMIT 50
        ''', (like, like)).fetchall()))

        results.extend(rows_to_list(db.execute('''
            SELECT 'custom' AS source, ci.id AS item_id, ci.name AS title,
                   COALESCE(ss.label, ci.section_key) AS subtitle,
                   COALESCE(ci.section_key, 'dashboard') AS page_key,
                   ci.section_key AS section_key
            FROM custom_items ci
            LEFT JOIN sidebar_sections ss ON ss.page_key = ci.section_key
            WHERE LOWER(ci.name) LIKE ? OR LOWER(COALESCE(ci.notes, '')) LIKE ?
            LIMIT 80
        ''', (like, like)).fetchall()))

        results.extend(rows_to_list(db.execute('''
            SELECT v.item_type AS source, NULL AS item_id, v.name AS title,
                   COALESCE(v.category, v.status_desc, v.item_type) AS subtitle,
                   v.item_type AS page_key, NULL AS section_key
            FROM v_all_purchases v
            WHERE LOWER(v.name) LIKE ?
               OR LOWER(COALESCE(v.category, '')) LIKE ?
               OR LOWER(COALESCE(v.item_type, '')) LIKE ?
            LIMIT 80
        ''', (like, like, like)).fetchall()))
    finally:
        db.close()

    q = query.lower()

    def rank(item):
        title = str(item.get('title') or '').lower()
        subtitle = str(item.get('subtitle') or '').lower()
        if title == q:
            return (0, title)
        if title.startswith(q):
            return (1, title)
        if q in title:
            return (2, title)
        if q in subtitle:
            return (3, title)
        return (4, title)

    results.sort(key=rank)
    trimmed = results[:limit]
    return jsonify({
        'ok': True,
        'query': query,
        'count': len(trimmed),
        'results': trimmed,
    })


# ── Sidebar Sections ─────────────────────────────────────

@app.route('/api/sidebar', methods=['GET'])
def get_sidebar():
    db = get_db()
    rows = db.execute('''
        SELECT ss.*, COALESCE(lt.long_term_count, 0) AS long_term_count
        FROM sidebar_sections ss
        LEFT JOIN (
            SELECT section_key, COUNT(*) AS long_term_count
            FROM custom_items
            WHERE COALESCE(is_long_term_objective, 0) = 1
            GROUP BY section_key
        ) lt ON lt.section_key = ss.page_key
        ORDER BY ss.sort_order, ss.id
    ''').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


BUILTIN_PAGES = {
    'dashboard', 'purchases', 'fashion', 'skincare', 'pharmacology', 'goals', 'tasks', 'misc', 'goal_archive', 'schedule', 'ai_interface'
}


def slugify_label(value):
    slug = ''.join(ch.lower() if ch.isalnum() else '_' for ch in str(value).strip())
    while '__' in slug:
        slug = slug.replace('__', '_')
    slug = slug.strip('_')
    return slug or 'section'


# ── Master Schedule ───────────────────────────────────────

@app.route('/api/schedule')
def get_schedule():
    """Return all tasks from schedule-flagged sections, grouped by interval."""
    db = get_db()
    rows = db.execute('''
        SELECT ci.*, s.color as status_color, s.name as status_name,
               ss.label as section_label, ss.page_key as section_key
        FROM custom_items ci
        JOIN statuses s ON ci.status_id = s.id
        JOIN sidebar_sections ss ON ci.section_key = ss.page_key
        WHERE ss.is_schedule = 1 AND ci.is_task = 1
        ORDER BY ci.task_interval, ci.task_time, ci.name
    ''').fetchall()
    db.close()
    items = rows_to_list(rows)
    for item in items:
        if int(item.get('is_long_term_objective') or 0) or int(item.get('task_count') or 0) > 0:
            item['sessions_required'] = int(item.get('task_count') or 0) or parse_lto_sessions(item.get('name', ''), item.get('notes', ''))
            item['sessions_completed'] = int(item.get('sessions_completed') or 0)
    return jsonify(items)


@app.route('/api/ai/status')
def ai_status():
    runtime = get_ai_runtime_info()
    has_search = bool(os.environ.get('GOOGLE_API_KEY') and os.environ.get('GOOGLE_CSE_ID'))
    return jsonify({
        'ok': True,
        'provider': runtime['provider'],
        'model': runtime['model'],
        'configured': runtime['configured'],
        'web_search': has_search,
    })


@app.route('/api/ai/research', methods=['POST'])
def ai_research():
    """Search the web, analyze results with AI, and optionally create goals."""
    data, error = get_json_payload(required_fields=['topic'])
    if error:
        return error

    topic = str(data.get('topic') or '').strip()
    if not topic:
        return api_error('topic is required', 400)

    life_area_id = data.get('life_area_id')
    create_goals = 1 if int(data.get('create_goals', 0) or 0) else 0
    token_limit = 2000
    try:
        token_limit = int(data.get('token_limit', 2000) or 2000)
    except (TypeError, ValueError):
        pass

    # Resolve life area name for context
    life_area_name = None
    if life_area_id:
        db = get_db()
        area = db.execute('SELECT name FROM life_areas WHERE id=?', (life_area_id,)).fetchone()
        if area:
            life_area_name = area['name']
        db.close()

    result = research_and_create_goals(topic, life_area_name=life_area_name, token_limit=token_limit)

    created_goals = []
    if create_goals and result.get('goals'):
        from datetime import date as _date, timedelta
        today = _date.today()

        db = get_db()
        try:
            # Resolve life_area_id: use provided, or first area
            area_id = None
            if life_area_id:
                try:
                    area_id = int(life_area_id)
                except (TypeError, ValueError):
                    pass
            if not area_id:
                row = db.execute('SELECT id FROM life_areas ORDER BY sort_order LIMIT 1').fetchone()
                area_id = row['id'] if row else 1

            for g in result['goals']:
                # Parse target_date_hint into actual date
                hint = (g.get('target_date_hint') or '').lower()
                target_date = None
                if 'week' in hint:
                    try:
                        weeks = int(re.search(r'(\d+)', hint).group(1))
                        target_date = (today + timedelta(weeks=weeks)).isoformat()
                    except Exception:
                        target_date = (today + timedelta(weeks=4)).isoformat()
                elif 'month' in hint:
                    try:
                        months = int(re.search(r'(\d+)', hint).group(1))
                        target_date = (today + timedelta(days=months * 30)).isoformat()
                    except Exception:
                        target_date = (today + timedelta(days=90)).isoformat()
                elif 'year' in hint:
                    target_date = (today + timedelta(days=365)).isoformat()

                cur = db.execute(
                    '''INSERT INTO goals (life_area_id, title, description, target_date, priority,
                       difficulty, time_commitment_hours, ai_priority_score, ai_reasoning)
                       VALUES (?,?,?,?,?,?,?,?,?)''',
                    (area_id, g['title'], g.get('description', ''),
                     target_date, g.get('priority', 3),
                     g.get('difficulty', 5), g.get('time_commitment_hours', 0),
                     g.get('priority', 3), f"Auto-created from research: {topic}")
                )
                created_goals.append({
                    'id': cur.lastrowid,
                    'title': g['title'],
                    'target_date': target_date,
                })
            db.commit()
        finally:
            db.close()

    return jsonify({
        'ok': True,
        'mode': result.get('mode', 'heuristic'),
        'search_results': result.get('search_results', []),
        'analysis': result.get('analysis', ''),
        'suggested_goals': result.get('goals', []),
        'created_goals': created_goals,
    })


@app.route('/api/ai/optimize-schedule', methods=['POST'])
def ai_optimize_schedule():
    data, error = get_json_payload()
    if error:
        return error

    section_key = (data.get('section_key') or '').strip() or None
    apply_updates_now = 1 if int(data.get('apply', 0) or 0) else 0
    preferences = data.get('preferences') if isinstance(data.get('preferences'), dict) else {}
    provided_updates = data.get('updates') if isinstance(data.get('updates'), list) else None

    db = get_db()
    query = '''
        SELECT ci.id, ci.section_key, ci.name, ci.sort_order, ci.subgroup, ci.task_time, ci.task_interval,
               s.color AS status_color
        FROM custom_items ci
        JOIN sidebar_sections ss ON ci.section_key = ss.page_key
        JOIN statuses s ON ci.status_id = s.id
        WHERE ss.is_schedule = 1 AND ci.is_task = 1
    '''
    params = []
    if section_key:
        query += ' AND ci.section_key = ?'
        params.append(section_key)
    query += ' ORDER BY ci.section_key, ci.sort_order, ci.name'

    tasks = rows_to_list(db.execute(query, params).fetchall())
    if not tasks:
        db.close()
        return api_error('No schedule tasks found to optimize', 404)

    if provided_updates is not None:
        plan = type('obj', (), {
            'mode': 'provided',
            'summary': f'Applying provided plan with {len(provided_updates)} updates.',
            'updates': provided_updates,
        })
    else:
        plan = optimize_schedule(tasks, preferences)
    applied_count = 0
    if apply_updates_now:
        applied_count = apply_schedule_updates(db, plan.updates)
        db.commit()

    db.close()
    return jsonify({
        'ok': True,
        'mode': plan.mode,
        'summary': plan.summary,
        'updates': plan.updates,
        'applied_count': applied_count
    })


@app.route('/api/ai/build-routine', methods=['POST'])
def ai_build_routine():
    data, error = get_json_payload(required_fields=['title', 'goal'])
    if error:
        return error

    apply_now = 1 if int(data.get('apply', 0) or 0) else 0
    db = get_db()
    sections = rows_to_list(db.execute('SELECT * FROM sidebar_sections ORDER BY sort_order, id').fetchall())
    plan = build_routine_plan(data, sections)

    created_page_key = None
    created_items = 0
    if apply_now:
        section_label = plan.get('section_label') or data.get('title')
        group_name = plan.get('group_name') or data.get('group_name') or 'Routines'
        section_type = (plan.get('section_type') or 'schedule').strip().lower()
        if section_type not in {'default', 'schedule', 'long_term_objective'}:
            section_type = 'schedule'

        base_key = 'custom_' + slugify_label(section_label)
        page_key = base_key
        i = 2
        while db.execute('SELECT 1 FROM sidebar_sections WHERE page_key=?', (page_key,)).fetchone():
            page_key = f'{base_key}_{i}'
            i += 1

        max_order = db.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
        db.execute(
            'INSERT INTO sidebar_sections (group_name, label, page_key, sort_order, is_builtin, is_schedule, is_long_term_section) VALUES (?,?,?,?,0,?,?)',
            (group_name, section_label, page_key, max_order + 1,
             1 if section_type == 'schedule' else 0,
             1 if section_type == 'long_term_objective' else 0)
        )
        created_page_key = page_key

        status_rows = rows_to_list(db.execute('SELECT id, color FROM statuses').fetchall())
        status_by_color = {r['color']: r['id'] for r in status_rows}
        default_status_id = status_by_color.get('blue') or (status_rows[0]['id'] if status_rows else 1)

        for idx, item in enumerate(plan.get('items', [])):
            status_id = status_by_color.get(str(item.get('status_color', 'blue')).lower(), default_status_id)
            db.execute(
                '''
                INSERT INTO custom_items (
                    section_key, name, status_id, notes, sort_order, is_task,
                    task_time, task_interval, subgroup, is_long_term_objective, is_goal, objective_completed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,0)
                ''',
                (
                    page_key,
                    str(item.get('name') or f'Routine task {idx + 1}').strip(),
                    status_id,
                    item.get('notes'),
                    idx,
                    1,
                    item.get('task_time'),
                    item.get('task_interval') or data.get('cadence') or 'daily',
                    item.get('subgroup'),
                    1 if section_type == 'long_term_objective' else 0,
                    1,
                )
            )
            created_items += 1
        db.commit()

    db.close()
    return jsonify({
        'ok': True,
        'mode': plan.get('mode', 'heuristic'),
        'summary': plan.get('summary', ''),
        'section_label': plan.get('section_label'),
        'section_type': plan.get('section_type'),
        'items': plan.get('items', []),
        'created_page_key': created_page_key,
        'created_items': created_items
    })


@app.route('/api/ai/query', methods=['POST'])
def ai_query():
    data, error = get_json_payload(required_fields=['prompt'])
    if error:
        return error

    prompt = str(data.get('prompt') or '').strip()
    if not prompt:
        return api_error('prompt is required', 400)

    include_schedule_context = 1 if int(data.get('include_schedule_context', 0) or 0) else 0
    empowered = 1 if int(data.get('empowered', 0) or 0) else 0
    apply_changes = 1 if int(data.get('apply_changes', 0) or 0) else 0
    history = data.get('history') if isinstance(data.get('history'), list) else []
    token_limit_raw = data.get('token_limit', data.get('reason_token_limit', 700))
    try:
        token_limit = int(token_limit_raw)
    except (TypeError, ValueError):
        token_limit = 700

    context = {
        'history': history,
    }

    allowed_tables = {
        'statuses', 'life_areas', 'fashion_categories', 'fashion_items',
        'skincare_routines', 'skincare_products', 'pharmacology_items',
        'goals', 'sidebar_sections', 'custom_items'
    }

    def table_columns(conn, table_name):
        rows = conn.execute(f'PRAGMA table_info({table_name})').fetchall()
        return [row['name'] for row in rows]

    def apply_empowered_edits(conn, edits):
        applied = 0
        results = []
        cols_cache = {}

        for idx, raw in enumerate(edits):
            if not isinstance(raw, dict):
                results.append({'index': idx, 'ok': False, 'error': 'Edit must be an object'})
                continue

            op = str(raw.get('op') or '').strip().lower()
            table = str(raw.get('table') or '').strip()
            if op not in {'insert', 'update', 'delete'}:
                results.append({'index': idx, 'ok': False, 'error': 'Invalid op'})
                continue
            if table not in allowed_tables:
                results.append({'index': idx, 'ok': False, 'error': f'Table not allowed: {table}'})
                continue

            if table not in cols_cache:
                cols_cache[table] = table_columns(conn, table)
            cols = set(cols_cache[table])

            if op == 'delete':
                try:
                    item_id = int(raw.get('id'))
                except (TypeError, ValueError):
                    results.append({'index': idx, 'ok': False, 'error': 'delete requires integer id'})
                    continue
                cur = conn.execute(f'DELETE FROM {table} WHERE id=?', (item_id,))
                ok = cur.rowcount > 0
                results.append({'index': idx, 'ok': ok, 'op': op, 'table': table, 'id': item_id})
                if ok:
                    applied += 1
                continue

            fields = raw.get('fields') if isinstance(raw.get('fields'), dict) else None
            if not fields:
                results.append({'index': idx, 'ok': False, 'error': f'{op} requires fields object'})
                continue

            blocked = {'id', 'created_at'}
            valid_pairs = [(k, v) for k, v in fields.items() if k in cols and k not in blocked]
            if not valid_pairs:
                results.append({'index': idx, 'ok': False, 'error': 'No valid fields for table'})
                continue

            if op == 'insert':
                col_names = [k for k, _ in valid_pairs]
                placeholders = ','.join(['?'] * len(valid_pairs))
                sql = f"INSERT INTO {table} ({','.join(col_names)}) VALUES ({placeholders})"
                vals = [v for _, v in valid_pairs]
                cur = conn.execute(sql, vals)
                results.append({'index': idx, 'ok': True, 'op': op, 'table': table, 'id': cur.lastrowid})
                applied += 1
                continue

            # update
            try:
                item_id = int(raw.get('id'))
            except (TypeError, ValueError):
                results.append({'index': idx, 'ok': False, 'error': 'update requires integer id'})
                continue

            set_parts = [f"{k}=?" for k, _ in valid_pairs]
            vals = [v for _, v in valid_pairs]
            if 'updated_at' in cols and 'updated_at' not in [k for k, _ in valid_pairs]:
                set_parts.append("updated_at=datetime('now')")

            sql = f"UPDATE {table} SET {', '.join(set_parts)} WHERE id=?"
            cur = conn.execute(sql, vals + [item_id])
            ok = cur.rowcount > 0
            results.append({'index': idx, 'ok': ok, 'op': op, 'table': table, 'id': item_id})
            if ok:
                applied += 1

        return applied, results

    db = get_db()
    if include_schedule_context:
        schedule_rows = db.execute(
            '''
            SELECT ci.id, ci.name, ci.task_time, ci.task_interval, ci.subgroup, ss.label AS section_label, ci.section_key
            FROM custom_items ci
            JOIN sidebar_sections ss ON ci.section_key = ss.page_key
            WHERE ss.is_schedule = 1 AND ci.is_task = 1
            ORDER BY ci.section_key, ci.sort_order, ci.name
            LIMIT 200
            '''
        ).fetchall()
        context['schedule_tasks'] = rows_to_list(schedule_rows)
    if empowered:
        full_data = {}
        for table in sorted(allowed_tables):
            try:
                rows = db.execute(f'SELECT * FROM {table} ORDER BY id LIMIT 2000').fetchall()
                full_data[table] = rows_to_list(rows)
            except sqlite3.OperationalError:
                full_data[table] = []
        context['full_data'] = full_data

    if empowered:
        result = query_ai_empowered(prompt, context, token_limit=token_limit)
        edits = result.get('edits') if isinstance(result.get('edits'), list) else []
        applied_count = 0
        edit_results = []
        if apply_changes and edits:
            try:
                applied_count, edit_results = apply_empowered_edits(db, edits)
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                db.close()
                return api_error(f'Database constraint error during AI apply: {exc}', 409)
        db.close()
        return jsonify({
            'ok': True,
            'mode': result.get('mode', 'heuristic'),
            'answer': result.get('answer', ''),
            'token_limit': result.get('token_limit', token_limit),
            'proposed_edits': len(edits),
            'applied_edits': applied_count,
            'edit_results': edit_results[:100],
        })

    db.close()
    result = query_ai(prompt, context, token_limit=token_limit)
    return jsonify({
        'ok': True,
        'mode': result.get('mode', 'heuristic'),
        'answer': result.get('answer', ''),
        'token_limit': result.get('token_limit', token_limit),
    })


@app.route('/api/ai/analyze-goals', methods=['POST'])
def ai_analyze_goals():
    data = request.get_json(silent=True) or {}
    apply_scores = 1 if int(data.get('apply', 0) or 0) else 0

    db = get_db()
    goals = rows_to_list(db.execute('''
        SELECT g.*, la.name as area_name
        FROM goals g
        JOIN life_areas la ON g.life_area_id = la.id
        WHERE g.is_completed = 0
        ORDER BY la.sort_order, g.priority DESC, g.title
    ''').fetchall())

    if not goals:
        db.close()
        return jsonify({
            'ok': True, 'mode': 'heuristic',
            'goals': [], 'priority_list': [],
            'summary': 'No active goals found.'
        })

    result = analyze_goals(goals)

    if apply_scores and result.get('goals'):
        for item in result['goals']:
            db.execute(
                """UPDATE goals
                   SET difficulty=?, time_commitment_hours=?, price_estimate=?,
                       ai_priority_score=?, ai_reasoning=?, updated_at=datetime('now')
                   WHERE id=?""",
                (item.get('difficulty'), item.get('time_commitment_hours'),
                 item.get('price_estimate'), item.get('priority_score'),
                 item.get('reasoning'), item['id'])
            )
        db.commit()

    # Build a merged response so the frontend has full goal context
    goals_by_id = {g['id']: g for g in goals}
    enriched = []
    for item in result.get('goals', []):
        merged = dict(goals_by_id.get(item['id'], {}))
        merged.update(item)
        enriched.append(merged)

    db.close()
    return jsonify({
        'ok': True,
        'mode': result.get('mode', 'heuristic'),
        'goals': enriched,
        'priority_list': result.get('priority_list', []),
        'summary': result.get('summary', ''),
    })


@app.route('/api/ai/today-plan', methods=['POST'])
def ai_today_plan():
    from datetime import datetime as _datetime

    data = request.get_json(silent=True) or {}
    now_iso = str(data.get('now_iso') or _datetime.utcnow().isoformat())
    today_section_key = str(data.get('today_section_key') or '').strip() or None
    try:
        end_hour = int(data.get('end_hour', 22) or 22)
    except (TypeError, ValueError):
        end_hour = 22
    end_hour = max(18, min(24, end_hour))
    selected_archive_ids = data.get('selected_archive_ids') if isinstance(data.get('selected_archive_ids'), list) else []
    selected_set = {str(x) for x in selected_archive_ids if str(x).strip()}

    db = get_db()
    schedule_query = '''
        SELECT ci.id, ci.name, ci.task_time, ci.task_interval, ci.subgroup,
               ci.task_count, ci.sessions_completed, ci.is_long_term_objective, ci.notes,
               ss.label as section_label, ss.page_key as section_key, ss.is_schedule
        FROM custom_items ci
        JOIN sidebar_sections ss ON ci.section_key = ss.page_key
        WHERE ss.is_schedule = 1 AND ci.is_task = 1
    '''
    params = []
    if today_section_key:
        schedule_query += ' AND ss.page_key = ?'
        params.append(today_section_key)
    schedule_query += ' ORDER BY ci.task_time, ci.sort_order, ci.name'
    schedule_tasks = rows_to_list(db.execute(schedule_query, params).fetchall())
    db.close()

    for st in schedule_tasks:
        tc = int(st.get('task_count') or 0)
        if tc > 0 or int(st.get('is_long_term_objective') or 0):
            st['sessions_required'] = tc or parse_lto_sessions(st.get('name', ''), st.get('notes', ''))
            st['sessions_completed'] = int(st.get('sessions_completed') or 0)

    archive_response = get_goals_archive()
    archive_items = archive_response.get_json(silent=True)
    if not isinstance(archive_items, list):
        archive_items = []

    # Candidate pool: goals/tasks/objectives not completed and not already part of schedule rows.
    candidates = []
    for item in archive_items:
        if not isinstance(item, dict):
            continue
        if int(item.get('is_completed') or 0):
            continue
        # Locked LTOs (prerequisite not done) are not eligible
        if int(item.get('is_locked') or 0):
            continue
        source_type = str(item.get('source_type') or '')
        item_kind = str(item.get('item_kind') or '')
        is_schedule_section = int(item.get('is_schedule_section') or 0)
        if source_type == 'custom_item' and is_schedule_section == 1:
            continue
        if source_type in {'goal', 'task'} or item_kind in {'task', 'long_term_objective', 'goal_item', 'goal'}:
            candidates.append(item)

    if selected_set:
        candidates = [c for c in candidates if str(c.get('archive_id') or '') in selected_set]

    plan = build_today_plan(schedule_tasks, candidates, now_iso=now_iso, end_hour=end_hour)

    return jsonify({
        'ok': True,
        'mode': plan.get('mode', 'heuristic'),
        'summary': plan.get('summary', ''),
        'schedule': schedule_tasks,
        'candidates_considered': len(candidates),
        'selected_candidates': len(selected_set),
        'free_minutes': int(plan.get('free_minutes') or 0),
        'recommendations': plan.get('recommendations', []),
    })


@app.route('/api/ai/today-plan/insert', methods=['POST'])
def ai_today_plan_insert():
    data, error = get_json_payload(required_fields=['today_section_key', 'selected_archive_ids'])
    if error:
        return error

    today_section_key = str(data.get('today_section_key') or '').strip()
    selected_archive_ids = data.get('selected_archive_ids') if isinstance(data.get('selected_archive_ids'), list) else []
    selected_set = {str(x).strip() for x in selected_archive_ids if str(x).strip()}
    recommendations = data.get('recommendations') if isinstance(data.get('recommendations'), list) else []

    if not today_section_key:
        return api_error('today_section_key is required', 400)
    if not selected_set:
        return api_error('selected_archive_ids must contain at least one item', 400)

    db = get_db()
    try:
        section = db.execute(
            'SELECT id, label, is_schedule FROM sidebar_sections WHERE page_key=?',
            (today_section_key,)
        ).fetchone()
        if not section:
            return api_error('Schedule section not found', 404)
        if int(section['is_schedule'] or 0) != 1:
            return api_error('Target section is not schedule-enabled', 400)

        status_rows = rows_to_list(db.execute('SELECT id, color FROM statuses').fetchall())
        status_by_color = {str(r['color']).lower(): int(r['id']) for r in status_rows}
        default_status_id = status_by_color.get('blue') or (status_rows[0]['id'] if status_rows else 1)

        existing_max = db.execute(
            'SELECT MAX(sort_order) FROM custom_items WHERE section_key=?',
            (today_section_key,)
        ).fetchone()[0]
        next_sort = int(existing_max or 0) + 1

        rec_by_archive = {
            str(r.get('archive_id') or ''): r
            for r in recommendations
            if isinstance(r, dict) and str(r.get('archive_id') or '').strip()
        }

        archive_response = get_goals_archive()
        archive_items = archive_response.get_json(silent=True)
        if not isinstance(archive_items, list):
            archive_items = []
        archive_by_id = {
            str(item.get('archive_id') or ''): item
            for item in archive_items
            if isinstance(item, dict) and str(item.get('archive_id') or '').strip()
        }

        inserted = []
        for archive_id in selected_set:
            item = archive_by_id.get(archive_id)
            if not item:
                continue
            rec = rec_by_archive.get(archive_id, {})
            name = str(item.get('title') or '').strip()
            if not name:
                continue

            task_time = rec.get('planned_start') or None
            subgroup = None
            parsed_minutes = parse_time(task_time) if task_time else None
            if parsed_minutes is not None:
                hour = parsed_minutes // 60
                if hour < 12:
                    subgroup = 'Morning'
                elif hour < 14:
                    subgroup = 'Midday'
                elif hour < 17:
                    subgroup = 'Afternoon'
                else:
                    subgroup = 'Evening'

            notes_parts = []
            if item.get('description'):
                notes_parts.append(str(item.get('description')))
            if rec.get('reason'):
                notes_parts.append(f"AI plan: {rec.get('reason')}")
            notes = '\n\n'.join(p for p in notes_parts if p).strip() or None

            # Parse sessions required for LTO items
            is_lto = int(item.get('is_long_term_objective') or 0)
            sessions_required = 0
            if is_lto or item.get('item_kind') == 'long_term_objective':
                sessions_required = parse_lto_sessions(name, item.get('description', ''))

            duplicate = db.execute(
                '''
                SELECT id FROM custom_items
                WHERE section_key=? AND name=? AND COALESCE(task_time, '') = COALESCE(?, '')
                LIMIT 1
                ''',
                (today_section_key, name, task_time)
            ).fetchone()
            if duplicate:
                continue

            db.execute(
                '''
                INSERT INTO custom_items (
                    section_key, name, status_id, link, notes, sort_order, is_task,
                    task_time, task_count, task_interval, subgroup, is_quick_objective,
                    is_long_term_objective, is_goal, objective_completed, sessions_completed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)
                ''',
                (
                    today_section_key,
                    name,
                    default_status_id,
                    item.get('link'),
                    notes,
                    next_sort,
                    1,
                    task_time,
                    sessions_required if sessions_required > 0 else None,
                    'daily',
                    subgroup,
                    0,
                    0,
                    1,
                )
            )
            next_sort += 1
            inserted.append({
                'archive_id': archive_id,
                'name': name,
                'task_time': task_time,
                'sessions_required': sessions_required,
            })

        db.commit()
    finally:
        db.close()

    return jsonify({
        'ok': True,
        'inserted_count': len(inserted),
        'inserted': inserted,
        'today_section_key': today_section_key,
    })


@app.route('/api/sidebar', methods=['POST'])
def add_sidebar_section():
    data, error = get_json_payload(required_fields=['label', 'group_name'])
    if error:
        return error
    label = data.get('label', '').strip()
    group_name = data.get('group_name', '').strip()
    section_type = str(data.get('section_type', 'default')).strip().lower()
    if section_type not in {'default', 'schedule', 'long_term_objective'}:
        return api_error('section_type must be one of: default, schedule, long_term_objective', 400)

    if not label or not group_name:
        return api_error('label and group_name required', 400)
    # Check if this matches a known builtin page key
    candidate_key = label.lower().replace(' ', '_')
    if candidate_key in BUILTIN_PAGES:
        page_key = candidate_key
        is_builtin = 1
        section_type = 'default'
    else:
        page_key = 'custom_' + candidate_key
        is_builtin = 0

    is_schedule = 1 if section_type == 'schedule' else 0
    is_long_term_section = 1 if section_type == 'long_term_objective' else 0

    db = get_db()
    try:
        existing = db.execute('SELECT id FROM sidebar_sections WHERE page_key=?', (page_key,)).fetchone()
        if existing:
            return api_error('Section already exists', 409)
        max_order = db.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
        db.execute(
            'INSERT INTO sidebar_sections (group_name, label, page_key, sort_order, is_builtin, is_schedule, is_long_term_section) VALUES (?,?,?,?,?,?,?)',
            (group_name, label, page_key, max_order + 1, is_builtin, is_schedule, is_long_term_section))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True, 'page_key': page_key}), 201


@app.route('/api/sidebar/<int:section_id>/toggle-schedule', methods=['PUT'])
def toggle_sidebar_schedule(section_id):
    db = get_db()
    try:
        section = db.execute('SELECT is_schedule FROM sidebar_sections WHERE id=?', (section_id,)).fetchone()
        if not section:
            return jsonify({'error': 'Not found'}), 404
        new_val = 0 if section['is_schedule'] else 1
        db.execute('UPDATE sidebar_sections SET is_schedule=? WHERE id=?', (new_val, section_id))
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True, 'is_schedule': new_val})


@app.route('/api/sidebar/reorder', methods=['PUT'])
def reorder_sidebar():
    data, error = get_json_payload(required_fields=['order'])
    if error:
        return error
    order = data.get('order', [])
    if not isinstance(order, list) or not order:
        return api_error('order must be a non-empty list', 400)
    try:
        order = [int(section_id) for section_id in order]
    except (TypeError, ValueError):
        return api_error('order entries must be integers', 400)

    db = get_db()
    try:
        existing_ids = {row['id'] for row in db.execute('SELECT id FROM sidebar_sections').fetchall()}
        if any(section_id not in existing_ids for section_id in order):
            return api_error('order contains unknown section id', 404)
        for i, section_id in enumerate(order):
            db.execute('UPDATE sidebar_sections SET sort_order=? WHERE id=?', (i, section_id))
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/sidebar/<int:section_id>', methods=['DELETE'])
def delete_sidebar_section(section_id):
    db = get_db()
    try:
        section = db.execute('SELECT * FROM sidebar_sections WHERE id=?', (section_id,)).fetchone()
        if not section:
            return jsonify({'error': 'Not found'}), 404
        if section['page_key'] == 'dashboard':
            return jsonify({'error': 'Cannot delete the Dashboard'}), 403
        if not section['is_builtin']:
            db.execute('DELETE FROM custom_items WHERE section_key=?', (section['page_key'],))
        db.execute('DELETE FROM sidebar_sections WHERE id=?', (section_id,))
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


# ── Custom Section Items ─────────────────────────────────

@app.route('/api/custom/<section_key>', methods=['GET'])
def get_custom_items(section_key):
    db = get_db()
    rows = db.execute('''
        SELECT ci.*, s.color as status_color, s.name as status_name
        FROM custom_items ci
        JOIN statuses s ON ci.status_id = s.id
        WHERE ci.section_key = ?
        ORDER BY ci.sort_order, ci.name
    ''', (section_key,)).fetchall()
    db.close()
    items = rows_to_list(rows)
    for item in items:
        if int(item.get('is_long_term_objective') or 0):
            item['sessions_required'] = parse_lto_sessions(item.get('name', ''), item.get('notes', ''))
    return jsonify(items)


@app.route('/api/custom/<section_key>', methods=['POST'])
def add_custom_item(section_key):
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_custom_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        db.execute(
            'INSERT INTO custom_items (section_key, name, status_id, link, notes, sort_order, is_task, task_time, task_count, task_interval, subgroup, is_quick_objective, is_long_term_objective, is_goal, objective_completed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)',
            (section_key, normalized['name'], normalized['status_id'],
             normalized['link'], normalized['notes'], normalized['sort_order'],
             normalized['is_task'], normalized['task_time'], normalized['task_count'], normalized['task_interval'], normalized['subgroup'],
             normalized['is_quick_objective'], normalized['is_long_term_objective'], normalized['is_goal']))
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/custom/<section_key>/<int:item_id>', methods=['PUT'])
def update_custom_item(section_key, item_id):
    data, error = get_json_payload(required_fields=['name', 'status_id'])
    if error:
        return error
    normalized, validation_error = normalize_custom_payload(data)
    if validation_error:
        return validation_error

    db = get_db()
    try:
        cur = db.execute('''UPDATE custom_items
                                                        SET name=?, status_id=?, link=?, notes=?, sort_order=?, is_task=?, task_time=?, task_count=?, task_interval=?, subgroup=?, is_quick_objective=?, is_long_term_objective=?, is_goal=?, updated_at=datetime('now')
                            WHERE id=? AND section_key=?''',
                         (normalized['name'], normalized['status_id'], normalized['link'],
                          normalized['notes'], normalized['sort_order'],
                          normalized['is_task'], normalized['task_time'], normalized['task_count'], normalized['task_interval'],
                                                    normalized['subgroup'], normalized['is_quick_objective'], normalized['is_long_term_objective'], normalized['is_goal'],
                          item_id, section_key))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Custom item not found', 404)
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return api_error(f'Database constraint error: {exc}', 409)
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/custom/<section_key>/reorder', methods=['PUT'])
def reorder_custom_items(section_key):
    data, error = get_json_payload(required_fields=['order'])
    if error:
        return error
    order = data.get('order', [])
    if not isinstance(order, list) or not order:
        return api_error('order must be a non-empty list', 400)
    try:
        order = [int(item_id) for item_id in order]
    except (TypeError, ValueError):
        return api_error('order entries must be integers', 400)

    db = get_db()
    try:
        existing_ids = {
            row['id'] for row in db.execute('SELECT id FROM custom_items WHERE section_key=?', (section_key,)).fetchall()
        }
        if any(item_id not in existing_ids for item_id in order):
            return api_error('order contains unknown item id', 404)
        for i, item_id in enumerate(order):
            db.execute('UPDATE custom_items SET sort_order=? WHERE id=? AND section_key=?', (i, item_id, section_key))
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/custom/<section_key>/<int:item_id>', methods=['DELETE'])
def delete_custom_item(section_key, item_id):
    db = get_db()
    try:
        cur = db.execute('DELETE FROM custom_items WHERE id=? AND section_key=?', (item_id, section_key))
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Custom item not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/api/custom/<section_key>/<int:item_id>/complete', methods=['PUT'])
def set_custom_objective_completed(section_key, item_id):
    data, error = get_json_payload(required_fields=['is_completed'])
    if error:
        return error
    try:
        is_completed = int(data.get('is_completed', 0) or 0)
    except (TypeError, ValueError):
        return api_error('is_completed must be an integer (0 or 1)', 400)

    is_completed = 1 if is_completed else 0
    db = get_db()
    try:
        item = db.execute(
            '''
            SELECT id, name, sort_order, is_long_term_objective, objective_completed
            FROM custom_items
            WHERE id=? AND section_key=?
            ''',
            (item_id, section_key)
        ).fetchone()
        if not item:
            return api_error('Custom item not found', 404)

        # Lock progression for long-term objectives: you cannot complete an objective
        # until ALL prior objectives across ALL phases are completed.
        if is_completed and int(item['is_long_term_objective'] or 0) == 1:
            blocking = db.execute(
                '''
                SELECT id, name
                FROM custom_items
                WHERE section_key=?
                  AND COALESCE(is_long_term_objective, 0) = 1
                  AND name NOT LIKE '━━━%'
                  AND sort_order < ?
                  AND COALESCE(objective_completed, 0) = 0
                ORDER BY sort_order ASC, id ASC
                LIMIT 1
                ''',
                (section_key, item['sort_order'])
            ).fetchone()

            if blocking:
                db.rollback()
                return api_error(f"Complete prior objective first: {blocking['name']}", 409)

        cur = db.execute(
            'UPDATE custom_items SET objective_completed=?, updated_at=datetime(\'now\') WHERE id=? AND section_key=?',
            (is_completed, item_id, section_key)
        )
        if cur.rowcount == 0:
            db.rollback()
            return api_error('Custom item not found', 404)
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True, 'objective_completed': is_completed})


@app.route('/api/custom/<section_key>/<int:item_id>/session', methods=['PUT'])
def record_session_complete(section_key, item_id):
    """Increment sessions_completed for a scheduled LTO item."""
    db = get_db()
    try:
        item = db.execute(
            'SELECT id, task_count, sessions_completed FROM custom_items WHERE id=? AND section_key=?',
            (item_id, section_key)
        ).fetchone()
        if not item:
            return api_error('Item not found', 404)
        total = int(item['task_count'] or 0)
        done = int(item['sessions_completed'] or 0) + 1
        db.execute(
            'UPDATE custom_items SET sessions_completed=?, updated_at=datetime(\'now\') WHERE id=?',
            (done, item_id)
        )
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True, 'sessions_completed': done, 'sessions_required': total, 'all_done': done >= total and total > 0})


# ── Optimize Task Placement ──────────────────────────────

def parse_time(t):
    """Parse time string like '8:30 AM' or '1:00 PM' to minutes since midnight."""
    if not t:
        return None
    t = t.strip().upper()
    try:
        # Handle H:MM AM/PM
        parts = t.replace('AM', '').replace('PM', '').strip().split(':')
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if 'PM' in t and h != 12:
            h += 12
        if 'AM' in t and h == 12:
            h = 0
        return h * 60 + m
    except (ValueError, IndexError):
        return None


def format_time(minutes):
    """Convert minutes since midnight back to H:MM AM/PM."""
    h = minutes // 60
    m = minutes % 60
    period = 'AM' if h < 12 else 'PM'
    if h == 0:
        h = 12
    elif h > 12:
        h -= 12
    return f'{h}:{m:02d} {period}'


@app.route('/api/custom/<section_key>/<int:item_id>/optimize', methods=['PUT'])
def optimize_task(section_key, item_id):
    """Find the best time slot for a task within its section's schedule."""
    db = get_db()
    item = db.execute('SELECT * FROM custom_items WHERE id=? AND section_key=?',
                      (item_id, section_key)).fetchone()
    if not item:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    if not item['is_task']:
        db.close()
        return jsonify({'error': 'Item is not a task'}), 400

    # Get all other tasks in the same section with valid times
    others = db.execute(
        'SELECT * FROM custom_items WHERE section_key=? AND id!=? AND is_task=1 ORDER BY sort_order',
        (section_key, item_id)).fetchall()

    slots = []
    for o in others:
        t = parse_time(o['task_time'])
        if t is not None:
            slots.append({'time': t, 'sort_order': o['sort_order'], 'subgroup': o['subgroup']})

    slots.sort(key=lambda s: s['time'])

    if not slots:
        # No other tasks — default to 9:00 AM
        best_time = 9 * 60
        best_order = 1
        best_subgroup = 'Morning'
    else:
        # Find the largest gap between consecutive tasks (within 6 AM – 10 PM)
        day_start = 6 * 60   # 6:00 AM
        day_end = 22 * 60    # 10:00 PM
        edges = [day_start] + [s['time'] for s in slots] + [day_end]

        best_gap = 0
        best_mid = None
        best_after_idx = 0
        for i in range(len(edges) - 1):
            gap = edges[i + 1] - edges[i]
            if gap > best_gap:
                best_gap = gap
                best_mid = edges[i] + gap // 2
                best_after_idx = i

        # Round to nearest 5 minutes
        best_time = (best_mid // 5) * 5

        # Determine sort_order: place between the two bounding tasks
        if best_after_idx == 0:
            best_order = slots[0]['sort_order'] - 1 if slots else 1
        elif best_after_idx >= len(slots):
            best_order = slots[-1]['sort_order'] + 1
        else:
            prev_order = slots[best_after_idx - 1]['sort_order']
            next_order = slots[best_after_idx]['sort_order']
            best_order = prev_order + 1
            # Shift subsequent tasks if needed
            if best_order >= next_order:
                db.execute(
                    'UPDATE custom_items SET sort_order = sort_order + 2 WHERE section_key=? AND sort_order >= ? AND id != ?',
                    (section_key, next_order, item_id))

        # Determine subgroup based on time of day
        hour = best_time / 60
        if hour < 12:
            best_subgroup = 'Morning'
        elif hour < 14:
            best_subgroup = 'Midday'
        elif hour < 17:
            best_subgroup = 'Afternoon'
        else:
            best_subgroup = 'Evening'

    time_str = format_time(best_time)
    db.execute(
        'UPDATE custom_items SET task_time=?, sort_order=?, subgroup=?, updated_at=datetime(\'now\') WHERE id=? AND section_key=?',
        (time_str, best_order, best_subgroup, item_id, section_key))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'task_time': time_str, 'sort_order': best_order, 'subgroup': best_subgroup})


if __name__ == '__main__':
    print(f"Database: {DB_PATH}")
    print("Starting server at http://localhost:5000")
    app.run(debug=True, port=5000)
