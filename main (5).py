# -*- coding: utf-8 -*-

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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8398354970:AAHqgmpKPptjDgI_Ogs1fKnBgfPi4N8SoR4")
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
    # plugins=dict(root="plugins"), # Handlers will be defined directly
)





# -----------------------------------------------------------------------------
# 5. Web Functions
# -----------------------------------------------------------------------------

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    bot_log_path = f"logs.txt"
    m_list = open(bot_log_path, "r").read()
    message_s = m_list.replace("\n","")
    return web.json_response(message_s)


async def web_server():
    web_app = web.Application(client_max_size=30000000000)
    web_app.add_routes(routes)
    return web_app


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
            r"^(?:http|ftp)s?://" # http:// or https://
            r"t.me|"
            r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|" #domain...
            r"localhost|" #localhost...
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})" # ...or ip
            r"(?::\d+)?" # optional port
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
START_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("تسجيل الدخول", callback_data="login"), InlineKeyboardButton("نقل الأعضاء", callback_data="memadd")],
        [InlineKeyboardButton("الحالة", callback_data="status"), InlineKeyboardButton("المساعدة", callback_data="help")],
        [InlineKeyboardButton("إلغاء", callback_data="cancel")]
    ]
)


HELP_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("الرئيسية", callback_data="home")],
        [InlineKeyboardButton("إغلاق", callback_data="close")]
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
    # This function was empty in the original, keeping it as a placeholder
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
async def memadd(client: Client, message: Message):
    await message.reply_text(
                    text=START.format(message.from_user.mention),
            disable_web_page_preview=True,
            reply_markup=START_BUTTONS)


@bot.on_callback_query(filters.regex("home"))
async def home_callback(client, callback_query):
    await callback_query.message.edit_text(
        text=START.format(callback_query.from_user.mention),
        disable_web_page_preview=True,
        reply_markup=START_BUTTONS
    )

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

@bot.on_callback_query(filters.regex("memadd"))
async def memadd_callback(client, callback_query):
    await memadd(client, callback_query.message)

@bot.on_callback_query(filters.regex("status"))
async def status_callback(client, callback_query):
    await status(client, callback_query.message)

@bot.on_callback_query(filters.regex("cancel"))
async def cancel_callback(client, callback_query):
    await callback_query.message.edit_text("تم إلغاء العملية.")

@bot.on_callback_query(filters.regex("close"))
async def close_callback(client, callback_query):
    await callback_query.message.delete()

