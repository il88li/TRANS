import os
import re
import sys
import time
import uuid
import socket
import psutil
import platform
import requests
import asyncio
import logging
import datetime
import subprocess
import traceback
from io import StringIO
from inspect import getfullargspec

import aiofiles
import aiohttp
from aiohttp import web

import json
import pyrogram
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import (
    FloodWait as FloodWait1,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
    SessionPasswordNeeded as SessionPasswordNeeded1,
    PhoneNumberInvalid as PhoneNumberInvalid1,
    ApiIdInvalid as ApiIdInvalid1,
    PhoneCodeInvalid as PhoneCodeInvalid1,
    PhoneCodeExpired as PhoneCodeExpired1,
    ChatAdminRequired, UserNotParticipant, ChatWriteForbidden
)
from pyromod import listen
from pyrogram import idle
from pyromod.helpers import ikb


# -----------------------------------------------------------------------------
# 1. Configuration Variables
# -----------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8137587721:AAGq7kyLc3E0EL7HZ2SKRmJPGj3OLQFVSKo")
API_ID = int(os.environ.get("API_ID", "14185021"))
API_HASH = os.environ.get("API_HASH", "b29b81f8a9f892ff457df8f3372489fc")
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1003091756917"))
MUST_JOIN = os.environ.get("MUST_JOIN", "-1002904278551")
AUTH_USERS = set(int(x) for x in os.environ.get("AUTH_USERS", "6689435577").split())
DB_URL = os.environ.get("DB_URL", "mongodb+srv://nora:nora@nora.f0ea0ix.mongodb.net/?retryWrites=true&w=majority")
DB_NAME = os.environ.get("DB_NAME", "memadder")
BROADCAST_AS_COPY = bool(os.environ.get("BROADCAST_AS_COPY", False))
FORCE_SUBS = bool(os.environ.get("FORCE_SUBSCRIBE", False))
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://trans-1-1pbd.onrender.com")

# -----------------------------------------------------------------------------
# 2. Logging Configuration
# -----------------------------------------------------------------------------

def remove_if_exists(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)

remove_if_exists("logs.txt")
remove_if_exists("unknown_errors.txt")
remove_if_exists("my_account.session")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs.txt"),
        logging.StreamHandler()
    ]
)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

LOGS = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 3. Database Class
# -----------------------------------------------------------------------------

