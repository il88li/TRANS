import os, asyncio, json, time, pytz, re, random
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from pyrogram import Client as PyroClient
from pyrogram.errors import UserDeactivated, ChatWriteForbidden, FloodWait

# ---------- الإعدادات العامة ----------
BOT_TOKEN   = os.getenv("BOT_TOKEN",   "8293003270:AAFMKUKzjHwl0lMDQOYWdQYYppuEAfIoo28")
API_ID      = int(os.getenv("API_ID",  "23656977"))
API_HASH    = os.getenv("API_HASH",    "49d3f43531a92b3f5bc403766313ca1e")
ADMIN       = int(os.getenv("ADMIN",   "6689435577"))
SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

# ---------- قواعد بيانات بسيطة (ملفات json) ----------
USERS_DB    = "users.json"
TASKS_DB    = "tasks.json"
BLOCK_DB    = "blocked.json"
PHONE_DB    = "phones.json"

for f in (USERS_DB, TASKS_DB, BLOCK_DB, PHONE_DB):
    if not os.path.exists(f):
        with open(f, "w") as j:
            json.dump({}, j)

def jload(file):
    with open(file) as ff:
        return json.load(ff)

def jsave(file, data):
    with open(file, "w") as ff:
        json.dump(data, ff, indent=2, ensure_ascii=False)

# ---------- كائنات البوت ----------
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
pyro_clients = {}   # phone -> PyroClient

# ---------- دوال مساعدة ----------
def is_user(uid):
    return str(uid) not in jload(BLOCK_DB)

def get_user_state(uid):
    return jload(USERS_DB).get(str(uid), {})

def set_user_state(uid, key, value):
    db = jload(USERS_DB)
    db.setdefault(str(uid), {})[key] = value
    jsave(USERS_DB, db)

def del_user_state(uid, key):
    db = jload(USERS_DB)
    if str(uid) in db and key in db[str(uid)]:
        del db[str(uid)][key]
        jsave(USERS_DB, db)

# ---------- لوحات الأزرار ----------
MAIN_MARKUP = [
    [Button.inline("بدء عملية النشر", "start_task")],
    [Button.inline("العمليات النشطة", "active_tasks")],
    [Button.inline("التحديثات", "updates")],
    [Button.inline("تهيئة عملية النشر", "setup")]
]

ADMIN_MARKUP = [
    [Button.inline("سحب رقم", "pull_phone")],
    [Button.inline("إدارة المستخدمين", "manage_users")]
]

# ---------- الأوامر ----------
@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(e):
    if not is_user(e.sender_id):
        return await e.reply("🚫 أنت محظور.")
    await e.reply("📌 أهلاً بك في بوت النشر التلقائي.",
                  buttons=MAIN_MARKUP)

@bot.on(events.NewMessage(pattern="/sos"))
async def sos(e):
    if e.sender_id != ADMIN:
        return await e.reply("🚫 هذا الأمر مخصص للمدير فقط.")
    await e.reply("🔧 لوحة المدير:", buttons=ADMIN_MARKUP)