@bot.on_message(filters.command("ping"))
async def ping_pong(client, message):       
    start = time()
    m_reply = await message.reply_text("checking ping...")
    delta_ping = time() - start
    current_time = datetime.datetime.utcnow()
    uptime_sec = (current_time - START_TIME).total_seconds()
    uptime = await _human_time_duration(int(uptime_sec))
    await m_reply.edit_text(
        f"🏓 **PING:**  **{delta_ping * 1000:.3f} ms** \n"
        f"⚡️ **Uptime:** **{uptime}**\n\n "
        f"💖 ** @nrbots**"
    )

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

        # Attempt to join the source chat. For public groups, get_chat_members should work without being an admin.
        # For private groups, joining might require an invite link or admin privileges, which is beyond the scope of this request.
        # We will proceed with get_chat_members assuming it's a public group or the user account can access it.
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
                            e = str(e)
                            if "Client has not been started yet" in e:
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("Client has not been started yet",reply_markup=keyboard)
                            elif "403 USER_PRIVACY_RESTRICTED" in e:
                                await nr.edit_text("failed to add because of The user's privacy settings")
                                await asyncio.sleep(1)
                            elif "400 CHAT_ADMIN_REQUIRED" in e:
                                await nr.edit_text("Failed to get members from source group because admin privileges are required. Please ensure the source group is public or your account is an admin there.",reply_markup=keyboard)
                                await app.stop()
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("Failed to get members from source group because admin privileges are required. Please ensure the source group is public or your account is an admin there.",reply_markup=keyboard)

                            elif "400 INVITE_REQUEST_SENT" in e:
                                await app.stop()
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("hey i cant scrape/add members from a group where i need admin approval to join chat.",reply_markup=keyboard)
                            elif "400 PEER_FLOOD" in e:
                                await app.stop()
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("Adding stopped due to 400 PEER_FLOOD\n\nyour account is limited please wait sometimes then try again.",reply_markup=keyboard)
                            elif "401 AUTH_KEY_UNREGISTERED" in e:
                                await app.stop()
                                await db.set_session(msg.from_user.id, "")
                                await db.set_login(msg.from_user.id,False)
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("please login again to use this feature",reply_markup=keyboard)
                            elif "403 CHAT_WRITE_FORBIDDEN" in e:
                                await app.stop()
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("You don't have rights to add members in this chat\nPlease make user your account admin and try again",reply_markup=keyboard)
                            elif "400 CHANNEL_INVALID" in e:
                                await app.stop()
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("The source or destination username is invalid",reply_markup=keyboard)
                            elif "400 USERNAME_NOT_OCCUPIED" in e:
                                await app.stop()
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("The username is not occupied by anyone please check the username or userid that you have provided",reply_markup=keyboard)
                            elif "401 SESSION_REVOKED" in e:
                                await app.stop()
                                await db.set_session(msg.from_user.id, "")
                                await db.set_login(msg.from_user.id,False)
                                remove_if_exists(f"{msg.from_user.id}_account.session")
                                return await nr.edit_text("you have terminated the login session from the user account \n\nplease login again",reply_markup=keyboard)
                            else:
                                await nr.edit_text(f'FAILED TO ADD \n\n**ERROR:** `{str(e)}`')
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
            e = str(e)
            if "Client has not been started yet" in e:
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("Client has not been started yet",reply_markup=keyboard)
            elif "403 USER_PRIVACY_RESTRICTED" in e:
                await nr.edit_text("failed to add because of The user's privacy settings",reply_markup=keyboard)
                await asyncio.sleep(1)
            elif "400 CHAT_ADMIN_REQUIRED" in e:
                await nr.edit_text("failed to add because of This method requires chat admin privileges.\n\nplease make your account admin on the group and try again",reply_markup=keyboard)
            elif "400 INVITE_REQUEST_SENT" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("hey i cant scrape/add members from a group where i need admin approval to join chat.",reply_markup=keyboard)
            elif "400 PEER_FLOOD" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("Adding stopped due to 400 PEER_FLOOD\n\nyour account is limited please wait sometimes then try again.",reply_markup=keyboard)
            elif "401 AUTH_KEY_UNREGISTERED" in e:
                await app.stop()
                await db.set_session(msg.from_user.id, "")
                await db.set_login(msg.from_user.id,False)
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("please login again to use this feature",reply_markup=keyboard)
            elif "403 CHAT_WRITE_FORBIDDEN" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("You don't have rights to send messages in this chat\nPlease make user account admin and try again",reply_markup=keyboard)
            elif "400 CHANNEL_INVALID" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("The source or destination username is invalid",reply_markup=keyboard)
            elif "400 USERNAME_NOT_OCCUPIED" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("The username is not occupied by anyone please check the username or userid that you have provided",reply_markup=keyboard)
            elif "401 SESSION_REVOKED" in e:
                await app.stop()
                await db.set_session(msg.from_user.id, "")
                await db.set_login(msg.from_user.id,False)
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("you have terminated the login session from the user account \n\nplease login again",reply_markup=keyboard)
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
                        e = str(e)
                        if "Client has not been started yet" in e:
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("Client has not been started yet",reply_markup=keyboard)
                        elif "403 USER_PRIVACY_RESTRICTED" in e:
                            await nr.edit_text("failed to add because of The user's privacy settings")
                            await asyncio.sleep(1)
                        elif "400 CHAT_ADMIN_REQUIRED" in e:
                            await nr.edit_text("failed to add because of This method requires chat admin privileges.\n\nplease make your account admin on the group and try again",reply_markup=keyboard)
                        elif "400 INVITE_REQUEST_SENT" in e:
                            await app.stop()
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("hey i cant scrape/add members from a group where i need admin approval to join chat.",reply_markup=keyboard)
                        elif "400 PEER_FLOOD" in e:
                            await app.stop()
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("Adding stopped due to 400 PEER_FLOOD\n\nyour account is limited please wait sometimes then try again.",reply_markup=keyboard)
                        elif "401 AUTH_KEY_UNREGISTERED" in e:
                            await app.stop()
                            await db.set_session(msg.from_user.id, "")
                            await db.set_login(msg.from_user.id,False)
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("please login again to use this feature",reply_markup=keyboard)
                        elif "403 CHAT_WRITE_FORBIDDEN" in e:
                            await app.stop()
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("You don't have rights to add members in this chat\nPlease make user your account admin and try again",reply_markup=keyboard)
                        elif "400 CHANNEL_INVALID" in e:
                            await app.stop()
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("The source or destination username is invalid",reply_markup=keyboard)
                        elif "400 USERNAME_NOT_OCCUPIED" in e:
                            await app.stop()
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("The username is not occupied by anyone please check the username or userid that you have provided",reply_markup=keyboard)
                        elif "401 SESSION_REVOKED" in e:
                            await app.stop()
                            await db.set_session(msg.from_user.id, "")
                            await db.set_login(msg.from_user.id,False)
                            remove_if_exists(f"{msg.from_user.id}_account.session")
                            return await nr.edit_text("you have terminated the login session from the user account \n\nplease login again",reply_markup=keyboard)
                        else:
                            await nr.edit_text(f'FAILED TO ADD \n\n**ERROR:** `{str(e)}`')
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
            e = str(e)
            if "Client has not been started yet" in e:
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("Client has not been started yet",reply_markup=keyboard)
            elif "403 USER_PRIVACY_RESTRICTED" in e:
                await nr.edit_text("failed to add because of The user's privacy settings",reply_markup=keyboard)
                await asyncio.sleep(1)
            elif "400 CHAT_ADMIN_REQUIRED" in e:
                await nr.edit_text("failed to add because of This method requires chat admin privileges.\n\nplease make your account admin on the group and try again",reply_markup=keyboard)
            elif "400 INVITE_REQUEST_SENT" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("hey i cant scrape/add members from a group where i need admin approval to join chat.",reply_markup=keyboard)
            elif "400 PEER_FLOOD" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("Adding stopped due to 400 PEER_FLOOD\n\nyour account is limited please wait sometimes then try again.",reply_markup=keyboard)
            elif "401 AUTH_KEY_UNREGISTERED" in e:
                await app.stop()
                await db.set_session(msg.from_user.id, "")
                await db.set_login(msg.from_user.id,False)
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("please login again to use this feature",reply_markup=keyboard)
            elif "403 CHAT_WRITE_FORBIDDEN" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("You don't have rights to send messages in this chat\nPlease make user account admin and try again",reply_markup=keyboard)
            elif "400 CHANNEL_INVALID" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("The source or destination username is invalid",reply_markup=keyboard)
            elif "400 USERNAME_NOT_OCCUPIED" in e:
                await app.stop()
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("The username is not occupied by anyone please check the username or userid that you have provided",reply_markup=keyboard)
            elif "401 SESSION_REVOKED" in e:
                await app.stop()
                await db.set_session(msg.from_user.id, "")
                await db.set_login(msg.from_user.id,False)
                remove_if_exists(f"{msg.from_user.id}_account.session")
                return await nr.edit_text("you have terminated the login session from the user account \n\nplease login again",reply_markup=keyboard)
            await app.stop()
            remove_if_exists(f"{msg.from_user.id}_account.session")
            return await nr.edit_text(f"**ERROR:** `{str(e)}`",reply_markup=keyboard)


