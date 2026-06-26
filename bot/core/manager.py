# bot/core/manager.py

import asyncio
import socket
import time
import random
from bot.packets import auth_packets, chat_packets, team_packets
from bot.core.router import listen_chat, listen_online

# রিকানেক্ট সেশন রিকভারি ইমপোর্ট
from bot.core.handlers import start_room_chat_auth_sequence
from utils.helpers import load_bot_room_state

async def create_socket_connection(ip, port):
    reader, writer = await asyncio.open_connection(ip, port)
    sock = writer.get_extra_info('socket')
    if sock is not None:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
        except AttributeError: pass 
    return reader, writer

async def send_online_packet(bot, packet):
    if bot.online_connected and getattr(bot, 'online_writer', None):
        try: 
            bot.online_writer.write(packet)
            await bot.online_writer.drain()
            return True
        except Exception:
            await bot._close_online_connection() 
            return False
    return False

async def send_chat_packet(bot, packet):
    if bot.chat_connected and getattr(bot, 'chat_writer', None):
        try: 
            bot.chat_writer.write(packet)
            await bot.chat_writer.drain()
            return True
        except Exception:
            await bot._close_chat_connection()
            return False
    return False

async def send_chat_message(bot, msg, ctx):
    if not ctx: return
    try:
        # সেশন স্পুফিং রিজেকশন এড়াতে বটের নিজের আসল ইউআইডি কনটেক্সটে ইনজেক্ট করা হলো
        ctx_copy = ctx.copy()
        ctx_copy['bot_uid'] = bot.my_uid
        
        # 🟢 সেশন জেসন থেকে লোড হওয়া আসল এবং ভেরিফাইড রুম আইডি ইনজেক্ট করা হলো
        if getattr(bot, 'room_id', None):
            ctx_copy['room_id'] = bot.room_id
        
        pkt = await chat_packets.create_chat_message_packet(msg, ctx_copy, bot.key, bot.iv)
        if pkt: await send_chat_packet(bot, pkt)
    except Exception: pass

async def manage_chat_connection(bot):
    c_ip, c_port = bot.server.AccountIP_Port.split(':')
    while bot.is_running:
        if not bot.chat_connected:
            try:
                reader, bot.chat_writer = await create_socket_connection(c_ip, int(c_port))
                
                handshake = await auth_packets.create_tcp_auth_packet(
                    bot.my_uid, bot.auth.token, bot.auth.timestamp, bot.key, bot.iv
                )

                bot.chat_writer.write(bytes.fromhex(handshake))
                await bot.chat_writer.drain()
                
                bot.chat_connected = True
                bot.team_chat_authed = False 
                
                await asyncio.sleep(1.0) 
                
                if bot.guild_id and bot.guild_data:
                    try:
                        await asyncio.sleep(2)
                        auth_clan_pkt = await chat_packets.AuthClan(bot.guild_id, bot.guild_data, bot.key, bot.iv)
                        if auth_clan_pkt: await send_chat_packet(bot, auth_clan_pkt)
                    except: pass
                
                # গ্যারেনার সাথে কনফ্লিক্ট এড়াতে লবি চ্যাট চ্যানেলটি রুমে অবস্থানকালে সম্পূর্ণ ব্লকড থাকবে
                if bot.is_in_team and bot.current_chat_code and bot.current_chat_owner and not getattr(bot, 'is_in_room', False):
                    c_code = str(bot.current_chat_code).lower()
                    c_owner = str(bot.current_chat_owner).lower()
                    if c_code not in ["none", "null", ""] and c_owner not in ["none", "null", ""]:
                        try:
                            await asyncio.sleep(0.5)
                            auth_pkt = await chat_packets.AuthTeam(bot.current_chat_owner, bot.current_chat_code, bot.key, bot.iv)
                            if auth_pkt and await send_chat_packet(bot, auth_pkt):
                                bot.team_chat_authed = True 
                        except: pass
                
                # RECONNECTION HOOK: ডিসকানেক্টের পর অটোমেটিক রুম চ্যাট রিকভার করার লজিক
                saved_room = load_bot_room_state(bot.my_uid)
                if saved_room:
                    room_id = saved_room.get("room_id")
                    secret_code = saved_room.get("secret_code")
                    if room_id and secret_code:
                        bot.room_id = room_id
                        bot.room_secret_code = secret_code
                        bot.is_in_room = True
                        print(f"[{bot.bot_name}] 🔄 Reconnection detected! Recovering room chat session...")
                        asyncio.create_task(start_room_chat_auth_sequence(bot, room_id, secret_code))
                    
                await listen_chat(bot, reader)
            except asyncio.CancelledError:
                break
            except Exception as e:
                await bot._close_chat_connection()
                await asyncio.sleep(3)
        await asyncio.sleep(1)