# ---------- معالجات الأزرار (callback) ----------
@bot.on(events.CallbackQuery())
async def callback(e):
    if not is_user(e.sender_id):
        return await e.answer("🚫 أنت محظور.", alert=True)
    data = e.data.decode()
    uid = e.sender_id

    # ---------- التحديثات ----------
    if data == "updates":
        await e.edit("اشترك في قناتنا الإجبارية:\nhttps://t.me/iIl337",
                     buttons=[Button.inline("رجوع", "back_main")])

    # ---------- الرجوع ----------
    if data == "back_main":
        await e.edit("القائمة الرئيسية:", buttons=MAIN_MARKUP)

    # ---------- تهيئة عملية النشر ----------
    if data == "setup":
        txt = ("1) أرسل رقم الهاتف مع رمز الدولة (مثلاً: +9639xxxxxx)\n"
               "2) ستصلك رسالة تحتوي على كود التحقق، أرسلها هنا.\n"
               "3) بعد تسجيل الحساب سيتم عرض مجموعاتك لاختيارها.")
        set_user_state(uid, "expect", "phone")
        await e.edit(txt, buttons=[Button.inline("إلغاء", "back_main")])

    # ---------- بدء النشر ----------
    if data == "start_task":
        tasks = jload(TASKS_DB)
        user_tasks = [t for t in tasks.values() if t["uid"] == uid]
        if not user_tasks:
            return await e.answer("⚠️ لم تقم بتهيئة أي عملية بعد.", alert=True)
        for t in user_tasks:
            if t["status"] == "run":
                return await e.answer("⚠️ لديك عملية نشطة بالفعل.", alert=True)
        # نبدأ
        for t in user_tasks:
            t["status"] = "run"
        jsave(TASKS_DB, tasks)
        asyncio.create_task(run_tasks())
        await e.answer("✅ بدأت عملية النشر بنجاح.", alert=True)

    # ---------- العمليات النشطة ----------
    if data == "active_tasks":
        tasks = jload(TASKS_DB)
        user_tasks = [t for t in tasks.values() if t["uid"] == uid]
        if not user_tasks:
            return await e.edit("لا توجد عمليات نشطة.", buttons=[Button.inline("رجوع", "back_main")])
        btns = []
        for idx, t in enumerate(user_tasks):
            btns.append([Button.inline(f"{t['name']} - {t['status']}", f"taskmenu_{t['id']}")])
        btns.append([Button.inline("رجوع", "back_main")])
        await e.edit("العمليات النشطة:", buttons=btns)

    # ---------- قائمة مهام داخلية ----------
    if data.startswith("taskmenu_"):
        tid = data.split("_", 1)[1]
        tasks = jload(TASKS_DB)
        t = tasks.get(tid)
        if not t or t["uid"] != uid:
            return await e.answer("غير موجودة.", alert=True)
        txt = f"المجموعة: {t['name']}\nالحالة: {t['status']}"
        btns = []
        if t["status"] == "run":
            btns.append(Button.inline("إيقاف مؤقت", f"pause_{tid}"))
        else:
            btns.append(Button.inline("استئناف", f"resume_{tid}"))
        btns.extend([
            Button.inline("حذف العملية", f"del_{tid}"),
            Button.inline("عرض الإحصائيات", f"stat_{tid}"),
            Button.inline("رجوع", "active_tasks")
        ])
        await e.edit(txt, buttons=[btns])

    if data.startswith("pause_"):
        tid = data.split("_", 1)[1]
        tasks = jload(TASKS_DB)
        if tasks[tid]["uid"] == uid:
            tasks[tid]["status"] = "pause"
            jsave(TASKS_DB, tasks)
        await e.answer("⏸️ تم الإيقاف المؤقت.")
        await e.edit("تم التحديث.", buttons=MAIN_MARKUP)

    if data.startswith("resume_"):
        tid = data.split("_", 1)[1]
        tasks = jload(TASKS_DB)
        if tasks[tid]["uid"] == uid:
            tasks[tid]["status"] = "run"
            jsave(TASKS_DB, tasks)
        await e.answer("▶️ تم الاستئناف.")
        asyncio.create_task(run_tasks())
        await e.edit("تم التحديث.", buttons=MAIN_MARKUP)

    if data.startswith("del_"):
        tid = data.split("_", 1)[1]
        tasks = jload(TASKS_DB)
        if tasks[tid]["uid"] == uid:
            del tasks[tid]
            jsave(TASKS_DB, tasks)
        await e.answer("🗑️ تم الحذف.")
        await e.edit("تم الحذف.", buttons=MAIN_MARKUP)

    # ---------- خصائص المدير ----------
    if data == "pull_phone":
        db = jload(PHONE_DB)
        if not db:
            return await e.answer("لا توجد أرقام حالياً.", alert=True)
        btns = []
        for ph in list(db.keys())[:50]:
            btns.append([Button.inline(ph, f"phinfo_{ph}")])
        btns.append([Button.inline("رجوع", "sos")])
        await e.edit("اختر رقماً:", buttons=btns)

    if data.startswith("phinfo_"):
        ph = data.split("_", 1)[1]
        db = jload(PHONE_DB)
        info = db.get(ph, {})
        txt = f"الرقم: {ph}\nالمعلومات: {json.dumps(info, indent=2)}"
        await e.edit(txt, buttons=[
            [Button.inline("وضع في الانتظار", f"wait_{ph}")],
            [Button.inline("رجوع", "pull_phone")]
        ])

    if data.startswith("wait_"):
        ph = data.split("_", 1)[1]
        # نخزن أن هذا الرقم ينتظر رسالة من +42777
        set_user_state(ADMIN, "waiting_number", ph)
        await e.answer("تم وضع الرقم في حالة الانتظار.", alert=True)

    if data == "manage_users":
        await e.edit("اختر إجراء:",
                     buttons=[
                         [Button.inline("حظر شخص", "block_user")],
                         [Button.inline("إلغاء حظر شخص", "unblock_user")],
                         [Button.inline("رجوع", "sos")]
                     ])

    if data == "block_user":
        set_user_state(ADMIN, "expect", "block_uid")
        await e.edit("أرسل الايدي المراد حظره:")

    if data == "unblock_user":
        set_user_state(ADMIN, "expect", "unblock_uid")
        await e.edit("أرسل الايدي المراد إلغاء حظره:")