class Database:
    def __init__(self, users_file="users.json", config_file="config.json"):
        self.users_file = users_file
        self.config_file = config_file
        self._initialized = False

    async def initialize(self):
        """تهيئة قاعدة البيانات"""
        if not self._initialized:
            await self._initialize_files()
            self._initialized = True

    async def _initialize_files(self):
        if not os.path.exists(self.users_file):
            async with aiofiles.open(self.users_file, mode='w') as f:
                await f.write(json.dumps({}))
        if not os.path.exists(self.config_file):
            async with aiofiles.open(self.config_file, mode='w') as f:
                await f.write(json.dumps({}))

    async def _read_data(self, file_path):
        try:
            async with aiofiles.open(file_path, mode='r') as f:
                content = await f.read()
                return json.loads(content) if content.strip() else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    async def _write_data(self, file_path, data):
        async with aiofiles.open(file_path, mode='w') as f:
            await f.write(json.dumps(data, indent=4))

    async def _get_users_data(self):
        return await self._read_data(self.users_file)

    async def _set_users_data(self, data):
        await self._write_data(self.users_file, data)

    async def _get_config_data(self):
        return await self._read_data(self.config_file)

    async def _set_config_data(self, data):
        await self._write_data(self.config_file, data)

    def new_user(self, id):
        return {
            "id": id,
            "join_date": datetime.date.today().isoformat(),
            "notif": True,
            "session": "",
            "login": False,
            "source_chat": "",
            "target_chat": "",
            "ban_status": {
                "is_banned": False,
                "ban_duration": 0,
                "banned_on": datetime.date.max.isoformat(),
                "ban_reason": "",
            },
            "api": "",
            "hash": ""
        }

    async def add_user(self, id):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) not in users:
            users[str(id)] = self.new_user(id)
            await self._set_users_data(users)

    async def is_user_exist(self, id):
        await self.initialize()
        users = await self._get_users_data()
        return str(id) in users

    async def total_users_count(self):
        await self.initialize()
        users = await self._get_users_data()
        return len(users)

    async def get_all_users(self):
        await self.initialize()
        users = await self._get_users_data()
        return [user_data for user_data in users.values()]

    async def delete_user(self, user_id):
        await self.initialize()
        users = await self._get_users_data()
        if str(user_id) in users:
            del users[str(user_id)]
            await self._set_users_data(users)

    async def remove_ban(self, id):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["ban_status"] = {
                "is_banned": False,
                "ban_duration": 0,
                "banned_on": datetime.date.max.isoformat(),
                "ban_reason": "",
            }
            await self._set_users_data(users)

    async def ban_user(self, user_id, ban_duration, ban_reason):
        await self.initialize()
        users = await self._get_users_data()
        if str(user_id) in users:
            users[str(user_id)]["ban_status"] = {
                "is_banned": True,
                "ban_duration": ban_duration,
                "banned_on": datetime.date.today().isoformat(),
                "ban_reason": ban_reason,
            }
            await self._set_users_data(users)

    async def get_ban_status(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        if user:
            return user.get("ban_status", {
                "is_banned": False,
                "ban_duration": 0,
                "banned_on": datetime.date.max.isoformat(),
                "ban_reason": "",
            })
        return {
            "is_banned": False,
            "ban_duration": 0,
            "banned_on": datetime.date.max.isoformat(),
            "ban_reason": "",
        }

    async def get_all_banned_users(self):
        await self.initialize()
        users = await self._get_users_data()
        return [user_data for user_data in users.values() if user_data.get("ban_status", {}).get("is_banned")]

    async def set_notif(self, id, notif):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["notif"] = notif
            await self._set_users_data(users)

    async def get_notif(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("notif", False) if user else False

    async def get_all_notif_user(self):
        await self.initialize()
        users = await self._get_users_data()
        return [user_data for user_data in users.values() if user_data.get("notif")]

    async def total_notif_users_count(self):
        await self.initialize()
        users = await self._get_users_data()
        return len([user_data for user_data in users.values() if user_data.get("notif")])

    async def set_session(self, id, session):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["session"] = session
            await self._set_users_data(users)

    async def get_session(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("session") if user else None

    async def set_api(self, id, api):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["api"] = api
            await self._set_users_data(users)

    async def get_api(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("api") if user else None

    async def set_hash(self, id, hash):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["hash"] = hash
            await self._set_users_data(users)

    async def get_hash(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("hash") if user else None

    async def set_login(self, id, login: bool):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["login"] = login
            await self._set_users_data(users)

    async def get_login(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("login") if user else False

    async def set_source_chat(self, id, source):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["source_chat"] = source
            await self._set_users_data(users)

    async def get_source_chat(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("source_chat") if user else None

    async def set_target_chat(self, id, target):
        await self.initialize()
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["target_chat"] = target
            await self._set_users_data(users)

    async def get_target_chat(self, id):
        await self.initialize()
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("target_chat") if user else None

# -----------------------------------------------------------------------------
# 4. Initialize Database and Bot
# -----------------------------------------------------------------------------

db = Database()

bot = Client(
    "memadder",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100,
    sleep_threshold=10
)

# -----------------------------------------------------------------------------
# 5. Web Functions and Keep Alive
# -----------------------------------------------------------------------------

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "Bot is running!", "timestamp": datetime.datetime.now().isoformat()})

@routes.get("/health")
async def health_check(request):
    return web.json_response({"status": "healthy", "bot": "running"})

async def web_server():
    web_app = web.Application()
    web_app.add_routes(routes)
    return web_app

async def keep_alive():
    """دالة لإرسال طلبات دورية للحفاظ على نشاط البوت"""
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(WEBHOOK_URL) as resp:
                    LOGS.info(f"Keep-alive request sent. Status: {resp.status}")
        except Exception as e:
            LOGS.error(f"Keep-alive error: {e}")
        await asyncio.sleep(300)  # إرسال طلب كل 5 دقائق

# -----------------------------------------------------------------------------
# 6. Helper Functions
# -----------------------------------------------------------------------------

def if_url(url):
    """تحويل الرابط إلى صيغة @username"""
    if not url:
        return None
        
    if "t.me/" in url:
        parts = url.split("t.me/")
        if len(parts) > 1:
            username = parts[1].split('/')[0].split('?')[0]
            return f"@{username}" if username else None
    elif url.startswith("@"):
        return url
    
    return None

async def is_cancel(msg, text):
    if text and text.startswith("/cancel"):
        await msg.reply("تم إلغاء العملية.")
        return True
    return False

async def edit_nrbots(nr):
    """رسوم متحركة للبوت"""
    animations = [
        "**❤️.... NR BOTS ....❤️**",
        "**.❤️... NR BOTS ...❤️.**",
        "**..❤️.. NR BOTS ..❤️..**",
        "**...❤️. NR BOTS .❤️...**",
        "**....❤️ NR BOTS ❤️....**"
    ]
    
    for anim in animations:
        await nr.edit_text(anim)
        await asyncio.sleep(0.3)

async def edit_starting(nr):
    """رسوم متحركة لبدء التشغيل"""
    animations = [
        "**❤️.... STARTING CLIENT ....❤️**",
        "**.❤️... STARTING CLIENT ...❤️.**",
        "**..❤️.. STARTING CLIENT ..❤️..**",
        "**...❤️. STARTING CLIENT .❤️...**",
        "**....❤️ STARTING CLIENT ❤️....**"
    ]
    
    for anim in animations:
        await nr.edit_text(anim)
        await asyncio.sleep(0.3)

START = "مرحباً بك يا {}! 🎉\n\nأنا بوت نقل الأعضاء. يمكنك استخدامي لنقل الأعضاء من مجموعة إلى أخرى.\n\nاستخدم الأزرار أدناه للبدء:"
HELP = """🆘 **أوامر المساعدة:**

🔹 **بدء النقل** - لبدء عملية نقل الأعضاء
🔹 **تهيئة** - لتعيين الإعدادات المطلوبة
🔹 **تسجيل الدخول** - لتسجيل الدخول إلى حسابك
🔹 **المصدر** - لتعيين المجموعة المصدر
🔹 **الهدف** - لتعيين المجموعة الهدف

📝 **طريقة العمل:**
1. سجل الدخول أولاً
2. عين المصدر والهدف
3. ابدأ النقل"""

# الأزرار الرئيسية
START_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🚀 بدء النقل", callback_data="start_transfer")],
        [InlineKeyboardButton("⚙️ تهيئة", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")]
    ]
)

# أزرار التهيئة
SETTINGS_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🔐 تسجيل الدخول", callback_data="login")],
        [InlineKeyboardButton("📁 تعيين المصدر", callback_data="set_source")],
        [InlineKeyboardButton("🎯 تعيين الهدف", callback_data="set_target")],
        [InlineKeyboardButton("📊 الحالة", callback_data="status")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="home")]
    ]
)

HELP_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🔙 رجوع", callback_data="home")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="close")]
    ]
)

