import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
    CallbackContext
)
from telethon import TelegramClient
from telethon.sessions import StringSession
import sqlalchemy as sa
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# إعدادات التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# قاعدة البيانات
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String(50))
    phone_number = Column(String(20))
    session_string = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_banned = Column(Boolean, default=False)

class PublishingJob(Base):
    __tablename__ = 'publishing_jobs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    job_name = Column(String(100))
    message_text = Column(Text)
    groups = Column(Text)  # JSON list of group IDs
    interval_minutes = Column(Integer)
    is_active = Column(Boolean, default=True)
    is_paused = Column(Boolean, default=False)
    last_published = Column(DateTime)
    next_publish = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    stats_sent = Column(Integer, default=0)

class AdminAction(Base):
    __tablename__ = 'admin_actions'
    
    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer)
    action_type = Column(String(50))
    target_user_id = Column(Integer)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

# إعدادات البوت
BOT_TOKEN = "8052900952:AAEvZKao98ibPDlUqxBVcj6In1YOa4cbW18"
API_ID = 23656977
API_HASH = "49d3f43531a92b3f5bc403766313ca1e"
ADMIN_ID = 6689435577
FORCE_SUBSCRIBE_CHANNEL = "@iIl337"

# مراحل المحادثة
(
    PHONE_NUMBER, VERIFICATION_CODE, 
    SELECT_GROUPS, SET_INTERVAL, SET_MESSAGE
) = range(5)

# تهيئة قاعدة البيانات
engine = create_engine('sqlite:///bot.db', echo=False)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

