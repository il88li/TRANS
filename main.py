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
MUST_JOIN = int(os.environ.get("MUST_JOIN", -1002904278551))
AUTH_USERS = set(int(x) for x in os.environ.get("AUTH_USERS", "6689435577").split())
DB_URL = os.environ.get("DB_URL", "mongodb+srv://nora:nora@nora.f0ea0ix.mongodb.net/?retryWrites=true&w=majority")
DB_NAME = os.environ.get("DB_NAME", "memadder")
BROADCAST_AS_COPY = bool(os.environ.get("BROADCAST_AS_COPY", False))
FORCE_SUBS = bool(os.environ.get("FORCE_SUBSCRIBE", False))
PORT = os.environ.get("PORT", "8080")
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
  filename=f"logs.txt",
  level=logging.INFO,
  format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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

    async def _initialize_files(self):
        if not os.path.exists(self.users_file):
            async with aiofiles.open(self.users_file, mode='w') as f:
                await f.write(json.dumps({}))
        if not os.path.exists(self.config_file):
            async with aiofiles.open(self.config_file, mode='w') as f:
                await f.write(json.dumps({}))

    async def _read_data(self, file_path):
        async with aiofiles.open(file_path, mode='r') as f:
            content = await f.read()
            return json.loads(content)

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
        users = await self._get_users_data()
        if str(id) not in users:
            users[str(id)] = self.new_user(id)
            await self._set_users_data(users)

    async def is_user_exist(self, id):
        users = await self._get_users_data()
        return str(id) in users

    async def total_users_count(self):
        users = await self._get_users_data()
        return len(users)

    async def get_all_users(self):
        users = await self._get_users_data()
        return [user_data for user_data in users.values()]

    async def delete_user(self, user_id):
        users = await self._get_users_data()
        if str(user_id) in users:
            del users[str(user_id)]
            await self._set_users_data(users)

    async def remove_ban(self, id):
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
        users = await self._get_users_data()
        return [user_data for user_data in users.values() if user_data.get("ban_status", {}).get("is_banned")]

    async def set_notif(self, id, notif):
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["notif"] = notif
            await self._set_users_data(users)

    async def get_notif(self, id):
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("notif", False) if user else False

    async def get_all_notif_user(self):
        users = await self._get_users_data()
        return [user_data for user_data in users.values() if user_data.get("notif")]

    async def total_notif_users_count(self):
        users = await self._get_users_data()
        return len([user_data for user_data in users.values() if user_data.get("notif")])

    async def set_session(self, id, session):
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["session"] = session
            await self._set_users_data(users)

    async def get_session(self, id):
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("session") if user else None

    async def set_api(self, id, api):
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["api"] = api
            await self._set_users_data(users)

    async def get_api(self, id):
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("api") if user else None

    async def set_hash(self, id, hash):
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["hash"] = hash
            await self._set_users_data(users)

    async def get_hash(self, id):
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("hash") if user else None

    async def set_login(self, id, login: bool):
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["login"] = login
            await self._set_users_data(users)

    async def get_login(self, id):
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("login") if user else False

    async def set_source_chat(self, id, source):
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["source_chat"] = source
            await self._set_users_data(users)

    async def get_source_chat(self, id):
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("source_chat") if user else None

    async def set_target_chat(self, id, target):
        users = await self._get_users_data()
        if str(id) in users:
            users[str(id)]["target_chat"] = target
            await self._set_users_data(users)

    async def get_target_chat(self, id):
        users = await self._get_users_data()
        user = users.get(str(id))
        return user.get("target_chat") if user else None

    async def set_fsub_channel(self, channel):
        config_data = await self._get_config_data()
        config_data["fsub_channel"] = channel
        await self._set_config_data(config_data)

    async def get_fsub_channel(self):
        config_data = await self._get_config_data()
        return config_data.get("fsub_channel")

    async def set_fsub(self, status: bool):
        config_data = await self._get_config_data()
        config_data["fsub"] = status
        await self._set_config_data(config_data)

    async def get_fsub(self):
        config_data = await self._get_config_data()
        return config_data.get("fsub")

    async def set_bcopy(self, status: bool):
        config_data = await self._get_config_data()
        config_data["bcopy"] = status
        await self._set_config_data(config_data)

    async def get_bcopy(self):
        config_data = await self._get_config_data()
        return config_data.get("bcopy")