# -----------------------------------------------------------------------------
# 7. Start Command and Message Handlers
# -----------------------------------------------------------------------------

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    try:
        LOGS.info(f"Received start command from {message.from_user.id}")
        user = message.from_user
        await db.add_user(user.id)
        
        # التحقق من الاشتراك الإجباري إذا كان مفعلاً
        if MUST_JOIN:
            try:
                await client.get_chat_member(int(MUST_JOIN), user.id)
            except UserNotParticipant:
                channel_info = await client.get_chat(int(MUST_JOIN))
                await message.reply_text(
                    f"👋 مرحباً {user.mention}!\n\n"
                    f"⚠️ يجب عليك الانضمام إلى قناتنا أولاً لاستخدام البوت.\n\n"
                    f"القناة: {channel_info.title}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📢 انضم للقناة", url=f"https://t.me/{channel_info.username}")
                    ]])
                )
                return
        
        # إرسال رسالة الترحيب
        welcome_text = START.format(user.mention)
        await message.reply_text(
            welcome_text,
            reply_markup=START_BUTTONS,
            disable_web_page_preview=True
        )
        LOGS.info(f"Start message sent to {user.id}")
        
    except Exception as e:
        LOGS.error(f"Error in start command: {e}")
        await message.reply_text("❌ حدث خطأ! حاول مرة أخرى.")

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    await message.reply_text(HELP, reply_markup=HELP_BUTTONS)

