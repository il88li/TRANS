import os
import logging
import asyncio
from threading import Thread
from datetime import datetime, timedelta
import sqlite3
from contextlib import contextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telethon import TelegramClient, events
from telethon.tl.types import Channel, User
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from flask import Flask, request, jsonify
import aiohttp

# إعدادات البوت
BOT_TOKEN = "8137587721:AAGq7kyLc3E0EL7HZ2SKRmJPGj3OLQFVSKo"
API_ID = 23656977
API_HASH = "49d3f43531a92b3f5bc403766313ca1e"
WEBHOOK_URL = "https://trans-ygyf.onrender.com"

# إعدادات قاعدة البيانات
DB_NAME = "transfer_bot.db"

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تطبيق Flask للحفاظ على البوت نشطاً
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    return jsonify({"status": "ok"})

# إدارة قاعدة البيانات
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            source_chat_id INTEGER,
            target_chat_id INTEGER,
            status TEXT,
            total_members INTEGER,
            transferred INTEGER,
            start_time DATETIME,
            end_time DATETIME
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sessions (
            user_id INTEGER PRIMARY KEY,
            phone TEXT,
            session_file TEXT,
            is_authenticated BOOLEAN DEFAULT FALSE
        )
    ''')
    conn.commit()
    conn.close()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

class TransferBot:
    def __init__(self):
        self.bot_app = None
        self.user_clients = {}  # {user_id: TelegramClient}
        self.active_transfers = {}  # {user_id: transfer_info}
        self.setup_db()
        
    def setup_db(self):
        init_db()
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        keyboard = [
            [InlineKeyboardButton("📋 تهيئة النقل", callback_data="setup_transfer")],
            [InlineKeyboardButton("▶️ بدء النقل", callback_data="start_transfer")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = """
        > **مرحباً بك في بوت نقل الأعضاء**
        
        *المميزات:*
        - نقل الأعضاء بين المجموعات والقنوات
        - إحصائيات حية أثناء النقل
        - فاصل زمني آمن بين كل عملية نقل
        
        *إبدأ بتهيئة النقل أولاً* ⚙️
        """
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if query.data == "setup_transfer":
            await self.setup_transfer(update, context)
        elif query.data == "start_transfer":
            await self.start_transfer(update, context)
        elif query.data == "stats":
            await self.show_stats(update, context)
        elif query.data == "login":
            await self.request_login(update, context)
        elif query.data == "select_source":
            await self.select_source_chat(update, context)
        elif query.data == "select_target":
            await self.select_target_chat(update, context)

    async def setup_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        keyboard = [
            [InlineKeyboardButton("🔑 تسجيل الدخول", callback_data="login")],
            [InlineKeyboardButton("📥 تحديد المصدر", callback_data="select_source")],
            [InlineKeyboardButton("📤 تحديد الهدف", callback_data="select_target")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        setup_text = """
        > **تهيئة إعدادات النقل**
        
        *الخطوات المطلوبة:*
        1. تسجيل الدخول إلى حسابك
        2. تحديد المجموعة المصدر
        3. تحديد المجموعة الهدف
        
        *الفاصل الزمني:* 10 دقائق بين كل عملية نقل
        """
        
        await query.edit_message_text(
            setup_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def request_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        # طلب رقم الهاتف
        await query.edit_message_text(
            "> **يرجى إرسال رقم هاتفك مع رمز الدولة**\n\nمثال: +201234567890",
            parse_mode='Markdown'
        )
        context.user_data['awaiting_phone'] = True

    async def handle_phone_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        phone_number = update.message.text
        
        if not context.user_data.get('awaiting_phone'):
            return
            
        try:
            # إنشاء جلسة جديدة للمستخدم
            session_name = f"session_{user_id}"
            client = TelegramClient(session_name, API_ID, API_HASH)
            
            await client.connect()
            sent_code = await client.send_code_request(phone_number)
            
            context.user_data['phone_number'] = phone_number
            context.user_data['client'] = client
            context.user_data['phone_code_hash'] = sent_code.phone_code_hash
            context.user_data['awaiting_code'] = True
            
            await update.message.reply_text(
                "> **تم إرسال رمز التحقق إليك**\n\nيرجى إرسال رمز التحقق الذي استلمته",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {str(e)}")

    async def handle_code(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        code = update.message.text
        
        if not context.user_data.get('awaiting_code'):
            return
            
        try:
            client = context.user_data['client']
            phone_number = context.user_data['phone_number']
            phone_code_hash = context.user_data['phone_code_hash']
            
            await client.sign_in(
                phone=phone_number,
                code=code,
                phone_code_hash=phone_code_hash
            )
            
            # حفظ الجلسة في قاعدة البيانات
            with get_db_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO user_sessions 
                    (user_id, phone, session_file, is_authenticated)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, phone_number, f"session_{user_id}", True))
                conn.commit()
            
            self.user_clients[user_id] = client
            
            await update.message.reply_text(
                "> ✅ **تم تسجيل الدخول بنجاح**",
                parse_mode='Markdown'
            )
            
            # إعادة عرض قائمة التهيئة
            await self.show_main_menu(update, context)
            
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في التسجيل: {str(e)}")

    async def select_source_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        if user_id not in self.user_clients:
            await query.edit_message_text(
                "> ❌ **يجب تسجيل الدخول أولاً**",
                parse_mode='Markdown'
            )
            return
            
        await query.edit_message_text(
            "> **جاري جلب المجموعات المتاحة...**",
            parse_mode='Markdown'
        )
        
        try:
            client = self.user_clients[user_id]
            dialogs = await client.get_dialogs()
            
            groups = []
            for dialog in dialogs:
                if dialog.is_channel or dialog.is_group:
                    groups.append(dialog)
            
            if not groups:
                await query.edit_message_text("❌ لم يتم العثور على مجموعات")
                return
                
            keyboard = []
            for group in groups[:10]:  # عرض أول 10 مجموعات فقط
                title = getattr(group.entity, 'title', 'Unknown')
                keyboard.append([InlineKeyboardButton(
                    f"📥 {title}", 
                    callback_data=f"source_{group.id}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="setup_transfer")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "> **اختر المجموعة المصدر:**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {str(e)}")

    async def start_transfer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        # التحقق من التهيئة
        with get_db_connection() as conn:
            cursor = conn.execute('''
                SELECT us.is_authenticated, ts.source_chat_id, ts.target_chat_id 
                FROM user_sessions us
                LEFT JOIN transfers ts ON us.user_id = ts.user_id AND ts.status = 'pending'
                WHERE us.user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            
        if not result or not result['is_authenticated']:
            await query.edit_message_text(
                "> ❌ **يجب تهيئة النقل أولاً**",
                parse_mode='Markdown'
            )
            return
            
        if not result['source_chat_id'] or not result['target_chat_id']:
            await query.edit_message_text(
                "> ❌ **يجب تحديد المصدر والهدف أولاً**",
                parse_mode='Markdown'
            )
            return
        
        # بدء عملية النقل
        await self.start_transfer_process(user_id, query)

    async def start_transfer_process(self, user_id, query):
        try:
            client = self.user_clients[user_id]
            
            with get_db_connection() as conn:
                cursor = conn.execute('''
                    SELECT source_chat_id, target_chat_id 
                    FROM transfers 
                    WHERE user_id = ? AND status = 'pending'
                ''', (user_id,))
                transfer_data = cursor.fetchone()
                
            source_id = transfer_data['source_chat_id']
            target_id = transfer_data['target_chat_id']
            
            # جلب الأعضاء من المصدر
            participants = await client.get_participants(source_id)
            total_members = len(participants)
            
            # تحديث قاعدة البيانات
            with get_db_connection() as conn:
                conn.execute('''
                    UPDATE transfers 
                    SET status = 'active', total_members = ?, start_time = datetime('now')
                    WHERE user_id = ?
                ''', (total_members, user_id))
                conn.commit()
            
            # بدء النقل
            transferred = 0
            failed = 0
            
            for participant in participants:
                if isinstance(participant, User) and not participant.bot:
                    try:
                        await client(InviteToChannelRequest(
                            channel=target_id,
                            users=[participant]
                        ))
                        transferred += 1
                        
                        # تحديث الإحصائيات
                        with get_db_connection() as conn:
                            conn.execute('''
                                UPDATE transfers 
                                SET transferred = ?
                                WHERE user_id = ?
                            ''', (transferred, user_id))
                            conn.commit()
                        
                        # تحديث الرسالة كل 10 عمليات نقل
                        if transferred % 10 == 0:
                            stats_text = f"""
                            > **جاري نقل الأعضاء...**
                            
                            *الإحصائيات:*
                            - ✅ تم نقل: {transferred}
                            - ❌ فشل: {failed}
                            - 📊 المتبقي: {total_members - transferred}
                            - ⏰ الوقت المنقضي: {datetime.now().strftime('%H:%M:%S')}
                            """
                            
                            await query.edit_message_text(
                                stats_text,
                                parse_mode='Markdown'
                            )
                        
                        # انتظار 10 دقائق بين كل عملية
                        await asyncio.sleep(600)  # 10 دقائق
                        
                    except Exception as e:
                        failed += 1
                        logger.error(f"Failed to transfer user: {e}")
            
            # إنهاء النقل
            with get_db_connection() as conn:
                conn.execute('''
                    UPDATE transfers 
                    SET status = 'completed', end_time = datetime('now')
                    WHERE user_id = ?
                ''', (user_id,))
                conn.commit()
            
            completion_text = f"""
            > **✅ اكتملت عملية النقل**
            
            *النتائج النهائية:*
            - ✅ تم نقل: {transferred}
            - ❌ فشل: {failed}
            - ⏰ وقت البدء: {datetime.now().strftime('%Y-%m-%d %H:%M')}
            """
            
            await query.edit_message_text(
                completion_text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Transfer process failed: {e}")
            await query.edit_message_text(f"❌ فشلت عملية النقل: {str(e)}")

    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        with get_db_connection() as conn:
            cursor = conn.execute('''
                SELECT status, total_members, transferred, start_time
                FROM transfers 
                WHERE user_id = ? 
                ORDER BY id DESC 
                LIMIT 1
            ''', (user_id,))
            stats = cursor.fetchone()
        
        if not stats:
            stats_text = "> **لا توجد إحصائيات متاحة**"
        else:
            stats_text = f"""
            > **📊 الإحصائيات الأخيرة**
            
            *حالة النقل:* {stats['status']}
            *إجمالي الأعضاء:* {stats['total_members'] or 0}
            *تم نقلهم:* {stats['transferred'] or 0}
            *وقت البدء:* {stats['start_time'] or 'غير محدد'}
            """
        
        keyboard = [[InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            stats_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if hasattr(update, 'callback_query'):
            query = update.callback_query
            user_id = query.from_user.id
            message = query.message
        else:
            user_id = update.effective_user.id
            message = update.message
        
        keyboard = [
            [InlineKeyboardButton("📋 تهيئة النقل", callback_data="setup_transfer")],
            [InlineKeyboardButton("▶️ بدء النقل", callback_data="start_transfer")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            "> **القائمة الرئيسية**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def keep_alive(self):
        """دورة للحفاظ على البوت نشطاً"""
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(WEBHOOK_URL) as resp:
                        logger.info(f"Keep-alive ping: {resp.status}")
            except Exception as e:
                logger.error(f"Keep-alive error: {e}")
            await asyncio.sleep(300)  # كل 5 دقائق

    def run_flask(self):
        """تشغيل خادم Flask في thread منفصل"""
        app.run(host='0.0.0.0', port=5000)

def main():
    # إنشاء البوت
    transfer_bot = TransferBot()
    
    # تشغيل Flask في thread منفصل
    flask_thread = Thread(target=transfer_bot.run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # إنشاء تطبيق البوت
    application = Application.builder().token(BOT_TOKEN).build()
    
    # إضافة handlers
    application.add_handler(CommandHandler("start", transfer_bot.start))
    application.add_handler(CallbackQueryHandler(transfer_bot.button_handler))
    
    # بدء البوت
    application.run_polling()

if __name__ == '__main__':
    main()
