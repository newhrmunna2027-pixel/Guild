# filepath: bot/core/logic.py
# bot/core/logic.py

import os
import json
import asyncio
from bot.packets import team_packets
from utils.helpers import delete_bot_room_state

TEAM_JSON_FILE = 'config/Team.json'

async def manage_team_file(bot, action, t_uid=None):
    if not os.path.exists('config'): 
        os.makedirs('config')
        
    try:
        with open(TEAM_JSON_FILE, 'r', encoding='utf-8') as f: 
            data = json.load(f)
    except Exception: 
        data = {}

    bot_uid = getattr(bot, 'my_uid', None)
    bot_key = str(bot_uid) if bot_uid else getattr(bot, 'bot_name', 'UnknownBot')
    
    if action == "sync_full_team" and t_uid is not None:
        valid_uids = [str(u) for u in t_uid if str(u).isdigit()]
        data[bot_key] = valid_uids

    elif action == "clear":
        data[bot_key] = []

    elif action == "add_member" and t_uid and str(t_uid).isdigit():
        if bot_key not in data: data[bot_key] = []
        if str(t_uid) not in data[bot_key]: data[bot_key].append(str(t_uid))
        
    elif action == "remove_member" and t_uid and str(t_uid).isdigit():
        if bot_key in data and str(t_uid) in data[bot_key]:
            data[bot_key].remove(str(t_uid))
            
    elif action == "set_leader" and t_uid:
        pass 

    try:
        with open(TEAM_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving team: {e}")

async def execute_solo_logic(bot):
    from bot.core.manager import send_online_packet 
    
    if getattr(bot, 'is_magic_mode', False):
        bot.is_magic_mode = False
        
    bot.is_locked = False
    bot.ignore_auto_solo = False # 🟢 বট সোলো হওয়ার সাথে সাথে ফ্ল্যাগটি রিসেট হবে
    
    if bot.is_in_team:
        leave_pkt = await team_packets.create_leave_team_packet(bot.my_uid, bot.key, bot.iv)
        await send_online_packet(bot, leave_pkt)
        bot.is_in_team = False
    
    await asyncio.sleep(0.5)
    await bot._close_chat_connection()   
    
    bot.team_chat_authed = False
    bot.current_chat_code = None
    bot.current_chat_owner = None
    bot.team_uids = []
    
    # 🟢 কাস্টম রুমের সেভ করা ডাটা ও সেশন ক্লিয়ার করে দিবে
    try:
        delete_bot_room_state(bot.my_uid)
        bot.room_id = None
        bot.room_secret_code = None
        bot.is_in_room = False
        bot.is_joining_room = False
    except Exception as e:
        print(f"[{getattr(bot, 'bot_name', 'Bot')}] ⚠️ Room state clear error: {e}")
    
    await manage_team_file(bot, "clear")
    print(f"[{getattr(bot, 'bot_name', 'Bot')}] 🔄 Execute Solo: Left Team, Room State Cleared & Chat connection closed.")

def load_saved_guild_members(bot_uid):
    uid_str = "".join(c for c in str(bot_uid) if c.isdigit())
    file_path = os.path.join('config', 'guild_members', f"{uid_str}.json")
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return ["".join(c for c in str(u) if c.isdigit()) for u in data.get("members", [])]
    except:
        return []

async def update_guild_members_list(bot):
    """১০ মিনিট পর পর বা স্টার্টআপে গ্যারেনা থেকে গিল্ড মেম্বারদের রিয়েল-টাইম ডাটা এনে ফাইলে সেভ করার ফাংশন"""
    if not bot.guild_id or str(bot.guild_id) in ["0", "N/A", "None"]:
        return
        
    try:
        import garena_api as bot_module
        
        config_name = getattr(bot, 'bot_display_name_from_manager', bot.bot_name)
        token, err = bot_module.get_active_token(config_name)
        
        if err or not token:
            print(f"[{bot.bot_name}] Sync Failed: Garena Token unavailable for session '{config_name}'.")
            return
            
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, bot_module.get_guild_member_list, token, str(bot.guild_id))
        
        if res.get("success"):
            all_uids = []
            if res.get("leader") and "uid" in res["leader"]:
                all_uids.append(str(res["leader"]["uid"]))
            if res.get("acting_leader") and "uid" in res["acting_leader"]:
                all_uids.append(str(res["acting_leader"]["uid"]))
            for officer in res.get("officers", []):
                if "uid" in officer:
                    all_uids.append(str(officer["uid"]))
            for member in res.get("members", []):
                if "uid" in member:
                    all_uids.append(str(member["uid"]))
                    
            file_dir = os.path.join('config', 'guild_members')
            os.makedirs(file_dir, exist_ok=True)
            
            uid_str = "".join(c for c in str(bot.my_uid) if c.isdigit())
            file_path = os.path.join(file_dir, f"{uid_str}.json")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({"members": all_uids}, f, indent=4)
                
            print(f"[{bot.bot_name}] ✅ Successfully saved {len(all_uids)} guild members.")
        else:
            print(f"[{bot.bot_name}] ⚠️ Guild Sync Response Failed: {res.get('message', 'Unknown Error')}")
            
    except Exception as e:
        print(f"[{bot.bot_name}] ❌ Error updating guild members: {e}")

async def sync_friends_to_admins_bot_logic(bot):
    """বট লগইন হওয়ার পর ফ্রেন্ডলিস্ট এনে সরাসরি অ্যাডমিন ফাইলে সেভ করার ফাংশন"""
    try:
        import garena_api as bot_module
        
        config_name = getattr(bot, 'bot_display_name_from_manager', bot.bot_name)
        token, err = bot_module.get_active_token(config_name)
        
        if err or not token:
            print(f"[{bot.bot_name}] Sync Failed: Token unavailable for friends sync.")
            return
            
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, bot_module.get_active_friend_list, token)
        
        if res.get("success"):
            friend_uids = [str(f["uid"]) for f in res["friends"] if str(f["uid"]) != str(bot.my_uid)]
            
            dir_path = os.path.join('config', 'admins')
            os.makedirs(dir_path, exist_ok=True)
            
            uid_str = "".join(c for c in str(bot.my_uid) if c.isdigit())
            file_path = os.path.join(dir_path, f"{uid_str}.json")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({"Admins": friend_uids}, f, indent=4)
                
            print(f"[{bot.bot_name}] ✅ Auto-Synced {len(friend_uids)} Friends to Admin list.")
        else:
            print(f"[{bot.bot_name}] ⚠️ Friends Sync Failed: {res.get('message', 'Unknown Error')}")
            
    except Exception as e:
        print(f"[{bot.bot_name}] ❌ Error updating friends to admins: {e}")