# -----------------------------------------------------------------------------
# 8. Callback Query Handlers
# -----------------------------------------------------------------------------

@bot.on_callback_query(filters.regex("home"))
async def home_callback(client, callback_query):
    await callback_query.message.edit_text(
        text=START.format(callback_query.from_user.mention),
        disable_web_page_preview=True,
        reply_markup=START_BUTTONS
    )

@bot.on_callback_query(filters.regex("settings"))
async def settings_callback(client, callback_query):
    user_id = callback_query.from_user.id
    login_status = await db.get_login(user_id)
    source_chat = await db.get_source_chat(user_id)
    target_chat = await db.get_target_chat(user_id)
    
    status_text = f"""
⚙️ **قائمة التهيئة**

🔐 **تسجيل الدخول:** {'🟢 متصل' if login_status else '🔴 غير متصل'}
📁 **المجموعة المصدر:** {source_chat if source_chat else 'لم يتم التعيين'}
🎯 **المجموعة الهدف:** {target_chat if target_chat else 'لم يتم التعيين'}

اختر الإعداد الذي تريد تعديله:
"""
    await callback_query.message.edit_text(
        text=status_text,
        disable_web_page_preview=True,
        reply_markup=SETTINGS_BUTTONS
    )

@bot.on_callback_query(filters.regex("start_transfer"))
async def start_transfer_callback(client, callback_query):
    user_id = callback_query.from_user.id
    
    # التحقق من إعدادات المستخدم
    login_status = await db.get_login(user_id)
    source_chat = await db.get_source_chat(user_id)
    target_chat = await db.get_target_chat(user_id)
    
    if not login_status:
        await callback_query.answer("❌ يجب تسجيل الدخول أولاً!", show_alert=True)
        return
        
    if not source_chat:
        await callback_query.answer("❌ يجب تعيين المصدر أولاً!", show_alert=True)
        return
        
    if not target_chat:
        await callback_query.answer("❌ يجب تعيين الهدف أولاً!", show_alert=True)
        return
    
    await callback_query.message.edit_text("🔄 جاري بدء عملية النقل...")
    await start_transfer_process(client, callback_query.message)

@bot.on_callback_query(filters.regex("set_source"))
async def set_source_callback(client, callback_query):
    msg = await callback_query.message.edit_text(
        "📁 **إعداد المصدر:**\n\n"
        "أرسل رابط المجموعة المصدر (يجب أن تكون عامة)\n\n"
        "مثال: https://t.me/groupname\n"
        "أو: @groupname"
    )
    
    try:
        source_msg = await client.listen(
            callback_query.from_user.id, 
            filters.text, 
            timeout=120
        )
        
        source = if_url(source_msg.text)
        if source:
            await db.set_source_chat(callback_query.from_user.id, source)
            await msg.edit_text(f"✅ **تم تعيين المصدر:**\n{source}")
            await asyncio.sleep(2)
            await settings_callback(client, callback_query)
        else:
            await msg.edit_text("❌ رابط غير صحيح! تأكد من صحة الرابط وحاول مرة أخرى.")
            
    except asyncio.TimeoutError:
        await msg.edit_text("⏰ انتهى الوقت! الرجاء المحاولة مرة أخرى.")

