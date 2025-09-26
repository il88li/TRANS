import asyncio
import logging
from telethon import TelegramClient, events, Button
from telethon.tl.types import Channel, User, UserStatusEmpty
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact
from telethon.sessions import StringSession
import sqlite3
import re

# إيقاف التسجيل المفصل
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# إعدادات API
API_ID = 23656977
API_HASH = '49d3f43531a92b3f5bc403766313ca1e'
BOT_TOKEN = '8427666066:AAGmHgzfoskdMf8d7pf3Vrs7b6R1VVB_jlY'

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
                 failed INTEGER, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_sessions
                 (user_id INTEGER PRIMARY KEY, session_string TEXT)''')
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

def update_progress(user_id, total_members=None, processed=None, failed=None, status=None):
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
        values.append(user_id)
        c.execute(f"UPDATE progress SET {','.join(updates)} WHERE user_id=?", values)
    else:
        c.execute("INSERT INTO progress (user_id, total_members, processed, failed, status) VALUES (?,?,?,?,?)",
                  (user_id, total_members or 0, processed or 0, failed or 0, status or 'idle'))
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

# دوال المساعدة
async def is_group_or_channel(entity):
    return isinstance(entity, Channel)

async def is_deleted_account(user):
    return isinstance(user.status, UserStatusEmpty) or getattr(user, 'deleted', False)

async def is_bot(user):
    return getattr(user, 'bot', False)

async def save_contact(user, user_client):
    try:
        if getattr(user, 'phone', None):
            contact = InputPhoneContact(
                client_id=user.id,
                phone=user.phone,
                first_name=user.first_name or '',
                last_name=user.last_name or ''
            )
            await user_client(ImportContactsRequest([contact]))
            return True
    except Exception:
        return False

async def add_to_group(user_id, target_entity, user_client):
    try:
        await user_client.edit_permissions(target_entity, user_id, view_messages=True)
        return True
    except Exception:
        return False

# قاموس لتخزين حالات المستخدمين
user_states = {}

# معالجة الأحداث
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    # مسح أي حالة سابقة
    if user_id in user_states:
        del user_states[user_id]
        
    buttons = [
        [Button.inline("🚀 بدء العملية", b"start_process")],
        [Button.inline("⚙️ المزيد", b"more_options")]
    ]
    await event.reply(
        "**مرحباً بك في بوت نقل الأعضاء**\n\n"
        "• استخدم زر 'بدء العملية' لبدء نقل الأعضاء\n"
        "• زر 'المزيد' للإعدادات وتسجيل الدخول",
        buttons=buttons
    )

@client.on(events.CallbackQuery(data=b"start_process"))
async def start_process_handler(event):
    user_id = event.sender_id
    settings = get_user_settings(user_id)
    
    if not settings or not settings[1] or not settings[2]:
        await event.edit("⚠️ يرجى تعيين المجموعة المصدر والهدف أولاً من خلال قائمة 'المزيد'")
        return
    
    user_session = get_user_session(user_id)
    if not user_session:
        await event.edit("⚠️ يرجى تسجيل الدخول إلى حسابك أولاً من خلال قائمة 'المزيد'")
        return
    
    await event.edit("🔄 جاري بدء عملية نقل الأعضاء...")
    await transfer_members(user_id, event)

@client.on(events.CallbackQuery(data=b"more_options"))
async def more_options_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    login_status = "✅ مسجل الدخول" if user_session else "❌ غير مسجل"
    
    buttons = [
        [Button.inline("📥 تعيين المصدر", b"set_source")],
        [Button.inline("📤 تعيين الهدف", b"set_target")],
        [Button.inline("🔐 تسجيل الدخول", b"user_login")],
        [Button.inline(f"حالة التسجيل: {login_status}", b"login_status")],
        [Button.inline("⏱ إعدادات التوقيت", b"timing_settings")],
        [Button.inline("📊 حالة التقدم", b"progress_status")],
        [Button.inline("🔄 إعادة تعيين", b"reset_settings")],
        [Button.inline("🔙 رجوع", b"back_main")]
    ]
    await event.edit("**الإعدادات المتقدمة:**", buttons=buttons)

@client.on(events.CallbackQuery(data=b"user_login"))
async def user_login_handler(event):
    user_id = event.sender_id
    user_states[user_id] = {'step': 'awaiting_phone'}
    await event.edit("🔐 **تسجيل الدخول إلى حسابك**\n\nأرسل رقم هاتفك مع رمز الدولة (مثال: +967733091200):")

@client.on(events.NewMessage)
async def handle_login_messages(event):
    user_id = event.sender_id
    message_text = event.text.strip()
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get('step') == 'awaiting_phone':
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
            user_states[user_id] = {'step': 'awaiting_phone'}
    
    elif state.get('step') == 'awaiting_code':
        # تنظيف رمز التحقق
        code = re.sub(r'[^\d]', '', message_text)
        
        if len(code) != 5:
            await event.reply("❌ رمز التحقق يجب أن يكون 5 أرقام. يرجى إعادة الإدخال:")
            return
        
        try:
            user_client = state['client']
            phone = state['phone']
            phone_code_hash = state['phone_code_hash']
            
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

@client.on(events.CallbackQuery(data=b"login_status"))
async def login_status_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    
    if user_session:
        status_text = "✅ **حسابك مسجل بنجاح**\n\nيمكنك الآن استخدام ميزات نقل الأعضاء."
    else:
        status_text = "❌ **لم تقم بتسجيل الدخول بعد**\n\nيرجى استخدام زر 'تسجيل الدخول' لإضافة حسابك."
    
    await event.edit(status_text, buttons=[[Button.inline("🔙 رجوع", b"more_options")]])

@client.on(events.CallbackQuery(data=b"set_source"))
async def set_source_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    if not user_session:
        await event.edit("⚠️ يرجى تسجيل الدخول أولاً لتتمكن من تعيين المجموعات")
        return
        
    user_states[user_id] = {'step': 'awaiting_source'}
    await event.edit("📥 أرسل معرف المجموعة/القناة المصدر (يجب أن تكون مشرفاً فيها):")

@client.on(events.CallbackQuery(data=b"set_target"))
async def set_target_handler(event):
    user_id = event.sender_id
    user_session = get_user_session(user_id)
    if not user_session:
        await event.edit("⚠️ يرجى تسجيل الدخول أولاً لتتمكن من تعيين المجموعات")
        return
        
    user_states[user_id] = {'step': 'awaiting_target'}
    await event.edit("📤 أرسل معرف المجموعة/القناة الهدف (يجب أن تكون مشرفاً فيها):")

@client.on(events.NewMessage)
async def handle_group_setting(event):
    user_id = event.sender_id
    message_text = event.text.strip()
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get('step') in ['awaiting_source', 'awaiting_target']:
        try:
            user_session_str = get_user_session(user_id)
            user_client = TelegramClient(StringSession(user_session_str), API_ID, API_HASH)
            await user_client.connect()
            
            entity = await user_client.get_entity(message_text)
            
            if await is_group_or_channel(entity):
                try:
                    me = await user_client.get_me()
                    participant = await user_client.get_permissions(entity, me)
                    if participant.is_admin:
                        if state['step'] == 'awaiting_source':
                            update_user_settings(user_id, source_group=message_text)
                            await event.reply(f"✅ تم تعيين المصدر: {entity.title}")
                        else:
                            update_user_settings(user_id, target_group=message_text)
                            await event.reply(f"✅ تم تعيين الهدف: {entity.title}")
                    else:
                        await event.reply("❌ يجب أن تكون مشرفاً في هذه المجموعة")
                except Exception as e:
                    await event.reply("❌ لا يمكن الوصول إلى المجموعة أو لا تملك الصلاحيات الكافية")
            else:
                await event.reply("❌ الرجاء إدخال مجموعة أو قناة صحيحة")
                
            await user_client.disconnect()
            
        except Exception as e:
            await event.reply(f"❌ خطأ في التعرف على المجموعة/القناة: يرجى التأكد من المعرف والمحاولة مرة أخرى")
        
        # تنظيف الحالة
        del user_states[user_id]

@client.on(events.CallbackQuery(data=b"timing_settings"))
async def timing_settings_handler(event):
    user_id = event.sender_id
    settings = get_user_settings(user_id)
    current_delay = settings[3] if settings else 86.0
    current_limit = settings[4] if settings else 1000
    
    buttons = [
        [Button.inline(f"⏱ التأخير: {current_delay} ثانية", b"no_action")],
        [Button.inline(f"📊 الحد اليومي: {current_limit} عضو", b"no_action")],
        [Button.inline("🔙 رجوع", b"more_options")]
    ]
    await event.edit("**إعدادات التوقيت:**\n\nالتأخير الافتراضي 86 ثانية يسمح بإضافة 1000 عضو خلال 24 ساعة", buttons=buttons)

@client.on(events.CallbackQuery(data=b"progress_status"))
async def progress_status_handler(event):
    user_id = event.sender_id
    progress = get_progress(user_id)
    
    if progress:
        status_text = f"""
**📊 حالة التقدم:**

• العدد الكلي: {progress[1]}
• المنقولون: {progress[2]}
• الفاشلون: {progress[3]}
• الحالة: {progress[4]}
        """
    else:
        status_text = "❌ لا توجد عملية نشطة"
    
    await event.edit(status_text, buttons=[[Button.inline("🔙 رجوع", b"more_options")]])

@client.on(events.CallbackQuery(data=b"reset_settings"))
async def reset_settings_handler(event):
    user_id = event.sender_id
    conn = sqlite3.connect('transfer_bot.db')
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM progress WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    await event.edit("✅ تم إعادة تعيين جميع الإعدادات", buttons=[[Button.inline("🔙 رجوع", b"more_options")]])

@client.on(events.CallbackQuery(data=b"back_main"))
async def back_main_handler(event):
    user_id = event.sender_id
    # مسح أي حالة سابقة
    if user_id in user_states:
        del user_states[user_id]
        
    buttons = [
        [Button.inline("🚀 بدء العملية", b"start_process")],
        [Button.inline("⚙️ المزيد", b"more_options")]
    ]
    await event.edit("**مرحباً بك في بوت نقل الأعضاء**", buttons=buttons)

@client.on(events.CallbackQuery(data=b"no_action"))
async def no_action_handler(event):
    await event.answer("لا يوجد إجراء لهذا الزر", alert=False)

# الدالة الرئيسية لنقل الأعضاء
async def transfer_members(user_id, event):
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
            members = await user_client.get_participants(source_entity, limit=50)  # تجنب الكثير في البداية
            
            # تصفية الأعضاء
            valid_members = []
            for member in members:
                if isinstance(member, User) and not await is_deleted_account(member) and not await is_bot(member):
                    valid_members.append(member)
            
            total_members = len(valid_members)
            if total_members == 0:
                await event.edit("❌ لم يتم العثور على أعضاء صالحين للنقل")
                return
            
            update_progress(user_id, total_members=total_members, processed=0, failed=0, status='جاري الحفظ')
            
            await event.edit(f"🔍 تم العثور على {total_members} عضو صالح\n💾 جاري حفظ الجهات...")
            
            # حفظ الجهات
            saved_contacts = 0
            for i, member in enumerate(valid_members):
                if await save_contact(member, user_client):
                    saved_contacts += 1
                update_progress(user_id, processed=i+1, status='جاري الحفظ')
                
                if i % 10 == 0:
                    await event.edit(f"💾 جاري حفظ الجهات... {i+1}/{total_members}")
                
                await asyncio.sleep(1)
            
            await event.edit(f"✅ تم حفظ {saved_contacts} جهة\n🚀 بدء عملية الإضافة...")
            
            # عملية الإضافة
            update_progress(user_id, processed=0, failed=0, status='جاري الإضافة')
            added_count = 0
            failed_count = 0
            
            for i, member in enumerate(valid_members):
                if added_count >= daily_limit:
                    await event.edit(f"⏸ تم الوصول إلى الحد اليومي ({daily_limit})")
                    break
                
                if await add_to_group(member.id, target_entity, user_client):
                    added_count += 1
                else:
                    failed_count += 1
                
                update_progress(user_id, processed=i+1, failed=failed_count, status='جاري الإضافة')
                
                if i % 5 == 0:
                    progress_msg = f"""
📊 تقدم الإضافة:
• المضافة: {added_count}
• الفاشلة: {failed_count}
• المتبقية: {total_members - i - 1}
                    """
                    await event.edit(progress_msg)
                
                await asyncio.sleep(delay)
            
            # النتيجة النهائية
            update_progress(user_id, status='مكتمل')
            result_msg = f"""
✅ **تم الانتهاء من عملية النقل**

• العدد الكلي: {total_members}
• المضافة بنجاح: {added_count}
• الفاشلة: {failed_count}
• المحفوظة: {saved_contacts}
            """
            await event.edit(result_msg)
            
        except Exception as e:
            await event.edit(f"❌ خطأ أثناء عملية النقل: {str(e)}")
        finally:
            await user_client.disconnect()
            
    except Exception as e:
        await event.edit(f"❌ خطأ عام: {str(e)}")

# تشغيل البوت
async def main():
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot is running successfully...")
    print("✅ API_ID:", API_ID)
    print("✅ API_HASH:", API_HASH)
    print("✅ BOT_TOKEN:", BOT_TOKEN)
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
