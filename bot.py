import os
import json
import asyncio
import logging
import re
from datetime import datetime, timedelta
from pyrogram import Client, filters, types
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneNumberInvalid, PhoneCodeExpired
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# بيانات البوت
BOT_TOKEN = "8228285723:AAGKVLO0GA_hTeiKvweWGzeck24CsaIuHFk"
API_ID = 23656977
API_HASH = "49d3f43531a92b3f5bc403766313ca1e"
ADMIN_ID = 6689435577
CHANNEL_USERNAME = "@iIl337"

# ملفات البيانات
USERS_FILE = "users.json"
PROCESSES_FILE = "processes.json"

# حالة المستخدمين
user_states = {}
active_sessions = {}

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
            processes = self.data_manager.load_data(PROCESSES_FILE)
            active_count = sum(1 for p in processes.values() if p.get('is_active', False))
            logger.info(f"Bot is alive - {active_count} active processes")
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

def validate_phone_number(phone: str) -> bool:
    """التحقق من صحة رقم الهاتف"""
    # تحقق من التنسيق الدولي
    pattern = r'^\+[1-9]\d{1,14}$'
    return bool(re.match(pattern, phone))

async def handle_phone_input(client, message, phone_number, data_manager):
    user_id = message.from_user.id
    
    try:
        # التحقق من صحة رقم الهاتف
        if not validate_phone_number(phone_number):
            await message.reply_text(
                "❌ رقم الهاتف غير صحيح. يرجى استخدام التنسيق الدولي:\n"
                "مثال: +201234567890 أو +966512345678\n\n"
                "أرسل رقم الهاتف مرة أخرى:"
            )
            return
        
        # إنشاء عميل جديد
        user_client = Client(
            f"user_{user_id}_{int(datetime.now().timestamp())}",
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
        
        await message.reply_text(
            "📲 تم إرسال كود التحقق إلى هاتفك.\n\n"
            "أرسل الكود الآن (5 أرقام):\n"
            "إذا لم يصلك الكود، تأكد من:\n"
            "• صحة رقم الهاتف\n"
            "• إشارة الشبكة\n"
            "• إعادة المحاولة بعد دقائق"
        )
        
    except PhoneNumberInvalid:
        await message.reply_text(
            "❌ رقم الهاتف غير صحيح.\n\n"
            "يرجى التأكد من:\n"
            "• استخدام التنسيق الدولي مع +\n"
            "• أن الرقم مسجل في تليجرام\n"
            "• إعادة إرسال الرقم بشكل صحيح\n\n"
            "مثال: +201234567890"
        )
        if user_id in user_states:
            del user_states[user_id]
    
    except Exception as e:
        error_msg = f"خطأ في تسجيل الحساب: {str(e)}"
        logger.error(error_msg)
        
        if "FLOOD" in str(e):
            await message.reply_text(
                "⏳ تم طلب العديد من الرموز. يرجى الانتظار قليلاً قبل المحاولة مرة أخرى."
            )
        else:
            await message.reply_text(
                "❌ حدث خطأ غير متوقع. يرجى:\n"
                "• التأكد من رقم الهاتف\n"
                "• المحاولة مرة أخرى لاحقًا\n"
                "• التواصل مع الدعم إذا استمرت المشكلة"
            )
        
        if user_id in user_states:
            del user_states[user_id]

async def handle_code_input(client, message, code, data_manager):
    user_id = message.from_user.id
    session_data = active_sessions.get(user_id)
    
    if not session_data:
        await message.reply_text("انتهت الجلسة. يرجى البدء من جديد باستخدام /start")
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # تنظيف الكود من أي مسافات أو أحرف غير رقمية
    code = re.sub(r'\D', '', code)
    
    if len(code) != 5:
        await message.reply_text("❌ الكود يجب أن يكون 5 أرقام. أرسل الكود مرة أخرى:")
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
            "✅ تم تسجيل الحساب بنجاح!\n\n"
            "يمكنك الآن:\n"
            "• اختيار المجموعات الهدف\n"
            "• تعيين رسالة النشر\n"
            "• بدء عملية النشر التلقائي",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("المجموعة الهدف", callback_data="setup_groups")],
                [types.InlineKeyboardButton("رسالة النشر", callback_data="setup_message")],
                [types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
            ])
        )
        
    except SessionPasswordNeeded:
        user_states[user_id] = "waiting_password"
        await message.reply_text(
            "🔒 الحساب محمي بكلمة مرور.\n\n"
            "أرسل كلمة المرور الآن:"
        )
    
    except PhoneCodeInvalid:
        await message.reply_text(
            "❌ كود التحقق غير صحيح.\n\n"
            "يرجى:\n"
            "• التأكد من الكود (5 أرقام)\n"
            "• إعادة إرسال الكود الصحيح\n"
            "• طلب كود جديد إذا انتهت صلاحية الكود"
        )
    
    except PhoneCodeExpired:
        await message.reply_text(
            "❌ انتهت صلاحية كود التحقق.\n\n"
            "يرجى:\n"
            "• البدء من جديد بإرسال رقم الهاتف\n"
            "• استخدام الكود الجديد الذي سيصلك"
        )
        if user_id in user_states:
            del user_states[user_id]
        if user_id in active_sessions:
            del active_sessions[user_id]
    
    except Exception as e:
        error_msg = f"خطأ في التحقق: {str(e)}"
        logger.error(error_msg)
        await message.reply_text(
            "❌ حدث خطأ أثناء التحقق.\n\n"
            "يرجى:\n"
            "• المحاولة مرة أخرى\n"
            "• البدء من جديد إذا لزم الأمر\n"
            "• التأكد من صحة البيانات"
        )
        if user_id in user_states:
            del user_states[user_id]
        if user_id in active_sessions:
            del active_sessions[user_id]