# -----------------------------------------------------------------------------
# 4. Bot Instance
# -----------------------------------------------------------------------------

bot = Client(
    "memadder",
    api_id = API_ID,
    api_hash = API_HASH,
    bot_token = BOT_TOKEN,
)

# -----------------------------------------------------------------------------
# 5. Web Functions and Keep Alive
# -----------------------------------------------------------------------------

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "Bot is running!"})

async def web_server():
    web_app = web.Application(client_max_size=30000000000)
    web_app.add_routes(routes)
    return web_app

async def keep_alive():
    """دولة لإرسال طلبات دورية للحفاظ على نشاط البوت"""
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

async def aexec(code, client, message):
    exec(
        "async def __aexec(client, message): "
        + "".join(f"\n {a}" for a in code.split("\n"))
    )
    return await locals()["__aexec"](client, message)

async def edit_or_reply(msg: Message, **kwargs):
    func = msg.edit_text if msg.from_user.is_self else msg.reply
    spec = getfullargspec(func.__wrapped__).args
    await func(**{k: v for k, v in kwargs.items() if k in spec})

def if_url(url):
    regex = re.compile(
            r"^(?:http|ftp)s?://" 
            r"t.me|"
            r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"
            r"localhost|"
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
            r"(?::\d+)?"
            r"(?:/?|[/?]\S+)$"
            , re.IGNORECASE)
    
    string = url
    x = re.match(regex, string) is not None 
    if x:
        if "t.me" in string:
            xu = string.split("t.me/")[1]
            return f"@{xu}"
    elif "@" in string:
        xu = string
        return xu

async def is_cancel(msg, text):
    if text.startswith("/cancel"):
        await msg.reply("تم إلغاء العملية.")
        return True
    return False

async def type_(text: str):
    text = text.lower()
    if text == "y":
        return True
    elif text == "n":
        return False
    else:
        return False

async def edit_nrbots(nr):
    await nr.edit_text("**❤️.... NR BOTS ....❤️**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**.❤️... NR BOTS ...❤️.**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**..❤️.. NR BOTS ..❤️..**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**...❤️. NR BOTS .❤️...**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**....❤️ NR BOTS ❤️....**")
    await asyncio.sleep(0.5)

async def edit_starting(nr):
    await nr.edit_text("**❤️.... STARTING CLIENT ....❤️**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**.❤️... STARTING CLIENT ...❤️.**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**..❤️.. STARTING CLIENT ..❤️..**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**...❤️. STARTING CLIENT .❤️...**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**....❤️ STARTING CLIENT ❤️....**")
    await asyncio.sleep(0.5)

async def edit_ini(nr):
    await nr.edit_text("**❤️........❤️**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**.❤️......❤️.**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**..❤️....❤️..**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**...❤️..❤️...**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**....❤️❤️....**")
    await asyncio.sleep(0.3)
    await nr.edit_text("🎊")
    await asyncio.sleep(0.4)

async def edit_active(nr):
    await nr.edit_text("**❤️.... STARTING ACTIVE MEMBER ADDING ....❤️**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**.❤️... STARTING ACTIVE MEMBER ADDING ...❤️.**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**..❤️.. STARTING ACTIVE MEMBER ADDING ..❤️..**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**...❤️. STARTING ACTIVE MEMBER ADDING .❤️...**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**....❤️ STARTING ACTIVE MEMBER ADDING ❤️....**")
    await asyncio.sleep(0.5)

