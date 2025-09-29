import os
import json
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from pyrogram import Client, filters, types
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# بيانات البوت
BOT_TOKEN = "8324471840:AAGIH09h4ZSWbJYzT4zBFQJm9MsPjcEhXvE"
API_ID = 23656977
API_HASH = "49d3f43531a92b3f5bc403766313ca1e"
ADMIN_ID = 6689435577
CHANNEL_USERNAME = "@iIl337"
WEBHOOK_URL = "https://trans-1-1pbd.onrender.com"
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

# ملفات البيانات
USERS_FILE = "users.json"
PROCESSES_FILE = "processes.json"

# حالة المستخدمين
user_states = {}
active_sessions = {}

# إنشاء تطبيق Flask
app = Flask(__name__)

# تهيئة Pyrogram Bot
bot = Client(
    "auto_poster_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

class DataManager:
    @staticmethod
    def load_data(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
            return {}

    @staticmethod
    def save_data(filename, data):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")
            return False

class BotManager:
    def __init__(self):
        self.data_manager = DataManager()
        self.scheduler = BackgroundScheduler()
        self.setup_scheduler()
    
    def setup_scheduler(self):
        """إعداد الجدولة للمهام الدورية"""
        # مهمة الحفاظ على النشاط
        self.scheduler.add_job(
            self.keep_alive,
            'interval',
            minutes=5,
            id='keep_alive'
        )
        
        # مهمة النشر التلقائي
        self.scheduler.add_job(
            self.process_publishing,
            'interval',
            minutes=1,
            id='auto_publish'
        )
        
        self.scheduler.start()
        logger.info("Scheduler started")
    
    def keep_alive(self):
        """إرسال طلبات دورية للحفاظ على نشاط البوت"""
        try:
            # طلب إلى الرابط الأساسي
            response = requests.get(WEBHOOK_URL, timeout=10)
            logger.info(f"Keep-alive request sent. Status: {response.status_code}")
            
            # تحديث إحصائيات النظام
            processes = self.data_manager.load_data(PROCESSES_FILE)
            active_count = sum(1 for p in processes.values() if p.get('is_active', False))
            logger.info(f"System status: {active_count} active processes")
            
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")
    
    def process_publishing(self):
        """معالجة النشر التلقائي"""
        try:
            processes = self.data_manager.load_data(PROCESSES_FILE)
            users = self.data_manager.load_data(USERS_FILE)
            
            for user_id_str, process in processes.items():
                if not process.get('is_active', False) or process.get('is_paused', False):
                    continue
                
                user_data = users.get(user_id_str, {})
                if not user_data.get('session_string'):
                    continue
                
                # التحقق من الوقت المناسب للنشر
                last_post = process.get('last_post_time')
                interval = process.get('interval_minutes', 60)
                
                if last_post:
                    last_time = datetime.fromisoformat(last_post)
                    next_time = last_time + timedelta(minutes=interval)
                    if datetime.now() < next_time:
                        continue
                
                # تنفيذ النشر
                asyncio.run(self.execute_publishing(user_id_str, process, user_data))
                
        except Exception as e:
            logger.error(f"Publishing process error: {e}")
    
    async def execute_publishing(self, user_id_str: str, process: dict, user_data: dict):
        """تنفيذ عملية النشر"""
        try:
            client = Client(
                f"user_{user_id_str}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=user_data['session_string'],
                in_memory=True
            )
            
            await client.start()
            
            message = process.get('message', '')
            target_groups = process.get('target_groups', [])
            
            success_count = 0
            for group_id in target_groups:
                try:
                    await client.send_message(int(group_id), message)
                    success_count += 1
                    logger.info(f"Message sent to {group_id} for user {user_id_str}")
                    await asyncio.sleep(2)  # فاصل بين الرسائل
                except Exception as e:
                    logger.error(f"Error sending to {group_id}: {e}")
            
            await client.stop()
            
            # تحديث وقت آخر نشر
            process['last_post_time'] = datetime.now().isoformat()
            process['success_count'] = process.get('success_count', 0) + success_count
            processes = self.data_manager.load_data(PROCESSES_FILE)
            processes[user_id_str] = process
            self.data_manager.save_data(PROCESSES_FILE, processes)
            
            logger.info(f"Publishing completed for user {user_id_str}: {success_count}/{len(target_groups)} successful")
            
        except Exception as e:
            logger.error(f"Error in publishing for user {user_id_str}: {e}")

# إنشاء مدير البوت
bot_manager = BotManager()

# === Bot Handlers ===
@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    
    keyboard = [
        [types.InlineKeyboardButton("بدء عملية النشر", callback_data="main_start_publish")],
        [types.InlineKeyboardButton("العمليات النشطة", callback_data="main_active_processes")],
        [types.InlineKeyboardButton("التحديثات", callback_data="main_updates")],
        [types.InlineKeyboardButton("تهيئة عملية النشر", callback_data="main_setup")]
    ]
    reply_markup = types.InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        "مرحباً! أنا بوت النشر التلقائي. اختر أحد الخيارات:",
        reply_markup=reply_markup
    )

@bot.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    try:
        if data == "main_start_publish":
            await start_publishing(client, callback_query)
        elif data == "main_active_processes":
            await show_active_processes(client, callback_query)
        elif data == "main_updates":
            await show_updates(client, callback_query)
        elif data == "main_setup":
            await show_setup_menu(client, callback_query)
        elif data == "main_menu":
            await show_main_menu(client, callback_query)
        elif data.startswith("setup_"):
            await setup_handler(client, callback_query)
        elif data.startswith("process_"):
            await process_handler(client, callback_query)
        elif data.startswith("control_"):
            await control_handler(client, callback_query)
        elif data.startswith("group_"):
            await groups_handler(client, callback_query)
        elif data.startswith("interval_"):
            await interval_handler(client, callback_query)
        elif data.startswith("register_"):
            await register_handler(client, callback_query)
        elif data.startswith("admin_"):
            await admin_handler(client, callback_query)
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى")

async def show_main_menu(client, callback_query):
    keyboard = [
        [types.InlineKeyboardButton("بدء عملية النشر", callback_data="main_start_publish")],
        [types.InlineKeyboardButton("العمليات النشطة", callback_data="main_active_processes")],
        [types.InlineKeyboardButton("التحديثات", callback_data="main_updates")],
        [types.InlineKeyboardButton("تهيئة عملية النشر", callback_data="main_setup")]
    ]
    reply_markup = types.InlineKeyboardMarkup(keyboard)
    
    await callback_query.edit_message_text(
        "القائمة الرئيسية - اختر أحد الخيارات:",
        reply_markup=reply_markup
    )

async def start_publishing(client, callback_query):
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    processes = data_manager.load_data(PROCESSES_FILE)
    user_process = processes.get(str(user_id))
    
    if not user_process or not user_process.get('target_groups') or not user_process.get('message'):
        keyboard = [[types.InlineKeyboardButton("تهيئة عملية النشر", callback_data="main_setup")]]
        reply_markup = types.InlineKeyboardMarkup(keyboard)
        
        await callback_query.edit_message_text(
            "⚠️ يرجى تهيئة عملية النشر أولاً (تسجيل حساب، تحديد المجموعات، ورسالة النشر)",
            reply_markup=reply_markup
        )
        return
    
    user_process['is_active'] = True
    user_process['is_paused'] = False
    processes[str(user_id)] = user_process
    data_manager.save_data(PROCESSES_FILE, processes)
    
    await callback_query.edit_message_text(
        "✅ تم بدء عملية النشر بنجاح!",
        reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
    )

async def show_active_processes(client, callback_query):
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    processes = data_manager.load_data(PROCESSES_FILE)
    user_process = processes.get(str(user_id), {})
    
    if not user_process or not user_process.get('is_active'):
        await callback_query.edit_message_text(
            "لا توجد عمليات نشطة حالياً.",
            reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
        )
        return
    
    keyboard = []
    groups_count = len(user_process.get('target_groups', []))
    interval = user_process.get('interval_minutes', 0)
    status = "نشطة" if not user_process.get('is_paused', False) else "متوقفة مؤقتاً"
    
    keyboard.append([types.InlineKeyboardButton(
        f"{groups_count} مجموعة - كل {interval} دقيقة - {status}", 
        callback_data=f"process_{user_id}"
    )])
    
    keyboard.append([types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")])
    
    await callback_query.edit_message_text(
        "العمليات النشطة:",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def show_updates(client, callback_query):
    keyboard = [
        [types.InlineKeyboardButton("قناة التحديثات", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
        [types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
    ]
    
    await callback_query.edit_message_text(
        "تابع آخر التحديثات على قناتنا:",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def show_setup_menu(client, callback_query):
    keyboard = [
        [types.InlineKeyboardButton("تسجيل حساب", callback_data="setup_register")],
        [types.InlineKeyboardButton("المجموعة الهدف", callback_data="setup_groups")],
        [types.InlineKeyboardButton("الفاصل الزمني", callback_data="setup_interval")],
        [types.InlineKeyboardButton("رسالة النشر", callback_data="setup_message")],
        [types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
    ]
    
    await callback_query.edit_message_text(
        "تهيئة عملية النشر - اختر الخيار المطلوب:",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def setup_handler(client, callback_query):
    data = callback_query.data
    
    if data == "setup_register":
        await register_account(client, callback_query)
    elif data == "setup_groups":
        await select_groups(client, callback_query)
    elif data == "setup_interval":
        await select_interval_menu(client, callback_query)
    elif data == "setup_message":
        await set_message(client, callback_query)

async def register_account(client, callback_query):
    user_id = callback_query.from_user.id
    
    keyboard = [
        [types.InlineKeyboardButton("تسجيل بـ Pyrogram", callback_data="register_pyrogram")],
        [types.InlineKeyboardButton("العودة", callback_data="main_setup")]
    ]
    
    user_states[user_id] = "waiting_phone"
    
    await callback_query.edit_message_text(
        "للتسجيل، سنحتاج إلى:\n"
        "1. رقم هاتفك مع رمز الدولة\n"
        "2. كود التحقق\n\n"
        "سيتم حفظ بيانات الجلسة بشكل آمن.",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def register_handler(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "register_pyrogram":
        user_states[user_id] = "waiting_phone"
        await callback_query.edit_message_text(
            "أرسل رقم هاتفك مع رمز الدولة (مثال: +20123456789):",
            reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("إلغاء", callback_data="main_setup")]])
        )

@bot.on_message(filters.private & filters.text)
async def message_handler(client, message):
    user_id = message.from_user.id
    message_text = message.text
    data_manager = DataManager()
    
    if user_id in user_states:
        state = user_states[user_id]
        
        if state == "waiting_phone":
            await handle_phone_input(client, message, message_text, data_manager)
        
        elif state == "waiting_code":
            await handle_code_input(client, message, message_text, data_manager)
        
        elif state == "waiting_password":
            await handle_password_input(client, message, message_text, data_manager)
        
        elif state == "waiting_message":
            await handle_message_input(client, message, message_text, data_manager)

async def handle_phone_input(client, message, phone_number, data_manager):
    user_id = message.from_user.id
    
    try:
        # إنشاء عميل جديد
        user_client = Client(
            f"user_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True
        )
        
        await user_client.connect()
        
        # طلب كود التحقق
        sent_code = await user_client.send_code(phone_number)
        active_sessions[user_id] = {
            'phone_number': phone_number,
            'phone_code_hash': sent_code.phone_code_hash,
            'client': user_client
        }
        
        await message.reply_text("تم إرسال كود التحقق إلى هاتفك. أرسل الكود الآن:")
        
    except Exception as e:
        await message.reply_text(f"خطأ في تسجيل الحساب: {str(e)}")
        if user_id in user_states:
            del user_states[user_id]

async def handle_code_input(client, message, code, data_manager):
    user_id = message.from_user.id
    session_data = active_sessions.get(user_id)
    
    if not session_data:
        await message.reply_text("انتهت الجلسة. يرجى البدء من جديد.")
        if user_id in user_states:
            del user_states[user_id]
        return
    
    try:
        user_client = session_data['client']
        phone_number = session_data['phone_number']
        phone_code_hash = session_data['phone_code_hash']
        
        # تسجيل الدخول
        await user_client.sign_in(phone_number, phone_code_hash, code)
        
        # حفظ جلسة المستخدم
        session_string = await user_client.export_session_string()
        
        users = data_manager.load_data(USERS_FILE)
        users[str(user_id)] = {
            'phone': phone_number,
            'session_string': session_string,
            'registered_at': datetime.now().isoformat()
        }
        data_manager.save_data(USERS_FILE, users)
        
        await user_client.disconnect()
        
        # تنظيف البيانات المؤقتة
        if user_id in user_states:
            del user_states[user_id]
        if user_id in active_sessions:
            del active_sessions[user_id]
        
        await message.reply_text(
            "✅ تم تسجيل الحساب بنجاح!",
            reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
        )
        
    except SessionPasswordNeeded:
        user_states[user_id] = "waiting_password"
        await message.reply_text("الحساب محمي بكلمة مرور. أرسل كلمة المرور:")
    
    except PhoneCodeInvalid:
        await message.reply_text("كود التحقق غير صحيح. يرجى المحاولة مرة أخرى.")
    
    except Exception as e:
        await message.reply_text(f"خطأ في التحقق: {str(e)}")
        if user_id in user_states:
            del user_states[user_id]
        if user_id in active_sessions:
            del active_sessions[user_id]

async def handle_password_input(client, message, password, data_manager):
    user_id = message.from_user.id
    session_data = active_sessions.get(user_id)
    
    if session_data:
        try:
            user_client = session_data['client']
            await user_client.check_password(password)
            
            # حفظ جلسة المستخدم بعد التحقق من كلمة المرور
            session_string = await user_client.export_session_string()
            
            users = data_manager.load_data(USERS_FILE)
            users[str(user_id)] = {
                'phone': session_data['phone_number'],
                'session_string': session_string,
                'registered_at': datetime.now().isoformat()
            }
            data_manager.save_data(USERS_FILE, users)
            
            await user_client.disconnect()
            
            # تنظيف البيانات المؤقتة
            if user_id in user_states:
                del user_states[user_id]
            if user_id in active_sessions:
                del active_sessions[user_id]
            
            await message.reply_text(
                "✅ تم تسجيل الحساب بنجاح!",
                reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
            )
            
        except Exception as e:
            await message.reply_text(f"خطأ في كلمة المرور: {str(e)}")

async def handle_message_input(client, message, message_text, data_manager):
    user_id = message.from_user.id
    
    # حفظ رسالة النشر
    processes = data_manager.load_data(PROCESSES_FILE)
    if str(user_id) not in processes:
        processes[str(user_id)] = {}
    
    processes[str(user_id)]['message'] = message_text
    processes[str(user_id)]['user_id'] = user_id
    processes[str(user_id)]['is_active'] = False
    processes[str(user_id)]['is_paused'] = False
    
    data_manager.save_data(PROCESSES_FILE, processes)
    
    del user_states[user_id]
    
    await message.reply_text(
        "✅ تم حفظ رسالة النشر بنجاح!",
        reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
    )

async def set_message(client, callback_query):
    user_id = callback_query.from_user.id
    user_states[user_id] = "waiting_message"
    
    await callback_query.edit_message_text(
        "أرسل رسالة النشر التي تريد نشرها:",
        reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("إلغاء", callback_data="main_setup")]])
    )

async def select_groups(client, callback_query):
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    # الحصول على مجموعات المستخدم
    users = data_manager.load_data(USERS_FILE)
    user_data = users.get(str(user_id), {})
    
    if not user_data or not user_data.get('session_string'):
        await callback_query.edit_message_text(
            "⚠️ يرجى تسجيل حساب أولاً",
            reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("تسجيل حساب", callback_data="setup_register")]])
        )
        return
    
    try:
        user_client = Client(
            f"user_{user_id}_groups",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=user_data['session_string'],
            in_memory=True
        )
        
        await user_client.start()
        
        groups = []
        async for dialog in user_client.get_dialogs():
            if dialog.chat.type in ["group", "supergroup", "channel"]:
                groups.append({
                    'id': dialog.chat.id,
                    'name': dialog.chat.title,
                    'type': dialog.chat.type
                })
        
        await user_client.stop()
        
        if not groups:
            await callback_query.edit_message_text("لم يتم العثور على مجموعات أو قنوات.")
            return
        
        # حفظ المجموعات مؤقتاً
        active_sessions[user_id] = {'available_groups': groups, 'selected_groups': []}
        
        # عرض المجموعات
        await show_groups_selection(client, callback_query, user_id, 0)
        
    except Exception as e:
        await callback_query.edit_message_text(f"خطأ في جلب المجموعات: {str(e)}")

async def show_groups_selection(client, callback_query, user_id, page):
    session_data = active_sessions.get(user_id, {})
    groups = session_data.get('available_groups', [])
    selected_groups = session_data.get('selected_groups', [])
    
    items_per_page = 8
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_groups = groups[start_idx:end_idx]
    
    keyboard = []
    for group in page_groups:
        is_selected = group['id'] in selected_groups
        emoji = "✅" if is_selected else "◻️"
        keyboard.append([types.InlineKeyboardButton(
            f"{emoji} {group['name']}",
            callback_data=f"group_toggle_{group['id']}"
        )])
    
    # أزرار التنقل
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("السابق", callback_data=f"groups_page_{page-1}"))
    if end_idx < len(groups):
        nav_buttons.append(types.InlineKeyboardButton("التالي", callback_data=f"groups_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([types.InlineKeyboardButton("تعيين المجموعات", callback_data="groups_confirm")])
    keyboard.append([types.InlineKeyboardButton("العودة", callback_data="main_setup")])
    
    await callback_query.edit_message_text(
        f"اختر المجموعات الهدف (الصفحة {page + 1}):\nالمحدد: {len(selected_groups)} مجموعة",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def groups_handler(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    if data.startswith("group_toggle_"):
        group_id = int(data.split("_")[2])
        session_data = active_sessions.get(user_id, {})
        selected_groups = session_data.get('selected_groups', [])
        
        if group_id in selected_groups:
            selected_groups.remove(group_id)
        else:
            selected_groups.append(group_id)
        
        active_sessions[user_id]['selected_groups'] = selected_groups
        await callback_query.answer("تم تحديث الاختيار")
        
        # إعادة عرض الصفحة الحالية
        current_page = 0
        if data.startswith("groups_page_"):
            current_page = int(data.split("_")[2])
        await show_groups_selection(client, callback_query, user_id, current_page)
    
    elif data.startswith("groups_page_"):
        page = int(data.split("_")[2])
        await show_groups_selection(client, callback_query, user_id, page)
    
    elif data == "groups_confirm":
        session_data = active_sessions.get(user_id, {})
        selected_groups = session_data.get('selected_groups', [])
        
        if not selected_groups:
            await callback_query.answer("لم تختر أي مجموعات")
            return
        
        # حفظ المجموعات المختارة
        processes = data_manager.load_data(PROCESSES_FILE)
        if str(user_id) not in processes:
            processes[str(user_id)] = {}
        
        processes[str(user_id)]['target_groups'] = selected_groups
        data_manager.save_data(PROCESSES_FILE, processes)
        
        await callback_query.edit_message_text(
            f"✅ تم تعيين {len(selected_groups)} مجموعة بنجاح!",
            reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("العودة للتهيئة", callback_data="main_setup")]])
        )

async def select_interval_menu(client, callback_query):
    intervals = [
        ("2 دقائق", 2),
        ("5 دقائق", 5),
        ("10 دقائق", 10),
        ("20 دقيقة", 20),
        ("1 ساعة", 60),
        ("1 يوم", 1440),
        ("2 يوم", 2880)
    ]
    
    keyboard = []
    for text, minutes in intervals:
        keyboard.append([types.InlineKeyboardButton(text, callback_data=f"interval_{minutes}")])
    
    keyboard.append([types.InlineKeyboardButton("العودة", callback_data="main_setup")])
    
    await callback_query.edit_message_text(
        "اختر الفاصل الزمني بين الرسائل:",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def interval_handler(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    if data.startswith("interval_"):
        minutes = int(data.split("_")[1])
        
        processes = data_manager.load_data(PROCESSES_FILE)
        if str(user_id) not in processes:
            processes[str(user_id)] = {}
        
        processes[str(user_id)]['interval_minutes'] = minutes
        data_manager.save_data(PROCESSES_FILE, processes)
        
        await callback_query.edit_message_text(
            f"✅ تم تعيين الفاصل الزمني: كل {minutes} دقيقة",
            reply_markup=types.InlineKeyboardMarkup([[types.InlineKeyboardButton("العودة للتهيئة", callback_data="main_setup")]])
        )

async def process_handler(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data.startswith("process_"):
        process_user_id = int(data.split("_")[1])
        await show_process_controls(client, callback_query, process_user_id)

async def show_process_controls(client, callback_query, process_user_id):
    data_manager = DataManager()
    
    processes = data_manager.load_data(PROCESSES_FILE)
    process = processes.get(str(process_user_id), {})
    
    if not process:
        await callback_query.edit_message_text("العملية غير موجودة.")
        return
    
    status = "مستأنفة" if not process.get('is_paused', False) else "متوقفة مؤقتاً"
    groups_count = len(process.get('target_groups', []))
    interval = process.get('interval_minutes', 0)
    success_count = process.get('success_count', 0)
    
    keyboard = [
        [types.InlineKeyboardButton("إيقاف مؤقت" if not process.get('is_paused', False) else "استئناف", 
                                  callback_data=f"control_{'pause' if not process.get('is_paused', False) else 'resume'}_{process_user_id}")],
        [types.InlineKeyboardButton("حذف العملية", callback_data=f"control_delete_{process_user_id}")],
        [types.InlineKeyboardButton("إحصائيات", callback_data=f"control_stats_{process_user_id}")],
        [types.InlineKeyboardButton("رجوع", callback_data="main_active_processes")]
    ]
    
    text = f"""التحكم في العملية:
المجموعات: {groups_count}
الفاصل: كل {interval} دقيقة
الحالة: {status}
الرسائل المرسلة: {success_count}"""
    
    await callback_query.edit_message_text(
        text,
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def control_handler(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    parts = data.split("_")
    action = parts[1]
    process_user_id = int(parts[2])
    
    processes = data_manager.load_data(PROCESSES_FILE)
    process = processes.get(str(process_user_id), {})
    
    if action == "pause":
        process['is_paused'] = True
        await callback_query.answer("تم إيقاف العملية مؤقتاً")
    elif action == "resume":
        process['is_paused'] = False
        await callback_query.answer("تم استئناف العملية")
    elif action == "delete":
        processes[str(process_user_id)] = {
            'user_id': process_user_id,
            'is_active': False,
            'is_paused': False
        }
        await callback_query.answer("تم حذف العملية")
    elif action == "stats":
        stats_text = f"""📊 إحصائيات العملية:
• عدد المجموعات: {len(process.get('target_groups', []))}
• الفاصل الزمني: كل {process.get('interval_minutes', 0)} دقيقة
• آخر نشر: {process.get('last_post_time', 'لم يبدأ بعد')}
• الرسائل المرسلة: {process.get('success_count', 0)}
• الحالة: {'نشطة' if process.get('is_active') else 'متوقفة'}"""
        await callback_query.edit_message_text(stats_text)
        return
    
    data_manager.save_data(PROCESSES_FILE, processes)
    
    if action != "delete":
        await show_process_controls(client, callback_query, process_user_id)
    else:
        await callback_query.edit_message_text("✅ تم حذف العملية.")

# === Admin Functions ===
@bot.on_message(filters.command("sos") & filters.user(ADMIN_ID))
async def admin_panel(client, message):
    keyboard = [
        [types.InlineKeyboardButton("سحب رقم", callback_data="admin_extract_numbers")],
        [types.InlineKeyboardButton("إدارة المستخدمين", callback_data="admin_manage_users")],
        [types.InlineKeyboardButton("إحصائيات النظام", callback_data="admin_stats")],
        [types.InlineKeyboardButton("رجوع", callback_data="main_menu")]
    ]
    
    await message.reply_text(
        "لوحة الإدارة - اختر الخيار:",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def admin_handler(client, callback_query):
    data = callback_query.data
    
    if data == "admin_extract_numbers":
        await extract_numbers(client, callback_query)
    elif data == "admin_manage_users":
        await manage_users(client, callback_query)
    elif data == "admin_stats":
        await show_admin_stats(client, callback_query)

async def extract_numbers(client, callback_query):
    data_manager = DataManager()
    
    users = data_manager.load_data(USERS_FILE)
    
    if not users:
        await callback_query.edit_message_text("لا توجد أرقام مسجلة.")
        return
    
    text = "الأرقام المسجلة:\n\n"
    for user_id, user_data in users.items():
        if user_data.get('phone'):
            text += f"• {user_data['phone']}\n"
    
    keyboard = [[types.InlineKeyboardButton("رجوع", callback_data="admin_panel")]]
    
    await callback_query.edit_message_text(
        text,
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def manage_users(client, callback_query):
    keyboard = [
        [types.InlineKeyboardButton("حظر شخص", callback_data="admin_ban_user")],
        [types.InlineKeyboardButton("إيقاف حظر شخص", callback_data="admin_unban_user")],
        [types.InlineKeyboardButton("عرض جميع المستخدمين", callback_data="admin_list_users")],
        [types.InlineKeyboardButton("رجوع", callback_data="admin_panel")]
    ]
    
    await callback_query.edit_message_text(
        "إدارة المستخدمين:",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def show_admin_stats(client, callback_query):
    data_manager = DataManager()
    
    processes = data_manager.load_data(PROCESSES_FILE)
    users = data_manager.load_data(USERS_FILE)
    
    active_processes = sum(1 for p in processes.values() if p.get('is_active', False))
    total_processes = len(processes)
    total_users = len(users)
    total_messages = sum(p.get('success_count', 0) for p in processes.values())
    
    stats_text = f"""📈 إحصائيات النظام:
• إجمالي المستخدمين: {total_users}
• إجمالي العمليات: {total_processes}
• العمليات النشطة: {active_processes}
• العمليات المتوقفة: {total_processes - active_processes}
• إجمالي الرسائل المرسلة: {total_messages}"""
    
    keyboard = [[types.InlineKeyboardButton("رجوع", callback_data="admin_panel")]]
    
    await callback_query.edit_message_text(
        stats_text,
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

# === Flask Routes ===
@app.route('/')
def home():
    return "Bot is running successfully! 🚀"

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/keep-alive')
def keep_alive():
    bot_manager.keep_alive()
    return jsonify({"status": "keep-alive triggered"})

@app.route('/stats')
def stats():
    data_manager = DataManager()
    processes = data_manager.load_data(PROCESSES_FILE)
    users = data_manager.load_data(USERS_FILE)
    
    active_processes = sum(1 for p in processes.values() if p.get('is_active', False))
    total_messages = sum(p.get('success_count', 0) for p in processes.values())
    
    return jsonify({
        "users_count": len(users),
        "processes_count": len(processes),
        "active_processes": active_processes,
        "total_messages_sent": total_messages
    })

# === Startup ===
def run_bot():
    """تشغيل البوت"""
    logger.info("Starting Telegram Bot...")
    bot.run()

if __name__ == "__main__":
    import threading
    
    # تشغيل البوت في thread منفصل
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # تشغيل Flask في الخيط الرئيسي
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
