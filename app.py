"""
LifeOptimization Web App
Flask backend serving API + frontend for managing the life optimization database.
"""
import sqlite3
import os
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder='static')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lifeoptimization.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


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
    data = request.json
    db = get_db()
    db.execute(
        'INSERT INTO fashion_items (category_id, name, status_id, link, rep_link, notes) VALUES (?,?,?,?,?,?)',
        (data['category_id'], data['name'], data['status_id'],
         data.get('link'), data.get('rep_link'), data.get('notes')))
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/fashion/<int:item_id>', methods=['PUT'])
def update_fashion_item(item_id):
    data = request.json
    db = get_db()
    db.execute('''UPDATE fashion_items 
                  SET category_id=?, name=?, status_id=?, link=?, rep_link=?, notes=?, updated_at=datetime('now')
                  WHERE id=?''',
               (data['category_id'], data['name'], data['status_id'],
                data.get('link'), data.get('rep_link'), data.get('notes'), item_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/fashion/<int:item_id>', methods=['DELETE'])
def delete_fashion_item(item_id):
    db = get_db()
    db.execute('DELETE FROM fashion_items WHERE id=?', (item_id,))
    db.commit()
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
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    db = get_db()
    existing = db.execute('SELECT id FROM skincare_routines WHERE name=?', (name,)).fetchone()
    if existing:
        db.close()
        return jsonify({'error': 'Routine already exists'}), 409
    max_order = db.execute('SELECT MAX(sort_order) FROM skincare_routines').fetchone()[0] or 0
    db.execute('INSERT INTO skincare_routines (name, sort_order) VALUES (?,?)', (name, max_order + 1))
    db.commit()
    new_id = db.execute('SELECT id FROM skincare_routines WHERE name=?', (name,)).fetchone()['id']
    db.close()
    return jsonify({'ok': True, 'id': new_id}), 201


@app.route('/api/skincare/routines/<int:routine_id>', methods=['DELETE'])
def delete_skincare_routine(routine_id):
    db = get_db()
    # Move products from this routine to "wanted" (unassigned)
    db.execute('UPDATE skincare_products SET routine_id=NULL, is_wanted=1 WHERE routine_id=?', (routine_id,))
    db.execute('DELETE FROM skincare_routines WHERE id=?', (routine_id,))
    db.commit()
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
    data = request.json
    db = get_db()
    db.execute(
        'INSERT INTO skincare_products (routine_id, name, status_id, step_order, is_wanted, link, notes) VALUES (?,?,?,?,?,?,?)',
        (data.get('routine_id'), data['name'], data['status_id'],
         data.get('step_order', 0), data.get('is_wanted', 0),
         data.get('link'), data.get('notes')))
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/skincare/<int:item_id>', methods=['PUT'])
def update_skincare_product(item_id):
    data = request.json
    db = get_db()
    db.execute('''UPDATE skincare_products 
                  SET routine_id=?, name=?, status_id=?, step_order=?, is_wanted=?, link=?, notes=?, updated_at=datetime('now')
                  WHERE id=?''',
               (data.get('routine_id'), data['name'], data['status_id'],
                data.get('step_order', 0), data.get('is_wanted', 0),
                data.get('link'), data.get('notes'), item_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/skincare/<int:item_id>', methods=['DELETE'])
def delete_skincare_product(item_id):
    db = get_db()
    db.execute('DELETE FROM skincare_products WHERE id=?', (item_id,))
    db.commit()
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
    data = request.json
    db = get_db()
    db.execute(
        'INSERT INTO pharmacology_items (name, status_id, dosage, frequency, link, notes) VALUES (?,?,?,?,?,?)',
        (data['name'], data['status_id'], data.get('dosage'),
         data.get('frequency'), data.get('link'), data.get('notes')))
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/pharmacology/<int:item_id>', methods=['PUT'])
def update_pharmacology(item_id):
    data = request.json
    db = get_db()
    db.execute('''UPDATE pharmacology_items 
                  SET name=?, status_id=?, dosage=?, frequency=?, link=?, notes=?, updated_at=datetime('now')
                  WHERE id=?''',
               (data['name'], data['status_id'], data.get('dosage'),
                data.get('frequency'), data.get('link'), data.get('notes'), item_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/pharmacology/<int:item_id>', methods=['DELETE'])
def delete_pharmacology(item_id):
    db = get_db()
    db.execute('DELETE FROM pharmacology_items WHERE id=?', (item_id,))
    db.commit()
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
    data = request.json
    db = get_db()
    db.execute(
        'INSERT INTO goals (life_area_id, title, description, target_date, priority) VALUES (?,?,?,?,?)',
        (data['life_area_id'], data['title'], data.get('description'),
         data.get('target_date'), data.get('priority', 0)))
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/goals/<int:goal_id>', methods=['PUT'])
def update_goal(goal_id):
    data = request.json
    db = get_db()
    db.execute('''UPDATE goals 
                  SET life_area_id=?, title=?, description=?, target_date=?, priority=?, is_completed=?, updated_at=datetime('now')
                  WHERE id=?''',
               (data['life_area_id'], data['title'], data.get('description'),
                data.get('target_date'), data.get('priority', 0),
                data.get('is_completed', 0), goal_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/goals/<int:goal_id>', methods=['DELETE'])
def delete_goal(goal_id):
    db = get_db()
    db.execute('DELETE FROM goals WHERE id=?', (goal_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})


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
    rows = db.execute('SELECT * FROM sidebar_sections ORDER BY sort_order, id').fetchall()
    db.close()
    return jsonify(rows_to_list(rows))


BUILTIN_PAGES = {
    'dashboard', 'purchases', 'fashion', 'skincare', 'pharmacology', 'goals', 'schedule'
}


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


@app.route('/api/sidebar', methods=['POST'])
def add_sidebar_section():
    data = request.json
    label = data.get('label', '').strip()
    group_name = data.get('group_name', '').strip()
    if not label or not group_name:
        return jsonify({'error': 'label and group_name required'}), 400
    # Check if this matches a known builtin page key
    candidate_key = label.lower().replace(' ', '_')
    if candidate_key in BUILTIN_PAGES:
        page_key = candidate_key
        is_builtin = 1
    else:
        page_key = 'custom_' + candidate_key
        is_builtin = 0
    db = get_db()
    existing = db.execute('SELECT id FROM sidebar_sections WHERE page_key=?', (page_key,)).fetchone()
    if existing:
        db.close()
        return jsonify({'error': 'Section already exists'}), 409
    max_order = db.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
    db.execute(
        'INSERT INTO sidebar_sections (group_name, label, page_key, sort_order, is_builtin) VALUES (?,?,?,?,?)',
        (group_name, label, page_key, max_order + 1, is_builtin))
    db.commit()
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
    data = request.json
    order = data.get('order', [])
    if not order:
        return jsonify({'error': 'order required'}), 400
    db = get_db()
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
    data = request.json
    db = get_db()
    db.execute(
        'INSERT INTO custom_items (section_key, name, status_id, link, notes, sort_order, is_task, task_time, task_count, task_interval, subgroup, is_quick_objective) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (section_key, data['name'], data['status_id'],
         data.get('link'), data.get('notes'), data.get('sort_order', 0),
         data.get('is_task', 0), data.get('task_time'), data.get('task_count'), data.get('task_interval'), data.get('subgroup'),
         data.get('is_quick_objective', 0)))
    db.commit()
    db.close()
    return jsonify({'ok': True}), 201


@app.route('/api/custom/<section_key>/<int:item_id>', methods=['PUT'])
def update_custom_item(section_key, item_id):
    data = request.json
    db = get_db()
    db.execute('''UPDATE custom_items
                  SET name=?, status_id=?, link=?, notes=?, sort_order=?, is_task=?, task_time=?, task_count=?, task_interval=?, subgroup=?, is_quick_objective=?, updated_at=datetime('now')
                  WHERE id=? AND section_key=?''',
               (data['name'], data['status_id'], data.get('link'),
                data.get('notes'), data.get('sort_order', 0),
                data.get('is_task', 0), data.get('task_time'), data.get('task_count'), data.get('task_interval'),
                data.get('subgroup'), data.get('is_quick_objective', 0),
                item_id, section_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/custom/<section_key>/reorder', methods=['PUT'])
def reorder_custom_items(section_key):
    data = request.json
    order = data.get('order', [])
    if not order:
        return jsonify({'error': 'order required'}), 400
    db = get_db()
    for i, item_id in enumerate(order):
        db.execute('UPDATE custom_items SET sort_order=? WHERE id=? AND section_key=?', (i, item_id, section_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})


@app.route('/api/custom/<section_key>/<int:item_id>', methods=['DELETE'])
def delete_custom_item(section_key, item_id):
    db = get_db()
    db.execute('DELETE FROM custom_items WHERE id=? AND section_key=?', (item_id, section_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})


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