@bot.on_message(filters.private & filters.command("memadd"))
async def NewChat(client, msg):
    try:
        chat = msg.chat
        nr = await msg.reply_text(".... NR BOTS ....")
        await edit_nrbots(nr)
        userr = msg.from_user.id
        if not await db.get_session(userr):
            return await nr.edit_text("please /login to use this feature.")

        await nr.delete()
        while True:
            src_raw = await bot.ask(chat.id, "أرسل لي الآن رابط مجموعة عامة من حيث تريد كشط ونقل الأعضاء منها.")
            if not src_raw.text:
                continue
            if await is_cancel(msg, src_raw.text):
                return
            src = if_url(src_raw.text)
            
            dest_raw = await bot.ask(chat.id, "أرسل لي الآن رابط مجموعة عامة حيث تريد إضافة أعضاء اليها.")
            if await is_cancel(msg, dest_raw.text):
                return
            dest = if_url(dest_raw.text)
            quant_raw = await bot.ask(chat.id, "أرسل لي الآن الكمية . كم عدد الأعضاء الذي تريد إضافتها الى مجموعتك.\n\nعلى سبيل المثال ارسل: 5\n\nمن أجل أمان حساباتك ضد حظر الاضافه ، يرجى تزويدنا برقم أقل من 20 رقمًا ")
            if await is_cancel(msg, quant_raw.text):
                return
            quant = int(quant_raw.text)
            type_raw = await bot.ask(chat.id, f'اختر الآن أي نوع من الأعضاء تريد كشطه من مجموعه `{src}`\n\nلنقل اعضاء 👤 نشطين👤 أرسل  `a`\n\nلنقل اعضاء 👥 مختلط 👥 أرسل الأعضاء `m`. \n\nارسل: `a` (إذا كنت تريد اعضاء نشطًين)\nارسل: `m` (إذا كنت تريد اعضاء نشطًين)')
            if await is_cancel(msg, type_raw.text):
                return
            type = type_raw.text.lower()

            confirm = await bot.ask(chat.id, f'أنت تريد إضافة `{quant}` {"`👤 أعضاء نشطين 👤`" if type == "a" else "`👥 أعضاء مختلطين 👥`"} من مجموعه `{src}` الى مجموعتك `{dest}`\n\n`هل هذا متاكد من الاضافه؟  (y / n):` \n\nارسل: `y` (إذا كانت الإجابة نعم)\nارسل: `n` (إذا كانت الإجابة لا)')
            if await is_cancel(msg, confirm.text):
                return
            confirm = confirm.text.lower()
            if confirm == "y":
                break
        try:
            await add(msg, src=src, dest=dest, count=quant, type=type)
        except Exception as e:
            return await msg.reply_text(f"**ERROR:** `{str(e)}`",reply_markup=keyboard)
    except Exception as e:
        return await msg.reply_text(f"**ERROR:** `{str(e)}`",reply_markup=keyboard)