async def edit_mixed(nr):
    await nr.edit_text("**❤️.... STARTING MIXED MEMBER ADDING ....❤️**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**.❤️... STARTING MIXED MEMBER ADDING ...❤️.**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**..❤️.. STARTING MIXED MEMBER ADDING ..❤️..**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**...❤️. STARTING MIXED MEMBER ADDING .❤️...**")
    await asyncio.sleep(0.3)
    await nr.edit_text("**....❤️ STARTING MIXED MEMBER ADDING ❤️....**")
    await asyncio.sleep(0.5)

keyboard = ikb([
        [("✨ Join Updates Channel ✨", "https://t.me/nrbots","url")], 
        [("✨ Join Support Group ✨","https://t.me/NrBotsupport","url")]
])

async def getme():
    data = await bot.get_me()
    BOT_USERNAME = data.username
    return str(BOT_USERNAME)

async def botid():
    data = await bot.get_me()
    BOT_ID = data.id
    return (BOT_ID)

START_TIME = datetime.datetime.utcnow()
START_TIME_ISO = START_TIME.replace(microsecond=0).isoformat()
TIME_DURATION_UNITS = (
    ("week", 60 * 60 * 24 * 7),
    ("day", 60 * 60 * 24),
    ("hour", 60 * 60),
    ("min", 60),
    ("sec", 1)
)
async def _human_time_duration(seconds):
    if seconds == 0:
        return "inf"
    parts = []
    for unit, div in TIME_DURATION_UNITS:
        amount, seconds = divmod(int(seconds), div)
        if amount > 0:
            parts.append("{} {}{}"
                         .format(amount, unit, "" if amount == 1 else "s"))
    return ", ".join(parts)

START = "مرحباً بك يا {}! أنا بوت نقل الأعضاء. يمكنك استخدامي لنقل الأعضاء من مجموعة إلى أخرى."
HELP = "هذه هي أوامر المساعدة:\n/login - لتسجيل الدخول إلى حسابك\n/memadd - لبدء عملية نقل الأعضاء\n/status - للتحقق من حالة تسجيل الدخول\n/ping - للتحقق من سرعة استجابة البوت"

# الأزرار الرئيسية المعدلة
START_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🚀 بدء النقل", callback_data="start_transfer")],
        [InlineKeyboardButton("⚙️ تهيئة", callback_data="settings")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="close")]
    ]
)

# أزرار التهيئة
SETTINGS_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🔐 تسجيل الدخول", callback_data="login")],
        [InlineKeyboardButton("📁 المصدر", callback_data="set_source")],
        [InlineKeyboardButton("🎯 الهدف", callback_data="set_target")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="home")]
    ]
)

HELP_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🔙 رجوع", callback_data="settings")],
        [InlineKeyboardButton("❌ إغلاق", callback_data="close")]
    ]
)

def humanbytes(size):
    """Convert Bytes To Bytes So That Human Can Read It"""
    if not size:
        return ""
    power = 2 ** 10
    raised_to_pow = 0
    dict_power_n = {0: "", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}

    while size > power:
        size /= power
        raised_to_pow += 1
    return str(round(size, 2)) + " " + dict_power_n[raised_to_pow] + "B"

async def set_global_channel():
    global MUST_JOIN
    MUST_JOIN = await db.get_fsub_channel()
    
async def set_global_fsub():
    global FORCE_SUBS
    FORCE_SUBS = await db.get_fsub()

async def handle_user_status(client, msg):
    pass

async def eor(message, text, parse_mode="md"):
    if message.from_user.id:
        if message.reply_to_message:
            kk = message.reply_to_message.message_id
            return await message.reply_text(
                text, reply_to_message_id=kk, parse_mode=parse_mode
            )
        return await message.reply_text(text, parse_mode=parse_mode)
    return await message.edit(text, parse_mode=parse_mode)

def get_text(message: Message) -> [None, str]:
    """Extract Text From Commands"""
    text_to_return = message.text
    if message.text is None:
        return None
    if " " in text_to_return:
        try:
            return message.text.split(None, 1)[1]
        except IndexError:
            return None
    else:
        return None

