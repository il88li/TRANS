import os
import json
import asyncio
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
import aiohttp
from aiohttp import web
import logging
import nest_asyncio
from datetime import datetime

# تطبيق nest_asyncio لحل مشكلة event loop
nest_asyncio.apply()

# إعدادات التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# بيانات البوت - التوكن الجديد
API_ID = 23656977
API_HASH = '49d3f43531a92b3f5bc403766313ca1e'
BOT_TOKEN = '8052900952:AAEmgVIJ2igX3fA5KAXs06xtZ5OeQjIXMjk'

# رابط الويب هووك
WEBHOOK_URL = 'https://trans-2-77.onrender.com'

# إنشاء المجلدات للتخزين
os.makedirs('sessions', exist_ok=True)
os.makedirs('data', exist_ok=True)

# ملفات التخزين
ACCOUNTS_FILE = 'data/accounts.json'
SETTINGS_FILE = 'data/settings.json'

# تهيئة ملفات التخزين
def init_files():
    if not os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)

init_files()

# تحميل وحفظ البيانات
def load_accounts():
    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_accounts(accounts):
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def load_settings():
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

# إنشاء عميل البوت
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# قاموس لتخزين حالات المستخدمين
user_states = {}
account_creation = {}

# زر البداية
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    user_states[user_id] = 'main'
    
    buttons = [
        [Button.inline("بدء العملية", "start_process")],
        [Button.inline("الحسابات", "manage_accounts")],
        [Button.inline("إعدادات", "settings")],
        [Button.inline("المطور", "developer")]
    ]
    
    await event.reply(
        "مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات\n\n"
        "اختر أحد الخيارات:",
        buttons=buttons
    )

# معالجة الأزرار
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    try:
        if data == 'start_process':
            await start_process(event)
        elif data == 'manage_accounts':
            await manage_accounts(event)
        elif data == 'settings':
            await settings_menu(event)
        elif data == 'developer':
            await developer_info(event)
        elif data == 'back_to_main':
            await back_to_main(event)
        elif data == 'add_account':
            await add_account_handler(event)
        elif data.startswith('delete_account_'):
            account_id = data.split('_')[2]
            await delete_account(event, account_id)
        elif data == 'set_source':
            await set_source_handler(event)
        elif data == 'set_target':
            await set_target_handler(event)
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await event.answer("❌ حدث خطأ في المعالجة", alert=True)

async def back_to_main(event):
    user_id = event.sender_id
    user_states[user_id] = 'main'
    
    buttons = [
        [Button.inline("بدء العملية", "start_process")],
        [Button.inline("الحسابات", "manage_accounts")],
        [Button.inline("إعدادات", "settings")],
        [Button.inline("المطور", "developer")]
    ]
    
    await event.edit(
        "مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات\n\n"
        "اختر أحد الخيارات:",
        buttons=buttons
    )