@bot.on_message(filters.command(["eval"], [".", "/", "!"]))
async def executor(client, message):
    if message.from_user.id not in AUTH_USERS:
        return
    if len(message.command) < 2:
        return await edit_or_reply(message, text="» Give a command to execute")
    try:
        cmd = message.text.split(" ", maxsplit=1)[1]
    except IndexError:
        return await message.delete()
    t1 = time.time()
    old_stderr = sys.stderr
    old_stdout = sys.stdout
    redirected_output = sys.stdout = StringIO()
    redirected_error = sys.stderr = StringIO()
    stdout, stderr, exc = None, None, None
    try:
        await aexec(cmd, client, message)
    except Exception:
        exc = traceback.format_exc()
    stdout = redirected_output.getvalue()
    stderr = redirected_error.getvalue()
    sys.stdout = old_stdout
    sys.stderr = old_stderr
    evaluation = ""
    if exc:
        evaluation = exc
    elif stderr:
        evaluation = stderr
    elif stdout:
        evaluation = stdout
    else:
        evaluation = "SUCCESS"
    final_output = f"`OUTPUT:`\n\n```{evaluation.strip()}```"
    if len(final_output) > 4096:
        filename = "output.txt"
        with open(filename, "w+", encoding="utf8") as out_file:
            out_file.write(str(evaluation.strip()))
        t2 = time.time()
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="⏳", callback_data=f"runtime {t2-t1} seconds"
                    )
                ]
            ]
        )
        await message.reply_document(
            document=filename,
            caption=f"INPUT:\n{cmd[0:980]}\n\nOUTPUT:\nattached document",
            quote=False,
            reply_markup=keyboard,
        )
        await message.delete()
        os.remove(filename)
    else:
        t2 = time.time()
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="⏳",
                        callback_data=f"runtime {round(t2-t1, 3)} seconds",
                    )
                ]
           ]
        )
        await edit_or_reply(message, text=final_output, reply_markup=keyboard)


