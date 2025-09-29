import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy import create_engine, Column, String, Integer, Boolean, Text, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession
from pyrogram import Client
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import json

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# إعداد قاعدة البيانات
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    phone = Column(String)
    session_string = Column(Text)
    is_banned = Column(Boolean, default=False)

class PublishingProcess(Base):
    __tablename__ = 'processes'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    target_groups = Column(JSON)  # قائمة المجموعات
    message = Column(Text)
    interval_minutes = Column(Integer)
    is_active = Column(Boolean, default=True)
    is_paused = Column(Boolean, default=False)
    next_post_time = Column(DateTime)

class AdminLog(Base):
    __tablename__ = 'admin_logs'
    id = Column(Integer, primary_key=True)
    action = Column(String)
    details = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow)

# إعداد قاعدة البيانات
engine = create_engine('sqlite:///bot.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db_session = Session()

# بيانات البوت
BOT_TOKEN = "8052900952:AAEvZKao98ibPDlUqxBVcj6In1YOa4cbW18"
API_ID = 23656977
API_HASH = "49d3f43531a92b3f5bc403766313ca1e"
ADMIN_ID = 6689435577
CHANNEL_USERNAME = "@iIl337"

# حالة المستخدمين
user_states = {}
user_sessions = {}
active_clients = {}

# المبين
scheduler = AsyncIOScheduler()

class TelegramBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
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
    
    async def start_publishing(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        # التحقق من اكتمال التهيئة
        process = db_session.query(PublishingProcess).filter_by(user_id=user_id).first()
        if not process or not process.target_groups or not process.message:
            await query.edit_message_text(
                "⚠️ يرجى تهيئة عملية النشر أولاً (تسجيل حساب، تحديد المجموعات، ورسالة النشر)",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تهيئة عملية النشر", callback_data="main_setup")]])
            )
            return
        
        process.is_active = True
        process.is_paused = False
        db_session.commit()
        
        # بدء الجدولة
        await self.schedule_publishing(user_id, process)
        
        await query.edit_message_text(
            "✅ تم بدء عملية النشر بنجاح!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
        )
    
    async def show_active_processes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        processes = db_session.query(PublishingProcess).filter_by(user_id=user_id, is_active=True).all()
        
        if not processes:
            await query.edit_message_text(
                "لا توجد عمليات نشطة حالياً.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
            )
            return
        
        keyboard = []
        for process in processes:
            group_name = process.target_groups[0] if process.target_groups else "مجموعات متعددة"
            keyboard.append([InlineKeyboardButton(
                f"{group_name} - كل {process.interval_minutes} دقيقة", 
                callback_data=f"process_{process.id}"
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
            await self.select_interval(update, context)
        elif data == "setup_message":
            await self.set_message(update, context)
    
    async def register_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        keyboard = [
            [InlineKeyboardButton("تسجيل بـ Telethon", callback_data="register_telethon")],
            [InlineKeyboardButton("تسجيل بـ Pyrogram", callback_data="register_pyrogram")],
            [InlineKeyboardButton("العودة", callback_data="main_setup")]
        ]
        
        user_states[user_id] = "waiting_phone"
        
        await query.edit_message_text(
            "اختر طريقة التسجيل:\n\nسيتم حفظ بيانات الجلسة بشكل آمن.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def process_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data.startswith("process_"):
            process_id = int(data.split("_")[1])
            await self.show_process_controls(update, context, process_id)
        elif data.startswith("control_"):
            parts = data.split("_")
            process_id = int(parts[2])
            action = parts[1]
            
            await self.handle_process_control(update, context, process_id, action)
    
    async def show_process_controls(self, update: Update, context: ContextTypes.DEFAULT_TYPE, process_id: int):
        query = update.callback_query
        process = db_session.query(PublishingProcess).filter_by(id=process_id).first()
        
        if not process:
            await query.edit_message_text("العملية غير موجودة.")
            return
        
        status = "مستأنفة" if not process.is_paused else "متوقفة مؤقتاً"
        
        keyboard = [
            [InlineKeyboardButton("إيقاف مؤقت" if not process.is_paused else "استئناف", 
                                callback_data=f"control_{'pause' if not process.is_paused else 'resume'}_{process_id}")],
            [InlineKeyboardButton("حذف العملية", callback_data=f"control_delete_{process_id}")],
            [InlineKeyboardButton("إحصائيات", callback_data=f"control_stats_{process_id}")],
            [InlineKeyboardButton("رجوع", callback_data="main_active_processes")]
        ]
        
        await query.edit_message_text(
            f"التحكم في العملية:\n"
            f"المجموعات: {len(process.target_groups)}\n"
            f"الفاصل: كل {process.interval_minutes} دقيقة\n"
            f"الحالة: {status}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def handle_process_control(self, update: Update, context: ContextTypes.DEFAULT_TYPE, process_id: int, action: str):
        query = update.callback_query
        process = db_session.query(PublishingProcess).filter_by(id=process_id).first()
        
        if action == "pause":
            process.is_paused = True
            db_session.commit()
        elif action == "resume":
            process.is_paused = False
            db_session.commit()
        elif action == "delete":
            db_session.delete(process)
            db_session.commit()
            await query.edit_message_text("✅ تم حذف العملية.")
            return
        elif action == "stats":
            await query.edit_message_text(
                f"إحصائيات العملية:\n"
                f"تم النشر في: {len(process.target_groups)} مجموعة\n"
                f"آخر نشر: {process.next_post_time if process.next_post_time else 'لم يبدأ بعد'}"
            )
            return
        
        await self.show_process_controls(update, context, process_id)
    
    async def select_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        # الحصول على مجموعات المستخدم
        user = db_session.query(User).filter_by(user_id=user_id).first()
        if not user or not user.session_string:
            await query.edit_message_text(
                "⚠️ يرجى تسجيل حساب أولاً",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تسجيل حساب", callback_data="setup_register")]])
            )
            return
        
        try:
            client = TelegramClient(StringSession(user.session_string), API_ID, API_HASH)
            await client.start()
            
            groups = []
            async for dialog in client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    groups.append({
                        'id': dialog.id,
                        'name': dialog.name,
                        'type': 'channel' if dialog.is_channel else 'group'
                    })
            
            await client.disconnect()
            
            if not groups:
                await query.edit_message_text("لم يتم العثور على مجموعات أو قنوات.")
                return
            
            # حفظ المجموعات مؤقتاً
            context.user_data['available_groups'] = groups
            context.user_data['selected_groups'] = []
            
            await self.show_groups_page(update, context, page=0)
            
        except Exception as e:
            await query.edit_message_text(f"خطأ في جلب المجموعات: {str(e)}")
    
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
    
    async def select_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                process = db_session.query(PublishingProcess).filter_by(user_id=user_id).first()
                if not process:
                    process = PublishingProcess(user_id=user_id)
                    db_session.add(process)
                
                process.message = message_text
                db_session.commit()
                
                del user_states[user_id]
                
                await update.message.reply_text(
                    "✅ تم حفظ رسالة النشر بنجاح!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("العودة للرئيسية", callback_data="main_menu")]])
                )
    
    async def schedule_publishing(self, user_id: int, process: PublishingProcess):
        """جدولة عملية النشر"""
        async def publish_job():
            if process.is_paused or not process.is_active:
                return
            
            user = db_session.query(User).filter_by(user_id=user_id).first()
            if not user or not user.session_string:
                return
            
            try:
                client = TelegramClient(StringSession(user.session_string), API_ID, API_HASH)
                await client.start()
                
                for group_id in process.target_groups:
                    try:
                        await client.send_message(int(group_id), process.message)
                        await asyncio.sleep(1)  # فاصل بين الرسائل
                    except Exception as e:
                        logger.error(f"Error sending to group {group_id}: {e}")
                
                await client.disconnect()
                
                # تحديث وقت النشر التالي
                process.next_post_time = datetime.utcnow() + timedelta(minutes=process.interval_minutes)
                db_session.commit()
                
            except Exception as e:
                logger.error(f"Error in publishing job: {e}")
        
        # إضافة المهمة للمجدول
        trigger = IntervalTrigger(minutes=process.interval_minutes)
        scheduler.add_job(publish_job, trigger, id=f"publish_{user_id}_{process.id}")
    
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
        
        users = db_session.query(User).all()
        
        if not users:
            await query.edit_message_text("لا توجد أرقام مسجلة.")
            return
        
        keyboard = []
        for user in users:
            if user.phone:
                keyboard.append([InlineKeyboardButton(
                    user.phone,
                    callback_data=f"admin_user_{user.id}"
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
