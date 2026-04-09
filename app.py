"""
LifeOptimization Web App
Flask backend serving API + frontend for managing the life optimization database.
"""
import sqlite3
import os
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

from ai_brain import optimize_schedule, build_routine_plan, apply_schedule_updates, get_ai_runtime_info, query_ai, query_ai_empowered, analyze_goals, build_today_plan

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

        # For existing Financial Theory data, default non-header rows to long-term objectives.
        conn.execute('''
            UPDATE custom_items
            SET is_long_term_objective = 1
            WHERE section_key = 'custom_financial_theory'
              AND COALESCE(is_long_term_objective, 0) = 0
              AND name NOT LIKE '━━━%'
        ''')
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
        for col, coltype in [
            ('difficulty', 'INTEGER'),
            ('time_commitment_hours', 'REAL'),
            ('price_estimate', 'REAL'),
            ('ai_priority_score', 'INTEGER'),
            ('ai_reasoning', 'TEXT'),
        ]:
            if col not in goal_columns:
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
        rows.append({
            'archive_id': f"custom_item:{row['id']}",
            'source_type': 'custom_item',
            'item_kind': 'long_term_objective' if int(row.get('is_long_term_objective') or 0) else ('task' if int(row.get('is_task') or 0) else 'goal_item'),
            **row,
        })

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
    'dashboard', 'purchases', 'fashion', 'skincare', 'pharmacology', 'goals', 'goal_archive', 'schedule', 'ai_interface'
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
    return jsonify(rows_to_list(rows))


@app.route('/api/ai/status')
def ai_status():
    runtime = get_ai_runtime_info()
    return jsonify({
        'ok': True,
        'provider': runtime['provider'],
        'model': runtime['model'],
        'configured': runtime['configured']
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
    try:
        end_hour = int(data.get('end_hour', 22) or 22)
    except (TypeError, ValueError):
        end_hour = 22
    end_hour = max(18, min(24, end_hour))

    db = get_db()
    schedule_tasks = rows_to_list(db.execute('''
        SELECT ci.id, ci.name, ci.task_time, ci.task_interval, ci.subgroup,
               ss.label as section_label, ss.page_key as section_key, ss.is_schedule
        FROM custom_items ci
        JOIN sidebar_sections ss ON ci.section_key = ss.page_key
        WHERE ss.is_schedule = 1 AND ci.is_task = 1
        ORDER BY ci.task_time, ci.sort_order, ci.name
    ''').fetchall())
    db.close()

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
        source_type = str(item.get('source_type') or '')
        item_kind = str(item.get('item_kind') or '')
        is_schedule_section = int(item.get('is_schedule_section') or 0)
        if source_type == 'custom_item' and is_schedule_section == 1:
            continue
        if source_type in {'goal', 'task'} or item_kind in {'task', 'long_term_objective', 'goal_item', 'goal'}:
            candidates.append(item)

    plan = build_today_plan(schedule_tasks, candidates, now_iso=now_iso, end_hour=end_hour)

    return jsonify({
        'ok': True,
        'mode': plan.get('mode', 'heuristic'),
        'summary': plan.get('summary', ''),
        'schedule': schedule_tasks,
        'candidates_considered': len(candidates),
        'free_minutes': int(plan.get('free_minutes') or 0),
        'recommendations': plan.get('recommendations', []),
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
    section = db.execute('SELECT is_schedule FROM sidebar_sections WHERE id=?', (section_id,)).fetchone()
    if not section:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    new_val = 0 if section['is_schedule'] else 1
    db.execute('UPDATE sidebar_sections SET is_schedule=? WHERE id=?', (new_val, section_id))
    db.commit()
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
    existing_ids = {row['id'] for row in db.execute('SELECT id FROM sidebar_sections').fetchall()}
    if any(section_id not in existing_ids for section_id in order):
        db.close()
        return api_error('order contains unknown section id', 404)
    for i, section_id in enumerate(order):
        db.execute('UPDATE sidebar_sections SET sort_order=? WHERE id=?', (i, section_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/sidebar/<int:section_id>', methods=['DELETE'])
def delete_sidebar_section(section_id):
    db = get_db()
    section = db.execute('SELECT * FROM sidebar_sections WHERE id=?', (section_id,)).fetchone()
    if not section:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    if section['page_key'] == 'dashboard':
        db.close()
        return jsonify({'error': 'Cannot delete the Dashboard'}), 403
    if not section['is_builtin']:
        db.execute('DELETE FROM custom_items WHERE section_key=?', (section['page_key'],))
    db.execute('DELETE FROM sidebar_sections WHERE id=?', (section_id,))
    db.commit()
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
    return jsonify(rows_to_list(rows))


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
    existing_ids = {
        row['id'] for row in db.execute('SELECT id FROM custom_items WHERE section_key=?', (section_key,)).fetchall()
    }
    if any(item_id not in existing_ids for item_id in order):
        db.close()
        return api_error('order contains unknown item id', 404)
    for i, item_id in enumerate(order):
        db.execute('UPDATE custom_items SET sort_order=? WHERE id=? AND section_key=?', (i, item_id, section_key))
    db.commit()
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