class TelegramPublisherBot:
    def __init__(self):
        self.app = Application.builder().token(BOT_TOKEN).build()
        self.user_clients: Dict[int, TelegramClient] = {}
        self.setup_handlers()
    
    def setup_handlers(self):
        """إعداد المعالجات"""
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("sos", self.admin_panel))
        
        # معالجات الأزرار
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # معالجات المحادثة
        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_setup, pattern="^setup_publish$")],
            states={
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_phone)],
                VERIFICATION_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_verification)],
                SELECT_GROUPS: [CallbackQueryHandler(self.select_groups)],
                SET_INTERVAL: [CallbackQueryHandler(self.set_interval)],
                SET_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_message)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        self.app.add_handler(conv_handler)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بداية البوت"""
        user = update.effective_user
        
        # التحقق من الاشتراك الإجباري
        if not await self.check_subscription(user.id):
            keyboard = [[InlineKeyboardButton("اشترك في القناة", url=f"https://t.me/{FORCE_SUBSCRIBE_CHANNEL[1:]}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "يجب عليك الاشتراك في القناة أولاً:",
                reply_markup=reply_markup
            )
            return
        
        # حفظ المستخدم في قاعدة البيانات
        await self.save_user(user)
        
        # إظهار القائمة الرئيسية
        keyboard = [
            [InlineKeyboardButton("1- بدء عملية النشر", callback_data="start_publish")],
            [InlineKeyboardButton("2- العمليات النشطة", callback_data="active_jobs")],
            [InlineKeyboardButton("3- التحديثات", url=f"https://t.me/{FORCE_SUBSCRIBE_CHANNEL[1:]}")],
            [InlineKeyboardButton("4- تهيئة عملية النشر", callback_data="setup_publish")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "مرحباً بك في بوت النشر التلقائي!\n"
            "اختر أحد الخيارات التالية:",
            reply_markup=reply_markup
        )
    
    async def check_subscription(self, user_id: int) -> bool:
        """التحقق من اشتراك المستخدم في القناة"""
        try:
            member = await self.app.bot.get_chat_member(FORCE_SUBSCRIBE_CHANNEL, user_id)
            return member.status in ['member', 'administrator', 'creator']
        except:
            return False
    
    async def save_user(self, user):
        """حفظ المستخدم في قاعدة البيانات"""
        db_session = Session()
        try:
            existing_user = db_session.query(User).filter_by(telegram_id=user.id).first()
            if not existing_user:
                new_user = User(
                    telegram_id=user.id,
                    username=user.username or ""
                )
                db_session.add(new_user)
                db_session.commit()
        finally:
            db_session.close()
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """معالج الأزرار"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "start_publish":
            await self.start_publishing(query, context)
        elif data == "active_jobs":
            await self.show_active_jobs(query, context)
        elif data == "setup_publish":
            await self.start_setup(update, context)
        elif data.startswith("job_"):
            await self.handle_job_action(query, context)
        elif data.startswith("pause_"):
            await self.pause_job(query, context)
        elif data.startswith("resume_"):
            await self.resume_job(query, context)
        elif data.startswith("delete_"):
            await self.delete_job(query, context)
        elif data.startswith("stats_"):
            await self.show_job_stats(query, context)
        elif data.startswith("groups_page_"):
            await self.show_groups_page(query, context)
        elif data.startswith("select_group_"):
            await self.toggle_group_selection(query, context)
        elif data.startswith("interval_"):
            await self.save_interval(query, context)
    
    async def start_publishing(self, query, context):
        """بدء عملية النشر"""
        user_id = query.from_user.id
        
        db_session = Session()
        try:
            # التحقق من وجود عمليات نشطة
            active_jobs = db_session.query(PublishingJob).filter_by(
                user_id=user_id, is_active=True, is_paused=False
            ).all()
            
            if not active_jobs:
                await query.message.edit_text("لا توجد عمليات نشطة للبدء.")
                return
            
            # بدء النشر لكل عملية
            for job in active_jobs:
                await self.schedule_publishing(job)
            
            await query.message.edit_text("✅ تم بدء عملية النشر بنجاح!")
        finally:
            db_session.close()
    
    async def show_active_jobs(self, query, context):
        """عرض العمليات النشطة"""
        user_id = query.from_user.id
        
        db_session = Session()
        try:
            jobs = db_session.query(PublishingJob).filter_by(user_id=user_id, is_active=True).all()
            
            if not jobs:
                await query.message.edit_text("لا توجد عمليات نشطة حالياً.")
                return
            
            keyboard = []
            for job in jobs:
                status = "⏸️" if job.is_paused else "▶️"
                keyboard.append([InlineKeyboardButton(
                    f"{status} {job.job_name}", 
                    callback_data=f"job_{job.id}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text("العمليات النشطة:", reply_markup=reply_markup)
        finally:
            db_session.close()
    
    async def handle_job_action(self, query, context):
        """معالجة إجراءات العملية"""
        job_id = int(query.data.split("_")[1])
        user_id = query.from_user.id
        
        keyboard = [
            [
                InlineKeyboardButton("⏸️ إيقاف مؤقت", callback_data=f"pause_{job_id}"),
                InlineKeyboardButton("▶️ استئناف", callback_data=f"resume_{job_id}")
            ],
            [
                InlineKeyboardButton("🗑️ حذف العملية", callback_data=f"delete_{job_id}"),
                InlineKeyboardButton("📊 إحصائيات", callback_data=f"stats_{job_id}")
            ],
            [InlineKeyboardButton("🔙 رجوع", callback_data="active_jobs")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text("اختر الإجراء المطلوب:", reply_markup=reply_markup)
    
    async def pause_job(self, query, context):
        """إيقاف العملية مؤقتاً"""
        job_id = int(query.data.split("_")[1])
        
        db_session = Session()
        try:
            job = db_session.query(PublishingJob).filter_by(id=job_id).first()
            if job:
                job.is_paused = True
                db_session.commit()
                await query.answer("تم إيقاف العملية مؤقتاً")
        finally:
            db_session.close()
    
    async def resume_job(self, query, context):
        """استئناف العملية"""
        job_id = int(query.data.split("_")[1])
        
        db_session = Session()
        try:
            job = db_session.query(PublishingJob).filter_by(id=job_id).first()
            if job:
                job.is_paused = False
                db_session.commit()
                await query.answer("تم استئناف العملية")
        finally:
            db_session.close()
    
    async def delete_job(self, query, context):
        """حذف العملية"""
        job_id = int(query.data.split("_")[1])
        
        db_session = Session()
        try:
            job = db_session.query(PublishingJob).filter_by(id=job_id).first()
            if job:
                job.is_active = False
                db_session.commit()
                await query.answer("تم حذف العملية")
        finally:
            db_session.close()
    
    async def show_job_stats(self, query, context):
        """عرض إحصائيات العملية"""
        job_id = int(query.data.split("_")[1])
        
        db_session = Session()
        try:
            job = db_session.query(PublishingJob).filter_by(id=job_id).first()
            if job:
                stats_text = f"""
📊 إحصائيات العملية: {job.job_name}

✅ الرسائل المرسلة: {job.stats_sent}
⏰ الفاصل الزمني: {job.interval_minutes} دقيقة
📅 تاريخ الإنشاء: {job.created_at.strftime('%Y-%m-%d %H:%M')}
🔍 الحالة: {'نشطة' if not job.is_paused else 'موقوفة'}
                """
                await query.message.edit_text(stats_text)
        finally:
            db_session.close()
    
    async def start_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """بدء تهيئة عملية النشر"""
        query = update.callback_query
        await query.answer()
        
        await query.message.edit_text(
            "لتهيئة عملية النشر، أرسل رقم هاتفك مع رمز الدولة (مثال: +1234567890):"
        )
        return PHONE_NUMBER
    
    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """الحصول على رقم الهاتف"""
        phone = update.message.text
        context.user_data['phone'] = phone
        
        # إنشاء جلسة Telethon
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        
        try:
            await client.connect()
            sent_code = await client.send_code_request(phone)
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            context.user_data['client'] = client
            
            await update.message.reply_text(
                "تم إرسال كود التحقق. أرسل الكود الآن:"
            )
            return VERIFICATION_CODE
            
        except Exception as e:
            await update.message.reply_text(f"حدث خطأ: {str(e)}")
            return ConversationHandler.END
    
    async def get_verification(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """الحصول على كود التحقق"""
        code = update.message.text
        client = context.user_data['client']
        phone = context.user_data['phone']
        phone_code_hash = context.user_data['phone_code_hash']
        
        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            session_string = client.session.save()
            
            # حفظ الجلسة في قاعدة البيانات
            db_session = Session()
            try:
                user = db_session.query(User).filter_by(telegram_id=update.effective_user.id).first()
                if user:
                    user.phone_number = phone
                    user.session_string = session_string
                    db_session.commit()
            finally:
                db_session.close()
            
            await update.message.reply_text("✅ تم تسجيل الحساب بنجاح!")
            
            # الانتقال لاختيار المجموعات
            return await self.show_user_groups(update, context)
            
        except Exception as e:
            await update.message.reply_text(f"خطأ في التحقق: {str(e)}")
            return ConversationHandler.END
    
    async def show_user_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """عرض مجموعات المستخدم"""
        user_id = update.effective_user.id
        
        db_session = Session()
        try:
            user = db_session.query(User).filter_by(telegram_id=user_id).first()
            if not user or not user.session_string:
                await update.message.reply_text("لم يتم العثور على حسابك")
                return ConversationHandler.END
            
            # إنشاء عميل Telethon
            client = TelegramClient(
                StringSession(user.session_string), 
                API_ID, 
                API_HASH
            )
            
            await client.connect()
            
            # الحصول على المجموعات
            dialogs = await client.get_dialogs()
            groups = [d for d in dialogs if d.is_group or d.is_channel]
            
            context.user_data['groups'] = groups
            context.user_data['selected_groups'] = []
            
            await client.disconnect()
            
            return await self.show_groups_page(update, context, page=0)
            
        except Exception as e:
            await update.message.reply_text(f"خطأ في الحصول على المجموعات: {str(e)}")
            return ConversationHandler.END
        finally:
            db_session.close()
    
    async def show_groups_page(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        """عرض صفحة المجموعات"""
        groups = context.user_data.get('groups', [])
        selected_groups = context.user_data.get('selected_groups', [])
        
        items_per_page = 5
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        
        page_groups = groups[start_idx:end_idx]
        
        keyboard = []
        for group in page_groups:
            is_selected = group.id in selected_groups
            icon = "✅" if is_selected else "⭕"
            keyboard.append([InlineKeyboardButton(
                f"{icon} {group.name}", 
                callback_data=f"select_group_{group.id}"
            )])
        
        # أزرار التنقل
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"groups_page_{page-1}"))
        if end_idx < len(groups):
            nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"groups_page_{page+1}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("تعيين ✅", callback_data="set_groups")])
        
        if isinstance(update, Update) and update.callback_query:
            await update.callback_query.message.edit_text(
                "اختر المجموعات المطلوبة:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "اختر المجموعات المطلوبة:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        return SELECT_GROUPS
    
    async def toggle_group_selection(self, query, context):
        """تبديل اختيار المجموعة"""
        group_id = int(query.data.split("_")[2])
        selected_groups = context.user_data.get('selected_groups', [])
        
        if group_id in selected_groups:
            selected_groups.remove(group_id)
        else:
            selected_groups.append(group_id)
        
        context.user_data['selected_groups'] = selected_groups
        
        # إعادة عرض الصفحة
        current_page = context.user_data.get('current_page', 0)
        await self.show_groups_page(query, context, current_page)
    
    async def select_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """اختيار المجموعات"""
        if update.callback_query.data == "set_groups":
            # الانتقال لتحديد الفاصل الزمني
            keyboard = [
                [InlineKeyboardButton("2 دقيقة", callback_data="interval_2")],
                [InlineKeyboardButton("5 دقائق", callback_data="interval_5")],
                [InlineKeyboardButton("10 دقائق", callback_data="interval_10")],
                [InlineKeyboardButton("20 دقيقة", callback_data="interval_20")],
                [InlineKeyboardButton("ساعة", callback_data="interval_60")],
                [InlineKeyboardButton("يوم", callback_data="interval_1440")],
                [InlineKeyboardButton("يومين", callback_data="interval_2880")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.message.edit_text(
                "اختر الفاصل الزمني للنشر:",
                reply_markup=reply_markup
            )
            return SET_INTERVAL
        
        return await self.toggle_group_selection(update.callback_query, context)
    
    async def set_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تحديد الفاصل الزمني"""
        query = update.callback_query
        await query.answer()
        
        interval = int(query.data.split("_")[1])
        context.user_data['interval'] = interval
        
        await query.message.edit_text("الآن أرسل رسالة النشر التي تريدها:")
        return SET_MESSAGE
    
    async def save_interval(self, query, context):
        """حفظ الفاصل الزمني"""
        interval = int(query.data.split("_")[1])
        context.user_data['interval'] = interval
        
        await query.message.edit_text("الآن أرسل رسالة النشر التي تريدها:")
        return SET_MESSAGE
    
    async def set_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """تحديد رسالة النشر"""
        message_text = update.message.text
        user_id = update.effective_user.id
        
        # حفظ عملية النشر
        db_session = Session()
        try:
            selected_groups = context.user_data.get('selected_groups', [])
            interval = context.user_data.get('interval', 5)
            
            job = PublishingJob(
                user_id=user_id,
                job_name=f"عملية {len(selected_groups)} مجموعة",
                message_text=message_text,
                groups=json.dumps(selected_groups),
                interval_minutes=interval,
                next_publish=datetime.utcnow() + timedelta(minutes=interval)
            )
            
            db_session.add(job)
            db_session.commit()
            
            await update.message.reply_text(
                "✅ تم حفظ عملية النشر بنجاح!\n"
                "يمكنك الآن بدء النشر من القائمة الرئيسية."
            )
            
        except Exception as e:
            await update.message.reply_text(f"خطأ في الحفظ: {str(e)}")
        finally:
            db_session.close()
        
        return ConversationHandler.END
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """إلغاء المحادثة"""
        await update.message.reply_text("تم الإلغاء.")
        return ConversationHandler.END
    
    async def schedule_publishing(self, job: PublishingJob):
        """جدولة عملية النشر"""
        # سيتم تنفيذ هذا في نسخة محسنة
        pass
    
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """لوحة تحكم المدير"""
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("غير مصرح لك باستخدام هذا الأمر.")
            return
        
        keyboard = [
            [InlineKeyboardButton("سحب رقم", callback_data="pull_number")],
            [InlineKeyboardButton("إدارة المستخدمين", callback_data="manage_users")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "لوحة تحكم المدير:",
            reply_markup=reply_markup
        )
    
    def run(self):
        """تشغيل البوت"""
        logger.info("بدء تشغيل البوت...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TelegramPublisherBot()
    bot.run()