# -----------------------------------------------------------------------------
# 7. Commands and Message Handlers
# -----------------------------------------------------------------------------

@bot.on_message(filters.command("start"))
async def start(client, message):
    user = message.from_user
    await db.add_user(user.id)
    if MUST_JOIN:
        try:
            await bot.get_chat_member(MUST_JOIN, user.id)
        except UserNotParticipant:
            await message.reply(
                f"Hey {user.mention}, to use me, you must join our updates channel.",
                reply_markup=ikb([
                    [('Join Now', f'https://t.me/{(await bot.get_chat(MUST_JOIN)).username}', 'url')]
                ])
            )
            return
    await message.reply_text(START.format(user.mention), reply_markup=START_BUTTONS)

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
        
    if not source_chat or not target_chat:
        await callback_query.answer("❌ يجب تعيين المصدر والهدف أولاً!", show_alert=True)
        return
    
    await callback_query.message.edit_text("🔄 جاري بدء عملية النقل...")
    await start_transfer_process(client, callback_query.message)

@bot.on_callback_query(filters.regex("set_source"))
async def set_source_callback(client, callback_query):
    msg = await callback_query.message.edit_text("📁 أرسل رابط المجموعة المصدر:")
    
    try:
        source_raw = await client.listen(callback_query.from_user.id, filters.text, timeout=60)
        source = if_url(source_raw.text)
        
        if source:
            await db.set_source_chat(callback_query.from_user.id, source)
            await msg.edit_text(f"✅ تم تعيين المصدر: {source}")
        else:
            await msg.edit_text("❌ رابط غير صحيح!")
            
    except asyncio.TimeoutError:
        await msg.edit_text("⏰ انتهى الوقت!")

@bot.on_callback_query(filters.regex("set_target"))
async def set_target_callback(client, callback_query):
    msg = await callback_query.message.edit_text("🎯 أرسل رابط المجموعة الهدف:")
    
    try:
        target_raw = await client.listen(callback_query.from_user.id, filters.text, timeout=60)
        target = if_url(target_raw.text)
        
        if target:
            await db.set_target_chat(callback_query.from_user.id, target)
            await msg.edit_text(f"✅ تم تعيين الهدف: {target}")
        else:
            await msg.edit_text("❌ رابط غير صحيح!")
            
    except asyncio.TimeoutError:
        await msg.edit_text("⏰ انتهى الوقت!")

@bot.on_callback_query(filters.regex("help"))
async def help_callback(client, callback_query):
    await callback_query.message.edit_text(
        text=HELP,
        disable_web_page_preview=True,
        reply_markup=HELP_BUTTONS
    )

@bot.on_callback_query(filters.regex("login"))
async def login_callback(client, callback_query):
    await genStr(client, callback_query.message)

@bot.on_callback_query(filters.regex("close"))
async def close_callback(client, callback_query):
    await callback_query.message.delete()

# -----------------------------------------------------------------------------
# 9. Transfer Process Functions
# -----------------------------------------------------------------------------

async def start_transfer_process(client, msg):
    user_id = msg.from_user.id
    
    # الحصول على الإعدادات
    source = await db.get_source_chat(user_id)
    target = await db.get_target_chat(user_id)
    
    if not source or not target:
        await msg.edit_text("❌ يجب تعيين المصدر والهدف أولاً!")
        return
    
    # طلب عدد الأعضاء ونوعهم
    try:
        quant_msg = await client.ask(user_id, "🔢 أرسل عدد الأعضاء المراد نقلهم:", timeout=60)
        quant = int(quant_msg.text)
        
        type_msg = await client.ask(user_id, 
            "👥 اختر نوع الأعضاء:\n\n"
            "🔹 أرسل `a` للأعضاء النشطين\n"
            "🔹 أرسل `m` للأعضاء المختلطين", 
            timeout=60
        )
        member_type = type_msg.text.lower()
        
        if member_type not in ['a', 'm']:
            await msg.edit_text("❌ نوع غير صحيح! استخدم `a` أو `m`")
            return
            
    except asyncio.TimeoutError:
        await msg.edit_text("⏰ انتهى الوقت!")
        return
    except ValueError:
        await msg.edit_text("❌ عدد غير صحيح!")
        return
    
    # بدء عملية النقل
    await add(msg, source, target, quant, member_type)

