# filepath: mongo_sync.py
# -*- coding: utf-8 -*-
# START OF FILE mongo_sync.py
import asyncio
import os
import json
import sqlite3
import random
import threading
import time
import uuid
import ssl
import sys
import re
from datetime import datetime

# পরম পাথ (Absolute Path) ও ডিরেক্টরি রেজোলিউশন প্যাচ
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import dns.resolver
try:
    dns.resolver.default_resolver = dns.resolver.Resolver()
    dns.resolver.default_resolver.nameservers.extend(['8.8.8.8', '1.1.1.1'])
except Exception as e:
    try:
        dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
        dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']
    except Exception:
        pass

try:
    from pymongo import MongoClient
except ImportError:
    print("[!] 'pymongo' is not installed. Please run 'pip install pymongo'")

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    import certifi
    import aiohttp
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("[!] Cryptographic libraries are missing. Run 'pip install pycryptodome aiohttp certifi'")

try:
    import garena_api as bot_module
except ImportError:
    print("[!] 'garena_api.py' not found in same folder.")

MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://newhrmunna2027_db_user:munna2288@cluster0.xoaeyib.mongodb.net/?appName=Cluster0")

client = None
db_mongo = None
col_system = None
col_accounts = None
col_admins = None
col_friends = None
col_guild_members = None

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command('ping')
    db_mongo = client['Esports_Bot_Panel_2']
    col_system = db_mongo['system_configs']  
    col_accounts = db_mongo['bot_accounts']  
    col_admins = db_mongo['bot_admins']
    col_friends = db_mongo['bot_friends']
    col_guild_members = db_mongo['guild_members']
    print("[MONGO] Successfully connected to MongoDB Atlas. Syncing Enabled.")
except Exception as e:
    client = None
    db_mongo = None
    col_system = None
    col_accounts = None
    col_admins = None
    col_friends = None
    col_guild_members = None
    print(f"[MONGO ERROR] Connection Failed (Running in Offline/Local SQLite Mode): {e}")

