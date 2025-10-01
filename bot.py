import os
import json
import asyncio
from telethon import TelegramClient, events, Button
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError,
    ChatAdminRequiredError,
    UserNotParticipantError,
    ChannelPrivateError,
    FloodWaitError
)
from telethon.tl.functions.channels import InviteToChannelRequest, GetParticipantRequest, GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import ChannelParticipantsSearch, User, ChannelParticipantAdmin, ChannelParticipantCreator
import aiohttp
from aiohttp import web
import logging
import nest_asyncio
from datetime import datetime, timedelta
import time

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
BOT_TOKEN = '8052900952:AAFTioRqhxF7Tby2ISWEjSB8dX4cWwqNXAk'

# المستخدم المسموح فقط
ALLOWED_USER_ID = 6689435577

# رابط الويب هووك الجديد
WEBHOOK_URL = 'https://trans-2-77.onrender.com'

# إنشاء المجلدات للتخزين
os.makedirs('sessions', exist_ok=True)
os.makedirs('data', exist_ok=True)

# ملفات التخزين
ACCOUNTS_FILE = 'data/accounts.json'
SETTINGS_FILE = 'data/settings.json'
LOG_FILE = 'data/transfer_log.json'
ACTIVE_PROCESSES_FILE = 'data/active_processes.json'

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
    if not os.path.exists(ACTIVE_PROCESSES_FILE):
        with open(ACTIVE_PROCESSES_FILE, 'w', encoding='utf-8') as f:
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