async def add(msg, src, dest, count: int, type):
    userid = msg.from_user.id
    nr = await msg.reply_text("**........**")
    await edit_ini(nr)

    try:
        cc = 0
        session = await db.get_session(userid)
        api = await db.get_api(userid) 
        hash = await db.get_hash(userid) 

        app = Client(name= userid,session_string=session, api_id=api, api_hash=hash)
        await nr.edit_text("**.... STARTING CLIENT ....**")
        
        await app.start()
        await edit_starting(nr)

        # محاولة الانضمام إلى الدردشة المصدر
        try:
            await app.join_chat(src)
        except Exception as e:
            LOGS.warning(f"Could not join source chat {src}: {e}. Proceeding to get members if possible.")
        
        chat = await app.get_chat(src)
        schat_id = chat.id
        
        xx = await app.get_chat(dest)
        tt = xx.members_count
        dchat_id = xx.id
        await app.join_chat(dchat_id)
        start_time = time.time()
        await asyncio.sleep(3)

    except Exception as e:
        e = str(e)
        if "Client has not been started yet" in e:
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("Client has not been started yet",reply_markup=keyboard)
        elif "403 USER_PRIVACY_RESTRICTED" in e:
            await nr.edit_text("failed to add because of The user's privacy settings",reply_markup=keyboard)
            await asyncio.sleep(1)
        elif "400 CHAT_ADMIN_REQUIRED" in e:
            await nr.edit_text("Failed to get members from source group because admin privileges are required. Please ensure the source group is public or your account is an admin there.",reply_markup=keyboard)
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("Failed to get members from source group because admin privileges are required. Please ensure the source group is public or your account is an admin there.",reply_markup=keyboard)

        elif "400 INVITE_REQUEST_SENT" in e:
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("hey i cant scrape/add members from a group where i need admin approval to join chat.",reply_markup=keyboard)
        elif "400 PEER_FLOOD" in e:
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("Adding stopped due to 400 PEER_FLOOD\n\nyour account is limited please wait sometimes then try again.",reply_markup=keyboard)
        elif "401 AUTH_KEY_UNREGISTERED" in e:
            await db.set_session(msg.from_user.id, "")
            await db.set_login(msg.from_user.id,False)
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("please login again to use this feature",reply_markup=keyboard)
        elif "403 CHAT_WRITE_FORBIDDEN" in e:
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("You don't have rights to send messages in this chat\nPlease make user account admin and try again",reply_markup=keyboard)
        elif "400 CHANNEL_INVALID" in e:
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("The source or destination username is invalid",reply_markup=keyboard)
        elif "400 USERNAME_NOT_OCCUPIED" in e:
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("The username is not occupied by anyone please check the username or userid that you have provided",reply_markup=keyboard)
        elif "401 SESSION_REVOKED" in e:
            await db.set_session(msg.from_user.id, "")
            await db.set_login(msg.from_user.id,False)
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text("you have terminated the login session from the user account \n\nplease login again",reply_markup=keyboard)
        return await nr.edit_text(f"**ERROR:** `{str(e)}`",reply_markup=keyboard)

    if type == "a":
        try:
            await nr.edit_text("**.... STARTING ACTIVE MEMBER ADDING ....**")
            await edit_active(nr)
            await asyncio.sleep(0.5)
            async for member in app.get_chat_members(schat_id):
                user = member.user
                s = ["RECENTLY","ONLINE"]
                if user.is_bot:
                    pass
                else:
                    b = (str(user.status)).split(".")[1]
                    if b in s:
                        try:
                            user_id = user.id
                            await nr.edit_text(f'TRYING TO ADD: `{user_id}`')
                            if await app.add_chat_members(dchat_id, user_id):
                                cc = cc+1
                                await nr.edit_text(f'ADDED: `{user_id}`')
                                await asyncio.sleep(5)
                        except FloodWait1 as fl:
                            t = "FLOODWAIT DETECTED IN USER ACCOUNT\n\nSTOPPED ADDING PROCESS"
                            await nr.edit_text(t)
                            x2 = await app.get_chat(dchat_id)
                            t2 = x2.members_count
                            completed_in = datetime.timedelta(
                            seconds=int(time.time() - start_time))
                            ttext = f"""
<u>**✨ Stopped adding process due to Floodwait of {fl.value}s ✨**</u>

    ┏━━━━━━━━━━━━━━━━━┓
    ┣✨ Added to chat Id: `{dchat_id}`
    ┣✨ Previous chat member count : **{tt}**
    ┣✨ Current chat member count : **{t2}**
    ┣✨ Total users added : **{cc}**
    ┣✨ Total time taken : **{completed_in}**s
    ┗━━━━━━━━━━━━━━━━━┛
                                """
                            await app.leave_chat(src)
                            await app.stop()
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text(ttext,reply_markup=keyboard)
                        except Exception as e:
                            # معالجة الأخطاء...
                            await asyncio.sleep(5)

                if cc == count:
                    x2 = await app.get_chat(dchat_id)
                    t2 = x2.members_count
                    completed_in = datetime.timedelta(
                    seconds=int(time.time() - start_time))
                    ttext = f"""
<u>**✨ Successfully completed adding process ✨**</u>

    ┏━━━━━━━━━━━━━━━━━┓
    ┣✨ Added to chat Id: `{dchat_id}`
    ┣✨ Previous chat member count : **{tt}**
    ┣✨ Current chat member count : **{t2}**
    ┣✨ Total users added : **{cc}**
    ┣✨ Total time taken : **{completed_in}**s
    ┗━━━━━━━━━━━━━━━━━┛
                        """

                    await app.leave_chat(src)
                    await app.stop()
                    remove_if_exists(f"{msg.from_user.id}_account.session")
                    return await nr.edit_text(ttext,reply_markup=keyboard)

        except Exception as e:
            # معالجة الأخطاء...
            await app.stop()
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text(f"**ERROR:** `{str(e)}`",reply_markup=keyboard)

    elif type == "m":
        try:
            await nr.edit_text("**.... STARTING MIXED MEMBER ADDING ....**")
            await edit_mixed(nr)
            await asyncio.sleep(0.5)
            async for member in app.get_chat_members(schat_id):
                user = member.user
                if user.is_bot:
                    pass
                else:
                    try:
                        user_id = user.id
                        await nr.edit_text(f'TRYING TO ADD: `{user_id}`')
                        if await app.add_chat_members(dchat_id, user_id):
                            cc = cc+1
                            await nr.edit_text(f'ADDED: `{user_id}`')
                            await asyncio.sleep(5)
                    except FloodWait1 as fl:
                        t = "FLOODWAIT DETECTED IN USER ACCOUNT\n\nSTOPPED ADDING PROCESS"
                        await nr.edit_text(t)
                        x2 = await app.get_chat(dchat_id)
                        t2 = x2.members_count
                        completed_in = datetime.timedelta(
                        seconds=int(time.time() - start_time))
                        ttext = f"""
<u>**✨ Stopped adding process due to Floodwait of {fl.value}s ✨**</u>

    ┏━━━━━━━━━━━━━━━━━┓
    ┣✨ Added to chat Id: `{dchat_id}`
    ┣✨ Previous chat member count : **{tt}**
    ┣✨ Current chat member count : **{t2}**
    ┣✨ Total users added : **{cc}**
    ┣✨ Total time taken : **{completed_in}**s
    ┗━━━━━━━━━━━━━━━━━┛
                                """
                        await app.leave_chat(src)
                        await app.stop()
                        remove_if_exists(f"{msg.from_user.id}_account.session")
                        return await nr.edit_text(ttext,reply_markup=keyboard)
                    except Exception as e:
                        await asyncio.sleep(5)

                if cc == count:
                    x2 = await app.get_chat(dchat_id)
                    t2 = x2.members_count
                    completed_in = datetime.timedelta(
                    seconds=int(time.time() - start_time))
                    ttext = f"""
<u>**✨ Successfully completed adding process ✨**</u>

    ┏━━━━━━━━━━━━━━━━━┓
    ┣✨ Added to chat Id: `{dchat_id}`
    ┣✨ Previous chat member count : **{tt}**
    ┣✨ Current chat member count : **{t2}**
    ┣✨ Total users added : **{cc}**
    ┣✨ Total time taken : **{completed_in}**s
    ┗━━━━━━━━━━━━━━━━━┛
                        """

                    await app.leave_chat(src)
                    await app.stop()
                    remove_if_exists(f"{msg.from_user.id}_account.session")
                    return await nr.edit_text(ttext,reply_markup=keyboard)

        except Exception as e:
            await app.stop()
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text(f"**ERROR:** `{str(e)}`",reply_markup=keyboard)

