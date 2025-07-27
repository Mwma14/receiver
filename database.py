# START OF FILE database.py

import sqlite3
import logging
import json
from datetime import datetime
import threading
from functools import wraps
import os
import re

logger = logging.getLogger(__name__)

DB_FILE = os.path.abspath("bot.db")

db_lock = threading.Lock()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def db_transaction(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with db_lock:
            conn = get_db_connection()
            try:
                result = func(conn, *args, **kwargs)
                conn.commit()
                return result
            except Exception as e:
                conn.rollback()
                logger.error(f"DB transaction failed in {func.__name__}: {e}", exc_info=True)
                raise
            finally:
                conn.close()
    return wrapper

def fetch_one(query, params=()):
    with db_lock:
        conn = get_db_connection()
        try:
            result = conn.execute(query, params).fetchone()
            return dict(result) if result else None
        finally:
            conn.close()

def fetch_all(query, params=()):
    with db_lock:
        conn = get_db_connection()
        try:
            results = conn.execute(query, params).fetchall()
            return [dict(row) for row in results]
        finally:
            conn.close()

def execute_query(query, params=()):
    with db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            logger.error(f"DB execute_query failed: {e}", exc_info=True)
            raise
        finally:
            conn.close()

@db_transaction
def init_db(conn):
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, username TEXT, is_blocked INTEGER DEFAULT 0, join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, manual_balance_adjustment REAL DEFAULT 0.0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (telegram_id INTEGER PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, phone_number TEXT NOT NULL, reg_time TIMESTAMP NOT NULL, status TEXT NOT NULL, status_details TEXT, job_id TEXT, session_file TEXT, last_status_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL NOT NULL, address TEXT NOT NULL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'pending', account_ids TEXT, FOREIGN KEY (user_id) REFERENCES users (telegram_id) ON DELETE CASCADE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS countries (code TEXT PRIMARY KEY, name TEXT, flag TEXT, time INTEGER, capacity INTEGER DEFAULT -1, price_ok REAL DEFAULT 0.0, price_restricted REAL DEFAULT 0.0, forum_topic_id INTEGER, accept_restricted TEXT DEFAULT 'True', accept_gmail TEXT DEFAULT 'False')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS proxies (id INTEGER PRIMARY KEY AUTOINCREMENT, proxy TEXT UNIQUE NOT NULL)''')

    cursor.execute("PRAGMA table_info(countries)")
    columns = [row['name'] for row in cursor.fetchall()]
    if 'forum_topic_id' not in columns:
        logger.info("Adding 'forum_topic_id' column to 'countries' table.")
        cursor.execute("ALTER TABLE countries ADD COLUMN forum_topic_id INTEGER")
    if 'accept_gmail' not in columns:
        logger.info("Adding 'accept_gmail' column to 'countries' table.")
        cursor.execute("ALTER TABLE countries ADD COLUMN accept_gmail TEXT DEFAULT 'False'")

    default_settings = {
        'api_id': '25707049', 'api_hash': '676a65f1f7028e4d969c628c73fbfccc',
        'channel_username': '@TW_Receiver_News', 'admin_channel': '@RAESUPPORT', 'support_id': str(6158106622),
        'spambot_username': '@SpamBot', 'two_step_password': '123456',
        'enable_spam_check': 'True', 'enable_device_check': 'False', 'bot_status': 'ON', 'add_account_status': 'UNLOCKED',
        'min_withdraw': '1.0', 'max_withdraw': '100.0',
        'welcome_message': "🎉 Welcome to the Account Receiver Bot!\n\nTo add an account, simply send the phone number with the country code (e.g., `+12025550104`).\n\nUse the buttons below to navigate.",
        'help_message': "🆘 Bot Help & Guide\n\n🔹 `/start` - Displays the main welcome message.\n🔹 `/balance` - Shows your detailed balance and allows withdrawal.\n🔹 `/rules` - View the bot's rules.\n🔹 `/cancel` - Stops any ongoing process you started.",
        'rules_message': "📜 Bot Rules\n\n1. Do not use the same phone number multiple times.\n2. Any attempt to exploit or cheat the bot will result in a permanent ban without appeal.\n3. The administration is not responsible for any account limitations or issues that arise after a successful confirmation."
    }
    for key, value in default_settings.items(): cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    if cursor.execute("SELECT COUNT(*) FROM countries").fetchone()[0] == 0:
        default_countries = {
            "+44": {"name": "UK", "flag": "🇬🇧", "time": 600, "capacity": 100, "price_ok": 0.62, "price_restricted": 0.10, "forum_topic_id": None, "accept_restricted": "True", "accept_gmail": "False"},
            "+95": {"name": "Myanmar", "flag": "🇲🇲", "time": 60, "capacity": 50, "price_ok": 0.18, "price_restricted": 0.0, "forum_topic_id": None, "accept_restricted": "True", "accept_gmail": "False"}
        }
        for code, data in default_countries.items(): cursor.execute("INSERT OR REPLACE INTO countries (code, name, flag, time, capacity, price_ok, price_restricted, forum_topic_id, accept_restricted, accept_gmail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (code, data['name'], data['flag'], data['time'], data['capacity'], data['price_ok'], data['price_restricted'], data['forum_topic_id'], data['accept_restricted'], data['accept_gmail']))
    
    logger.info("Database initialized/checked successfully.")


@db_transaction
def process_withdrawal_request(conn, user_id, address, amount_to_withdraw):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO withdrawals (user_id, amount, address, status) VALUES (?, ?, ?, ?)",
        (user_id, amount_to_withdraw, address, 'pending')
    )
    withdrawal_id = cursor.lastrowid
    logger.info(f"Created pending withdrawal request ID {withdrawal_id} for user {user_id} of ${amount_to_withdraw:.2f}.")
    return withdrawal_id

@db_transaction
def confirm_withdrawal(conn, withdrawal_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM withdrawals WHERE id = ? AND status = 'pending'", (withdrawal_id,))
    withdrawal = cursor.fetchone()
    if not withdrawal:
        return None 

    cursor.execute("UPDATE withdrawals SET status = 'completed' WHERE id = ?", (withdrawal_id,))
    
    user_id = withdrawal['user_id']
    amount = withdrawal['amount']

    _, _, earned_balance, manual_adjustment, withdrawable_accounts = get_user_balance_details(user_id)
    
    if withdrawable_accounts:
        account_ids = [acc['id'] for acc in withdrawable_accounts]
        account_ids_json = json.dumps(account_ids)
        placeholders = ','.join('?' for _ in account_ids)
        cursor.execute(f"UPDATE accounts SET status = 'withdrawn' WHERE id IN ({placeholders})", account_ids)
        cursor.execute("UPDATE withdrawals SET account_ids = ? WHERE id = ?", (account_ids_json, withdrawal_id))

    manual_part_of_withdrawal = max(0, amount - earned_balance)
    if manual_part_of_withdrawal > 0:
        cursor.execute(
            "UPDATE users SET manual_balance_adjustment = manual_balance_adjustment - ? WHERE telegram_id = ?",
            (manual_part_of_withdrawal, user_id)
        )

    logger.info(f"Confirmed withdrawal ID {withdrawal_id} for user {user_id}. Amount: ${amount:.2f}")
    return dict(withdrawal)

def get_user_balance_details(uid):
    cfg = get_countries_config()
    pending_withdrawal_sum = fetch_one("SELECT SUM(amount) FROM withdrawals WHERE user_id = ? AND status = 'pending'", (uid,))
    pending_amount = (pending_withdrawal_sum or {'SUM(amount)': 0.0})['SUM(amount)'] or 0.0

    accs = fetch_all("SELECT id, phone_number, status FROM accounts WHERE user_id = ?", (uid,))
    user_row = fetch_one("SELECT manual_balance_adjustment FROM users WHERE telegram_id = ?", (uid,))
    manual_adjustment = (user_row or {'manual_balance_adjustment': 0.0})['manual_balance_adjustment']
    
    summary, earned_balance, withdrawable_accs = {}, 0.0, []
    for acc in accs:
        summary[acc['status']] = summary.get(acc['status'], 0) + 1
        if acc['status'] in ['ok', 'restricted']:
            withdrawable_accs.append(acc)
            mc_code = next((c for c in sorted(cfg.keys(), key=len, reverse=True) if acc['phone_number'].startswith(c)), None)
            if mc_code:
                country_cfg = cfg.get(mc_code, {})
                if acc['status'] == 'ok': earned_balance += country_cfg.get('price_ok', 0.0)
                elif acc['status'] == 'restricted': earned_balance += country_cfg.get('price_restricted', 0.0)

    total_balance = round(earned_balance + manual_adjustment - pending_amount, 2)
    return summary, total_balance, earned_balance, manual_adjustment, withdrawable_accs

def get_countries_config(): return {row['code']: row for row in fetch_all("SELECT * FROM countries ORDER BY name")}
def get_country_by_code(code): return fetch_one("SELECT * FROM countries WHERE code = ?", (code,))
def get_country_account_count(code):
    res = fetch_one("SELECT COUNT(*) as c FROM accounts WHERE phone_number LIKE ?", (f"{code}%",))
    return res['c'] if res else 0

# NEW FUNCTION: To get counts for the new File Manager UI.
def get_country_account_counts_by_status(code_prefix: str): 
    return fetch_all("SELECT status, COUNT(*) as count FROM accounts WHERE phone_number LIKE ? GROUP BY status", (f"{code_prefix}%",))

def update_country_value(code, key, value): return execute_query(f"UPDATE countries SET {key} = ? WHERE code = ?", (value, code))
def add_country(code, name, flag, time, capacity, price_ok, price_restricted, forum_topic_id, accept_restricted, accept_gmail='False'): execute_query("INSERT OR REPLACE INTO countries (code, name, flag, time, capacity, price_ok, price_restricted, forum_topic_id, accept_restricted, accept_gmail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (code, name, flag, time, capacity, price_ok, price_restricted, forum_topic_id, accept_restricted, accept_gmail))
def delete_country(code): return execute_query("DELETE FROM countries WHERE code = ?", (code,))
def add_admin(tid): return execute_query("INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)", (tid,))
def remove_admin(tid): return execute_query("DELETE FROM admins WHERE telegram_id = ?", (tid,))
def is_admin(tid): return fetch_one("SELECT 1 FROM admins WHERE telegram_id = ?", (tid,)) is not None
def get_all_admins(): return fetch_all("SELECT * FROM admins")
def get_setting(key, default=None):
    result = fetch_one("SELECT value FROM settings WHERE key = ?", (key,))
    return result['value'] if result else default
def get_all_settings(): return {row['key']: row['value'] for row in fetch_all("SELECT * FROM settings")}
def set_setting(key, value): return execute_query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
def get_all_accounts_by_status_and_country(status: str, code_prefix: str): return fetch_all("SELECT * FROM accounts WHERE status = ? AND phone_number LIKE ?", (status, f"{code_prefix}%"))
def get_or_create_user(tid, username=None):
    user = fetch_one("SELECT * FROM users WHERE telegram_id = ?", (tid,))
    if not user:
        execute_query("INSERT INTO users (telegram_id, username, join_date) VALUES (?, ?, ?)", (tid, username, datetime.utcnow()))
        return fetch_one("SELECT * FROM users WHERE telegram_id = ?", (tid,)), True
    elif username and user.get('username') != username:
        execute_query("UPDATE users SET username = ? WHERE telegram_id = ?", (username, tid))
    return user, False
def get_user_by_id(tid): return fetch_one("SELECT * FROM users WHERE telegram_id = ?", (tid,))
def get_all_users(page=1, limit=10): return fetch_all("SELECT u.*, (SELECT COUNT(*) FROM accounts WHERE user_id = u.telegram_id) as account_count FROM users u ORDER BY join_date DESC LIMIT ? OFFSET ?", (limit, (page - 1) * limit))
def count_all_users(): return fetch_one("SELECT COUNT(*) as c FROM users")['c']
def block_user(tid): return execute_query("UPDATE users SET is_blocked = 1 WHERE telegram_id = ?", (tid,))
def unblock_user(tid): return execute_query("UPDATE users SET is_blocked = 0 WHERE telegram_id = ?", (tid,))
def get_all_user_ids(only_non_blocked=True):
    query = "SELECT telegram_id FROM users"
    if only_non_blocked: query += " WHERE is_blocked = 0"
    return [row['telegram_id'] for row in fetch_all(query)]
def adjust_user_balance(user_id, amount_to_add): return execute_query("UPDATE users SET manual_balance_adjustment = manual_balance_adjustment + ? WHERE telegram_id = ?", (amount_to_add, user_id))
def add_proxy(proxy_str): return execute_query("INSERT OR IGNORE INTO proxies (proxy) VALUES (?)", (proxy_str,))
def remove_proxy_by_id(proxy_id): return execute_query("DELETE FROM proxies WHERE id = ?", (proxy_id,))
def get_all_proxies(page=1, limit=10): return fetch_all("SELECT * FROM proxies ORDER BY id LIMIT ? OFFSET ?", (limit, (page - 1) * limit))
def get_random_proxy():
    proxy = fetch_one("SELECT proxy FROM proxies ORDER BY RANDOM() LIMIT 1")
    return proxy['proxy'] if proxy else None
def count_all_proxies(): return fetch_one("SELECT COUNT(*) as c FROM proxies")['c']
def check_phone_exists(p_num): return fetch_one("SELECT 1 FROM accounts WHERE phone_number = ?", (p_num,)) is not None
def add_account(uid, p, status, jid, sfile):
    execute_query("INSERT INTO accounts (user_id, phone_number, reg_time, status, job_id, session_file) VALUES (?, ?, ?, ?, ?, ?)", (uid, p, datetime.utcnow(), status, jid, sfile))
    return fetch_one("SELECT last_insert_rowid() as id")['id']
def update_account_status(jid, new_status, status_details=""): return execute_query("UPDATE accounts SET status = ?, status_details = ?, last_status_update = ? WHERE job_id = ?", (new_status, status_details, datetime.utcnow(), jid))
def find_account_by_job_id(jid): return fetch_one("SELECT * FROM accounts WHERE job_id = ?", (jid,))
def get_all_accounts_paginated(page=1, limit=10): return fetch_all("SELECT a.id, a.phone_number, a.status, a.user_id, u.username FROM accounts a LEFT JOIN users u ON a.user_id = u.telegram_id ORDER BY a.reg_time DESC LIMIT ? OFFSET ?", (limit, (page - 1) * limit))
def count_all_accounts(): return fetch_one("SELECT COUNT(*) as c FROM accounts")['c']
def get_accounts_for_reprocessing(): return fetch_all("SELECT * FROM accounts WHERE status = 'pending_session_termination' AND last_status_update <= datetime('now', '-24 hours')")
def get_stuck_pending_accounts(): return fetch_all("SELECT * FROM accounts WHERE status = 'pending_confirmation' AND reg_time <= datetime('now', '-30 minutes')")
def get_error_accounts(): return fetch_all("SELECT * FROM accounts WHERE status = 'error'")
def get_problematic_accounts_by_user(user_id): return fetch_all("SELECT * FROM accounts WHERE user_id = ? AND status IN ('pending_confirmation', 'error')", (user_id,))
def get_all_withdrawals(page=1, limit=10): return fetch_all("SELECT w.*, u.username FROM withdrawals w JOIN users u ON w.user_id = u.telegram_id ORDER BY w.timestamp DESC LIMIT ? OFFSET ?", (limit, (page-1)*limit))
def count_all_withdrawals(): return fetch_one("SELECT COUNT(*) as c FROM withdrawals")['c']
def get_bot_stats():
    return {
        "total_users": count_all_users(), "blocked_users": fetch_one("SELECT COUNT(*) as c FROM users WHERE is_blocked = 1")['c'],
        "total_accounts": count_all_accounts(), "accounts_by_status": {r['status']: r['c'] for r in fetch_all("SELECT status, COUNT(*) as c FROM accounts GROUP BY status")},
        "total_withdrawals_amount": (fetch_one("SELECT SUM(amount) as s FROM withdrawals WHERE status = 'completed'") or {'s': 0})['s'] or 0.0,
        "total_withdrawals_count": count_all_withdrawals(), "total_proxies": count_all_proxies(),
    }
@db_transaction
def purge_user_data(conn, user_id):
    cursor = conn.cursor()
    sessions = cursor.execute("SELECT session_file FROM accounts WHERE user_id = ?", (user_id,)).fetchall()
    cursor.execute("DELETE FROM users WHERE telegram_id = ?", (user_id,))
    deleted_count = cursor.rowcount
    if deleted_count == 0: return 0, []
    session_files_to_delete = [row['session_file'] for row in sessions if row['session_file']]
    return deleted_count, session_files_to_delete

# END OF FILE database.py