async def handle_password_input(client, message, password, data_manager):
    user_id = message.from_user.id
    session_data = active_sessions.get(user_id)
    
    if not session_data:
        await message.reply_text("انتهت الجلسة. يرجى البدء من جديد باستخدام /start")
        if user_id in user_states:
            del user_states[user_id]
        return
    
    try:
        user_client = session_data['client']
        await user_client.check_password(password)
        
        # حفظ جلسة المستخدم بعد التحقق من كلمة المرور
        session_string = await user_client.export_session_string()
        
        users = data_manager.load_data(USERS_FILE)
        users[str(user_id)] = {
            'phone': session_data['phone_number'],
            'session_string': session_string,
            'registered_at': datetime.now().isoformat(),
            'has_2fa': True
        }
        data_manager.save_data(USERS_FILE, users)
        
        await user_client.disconnect()
        
        # تنظيف البيانات المؤقتة
        if user_id in user_states:
            del user_states[user_id]
        if user_id in active_sessions:
            del active_sessions[user_id]
        
        await message.reply_text(
            "✅ تم تسجيل الحساب بنجاح!\n\n"
            "تم تفعيل الحماية ثنائية العوامل.",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("المجموعة الهدف", callback_data="setup_groups")],
                [types.InlineKeyboardButton("رسالة النشر", callback_data="setup_message")],
                [types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
            ])
        )
        
    except Exception as e:
        error_msg = f"خطأ في كلمة المرور: {str(e)}"
        logger.error(error_msg)
        await message.reply_text(
            "❌ كلمة المرور غير صحيحة.\n\n"
            "أرسل كلمة المرور مرة أخرى:"
        )

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
        "مرحباً! 👋 أنا بوت النشر التلقائي.\n\n"
        "يمكنني مساعدتك في:\n"
        "• النشر التلقائي في القنوات والمجموعات\n"
        "• جدولة الرسائل بفترات زمنية\n"
        "• إدارة عمليات النشر بسهولة\n\n"
        "اختر أحد الخيارات:",
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
        "🏠 القائمة الرئيسية - اختر أحد الخيارات:",
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
            "⚠️ يرجى تهيئة عملية النشر أولاً:\n\n"
            "• تسجيل حساب\n"
            "• تحديد المجموعات الهدف\n"
            "• تعيين رسالة النشر",
            reply_markup=reply_markup
        )
        return
    
    user_process['is_active'] = True
    user_process['is_paused'] = False
    processes[str(user_id)] = user_process
    data_manager.save_data(PROCESSES_FILE, processes)
    
    groups_count = len(user_process.get('target_groups', []))
    interval = user_process.get('interval_minutes', 0)
    
    await callback_query.edit_message_text(
        f"✅ تم بدء عملية النشر بنجاح!\n\n"
        f"📊 تفاصيل العملية:\n"
        f"• عدد المجموعات: {groups_count}\n"
        f"• الفاصل الزمني: كل {interval} دقيقة\n"
        f"• الحالة: نشطة 🟢",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("عرض العمليات النشطة", callback_data="main_active_processes")],
            [types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
        ])
    )

