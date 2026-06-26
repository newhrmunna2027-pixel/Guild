# utils/api_client.py (Windows Proactor Fix)

import requests
import asyncio

API_ENDPOINT = "http://node11.zampto.net:21289/player-info?uid="

def sync_fetch(uid):
    url = f"{API_ENDPOINT}{uid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    # ব্রাউজারের মতো স্ট্যান্ডার্ড গেট রিকোয়েস্ট পাঠানো হচ্ছে
    response = requests.get(url, headers=headers, timeout=12)
    if response.status_code == 200:
        return response.json()
    return None

async def fetch_player_info(uid, retries=3):
    """Requests লাইব্রেরি ব্যবহার করে পৃথক থ্রেডে প্লেয়ার ডাটা লোড করার মেথড"""
    if not uid:
        return None
        
    for attempt in range(retries):
        try:
            # ব্লকিং requests.get মেথডটিকে থ্রেড পুলের সাহায্যে রান করানো হচ্ছে
            data = await asyncio.to_thread(sync_fetch, uid)
            if data:
                return data
        except Exception as e:
            if attempt == retries - 1:
                print(f"[API Client Error] Failed to fetch UID {uid} after {retries} attempts: {e} ({type(e).__name__})")
            else:
                # ফেইল করলে ১.৫ সেকেন্ড অপেক্ষা করে পুনরায় চেষ্টা করবে
                await asyncio.sleep(1.5)
                
    return None