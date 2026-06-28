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
    bot.ignore_auto_solo = False 
    
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

import threading # ফাইলের উপরে এটি যুক্ত আছে ধরে নিলাম

# 🟢 নতুন On-Demand API Sync Logic
async def fetch_and_sync_all_lists(bot):
    """শুধুমাত্র ইনভাইট পেলে এবং লিস্টে নাম না থাকলেই এই ফাংশনটি কল হবে"""
    try:
        import garena_api as bot_module
        
        config_name = getattr(bot, 'bot_display_name_from_manager', bot.bot_name)
        token, err = bot_module.get_active_token(config_name)
        
        if err or not token:
            print(f"[{bot.bot_name}] ⚠️ On-Demand Sync Failed: Token unavailable.")
            return
            
        loop = asyncio.get_running_loop()
        
        # 1. Sync Friends to Admins File
        res_friends = await loop.run_in_executor(None, bot_module.get_active_friend_list, token)
        if res_friends.get("success"):
            friend_uids = [str(f["uid"]) for f in res_friends["friends"] if str(f["uid"]) != str(bot.my_uid)]
            
            dir_path = os.path.join('config', 'admins')
            os.makedirs(dir_path, exist_ok=True)
            uid_str = "".join(c for c in str(bot.my_uid) if c.isdigit())
            file_path = os.path.join(dir_path, f"{uid_str}.json")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({"Admins": friend_uids}, f, indent=4)
            print(f"[{bot.bot_name}] ✅ On-Demand Sync: Fetched and Saved {len(friend_uids)} Friends.")
            
            # 🟢 Cloud Mongo Sync for Admins (Background)
            try:
                import mongo_sync
                admin_data = {"Bot_Name": bot.bot_name, "Guild_ID": str(bot.guild_id), "Admins": friend_uids}
                threading.Thread(target=mongo_sync.push_admin_to_mongo, args=(bot.bot_name, admin_data)).start()
            except Exception: pass

        # 2. Sync Guild Members
        if bot.guild_id and str(bot.guild_id) not in ["0", "N/A", "None"]:
            res_guild = await loop.run_in_executor(None, bot_module.get_guild_member_list, token, str(bot.guild_id))
            if res_guild.get("success"):
                all_uids = []
                if res_guild.get("leader") and "uid" in res_guild["leader"]:
                    all_uids.append(str(res_guild["leader"]["uid"]))
                if res_guild.get("acting_leader") and "uid" in res_guild["acting_leader"]:
                    all_uids.append(str(res_guild["acting_leader"]["uid"]))
                for officer in res_guild.get("officers", []):
                    if "uid" in officer:
                        all_uids.append(str(officer["uid"]))
                for member in res_guild.get("members", []):
                    if "uid" in member:
                        all_uids.append(str(member["uid"]))
                        
                file_dir = os.path.join('config', 'guild_members')
                os.makedirs(file_dir, exist_ok=True)
                uid_str = "".join(c for c in str(bot.my_uid) if c.isdigit())
                file_path = os.path.join(file_dir, f"{uid_str}.json")
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({"members": all_uids}, f, indent=4)
                print(f"[{bot.bot_name}] ✅ On-Demand Sync: Fetched and Saved {len(all_uids)} Guild members.")
                
                # 🟢 Cloud Mongo Sync for Guild Members (Background)
                try:
                    import mongo_sync
                    threading.Thread(target=mongo_sync.push_guild_members_to_mongo, args=(bot.bot_name, bot.my_uid, str(bot.guild_id), all_uids)).start()
                except Exception: pass

    except Exception as e:
        print(f"[{bot.bot_name}] ❌ Error during on-demand sync: {e}")
