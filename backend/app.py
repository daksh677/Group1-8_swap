import os
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import bcrypt
import jwt
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from db import get_connection

for env_path in [
    os.path.join(os.path.dirname(__file__), '.env'),
    os.path.join(os.path.dirname(__file__), 'db', '.env'),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

JWT_SECRET = os.getenv('JWT_SECRET', 'dev-secret')


def serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    return value


def json_error(message: str, status: int = 400):
    return jsonify({'error': message}), status


def get_user_id_from_request():
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        raise PermissionError('No token provided')

    token = header.split(' ', 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    except Exception as exc:
        raise PermissionError('Invalid token') from exc

    return payload['userId']


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')

    if not name or not email or not password:
        return json_error('Name, email, and password required', 400)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id FROM users WHERE email = %s', (email,))
        if cur.fetchone():
            return json_error('Email already registered', 409)

        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute(
            'INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)',
            (name, email, password_hash),
        )
        conn.commit()
        user_id = cur.lastrowid

        token = jwt.encode({'userId': user_id}, JWT_SECRET, algorithm='HS256')
        return jsonify({'token': token, 'user': {'id': user_id, 'name': name, 'email': email}}), 201
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return json_error('Email and password required', 400)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cur.fetchone()
        if not user:
            return json_error('Invalid email or password', 401)

        stored_hash = user['password_hash']
        if not bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8')):
            return json_error('Invalid email or password', 401)

        token = jwt.encode({'userId': user['id']}, JWT_SECRET, algorithm='HS256')
        return jsonify({
            'token': token,
            'user': {'id': user['id'], 'name': user['name'], 'email': user['email']},
        })
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/auth/me')
def auth_me():
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id, name, email, created_at FROM users WHERE id = %s', (user_id,))
        user = cur.fetchone()
        if not user:
            return json_error('User not found', 404)

        cur.execute(
            '''SELECT m.id AS member_id, m.role, h.id AS household_id, h.name AS household_name, h.invite_code
               FROM members m JOIN households h ON m.household_id = h.id
               WHERE m.user_id = %s''',
            (user_id,),
        )
        member = cur.fetchone()
        return jsonify({'user': serialize(user), 'household': serialize(member) or None})
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households', methods=['POST'])
def create_household():
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    data = request.get_json(silent=True) or {}
    name = data.get('name')
    if not name:
        return json_error('Household name required', 400)

    invite_code = str(uuid.uuid4())[:8].upper()
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('INSERT INTO households (name, invite_code) VALUES (%s, %s)', (name, invite_code))
        conn.commit()
        household_id = cur.lastrowid
        cur.execute('INSERT INTO members (household_id, user_id, role) VALUES (%s, %s, %s)', (household_id, user_id, 'admin'))
        conn.commit()

        default_chores = [
            ('Clean the kitchen', 100),
            ('Mop the floor', 200),
            ('Do the laundry', 100),
            ('Take out the trash', 50),
            ('Clean the bathroom', 150),
            ('Vacuum the living room', 100),
            ('Wash the dishes', 100),
            ('Water the plants', 50),
            ('Clean the windows', 150),
            ('Organize the pantry', 200),
        ]
        for chore_name, chore_points in default_chores:
            cur.execute(
                'INSERT INTO chores (household_id, name, points) VALUES (%s, %s, %s)',
                (household_id, chore_name, chore_points),
            )
        conn.commit()

        return jsonify({'id': household_id, 'name': name, 'invite_code': invite_code, 'role': 'admin'}), 201
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/join', methods=['POST'])
def join_household():
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    data = request.get_json(silent=True) or {}
    invite_code = data.get('invite_code')
    if not invite_code:
        return json_error('Invite code required', 400)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id FROM households WHERE invite_code = %s', (invite_code.upper(),))
        household = cur.fetchone()
        if not household:
            return json_error('Invalid invite code', 404)

        household_id = household['id']
        cur.execute('SELECT id FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        if cur.fetchone():
            return json_error('Already a member of this household', 409)

        cur.execute('SELECT id FROM members WHERE user_id = %s', (user_id,))
        if cur.fetchone():
            return json_error('User already belongs to another household', 409)

        cur.execute('SELECT id FROM household_bans WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        if cur.fetchone():
            return json_error('You were removed from this household and cannot rejoin', 403)

        cur.execute('INSERT INTO members (household_id, user_id, role) VALUES (%s, %s, %s)', (household_id, user_id, 'member'))
        conn.commit()

        cur.execute('SELECT name, invite_code FROM households WHERE id = %s', (household_id,))
        household_data = cur.fetchone()
        return jsonify({'id': household_id, 'name': household_data['name'], 'invite_code': household_data['invite_code'], 'role': 'member'})
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/members')
def household_members(household_id: int):
    try:
        get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            '''SELECT m.id, m.role, m.joined_at, u.id AS user_id, u.name, u.email
               FROM members m JOIN users u ON m.user_id = u.id
               WHERE m.household_id = %s ORDER BY m.joined_at''',
            (household_id,),
        )
        return jsonify(serialize(cur.fetchall()))
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/members/<int:member_id>', methods=['DELETE'])
def remove_member(household_id: int, member_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT role FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        admin = cur.fetchone()
        if not admin or admin['role'] != 'admin':
            return json_error('Only admin can remove members', 403)

        cur.execute('SELECT user_id, role FROM members WHERE id = %s AND household_id = %s', (member_id, household_id))
        target = cur.fetchone()
        if not target:
            return json_error('Member not found', 404)
        if target['role'] == 'admin':
            return json_error('Cannot remove the admin', 403)
        if target['user_id'] == user_id:
            return json_error('Cannot remove yourself', 403)

        cur.execute('INSERT IGNORE INTO household_bans (household_id, user_id) VALUES (%s, %s)', (household_id, target['user_id']))
        cur.execute('DELETE FROM members WHERE id = %s', (member_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/invite', methods=['PUT'])
def regenerate_invite(household_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT role FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        member = cur.fetchone()
        if not member or member['role'] != 'admin':
            return json_error('Only admin can regenerate invite code', 403)

        new_code = str(uuid.uuid4())[:8].upper()
        cur.execute('UPDATE households SET invite_code = %s WHERE id = %s', (new_code, household_id))
        conn.commit()
        return jsonify({'invite_code': new_code})
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/expenses')
def list_expenses(household_id: int):
    try:
        get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            '''SELECT e.*, u.name AS payer_name
               FROM expenses e JOIN members m ON e.payer_id = m.id JOIN users u ON m.user_id = u.id
               WHERE e.household_id = %s AND e.archived = 0 ORDER BY e.expense_date DESC, e.created_at DESC''',
            (household_id,),
        )
        expenses = cur.fetchall()

        for expense in expenses:
            cur.execute(
                '''SELECT es.member_id, es.share_amount, u.name AS member_name
                   FROM expense_shares es JOIN members m ON es.member_id = m.id JOIN users u ON m.user_id = u.id
                   WHERE es.expense_id = %s''',
                (expense['id'],),
            )
            expense['shares'] = cur.fetchall()

        return jsonify(serialize(expenses))
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/expenses', methods=['POST'])
def create_expense(household_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    description = data.get('description')
    expense_date = data.get('expense_date') or date.today().isoformat()
    split_with_member_ids = data.get('split_with_member_ids') or []

    if amount is None or not description:
        return json_error('Amount and description required', 400)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        member_row = cur.fetchone()
        if not member_row:
            return json_error('Not a member of this household', 403)
        payer_id = member_row['id']

        if split_with_member_ids:
            target_members = split_with_member_ids
        else:
            cur.execute('SELECT id FROM members WHERE household_id = %s', (household_id,))
            target_members = [row['id'] for row in cur.fetchall()]

        share_amount = round(float(amount) / len(target_members), 2)
        remainder = round(float(amount) - (share_amount * len(target_members)), 2)

        cur.execute(
            'INSERT INTO expenses (household_id, payer_id, amount, description, expense_date) VALUES (%s, %s, %s, %s, %s)',
            (household_id, payer_id, amount, description, expense_date),
        )
        expense_id = cur.lastrowid
        conn.commit()

        for i, member_id in enumerate(target_members):
            share_value = share_amount
            if i == 0:
                share_value = round(share_value + remainder, 2)
            cur.execute(
                'INSERT INTO expense_shares (expense_id, member_id, share_amount) VALUES (%s, %s, %s)',
                (expense_id, member_id, share_value),
            )
        conn.commit()
        return jsonify({'id': expense_id}), 201
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/expenses/<int:expense_id>', methods=['PUT'])
def update_expense(household_id: int, expense_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    data = request.get_json(silent=True) or {}
    amount = data.get('amount')
    description = data.get('description')
    expense_date = data.get('expense_date')

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            '''SELECT e.* FROM expenses e JOIN members m ON e.payer_id = m.id
               WHERE e.id = %s AND e.household_id = %s AND m.user_id = %s''',
            (expense_id, household_id, user_id),
        )
        expense = cur.fetchone()
        if not expense:
            return json_error('Not authorized or expense not found', 403)

        if amount is not None or description is not None or expense_date is not None:
            cur.execute(
                'UPDATE expenses SET amount = COALESCE(%s, amount), description = COALESCE(%s, description), expense_date = COALESCE(%s, expense_date) WHERE id = %s',
                (amount, description, expense_date, expense_id),
            )
            conn.commit()

        if amount is not None:
            cur.execute('SELECT share_amount FROM expense_shares WHERE expense_id = %s', (expense_id,))
            old_shares = cur.fetchall()
            count = len(old_shares)
            if count > 0:
                share_amount = round(float(amount) / count, 2)
                remainder = round(float(amount) - (share_amount * count), 2)
                cur.execute('SELECT id FROM expense_shares WHERE expense_id = %s ORDER BY id', (expense_id,))
                shares = cur.fetchall()
                for i, share in enumerate(shares):
                    share_value = share_amount
                    if i == 0:
                        share_value = round(share_value + remainder, 2)
                    cur.execute('UPDATE expense_shares SET share_amount = %s WHERE id = %s', (share_value, share['id']))
                conn.commit()

        return jsonify({'success': True})
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/expenses/<int:expense_id>', methods=['DELETE'])
def delete_expense(household_id: int, expense_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            '''SELECT e.*, m.user_id AS owner_id FROM expenses e JOIN members m ON e.payer_id = m.id
               WHERE e.id = %s AND e.household_id = %s''',
            (expense_id, household_id),
        )
        expense = cur.fetchone()
        if not expense:
            return json_error('Expense not found', 404)

        cur.execute('SELECT role FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        member = cur.fetchone()
        is_owner = expense['owner_id'] == user_id
        is_admin = bool(member and member['role'] == 'admin')
        if not is_owner and not is_admin:
            return json_error('Not authorized', 403)

        cur.execute('UPDATE expenses SET archived = 1 WHERE id = %s', (expense_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/chores')
def list_chores(household_id: int):
    try:
        get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            '''SELECT c.id, c.household_id, c.name, c.points, c.created_at
               FROM chores c
               WHERE c.household_id = %s ORDER BY c.created_at''',
            (household_id,),
        )
        return jsonify(serialize(cur.fetchall()))
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/chores', methods=['POST'])
def create_chore(household_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    data = request.get_json(silent=True) or {}
    name = data.get('name')
    points = data.get('points')

    if not name or points is None:
        return json_error('Name and points required', 400)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        member = cur.fetchone()
        if not member:
            return json_error('Not a member of this household', 403)

        cur.execute(
            'INSERT INTO chores (household_id, name, points) VALUES (%s, %s, %s)',
            (household_id, name, points),
        )
        conn.commit()
        return jsonify({'id': cur.lastrowid, 'name': name, 'points': points}), 201
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/chores/<int:chore_id>/complete', methods=['POST'])
def complete_chore(household_id: int, chore_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        member_row = cur.fetchone()
        if not member_row:
            return json_error('Not a member', 403)
        member_id = member_row['id']

        cur.execute('SELECT id, name, points FROM chores WHERE id = %s AND household_id = %s', (chore_id, household_id))
        chore = cur.fetchone()
        if not chore:
            return json_error('Chore not found', 404)

        cur.execute('INSERT INTO chore_completions (chore_id, completed_by_id) VALUES (%s, %s)', (chore_id, member_id))
        conn.commit()

        return jsonify({'success': True, 'points': chore['points'], 'chore_name': chore['name']}), 201
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/chores/leaderboard')
def chore_leaderboard(household_id: int):
    try:
        get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            '''SELECT m.id AS member_id, u.name,
                     COALESCE(SUM(c.points), 0) AS points
              FROM members m
              JOIN users u ON m.user_id = u.id
              LEFT JOIN chore_completions cc ON cc.completed_by_id = m.id
              LEFT JOIN chores c ON cc.chore_id = c.id
              WHERE m.household_id = %s
              GROUP BY m.id, u.name''',
            (household_id,),
        )
        rows = cur.fetchall()
        total_points = sum(r['points'] for r in rows)
        member_count = len(rows)

        leaderboard = []
        for r in rows:
            net = 2 * r['points'] - total_points if member_count > 0 else 0
            leaderboard.append({
                'member_id': r['member_id'],
                'name': r['name'],
                'points': r['points'],
                'net': net,
            })

        leaderboard.sort(key=lambda x: x['net'], reverse=True)
        return jsonify(leaderboard)
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/settlements')
def list_settlements(household_id: int):
    try:
        get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            '''SELECT s.*, fu.name AS from_name, tu.name AS to_name
               FROM settlements s JOIN members fm ON s.from_member_id = fm.id JOIN users fu ON fm.user_id = fu.id
               JOIN members tm ON s.to_member_id = tm.id JOIN users tu ON tm.user_id = tu.id
               WHERE s.household_id = %s ORDER BY s.settlement_date DESC, s.created_at DESC''',
            (household_id,),
        )
        return jsonify(serialize(cur.fetchall()))
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/settlements', methods=['POST'])
def create_settlement(household_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    data = request.get_json(silent=True) or {}
    from_member_id = data.get('from_member_id')
    to_member_id = data.get('to_member_id')
    amount = data.get('amount')
    settlement_date = data.get('settlement_date') or date.today().isoformat()

    if not from_member_id or not to_member_id or amount is None:
        return json_error('from_member_id, to_member_id, and amount required', 400)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        if not cur.fetchone():
            return json_error('Not a member', 403)

        cur.execute(
            'INSERT INTO settlements (household_id, from_member_id, to_member_id, amount, settlement_date) VALUES (%s, %s, %s, %s, %s)',
            (household_id, from_member_id, to_member_id, amount, settlement_date),
        )
        conn.commit()
        return jsonify({'id': cur.lastrowid}), 201
    except Exception as exc:
        conn.rollback()
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


@app.route('/api/households/<int:household_id>/balance')
def balance(household_id: int):
    try:
        user_id = get_user_id_from_request()
    except PermissionError as exc:
        return json_error(str(exc), 401)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT id FROM members WHERE household_id = %s AND user_id = %s', (household_id, user_id))
        member_row = cur.fetchone()
        if not member_row:
            return json_error('Not a member', 403)
        my_member_id = member_row['id']

        cur.execute('SELECT m.id, u.name, u.id AS user_id FROM members m JOIN users u ON m.user_id = u.id WHERE m.household_id = %s', (household_id,))
        members = cur.fetchall()

        cur.execute('SELECT IFNULL(SUM(e.amount), 0) AS total FROM expenses e WHERE e.household_id = %s AND e.payer_id = %s AND e.archived = 0', (household_id, my_member_id))
        paid = cur.fetchone()
        cur.execute('SELECT IFNULL(SUM(es.share_amount), 0) AS total FROM expenses e JOIN expense_shares es ON e.id = es.expense_id WHERE e.household_id = %s AND es.member_id = %s AND e.archived = 0', (household_id, my_member_id))
        owed_by_others = cur.fetchone()
        money_balance = round(float(paid['total']) - float(owed_by_others['total']), 2)

        cur.execute('SELECT IFNULL(SUM(c.points), 0) AS total FROM chore_completions cc JOIN chores c ON cc.chore_id = c.id WHERE c.household_id = %s AND cc.completed_by_id = %s', (household_id, my_member_id))
        my_completions = cur.fetchone()
        cur.execute('SELECT IFNULL(SUM(c.points), 0) AS total FROM chore_completions cc JOIN chores c ON cc.chore_id = c.id WHERE c.household_id = %s', (household_id,))
        all_completions = cur.fetchone()
        member_count = len(members)
        my_fair_share = float(all_completions['total']) / member_count if member_count else 0
        chore_credit = round(float(my_completions['total']) - my_fair_share, 2)

        cur.execute('SELECT IFNULL(SUM(amount), 0) AS total FROM settlements WHERE household_id = %s AND to_member_id = %s', (household_id, my_member_id))
        settlements_owed_to_me = cur.fetchone()
        cur.execute('SELECT IFNULL(SUM(amount), 0) AS total FROM settlements WHERE household_id = %s AND from_member_id = %s', (household_id, my_member_id))
        settlements_i_paid = cur.fetchone()
        net_settlements = round(float(settlements_i_paid['total']) - float(settlements_owed_to_me['total']), 2)
        combined_balance = round(money_balance + net_settlements, 2)

        breakdown = []
        for member in members:
            if member['id'] == my_member_id:
                continue
            cur.execute('SELECT IFNULL(SUM(es.share_amount), 0) AS total FROM expenses e JOIN expense_shares es ON e.id = es.expense_id WHERE e.household_id = %s AND e.payer_id = %s AND es.member_id = %s AND e.archived = 0', (household_id, my_member_id, member['id']))
            total_paid = float(cur.fetchone()['total'])
            cur.execute('SELECT IFNULL(SUM(es.share_amount), 0) AS total FROM expenses e JOIN expense_shares es ON e.id = es.expense_id WHERE e.household_id = %s AND e.payer_id = %s AND es.member_id = %s AND e.archived = 0', (household_id, member['id'], my_member_id))
            total_received = float(cur.fetchone()['total'])
            cur.execute('SELECT IFNULL(SUM(amount), 0) AS total FROM settlements WHERE household_id = %s AND from_member_id = %s AND to_member_id = %s', (household_id, my_member_id, member['id']))
            from_me = cur.fetchone()
            cur.execute('SELECT IFNULL(SUM(amount), 0) AS total FROM settlements WHERE household_id = %s AND from_member_id = %s AND to_member_id = %s', (household_id, member['id'], my_member_id))
            to_me = cur.fetchone()
            net = round(total_paid - total_received + float(from_me['total']) - float(to_me['total']), 2)
            cur.execute('SELECT COUNT(*) AS cnt FROM chore_completions cc JOIN chores c ON cc.chore_id = c.id WHERE c.household_id = %s AND cc.completed_by_id = %s', (household_id, member['id']))
            chore_count = cur.fetchone()['cnt']
            breakdown.append({'member_id': member['id'], 'user_id': member['user_id'], 'name': member['name'], 'total_paid': total_paid, 'total_received': total_received, 'net_balance': net, 'chore_count': chore_count})

        return jsonify({
            'money_balance': money_balance,
            'net_settlements': net_settlements,
            'chore_credit': chore_credit,
            'total_chore_weight_completed': float(my_completions['total']),
            'fair_share_chore_weight': my_fair_share,
            'combined_balance': combined_balance,
            'breakdown': breakdown,
        })
    except Exception as exc:
        return json_error(str(exc), 500)
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '3001')), debug=True)
