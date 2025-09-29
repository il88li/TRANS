import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# إعدادات البوت
BOT_TOKEN = "8398354970:AAEZ2KASsMsTIYZDSRAX5DTzzWUiCrvW9zo"

# تخزين البيانات
user_data = {}
active_transfers = {}

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("بدء النقل", callback_data="start_transfer")],
        [InlineKeyboardButton("اضفني للمصدر", callback_data="add_to_source")],
        [InlineKeyboardButton("اضفني للهدف", callback_data="add_to_destination")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "مرحباً! أنا بوت نقل الأعضاء\n\n"
        "اختر أحد الخيارات:",
        reply_markup=reply_markup
    )

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data == "start_transfer":
        await start_transfer(query, context)
    elif query.data == "add_to_source":
        await add_to_source(query, context)
    elif query.data == "add_to_destination":
        await add_to_destination(query, context)

async def start_transfer(query, context):
    user_id = query.from_user.id
    
    if user_id not in user_data or 'source_group' not in user_data[user_id]:
        await query.edit_message_text(
            "❌ يجب عليك أولاً إضافة البوت إلى المجموعة المصدر باستخدام 'اضفني للمصدر'"
        )
        return
    
    if user_id not in user_data or 'destination_group' not in user_data[user_id]:
        await query.edit_message_text(
            "❌ يجب عليك أولاً إضافة البوت إلى المجموعة الهدف باستخدام 'اضفني للهدف'"
        )
        return
    
    active_transfers[user_id] = True
    await query.edit_message_text(
        "🔄 بدأ عملية النقل...\n"
        "سيتم نقل الأعضاء الذين يرسلون رسائل في المجموعة المصدر\n"
        "مع تأخير 2 ثانية بين كل نقل\n\n"
        "لإيقاف النقل، أرسل /stop"
    )
    
    # بدء مراقبة المجموعة المصدر
    asyncio.create_task(monitor_and_transfer(user_id, context))

async def add_to_source(query, context):
    user_id = query.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['source_group'] = True
    
    await query.edit_message_text(
        "✅ تم تعيين المجموعة الحالية كمصدر\n\n"
        "الآن أضف البوت إلى المجموعة الهدف واضغط على 'اضفني للهدف'"
    )

async def add_to_destination(query, context):
    user_id = query.from_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['destination_group'] = True
    
    await query.edit_message_text(
        "✅ تم تعيين المجموعة الحالية كهدف\n\n"
        "الآن يمكنك البدء في النقل بالضغط على 'بدء النقل'"
    )

async def monitor_and_transfer(user_id, context):
    try:
        while active_transfers.get(user_id, False):
            # محاكاة عملية النقل (ستحتاج لتعديل هذا الجزء حسب احتياجاتك)
            # في الواقع، تحتاج لاستخدام getUpdates أو webhooks لمراقبة الرسائل
            
            await asyncio.sleep(2)  # تأخير 2 ثانية بين كل نقل
            
    except Exception as e:
        logging.error(f"Error in transfer process: {e}")

async def stop_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id in active_transfers:
        active_transfers[user_id] = False
        await update.message.reply_text("⏹️ تم إيقاف عملية النقل")
    else:
        await update.message.reply_text("❌ لا توجد عملية نقل نشطة")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل من المجموعات المراقبة"""
    user_id = update.message.from_user.id
    
    # التحقق مما إذا كانت الرسالة من مجموعة مصدر ونقل نشط
    if (user_id in active_transfers and 
        active_transfers[user_id] and 
        user_id in user_data and 
        'source_group' in user_data[user_id]):
        
        try:
            # هنا يمكنك إضافة منطق النقل الفعلي
            # هذا مثال مبسط
            message = update.message
            await message.forward(chat_id=user_data[user_id].get('destination_chat_id'))
            
        except Exception as e:
            logging.error(f"Error forwarding message: {e}")

def main():
    # إنشاء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()

    # إضافة handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_transfer))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(MessageHandler(None, handle_message))

    # بدء البوت
    application.run_polling()
    print("البوت يعمل...")

if __name__ == '__main__':
    main()