async def show_active_processes(client, callback_query):
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    processes = data_manager.load_data(PROCESSES_FILE)
    user_process = processes.get(str(user_id), {})
    
    if not user_process or not user_process.get('is_active'):
        await callback_query.edit_message_text(
            "📭 لا توجد عمليات نشطة حالياً.\n\n"
            "يمكنك بدء عملية نشر جديدة من القائمة الرئيسية.",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("بدء عملية نشر", callback_data="main_start_publish")],
                [types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
            ])
        )
        return
    
    keyboard = []
    groups_count = len(user_process.get('target_groups', []))
    interval = user_process.get('interval_minutes', 0)
    status = "نشطة 🟢" if not user_process.get('is_paused', False) else "متوقفة مؤقتاً ⏸️"
    success_count = user_process.get('success_count', 0)
    
    keyboard.append([types.InlineKeyboardButton(
        f"📊 {groups_count} مجموعة | كل {interval} دقيقة | {status}", 
        callback_data=f"process_{user_id}"
    )])
    
    keyboard.append([types.InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")])
    
    await callback_query.edit_message_text(
        f"📋 العمليات النشطة:\n\n"
        f"الرسائل المرسلة: {success_count}",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def show_updates(client, callback_query):
    keyboard = [
        [types.InlineKeyboardButton("📢 قناة التحديثات", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
        [types.InlineKeyboardButton("🏠 العودة للرئيسية", callback_data="main_menu")]
    ]
    
    await callback_query.edit_message_text(
        "📰 تابع آخر التحديثات والإعلانات على قناتنا الرسمية:",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def show_setup_menu(client, callback_query):
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    users = data_manager.load_data(USERS_FILE)
    user_data = users.get(str(user_id), {})
    
    account_status = "✅ مسجل" if user_data.get('session_string') else "❌ غير مسجل"
    
    processes = data_manager.load_data(PROCESSES_FILE)
    user_process = processes.get(str(user_id), {})
    
    groups_status = f"✅ {len(user_process.get('target_groups', []))} مجموعة" if user_process.get('target_groups') else "❌ غير معين"
    message_status = "✅ معينة" if user_process.get('message') else "❌ غير معينة"
    interval_status = f"✅ {user_process.get('interval_minutes', 0)} دقيقة" if user_process.get('interval_minutes') else "❌ غير معين"
    
    keyboard = [
        [types.InlineKeyboardButton(f"حساب المستخدم - {account_status}", callback_data="setup_register")],
        [types.InlineKeyboardButton(f"المجموعة الهدف - {groups_status}", callback_data="setup_groups")],
        [types.InlineKeyboardButton(f"الفاصل الزمني - {interval_status}", callback_data="setup_interval")],
        [types.InlineKeyboardButton(f"رسالة النشر - {message_status}", callback_data="setup_message")],
        [types.InlineKeyboardButton("🏠 العودة للرئيسية", callback_data="main_menu")]
    ]
    
    await callback_query.edit_message_text(
        f"⚙️ تهيئة عملية النشر\n\n"
        f"حالة التهيئة:\n"
        f"• {account_status}\n"
        f"• {groups_status}\n"
        f"• {interval_status}\n"
        f"• {message_status}\n\n"
        f"اختر الخيار المطلوب:",
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
        [types.InlineKeyboardButton("📱 تسجيل حساب", callback_data="register_pyrogram")],
        [types.InlineKeyboardButton("🏠 العودة", callback_data="main_setup")]
    ]
    
    user_states[user_id] = "waiting_phone"
    
    await callback_query.edit_message_text(
        "🔐 تسجيل حساب المستخدم\n\n"
        "للتسجيل، سنحتاج إلى:\n"
        "1. 📱 رقم هاتفك مع رمز الدولة\n"
        "2. 🔢 كود التحقق (5 أرقام)\n"
        "3. 🔒 كلمة المرور (إذا كان الحساب محمي)\n\n"
        "❗ سيتم حفظ بيانات الجلسة بشكل آمن ولا يتم مشاركتها مع أي طرف ثالث.",
        reply_markup=types.InlineKeyboardMarkup(keyboard)
    )

async def register_handler(client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "register_pyrogram":
        user_states[user_id] = "waiting_phone"
        await callback_query.edit_message_text(
            "📱 أرسل رقم هاتفك مع رمز الدولة:\n\n"
            "🌍 أمثلة:\n"
            "• مصر: +201234567890\n"
            "• السعودية: +966512345678\n"
            "• الإمارات: +971501234567\n\n"
            "❗ تأكد من:\n"
            "• استخدام التنسيق الدولي مع +\n"
            "• أن الرقم مسجل في تليجرام\n"
            "• وجود إشارة شبكة جيدة",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("🔙 إلغاء", callback_data="main_setup")]
            ])
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
        "✅ تم حفظ رسالة النشر بنجاح!\n\n"
        f"📝 الرسالة:\n{message_text}\n\n"
        "يمكنك الآن بدء عملية النشر أو تعديل الإعدادات الأخرى.",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("بدء النشر", callback_data="main_start_publish")],
            [types.InlineKeyboardButton("الإعدادات", callback_data="main_setup")],
            [types.InlineKeyboardButton("الرئيسية", callback_data="main_menu")]
        ])
    )

async def set_message(client, callback_query):
    user_id = callback_query.from_user.id
    user_states[user_id] = "waiting_message"
    
    await callback_query.edit_message_text(
        "📝 إعداد رسالة النشر\n\n"
        "أرسل رسالة النشر التي تريد نشرها:\n\n"
        "💡 نصائح:\n"
        "• يمكنك استخدام النص العادي فقط\n"
        "• تجنب الرموز الخاصة\n"
        "• احرص على وضوح الرسالة",
        reply_markup=types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("🔙 إلغاء", callback_data="main_setup")]
        ])
    )

