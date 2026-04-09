"""
LifeOptimization DB Helper
Quick CLI to query and manage the database.

Usage:
    python db_helper.py <command> [args]

Commands:
    show <table>            Show all rows from a table
    routines                Show skincare routines in order
    purchases [status]      Show purchases, optionally filtered by status color
    add-fashion <cat> <name> <status> [link] [replink]
    add-skincare <routine> <name> <status> <order> [link]
    add-goal <area> <title> [description]
    update-status <table> <id> <new_status_color>
    tables                  List all tables
"""
import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lifeoptimization.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def show_table(table_name):
    conn = get_conn()
    safe_tables = [r['name'] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' OR type='view'").fetchall()]
    if table_name not in safe_tables:
        print(f"Unknown table: {table_name}. Available: {safe_tables}")
        return
    rows = conn.execute(f'SELECT * FROM [{table_name}]').fetchall()
    if not rows:
        print(f"(empty)")
        return
    cols = rows[0].keys()
    print(' | '.join(cols))
    print('-' * 80)
    for r in rows:
        print(' | '.join(str(r[c]) for c in cols))
    conn.close()


def show_routines():
    conn = get_conn()
    routines = conn.execute('SELECT * FROM skincare_routines ORDER BY sort_order').fetchall()
    for routine in routines:
        print(f"\n{'='*50}")
        print(f"  {routine['name']}")
        print(f"{'='*50}")
        products = conn.execute('''
            SELECT sp.*, s.color, s.description as status_desc 
            FROM skincare_products sp 
            JOIN statuses s ON sp.status_id = s.id 
            WHERE sp.routine_id = ? AND sp.is_wanted = 0
            ORDER BY sp.step_order
        ''', (routine['id'],)).fetchall()
        for i, p in enumerate(products, 1):
            print(f"  {i}. [{p['color']}] {p['name']}")

    # Wanted products
    wanted = conn.execute('''
        SELECT sp.*, s.color FROM skincare_products sp
        JOIN statuses s ON sp.status_id = s.id
        WHERE sp.is_wanted = 1
    ''').fetchall()
    if wanted:
        print(f"\n{'='*50}")
        print(f"  Wanted Products")
        print(f"{'='*50}")
        for p in wanted:
            print(f"  - [{p['color']}] {p['name']}")
    conn.close()


def show_purchases(status_filter=None):
    conn = get_conn()
    query = 'SELECT * FROM v_all_purchases'
    params = []
    if status_filter:
        query += ' WHERE status_color = ?'
        params.append(status_filter)
    rows = conn.execute(query, params).fetchall()
    for r in rows:
        print(f"  [{r['status_color']:6}] ({r['item_type']:12}) {r['name']}"
              f"  | {r['category'] or ''}")
    conn.close()


def add_fashion(cat, name, status_color, link=None, rep_link=None):
    conn = get_conn()
    cat_id = conn.execute('SELECT id FROM fashion_categories WHERE name = ?', (cat,)).fetchone()
    if not cat_id:
        print(f"Unknown category: {cat}")
        return
    status = conn.execute('SELECT id FROM statuses WHERE color = ?', (status_color,)).fetchone()
    if not status:
        print(f"Unknown status color: {status_color}")
        return
    conn.execute(
        'INSERT INTO fashion_items (category_id, name, status_id, link, rep_link) VALUES (?,?,?,?,?)',
        (cat_id['id'], name, status['id'], link, rep_link))
    conn.commit()
    print(f"Added fashion item: {name}")
    conn.close()


def add_skincare(routine_name, name, status_color, order, link=None):
    conn = get_conn()
    routine = conn.execute('SELECT id FROM skincare_routines WHERE name = ?', (routine_name,)).fetchone()
    if not routine:
        print(f"Unknown routine: {routine_name}")
        return
    status = conn.execute('SELECT id FROM statuses WHERE color = ?', (status_color,)).fetchone()
    if not status:
        print(f"Unknown status color: {status_color}")
        return
    conn.execute(
        'INSERT INTO skincare_products (routine_id, name, status_id, step_order, link) VALUES (?,?,?,?,?)',
        (routine['id'], name, status['id'], int(order), link))
    conn.commit()
    print(f"Added skincare product: {name}")
    conn.close()


def add_goal(area_name, title, description=None):
    conn = get_conn()
    area = conn.execute('SELECT id FROM life_areas WHERE name = ?', (area_name,)).fetchone()
    if not area:
        print(f"Unknown life area: {area_name}")
        return
    conn.execute(
        'INSERT INTO goals (life_area_id, title, description) VALUES (?,?,?)',
        (area['id'], title, description))
    conn.commit()
    print(f"Added goal: {title} ({area_name})")
    conn.close()


def update_status(table_name, item_id, new_color):
    conn = get_conn()
    safe_tables = ['fashion_items', 'skincare_products', 'pharmacology_items', 'misc_items']
    if table_name not in safe_tables:
        print(f"Can only update status on: {safe_tables}")
        return
    status = conn.execute('SELECT id FROM statuses WHERE color = ?', (new_color,)).fetchone()
    if not status:
        print(f"Unknown status color: {new_color}")
        return
    conn.execute(f'UPDATE [{table_name}] SET status_id = ?, updated_at = datetime("now") WHERE id = ?',
                 (status['id'], int(item_id)))
    conn.commit()
    print(f"Updated {table_name} item {item_id} to status: {new_color}")
    conn.close()


def list_tables():
    conn = get_conn()
    tables = conn.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name").fetchall()
    for t in tables:
        print(f"  [{t['type']}] {t['name']}")
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == 'show' and len(sys.argv) >= 3:
        show_table(sys.argv[2])
    elif cmd == 'routines':
        show_routines()
    elif cmd == 'purchases':
        show_purchases(sys.argv[2] if len(sys.argv) >= 3 else None)
    elif cmd == 'add-fashion' and len(sys.argv) >= 5:
        add_fashion(sys.argv[2], sys.argv[3], sys.argv[4],
                    sys.argv[5] if len(sys.argv) > 5 else None,
                    sys.argv[6] if len(sys.argv) > 6 else None)
    elif cmd == 'add-skincare' and len(sys.argv) >= 6:
        add_skincare(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
                     sys.argv[6] if len(sys.argv) > 6 else None)
    elif cmd == 'add-goal' and len(sys.argv) >= 4:
        add_goal(sys.argv[2], sys.argv[3],
                 sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == 'update-status' and len(sys.argv) >= 5:
        update_status(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == 'tables':
        list_tables()
    else:
        print(__doc__)