def load_active_processes():
    try:
        with open(ACTIVE_PROCESSES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_active_processes(processes):
    with open(ACTIVE_PROCESSES_FILE, 'w', encoding='utf-8') as f:
        json.dump(processes, f, ensure_ascii=False, indent=2)

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
        json.dump(logs[-100:], f, ensure_ascii=False, indent=2)

# إنشاء عميل البوت
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# قاموس لتخزين حالات المستخدمين
user_states = {}
account_creation = {}
active_transfers = {}  # لتخزين عمليات النقل النشطة
processing_users = set()

# التحقق من المستخدم المسموح
def check_allowed_user(user_id):
    return user_id == ALLOWED_USER_ID

# زر البداية
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    
    if not check_allowed_user(user_id):
        await event.reply("❌ **غير مسموح لك باستخدام هذا البوت**")
        return
    
    user_states[user_id] = 'main'
    
    # التحقق من وجود عملية نقل نشطة
    active_processes = load_active_processes()
    has_active_process = str(user_id) in active_processes
    
    buttons = [
        [Button.inline("🚀 بدء العملية", "start_process")],
        [Button.inline("📱 الحسابات", "manage_accounts")],
        [Button.inline("⚙️ إعدادات", "settings")],
    ]
    
    if has_active_process:
        buttons.append([Button.inline("📊 إحصائيات مباشرة", "live_stats")])
    
    buttons.append([Button.inline("👨‍💻 المطور", "developer")])
    
    await event.reply(
        "🔄 **مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات**\n\n"
        "اختر أحد الخيارات:",
        buttons=buttons
    )

# معالجة الأزرار
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
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
        elif data == 'live_stats':
            await show_live_stats(event)
        elif data == 'stop_process':
            await stop_transfer_process(event)
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await event.answer("❌ حدث خطأ في المعالجة", alert=True)

async def back_to_main(event):
    user_id = event.sender_id
    user_states[user_id] = 'main'
    
    active_processes = load_active_processes()
    has_active_process = str(user_id) in active_processes
    
    buttons = [
        [Button.inline("🚀 بدء العملية", "start_process")],
        [Button.inline("📱 الحسابات", "manage_accounts")],
        [Button.inline("⚙️ إعدادات", "settings")],
    ]
    
    if has_active_process:
        buttons.append([Button.inline("📊 إحصائيات مباشرة", "live_stats")])
    
    buttons.append([Button.inline("👨‍💻 المطور", "developer")])
    
    await event.edit(
        "🔄 **مرحباً! أنا بوت نقل الأعضاء بين المجموعات والقنوات**\n\n"
        "اختر أحد الخيارات:",
        buttons=buttons
    )

async def check_account_permissions(client, entity):
    """التحقق من صلاحيات الحساب في الكيان"""
    try:
        me = await client.get_me()
        participant = await client(GetParticipantRequest(entity, me))
        
        permissions = {
            'is_creator': False,
            'is_admin': False,
            'can_invite': False,
            'can_add_members': False,
            'can_manage_chat': False
        }
        
        if hasattr(participant.participant, 'admin_rights'):
            admin_rights = participant.participant.admin_rights
            permissions.update({
                'is_admin': True,
                'can_invite': admin_rights.invite_users if admin_rights else False,
                'can_add_members': admin_rights.invite_users if admin_rights else False,
                'can_manage_chat': admin_rights.ban_users if admin_rights else False
            })
        
        if isinstance(participant.participant, ChannelParticipantCreator):
            permissions.update({
                'is_creator': True,
                'is_admin': True,
                'can_invite': True,
                'can_add_members': True,
                'can_manage_chat': True
            })
        
        return permissions, None
        
    except Exception as e:
        return None, f"❌ خطأ في التحقق من الصلاحيات: {str(e)}"

async def check_entity_access(client, entity_link):
    """التحقق من الوصول إلى الكيان"""
    try:
        entity = await client.get_entity(entity_link)
        return entity, None
    except ChannelPrivateError:
        return None, "❌ الحساب لا يستطيع الوصول إلى هذه القناة/المجموعة"
    except Exception as e:
        return None, f"❌ خطأ في الوصول إلى الكيان: {str(e)}"

async def get_active_members(client, source_entity, limit=1000):
    """الحصول على الأعضاء النشطين مع نظام فلترة"""
    try:
        all_participants = await client.get_participants(source_entity, limit=limit)
        
        # تطبيق الفلترة على الأعضاء
        filtered_members = []
        
        for participant in all_participants:
            # استبعاد البوتات والحسابات المحذوفة
            if participant.bot or participant.deleted:
                continue
            
            # استبعاد المشرفين والمنشئين (اختياري)
            try:
                participant_info = await client(GetParticipantRequest(source_entity, participant))
                if hasattr(participant_info.participant, 'admin_rights') or isinstance(participant_info.participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                    continue
            except:
                pass
            
            # إضافة العضو المفلتر
            filtered_members.append(participant)
            
            if len(filtered_members) >= limit:
                break
        
        return filtered_members, None
        
    except Exception as e:
        return None, f"❌ خطأ في جلب الأعضاء: {str(e)}"

async def start_process(event):
    user_id = event.sender_id
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
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
        
        await event.edit("🔍 **جاري التحقق من الصلاحيات والوصول...**")
        
        # التحقق من الحسابات الصالحة
        valid_accounts = []
        validation_reports = []
        
        for account in accounts:
            try:
                session_name = f"sessions/{user_id}_{account['phone']}"
                client = TelegramClient(session_name, API_ID, API_HASH)
                await client.start(phone=account['phone'])
                
                # التحقق من الوصول إلى المصدر
                source_entity, source_error = await check_entity_access(client, settings['source'])
                if source_error:
                    validation_reports.append(f"❌ {account['phone']}: {source_error}")
                    await client.disconnect()
                    continue
                
                # التحقق من الوصول إلى الهدف
                target_entity, target_error = await check_entity_access(client, settings['target'])
                if target_error:
                    validation_reports.append(f"❌ {account['phone']}: {target_error}")
                    await client.disconnect()
                    continue
                
                # التحقق من الصلاحيات في الهدف
                target_permissions, perm_error = await check_account_permissions(client, target_entity)
                if perm_error or not target_permissions.get('can_add_members', False):
                    validation_reports.append(f"❌ {account['phone']}: لا يملك صلاحية إضافة أعضاء في الهدف")
                    await client.disconnect()
                    continue
                
                # جلب الأعضاء النشطين من المصدر
                active_members, members_error = await get_active_members(client, source_entity, 500)
                if members_error:
                    validation_reports.append(f"❌ {account['phone']}: {members_error}")
                    await client.disconnect()
                    continue
                
                if not active_members:
                    validation_reports.append(f"⚠️ {account['phone']}: لا يوجد أعضاء نشطين في المصدر")
                    await client.disconnect()
                    continue
                
                valid_accounts.append({
                    'client': client,
                    'phone': account['phone'],
                    'session_name': session_name,
                    'active_members': active_members
                })
                
                validation_reports.append(f"✅ {account['phone']}: حساب صالح - {len(active_members)} عضو نشط")
                
            except Exception as e:
                logger.error(f"Error validating account {account['phone']}: {e}")
                validation_reports.append(f"❌ {account['phone']}: خطأ في التحقق - {str(e)}")
        
        if len(valid_accounts) == 0:
            report_text = "❌ **لا توجد حسابات صالحة لعملية النقل**\n\n" + "\n".join(validation_reports)
            await event.edit(report_text)
            return
        
        # بدء عملية النقل
        await event.edit(f"✅ **تم التحقق من {len(valid_accounts)} حساب صالح**\n🚀 **بدء عملية نقل الأعضاء...**")
        
        # حفظ بيانات العملية النشطة
        active_processes = load_active_processes()
        active_processes[str(user_id)] = {
            'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_accounts': len(valid_accounts),
            'total_members': sum(len(acc['active_members']) for acc in valid_accounts),
            'transferred': 0,
            'failed': 0,
            'current_account': 0,
            'status': 'جاري النقل',
            'accounts_status': {acc['phone']: {'transferred': 0, 'failed': 0} for acc in valid_accounts}
        }
        save_active_processes(active_processes)
        
        # بدء النقل بالتناوب
        asyncio.create_task(rotate_transfer_process(user_id, valid_accounts, settings['target'], event))
        
    except Exception as e:
        logger.error(f"Error in start_process: {e}")
        await event.edit(f"❌ **حدث خطأ في عملية النقل:** {str(e)}")
        processing_users.discard(user_id)

async def rotate_transfer_process(user_id, valid_accounts, target, original_event):
    """نقل الأعضاء بنظام التناوب بين الحسابات"""
    try:
        total_transferred = 0
        total_failed = 0
        
        # حساب إجمالي الأعضاء
        total_members = sum(len(acc['active_members']) for acc in valid_accounts)
        members_transferred = 0
        
        # المتابعة حتى نقل جميع الأعضاء
        while members_transferred < total_members:
            for account_idx, account_data in enumerate(valid_accounts):
                if members_transferred >= total_members:
                    break
                
                # تحديث الإحصائيات
                active_processes = load_active_processes()
                if str(user_id) not in active_processes:
                    break
                
                # نقل عضو واحد من هذا الحساب
                result = await transfer_single_member(account_data, target, account_idx + 1)
                
                if result['success']:
                    total_transferred += 1
                    members_transferred += 1
                else:
                    total_failed += 1
                
                # تحديث الإحصائيات المباشرة
                active_processes[str(user_id)]['transferred'] = total_transferred
                active_processes[str(user_id)]['failed'] = total_failed
                active_processes[str(user_id)]['current_account'] = account_idx + 1
                active_processes[str(user_id)]['accounts_status'][account_data['phone']]['transferred'] = result.get('account_transferred', 0)
                active_processes[str(user_id)]['accounts_status'][account_data['phone']]['failed'] = result.get('account_failed', 0)
                save_active_processes(active_processes)
                
                # تأخير بين كل عملية نقل
                await asyncio.sleep(20)
        
        # إنهاء العملية
        active_processes = load_active_processes()
        if str(user_id) in active_processes:
            active_processes[str(user_id)]['status'] = 'مكتمل'
            active_processes[str(user_id)]['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            save_active_processes(active_processes)
        
        # إرسال نتيجة النهائية
        result_text = (
            f"✅ **تم الانتهاء من عملية النقل!**\n\n"
            f"✅ **الأعضاء المنقولون بنجاح:** {total_transferred}\n"
            f"❌ **الفاشلين:** {total_failed}\n"
            f"📱 **الحسابات المستخدمة:** {len(valid_accounts)}\n"
            f"🕒 **الوقت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        await original_event.edit(result_text)
        
        # حفظ السجل
        log_transfer(user_id, {
            'success': total_transferred,
            'failed': total_failed,
            'total_members': total_members,
            'valid_accounts': len(valid_accounts),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # إغلاق جميع العملاء
        for account_data in valid_accounts:
            await account_data['client'].disconnect()
        
    except Exception as e:
        logger.error(f"Error in rotate_transfer_process: {e}")
        
        # تحديث حالة الخطأ
        active_processes = load_active_processes()
        if str(user_id) in active_processes:
            active_processes[str(user_id)]['status'] = f'خطأ: {str(e)}'
            save_active_processes(active_processes)
    finally:
        processing_users.discard(user_id)

async def transfer_single_member(account_data, target, account_num):
    """نقل عضو واحد باستخدام حساب معين"""
    client = account_data['client']
    
    try:
        if not account_data['active_members']:
            return {'success': False, 'error': 'لا يوجد أعضاء متاحين'}
        
        # أخذ أول عضو من القائمة
        member = account_data['active_members'].pop(0)
        target_entity = await client.get_entity(target)
        
        try:
            await client(InviteToChannelRequest(target_entity, [member]))
            
            # تحديث إحصائيات الحساب
            account_data['transferred'] = account_data.get('transferred', 0) + 1
            
            return {
                'success': True,
                'account_transferred': account_data['transferred'],
                'account_failed': account_data.get('failed', 0)
            }
            
        except FloodWaitError as e:
            logger.warning(f"Flood wait for {account_data['phone']}: {e.seconds} seconds")
            await asyncio.sleep(e.seconds + 5)
            return {'success': False, 'error': f'Flood wait: {e.seconds}s'}
        except Exception as e:
            logger.error(f"Error inviting member {member.id} with {account_data['phone']}: {e}")
            account_data['failed'] = account_data.get('failed', 0) + 1
            return {
                'success': False,
                'error': str(e),
                'account_transferred': account_data.get('transferred', 0),
                'account_failed': account_data['failed']
            }
            
    except Exception as e:
        logger.error(f"Error in transfer_single_member for {account_data['phone']}: {e}")
        return {'success': False, 'error': str(e)}

async def show_live_stats(event):
    """عرض الإحصائيات المباشرة للعملية الحالية"""
    user_id = event.sender_id
    
    active_processes = load_active_processes()
    process_data = active_processes.get(str(user_id))
    
    if not process_data:
        await event.answer("❌ لا توجد عملية نقل نشطة", alert=True)
        return
    
    # بناء تقرير الإحصائيات
    stats_text = f"📊 **الإحصائيات المباشرة**\n\n"
    stats_text += f"🕒 **وقت البدء:** {process_data['start_time']}\n"
    stats_text += f"📈 **الحالة:** {process_data['status']}\n"
    stats_text += f"👥 **إجمالي الأعضاء:** {process_data['total_members']}\n"
    stats_text += f"✅ **تم نقلهم:** {process_data['transferred']}\n"
    stats_text += f"❌ **الفاشلين:** {process_data['failed']}\n"
    stats_text += f"📱 **الحساب الحالي:** {process_data['current_account']}/{process_data['total_accounts']}\n\n"
    
    # إحصائيات كل حساب
    stats_text += "**إحصائيات الحسابات:**\n"
    for phone, acc_stats in process_data['accounts_status'].items():
        stats_text += f"• {phone}: ✅{acc_stats['transferred']} ❌{acc_stats['failed']}\n"
    
    buttons = [
        [Button.inline("🔄 تحديث الإحصائيات", "live_stats")],
        [Button.inline("🛑 إيقاف العملية", "stop_process")],
        [Button.inline("🔙 رجوع", "back_to_main")]
    ]
    
    await event.edit(stats_text, buttons=buttons)

async def stop_transfer_process(event):
    """إيقاف عملية النقل الحالية"""
    user_id = event.sender_id
    
    active_processes = load_active_processes()
    if str(user_id) in active_processes:
        active_processes[str(user_id)]['status'] = 'متوقف بواسطة المستخدم'
        active_processes[str(user_id)]['end_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        save_active_processes(active_processes)
    
    await event.answer("✅ تم إيقاف عملية النقل", alert=True)
    await back_to_main(event)

# باقي الدوال (manage_accounts, add_account_handler, delete_account, settings_menu, etc.)
# تبقى كما هي مع إضافة التحقق من المستخدم المسموح

async def manage_accounts(event):
    user_id = event.sender_id
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
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
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
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
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
    accounts = load_accounts().get(str(user_id), [])
    
    if int(account_index) < len(accounts):
        deleted_account = accounts.pop(int(account_index))
        save_accounts({**load_accounts(), str(user_id): accounts})
        
        session_file = f"sessions/{user_id}_{deleted_account['phone']}.session"
        if os.path.exists(session_file):
            os.remove(session_file)
        
        await event.answer(f"✅ تم حذف الحساب {deleted_account['phone']}", alert=True)
        await manage_accounts(event)

async def settings_menu(event):
    user_id = event.sender_id
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
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
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
    user_states[user_id] = 'awaiting_source'
    
    await event.edit(
        "📥 **إعداد المصدر**\n\n"
        "أرسل رابط أو معرف المجموعة/القناة المصدر:\n\n"
        "لإلغاء العملية، اكتب /cancel"
    )

async def set_target_handler(event):
    user_id = event.sender_id
    
    if not check_allowed_user(user_id):
        await event.answer("❌ غير مسموح لك باستخدام هذا البوت", alert=True)
        return
    
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

# معالجة الرسائل النصية (تبقى كما هي مع إضافة التحقق)
@bot.on(events.NewMessage)
async def message_handler(event):
    user_id = event.sender_id
    
    if not check_allowed_user(user_id):
        return
    
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

# دوال معالجة المدخلات (تبقى كما هي)
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
    
    active_processes = load_active_processes()
    has_active_process = str(user_id) in active_processes
    
    buttons = [
        [Button.inline("🚀 بدء العملية", "start_process")],
        [Button.inline("📱 الحسابات", "manage_accounts")],
        [Button.inline("⚙️ إعدادات", "settings")],
    ]
    
    if has_active_process:
        buttons.append([Button.inline("📊 إحصائيات مباشرة", "live_stats")])
    
    buttons.append([Button.inline("👨‍💻 المطور", "developer")])
    
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