# -----------------------------------------------------------------------------
# 10. Login Function (بقية الدوال تبقى كما هي)
# -----------------------------------------------------------------------------

PHONE_NUMBER_TEXT = (
    "أرسل الآن رقم هاتف حساب Telegram الخاص بك بالتنسيق الدولي.  \n"
     "تضمين رمز البلد. مثال: ** + +14154566376 ** \n\n"
     "اضغط /cancel لإلغاء المهمة."
)

API_TEXT = (
    "ارسل الايدي الخاص بك ...\n\n اذا لا تعرف من اين تحصل على الايدي\n 1- اذهب الى موقع تلغرام هذا👇\n http://my.telegram.org \n 2- انسخ الايدي ثما ارسله هنا`"
)

HASH_TEXT = (
    "ارسل api Hash \n\n اذا لا تعرف من اين تحصل على api Hash \n 1- اذهب الى موقع تلغرام هذا👇\n http://my.telegram.org  \n2- انسخ api Hash ثما ارسله هنا`"
)

async def genStr(_, msg: Message):
    nr = await msg.reply_text("**.... NoRa BOTS ....**")
    await edit_nrbots(nr)
    await asyncio.sleep(0.4)
    await nr.delete()
    await msg.reply("{}! لمزيد من الأمان لحسابك ، يجب أن تزودني بـ api_id و api_hash لتسجيل الدخول إلى حسابك\n\n⚠️ يرجى تسجيل الدخول إلى حسابك الوهمي ، ولا تستخدم حسابك الحقيقي ⚠️\n\n شاهد طريقة الحصول على api id , api Hash \n\n https://youtu.be/NsbhYHz7K_w️".format(msg.from_user.mention))
    await asyncio.sleep(2)
    chat = msg.chat
    api = await bot.ask(
        chat.id, API_TEXT)
    
    if await is_cancel(msg, api.text):
        return
    try:
        check_api = int(api.text)
    except Exception:
        await msg.reply("`APP_ID` غير صالح.\nاضغط على /login لتسجيل مره اخرى.")
        return
    api_id = api.text
    hash = await bot.ask(chat.id, HASH_TEXT)
    if await is_cancel(msg, hash.text):
        return
    if not len(hash.text) >= 30:
        await msg.reply("`api_Hash` غير صالح.\nاضغط على /login لتسجيل مره اخرى")
        return
    api_hash = hash.text
    while True:
        number = await bot.ask(chat.id, PHONE_NUMBER_TEXT)
        if not number.text:
            continue
        if await is_cancel(msg, number.text):
            return
        phone = number.text
        confirm = await bot.ask(chat.id, f'هذا "{phone}" صحيح؟ (y/n): \n\nارسل: `y` (اذا كان اارقم صحيح ارسل y )\nارسل: `n` (اذا كان الرقم خطأ ارسل n)')
        if await is_cancel(msg, confirm.text):
            return
        confirm = confirm.text.lower()
        if confirm == "y":
            break
    try:
        client = Client(f"{chat.id}_account", api_id=api_id, api_hash=api_hash,in_memory=True)
    except Exception as e:
        await bot.send_message(chat.id ,f"**ERROR:** `{str(e)}`\nPress /login to Start again.")
        return
    try:
        await client.connect()
    except ConnectionError:
        await client.disconnect()
        await client.connect()
    try:
        code = await client.send_code(phone)
        await asyncio.sleep(1)
    except FloodWait1 as e:
        await msg.reply(f"You account have Floodwait of {e.value} Seconds. Please try after {e.value} Seconds")
        return
    except ApiIdInvalid1:
        await msg.reply("APP ID and API Hash are Invalid.\n\nPress /login to Start again.")
        return
    except PhoneNumberInvalid1:
        await msg.reply("رقمك هذا غير صحيح.\n\nاضغط /login لتسجيل مره اخرى.")
        return
    try:
        a = """
يتم إرسال كود مكون من خمسه ارقام إلى رقم هاتفك ، 
الرجاء ارسال الكود بتنسيق هذا 1 2 3 4 5. (مسافة بين كل رقم!) \n
إذا لم يرسل Bot OTP ، فحاول  أعد تشغيل وابدأ المهمة مرة أخرى باستخدام الأمر /start إلى Bot.
اضغط /cancel للإلغاء.."""
        otp = await bot.ask(chat.id, a
                    , timeout=300
                    )

    except asyncio.exceptions.TimeoutError:
        await msg.reply("بلغ الحد الزمني 5 دقائق.\n اضغط /login الدخول للبدء من جديد")
        return
    if await is_cancel(msg, otp.text):
        return
    otp_code = otp.text
    try:
        await client.sign_in(phone, code.phone_code_hash, phone_code=' '.join(str(otp_code)))
    except PhoneCodeInvalid1:
        await msg.reply("رمز غير صالح. \n\n اضغط /login الدخول للبدء من جديد..")
        return
    except PhoneCodeExpired1:
        await msg.reply("Code is Expired.\n\nPress /login to Start again.")
        return
    except SessionPasswordNeeded1:
        try:
            two_step_code = await bot.ask(
                chat.id, 
                "حسابك يوجد فيه تحقق بخطوتين.\nارسل رمز تحقق بخطوتين او .\n\nاضغط /cancel للإلغاء.",
                timeout=300
            )
        except asyncio.exceptions.TimeoutError:
            await msg.reply("`Time limit reached of 5 min.\n\nPress /login to Start again.`")
            return
        if await is_cancel(msg, two_step_code.text):
            return
        new_code = two_step_code.text
        try:
            await client.check_password(new_code)
        except Exception as e:
            await msg.reply(f"**ERROR:** `{str(e)}`")
            return
    except Exception as e:
        await bot.send_message(chat.id ,f"**ERROR:** `{str(e)}`")
        return
    try:
        session_string = await client.export_session_string()
        await bot.send_message(chat.id,"✅ حسابك متصل بنجاح",)
        await db.set_session(chat.id, session_string)
        await db.set_api(chat.id,api_id)
        await db.set_hash(chat.id,api_hash)
        await db.set_login(chat.id,True)
        await client.disconnect()
    except Exception as e:
        await bot.send_message(chat.id ,f"**ERROR:** `{str(e)}`")
        return

# -----------------------------------------------------------------------------
# 11. Main Function with Keep Alive
# -----------------------------------------------------------------------------

async def main():
    global db
    db = Database()
    await db._initialize_files()
    
    # بدء الخادم الويب
    app = web.AppRunner(await web_server())
    await app.setup()
    bind_address = "0.0.0.0"
    await web.TCPSite(app, bind_address, PORT).start()
    
    # بدء البوت
    await bot.start()
    print("Bot Started")
    
    # بدء دالة الحفاظ على النشاط
    asyncio.create_task(keep_alive())
    
    await idle()
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
