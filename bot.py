import os
import json
import asyncio
from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError,
    ChatAdminRequiredError,
    UserNotParticipantError,
    ChannelPrivateError
)
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import ChannelParticipantsSearch
import aiohttp
from aiohttp import web
import logging
import nest_asyncio
from datetime import datetime

# تطبيق nest_asyncio لحل مشكلة event loop
nest_asyncio.apply()

# إعدادات التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# بيانات البوت
API_ID = 23656977
API_HASH = '49d3f43531a92b3f5bc403766313ca1e'
BOT_TOKEN = '8052900952:AAEmgVIJ2igX3fA5KAXs06xtZ5OeQjIXMjk'

# رابط الويب هووك الجديد
WEBHOOK_URL = 'https://trans-2-77.onrender.com'

# إنشاء المجلدات للتخزين
os.makedirs('sessions', exist_ok=True)
os.makedirs('data', exist_ok=True)

# ملفات التخزين
ACCOUNTS_FILE = 'data/accounts.json'
SETTINGS_FILE = 'data/settings.json'
LOG_FILE = 'data/transfer_log.json'

# تهيئة ملفات التخزين
def init_files():
    if not os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)

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

def log_transfer(user_id, result):
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except:
        logs = []
    
    logs.append({
        'user_id': user_id,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'result': result
    })
    
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs[-100:], f, ensure_ascii=False, indent=2)  # حفظ آخر 100 عملية فقط

# إنشاء عميل البوت
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# قاموس لتخزين حالات المستخدمين
user_states = {}
account_creation = {}
processing_users = set()  # لمنع العمليات المتكررة

# زر البداية
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    
    # مسح الحالة السابقة
    user_states[user_id] = 'main'
    
    buttons = [
        [Button.inline("🚀 بدء العملية", "start_process")],
        [Button.inline("📱 الحسابات", "manage_accounts")],
        [Button.inline("⚙️ إعدادات", "settings")],
        [Button.inline("👨‍💻 المطور", "developer")]
    ]
    
    await event.reply(
        "🔄 **مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات**\n\n"
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
        [Button.inline("🚀 بدء العملية", "start_process")],
        [Button.inline("📱 الحسابات", "manage_accounts")],
        [Button.inline("⚙️ إعدادات", "settings")],
        [Button.inline("👨‍💻 المطور", "developer")]
    ]
    
    await event.edit(
        "🔄 **مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات**\n\n"
        "اختر أحد الخيارات:",
        buttons=buttons
    )

async def check_permissions(client, source, target):
    """التحقق من جميع الصلاحيات المطلوبة"""
    permissions_report = {
        'source_access': False,
        'target_access': False,
        'source_member': False,
        'target_admin': False,
        'can_invite': False,
        'errors': []
    }
    
    try:
        # التحقق من المصدر
        source_entity = await client.get_entity(source)
        permissions_report['source_access'] = True
        
        # التحقق من العضوية في المصدر
        try:
            await client(GetParticipantRequest(source_entity, await client.get_me()))
            permissions_report['source_member'] = True
        except UserNotParticipantError:
            permissions_report['errors'].append("❌ الحساب ليس عضو في المصدر")
        except Exception as e:
            permissions_report['errors'].append(f"❌ خطأ في التحقق من العضوية في المصدر: {str(e)}")
        
        # التحقق من الهدف
        target_entity = await client.get_entity(target)
        permissions_report['target_access'] = True
        
        # التحقق من الصلاحيات في الهدف
        try:
            participant = await client(GetParticipantRequest(target_entity, await client.get_me()))
            if hasattr(participant.participant, 'admin_rights'):
                if participant.participant.admin_rights.invite_users:
                    permissions_report['target_admin'] = True
                    permissions_report['can_invite'] = True
                else:
                    permissions_report['errors'].append("❌ الحساب ليس لديه صلاحية إضافة أعضاء في الهدف")
            else:
                permissions_report['errors'].append("❌ الحساب ليس مشرف في الهدف")
        except ChatAdminRequiredError:
            permissions_report['errors'].append("❌ الحساب ليس مشرف في الهدف")
        except Exception as e:
            permissions_report['errors'].append(f"❌ خطأ في التحقق من الصلاحيات في الهدف: {str(e)}")
            
    except ChannelPrivateError:
        permissions_report['errors'].append("❌ الحساب لا يستطيع الوصول إلى القناة/المجموعة")
    except Exception as e:
        permissions_report['errors'].append(f"❌ خطأ في الوصول إلى الكيان: {str(e)}")
    
    return permissions_report

