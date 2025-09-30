import os
import json
import asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import SessionPasswordNeededError
from aiohttp import web
import requests
import re

# بيانات API
API_ID = 23656977
API_HASH = '49d3f43531a92b3f5bc403766313ca1e'
BOT_TOKEN = '8228285723:AAHwfs_M8b4bnxgJPmjMNtR1nm0P6yoLEDk'

# إنشاء مجلدات التخزين
if not os.path.exists('sessions'):
    os.makedirs('sessions')
if not os.path.exists('data'):
    os.makedirs('data')

# حالات المستخدمين
user_states = {}

# تهيئة البيانات
def load_data():
    try:
        with open('data/users.json', 'r') as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open('data/users.json', 'w') as f:
        json.dump(data, f, indent=4)

def load_settings():
    try:
        with open('data/settings.json', 'r') as f:
            return json.load(f)
    except:
        return {'source': '', 'target': ''}

def save_settings(settings):
    with open('data/settings.json', 'w') as f:
        json.dump(settings, f, indent=4)

# إنشاء العميل
client = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# وظائف المساعدة
async def get_user_sessions(user_id):
    data = load_data()
    return data.get(str(user_id), {}).get('sessions', [])

async def save_user_session(user_id, session_string, phone):
    data = load_data()
    if str(user_id) not in data:
        data[str(user_id)] = {'sessions': []}
    
    sessions = data[str(user_id)]['sessions']
    if len(sessions) >= 10:
        return False
    
    sessions.append({
        'session_string': session_string,
        'phone': phone,
        'added_date': datetime.now().isoformat()
    })
    
    save_data(data)
    return True

async def delete_user_session(user_id, session_index):
    data = load_data()
    if str(user_id) in data:
        sessions = data[str(user_id)]['sessions']
        if 0 <= session_index < len(sessions):
            sessions.pop(session_index)
            save_data(data)
            return True
    return False

async def get_user_clients(user_id):
    sessions = await get_user_sessions(user_id)
    clients = []
    for session_data in sessions:
        try:
            session_client = TelegramClient(
                StringSession(session_data['session_string']), 
                API_ID, 
                API_HASH
            )
            await session_client.connect()
            if await session_client.is_user_authorized():
                clients.append(session_client)
            else:
                await session_client.disconnect()
        except Exception as e:
            print(f"Error creating client: {e}")
    return clients

async def join_channel(client, channel_link):
    try:
        if 't.me/' in channel_link:
            if '+' in channel_link:
                hash_link = channel_link.split('+')[1]
                await client(ImportChatInviteRequest(hash_link))
            else:
                username = channel_link.split('t.me/')[-1].replace('@', '')
                await client(JoinChannelRequest(username))
            return True
    except Exception as e:
        print(f"Error joining channel: {e}")
        return False

async def add_member_to_channel(client, target_channel, user_id):
    try:
        await client.edit_permissions(target_channel, user_id, view_messages=True)
        return True
    except Exception as e:
        print(f"Error adding member: {e}")
        return False

# تعريف الأحداث
@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    buttons = [
        [Button.inline('بدء العملية', b'start_process')],
        [Button.inline('الحسابات', b'accounts'), Button.inline('الاعدادات', b'settings')],
        [Button.inline('المطور', b'developer')]
    ]
    
    await event.reply(
        '**مرحباً بك في بوت نقل الأعضاء**\n\n'
        'اختر من الأزرار أدناه:',
        buttons=buttons
    )

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == 'start_process':
        await start_process(event)
    elif data == 'accounts':
        await show_accounts(event)
    elif data == 'settings':
        await show_settings(event)
    elif data == 'developer':
        await show_developer(event)
    elif data.startswith('delete_account_'):
        index = int(data.split('_')[2])
        await delete_account(event, index)
    elif data == 'add_account':
        await add_account_flow(event)
    elif data == 'set_source':
        user_states[user_id] = 'waiting_source'
        await set_source(event)
    elif data == 'set_target':
        user_states[user_id] = 'waiting_target'
        await set_target(event)
    elif data == 'back_to_main':
        await back_to_main(event)

