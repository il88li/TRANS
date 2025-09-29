import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pyrogram import Client
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# بيانات البوت
BOT_TOKEN = "8052900952:AAEvZKao98ibPDlUqxBVcj6In1YOa4cbW18"
API_ID = 23656977
API_HASH = "49d3f43531a92b3f5bc403766313ca1e"
ADMIN_ID = 6689435577
CHANNEL_USERNAME = "@iIl337"

# ملفات البيانات
USERS_FILE = "users.json"
PROCESSES_FILE = "processes.json"
ADMIN_LOGS_FILE = "admin_logs.json"

# حالة المستخدمين
user_states = {}
user_sessions = {}

# المبين
scheduler = AsyncIOScheduler()

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

class TelegramBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.data_manager = DataManager()
        self.setup_handlers()
        
    def setup_handlers(self):
        # handlers للأوامر
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("sos", self.admin_panel))
        
        # handlers للأزرار
        self.application.add_handler(CallbackQueryHandler(self.button_handler, pattern="^main_"))
        self.application.add_handler(CallbackQueryHandler(self.setup_handler, pattern="^setup_"))
        self.application.add_handler(CallbackQueryHandler(self.process_handler, pattern="^process_"))
        self.application.add_handler(CallbackQueryHandler(self.admin_handler, pattern="^admin_"))
        self.application.add_handler(CallbackQueryHandler(self.groups_handler, pattern="^(group_|groups_)"))
        self.application.add_handler(CallbackQueryHandler(self.interval_handler, pattern="^interval_"))
        
        # handlers للرسائل
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        keyboard = [
            [InlineKeyboardButton("بدء عملية النشر", callback_data="main_start_publish")],
            [InlineKeyboardButton("العمليات النشطة", callback_data="main_active_processes")],
            [InlineKeyboardButton("التحديثات", callback_data="main_updates")],
            [InlineKeyboardButton("تهيئة عملية النشر", callback_data="main_setup")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "مرحباً! أنا بوت النشر التلقائي. اختر أحد الخيارات:",
            reply_markup=reply_markup
        )
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "main_start_publish":
            await self.start_publishing(update, context)
        elif data == "main_active_processes":
            await self.show_active_processes(update, context)
        elif data == "main_updates":
            await self.show_updates(update, context)
        elif data == "main_setup":
            await self.show_setup_menu(update, context)
        elif data == "main_menu":
            await self.show_main_menu(update, context)
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
        keyboard = [
            [InlineKeyboardButton("بدء عملية النشر", callback_data="main_start_publish")],
            [InlineKeyboardButton("العمليات النشطة", callback_data="main_active_processes")],
            [InlineKeyboardButton("التحديثات", callback_data="main_updates")],
            [InlineKeyboardButton("تهيئة عملية النشر", callback_data="main_setup")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "القائمة الرئيسية - اختر أحد الخيارات:",
            reply_markup=reply_markup
        )
    
    async def start_publishing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        # التحقق من اكتمال التهيئة
        processes = self.data_manager.load_data(PROCESSES_FILE)
        user_process = processes.get(str(user_id))
        
        if not user_process or not user_process.get('target_groups') or not user_process.get('message'):
            await query.edit_message_text(
                "⚠️ يرجى تهيئة عملية النشر أولاً (تسجيل حساب، تحديد المجموعات، ورسالة النشر)",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تهيئة عملية النشر", callback_data="main_setup")]])
            )
            return
        
        user_process['is_active'] = True
        user_process['is_paused'] = False
        processes[str(user_id)] = user_process
        self.data_manager.save_data(PROCESSES_FILE, processes)
        
        # بدء الجدولة
        await self.schedule_publishing(user_id, user_process)
        
        await query.edit_message_text(
            "✅ تم بدء عملية النشر بنجاح!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
        )
    
    async def show_active_processes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        processes = self.data_manager.load_data(PROCESSES_FILE)
        user_process = processes.get(str(user_id), {})
        
        if not user_process or not user_process.get('is_active'):
            await query.edit_message_text(
                "لا توجد عمليات نشطة حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
            )
            return
        
        keyboard = []
        group_name = user_process['target_groups'][0] if user_process['target_groups'] else "مجموعات متعددة"
        keyboard.append([InlineKeyboardButton(
            f"{group_name} - كل {user_process['interval_minutes']} دقيقة", 
            callback_data=f"process_{user_id}"
        )])
        
        keyboard.append([InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")])
        
        await query.edit_message_text(
            "العمليات النشطة:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_updates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
        keyboard = [
            [InlineKeyboardButton("قناة التحديثات", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            "تابع آخر التحديثات على قناتنا:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def show_setup_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
        keyboard = [
            [InlineKeyboardButton("تسجيل حساب", callback_data="setup_register")],
            [InlineKeyboardButton("المجموعة الهدف", callback_data="setup_groups")],
            [InlineKeyboardButton("الفاصل الزمني", callback_data="setup_interval")],
            [InlineKeyboardButton("رسالة النشر", callback_data="setup_message")],
            [InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]
        ]
        
        await query.edit_message_text(
            "تهيئة عملية النشر - اختر الخيار المطلوب:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def setup_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "setup_register":
            await self.register_account(update, context)
        elif data == "setup_groups":
            await self.select_groups(update, context)
        elif data == "setup_interval":
            await self.select_interval_menu(update, context)
        elif data == "setup_message":
            await self.set_message(update, context)
    
    async def register_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        keyboard = [
            [InlineKeyboardButton("تسجيل بـ Pyrogram", callback_data="register_pyrogram")],
            [InlineKeyboardButton("العودة", callback_data="main_setup")]
        ]
        
        user_states[user_id] = "waiting_phone"
        
        await query.edit_message_text(
            "للتسجيل، سنحتاج إلى:\n"
            "1. رقم هاتفك\n"
            "2. كود التحقق\n"
            "3. كود التحقق ثنائي الخطوة (إن وجد)\n\n"
            "سيتم حفظ بيانات الجلسة بشكل آمن.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def select_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        # الحصول على مجموعات المستخدم
        users = self.data_manager.load_data(USERS_FILE)
        user_data = users.get(str(user_id), {})
        
        if not user_data or not user_data.get('session_string'):
            await query.edit_message_text(
                "⚠️ يرجى تسجيل حساب أولاً",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تسجيل حساب", callback_data="setup_register")]])
            )
            return
        
        # في بيئة Render، سنستخدم مجموعات وهمية للاختبار
        groups = [
            {'id': -100123456789, 'name': 'مجموعة اختبار 1', 'type': 'group'},
            {'id': -100987654321, 'name': 'قناة اختبار 2', 'type': 'channel'},
            {'id': -100111111111, 'name': 'مجموعة عامة', 'type': 'group'},
            {'id': -100222222222, 'name': 'قناة أخبار', 'type': 'channel'}
        ]
        
        # حفظ المجموعات مؤقتاً
        context.user_data['available_groups'] = groups
        context.user_data['selected_groups'] = []
        
        await self.show_groups_page(update, context, page=0)
    
    async def show_groups_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        query = update.callback_query
        groups = context.user_data['available_groups']
        selected_groups = context.user_data['selected_groups']
        
        items_per_page = 8
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_groups = groups[start_idx:end_idx]
        
        keyboard = []
        for group in page_groups:
            is_selected = any(g['id'] == group['id'] for g in selected_groups)
            emoji = "✅" if is_selected else "◻️"
            keyboard.append([InlineKeyboardButton(
                f"{emoji} {group['name']} ({group['type']})",
                callback_data=f"group_toggle_{group['id']}"
            )])
        
        # أزرار التنقل
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("السابق", callback_data=f"groups_page_{page-1}"))
        if end_idx < len(groups):
            nav_buttons.append(InlineKeyboardButton("التالي", callback_data=f"groups_page_{page+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("تعيين المجموعات", callback_data="groups_confirm")])
        keyboard.append([InlineKeyboardButton("العودة", callback_data="main_setup")])
        
        await query.edit_message_text(
            f"اختر المجموعات الهدف (الصفحة {page + 1}):\nالمحدد: {len(selected_groups)} مجموعة",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def groups_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data.startswith("group_toggle_"):
            group_id = int(data.split("_")[2])
            await self.toggle_group_selection(update, context, group_id)
        elif data.startswith("groups_page_"):
            page = int(data.split("_")[2])
            await self.show_groups_page(update, context, page)
        elif data == "groups_confirm":
            await self.confirm_groups_selection(update, context)
    
    async def toggle_group_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: int):
        query = update.callback_query
        selected_groups = context.user_data['selected_groups']
        available_groups = context.user_data['available_groups']
        
        group = next((g for g in available_groups if g['id'] == group_id), None)
        if group:
            if any(g['id'] == group_id for g in selected_groups):
                selected_groups[:] = [g for g in selected_groups if g['id'] != group_id]
            else:
                selected_groups.append(group)
        
        # إعادة عرض نفس الصفحة
        current_page = 0  # يمكن حساب الصفحة الحالية إذا لزم الأمر
        await self.show_groups_page(update, context, current_page)
    
    async def confirm_groups_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        selected_groups = context.user_data['selected_groups']
        
        if not selected_groups:
            await query.edit_message_text(
                "⚠️ لم تختر أي مجموعات",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة", callback_data="setup_groups")]])
            )
            return
        
        # حفظ المجموعات المختارة
        processes = self.data_manager.load_data(PROCESSES_FILE)
        if str(user_id) not in processes:
            processes[str(user_id)] = {}
        
        processes[str(user_id)]['target_groups'] = [group['id'] for group in selected_groups]
        self.data_manager.save_data(PROCESSES_FILE, processes)
        
        group_names = ", ".join([group['name'] for group in selected_groups])
        await query.edit_message_text(
            f"✅ تم تعيين المجموعات بنجاح:\n{group_names}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للتهيئة", callback_data="main_setup")]])
        )
    
    async def select_interval_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
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
            keyboard.append([InlineKeyboardButton(text, callback_data=f"interval_{minutes}")])
        
        keyboard.append([InlineKeyboardButton("العودة", callback_data="main_setup")])
        
        await query.edit_message_text(
            "اختر الفاصل الزمني بين الرسائل:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def interval_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data.startswith("interval_"):
            minutes = int(data.split("_")[1])
            
            # حفظ الفاصل الزمني
            processes = self.data_manager.load_data(PROCESSES_FILE)
            if str(user_id) not in processes:
                processes[str(user_id)] = {}
            
            processes[str(user_id)]['interval_minutes'] = minutes
            self.data_manager.save_data(PROCESSES_FILE, processes)
            
            await query.edit_message_text(
                f"✅ تم تعيين الفاصل الزمني: كل {minutes} دقيقة",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للتهيئة", callback_data="main_setup")]])
            )
    
    async def set_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        user_states[user_id] = "waiting_message"
        
        await query.edit_message_text(
            "أرسل رسالة النشر التي تريد نشرها:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء", callback_data="main_setup")]])
        )
    
    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        message_text = update.message.text
        
        if user_id in user_states:
            state = user_states[user_id]
            
            if state == "waiting_message":
                # حفظ رسالة النشر
                processes = self.data_manager.load_data(PROCESSES_FILE)
                if str(user_id) not in processes:
                    processes[str(user_id)] = {}
                
                processes[str(user_id)]['message'] = message_text
                processes[str(user_id)]['user_id'] = user_id
                processes[str(user_id)]['is_active'] = False
                processes[str(user_id)]['is_paused'] = False
                
                self.data_manager.save_data(PROCESSES_FILE, processes)
                
                del user_states[user_id]
                
                await update.message.reply_text(
                    "✅ تم حفظ رسالة النشر بنجاح!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
                )
    
    async def process_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data.startswith("process_"):
            process_user_id = int(data.split("_")[1])
            await self.show_process_controls(update, context, process_user_id)
        elif data.startswith("control_"):
            parts = data.split("_")
            process_user_id = int(parts[2])
            action = parts[1]
            
            await self.handle_process_control(update, context, process_user_id, action)
    
    async def show_process_controls(self, update: Update, context: ContextTypes.DEFAULT_TYPE, process_user_id: int):
        query = update.callback_query
        
        processes = self.data_manager.load_data(PROCESSES_FILE)
        process = processes.get(str(process_user_id), {})
        
        if not process:
            await query.edit_message_text("العملية غير موجودة.")
            return
        
        status = "مستأنفة" if not process.get('is_paused', False) else "متوقفة مؤقتاً"
        groups_count = len(process.get('target_groups', []))
        interval = process.get('interval_minutes', 0)
        
        keyboard = [
            [InlineKeyboardButton("إيقاف مؤقت" if not process.get('is_paused', False) else "استئناف", 
                                callback_data=f"control_{'pause' if not process.get('is_paused', False) else 'resume'}_{process_user_id}")],
            [InlineKeyboardButton("حذف العملية", callback_data=f"control_delete_{process_user_id}")],
            [InlineKeyboardButton("إحصائيات", callback_data=f"control_stats_{process_user_id}")],
            [InlineKeyboardButton("رجوع", callback_data="main_active_processes")]
        ]
        
        await query.edit_message_text(
            f"التحكم في العملية:\n"
            f"المجموعات: {groups_count}\n"
            f"الفاصل: كل {interval} دقيقة\n"
            f"الحالة: {status}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_process_control(self, update: Update, context: ContextTypes.DEFAULT_TYPE, process_user_id: int, action: str):
        query = update.callback_query
        
        processes = self.data_manager.load_data(PROCESSES_FILE)
        process = processes.get(str(process_user_id), {})
        
        if action == "pause":
            process['is_paused'] = True
        elif action == "resume":
            process['is_paused'] = False
        elif action == "delete":
            processes[str(process_user_id)] = {
                'user_id': process_user_id,
                'is_active': False,
                'is_paused': False
            }
        elif action == "stats":
            await query.edit_message_text(
                f"إحصائيات العملية:\n"
                f"تم النشر في: {len(process.get('target_groups', []))} مجموعة\n"
                f"آخر نشر: {process.get('next_post_time', 'لم يبدأ بعد')}"
            )
            return
        
        self.data_manager.save_data(PROCESSES_FILE, processes)
        
        if action != "delete":
            await self.show_process_controls(update, context, process_user_id)
        else:
            await query.edit_message_text("✅ تم حذف العملية.")
    
    async def schedule_publishing(self, user_id: int, process: dict):
        """جدولة عملية النشر"""
        async def publish_job():
            processes = self.data_manager.load_data(PROCESSES_FILE)
            current_process = processes.get(str(user_id), {})
            
            if current_process.get('is_paused', True) or not current_process.get('is_active', False):
                return
            
            users_data = self.data_manager.load_data(USERS_FILE)
            user_data = users_data.get(str(user_id), {})
            
            if not user_data or not user_data.get('session_string'):
                return
            
            try:
                # استخدام Pyrogram للنشر
                app = Client(
                    f"user_{user_id}",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=user_data['session_string']
                )
                
                async with app:
                    for group_id in current_process.get('target_groups', []):
                        try:
                            await app.send_message(group_id, current_process.get('message', ''))
                            await asyncio.sleep(1)  # فاصل بين الرسائل
                        except Exception as e:
                            logger.error(f"Error sending to group {group_id}: {e}")
                
                # تحديث وقت النشر التالي
                current_process['next_post_time'] = datetime.utcnow().isoformat()
                processes[str(user_id)] = current_process
                self.data_manager.save_data(PROCESSES_FILE, processes)
                
            except Exception as e:
                logger.error(f"Error in publishing job: {e}")
        
        # إضافة المهمة للمجدول
        trigger = IntervalTrigger(minutes=process.get('interval_minutes', 60))
        scheduler.add_job(publish_job, trigger, id=f"publish_{user_id}")
    
    # الميزات الإدارية
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if user_id != ADMIN_ID:
            await update.message.reply_text("⛔ ليس لديك صلاحية الوصول لهذا القسم.")
            return
        
        keyboard = [
            [InlineKeyboardButton("سحب رقم", callback_data="admin_extract_numbers")],
            [InlineKeyboardButton("إدارة المستخدمين", callback_data="admin_manage_users")],
            [InlineKeyboardButton("رجوع", callback_data="main_menu")]
        ]
        
        await update.message.reply_text(
            "لوحة الإدارة - اختر الخيار:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def admin_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if user_id != ADMIN_ID:
            await query.edit_message_text("⛔ ليس لديك صلاحية الوصول لهذا القسم.")
            return
        
        if data == "admin_extract_numbers":
            await self.extract_numbers(update, context)
        elif data == "admin_manage_users":
            await self.manage_users(update, context)
    
    async def extract_numbers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
        users = self.data_manager.load_data(USERS_FILE)
        
        if not users:
            await query.edit_message_text("لا توجد أرقام مسجلة.")
            return
        
        keyboard = []
        for user_id, user_data in users.items():
            if user_data.get('phone'):
                keyboard.append([InlineKeyboardButton(
                    user_data['phone'],
                    callback_data=f"admin_user_{user_id}"
                )])
        
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="admin_panel")])
        
        await query.edit_message_text(
            "الأرقام المسجلة:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def manage_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
        keyboard = [
            [InlineKeyboardButton("حظر شخص", callback_data="admin_ban_user")],
            [InlineKeyboardButton("إيقاف حظر شخص", callback_data="admin_unban_user")],
            [InlineKeyboardButton("رجوع", callback_data="admin_panel")]
        ]
        
        await query.edit_message_text(
            "إدارة المستخدمين:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    def run(self):
        """تشغيل البوت"""
        scheduler.start()
        self.application.run_polling()

if __name__ == "__main__":
    bot = TelegramBot()
    bot.run()