async def select_groups(client, callback_query):
    user_id = callback_query.from_user.id
    data_manager = DataManager()
    
    # الحصول على مجموعات المستخدم
    users = data_manager.load_data(USERS_FILE)
    user_data = users.get(str(user_id), {})
    
    if not user_data or not user_data.get('session_string'):
        await callback_query.edit_message_text(
            "⚠️ يرجى تسجيل حساب أولاً\n\n"
            "لا يمكن جلب المجموعات بدون تسجيل حساب المستخدم.",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("تسجيل حساب", callback_data="setup_register")],
                [types.InlineKeyboardButton("العودة", callback_data="main_setup")]
            ])
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
                # تجنب القنوات الخاصة التي لا يمكن الكتابة فيها
                try:
                    # اختبار إذا كان يمكن إرسال رسالة
                    chat_member = await user_client.get_chat_member(dialog.chat.id, 'me')
                    if chat_member.can_send_messages:
                        groups.append({
                            'id': dialog.chat.id,
                            'name': dialog.chat.title,
                            'type': dialog.chat.type
                        })
                except:
                    continue
        
        await user_client.stop()
        
        if not groups:
            await callback_query.edit_message_text(
                "❌ لم يتم العثور على مجموعات أو قنوات متاحة.\n\n"
                "تأكد من:\n"
                "• أنك مشرف في المجموعات\n"
                "• أن لديك صلاحية إرسال الرسائل\n"
                "• وجود مجموعات في حسابك",
                reply_markup=types.InlineKeyboardMarkup([
                    [types.InlineKeyboardButton("العودة", callback_data="main_setup")]
                ])
            )
            return
        
        # حفظ المجموعات مؤقتاً
        active_sessions[user_id] = {'available_groups': groups, 'selected_groups': []}
        
        # عرض المجموعات
        await show_groups_selection(client, callback_query, user_id, 0)
        
    except Exception as e:
        logger.error(f"Error fetching groups: {e}")
        await callback_query.edit_message_text(
            f"❌ خطأ في جلب المجموعات: {str(e)}\n\n"
            "يرجى:\n"
            "• التأكد من اتصال الإنترنت\n"
            "• إعادة تسجيل الحساب\n"
            "• المحاولة لاحقاً",
            reply_markup=types.InlineKeyboardMarkup([
                [types.InlineKeyboardButton("إعادة التسجيل", callback_data="setup_register")],
                [types.InlineKeyboardButton("العودة", callback_data="main_setup")]
            ])
        )

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

# === Startup ===
if __name__ == "__main__":
    logger.info("Starting Telegram Bot in Polling Mode...")
    print("🤖 Bot is starting...")
    print("📞 Token:", BOT_TOKEN[:10] + "..." if BOT_TOKEN else "Not set")
    print("🔑 API ID:", API_ID)
    print("👑 Admin ID:", ADMIN_ID)
    
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"❌ Failed to start bot: {e}")