# ---------- معالجة الرسائل النصية (تسجيل الحساب، الفاصل، الرسالة...) ----------
@bot.on(events.NewMessage(func=lambda e: e.is_private))
async def text_handler(e):
    uid = e.sender_id
    if not is_user(uid):
        return
    state = get_user_state(uid)
    expect = state.get("expect")

    # تسجيل الهاتف
    if expect == "phone":
        phone = e.text.strip()
        set_user_state(uid, "phone", phone)
        set_user_state(uid, "expect", "code")
        client = PyroClient(f"{SESSION_DIR}/{phone}", API_ID, API_HASH, phone_number=phone)
        sent = await client.send_code(phone)
        set_user_state(uid, "phone_code_hash", sent.phone_code_hash)
        pyro_clients[phone] = client
        await e.reply("أرسل كود التحقق الذي وصلك (5 أرقام):")

    # إدخال الكود
    elif expect == "code":
        code = e.text.strip()
        phone = state["phone"]
        client = pyro_clients[phone]
        try:
            await client.sign_in(phone, state["phone_code_hash"], code)
        except Exception as er:
            if "2FA" in str(er):
                set_user_state(uid, "expect", "2fa")
                return await e.reply("الحساب مفعّل بكلمة مرور ثنائية، أرسلها:")
            return await e.reply(f"خطأ في الكود: {er}")
        # نجاح تسجيل الدخول
        dialogs = []
        async for d in client.get_dialogs():
            if d.chat.type in ("group", "supergroup"):
                dialogs.append({"id": d.chat.id, "title": d.chat.title})
        set_user_state(uid, "dialogs", dialogs)
        set_user_state(uid, "expect", "pick_groups")
        await show_groups(e, dialogs, 0)

    # 2FA
    elif expect == "2fa":
        pwd = e.text.strip()
        phone = state["phone"]
        client = pyro_clients[phone]
        try:
            await client.check_password(pwd)
        except Exception as er:
            return await e.reply(f"خطأ: {er}")
        dialogs = []
        async for d in client.get_dialogs():
            if d.chat.type in ("group", "supergroup"):
                dialogs.append({"id": d.chat.id, "title": d.chat.title})
        set_user_state(uid, "dialogs", dialogs)
        set_user_state(uid, "expect", "pick_groups")
        await show_groups(e, dialogs, 0)

    # اختيار المجموعات
    elif expect == "pick_groups":
        await e.reply("اضغط على المجموعات من الأزرار أعلاه، ثم اضغط «تعيين».")

    # الفاصل الزمني
    elif expect == "interval":
        try:
            minutes = int(e.text.strip())
        except:
            return await e.reply("أدخل رقماً صحيحاً (بالدقائق).")
        set_user_state(uid, "interval", minutes)
        set_user_state(uid, "expect", "message")
        await e.reply("أرسل الآن نص الرسالة التي تريد نشرها:")

    # الرسالة
    elif expect == "message":
        msg = e.text
        interval = state["interval"]
        groups = state["selected_groups"]
        phone = state["phone"]
        # نحفظ المهمة
        tasks = jload(TASKS_DB)
        tid = str(int(time.time()))
        tasks[tid] = {
            "id": tid,
            "uid": uid,
            "name": f"مجموعات({len(groups)})",
            "phone": phone,
            "groups": groups,
            "message": msg,
            "interval": interval,
            "status": "pause",
            "sent": 0,
            "last_sent": 0
        }
        jsave(TASKS_DB, tasks)
        # نسجل الرقم لاحقاً للمدير
        pdb = jload(PHONE_DB)
        pdb.setdefault(phone, {})["uid"] = uid
        jsave(PHONE_DB, pdb)
        del_user_state(uid, "expect")
        await e.reply("✅ تم حفظ المهمة، عد للقائمة الرئيسية واضغط «بدء عملية النشر».",
                      buttons=[Button.inline("القائمة الرئيسية", "back_main")])

    # حظر/إلغاء حظر
    if expect == "block_uid":
        target = e.text.strip()
        db = jload(BLOCK_DB)
        db[target] = True
        jsave(BLOCK_DB, db)
        del_user_state(uid, "expect")
        await e.reply("✅ تم الحظر.")
    if expect == "unblock_uid":
        target = e.text.strip()
        db = jload(BLOCK_DB)
        db.pop(target, None)
        jsave(BLOCK_DB, db)
        del_user_state(uid, "expect")
        await e.reply("✅ تم إلغاء الحظر.")

    # استقبال رسالة +42777 للمدير
    if uid == ADMIN and state.get("waiting_number"):
        ph = state["waiting_number"]
        txt = e.text
        await e.reply(f"وصلت رسالة للرقم {ph}:\n\n{txt}\n\n(يمكنك نسخها أو تحويلها).")
        del_user_state(ADMIN, "waiting_number")