DB_PATH = os.path.join(BASE_DIR, 'config', 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn

def init_sqlite():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT, uid TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS bots (name TEXT PRIMARY KEY, login_uid TEXT, password TEXT, ingame_uid TEXT, owner TEXT, folder TEXT, bot_number INTEGER)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS profiles (ingame_uid TEXT PRIMARY KEY, data TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS admins (bot_name TEXT PRIMARY KEY, guild_id TEXT, data TEXT)""")
    conn.commit()
    conn.close()

# ========================================================
# 🚀 PULL / PUSH MONGODB FUNCTIONS (Event-Driven)
# ========================================================
def pull_all_from_mongo():
    if col_system is None or col_accounts is None:
        print("[MONGO] MongoDB Offline. Skipping Live Sync Pull.")
        return
    try:
        init_sqlite()
        conn = get_db_connection()
        cursor = conn.cursor()
        
        bot_owners = {}
        bot_numbers = {}
        
        for doc in col_system.find():
            filename = doc['_id']
            data = doc.get('data', {})
            if filename == 'users.json':
                for uname, udata in data.items():
                    cursor.execute("INSERT OR IGNORE INTO users (username, password, role, uid) VALUES (?, ?, ?, ?)", (uname, udata.get('password'), udata.get('role'), udata.get('uid')))
            elif filename == 'profile.json':
                for ingame_uid, pdata in data.items():
                    cursor.execute("INSERT OR REPLACE INTO profiles (ingame_uid, data) VALUES (?, ?)", (ingame_uid, json.dumps(pdata)))
            elif filename == 'bot_owners.json': 
                bot_owners = data
            elif filename == 'bot_numbers.json': 
                bot_numbers = data
            elif filename == 'owner.json':
                # 🟢 Owner list pulling and saving
                try:
                    owner_path = os.path.join(BASE_DIR, 'config', 'owner.json')
                    os.makedirs(os.path.dirname(owner_path), exist_ok=True)
                    with open(owner_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=4)
                except Exception: pass

        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO users (username, password, role, uid) VALUES (?, ?, ?, ?)", ("owner", "owner", "owner", str(random.randint(10000, 99999))))

        for doc in col_accounts.find():
            name = doc['_id']
            if not name or str(name).strip().lower() in ['none', 'null', 'undefined', '']:
                try:
                    col_accounts.delete_one({'_id': name})
                    if col_admins is not None: col_admins.delete_one({'_id': name})
                except Exception: pass
                continue 

            data = doc.get('data', {})
            acc = data.get('account', {})
            owner_info = bot_owners.get(name, {})
            creator = owner_info.get("creator", "owner") if isinstance(owner_info, dict) else owner_info
            folder = owner_info.get("folder", creator) if isinstance(owner_info, dict) else creator
            b_num = bot_numbers.get(name, 0)
            
            cursor.execute("SELECT ingame_uid FROM bots WHERE name=?", (name,))
            row = cursor.fetchone()
            existing_uid = row[0] if row else None
            
            cursor.execute("""INSERT OR REPLACE INTO bots (name, login_uid, password, ingame_uid, owner, folder, bot_number) VALUES (?, ?, ?, ?, ?, ?, ?)""", (name, acc.get('uid'), acc.get('password'), existing_uid, creator, folder, b_num))
                
        # 🟢 Admin list pulling and saving
        if col_admins is not None:
            for doc in col_admins.find():
                name = doc['_id']
                if not name or str(name).strip().lower() in ['none', 'null', 'undefined', '']:
                    try: col_admins.delete_one({'_id': name})
                    except: pass
                    continue
                    
                data = doc.get('data', {})
                
                # Update Local SQLite
                cursor.execute("INSERT OR REPLACE INTO admins (bot_name, guild_id, data) VALUES (?, ?, ?)", (name, str(data.get('Guild_ID', '')), json.dumps(data)))
                
                # Update Local JSON
                cursor.execute("SELECT ingame_uid FROM bots WHERE name=?", (name,))
                row = cursor.fetchone()
                if row and row[0]:
                    uid_str = "".join(c for c in str(row[0]) if c.isdigit())
                    try:
                        dir_path = os.path.join(BASE_DIR, 'config', 'admins')
                        os.makedirs(dir_path, exist_ok=True)
                        file_path = os.path.join(dir_path, f"{uid_str}.json")
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump({"Admins": data.get("Admins", [])}, f, indent=4)
                    except Exception: pass

        # 🟢 Guild Members pulling and saving
        if col_guild_members is not None:
            for doc in col_guild_members.find():
                bot_uid = doc.get('bot_uid')
                members = doc.get('members', [])
                if bot_uid:
                    try:
                        file_dir = os.path.join(BASE_DIR, 'config', 'guild_members')
                        os.makedirs(file_dir, exist_ok=True)
                        file_path = os.path.join(file_dir, f"{bot_uid}.json")
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump({"members": members}, f, indent=4)
                    except Exception: pass
            
        cursor.execute("DELETE FROM bots WHERE name IS NULL OR name = '' OR name = 'null' OR name = 'None' OR name = 'undefined'")
                           
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SYNC ERROR] {e}")

def start_change_stream():
    if client is None:
        return
    def watch_db():
        print("[MONGO] Live Sync Started. Listening for changes...")
        while True:
            try:
                if client is None:
                    time.sleep(5)
                    continue
                pipeline = [{"$match": {"operationType": {"$in": ["insert", "update", "replace", "delete"]}}}]
                with client.watch(pipeline) as stream:
                    for change in stream:
                        pull_all_from_mongo()
            except Exception as e:
                time.sleep(5)
                
    threading.Thread(target=watch_db, daemon=True).start()

# 🟢 PUSH FUNCTIONS (Called manually when data changes)
def push_user_to_mongo():
    if col_system is None: return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, role, uid FROM users")
    users_data = {row[0]: {"password": row[1], "role": row[2], "uid": row[3]} for row in cursor.fetchall()}
    conn.close()
    try: col_system.update_one({'_id': 'users.json'}, {'$set': {'data': users_data}}, upsert=True)
    except: pass

def push_profile_to_mongo():
    if col_system is None: return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ingame_uid, data FROM profiles")
    profiles_data = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
    conn.close()
    try: col_system.update_one({'_id': 'profile.json'}, {'$set': {'data': profiles_data}}, upsert=True)
    except: pass

def push_bot_to_mongo(name, login_uid, password, owner, folder, bot_number):
    if col_accounts is None or col_system is None: return
    if not name or str(name).strip().lower() in ['none', 'null', 'undefined', '']: return
    try:
        col_accounts.update_one({'_id': name}, {'$set': {'data': {"account": {"uid": login_uid, "password": password}}}}, upsert=True)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, owner, folder FROM bots WHERE name IS NOT NULL AND name != ''")
        owners_data = {row[0]: {"creator": row[1], "folder": row[2]} for row in cursor.fetchall()}
        col_system.update_one({'_id': 'bot_owners.json'}, {'$set': {'data': owners_data}}, upsert=True)
        cursor.execute("SELECT name, bot_number FROM bots WHERE name IS NOT NULL AND name != ''")
        numbers_data = {row[0]: row[1] for row in cursor.fetchall()}
        col_system.update_one({'_id': 'bot_numbers.json'}, {'$set': {'data': numbers_data}}, upsert=True)
        conn.close()
    except: pass

def push_admin_to_mongo(name, admin_data):
    if col_admins is None: return
    if not name or str(name).strip().lower() in ['none', 'null', 'undefined', '']: return
    try: col_admins.update_one({'_id': name}, {'$set': {'data': admin_data}}, upsert=True)
    except Exception as e: print(f"[MONGO ERROR] {e}")

def push_guild_members_to_mongo(bot_name, bot_uid, clan_id, members_list):
    if col_guild_members is None: return
    try:
        col_guild_members.update_one(
            {'_id': bot_name},
            {'$set': {'bot_uid': str(bot_uid), 'clan_id': str(clan_id), 'members': members_list, 'last_update': time.time()}},
            upsert=True
        )
    except Exception as e: pass

def push_owner_to_mongo():
    if col_system is None: return
    try:
        owner_path = os.path.join(BASE_DIR, 'config', 'owner.json')
        if os.path.exists(owner_path):
            with open(owner_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            col_system.update_one({'_id': 'owner.json'}, {'$set': {'data': data}}, upsert=True)
    except Exception as e: print(f"[MONGO ERROR] Owner Push Error: {e}")

def delete_bot_from_mongo(name):
    if col_accounts is None or col_system is None: return
    try: 
        col_accounts.delete_one({'_id': name})
        if col_admins is not None: col_admins.delete_one({'_id': name})
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, owner, folder FROM bots WHERE name IS NOT NULL AND name != ''")
        owners_data = {row[0]: {"creator": row[1], "folder": row[2]} for row in cursor.fetchall()}
        col_system.update_one({'_id': 'bot_owners.json'}, {'$set': {'data': owners_data}}, upsert=True)
        cursor.execute("SELECT name, bot_number FROM bots WHERE name IS NOT NULL AND name != ''")
        numbers_data = {row[0]: row[1] for row in cursor.fetchall()}
        col_system.update_one({'_id': 'bot_numbers.json'}, {'$set': {'data': numbers_data}}, upsert=True)
        conn.close()
    except: pass

def rename_bot_in_mongo(old_name, new_name):
    if col_accounts is None or col_system is None: return
    if not new_name or str(new_name).strip().lower() in ['none', 'null', 'undefined', '']: return
    try:
        doc = col_accounts.find_one({'_id': old_name})
        if doc:
            col_accounts.insert_one({'_id': new_name, 'data': doc['data']})
            col_accounts.delete_one({'_id': old_name})
        if col_admins is not None:
            admin_doc = col_admins.find_one({'_id': old_name})
            if admin_doc:
                col_admins.insert_one({'_id': new_name, 'data': admin_doc['data']})
                col_admins.delete_one({'_id': old_name})
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, owner, folder FROM bots WHERE name IS NOT NULL AND name != ''")
        owners_data = {row[0]: {"creator": row[1], "folder": row[2]} for row in cursor.fetchall()}
        col_system.update_one({'_id': 'bot_owners.json'}, {'$set': {'data': owners_data}}, upsert=True)
        cursor.execute("SELECT name, bot_number FROM bots WHERE name IS NOT NULL AND name != ''")
        numbers_data = {row[0]: row[1] for row in cursor.fetchall()}
        col_system.update_one({'_id': 'bot_numbers.json'}, {'$set': {'data': numbers_data}}, upsert=True)
        conn.close()
    except: pass

pull_all_from_mongo()
start_change_stream()

# END OF FILE mongo_sync.py
