import os
import asyncio
import sqlite3
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional
from telethon import TelegramClient, events, Button
from telethon.tl.types import Channel, User, Chat
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

# إعدادات البوت
API_ID = 23656977
API_HASH = "49d3f43531a92b3f5bc403766313ca1e"
BOT_TOKEN = "8137587721:AAGq7kyLc3E0EL7HZ2SKRmJPGj3OLQFVSKo"
WEBHOOK_URL = "https://trans-ygyf.onrender.com"

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class TransferBot:
    def __init__(self):
        self.client = None
        self.user_sessions = {}
        self.transfer_sessions = {}
        self.setup_database()
        
    def setup_database(self):
        """تهيئة قاعدة البيانات SQLite"""
        self.conn = sqlite3.connect('transfer_bot.db', check_same_thread=False)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                session_string TEXT,
                is_authenticated BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                source_chat_id INTEGER,
                source_chat_title TEXT,
                target_chat_id INTEGER,
                target_chat_title TEXT,
                status TEXT DEFAULT 'pending',
                total_members INTEGER DEFAULT 0,
                transferred INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                start_time DATETIME,
                end_time DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    async def start_bot(self):
        """بدء تشغيل البوت"""
        # بدء مهمة الحفاظ على النشاط
        asyncio.create_task(self.keep_alive_task())
        
        self.client = TelegramClient('bot_session', API_ID, API_HASH)
        
        # تعريف الأحداث
        self.client.add_event_handler(self.handle_start, events.NewMessage(pattern='/start'))
        self.client.add_event_handler(self.handle_callback, events.CallbackQuery())
        self.client.add_event_handler(self.handle_message, events.NewMessage())
        
        await self.client.start(bot_token=BOT_TOKEN)
        logger.info("Bot started successfully!")
        
        await self.client.run_until_disconnected()
    
    async def keep_alive_task(self):
        """مهمة دورية للحفاظ على النشاط"""
        while True:
            try:
                response = requests.get(WEBHOOK_URL, timeout=10)
                logger.info(f"Keep-alive ping: {response.status_code}")
            except Exception as e:
                logger.error(f"Keep-alive error: {e}")
            
            await asyncio.sleep(300)  # كل 5 دقائق
    
    async def handle_start(self, event):
        """معالجة أمر /start"""
        buttons = [
            [Button.inline("⚙️ تهيئة النقل", "setup_transfer")],
            [Button.inline("▶️ بدء النقل", "start_transfer")],
            [Button.inline("📊 الإحصائيات", "show_stats")]
        ]
        
        text = """
**مرحباً بك في بوت نقل الأعضاء**

🎯 **المميزات:**
• نقل الأعضاء بين المجموعات والقنوات
• إحصائيات حية أثناء النقل  
• فاصل زمني آمن بين كل عملية نقل (10 دقائق)

🔰 **إبدأ بتهيئة النقل أولاً**
        """
        
        await event.reply(text, buttons=buttons)
    
    async def handle_callback(self, event):
        """معالجة events الـ Callback"""
        data = event.data.decode('utf-8')
        
        if data == "setup_transfer":
            await self.setup_transfer(event)
        elif data == "start_transfer":
            await self.start_transfer(event)
        elif data == "show_stats":
            await self.show_stats(event)
        elif data == "login_user":
            await self.request_login(event)
        elif data == "select_source":
            await self.select_source_chat(event)
        elif data == "select_target":
            await self.select_target_chat(event)
        elif data == "main_menu":
            await self.show_main_menu(event)
        elif data.startswith("source_"):
            await self.save_source_chat(event, data)
        elif data.startswith("target_"):
            await self.save_target_chat(event, data)
        elif data == "cancel_transfer":
            await self.cancel_transfer(event)
    
    async def setup_transfer(self, event):
        """عرض قائمة تهيئة النقل"""
        user_id = event.sender_id
        
        # التحقق من حالة المستخدم
        cursor = self.conn.cursor()
        cursor.execute('SELECT is_authenticated FROM user_sessions WHERE user_id = ?', (user_id,))
        auth_result = cursor.fetchone()
        
        is_authenticated = auth_result[0] if auth_result else False
        
        buttons = []
        if not is_authenticated:
            buttons.append([Button.inline("🔑 تسجيل الدخول", "login_user")])
        else:
            buttons.append([Button.inline("📥 تحديد المصدر", "select_source")])
            buttons.append([Button.inline("📤 تحديد الهدف", "select_target")])
        
        buttons.append([Button.inline("🏠 الرئيسية", "main_menu")])
        
        auth_status = "✅ مسجل الدخول" if is_authenticated else "❌ غير مسجل"
        
        text = f"""
**تهيئة إعدادات النقل**

📊 **حالة التسجيل:** {auth_status}

📋 **الخطوات المطلوبة:**
1. تسجيل الدخول إلى حسابك
2. تحديد المجموعة المصدر  
3. تحديد المجموعة الهدف

⏰ **الفاصل الزمني:** 10 دقائق بين كل عملية نقل
        """
        
        await event.edit(text, buttons=buttons)
    
    async def request_login(self, event):
        """طلب تسجيل الدخول"""
        text = """
**يرجى إرسال رقم هاتفك مع رمز الدولة**

📞 **مثال:** `+201234567890`

🔒 سيتم إنشاء جلسة آمنة لحسابك
        """
        
        await event.edit(text)
        
        user_id = event.sender_id
        if user_id not in self.transfer_sessions:
            self.transfer_sessions[user_id] = {}
        self.transfer_sessions[user_id]['awaiting_phone'] = True
    
    async def handle_message(self, event):
        """معالجة الرسائل النصية"""
        user_id = event.sender_id
        message_text = event.text.strip()
        
        if not message_text.startswith('/'):
            if user_id in self.transfer_sessions:
                session = self.transfer_sessions[user_id]
                
                if session.get('awaiting_phone'):
                    await self.process_phone_input(event, message_text)
                elif session.get('awaiting_code'):
                    await self.process_code_input(event, message_text)
                elif session.get('awaiting_password'):
                    await self.process_password_input(event, message_text)
    
    async def process_phone_input(self, event, phone):
        """معالجة إدخال رقم الهاتف"""
        user_id = event.sender_id
        
        try:
            # تنظيف رقم الهاتف
            phone = phone.strip().replace(' ', '')
            
            if not phone.startswith('+'):
                await event.reply("❌ **يرجى إدخال رقم الهاتف مع رمز الدولة مثل:** `+201234567890`")
                return
            
            # إنشاء عميل جديد للمستخدم
            session_name = f"user_{user_id}"
            user_client = TelegramClient(session_name, API_ID, API_HASH)
            
            await user_client.connect()
            sent_code = await user_client.send_code_request(phone)
            
            # حفظ البيانات
            self.user_sessions[user_id] = {
                'client': user_client,
                'phone': phone,
                'phone_code_hash': sent_code.phone_code_hash
            }
            
            self.transfer_sessions[user_id]['awaiting_phone'] = False
            self.transfer_sessions[user_id]['awaiting_code'] = True
            
            text = """
**تم إرسال رمز التحقق إليك**

🔢 **يرجى إرسال رمز التحقق الذي استلمته**

💡 **ملاحظة:** إذا لم تستلم الرمز، تأكد من صحة رقم الهاتف
            """
            
            await event.reply(text)
            
        except Exception as e:
            await event.reply(f"❌ **خطأ:** `{str(e)}`")
    
    async def process_code_input(self, event, code):
        """معالجة إدخال رمز التحقق"""
        user_id = event.sender_id
        
        try:
            if user_id not in self.user_sessions:
                await event.reply("❌ **لم يتم العثور على جلسة التسجيل، يرجى البدء من جديد**")
                return
            
            user_data = self.user_sessions[user_id]
            client = user_data['client']
            phone = user_data['phone']
            phone_code_hash = user_data['phone_code_hash']
            
            # تنظيف الرمز من المسافات
            code = code.strip().replace(' ', '')
            
            # محاولة تسجيل الدخول
            try:
                result = await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash
                )
                
                # إذا وصلنا هنا، يعني التسجيل ناجح
                await self.handle_successful_login(user_id, client, event)
                
            except SessionPasswordNeededError:
                # طلب كلمة مرور التحقق بخطوتين
                self.transfer_sessions[user_id]['awaiting_code'] = False
                self.transfer_sessions[user_id]['awaiting_password'] = True
                
                text = """
**يتطلب حسابك التحقق بخطوتين**

🔐 **يرجى إرسال كلمة مرور التحقق**

📍 هذه هي كلمة المرور التي قمت بتعيينها لحسابك
                """
                
                await event.reply(text)
                
            except PhoneCodeInvalidError:
                await event.reply("❌ **رمز التحقق غير صحيح، يرجى المحاولة مرة أخرى**")
                
            except Exception as e:
                await event.reply(f"❌ **خطأ في التسجيل:** `{str(e)}`")
            
        except Exception as e:
            await event.reply(f"❌ **خطأ:** `{str(e)}`")
    
    async def process_password_input(self, event, password):
        """معالجة إدخال كلمة المرور"""
        user_id = event.sender_id
        
        try:
            user_data = self.user_sessions[user_id]
            client = user_data['client']
            
            # تسجيل الدخول بكلمة المرور
            await client.sign_in(password=password.strip())
            
            # إذا وصلنا هنا، يعني التسجيل ناجح
            await self.handle_successful_login(user_id, client, event)
            
        except Exception as e:
            await event.reply(f"❌ **خطأ في كلمة المرور:** `{str(e)}`")
    
    async def handle_successful_login(self, user_id, client, event):
        """معالجة تسجيل الدخول الناجح"""
        try:
            # حفظ الجلسة في قاعدة البيانات
            session_string = await client.session.save()
            
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_sessions 
                (user_id, phone, session_string, is_authenticated)
                VALUES (?, ?, ?, ?)
            ''', (user_id, self.user_sessions[user_id]['phone'], session_string, True))
            self.conn.commit()
            
            # تحديث الحالة
            if user_id in self.transfer_sessions:
                self.transfer_sessions[user_id]['awaiting_password'] = False
                self.transfer_sessions[user_id]['authenticated'] = True
            
            text = """
✅ **تم تسجيل الدخول بنجاح**

🎉 يمكنك الآن تحديد المجموعات والبدء في نقل الأعضاء
            """
            
            await event.reply(text)
            await self.show_main_menu(event)
            
        except Exception as e:
            await event.reply(f"❌ **خطأ في حفظ الجلسة:** `{str(e)}`")
    
    async def select_source_chat(self, event):
        """اختيار المجموعة المصدر"""
        user_id = event.sender_id
        
        # التحقق من تسجيل الدخول
        if not await self.check_authentication(event, user_id):
            return
        
        await event.edit("**جاري جلب المجموعات المتاحة...**")
        
        try:
            user_client = self.user_sessions[user_id]['client']
            dialogs = await user_client.get_dialogs()
            
            groups = []
            for dialog in dialogs:
                if dialog.is_channel or dialog.is_group:
                    groups.append(dialog)
            
            if not groups:
                await event.edit("❌ **لم يتم العثور على مجموعات**")
                return
            
            # إنشاء أزرار للمجموعات
            buttons = []
            for group in groups[:8]:
                title = getattr(group.entity, 'title', 'Unknown')[:20]
                buttons.append([Button.inline(f"📥 {title}", f"source_{group.id}")])
            
            buttons.append([Button.inline("🔙 رجوع", "setup_transfer")])
            
            await event.edit("**اختر المجموعة المصدر:**", buttons=buttons)
            
        except Exception as e:
            await event.edit(f"❌ **خطأ:** `{str(e)}`")
    
    async def save_source_chat(self, event, data):
        """حفظ المجموعة المصدر المختارة"""
        user_id = event.sender_id
        
        try:
            chat_id = int(data.split('_')[1])
            user_client = self.user_sessions[user_id]['client']
            chat = await user_client.get_entity(chat_id)
            chat_title = getattr(chat, 'title', 'Unknown')
            
            # حفظ في قاعدة البيانات
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO transfers 
                (user_id, source_chat_id, source_chat_title, status)
                VALUES (?, ?, ?, 'pending')
            ''', (user_id, chat_id, chat_title))
            self.conn.commit()
            
            await event.edit(f"✅ **تم تحديد المصدر:** `{chat_title}`")
            await asyncio.sleep(2)
            await self.setup_transfer(event)
            
        except Exception as e:
            await event.edit(f"❌ **خطأ:** `{str(e)}`")
    
    async def select_target_chat(self, event):
        """اختيار المجموعة الهدف"""
        user_id = event.sender_id
        
        if not await self.check_authentication(event, user_id):
            return
        
        await event.edit("**جاري جلب المجموعات المتاحة...**")
        
        try:
            user_client = self.user_sessions[user_id]['client']
            dialogs = await user_client.get_dialogs()
            
            groups = []
            for dialog in dialogs:
                if dialog.is_channel or dialog.is_group:
                    groups.append(dialog)
            
            if not groups:
                await event.edit("❌ **لم يتم العثور على مجموعات**")
                return
            
            buttons = []
            for group in groups[:8]:
                title = getattr(group.entity, 'title', 'Unknown')[:20]
                buttons.append([Button.inline(f"📤 {title}", f"target_{group.id}")])
            
            buttons.append([Button.inline("🔙 رجوع", "setup_transfer")])
            
            await event.edit("**اختر المجموعة الهدف:**", buttons=buttons)
            
        except Exception as e:
            await event.edit(f"❌ **خطأ:** `{str(e)}`")
    
    async def save_target_chat(self, event, data):
        """حفظ المجموعة الهدف المختارة"""
        user_id = event.sender_id
        
        try:
            chat_id = int(data.split('_')[1])
            user_client = self.user_sessions[user_id]['client']
            chat = await user_client.get_entity(chat_id)
            chat_title = getattr(chat, 'title', 'Unknown')
            
            # تحديث قاعدة البيانات
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE transfers 
                SET target_chat_id = ?, target_chat_title = ?
                WHERE user_id = ? AND status = 'pending'
            ''', (chat_id, chat_title, user_id))
            self.conn.commit()
            
            await event.edit(f"✅ **تم تحديد الهدف:** `{chat_title}`")
            await asyncio.sleep(2)
            await self.setup_transfer(event)
            
        except Exception as e:
            await event.edit(f"❌ **خطأ:** `{str(e)}`")
    
    async def start_transfer(self, event):
        """بدء عملية النقل"""
        user_id = event.sender_id
        
        # التحقق من التهيئة
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT us.is_authenticated, t.source_chat_id, t.target_chat_id
            FROM user_sessions us
            LEFT JOIN transfers t ON us.user_id = t.user_id AND t.status = 'pending'
            WHERE us.user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        
        if not result or not result[0]:
            await event.edit("❌ **يجب تسجيل الدخول أولاً**")
            return
        
        if not result[1] or not result[2]:
            await event.edit("❌ **يجب تحديد المصدر والهدف أولاً**")
            return
        
        buttons = [[Button.inline("❌ إلغاء النقل", "cancel_transfer")]]
        
        await event.edit(
            "**جاري بدء عملية النقل...**\n\n⏳ سيبدأ النقل خلال ثواني",
            buttons=buttons
        )
        
        # بدء النقل في الخلفية
        asyncio.create_task(self.transfer_members(user_id, event))
    
    async def transfer_members(self, user_id, event):
        """عملية نقل الأعضاء"""
        try:
            user_client = self.user_sessions[user_id]['client']
            
            # الحصول على بيانات النقل
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT source_chat_id, target_chat_id, source_chat_title, target_chat_title
                FROM transfers 
                WHERE user_id = ? AND status = 'pending'
            ''', (user_id,))
            transfer_data = cursor.fetchone()
            
            source_id = transfer_data[0]
            target_id = transfer_data[1]
            source_title = transfer_data[2]
            target_title = transfer_data[3]
            
            # جلب الأعضاء
            participants = await user_client.get_participants(source_id)
            total_members = len([p for p in participants if isinstance(p, User) and not p.bot])
            
            # تحديث قاعدة البيانات
            cursor.execute('''
                UPDATE transfers 
                SET status = 'active', total_members = ?, start_time = datetime('now')
                WHERE user_id = ?
            ''', (total_members, user_id))
            self.conn.commit()
            
            transferred = 0
            failed = 0
            
            # عملية النقل
            for participant in participants:
                if isinstance(participant, User) and not participant.bot:
                    try:
                        # التحقق من حالة النقل
                        cursor.execute('SELECT status FROM transfers WHERE user_id = ?', (user_id,))
                        status_result = cursor.fetchone()
                        if status_result and status_result[0] == 'cancelled':
                            break
                            
                        await user_client(InviteToChannelRequest(
                            channel=target_id,
                            users=[participant]
                        ))
                        transferred += 1
                        
                        # تحديث الإحصائيات
                        cursor.execute('''
                            UPDATE transfers 
                            SET transferred = ?, failed = ?
                            WHERE user_id = ?
                        ''', (transferred, failed, user_id))
                        self.conn.commit()
                        
                        # تحديث الرسالة كل 3 عمليات نقل
                        if transferred % 3 == 0:
                            buttons = [[Button.inline("❌ إلغاء النقل", "cancel_transfer")]]
                            
                            text = f"""
**جاري نقل الأعضاء...**

📤 **المصدر:** `{source_title}`
📥 **الهدف:** `{target_title}`

📊 **الإحصائيات:**
• ✅ تم نقل: `{transferred}`
• ❌ فشل: `{failed}`
• 📊 المتبقي: `{total_members - transferred}`
• ⏰ الوقت: `{datetime.now().strftime('%H:%M:%S')}`
                            """
                            
                            await event.edit(text, buttons=buttons)
                        
                        # انتظار 10 دقائق
                        await asyncio.sleep(600)
                        
                    except Exception as e:
                        failed += 1
                        logger.error(f"Failed to transfer user: {e}")
            
            # إنهاء النقل
            final_status = 'cancelled' if failed > transferred else 'completed'
            cursor.execute('''
                UPDATE transfers 
                SET status = ?, end_time = datetime('now')
                WHERE user_id = ?
            ''', (final_status, user_id))
            self.conn.commit()
            
            text = f"""
✅ **اكتملت عملية النقل**

🎯 **النتائج النهائية:**
• ✅ تم نقل: `{transferred}`
• ❌ فشل: `{failed}`
• ⏰ وقت الانتهاء: `{datetime.now().strftime('%Y-%m-%d %H:%M')}`
            """
            
            await event.edit(text)
            
        except Exception as e:
            logger.error(f"Transfer process failed: {e}")
            await event.edit(f"❌ **فشلت عملية النقل:** `{str(e)}`")
    
    async def cancel_transfer(self, event):
        """إلغاء عملية النقل"""
        user_id = event.sender_id
        
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE transfers 
            SET status = 'cancelled', end_time = datetime('now')
            WHERE user_id = ? AND status = 'active'
        ''', (user_id,))
        self.conn.commit()
        
        await event.edit("❌ **تم إلغاء عملية النقل**")
    
    async def show_stats(self, event):
        """عرض الإحصائيات"""
        user_id = event.sender_id
        
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT status, total_members, transferred, failed, start_time
            FROM transfers 
            WHERE user_id = ? 
            ORDER BY id DESC 
            LIMIT 1
        ''', (user_id,))
        stats = cursor.fetchone()
        
        if not stats:
            text = "**لا توجد إحصائيات متاحة**"
        else:
            text = f"""
📊 **الإحصائيات الأخيرة**

📈 **حالة النقل:** `{stats[0]}`
👥 **إجمالي الأعضاء:** `{stats[1] or 0}`
✅ **تم نقلهم:** `{stats[2] or 0}`
❌ **الفاشل:** `{stats[3] or 0}`
⏰ **وقت البدء:** `{stats[4] or 'غير محدد'}`
            """
        
        buttons = [[Button.inline("🏠 الرئيسية", "main_menu")]]
        await event.edit(text, buttons=buttons)
    
    async def show_main_menu(self, event):
        """عرض القائمة الرئيسية"""
        buttons = [
            [Button.inline("⚙️ تهيئة النقل", "setup_transfer")],
            [Button.inline("▶️ بدء النقل", "start_transfer")],
            [Button.inline("📊 الإحصائيات", "show_stats")]
        ]
        
        await event.edit("**القائمة الرئيسية**", buttons=buttons)
    
    async def check_authentication(self, event, user_id):
        """التحقق من تسجيل الدخول"""
        if user_id not in self.user_sessions:
            await event.edit("❌ **يجب تسجيل الدخول أولاً**")
            return False
        
        cursor = self.conn.cursor()
        cursor.execute('SELECT is_authenticated FROM user_sessions WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if not result or not result[0]:
            await event.edit("❌ **يجب تسجيل الدخول أولاً**")
            return False
            
        return True

async def main():
    """الدالة الرئيسية"""
    bot = TransferBot()
    await bot.start_bot()

if __name__ == '__main__':
    asyncio.run(main())