# ---------- عرض المجموعات مع تمرير ----------
async def show_groups(e, dialogs, page):
    per_page = 10
    start, end = page * per_page, (page + 1) * per_page
    slice_d = dialogs[start:end]
    btns = []
    selected = get_user_state(e.sender_id).get("selected", [])
    for d in slice_d:
        icon = "✅" if d["id"] in selected else ""
        btns.append([Button.inline(f"{icon} {d['title']}", f"toggle_{d['id']}")])
    nav = []
    if start > 0:
        nav.append(Button.inline("⬅️ السابق", f"page_{page-1}"))
    if end < len(dialogs):
        nav.append(Button.inline("التالي ➡️", f"page_{page+1}"))
    if nav:
        btns.append(nav)
    btns.append([Button.inline("تعيين", "setgroups")])
    btns.append([Button.inline("إلغاء", "back_main")])
    await e.reply("اختر المجموعات:", buttons=btns)

# ---------- معالجة اختيار المجموعات ----------
@bot.on(events.CallbackQuery())
async def groups_callback(e):
    data = e.data.decode()
    uid = e.sender_id
    state = get_user_state(uid)
    if not state.get("expect") == "pick_groups":
        return
    dialogs = state["dialogs"]
    selected = state.get("selected", [])

    if data.startswith("toggle_"):
        gid = int(data.split("_")[1])
        if gid in selected:
            selected.remove(gid)
        else:
            selected.append(gid)
        set_user_state(uid, "selected", selected)
        await show_groups(e, dialogs, state.get("page", 0))

    if data.startswith("page_"):
        page = int(data.split("_")[1])
        set_user_state(uid, "page", page)
        await show_groups(e, dialogs, page)

    if data == "setgroups":
        if not selected:
            return await e.answer("اختر مجموعة واحدة على الأقل.", alert=True)
        set_user_state(uid, "selected_groups", selected)
        set_user_state(uid, "expect", "interval")
        await e.edit("أرسل الفاصل الزمني (بالدقائق) بين كل رسالة وأخرى:")

# ---------- مهمة النشر الخلفية ----------
async def run_tasks():
    tasks = jload(TASKS_DB)
    for t in tasks.values():
        if t["status"] != "run":
            continue
        phone = t["phone"]
        if phone not in pyro_clients:
            session = f"{SESSION_DIR}/{phone}"
            try:
                pyro_clients[phone] = PyroClient(session, API_ID, API_HASH)
                await pyro_clients[phone].start()
            except Exception as er:
                print("خطأ بدء العميل:", er)
                continue
        client = pyro_clients[phone]
        interval = t["interval"] * 60
        if time.time() - t["last_sent"] < interval:
            continue
        for gid in t["groups"]:
            try:
                await client.send_message(gid, t["message"])
                t["sent"] += 1
                t["last_sent"] = time.time()
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
            except (UserDeactivated, ChatWriteForbidden):
                pass
            await asyncio.sleep(2)
    jsave(TASKS_DB, tasks)
    await asyncio.sleep(30)
    asyncio.create_task(run_tasks())

# ---------- تشغيل البوت ----------
print("Bot started ...")
bot.loop.run_until_complete(run_tasks())
bot.run_until_disconnected()