async def start_process(event):
    settings = load_settings()
    if not settings.get('source') or not settings.get('target'):
        await event.edit(
            '** يرجى تعيين المصدر والهدف اولا **\n\n'
            'اذهب إلى الاعدادات لتعيين القنوات/المجموعات المصدر والهدف.',
            buttons=[[Button.inline('رجوع', b'back_to_main')]]
        )
        return
    
    user_clients = await get_user_clients(event.sender_id)
    if not user_clients:
        await event.edit(
            '** لا توجد حسابات مضافة **\n\n'
            'يرجى اضافة حسابات اولا من قسم الحسابات.',
            buttons=[[Button.inline('رجوع', b'back_to_main')]]
        )
        return
    
    await event.edit('** بدء عملية نقل الأعضاء... **')
    
    success_count = 0
    failed_count = 0
    
    for i, user_client in enumerate(user_clients):
        try:
            await event.edit(f'** معالجة الحساب {i+1} من {len(user_clients)} **')
            
            await join_channel(user_client, settings['source'])
            await asyncio.sleep(2)
            
            await join_channel(user_client, settings['target'])
            await asyncio.sleep(2)
            
            success_count += 1
            
            if i < len(user_clients) - 1:
                await event.edit(f'** انتظر 5 دقائق قبل الحساب التالي **')
                await asyncio.sleep(300)
                
        except Exception as e:
            print(f"Error in transfer: {e}")
            failed_count += 1
        finally:
            await user_client.disconnect()
    
    await event.edit(
        f'** اكتملت العملية **\n\n'
        f'الحسابات الناجحة: {success_count}\n'
        f'الحسابات الفاشلة: {failed_count}',
        buttons=[[Button.inline('رجوع', b'back_to_main')]]
    )

async def show_accounts(event):
    user_id = event.sender_id
    sessions = await get_user_sessions(user_id)
    
    buttons = []
    for i, session in enumerate(sessions):
        buttons.append([Button.inline(f'حذف {session["phone"]}', f'delete_account_{i}')])
    
    buttons.append([Button.inline('اضافة حساب', b'add_account')])
    buttons.append([Button.inline('رجوع', b'back_to_main')])
    
    message = f'** الحسابات المسجلة ({len(sessions)}/10) **\n\n'
    if sessions:
        for i, session in enumerate(sessions):
            message += f'{i+1}. {session["phone"]}\n'
    else:
        message += 'لا توجد حسابات مضافة'
    
    await event.edit(message, buttons=buttons)

async def delete_account(event, index):
    if await delete_user_session(event.sender_id, index):
        await event.answer('تم حذف الحساب', alert=False)
        await show_accounts(event)
    else:
        await event.answer('فشل في حذف الحساب', alert=True)

async def add_account_flow(event):
    user_id = event.sender_id
    user_states[user_id] = 'waiting_phone'
    
    await event.edit(
        '** اضافة حساب جديد **\n\n'
        'ارسل رقم الهاتف مع رمز الدولة:\n'
        'مثال: +201234567890',
        buttons=[[Button.inline('رجوع', b'accounts')]]
    )

async def show_settings(event):
    settings = load_settings()
    
    message = f'** الاعدادات **\n\n'
    message += f'المصدر: {settings.get("source", "لم يتم التعيين")}\n'
    message += f'الهدف: {settings.get("target", "لم يتم التعيين")}\n'
    
    buttons = [
        [Button.inline('تعيين المصدر', b'set_source')],
        [Button.inline('تعيين الهدف', b'set_target')],
        [Button.inline('رجوع', b'back_to_main')]
    ]
    
    await event.edit(message, buttons=buttons)

async def set_source(event):
    await event.edit(
        '** تعيين المصدر **\n\n'
        'ارسل رابط القناة/المجموعة المصدر:',
        buttons=[[Button.inline('رجوع', b'settings')]]
    )