async def manage_online_connection(bot):
    o_ip, o_port = bot.server.Online_IP_Port.split(':')
    while bot.is_running:
        if not bot.online_connected:
            try:
                reader, bot.online_writer = await create_socket_connection(o_ip, int(o_port))
                
                handshake = await auth_packets.create_tcp_auth_packet(
                    bot.my_uid, bot.auth.token, bot.auth.timestamp, bot.key, bot.iv
                )

                bot.online_writer.write(bytes.fromhex(handshake))
                await bot.online_writer.drain()
                
                bot.online_connected = True
                bot.online_retries = 0 
                
                await listen_online(bot, reader)
            except asyncio.CancelledError:
                break
            except Exception as e:
                bot.online_retries += 1
                await bot._close_online_connection()
                
                if bot.online_retries >= 3:
                    return 
                    
                await asyncio.sleep(3)
        await asyncio.sleep(1)

async def heartbeat_loop(bot):
    while bot.is_running:
        try: 
            # ১. অনলাইন পোর্টের স্ট্যান্ডার্ড হার্টবিট সিঙ্ক
            if bot.online_connected and getattr(bot, 'online_writer', None):
                try:
                    ping_game_pkt = await team_packets.create_keep_alive_packet(bot.key, bot.iv, bot.region)
                    if ping_game_pkt:
                        bot.online_writer.write(ping_game_pkt)
                        await bot.online_writer.drain()
                except Exception: 
                    await bot._close_online_connection()
            
            # ২. চ্যাট সার্ভার হার্টবিট সিঙ্ক (ডিসকানেক্ট এড়ানোর জন্য সাইলেন্ট হুইসপার সিঙ্ক)
            # এটি . (ডট) চ্যাট স্প্যাম না করেই সকেট কানেকশন সম্পূর্ণ সাইলেন্টভাবে সচল রাখবে
            if bot.chat_connected and getattr(bot, 'chat_writer', None):
                try:
                    # বটের নিজের ইউআইডি দিয়ে ১টি সাইলেন্ট জিরো-উইডথ মেসেজ প্যাকেট সেন্ড করা হবে
                    # এটি কোনো দৃশ্যমান টেক্সট স্প্যাম না করেই চ্যাট সার্ভার কানেকশন সচল রাখবে
                    ctx = {
                        'chat_type': 2,       # Private whisper mode
                        'uid': bot.my_uid,    # নিজের ইউআইডিতে হুইসপার
                        'chat_id': bot.my_uid,
                        'bot_uid': bot.my_uid
                    }
                    silent_keep_alive_pkt = await chat_packets.create_chat_message_packet("\u200b", ctx, bot.key, bot.iv)
                    if silent_keep_alive_pkt:
                        bot.chat_writer.write(silent_keep_alive_pkt)
                        await bot.chat_writer.drain()
                except Exception: 
                    await bot._close_chat_connection()
                        
        except asyncio.CancelledError:
            break
        except Exception: 
            pass
        await asyncio.sleep(15) # হার্টবিট ইন্টারভাল ১৫ সেকেন্ডে সিঙ্ক করা হয়েছে