async def start_process(event):
    user_id = event.sender_id
    accounts = load_accounts().get(str(user_id), [])
    settings = load_settings().get(str(user_id), {})
    
    if len(accounts) == 0:
        await event.answer("❌ يجب إضافة حسابات أولاً!", alert=True)
        return
    
    if not settings.get('source') or not settings.get('target'):
        await event.answer("❌ يجب تعيين المصدر والهدف أولاً!", alert=True)
        return
    
    await event.edit("🚀 بدء عملية نقل الأعضاء...")
    
    # عملية نقل الأعضاء
    success_count = 0
    failed_count = 0
    
    for account_index, account in enumerate(accounts):
        try:
            await event.edit(f"🔄 جاري معالجة الحساب {account_index + 1} من {len(accounts)}...")
            
            session_name = f"sessions/{user_id}_{account['phone']}"
            client = TelegramClient(session_name, API_ID, API_HASH)
            
            await client.start(phone=account['phone'])
            
            # الحصول على أعضاء المصدر
            try:
                source_entity = await client.get_entity(settings['source'])
                participants = await client.get_participants(source_entity, limit=20)  # زيادة الحد
                logger.info(f"تم جلب {len(participants)} عضو من المصدر")
            except Exception as e:
                logger.error(f"Error getting participants from source: {e}")
                await event.edit(f"❌ خطأ في جلب الأعضاء من المصدر: {e}")
                await client.disconnect()
                continue
            
            # دعوة الأعضاء إلى الهدف
            try:
                target_entity = await client.get_entity(settings['target'])
            except Exception as e:
                logger.error(f"Error getting target entity: {e}")
                await event.edit(f"❌ خطأ في الوصول إلى الهدف: {e}")
                await client.disconnect()
                continue
            
            for participant_index, participant in enumerate(participants):
                try:
                    if not participant.bot and not participant.is_self:  # تجنب البوتات والحساب نفسه
                        # التحقق مما إذا كان العضو موجوداً بالفعل في الهدف
                        try:
                            target_participants = await client.get_participants(target_entity, limit=100)
                            existing_members = [p.id for p in target_participants]
                            
                            if participant.id in existing_members:
                                logger.info(f"العضو {participant.id} موجود بالفعل في الهدف")
                                continue
                        except:
                            pass
                        
                        # دعوة العضو
                        await client(InviteToChannelRequest(target_entity, [participant]))
                        success_count += 1
                        logger.info(f"تم دعوة العضو {participant.id} بنجاح")
                        
                        await event.edit(
                            f"🔄 جاري معالجة الحساب {account_index + 1} من {len(accounts)}\n"
                            f"✅ تم نقل {success_count} عضو\n"
                            f"❌ فشل {failed_count} عضو\n"
                            f"📊 العضو {participant_index + 1} من {len(participants)}"
                        )
                        
                        # تأخير 10 دقائق بين كل عملية نقل
                        await asyncio.sleep(600)
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error inviting {participant.id}: {e}")
                    await asyncio.sleep(30)  # تأخير أقل في حالة الخطأ
            
            await client.disconnect()
            
            # تأخير بين الحسابات
            if account_index < len(accounts) - 1:
                await event.edit(f"⏳ انتظار 10 دقائق قبل الانتقال للحساب التالي...")
                await asyncio.sleep(600)
            
        except Exception as e:
            logger.error(f"Error with account {account['phone']}: {e}")
            failed_count += 1
            await asyncio.sleep(30)
    
    await event.edit(
        f"✅ تم الانتهاء من عملية النقل!\n\n"
        f"✅ الأعضاء المنقولون بنجاح: {success_count}\n"
        f"❌ الفاشلين: {failed_count}\n"
        f"🕒 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

async def manage_accounts(event):
    user_id = event.sender_id
    accounts = load_accounts().get(str(user_id), [])
    
    buttons = []
    for i, account in enumerate(accounts):
        buttons.append([Button.inline(f"❌ {account['phone']}", f"delete_account_{i}")])
    
    buttons.append([Button.inline("➕ إضافة حساب", "add_account")])
    buttons.append([Button.inline("🔙 رجوع", "back_to_main")])
    
    text = f"📱 الحسابات المسجلة ({len(accounts)}/10):\n\n"
    for account in accounts:
        text += f"📞 {account['phone']}\n"
    
    await event.edit(text, buttons=buttons)

async def add_account_handler(event):
    user_id = event.sender_id
    user_states[user_id] = 'awaiting_phone'
    account_creation[user_id] = {}
    
    await event.edit(
        "📱 إضافة حساب جديد\n\n"
        "أرسل رقم الهاتف (مع رمز الدولة):\n"
        "مثال: +201234567890\n\n"
        "لإلغاء العملية، اكتب /cancel"
    )

async def delete_account(event, account_index):
    user_id = event.sender_id
    accounts = load_accounts().get(str(user_id), [])
    
    if int(account_index) < len(accounts):
        deleted_account = accounts.pop(int(account_index))
        save_accounts({**load_accounts(), str(user_id): accounts})
        
        # حذف ملف الجلسة
        session_file = f"sessions/{user_id}_{deleted_account['phone']}.session"
        if os.path.exists(session_file):
            os.remove(session_file)
        
        await event.answer(f"✅ تم حذف الحساب {deleted_account['phone']}", alert=True)
        await manage_accounts(event)

async def settings_menu(event):
    user_id = event.sender_id
    settings = load_settings().get(str(user_id), {})
    
    source = settings.get('source', 'لم يتم التعيين')
    target = settings.get('target', 'لم يتم التعيين')
    
    buttons = [
        [Button.inline("📥 تعيين المصدر", "set_source")],
        [Button.inline("📤 تعيين الهدف", "set_target")],
        [Button.inline("🔙 رجوع", "back_to_main")]
    ]
    
    await event.edit(
        f"⚙️ إعدادات النقل:\n\n"
        f"📥 المصدر: {source}\n"
        f"📤 الهدف: {target}\n\n"
        "اختر الإعداد الذي تريد تعديله:",
        buttons=buttons
    )

async def set_source_handler(event):
    user_id = event.sender_id
    user_states[user_id] = 'awaiting_source'
    
    await event.edit(
        "📥 إعداد المصدر\n\n"
        "أرسل رابط أو معرف المجموعة/القناة المصدر:\n\n"
        "ملاحظة: يجب أن تكون الحسابات مشتركة في المصدر\n\n"
        "لإلغاء العملية، اكتب /cancel"
    )

async def set_target_handler(event):
    user_id = event.sender_id
    user_states[user_id] = 'awaiting_target'
    
    await event.edit(
        "📤 إعداد الهدف\n\n"
        "أرسل رابط أو معرف المجموعة/القناة الهدف:\n\n"
        "ملاحظة: يجب أن تكون الحسابات مشتركة في الهدف ولديها صلاحية الدعوة\n\n"
        "لإلغاء العملية، اكتب /cancel"
    )

async def developer_info(event):
    buttons = [
        [Button.url("تواصل مع المطور", "https://t.me/OlIiIl7")],
        [Button.inline("🔙 رجوع", "back_to_main")]
    ]
    
    await event.edit(
        "👨‍💻 معلومات المطور:\n\n"
        "اسم المستخدم: @OlIiIl7\n"
        "لأي استفسارات أو مشاكل تقنية، تواصل مع المطور",
        buttons=buttons
    )

# معالجة الرسائل النصية
@bot.on(events.NewMessage)
async def message_handler(event):
    user_id = event.sender_id
    text = event.text
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if text == '/cancel':
        user_states[user_id] = 'main'
        await event.reply("تم إلغاء العملية")
        await back_to_main_by_message(event)
        return
    
    if state == 'awaiting_phone':
        await handle_phone_input(event, text)
    elif state == 'awaiting_code':
        await handle_code_input(event, text)
    elif state == 'awaiting_password':
        await handle_password_input(event, text)
    elif state == 'awaiting_source':
        await handle_source_input(event, text)
    elif state == 'awaiting_target':
        await handle_target_input(event, text)

async def handle_phone_input(event, phone):
    user_id = event.sender_id
    
    if not phone.startswith('+'):
        await event.reply("❌ رقم الهاتف يجب أن يبدأ بـ + ويحتوي على رمز الدولة")
        return
    
    account_creation[user_id]['phone'] = phone
    
    try:
        session_name = f"sessions/{user_id}_{phone}"
        client = TelegramClient(session_name, API_ID, API_HASH)
        await client.connect()
        
        sent_code = await client.send_code_request(phone)
        account_creation[user_id]['client'] = client
        account_creation[user_id]['phone_code_hash'] = sent_code.phone_code_hash
        
        user_states[user_id] = 'awaiting_code'
        await event.reply("📲 تم إرسال رمز التحقق إلى حسابك\n\nأرسل رمز التحقق:")
        
    except Exception as e:
        logger.error(f"Error sending code: {e}")
        await event.reply("❌ حدث خطأ في إرسال رمز التحقق. تأكد من رقم الهاتف وحاول مرة أخرى")

async def handle_code_input(event, code):
    user_id = event.sender_id
    account_data = account_creation.get(user_id, {})
    
    if not account_data:
        await event.reply("❌ لم يتم العثور على بيانات الحساب. ابدأ من جديد")
        user_states[user_id] = 'main'
        return
    
    try:
        client = account_data['client']
        phone = account_data['phone']
        phone_code_hash = account_data['phone_code_hash']
        
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        
        # حفظ الحساب
        accounts = load_accounts()
        user_accounts = accounts.get(str(user_id), [])
        
        if len(user_accounts) >= 10:
            await event.reply("❌ لقد وصلت إلى الحد الأقصى لعدد الحسابات (10)")
            await client.disconnect()
            return
        
        user_accounts.append({'phone': phone})
        accounts[str(user_id)] = user_accounts
        save_accounts(accounts)
        
        user_states[user_id] = 'main'
        await event.reply("✅ تم إضافة الحساب بنجاح!")
        await client.disconnect()
        
    except SessionPasswordNeededError:
        user_states[user_id] = 'awaiting_password'
        await event.reply("🔐 هذا الحساب محمي بكلمة مرور\n\nأرسل كلمة المرور:")
    
    except PhoneCodeInvalidError:
        await event.reply("❌ رمز التحقق غير صحيح. حاول مرة أخرى:")
    
    except Exception as e:
        logger.error(f"Error signing in: {e}")
        await event.reply("❌ حدث خطأ في تسجيل الدخول. حاول مرة أخرى")

async def handle_password_input(event, password):
    user_id = event.sender_id
    account_data = account_creation.get(user_id, {})
    
    try:
        client = account_data['client']
        await client.sign_in(password=password)
        
        # حفظ الحساب
        accounts = load_accounts()
        user_accounts = accounts.get(str(user_id), [])
        user_accounts.append({'phone': account_data['phone']})
        accounts[str(user_id)] = user_accounts
        save_accounts(accounts)
        
        user_states[user_id] = 'main'
        await event.reply("✅ تم إضافة الحساب بنجاح!")
        await client.disconnect()
        
    except Exception as e:
        logger.error(f"Error with password: {e}")
        await event.reply("❌ كلمة المرور غير صحيحة. حاول مرة أخرى:")

async def handle_source_input(event, source):
    user_id = event.sender_id
    
    try:
        entity = await bot.get_entity(source)
        
        settings = load_settings()
        user_settings = settings.get(str(user_id), {})
        user_settings['source'] = source
        settings[str(user_id)] = user_settings
        save_settings(settings)
        
        user_states[user_id] = 'main'
        await event.reply(f"✅ تم تعيين المصدر: {source}")
        
    except Exception as e:
        logger.error(f"Error setting source: {e}")
        await event.reply("❌ لا يمكن الوصول إلى المصدر. تأكد من الرابط وأن البوت مشترك في القناة/المجموعة")

async def handle_target_input(event, target):
    user_id = event.sender_id
    
    try:
        entity = await bot.get_entity(target)
        
        settings = load_settings()
        user_settings = settings.get(str(user_id), {})
        user_settings['target'] = target
        settings[str(user_id)] = user_settings
        save_settings(settings)
        
        user_states[user_id] = 'main'
        await event.reply(f"✅ تم تعيين الهدف: {target}")
        
    except Exception as e:
        logger.error(f"Error setting target: {e}")
        await event.reply("❌ لا يمكن الوصول إلى الهدف. تأكد من الرابط وأن البوت مشترك في القناة/المجموعة")

async def back_to_main_by_message(event):
    user_id = event.sender_id
    user_states[user_id] = 'main'
    
    buttons = [
        [Button.inline("بدء العملية", "start_process")],
        [Button.inline("الحسابات", "manage_accounts")],
        [Button.inline("إعدادات", "settings")],
        [Button.inline("المطور", "developer")]
    ]
    
    await event.reply(
        "مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات\n\n"
        "اختر أحد الخيارات:",
        buttons=buttons
    )

# خادم ويب بسيط للحفاظ على النشاط
async def handle_web_request(request):
    return web.Response(text="Bot is running!")

async def handle_health_check(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_web_request)
    app.router.add_get('/health', handle_health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"Web server started on port {port}")

# وظيفة دورية للحفاظ على نشاط البوت
async def keep_alive():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(WEBHOOK_URL) as resp:
                    logger.info(f"Keep-alive request sent. Status: {resp.status}")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")
        
        await asyncio.sleep(300)

# الدالة الرئيسية
async def main():
    # بدء خادم الويب
    await start_web_server()
    
    # بدء وظيفة الحفاظ على النشاط
    asyncio.create_task(keep_alive())
    
    print("Bot is starting...")
    
    # التأكد من أن البوت يعمل
    await bot.start()
    print("Bot started successfully!")
    
    # تشغيل البوت
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