async def set_target(event):
    await event.edit(
        '** تعيين الهدف **\n\n'
        'ارسل رابط القناة/المجموعة الهدف:',
        buttons=[[Button.inline('رجوع', b'settings')]]
    )

async def show_developer(event):
    await event.edit(
        '** المطور **\n\n'
        'للتواصل مع المطور:\n'
        '@OlIiIl7\n\n'
        'للدعم الفني والاستفسارات.',
        buttons=[[Button.inline('رجوع', b'back_to_main')]]
    )

async def back_to_main(event):
    await start_handler(event)

@client.on(events.NewMessage)
async def message_handler(event):
    user_id = event.sender_id
    text = event.text
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state == 'waiting_phone':
        if text.startswith('/'):
            return
        
        if not re.match(r'^\+\d{10,15}$', text):
            await event.reply('رقم الهاتف غير صحيح. يرجى ارسال رقم هاتف صحيح مع رمز الدولة.')
            return
        
        user_states[user_id] = {'state': 'waiting_code', 'phone': text}
        
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            sent_code = await client.send_code_request(text)
            user_states[user_id]['phone_code_hash'] = sent_code.phone_code_hash
            user_states[user_id]['client'] = client
            
            await event.reply('تم ارسال كود التحقق. يرجى ارسال الكود:')
        except Exception as e:
            await event.reply(f'خطأ في ارسال كود التحقق: {e}')
            user_states.pop(user_id, None)
    
    elif isinstance(state, dict) and state.get('state') == 'waiting_code':
        if text.startswith('/'):
            return
        
        try:
            client = state['client']
            phone = state['phone']
            phone_code_hash = state['phone_code_hash']
            
            await client.sign_in(phone, text, phone_code_hash=phone_code_hash)
            
            session_string = client.session.save()
            await save_user_session(user_id, session_string, phone)
            
            await event.reply('تم اضافة الحساب بنجاح!')
            user_states.pop(user_id, None)
            await client.disconnect()
            
        except SessionPasswordNeededError:
            user_states[user_id]['state'] = 'waiting_password'
            await event.reply('هذا الحساب محمي بكلمة مرور. يرجى ارسال كلمة المرور:')
        except Exception as e:
            await event.reply(f'خطأ في التحقق: {e}')
            user_states.pop(user_id, None)
            if 'client' in state:
                await state['client'].disconnect()
    
    elif isinstance(state, dict) and state.get('state') == 'waiting_password':
        if text.startswith('/'):
            return
        
        try:
            client = state['client']
            await client.sign_in(password=text)
            
            session_string = client.session.save()
            await save_user_session(user_id, session_string, state['phone'])
            
            await event.reply('تم اضافة الحساب بنجاح!')
            user_states.pop(user_id, None)
            await client.disconnect()
            
        except Exception as e:
            await event.reply(f'خطأ في كلمة المرور: {e}')
            user_states.pop(user_id, None)
            if 'client' in state:
                await state['client'].disconnect()
    
    elif state == 'waiting_source':
        settings = load_settings()
        settings['source'] = text
        save_settings(settings)
        
        await event.reply('تم تعيين المصدر بنجاح!')
        user_states.pop(user_id, None)
    
    elif state == 'waiting_target':
        settings = load_settings()
        settings['target'] = text
        save_settings(settings)
        
        await event.reply('تم تعيين الهدف بنجاح!')
        user_states.pop(user_id, None)

# خادم ويب للحفاظ على نشاط البوت
async def web_server():
    app = web.Application()
    
    async def handle(request):
        return web.Response(text="Bot is running!")
    
    app.router.add_get('/', handle)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

# طلبات دورية للحفاظ على النشاط
async def keep_alive():
    while True:
        try:
            requests.get('https://trans-1-1pbd.onrender.com')
            print("Keep-alive request sent")
        except Exception as e:
            print(f"Keep-alive error: {e}")
        
        await asyncio.sleep(300)

# التشغيل الرئيسي
async def main():
    await web_server()
    asyncio.create_task(keep_alive())
    
    print("Bot is running...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    import datetime
    from datetime import datetime
    
    asyncio.run(main())