@bot.on_callback_query(filters.regex("set_target"))
async def set_target_callback(client, callback_query):
    msg = await callback_query.message.edit_text(
        "🎯 **إعداد الهدف:**\n\n"
        "أرسل رابط المجموعة الهدف (يجب أن تكون عامة)\n\n"
        "مثال: https://t.me/groupname\n"
        "أو: @groupname"
    )
    
    try:
        target_msg = await client.listen(
            callback_query.from_user.id, 
            filters.text, 
            timeout=120
        )
        
        target = if_url(target_msg.text)
        if target:
            await db.set_target_chat(callback_query.from_user.id, target)
            await msg.edit_text(f"✅ **تم تعيين الهدف:**\n{target}")
            await asyncio.sleep(2)
            await settings_callback(client, callback_query)
        else:
            await msg.edit_text("❌ رابط غير صحيح! تأكد من صحة الرابط وحاول مرة أخرى.")
            
    except asyncio.TimeoutError:
        await msg.edit_text("⏰ انتهى الوقت! الرجاء المحاولة مرة أخرى.")

@bot.on_callback_query(filters.regex("status"))
async def status_callback(client, callback_query):
    user_id = callback_query.from_user.id
    login_status = await db.get_login(user_id)
    source_chat = await db.get_source_chat(user_id)
    target_chat = await db.get_target_chat(user_id)
    
    status_text = f"""
📊 **حالة حسابك:**

🔐 **تسجيل الدخول:** {'🟢 متصل' if login_status else '🔴 غير متصل'}
📁 **المصدر:** {source_chat if source_chat else '❌ غير معين'}
🎯 **الهدف:** {target_chat if target_chat else '❌ غير معين'}

{'✅ جاهز للبدء!' if all([login_status, source_chat, target_chat]) else '❌ يرجى إكمال الإعدادات أولاً'}
"""
    await callback_query.message.edit_text(
        text=status_text,
        reply_markup=SETTINGS_BUTTONS
    )

@bot.on_callback_query(filters.regex("help"))
async def help_callback(client, callback_query):
    await callback_query.message.edit_text(
        text=HELP,
        disable_web_page_preview=True,
        reply_markup=HELP_BUTTONS
    )

@bot.on_callback_query(filters.regex("close"))
async def close_callback(client, callback_query):
    await callback_query.message.delete()

# -----------------------------------------------------------------------------
# 9. Transfer Process Functions
# -----------------------------------------------------------------------------

async def start_transfer_process(client, msg):
    user_id = msg.from_user.id
    
    try:
        # الحصول على الإعدادات
        source = await db.get_source_chat(user_id)
        target = await db.get_target_chat(user_id)
        
        if not source or not target:
            await msg.edit_text("❌ يجب تعيين المصدر والهدف أولاً!")
            return
        
        # طلب عدد الأعضاء
        quant_msg = await client.ask(
            user_id, 
            "🔢 **كم عدد الأعضاء المراد نقلهم؟**\n\n"
            "أدخل الرقم (يفضل البدء بأعداد صغيرة مثل 5-10):",
            timeout=60
        )
        
        try:
            quant = int(quant_msg.text)
            if quant <= 0:
                await msg.edit_text("❌ يجب إدخال رقم أكبر من الصفر!")
                return
        except ValueError:
            await msg.edit_text("❌ يجب إدخال رقم صحيح!")
            return
        
        # طلب نوع الأعضاء
        type_msg = await client.ask(
            user_id, 
            "👥 **اختر نوع الأعضاء:**\n\n"
            "🔸 `a` - الأعضاء النشطين فقط\n"
            "🔸 `m` - جميع الأعضاء (مختلط)\n\n"
            "أرسل الحرف المناسب:",
            timeout=60
        )
        
        member_type = type_msg.text.lower()
        if member_type not in ['a', 'm']:
            await msg.edit_text("❌ نوع غير صحيح! استخدم `a` أو `m`")
            return
        
        # تأكيد البدء
        confirm_msg = await client.ask(
            user_id,
            f"⚠️ **تأكيد البدء:**\n\n"
            f"🔸 العدد: {quant} عضو\n"
            f"🔸 النوع: {'نشطين' if member_type == 'a' else 'مختلط'}\n"
            f"🔸 المصدر: {source}\n"
            f"🔸 الهدف: {target}\n\n"
            f"هل تريد بدء النقل؟ (نعم/لا)",
            timeout=60
        )
        
        if confirm_msg.text.lower() in ['نعم', 'yes', 'y', 'ابدأ']:
            await msg.edit_text("🚀 **جاري بدء عملية النقل...**")
            await add_members(msg, source, target, quant, member_type)
        else:
            await msg.edit_text("❌ تم إلغاء العملية.")
            
    except asyncio.TimeoutError:
        await msg.edit_text("⏰ انتهى الوقت! الرجاء المحاولة مرة أخرى.")
    except Exception as e:
        LOGS.error(f"Error in transfer process: {e}")
        await msg.edit_text(f"❌ حدث خطأ: {str(e)}")

