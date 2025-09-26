import asyncio
import logging
from telethon import TelegramClient, events, Button
from telethon.tl.types import Channel, User, UserStatusEmpty
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact
from telethon.sessions import StringSession
import sqlite3
import re
import requests
import threading
import time
from flask import Flask

# إيقاف التسجيل المفصل
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# إعدادات API
API_ID = 23656977
API_HASH = '49d3f43531a92b3f5bc403766313ca1e'
BOT_TOKEN = '8427666066:AAGmHgzfoskdMf8d7pf3Vrs7b6R1VVB_jlY'
WEBHOOK_URL = "https://trans-ygyf.onrender.com"

# تهيئة العميل
client = TelegramClient('member_transfer_bot', API_ID, API_HASH)

# قاعدة البيانات
def init_db():
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (user_id INTEGER PRIMARY KEY, source_group TEXT, target_group TEXT, 
                 delay REAL, daily_limit INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS progress
                 (user_id INTEGER, total_members INTEGER, processed INTEGER, 
                 failed INTEGER, status TEXT, paused INTEGER DEFAULT 0, current_index INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_sessions
                 (user_id INTEGER PRIMARY KEY, session_string TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transferred_members
                 (user_id INTEGER, member_id INTEGER, username TEXT, 
                  transferred INTEGER, timestamp DATETIME)''')
    conn.commit()
    conn.close()

init_db()

# دوال مساعدة للقاعدة البيانات
def get_user_settings(user_id):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM settings WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def update_user_settings(user_id, **kwargs):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    if get_user_settings(user_id):
        set_clause = ', '.join([f"{k}=?" for k in kwargs])
        values = list(kwargs.values()) + [user_id]
        c.execute(f"UPDATE settings SET {set_clause} WHERE user_id=?", values)
    else:
        columns = ['user_id'] + list(kwargs.keys())
        placeholders = ','.join(['?'] * len(columns))
        values = [user_id] + list(kwargs.values())
        c.execute(f"INSERT INTO settings ({','.join(columns)}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()

def update_progress(user_id, total_members=None, processed=None, failed=None, status=None, paused=None, current_index=None):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM progress WHERE user_id=?", (user_id,))
    if c.fetchone():
        updates = []
        values = []
        if total_members is not None:
            updates.append("total_members=?")
            values.append(total_members)
        if processed is not None:
            updates.append("processed=?")
            values.append(processed)
        if failed is not None:
            updates.append("failed=?")
            values.append(failed)
        if status is not None:
            updates.append("status=?")
            values.append(status)
        if paused is not None:
            updates.append("paused=?")
            values.append(paused)
        if current_index is not None:
            updates.append("current_index=?")
            values.append(current_index)
        values.append(user_id)
        c.execute(f"UPDATE progress SET {','.join(updates)} WHERE user_id=?", values)
    else:
        c.execute("INSERT INTO progress (user_id, total_members, processed, failed, status, paused, current_index) VALUES (?,?,?,?,?,?,?)",
                  (user_id, total_members or 0, processed or 0, failed or 0, status or 'idle', paused or 0, current_index or 0))
    conn.commit()
    conn.close()

def get_progress(user_id):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM progress WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def save_user_session(user_id, session_string):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_sessions (user_id, session_string) VALUES (?,?)",
              (user_id, session_string))
    conn.commit()
    conn.close()

def get_user_session(user_id):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("SELECT session_string FROM user_sessions WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def log_transferred_member(user_id, member_id, username, transferred):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO transferred_members (user_id, member_id, username, transferred, timestamp) VALUES (?,?,?,?,datetime('now'))",
              (user_id, member_id, username or '', transferred,))
    conn.commit()
    conn.close()

def get_transferred_members_count(user_id):
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM transferred_members WHERE user_id=? AND transferred=1", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

# دالة للحفاظ على نشاط البوت باستخدام requests
def keep_alive():
    while True:
        try:
            response = requests.get(WEBHOOK_URL, timeout=30)
            logger.info(f"Keep-alive request sent. Status: {response.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive failed: {e}")
        time.sleep(300)  # كل 5 دقائق

# بدء thread للحفاظ على النشاط
def start_keep_alive():
    keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
    keep_alive_thread.start()
    logger.info("Keep-alive thread started")

# دوال المساعدة
async def is_group_or_channel(entity):
    return isinstance(entity, Channel)

async def is_deleted_account(user):
    return isinstance(user.status, UserStatusEmpty) or getattr(user, 'deleted', False)

async def is_bot(user):
    return getattr(user, 'bot', False)

async def save_contact(user, user_client):
    try:
        # إنشاء رقم هاتف افتراضي إذا لم يكن موجوداً
        phone = getattr(user, 'phone', None)
        if not phone:
            # إنشاء رقم افتراضي بناءً على ID المستخدم
            phone = f"+999{user.id:09d}"  # رقم افتراضي باستخدام ID المستخدم
        
        # التأكد من أن الرقم يبدأ بـ +
        if not phone.startswith('+'):
            phone = '+' + phone
            
        contact = InputPhoneContact(
            client_id=user.id,
            phone=phone,
            first_name=user.first_name or f'User{user.id}',
            last_name=user.last_name or ''
        )
        result = await user_client(ImportContactsRequest([contact]))
        return True, "تم حفظ جهة الاتصال"
    except Exception as e:
        error_msg = str(e)
        if "PHONE_NUMBER_INVALID" in error_msg:
            # محاولة برقم افتراضي مختلف
            try:
                phone = f"+000{user.id:09d}"
                contact = InputPhoneContact(
                    client_id=user.id,
                    phone=phone,
                    first_name=user.first_name or f'User{user.id}',
                    last_name=user.last_name or ""
                )
                await user_client(ImportContactsRequest([contact]))
                return True, "تم حفظ جهة الاتصال برقم افتراضي"
            except Exception as e2:
                return False, f"فشل حفظ الجهة: {str(e2)}"
        return False, f"خطأ في حفظ الجهة: {error_msg}"

async def add_to_group(user_id, target_entity, user_client):
    try:
        # محاولة إضافة المستخدم إلى المجموعة
        await user_client.edit_permissions(target_entity, user_id, view_messages=True)
        return True, "تمت الإضافة بنجاح"
    except Exception as e:
        error_msg = str(e)
        if "USER_ALREADY_PARTICIPANT" in error_msg:
            return True, "العضو موجود بالفعل"
        elif "USER_PRIVACY_RESTRICTED" in error_msg:
            return False, "خصوصية المستخدم تمنع الإضافة"
        elif "CHAT_ADMIN_REQUIRED" in error_msg:
            return False, "صلاحيات مشرف غير كافية"
        elif "PEER_FLOOD" in error_msg:
            return False, "تم حظر الإضافة مؤقتاً بسبب التكرار"
        elif "USER_NOT_MUTUAL_CONTACT" in error_msg:
            return False, "يجب أن يكون المستخدم في جهات الاتصال أولاً"
        else:
            return False, f"خطأ في الإضافة: {error_msg}"

async def is_user_in_group(user_id, target_entity, user_client):
    try:
        participant = await user_client.get_permissions(target_entity, user_id)
        return True
    except Exception:
        return False

async def get_actual_members_count(target_entity, user_client):
    try:
        count = 0
        async for member in user_client.iter_participants(target_entity, aggressive=False):
            if isinstance(member, User) and not await is_deleted_account(member) and not await is_bot(member):
                count += 1
        return count
    except Exception as e:
        logger.error(f"Error counting members: {e}")
        return 0

# قاموس لتخزين حالات المستخدمين
user_states = {}
# قاموس لتخزين حالة الإيقاف
pause_states = {}

# معالجة الأحداث
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    # مسح أي حالة سابقة
    if user_id in user_states:
        del user_states[user_id]
        
    buttons = [
        [Button.inline("🚀 بدء العملية", b"start_process")],
        [Button.inline("⚙️ الإعدادات", b"settings_main")]
    ]
    await event.reply(
        "**مرحباً بك في بوت نقل الأعضاء**\n\n"
        "• استخدم زر 'بدء العملية' لبدء نقل الأعضاء\n"
        "• زر 'الإعدادات' لضبط إعدادات البوت",
        buttons=buttons
    )

@client.on(events.CallbackQuery(pattern=b'start_process'))
async def start_process_handler(event):
    user_id = event.sender_id
    settings = get_user_settings(user_id)
    
    if not settings or not settings[1] or not settings[2]:
        await event.edit("⚠️ يرجى تعيين المجموعة المصدر والهدف أولاً من خلال قائمة 'الإعدادات'")
        return
    
    user_session = get_user_session(user_id)
    if not user_session:
        await event.edit("⚠️ يرجى تسجيل الدخول إلى حسابك أولاً من خلال قائمة 'الإعدادات'")
        return
    
    # التحقق إذا كانت هناك عملية متوقفة
    progress = get_progress(user_id)
    if progress and progress[5] == 1:  # إذا كانت العملية متوقفة
        buttons = [
            [Button.inline("🔄 استئناف العملية", b"resume_process")],
            [Button.inline("🆕 بدء عملية جديدة", b"new_process")],
            [Button.inline("❌ إلغاء", b"settings_main")]
        ]
        await event.edit("⚠️ هناك عملية متوقفة. هل تريد استئنافها أم بدء عملية جديدة؟", buttons=buttons)
        return
    
    await event.edit("🔄 جاري بدء عملية نقل الأعضاء...")
    await transfer_members_individual(user_id, event)

@client.on(events.CallbackQuery(pattern=b'resume_process'))
async def resume_process_handler(event):
    user_id = event.sender_id
    await event.edit("🔄 جاري استئناف العملية من حيث توقفت...")
    await transfer_members_individual(user_id, event, resume=True)

@client.on(events.CallbackQuery(pattern=b'new_process'))
async def new_process_handler(event):
    user_id = event.sender_id
    # إعادة تعيين التقدم
    update_progress(user_id, total_members=0, processed=0, failed=0, status='جاري النقل', paused=0, current_index=0)
    await event.edit("🔄 جاري بدء عملية نقل جديدة...")
    await transfer_members_individual(user_id, event)

@client.on(events.CallbackQuery(pattern=b'pause_process'))
async def pause_process_handler(event):
    user_id = event.sender_id
    # وضع علامة إيقاف
    if user_id in pause_states:
        pause_states[user_id] = True
    update_progress(user_id, paused=1)
    await event.edit("⏸ تم إيقاف العملية. يمكنك استئنافها لاحقاً من قائمة الإعدادات.", buttons=[[Button.inline("🔙 رجوع", b"settings_main")]])

@client.on(events.CallbackQuery(pattern=b'settings_main'))
async def settings_main_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    login_status = "✅ مسجل الدخول" if user_session else "❌ غير مسجل"
    
    settings = get_user_settings(user_id)
    current_delay = settings[3] if settings else 86.0
    current_limit = settings[4] if settings else 1000
    
    progress = get_progress(user_id)
    pause_button = []
    if progress and progress[4] == 'جاري النقل':  # إذا كانت العملية قيد التشغيل
        pause_button = [Button.inline("⏸ إيقاف مؤقت", b"pause_process")]
    
    buttons = [
        [Button.inline("🔐 إعدادات الحساب", b"account_settings")],
        [Button.inline("📋 إعدادات المجموعات", b"group_settings")],
        [Button.inline("⏱ إعدادات التوقيت", b"timing_settings")],
        [Button.inline("📊 حالة التقدم", b"progress_status")],
        [Button.inline("🔍 تحقق من الأعضاء", b"check_members")],
        pause_button,
        [Button.inline("🔄 إعادة تعيين", b"reset_settings")],
        [Button.inline("🔙 رجوع", b"back_main")]
    ]
    
    # إزالة الأزرار الفارغة
    buttons = [btn for btn in buttons if btn]
    
    status_text = f"""
**⚙️ الإعدادات الرئيسية**

• حالة التسجيل: {login_status}
• الفاصل الزمني: {current_delay} ثانية
• الحد اليومي: {current_limit} عضو
    """
    
    await event.edit(status_text, buttons=buttons)

@client.on(events.CallbackQuery(pattern=b'account_settings'))
async def account_settings_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    login_status = "✅ مسجل الدخول" if user_session else "❌ غير مسجل"
    
    buttons = [
        [Button.inline("🔐 تسجيل الدخول", b"user_login")],
        [Button.inline(f"حالة التسجيل: {login_status}", b"login_status")],
        [Button.inline("🔙 رجوع للإعدادات", b"settings_main")]
    ]
    
    await event.edit("**🔐 إعدادات الحساب**", buttons=buttons)

@client.on(events.CallbackQuery(pattern=b'group_settings'))
async def group_settings_handler(event):
    user_id = event.sender_id
    settings = get_user_settings(user_id)
    source_group = settings[1] if settings else "غير معين"
    target_group = settings[2] if settings else "غير معين"
    
    buttons = [
        [Button.inline("📥 تعيين المصدر", b"set_source")],
        [Button.inline("📤 تعيين الهدف", b"set_target")],
        [Button.inline("🔙 رجوع للإعدادات", b"settings_main")]
    ]
    
    status_text = f"""
**📋 إعدادات المجموعات**

• المجموعة المصدر: {source_group}
• المجموعة الهدف: {target_group}
    """
    
    await event.edit(status_text, buttons=buttons)

@client.on(events.CallbackQuery(pattern=b'timing_settings'))
async def timing_settings_handler(event):
    user_id = event.sender_id
    settings = get_user_settings(user_id)
    current_delay = settings[3] if settings else 86.0
    current_limit = settings[4] if settings else 1000
    
    buttons = [
        [Button.inline("⏱ تعديل الفاصل الزمني", b"set_delay")],
        [Button.inline("📊 تعديل الحد اليومي", b"set_limit")],
        [Button.inline("🔙 رجوع للإعدادات", b"settings_main")]
    ]
    
    help_text = f"""
**⏱ إعدادات التوقيت**

• الفاصل الزمني الحالي: {current_delay} ثانية
• الحد اليومي الحالي: {current_limit} عضو

• الفاصل الزمني: الوقت بين كل عملية إضافة
• الحد اليومي: أقصى عدد يمكن إضافته خلال 24 ساعة
• الفاصل الافتراضي 86 ثانية يسمح بإضافة 1000 عضو خلال 24 ساعة
    """
    
    await event.edit(help_text, buttons=buttons)

@client.on(events.CallbackQuery(pattern=b'set_delay'))
async def set_delay_handler(event):
    user_id = event.sender_id
    user_states[user_id] = {'step': 'awaiting_delay'}
    await event.edit("⏱ **تعديل الفاصل الزمني**\n\nأدخل الفاصل الزمني بين كل عملية إضافة (بالثواني):\n\nمثال: 86 (لإضافة 1000 عضو في 24 ساعة)")

@client.on(events.CallbackQuery(pattern=b'set_limit'))
async def set_limit_handler(event):
    user_id = event.sender_id
    user_states[user_id] = {'step': 'awaiting_limit'}
    await event.edit("📊 **تعديل الحد اليومي**\n\nأدخل الحد الأقصى لعدد الأعضاء الذي يمكن إضافته خلال 24 ساعة:\n\nمثال: 1000 (الحد الأقصى الآمن)")

@client.on(events.NewMessage)
async def handle_all_messages(event):
    user_id = event.sender_id
    message_text = event.text.strip()
    
    # معالجة إدخال الإعدادات
    if user_id in user_states:
        state = user_states[user_id]
        
        if state.get('step') == 'awaiting_delay':
            try:
                delay = float(message_text)
                if delay < 5:
                    await event.reply("❌ الفاصل الزمني يجب أن يكون 5 ثواني على الأقل")
                    return
                update_user_settings(user_id, delay=delay)
                await event.reply(f"✅ تم تعيين الفاصل الزمني إلى {delay} ثانية")
            except ValueError:
                await event.reply("❌ يرجى إدخال رقم صحيح أو عشري صحيح")
            del user_states[user_id]
            return
            
        elif state.get('step') == 'awaiting_limit':
            try:
                limit = int(message_text)
                if limit < 1:
                    await event.reply("❌ الحد اليومي يجب أن يكون 1 على الأقل")
                    return
                if limit > 2000:
                    await event.reply("⚠️ الحد الأعلى الموصى به هو 2000 عضو")
                update_user_settings(user_id, daily_limit=limit)
                await event.reply(f"✅ تم تعيين الحد اليومي إلى {limit} عضو")
            except ValueError:
                await event.reply("❌ يرجى إدخال رقم صحيح")
            del user_states[user_id]
            return
    
    # معالجة تسجيل الدخول
    if user_id in user_states and user_states[user_id].get('step') == 'awaiting_phone':
        # تنظيف رقم الهاتف
        phone = re.sub(r'[^\d+]', '', message_text)
        if not phone.startswith('+'):
            phone = '+' + phone
        
        if len(phone) < 10:
            await event.reply("❌ رقم الهاتف غير صحيح. يرجى إدخال رقم هاتف صحيح مع رمز الدولة:")
            return
        
        try:
            user_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await user_client.connect()
            
            # إرسال رمز التحقق
            sent_code = await user_client.send_code_request(phone)
            user_states[user_id] = {
                'step': 'awaiting_code',
                'phone': phone,
                'client': user_client,
                'phone_code_hash': sent_code.phone_code_hash
            }
            
            await event.reply("✅ **تم إرسال رمز التحقق**\n\nأرسل رمز التحقق المكون من 5 أرقام الذي استلمته:")
            
        except Exception as e:
            await event.reply(f"❌ **خطأ في إرسال الرمز**: {str(e)}\n\nيرجى التحقق من رقم الهاتف والمحاولة مرة أخرى:")
            if 'client' in locals():
                await user_client.disconnect()
    
    elif user_id in user_states and user_states[user_id].get('step') == 'awaiting_code':
        # تنظيف رمز التحقق
        code = re.sub(r'[^\d]', '', message_text)
        
        if len(code) != 5:
            await event.reply("❌ رمز التحقق يجب أن يكون 5 أرقام. يرجى إعادة الإدخال:")
            return
        
        try:
            user_client = user_states[user_id]['client']
            phone = user_states[user_id]['phone']
            phone_code_hash = user_states[user_id]['phone_code_hash']
            
            # تسجيل الدخول بالرمز
            await user_client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            
            # حفظ الجلسة
            session_string = user_client.session.save()
            save_user_session(user_id, session_string)
            
            await event.reply("✅ **تم تسجيل الدخول بنجاح!**\n\nيمكنك الآن استخدام البوت لنقل الأعضاء.")
            
            # تنظيف الحالة
            del user_states[user_id]
            await user_client.disconnect()
            
        except Exception as e:
            error_msg = str(e)
            if "code" in error_msg and "invalid" in error_msg:
                await event.reply("❌ **رمز التحقق غير صحيح**\n\nيرجى إعادة إدخال الرمز الصحيح:")
            else:
                await event.reply(f"❌ **خطأ في تسجيل الدخول**: {error_msg}\n\nيرجى المحاولة مرة أخرى من البداية باستخدام /start")
                del user_states[user_id]
    
    # معالجة إدخال المجموعات
    elif user_id in user_states and user_states[user_id].get('step') in ['awaiting_source', 'awaiting_target']:
        try:
            user_session_str = get_user_session(user_id)
            user_client = TelegramClient(StringSession(user_session_str), API_ID, API_HASH)
            await user_client.connect()
            
            entity = await user_client.get_entity(message_text)
            
            if await is_group_or_channel(entity):
                if user_states[user_id]['step'] == 'awaiting_source':
                    # للمصدر: لا نحتاج إلى التحقق من الصلاحيات
                    update_user_settings(user_id, source_group=message_text)
                    await event.reply(f"✅ تم تعيين المصدر: {entity.title}\n\nيمكنك الآن البدء في عملية النقل.")
                else:
                    # للهدف: نحتاج إلى التحقق من صلاحيات المشرف
                    try:
                        me = await user_client.get_me()
                        participant = await user_client.get_permissions(entity, me)
                        if participant.is_admin:
                            update_user_settings(user_id, target_group=message_text)
                            await event.reply(f"✅ تم تعيين الهدف: {entity.title}")
                        else:
                            await event.reply("❌ يجب أن تكون مشرفاً في المجموعة الهدف لتتمكن من إضافة الأعضاء")
                    except Exception as e:
                        await event.reply("❌ لا يمكن الوصول إلى المجموعة أو لا تملك الصلاحيات الكافية للإضافة")
            else:
                await event.reply("❌ الرجاء إدخال مجموعة أو قناة صحيحة")
                
            await user_client.disconnect()
            
        except Exception as e:
            await event.reply(f"❌ خطأ في التعرف على المجموعة/القناة: يرجى التأكد من المعرف والمحاولة مرة أخرى")
        
        # تنظيف الحالة
        del user_states[user_id]

@client.on(events.CallbackQuery(pattern=b'user_login'))
async def user_login_handler(event):
    user_id = event.sender_id
    user_states[user_id] = {'step': 'awaiting_phone'}
    await event.edit("🔐 **تسجيل الدخول إلى حسابك**\n\nأرسل رقم هاتفك مع رمز الدولة (مثال: +967733091200):")

@client.on(events.CallbackQuery(pattern=b'login_status'))
async def login_status_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    
    if user_session:
        status_text = "✅ **حسابك مسجل بنجاح**\n\nيمكنك الآن استخدام ميزات نقل الأعضاء."
    else:
        status_text = "❌ **لم تقم بتسجيل الدخول بعد**\n\nيرجى استخدام زر 'تسجيل الدخول' لإضافة حسابك."
    
    await event.edit(status_text, buttons=[[Button.inline("🔙 رجوع", b"account_settings")]])

@client.on(events.CallbackQuery(pattern=b'set_source'))
async def set_source_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    if not user_session:
        await event.edit("⚠️ يرجى تسجيل الدخول أولاً لتتمكن من تعيين المجموعات")
        return
        
    user_states[user_id] = {'step': 'awaiting_source'}
    await event.edit("📥 **تعيين المجموعة المصدر**\n\nأرسل معرف المجموعة/القناة المصدر:\n\n❗ **ملاحظة:** لا تحتاج إلى أن تكون مشرفاً في المصدر")

@client.on(events.CallbackQuery(pattern=b'set_target'))
async def set_target_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    if not user_session:
        await event.edit("⚠️ يرجى تسجيل الدخول أولاً لتتمكن من تعيين المجموعات")
        return
        
    user_states[user_id] = {'step': 'awaiting_target'}
    await event.edit("📤 **تعيين المجموعة الهدف**\n\nأرسل معرف المجموعة/القناة الهدف:\n\n❗ **ملاحظة:** يجب أن تكون مشرفاً في الهدف")

@client.on(events.CallbackQuery(pattern=b'check_members'))
async def check_members_handler(event):
    user_id = event.sender_id
    settings = get_user_settings(user_id)
    
    if not settings or not settings[2]:
        await event.edit("⚠️ يرجى تعيين المجموعة الهدف أولاً")
        return
    
    user_session = get_user_session(user_id)
    if not user_session:
        await event.edit("⚠️ يرجى تسجيل الدخول أولاً")
        return
    
    await event.edit("🔍 جاري التحقق من عدد الأعضاء الفعلي في الهدف...")
    
    try:
        user_session_str = get_user_session(user_id)
        user_client = TelegramClient(StringSession(user_session_str), API_ID, API_HASH)
        await user_client.connect()
        
        target_entity = await user_client.get_entity(settings[2])
        actual_count = await get_actual_members_count(target_entity, user_client)
        transferred_count = get_transferred_members_count(user_id)
        
        await event.edit(f"""
📊 **التحقق من الأعضاء:**

• الأعضاء المنقولين المسجلين: {transferred_count}
• الأعضاء الفعليين في الهدف: {actual_count}
• الفرق: {actual_count - transferred_count}

🔍 **تحليل الفرق:**
- إذا كان الفرق موجباً: يوجد أعضاء إضافيين في المجموعة
- إذا كان الفرق سالباً: بعض الأعضاء لم يتم إضافتهم فعلياً
- إذا كان الفرق صفراً: كل شيء يعمل بشكل صحيح
        """)
        
        await user_client.disconnect()
    except Exception as e:
        await event.edit(f"❌ خطأ في التحقق: {str(e)}")

@client.on(events.CallbackQuery(pattern=b'progress_status'))
async def progress_status_handler(event):
    user_id = event.sender_id
    progress = get_progress(user_id)
    transferred_count = get_transferred_members_count(user_id)
    
    if progress:
        status_text = f"""
**📊 حالة التقدم:**

• العدد الكلي: {progress[1]}
• المعالجون: {progress[2]}
• الفاشلون: {progress[3]}
• المسجلين في DB: {transferred_count}
• الحالة: {progress[4]}
• الإيقاف: {'⏸ متوقف' if progress[5] else '▶️ يعمل'}
        """
        buttons = [
            [Button.inline("🔄 استئناف", b"resume_process")] if progress[5] else [Button.inline("⏸ إيقاف", b"pause_process")],
            [Button.inline("🔙 رجوع", b"settings_main")]
        ]
    else:
        status_text = "❌ لا توجد عملية نشطة"
        buttons = [[Button.inline("🔙 رجوع", b"settings_main")]]
    
    await event.edit(status_text, buttons=buttons)

@client.on(events.CallbackQuery(pattern=b'reset_settings'))
async def reset_settings_handler(event):
    user_id = event.sender_id
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM progress WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM transferred_members WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    await event.edit("✅ تم إعادة تعيين جميع الإعدادات والسجلات", buttons=[[Button.inline("🔙 رجوع", b"settings_main")]])

@client.on(events.CallbackQuery(pattern=b'back_main'))
async def back_main_handler(event):
    user_id = event.sender_id
    # مسح أي حالة سابقة
    if user_id in user_states:
        del user_states[user_id]
        
    buttons = [
        [Button.inline("🚀 بدء العملية", b"start_process")],
        [Button.inline("⚙️ الإعدادات", b"settings_main")]
    ]
    await event.edit("**مرحباً بك في بوت نقل الأعضاء**", buttons=buttons)

@client.on(events.CallbackQuery(pattern=b'no_action'))
async def no_action_handler(event):
    await event.answer("لا يوجد إجراء لهذا الزر", alert=False)

# الدالة الرئيسية لنقل الأعضاء بشكل فردي
async def transfer_members_individual(user_id, event, resume=False):
    try:
        settings = get_user_settings(user_id)
        if not settings:
            await event.edit("❌ لم يتم تعيين الإعدادات")
            return
        
        user_session_str = get_user_session(user_id)
        if not user_session_str:
            await event.edit("❌ لم يتم تسجيل الدخول")
            return
        
        # استخدام حساب المستخدم للعمليات
        user_client = TelegramClient(StringSession(user_session_str), API_ID, API_HASH)
        await user_client.connect()
        
        try:
            source_entity = await user_client.get_entity(settings[1])
            target_entity = await user_client.get_entity(settings[2])
            delay = settings[3] or 86.0
            daily_limit = settings[4] or 1000
            
            # الحصول على قائمة الأعضاء
            await event.edit("🔍 جاري جلب الأعضاء من المصدر...")
            
            all_members = []
            try:
                async for member in user_client.iter_participants(source_entity, aggressive=True):
                    all_members.append(member)
                    if len(all_members) % 50 == 0:
                        await event.edit(f"🔍 تم جلب {len(all_members)} عضو حتى الآن...")
            except Exception as e:
                await event.edit(f"⚠️ توقف الجلب عند {len(all_members)} عضو: {str(e)}")
            
            if not all_members:
                await event.edit("❌ لم يتم العثور على أي أعضاء في المجموعة المصدر")
                return
            
            # تصفية الأعضاء
            valid_members = []
            for member in all_members:
                if isinstance(member, User) and not await is_deleted_account(member) and not await is_bot(member):
                    valid_members.append(member)
            
            total_members = len(valid_members)
            if total_members == 0:
                await event.edit("❌ لم يتم العثور على أعضاء صالحين للنقل")
                return
            
            # تحديد نقطة البداية إذا كانت استئناف
            start_index = 0
            if resume:
                progress = get_progress(user_id)
                if progress and progress[6] > 0:  # current_index
                    start_index = progress[6]
                    await event.edit(f"🔄 استئناف العملية من العضو {start_index + 1} من أصل {total_members}")
                else:
                    await event.edit("❌ لا توجد عملية متوقفة للاستئناف")
                    return
            
            update_progress(user_id, total_members=total_members, processed=start_index, failed=0, status='جاري النقل', paused=0, current_index=start_index)
            
            # عملية النقل الفردي
            added_count = 0
            failed_count = 0
            saved_contacts = 0
            
            # تهيئة حالة الإيقاف
            if user_id not in pause_states:
                pause_states[user_id] = False
            
            for i in range(start_index, len(valid_members)):
                # التحقق من طلب الإيقاف
                if pause_states.get(user_id, False):
                    update_progress(user_id, paused=1, current_index=i)
                    await event.edit("⏸ تم إيقاف العملية. يمكنك استئنافها لاحقاً من قائمة الإعدادات.")
                    pause_states[user_id] = False
                    return
                
                if added_count >= daily_limit:
                    await event.edit(f"⏸ تم الوصول إلى الحد اليومي ({daily_limit})")
                    break
                
                member = valid_members[i]
                
                try:
                    username = f"@{member.username}" if member.username else member.first_name or f"user_{member.id}"
                    
                    # التحقق إذا كان العضو موجوداً بالفعل في الهدف
                    if await is_user_in_group(member.id, target_entity, user_client):
                        status_msg = f"⏩ العضو {i+1}/{total_members} ({username}) موجود بالفعل في الهدف، تخطي..."
                        await event.edit(status_msg)
                        log_transferred_member(user_id, member.id, username, 1)
                        added_count += 1
                        update_progress(user_id, processed=i+1, current_index=i+1)
                        continue
                    
                    # حفظ العضو كجهة اتصال (سواء كان لديه رقم هاتف أو لا)
                    contact_saved, contact_reason = await save_contact(member, user_client)
                    if contact_saved:
                        saved_contacts += 1
                        contact_msg = "✅ " + contact_reason
                    else:
                        contact_msg = "❌ " + contact_reason
                    
                    await asyncio.sleep(1)  # تأخير بسيط بعد الحفظ
                    
                    # إضافة العضو إلى الهدف
                    add_success, add_reason = await add_to_group(member.id, target_entity, user_client)
                    
                    if add_success:
                        added_count += 1
                        log_transferred_member(user_id, member.id, username, 1)
                        status_msg = f"✅ تمت إضافة العضو {i+1}/{total_members} ({username})"
                    else:
                        failed_count += 1
                        log_transferred_member(user_id, member.id, username, 0)
                        status_msg = f"❌ فشل إضافة العضو {i+1}/{total_members} ({username})"
                    
                    # تحديث التقدم
                    update_progress(user_id, processed=i+1, failed=failed_count, current_index=i+1)
                    
                    # عرض نتيجة كل عملية بشكل فردي
                    progress_msg = f"""
📊 **تقدم النقل الفردي**

• العضو: {i+1}/{total_members}
• المضافة: {added_count}
• الفاشلة: {failed_count}
• المحفوظة: {saved_contacts}

{status_msg}
💾 {contact_msg}
🎯 {add_reason}
                    """
                    await event.edit(progress_msg)
                    
                    # تأخير بين العمليات
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    failed_count += 1
                    username = f"@{member.username}" if member.username else member.first_name or f"user_{member.id}"
                    log_transferred_member(user_id, member.id, username, 0)
                    error_msg = f"❌ خطأ غير متوقع في العضو {i+1}/{total_members} ({username}): {str(e)}"
                    await event.edit(error_msg)
                    logger.error(f"Error processing member {i+1}: {e}")
                    update_progress(user_id, processed=i+1, failed=failed_count, current_index=i+1)
                    continue
            
            # النتيجة النهائية
            update_progress(user_id, status='مكتمل', paused=0)
            result_msg = f"""
✅ **تم الانتهاء من عملية النقل الفردي**

• العدد الإجمالي في المصدر: {len(all_members)}
• الأعضاء الصالحين: {total_members}
• المضافة بنجاح: {added_count}
• الفاشلة: {failed_count}
• المحفوظة: {saved_contacts}
• النجاح: {(added_count/total_members*100) if total_members > 0 else 0:.1f}%

🎯 **ميزات النظام:**
- حفظ جهات الاتصال برقم هاتف أو بدون
- عرض نتيجة كل عملية فوراً
- إيقاف واستئناف العملية
- التعامل مع جميع أنواع الأخطاء
            """
            await event.edit(result_msg)
            
        except Exception as e:
            await event.edit(f"❌ خطأ أثناء عملية النقل: {str(e)}")
        finally:
            await user_client.disconnect()
            
    except Exception as e:
        await event.edit(f"❌ خطأ عام: {str(e)}")

# تشغيل البوت مع Keep-alive
async def main():
    # بدء مهمة keep-alive في thread منفصل
    start_keep_alive()
    
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot is running successfully...")
    print("✅ API_ID:", API_ID)
    print("✅ API_HASH:", API_HASH)
    print("✅ WEBHOOK_URL:", WEBHOOK_URL)
    print("✅ Keep-alive activated (every 5 minutes)")
    
    # بدء خادم ويب على البورت 10000
    def run_web_server():
        app = Flask(__name__)
        
        @app.route('/')
        def home():
            return "Bot is running on port 10000"
        
        @app.route('/health')
        def health():
            return "OK"
        
        # تشغيل على البورت 10000
        app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)
    
    # تشغيل خادم الويب في thread منفصل
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    print("✅ Web server started on port 10000")
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