@bot.on_message(filters.command(["sh"], [".", "/", "!"]))
async def shell(client, message):
    if message.from_user.id not in AUTH_USERS:
        return
    if len(message.command) < 2:
        return await edit_or_reply(message, text="**usage:**\n\n» /sh echo hello world")
    text = message.text.split(None, 1)[1]
    if "\n" in text:
        code = text.split("\n")
        output = ""
        for x in code:
            shell = re.split(""" (?=(?:[^"]|\'[^"]*\'|\"[^\"]*\")*$)""", x)
            try:
                process = subprocess.Popen(
                    shell,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as err:
                print(err)
                await edit_or_reply(message, text=f"`ERROR:`\n\n```{err}```")
            output += f"**{code}**\n"
            output += process.stdout.read()[:-1].decode("utf-8")
            output += "\n"
    else:
        shell = re.split(""" (?=(?:[^"]|\'[^"]*\'|\"[^\"]*\")*$)""", text)
        for a in range(len(shell)):
            shell[a] = shell[a].replace("\"", "")
        try:
            process = subprocess.Popen(
                shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as err:
            print(err)
            exc_type, exc_obj, exc_tb = sys.exc_info()
            errors = traceback.format_exception(
                etype=exc_type,
                value=exc_obj,
                tb=exc_tb,
            )
            return await edit_or_reply(
                message, text=f"`ERROR:`\n\n```" + "".join(errors) + "```"
            )
        output = process.stdout.read()[:-1].decode("utf-8")
    if str(output) == "\n":
        output = None
    if output:
        if len(output) > 4096:
            with open("output.txt", "w+") as file:
                file.write(output)
            await bot.send_document(
                message.chat.id,
                "output.txt",
                reply_to_message_id=message.message_id,
                caption="`OUTPUT`",
            )
            return remove_if_exists("output.txt")
        await edit_or_reply(message, text=f"`OUTPUT:`\n\n```{output}```")
    else:
        await edit_or_reply(message, text="`OUTPUT:`\n\n`no output`")


@bot.on_message(filters.incoming & filters.private, group=-1)
async def check(client, msg):
    await handle_user_status(client, msg)

@bot.on_message(filters.private & filters.command("stats"))
async def sts(c, m):
    if m.from_user.id not in AUTH_USERS:
        return
    try:
        n = await m.reply_text("Collecting Bot stats...\n\nthis will take some time...")
        bu = await db.total_users_count()
        
        await n.edit_text(f"**Total Bot Users: {bu}**")
    except BaseException:
        traceback.print_exc()
        await m.reply_text(
            f"Error occoured ⚠️! Traceback given below\n\n`{traceback.format_exc()}`",
            quote=True
        )


@bot.on_message(filters.private & filters.command("ban"))
async def ban(c, m):
    if m.from_user.id not in AUTH_USERS:
        return
    if len(m.command) == 1:
        await m.reply_text(
            f"Use this command to restrict / ban any user from using this bot.\n\nUsage:\n\n`/ban user_id ban_duration ban_reason`\n\nEg: `/ban 1234567 10 you abused our bot.`\n This will ban user with id `1234567` for `10` days for the reason `you abused our bot`.",
            quote=True,
        )
        return

    try:
        user_id = int(m.command[1])
        ban_duration = int(m.command[2])
        ban_reason = " ".join(m.command[3:])
        ban_log_text = f"Banning user {user_id} for {ban_duration} days for the reason {ban_reason}."

        try:
            await c.send_message(
                user_id,
                f"**Important Message From Bot Owner**\n\nMy Owner Banned You to use this bot for **{ban_duration}** day(s) for the reason __{ban_reason}__ ",
            )
            ban_log_text += "\n\n✅ User notified successfully! ✅"
        except BaseException:
            traceback.print_exc()
            ban_log_text += (
                f"\n\n ⚠️ User notification failed! ⚠️ \n\n`{traceback.format_exc()}`"
            )
        await db.ban_user(user_id, ban_duration, ban_reason)
        print(ban_log_text)
        await m.reply_text(ban_log_text, quote=True)
    except BaseException:
        traceback.print_exc()
        await m.reply_text(
            f"Error occoured ⚠️! Traceback given below\n\n`{traceback.format_exc()}`",
            quote=True
        )


@bot.on_message(filters.private & filters.command("unban"))
async def unban(c, m):
    if m.from_user.id not in AUTH_USERS:
        return
    if len(m.command) == 1:
        await m.reply_text(
            f"Use this command to unban any user.\n\nUsage:\n\n`/unban user_id`\n\nEg: `/unban 1234567`\n This will unban user with id `1234567`.",
            quote=True,
        )
        return

    try:
        user_id = int(m.command[1])
        unban_log_text = f"Unbanning user 🤪 {user_id}"

        try:
            await c.send_message(user_id, f"**Important Message From Bot Owner**\n\nMy Owner Unbanned You Now You Can Use This Bot")
            unban_log_text += "\n\n✅ User notified successfully! ✅"
        except BaseException:
            traceback.print_exc()
            unban_log_text += (
                f"\n\n⚠️ User notification failed! ⚠️\n\n`{traceback.format_exc()}`"
            )
        await db.remove_ban(user_id)
        print(unban_log_text)
        await m.reply_text(unban_log_text, quote=True)
    except BaseException:
        traceback.print_exc()
        await m.reply_text(
            f"⚠️ Error occoured ⚠️! Traceback given below\n\n`{traceback.format_exc()}`",
            quote=True,
        )


@bot.on_message(filters.private & filters.command("banned"))
async def _banned_usrs(c, m):
    if m.from_user.id not in AUTH_USERS:
        return
    all_banned_users = await db.get_all_banned_users()
    banned_usr_count = 0
    text = ""
    async for banned_user in all_banned_users:
        user_id = banned_user["id"]
        ban_duration = banned_user["ban_status"]["ban_duration"]
        banned_on = banned_user["ban_status"]["banned_on"]
        ban_reason = banned_user["ban_status"]["ban_reason"]
        banned_usr_count += 1
        text += f"> **User_id**: `{user_id}`, **Ban Duration**: `{ban_duration}`, **Banned on**: `{banned_on}`, **Reason**: `{ban_reason}`\n\n"
    reply_text = f"Total banned user(s) 🤭: `{banned_usr_count}`\n\n{text}"
    if len(reply_text) > 4096:
        with open("banned-users.txt", "w") as f:
            f.write(reply_text)
        await m.reply_document("banned-users.txt", True)
        os.remove("banned-users.txt")
        return
    await m.reply_text(reply_text, True)
async def send_msg(user_id, message):
    global BROADCAST_AS_COPY # Ensure global variable is used
    BROADCAST_AS_COPY = await db.get_bcopy() # Update from DB
    try:
        if BROADCAST_AS_COPY is False:
            await message.forward(chat_id=user_id)
        elif BROADCAST_AS_COPY is True:
            await message.copy(chat_id=user_id)
        return 200, None
    except FloodWait1 as e:
        await asyncio.sleep(e.x)
        return await send_msg(user_id, message)
    except InputUserDeactivated:
        return 400, f"{user_id} : deactivated\n"
    except UserIsBlocked:
        return 400, f"{user_id} : blocked the bot\n"
    except PeerIdInvalid:
        return 400, f"{user_id} : user id invalid\n"
    except Exception:
        return 500, f"{user_id} : {traceback.format_exc()}\n"


async def broadcast(m, db_instance):
    all_users = await db_instance.get_all_notif_user()
    broadcast_msg = m.reply_to_message
    while True:
        broadcast_id = "".join([random.choice(string.ascii_letters) for i in range(3)])
        if not broadcast_ids.get(broadcast_id):
            break
    out = await m.reply_text(
        text=f"Broadcast Started! You will be notified with log file when all the users are notified."
    )
    start_time = time.time()
    total_users = await db_instance.total_users_count()
    done = 0
    failed = 0
    success = 0
    broadcast_ids[broadcast_id] = dict(
        total=total_users, current=done, failed=failed, success=success
    )
    async with aiofiles.open("broadcast.txt", "w") as broadcast_log_file:
        async for user in all_users:
            sts, msg = await send_msg(user_id=int(user["id"]), message=broadcast_msg)
            if msg is not None:
                await broadcast_log_file.write(msg)
            if sts == 200:
                success += 1
            else:
                failed += 1
            if sts == 400:
                await db_instance.delete_user(user["id"])
            done += 1
            if broadcast_ids.get(broadcast_id) is None:
                break
            else:
                broadcast_ids[broadcast_id].update(
                    dict(current=done, failed=failed, success=success)
                )
    if broadcast_ids.get(broadcast_id):
        broadcast_ids.pop(broadcast_id)
    completed_in = datetime.timedelta(seconds=int(time.time() - start_time))
    await asyncio.sleep(3)
    await out.delete()
    if failed == 0:
        await m.reply_text(
            text=f"broadcast completed in `{completed_in}`\n\nTotal users {total_users}.\nTotal done {done}, {success} success and {failed} failed.",
            quote=True,
        )
    else:
        await m.reply_document(
            document="broadcast.txt",
            caption=f"broadcast completed in `{completed_in}`\n\nTotal users {total_users}.\nTotal done {done}, {success} success and {failed} failed.",
            quote=True,
        )
    os.remove("broadcast.txt")


@bot.on_message(filters.private & filters.command("broadcast"))
async def broadcast_handler_open(_, m):
    if m.from_user.id not in AUTH_USERS:
        return
    if m.reply_to_message is None:
        await m.delete()
    else:
        await broadcast(m, db)


@bot.on_message(filters.command("fsub"))       
async def run_l(bt,m):
    if m.from_user.id not in AUTH_USERS:
        return
    if len(m.command) == 1:
        await m.reply_text(
            f"Use this command to set into the botn\nUsage:\n\n`/fsub on|off`\n\nEg: `/fsub on`",
           
        )
        return
    fsub = (m.command[1])
    if fsub == "on":
        await db.set_fsub(True)
        await m.reply_text(f"successfully started fsub")
    elif fsub == "off":
        await db.set_fsub(False)
        await m.reply_text(f"successfully stopped fsub")
    else:
        await m.reply_text(
            f"Use this command to set into the botn\nUsage:\n\n`/fsub on|off`\n\nEg: `/fsub on`",
           
        )

@bot.on_message(filters.command("channel"))       
async def set_c(bt,m):
    if m.from_user.id not in AUTH_USERS:
        return
    if len(m.command) == 1:
        await m.reply_text(
            f"Use this command to set fsub channel of the bot\n\nUsage:\n\n`/channel channel username or channel id with -100`\n\nEg: `/channel nrbots`",
           
        )
        return
    c = m.command[1]
    await db.set_fsub_channel(c)
    await m.reply_text(f"successfully set fsub channel to @{c}\n\nplease wait few seconds for update")
@bot.on_message(filters.command("b_copy"))       
async def run_l(bt,m):
    if m.from_user.id not in AUTH_USERS:
        return
    if len(m.command) == 1:
        await m.reply_text(
            f"Use this command to set broadcast as copy\n\nUsage:\n\n`/b_copy on|off`\n\nEg: `/b_copy on`",
           
        )
        return
    fsub = (m.command[1])
    if fsub == "on":
        await db.set_bcopy(True)
        await m.reply_text(f"successfully set broadcast as copy")
    elif fsub == "off":
        await db.set_bcopy(False)
        await m.reply_text(f"successfully broadcast as forward")
    else:
        await m.reply_text(
            f"Use this command to set broadcast as copy\n\nUsage:\n\n`/b_copy on|off`\n\nEg: `/b_copy on`",
           
        )


@bot.on_message(filters.command("paste") & ~filters.bot)
async def paste(client, message):
    pablo = await eor(message, "`Please Wait.....`")
    tex_t = get_text(message)
    message_s = tex_t
    if not tex_t:
        if not message.reply_to_message:
            await pablo.edit("`Reply To File / Give Me Text To Paste!`")
            return
        if not message.reply_to_message.text:
            file = await message.reply_to_message.download()
            m_list = open(file, "r").read()
            message_s = m_list
            os.remove(file)
        elif message.reply_to_message.text:
            message_s = message.reply_to_message.text
    key = (
        requests.post("https://nekobin.com/api/documents", json={"content": message_s})
        .json()
        .get("result")
        .get("key")
    )
    url = f"https://nekobin.com/{key}"
    raw = f"https://nekobin.com/raw/{key}"
    reply_text = f"Pasted Text To [NekoBin]({url}) And For Raw [Click Here]({raw})"
    await pablo.edit(reply_text,disable_web_page_preview=True)
    link = f"https://webshot.deam.io/{url}/?delay=2000"
    await client.send_photo(message.chat.id, link, caption=f"Screenshort")


@bot.on_message(filters.command("restart"))
async def restart_bot(_, message):
    if message.from_user.id not in AUTH_USERS:
        return
    try:
        msg = await message.reply_text("❖ Restarting bot...")
        LOGS.info("BOT RESTARTED !!")
    except BaseException as err:
        LOGS.error(f"{err}")
        return
    await msg.edit_text("✅ تمت إعادة تشغيل الروبوت! \ n \ n »نشط مرة أخرى في غضون 5-10 ثوان.")
    os.system(f"kill -9 {os.getpid()} && python3 main.py") # Changed startup.py to main.py
    


@bot.on_message(filters.command("quit"))
async def restart_bot(_, message):
    if message.from_user.id not in AUTH_USERS:
        return
    try:
        msg = await message.reply_text("❖ Stopping bot...")
        LOGS.info("Bot stopped !!")
    except BaseException as err:
        LOGS.error(f"{err}")
        return
    await msg.edit_text("✅ البوت تم إيقافه !")
    os.system(f"kill -9 {os.getpid()}")


@bot.on_message(filters.command("sysinfo"))
async def fetch_system_information(client, message):
    if message.from_user.id not in AUTH_USERS:
        return
    splatform = platform.system()
    platform_release = platform.release()
    platform_version = platform.version()
    architecture = platform.machine()
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(socket.gethostname())
    mac_address = ":".join(re.findall("..", "%012x" % uuid.getnode()))
    processor = platform.processor()
    ram = humanbytes(round(psutil.virtual_memory().total))
    cpu_freq = psutil.cpu_freq().current
    if cpu_freq >= 1000:
        cpu_freq = f"{round(cpu_freq / 1000, 2)}GHz"
    else:
        cpu_freq = f"{round(cpu_freq, 2)}MHz"
    du = psutil.disk_usage(client.workdir)
    psutil.disk_io_counters()
    disk = f"{humanbytes(du.used)} / {humanbytes(du.total)} " f"({du.percent}%)"
    somsg = f"""🖥 **System Information**
    
**PlatForm :** `{splatform}`
**PlatForm - Release :** `{platform_release}`
**PlatForm - Version :** `{platform_version}`
**Architecture :** `{architecture}`
**HostName :** `{hostname}`
**IP :** `{ip_address}`
**Mac :** `{mac_address}`
**Processor :** `{processor}`
**Ram : ** `{ram}`
**CPU :** `{len(psutil.Process().cpu_affinity())}`
**CPU FREQ :** `{cpu_freq}`
**DISK :** `{disk}`
    """
    
    await message.reply(somsg)


@bot.on_message(filters.command("logs"))
async def get_bot_logs(c: Client, m: Message):
    if m.from_user.id not in AUTH_USERS:
        return
    bot_log_path = f"logs.txt"
    if os.path.exists(bot_log_path):
        try:
            pablo = await m.reply_text("please wait....")
            m_list = open(bot_log_path, "r").read()
            message_s = m_list
            key = (
                requests.post("https://nekobin.com/api/documents", json={"content": message_s})
                .json()
                .get("result")
                .get("key")
            )
            url = f"https://nekobin.com/{key}"
            raw = f"https://nekobin.com/raw/{key}"
            reply_text = f"Here is the link of your logs.\n\nNekoBin [Click Here]({url})\n\nRaw [Click Here]({raw})"
            await pablo.edit(reply_text,disable_web_page_preview=True)
            await m.reply_document(
                bot_log_path,
                quote=True,
                caption= f'📁 this is the log of your bot',
            )
        except Exception as e:
            print(f'[ERROR]: {e}')
            LOGS.error(e)
    else:
        if not os.path.exists(bot_log_path):
            await m.reply_text('❌ no logs found !')


# -----------------------------------------------------------------------------
# 8. Callback Query Handlers
# -----------------------------------------------------------------------------

@bot.on_callback_query(filters.regex("home"))
async def cb_home(client, update):
    await update.message.edit_text(
            text=START.format(update.from_user.mention),
            disable_web_page_preview=True,
            reply_markup=START_BUTTONS)

@bot.on_callback_query(filters.regex("help"))
async def cb_help(client, update):
        await update.message.edit_text(
      
            text=HELP,
            disable_web_page_preview=True,
            reply_markup=HELP_BUTTONS)


@bot.on_callback_query(filters.regex("close"))
async def cb_close(client, update):
    await update.message.delete()


@bot.on_callback_query(filters.regex(r"runtime"))
async def runtime_func_cq(_, cq):
    runtime = cq.data.split(None, 1)[1]
    await cq.answer(runtime, show_alert=True)


@bot.on_callback_query(filters.regex("Logout"))
async def cb_data_logout(client, update):
    user_id = update.from_user.id
    await update.message.edit_text(
            text='هل انت متاكد من تسجيل الخروج',
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"Yes",
                        callback_data="yes",
                    )
                ],
              
                [InlineKeyboardButton("close", callback_data="close")],
            ]
        ),)


@bot.on_callback_query(filters.regex("yes"))
async def cb_data_yes(client, update):
    user_id = update.from_user.id
    await db.set_session(user_id, "")
    await db.set_login(user_id,False)
    await update.message.edit_text(
            text='Logged Out Successfully ✅\n\nDo terminate the login session manually')


# -----------------------------------------------------------------------------
# 9. Entry Point
# -----------------------------------------------------------------------------

async def main():
    try:   
        print("يبدا البوت....")
        LOGS.info("starting bot...")

        await bot.start()
        app = web.AppRunner(await web_server())
        await app.setup()
        bind_address = "0.0.0.0"
        await web.TCPSite(app, bind_address, PORT).start()

        b = await getme()
        
        LOGS.info(f"@{b} started...")

        print(f"@{b} started...")
        
        
        await idle()
    except Exception as e:
        print(e)
        LOGS.warning(e)

async def main():
    global db
    db = Database()
    await db._initialize_files()
    await bot.start()
    print("Bot Started")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())

@bot.on_message(filters.private & filters.command("start"))
async def start(client, message):
    user = message.from_user
    await db.add_user(user.id)
    if MUST_JOIN: # Corrected indentation
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