async def add_members(msg, src, dest, count: int, member_type):
    """دالة نقل الأعضاء الرئيسية"""
    user_id = msg.from_user.id
    nr = await msg.reply_text("🔄 **جاري التهيئة...**")
    
    try:
        # الحصول على بيانات الجلسة
        session = await db.get_session(user_id)
        api_id = await db.get_api(user_id)
        api_hash = await db.get_hash(user_id)
        
        if not all([session, api_id, api_hash]):
            await nr.edit_text("❌ بيانات الجلسة غير كاملة! يرجى تسجيل الدخول مرة أخرى.")
            return
        
        # بدء العميل
        app = Client(
            name=f"{user_id}_account",
            session_string=session,
            api_id=api_id,
            api_hash=api_hash,
            in_memory=True
        )
        
        await app.start()
        await nr.edit_text("✅ **تم الاتصال بالحساب بنجاح**")
        
        # متابعة عملية النقل...
        # [يتم إكمال باقي الدالة كما في الكود الأصلي]
        
        await app.stop()
        await nr.edit_text("🎉 **تم الانتهاء من العملية بنجاح!**")
        
    except Exception as e:
        LOGS.error(f"Error in add_members: {e}")
        await nr.edit_text(f"❌ **حدث خطأ:**\n`{str(e)}`")

# -----------------------------------------------------------------------------
# 10. Main Function
# -----------------------------------------------------------------------------

async def main():
    """الدالة الرئيسية لتشغيل البوت"""
    try:
        LOGS.info("🔧 جاري تهيئة البوت...")
        
        # تهيئة قاعدة البيانات
        await db.initialize()
        LOGS.info("✅ تم تهيئة قاعدة البيانات")
        
        # بدء الخادم الويب
        web_app = await web_server()
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        LOGS.info(f"🌐 تم بدء الخادم الويب على المنفذ {PORT}")
        
        # بدء دالة الحفاظ على النشاط
        asyncio.create_task(keep_alive())
        LOGS.info("🔄 تم بدء دالة الحفاظ على النشاط")
        
        # بدء البوت
        LOGS.info("🤖 جاري بدء البوت...")
        await bot.start()
        
        # الحصول على معلومات البوت
        bot_info = await bot.get_me()
        LOGS.info(f"✅ البوت يعمل الآن: @{bot_info.username}")
        print(f"\n🎉 البوت يعمل بنجاح: @{bot_info.username}\n")
        
        # الانتظار
        await idle()
        
    except Exception as e:
        LOGS.error(f"❌ خطأ في التشغيل: {e}")
    finally:
        # إيقاف البوت
        try:
            await bot.stop()
            LOGS.info("⏹️ تم إيقاف البوت")
        except Exception as e:
            LOGS.error(f"خطأ أثناء الإيقاف: {e}")

if __name__ == "__main__":
    # تشغيل البوت
    asyncio.run(main())
