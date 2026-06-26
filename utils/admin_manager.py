# --- START OF FILE utils/admin_manager.py ---

import json
import os
import sqlite3
import time
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'config', 'database.db')
OWNER_FILE = os.path.join(BASE_DIR, 'config', 'owner.json')
MOOD_FILE = os.path.join(BASE_DIR, 'config', 'bot_moods.json')
LANG_FILE = os.path.join(BASE_DIR, 'config', 'bot_lang.json')

def get_db_connection():
    # ৩০ সেকেন্ডের বিজি টাইমআউট ও ওযাল মোড সক্রিয় করা হয়েছে লকিং এড়ানোর জন্য
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn

def _execute_with_retry(func, *args, retries=5, delay=0.5):
    """ডাটাবেজ লক থাকলে সেটি নির্দিষ্ট সময় পর পর পুনরায় চেষ্টা করার মেকানিজম"""
    for attempt in range(retries):
        try:
            return func(*args)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                time.sleep(delay)
            else:
                raise e

def _get_bot_name_raw(bot_uid):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM bots WHERE ingame_uid=? OR login_uid=? OR name=?", (str(bot_uid), str(bot_uid), str(bot_uid)))
        row = cursor.fetchone()
        return row[0] if row else str(bot_uid)
    finally:
        conn.close()

def _get_bot_name(bot_uid):
    try:
        return _execute_with_retry(_get_bot_name_raw, bot_uid)
    except:
        return str(bot_uid)

def _get_admin_data_raw(bot_name):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM admins WHERE bot_name=?", (bot_name,))
        row = cursor.fetchone()
        if row: 
            return json.loads(row[0])
    finally:
        conn.close()
    return {"Bot_Name": bot_name, "Guild_ID": None, "Admins": [], "Members": {}}

def _get_admin_data(bot_uid_or_name):
    bot_name = _get_bot_name(bot_uid_or_name)
    try:
        return _execute_with_retry(_get_admin_data_raw, bot_name)
    except:
        return {"Bot_Name": bot_name, "Guild_ID": None, "Admins": [], "Members": {}}

def _save_admin_data_raw(bot_name, data):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO admins (bot_name, guild_id, data) VALUES (?, ?, ?)", 
                       (bot_name, str(data.get("Guild_ID", "")), json.dumps(data)))
        conn.commit()
    finally:
        conn.close()

def _save_admin_data(bot_uid_or_name, data):
    bot_name = _get_bot_name(bot_uid_or_name)
    try:
        _execute_with_retry(_save_admin_data_raw, bot_name, data)
        try:
            import mongo_sync
            threading.Thread(target=mongo_sync.push_admin_to_mongo, args=(bot_name, data)).start()
        except: 
            pass
    except Exception as e:
        print(f"[Admin Manager] Error saving admin data: {e}")

def init_bot(bot_uid, bot_name, guild_id):
    if not os.path.exists(os.path.dirname(OWNER_FILE)):
        os.makedirs(os.path.dirname(OWNER_FILE), exist_ok=True)
    if not os.path.exists(OWNER_FILE):
        with open(OWNER_FILE, 'w', encoding='utf-8') as f:
            json.dump({"Owners": ["784579784"]}, f, indent=4)

    data = _get_admin_data(bot_name)
    data["Bot_Name"] = bot_name
    data["Guild_ID"] = guild_id
    if "Admins" not in data: data["Admins"] = []
    if "Members" not in data: data["Members"] = {}
    _save_admin_data(bot_name, data)

def is_owner(uid):
    uid_str = str(uid)
    try:
        with open(OWNER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if uid_str in [str(o) for o in data.get("Owners", [])]: return True
    except: pass
    return False

def can_auto_join(bot_uid, inviter_uid):
    i_uid = str(inviter_uid)
    if is_owner(i_uid): return True
    data = _get_admin_data(bot_uid)
    if i_uid in data.get("Admins", []): return True
    members = data.get("Members", {})
    if i_uid in members:
        expire_time = members[i_uid].get("expires_at", 0)
        if time.time() < expire_time: return True
        else: 
            del data["Members"][i_uid]
            _save_admin_data(bot_uid, data)
    return False

def add_guild_member(bot_uid, inviter_uid, guild_id, player_name="Unknown"):
    data = _get_admin_data(bot_uid)
    i_uid = str(inviter_uid)
    data["Members"][i_uid] = {
        "name": player_name, "guild_id": guild_id, "expires_at": int(time.time()) + 86400
    }
    _save_admin_data(bot_uid, data)

def add_admin(bot_uid, admin_uids):
    data = _get_admin_data(bot_uid)
    current_admins = data.get("Admins", [])
    added = 0
    for uid in admin_uids:
        s_uid = str(uid)
        if s_uid not in current_admins:
            current_admins.append(s_uid)
            added += 1
    data["Admins"] = current_admins
    _save_admin_data(bot_uid, data)
    return added

def remove_admin(bot_uid, admin_uids):
    data = _get_admin_data(bot_uid)
    current_admins = data.get("Admins", [])
    removed = 0
    for uid in admin_uids:
        s_uid = str(uid)
        if s_uid in current_admins:
            current_admins.remove(s_uid)
            removed += 1
    data["Admins"] = current_admins
    _save_admin_data(bot_uid, data)
    return removed

def get_admins(bot_uid):
    data = _get_admin_data(bot_uid)
    return data.get("Admins", [])

def load_bot_mood(bot_uid):
    if not os.path.exists(MOOD_FILE): return "normal"
    try:
        with open(MOOD_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(str(bot_uid), "normal")
    except: return "normal"

def save_bot_mood(bot_uid, mood):
    data = {}
    if os.path.exists(MOOD_FILE):
        try:
            with open(MOOD_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        except: pass
    data[str(bot_uid)] = mood
    try:
        with open(MOOD_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
    except: pass

def load_bot_lang(bot_uid):
    if not os.path.exists(LANG_FILE): return "en"
    try:
        with open(LANG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(str(bot_uid), "en")
    except: return "en"

def save_bot_lang(bot_uid, lang):
    data = {}
    if os.path.exists(LANG_FILE):
        try:
            with open(LANG_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
        except: pass
    data[str(bot_uid)] = lang
    try:
        with open(LANG_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
    except: pass

# --- END OF FILE utils/admin_manager.py ---