# -*- coding: utf-8 -*-
# utils/api_client.py - Native Garena API Wrapper (Fixed NameError & Circular References)

import os
import sys
import asyncio
import sqlite3

# পরম পাথ (Absolute Path) জেনারেটর যা ডিরেক্টরি অমিল এড়াতে সাহায্য করে
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'config', 'database.db')

if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import garena_api as bot_module

async def retrieve_active_bot_token():
    """ডাটাবেজে যুক্ত সক্রিয় বটগুলোর মধ্য থেকে যেকোনো একটির সেশন টোকেন রিট্রিভ করার মেথড (Fixed Shadowing)"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM bots")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"[API Client DB Error] {e}")
        rows = []
    finally:
        conn.close()

    for row in rows:
        bot_name = row[0]
        loop = asyncio.get_running_loop()
        try:
            # requests ব্লকিং এড়াতে থ্রেড পুল এক্সিকিউটর ব্যবহার করা হয়েছে
            token, _ = await loop.run_in_executor(None, bot_module.get_active_token, bot_name)
            if token:
                return token
        except Exception as e:
            print(f"[API Client] Token fetch error for {bot_name}: {e}")
    return None

def map_garena_to_info_format(res):
    """garena_api এর রেসপন্স ডাটাকে actions_info.py এর উপযোগী ফরম্যাটে রূপান্তর করার ম্যাপার (Fixed NameError)"""
    if not res or not res.get("success"):
        return None
        
    json_data = res.get("json_data", {})
    if not isinstance(json_data, dict):
        json_data = {}
        
    def safe_get_dict(parent, key):
        val = parent.get(str(key))
        return val if isinstance(val, dict) else {}

    basic = safe_get_dict(json_data, 1)
    credit = safe_get_dict(json_data, 3)
    pet = safe_get_dict(json_data, 4)
    clan = safe_get_dict(json_data, 6)
    captain = safe_get_dict(json_data, 8)
    social = safe_get_dict(json_data, 9)

    # 🟢 FIXED: Removed self-referential 'b_info' and 'b' calls to prevent NameError/Circular Crashes
    basic_info = {
        "nickname": basic.get("3") or res.get("nickname") or "Unknown",
        "accountId": str(basic.get("1") or res.get("uid") or "0"),
        "account_id": str(basic.get("1") or res.get("uid") or "0"),
        "level": int(basic.get("6") or res.get("level") or 0),
        "exp": int(basic.get("7") or 0),
        "liked": int(basic.get("21") or res.get("likes") or 0),
        "createAt": str(basic.get("44") or res.get("created_at") or "0"),
        "create_at": str(basic.get("44") or res.get("created_at") or "0"),
        "lastLoginAt": str(basic.get("24") or res.get("last_login") or "0"),
        "last_login_at": str(basic.get("24") or res.get("last_login") or "0")
    }

    credit_info = {
        "creditScore": int(credit.get("1") or 100),
        "credit_score": int(credit.get("1") or 100)
    }

    social_info = {
        "signature": social.get("9") or res.get("signature") or "No Signature"
    }

    clan_info = {
        "clanName": clan.get("2") or res.get("clan_name") or "No Guild",
        "clan_name": clan.get("2") or res.get("clan_name") or "No Guild",
        "clanId": str(clan.get("1") or res.get("clan_id") or "N/A"),
        "clan_id": str(clan.get("1") or res.get("clan_id") or "N/A"),
        "captainId": str(clan.get("3") or res.get("leader_uid") or "N/A"),
        "captain_id": str(clan.get("3") or res.get("leader_uid") or "N/A"),
        "memberNum": int(clan.get("4") or 0),
        "member_num": int(clan.get("4") or 0),
        "capacity": int(clan.get("5") or 50)
    }

    captain_info = {
        "nickname": captain.get("3") or "Unknown"
    }

    pet_info = {
        "id": int(pet.get("1") or 0),
        "name": pet.get("2") or ""
    }

    return {
        "basicInfo": basic_info,
        "basic_info": basic_info,
        "creditScoreInfo": credit_info,
        "credit_score_info": credit_info,
        "socialInfo": social_info,
        "social_info": social_info,
        "clanBasicInfo": clan_info,
        "clan_basic_info": clan_info,
        "captainBasicInfo": captain_info,
        "captain_basic_info": captain_info,
        "petInfo": pet_info,
        "pet_info": pet_info
    }

async def fetch_player_info(uid, retries=3):
    """৩য় পক্ষের সার্ভারের সাহায্য ছাড়া সরাসরি গ্যারেনা গেটওয়ে থেকে প্লেয়ার ডাটা স্ক্যান"""
    if not uid:
        return None
        
    token = await retrieve_active_bot_token()
    if not token:
        print("[API Client Error] No active Garena Token found in database. Cannot scan player.")
        return None

    for attempt in range(retries):
        try:
            loop = asyncio.get_running_loop()
            # requests ব্লকিং এড়াতে থ্রেড পুল এক্সিকিউটর ব্যবহার করা হয়েছে
            res = await loop.run_in_executor(None, bot_module.get_player_info_detailed, str(uid), token)
            if res and res.get("success"):
                return map_garena_to_info_format(res)
        except Exception as e:
            if attempt == retries - 1:
                print(f"[API Client Error] Garena request failed for UID {uid}: {e}")
            else:
                await asyncio.sleep(1.0)
    return None