async def start_process(event):
    user_id = event.sender_id
    
    # منع العمليات المتكررة
    if user_id in processing_users:
        await event.answer("⚠️ هناك عملية نقل قيد التنفيذ بالفعل!", alert=True)
        return
    
    processing_users.add(user_id)
    
    try:
        accounts = load_accounts().get(str(user_id), [])
        settings = load_settings().get(str(user_id), {})
        
        if len(accounts) == 0:
            await event.answer("❌ يجب إضافة حسابات أولاً!", alert=True)
            return
        
        if not settings.get('source') or not settings.get('target'):
            await event.answer("❌ يجب تعيين المصدر والهدف أولاً!", alert=True)
            return
        
        await event.edit("🔍 **جاري التحقق من الصلاحيات...**")
        
        # التحقق من الصلاحيات لجميع الحسابات
        valid_accounts = []
        permission_reports = []
        
        for account in accounts:
            try:
                session_name = f"sessions/{user_id}_{account['phone']}"
                client = TelegramClient(session_name, API_ID, API_HASH)
                await client.start(phone=account['phone'])
                
                # التحقق من الصلاحيات
                permissions = await check_permissions(client, settings['source'], settings['target'])
                permission_reports.append({
                    'phone': account['phone'],
                    'permissions': permissions
                })
                
                if all([permissions['source_access'], permissions['target_access'], 
                       permissions['source_member'], permissions['can_invite']]):
                    valid_accounts.append({
                        'client': client,
                        'phone': account['phone'],
                        'session_name': session_name
                    })
                else:
                    await client.disconnect()
                    
            except Exception as e:
                logger.error(f"Error checking permissions for {account['phone']}: {e}")
                permission_reports.append({
                    'phone': account['phone'],
                    'permissions': {'errors': [f"❌ خطأ في التحقق: {str(e)}"]}
                })
        
        if len(valid_accounts) == 0:
            await event.edit(
                "❌ **لا توجد حسابات صالحة لعملية النقل**\n\n"
                "**تقرير الصلاحيات:**\n" +
                "\n".join([f"📱 {report['phone']}: {', '.join(report['permissions']['errors'])}" 
                          for report in permission_reports])
            )
            return
        
        await event.edit(f"✅ **تم التحقق من {len(valid_accounts)} حساب صالح**\n🚀 **بدء عملية نقل الأعضاء...**")
        
        # عملية نقل الأعضاء بشكل متزامن
        success_count = 0
        failed_count = 0
        transfer_details = []
        
        # الحصول على الأعضاء من المصدر (باستخدام أول حساب صالح)
        source_client = valid_accounts[0]['client']
        source_entity = await source_client.get_entity(settings['source'])
        participants = await source_client.get_participants(source_entity, limit=50)
        
        if len(participants) == 0:
            await event.edit("❌ **لا يوجد أعضاء في المصدر لنقلهم**")
            return
        
        # نقل الأعضاء باستخدام جميع الحسابات الصالحة بشكل متزامن
        tasks = []
        members_per_account = max(1, len(participants) // len(valid_accounts))
        
        for i, account_data in enumerate(valid_accounts):
            start_idx = i * members_per_account
            end_idx = start_idx + members_per_account if i < len(valid_accounts) - 1 else len(participants)
            account_participants = participants[start_idx:end_idx]
            
            if account_participants:
                task = transfer_members(account_data, settings['target'], account_participants, i+1)
                tasks.append(task)
        
        # تنفيذ جميع المهام بشكل متزامن
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # جمع النتائج
        for result in results:
            if isinstance(result, dict):
                success_count += result['success']
                failed_count += result['failed']
                transfer_details.extend(result['details'])
        
        # إغلاق جميع العملاء
        for account_data in valid_accounts:
            await account_data['client'].disconnect()
        
        # حفظ السجل
        log_transfer(user_id, {
            'success': success_count,
            'failed': failed_count,
            'total_members': len(participants),
            'valid_accounts': len(valid_accounts),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'details': transfer_details
        })
        
        # إظهار النتيجة
        result_text = (
            f"✅ **تم الانتهاء من عملية النقل!**\n\n"
            f"✅ **الأعضاء المنقولون بنجاح:** {success_count}\n"
            f"❌ **الفاشلين:** {failed_count}\n"
            f"👥 **إجمالي الأعضاء في المصدر:** {len(participants)}\n"
            f"📱 **الحسابات المستخدمة:** {len(valid_accounts)}\n"
            f"🕒 **الوقت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        await event.edit(result_text)
        
    except Exception as e:
        logger.error(f"Error in start_process: {e}")
        await event.edit(f"❌ **حدث خطأ في عملية النقل:** {str(e)}")
    finally:
        processing_users.discard(user_id)

async def transfer_members(account_data, target, participants, account_num):
    """نقل الأعضاء باستخدام حساب معين"""
    client = account_data['client']
    success = 0
    failed = 0
    details = []
    
    try:
        target_entity = await client.get_entity(target)
        
        for i, participant in enumerate(participants):
            try:
                if not participant.bot and not participant.deleted:
                    await client(InviteToChannelRequest(target_entity, [participant]))
                    success += 1
                    details.append(f"الحساب {account_num}: ✅ تم نقل {participant.id}")
                    
                    # تأخير 3-7 ثواني بين كل عملية
                    await asyncio.sleep(3 + (i % 4))
                    
            except Exception as e:
                failed += 1
                details.append(f"الحساب {account_num}: ❌ فشل نقل {participant.id} - {str(e)}")
                await asyncio.sleep(2)
                
    except Exception as e:
        logger.error(f"Error in transfer_members for {account_data['phone']}: {e}")
        failed += len(participants)
        details.append(f"الحساب {account_num}: ❌ خطأ عام - {str(e)}")
    
    return {'success': success, 'failed': failed, 'details': details}

async def manage_accounts(event):
    user_id = event.sender_id
    accounts = load_accounts().get(str(user_id), [])
    
    buttons = []
    for i, account in enumerate(accounts):
        buttons.append([Button.inline(f"🗑️ حذف {account['phone']}", f"delete_account_{i}")])
    
    buttons.append([Button.inline("➕ إضافة حساب", "add_account")])
    buttons.append([Button.inline("🔙 رجوع", "back_to_main")])
    
    text = f"📱 **الحسابات المسجلة ({len(accounts)}/10):**\n\n"
    for account in accounts:
        text += f"• 📞 {account['phone']}\n"
    
    await event.edit(text, buttons=buttons)

async def add_account_handler(event):
    user_id = event.sender_id
    user_states[user_id] = 'awaiting_phone'
    account_creation[user_id] = {}
    
    await event.edit(
        "📱 **إضافة حساب جديد**\n\n"
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
        f"⚙️ **إعدادات النقل:**\n\n"
        f"📥 **المصدر:** {source}\n"
        f"📤 **الهدف:** {target}\n\n"
        "اختر الإعداد الذي تريد تعديله:",
        buttons=buttons
    )

async def set_source_handler(event):
    user_id = event.sender_id
    user_states[user_id] = 'awaiting_source'
    
    await event.edit(
        "📥 **إعداد المصدر**\n\n"
        "أرسل رابط أو معرف المجموعة/القناة المصدر:\n\n"
        "لإلغاء العملية، اكتب /cancel"
    )

async def set_target_handler(event):
    user_id = event.sender_id
    user_states[user_id] = 'awaiting_target'
    
    await event.edit(
        "📤 **إعداد الهدف**\n\n"
        "أرسل رابط أو معرف المجموعة/القناة الهدف:\n\n"
        "لإلغاء العملية، اكتب /cancel"
    )

async def developer_info(event):
    buttons = [
        [Button.url("📞 تواصل مع المطور", "https://t.me/OlIiIl7")],
        [Button.inline("🔙 رجوع", "back_to_main")]
    ]
    
    await event.edit(
        "👨‍💻 **معلومات المطور:**\n\n"
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
        [Button.inline("🚀 بدء العملية", "start_process")],
        [Button.inline("📱 الحسابات", "manage_accounts")],
        [Button.inline("⚙️ إعدادات", "settings")],
        [Button.inline("👨‍💻 المطور", "developer")]
    ]
    
    await event.reply(
        "🔄 **مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات**\n\n"
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
    await start_web_server()
    asyncio.create_task(keep_alive())
    
    print("Bot is starting...")
    await bot.start()
    print("Bot started successfully!")
    
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
