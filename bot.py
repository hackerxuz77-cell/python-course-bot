import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dateutil.relativedelta import relativedelta
import asyncio
import threading
import time

import config

# Log konfiguratsiyasi
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ma'lumotlar bazasini sozlash
conn = sqlite3.connect(config.DATABASE_NAME, check_same_thread=False)
cursor = conn.cursor()

# Jadval yaratish
def init_database():
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        join_date TIMESTAMP,
        subscription_end TIMESTAMP,
        penalty_count INTEGER DEFAULT 0
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        admin_id INTEGER,
        task_text TEXT,
        assigned_time TIMESTAMP,
        status TEXT DEFAULT 'pending',
        rating INTEGER,
        feedback TEXT,
        completed_time TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS penalties (
        penalty_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        reason TEXT,
        penalty_date TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_reports (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        report_text TEXT,
        report_date TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    conn.commit()

# Yangi a'zoni kutish
async def new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for user in update.message.new_chat_members:
        # Botning o'zini e'tiborsiz qoldirish
        if user.is_bot:
            continue
            
        # Foydalanuvchini ma'lumotlar bazasiga qo'shish
        subscription_end = datetime.now() + relativedelta(months=config.SUBSCRIPTION_MONTHS)
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, join_date, subscription_end) VALUES (?, ?, ?, ?, ?, ?)',
                      (user.id, user.username, user.first_name, user.last_name, datetime.now(), subscription_end))
        conn.commit()
        
        # Xush kelibsiz xabari
        welcome_text = f"Assalomu alaykum {user.first_name}! 🐍\n\nPython kursimizga xush kelibsiz!\n\n"
        welcome_text += f"Sizning obunangiz {subscription_end.strftime('%Y-%m-%d')} sanagacha amal qiladi."
        
        await update.message.reply_text(welcome_text)

# Start komandasi
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Shaxsiy chat ekanligini tekshirish
    if update.effective_chat.type == 'private':
        if user.id in config.ADMINS:
            await admin_panel(update, context)
        else:
            await update.message.reply_text("Salom! Men Python kursi guruhi botiman. Guruhga qo'shiling va kodlashni o'rganing! 🐍")

# Admin paneli
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in config.ADMINS:
        await update.message.reply_text("❌ Sizga ruxsat yo'q!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📝 Uy vazifasi berish", callback_data="assign_task")],
        [InlineKeyboardButton("👥 Obunachilar ro'yxati", callback_data="subscribers_list")],
        [InlineKeyboardButton("⏰ Yaqin to'lovchilar", callback_data="upcoming_payments")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🏛 Admin paneli:", reply_markup=reply_markup)

# Vazifa berish bosqichlari
async def assign_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in config.ADMINS:
        await query.edit_message_text("❌ Sizga ruxsat yo'q!")
        return
    
    # Foydalanuvchilar ro'yxatini olish
    cursor.execute('SELECT user_id, first_name, last_name FROM users ORDER BY first_name')
    users = cursor.fetchall()
    
    if not users:
        await query.edit_message_text("❌ Hozircha obunachilar yo'q!")
        return
    
    keyboard = []
    for user in users:
        keyboard.append([InlineKeyboardButton(f"👤 {user[1]} {user[2]}", callback_data=f"select_user_{user[0]}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Kimga vazifa bermoqchisiz?", reply_markup=reply_markup)

# Foydalanuvchini tanlash
async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "admin_back":
        await admin_panel_callback(update, context)
        return
    
    user_id = int(query.data.split('_')[-1])
    context.user_data['selected_user'] = user_id
    
    await query.edit_message_text("📝 Vazifa matnini yuboring:\n\n(Necha marta, qanday vazifa, qachongacha bajarsin)")

# Vazifa matnini qabul qilish
async def receive_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'selected_user' not in context.user_data:
        return
    
    task_text = update.message.text
    user_id = context.user_data['selected_user']
    
    # Vazifani ma'lumotlar bazasiga saqlash
    cursor.execute('INSERT INTO tasks (user_id, admin_id, task_text, assigned_time) VALUES (?, ?, ?, ?)',
                  (user_id, update.effective_user.id, task_text, datetime.now()))
    conn.commit()
    task_id = cursor.lastrowid
    
    # Foydalanuvchiga vazifani yuborish
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📋 Yangi uy vazifasi berildi!\n\n{task_text}\n\nVazifani bajarish uchun 24 soat vaqtingiz bor.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👀 Vazifani ko'rish", callback_data=f"view_task_{task_id}")]
            ])
        )
        await update.message.reply_text("✅ Vazifa muvaffaqiyatli yuborildi!")
    except Exception as e:
        logger.error(f"Vazifani yuborishda xatolik: {e}")
        await update.message.reply_text("❌ Foydalanuvchiga xabar yuborib bo'lmadi. U botni ishga tushirmagan bo'lishi mumkin.")
    
    del context.user_data['selected_user']

# Vazifani ko'rish
async def view_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split('_')[-1])
    
    # Vazifa ma'lumotlarini olish
    cursor.execute('SELECT task_text, assigned_time FROM tasks WHERE task_id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task:
        task_text, assigned_time = task
        assigned_time = datetime.strptime(assigned_time, "%Y-%m-%d %H:%M:%S.%f")
        deadline = assigned_time + timedelta(hours=24)
        
        message_text = f"📋 Sizning vazifangiz:\n\n{task_text}\n\n"
        message_text += f"⏰ Vazifa berilgan vaqt: {assigned_time.strftime('%Y-%m-%d %H:%M')}\n"
        message_text += f"🕓 Vazifa muddati: {deadline.strftime('%Y-%m-%d %H:%M')}"
        
        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Vazifani bajardim", callback_data=f"complete_task_{task_id}")]
            ])
        )
        
        # 24 soatdan keyin tekshirish
        asyncio.create_task(schedule_task_check(task_id, deadline, context))

# Vazifa tekshiruvini rejalashtirish
async def schedule_task_check(task_id, deadline, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    delay = (deadline - now).total_seconds()
    
    if delay > 0:
        await asyncio.sleep(delay)
        await check_task_completion(task_id, context)

# Vazifa bajarilganligini tekshirish
async def check_task_completion(task_id, context: ContextTypes.DEFAULT_TYPE):
    # Vazifa holatini tekshirish
    cursor.execute('SELECT status, user_id, admin_id FROM tasks WHERE task_id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task and task[0] == 'pending':
        status, user_id, admin_id = task
        
        # Adminga xabar berish
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"⏰ Vazifa bajarilmadi! Vazifa ID: {task_id}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Vazifani ko'rish", callback_data=f"admin_view_task_{task_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"Xabar yuborishda xatolik: {e}")

# Vazifani bajardim tugmasi
async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split('_')[-1])
    
    # Vazifa ma'lumotlarini olish
    cursor.execute('SELECT user_id, admin_id FROM tasks WHERE task_id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task:
        user_id, admin_id = task
        
        # Vazifa holatini yangilash
        cursor.execute('UPDATE tasks SET status = "completed", completed_time = ? WHERE task_id = ?', 
                      (datetime.now(), task_id))
        conn.commit()
        
        await query.edit_message_text("✅ Vazifangiz qabul qilindi! Admin tekshiradi.")
        
        # Adminga xabar berish
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📩 Yangi topshiriq keldi! Vazifa ID: {task_id}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Vazifani ko'rish", callback_data=f"admin_review_task_{task_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"Xabar yuborishda xatolik: {e}")

# Admin vazifani ko'rish
async def admin_review_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split('_')[-1])
    
    # Vazifa ma'lumotlarini olish
    cursor.execute('SELECT task_text, user_id, assigned_time, completed_time FROM tasks WHERE task_id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task:
        task_text, user_id, assigned_time, completed_time = task
        
        # Foydalanuvchi ma'lumotlarini olish
        cursor.execute('SELECT first_name, last_name FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user:
            first_name, last_name = user
            message_text = f"👤 Foydalanuvchi: {first_name} {last_name}\n"
            message_text += f"📋 Vazifa: {task_text}\n"
            message_text += f"⏰ Berilgan vaqt: {assigned_time}\n"
            message_text += f"✅ Bajarligan vaqt: {completed_time}"
            
            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("1 ⭐", callback_data=f"rate_1_{task_id}"),
                     InlineKeyboardButton("2 ⭐", callback_data=f"rate_2_{task_id}"),
                     InlineKeyboardButton("3 ⭐", callback_data=f"rate_3_{task_id}")],
                    [InlineKeyboardButton("4 ⭐", callback_data=f"rate_4_{task_id}"),
                     InlineKeyboardButton("5 ⭐", callback_data=f"rate_5_{task_id}")]
                ])
            )

# Baho berish
async def rate_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split('_')
    rating = int(data_parts[1])
    task_id = int(data_parts[2])
    
    # Bahoni saqlash
    cursor.execute('UPDATE tasks SET rating = ? WHERE task_id = ?', (rating, task_id))
    conn.commit()
    
    # Vazifa ma'lumotlarini olish
    cursor.execute('SELECT user_id FROM tasks WHERE task_id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task:
        user_id = task[0]
        
        # Foydalanuvchi ma'lumotlarini olish
        cursor.execute('SELECT first_name, last_name FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user:
            first_name, last_name = user
            
            rating_text = ""
            if rating == 1:
                rating_text = "1 - Qoniqarsiz"
            elif rating == 2:
                rating_text = "2 - Dars qilishga ishtiyoq yo'q"
            elif rating == 3:
                rating_text = "3 - Yaxshiroq intil"
            elif rating == 4:
                rating_text = "4 - Yaxshi"
            elif rating == 5:
                rating_text = "5 - A'lo"
            
            await query.edit_message_text(f"✅ Baho berildi: {rating_text}")
            
            # Foydalanuvchiga bahoni yuborish
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📊 Sizning vazifangiz baholandi: {rating_text}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("❌ Sababini bilish", callback_data=f"ask_reason_{task_id}")]
                    ])
                )
            except Exception as e:
                logger.error(f"Xabar yuborishda xatolik: {e}")

# Sabab so'rash
async def ask_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split('_')[-1])
    context.user_data['task_for_reason'] = task_id
    
    await query.edit_message_text("📝 Baho sababini yozing:")

# Sababni qabul qilish
async def receive_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'task_for_reason' not in context.user_data:
        return
    
    task_id = context.user_data['task_for_reason']
    reason_text = update.message.text
    
    # Sababni saqlash
    cursor.execute('UPDATE tasks SET feedback = ? WHERE task_id = ?', (reason_text, task_id))
    conn.commit()
    
    # Vazifa ma'lumotlarini olish
    cursor.execute('SELECT user_id, rating FROM tasks WHERE task_id = ?', (task_id,))
    task = cursor.fetchone()
    
    if task:
        user_id, rating = task
        
        # Foydalanuvchi ma'lumotlarini olish
        cursor.execute('SELECT first_name, last_name FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if user:
            first_name, last_name = user
            
            rating_text = ""
            if rating == 1:
                rating_text = "1 - Qoniqarsiz"
            elif rating == 2:
                rating_text = "2 - Dars qilishga ishtiyoq yo'q"
            elif rating == 3:
                rating_text = "3 - Yaxshiroq intil"
            elif rating == 4:
                rating_text = "4 - Yaxshi"
            elif rating == 5:
                rating_text = "5 - A'lo"
            
            await update.message.reply_text("✅ Sabab qabul qilindi!")
            
            # Foydalanuvchiga sababni yuborish
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📝 Sizning vazifangiz bahosi sababi:\n\n{rating_text}\n\n{reason_text}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Tushundim", callback_data="understand_reason")]
                    ])
                )
                
                # Jarima qo'shish (agar baho past bo'lsa)
                if rating <= 2:
                    cursor.execute('SELECT penalty_count FROM users WHERE user_id = ?', (user_id,))
                    penalty_count = cursor.fetchone()[0] or 0
                    penalty_count += 1
                    
                    cursor.execute('UPDATE users SET penalty_count = ? WHERE user_id = ?', (penalty_count, user_id))
                    cursor.execute('INSERT INTO penalties (user_id, amount, reason, penalty_date) VALUES (?, ?, ?, ?)',
                                  (user_id, config.PENALTY_AMOUNT, reason_text, datetime.now()))
                    conn.commit()
                    
                    if penalty_count >= 3:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"⚠️ Sizda {penalty_count} marta jarima to'plandingiz. Keyingi oy {config.MONTHLY_PAYMENT + (config.PENALTY_AMOUNT * penalty_count)} so'm to'lashingiz kerak bo'ladi."
                        )
                
            except Exception as e:
                logger.error(f"Xabar yuborishda xatolik: {e}")
    
    del context.user_data['task_for_reason']

# Kunlik xabar yuborish
async def send_daily_notification():
    # Barcha foydalanuvchilarga xabar yuborish
    cursor.execute('SELECT user_id, first_name FROM users WHERE subscription_end > ?', (datetime.now(),))
    users = cursor.fetchall()
    
    for user in users:
        try:
            # Bot instansiyasini yaratish
            application = Application.builder().token(config.BOT_TOKEN).build()
            await application.bot.send_message(
                chat_id=user[0],
                text=f"Salom {user[1]}! 🌟\n\nSiz 1 kun o'tkazdingiz. Hozirgacha nimalar o'rgandingiz?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 Javob yozish", callback_data=f"daily_report_{user[0]}")]
                ])
            )
        except Exception as e:
            logger.error(f"Xabar yuborishda xatolik: {e}")

# Kunlik hisobot yuborish
async def daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[-1])
    context.user_data['daily_report_user'] = user_id
    
    await query.edit_message_text("📖 Bugun nimalar o'rgandingiz? Hisobot yozing:")

# Kunlik hisobotni qabul qilish
async def receive_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'daily_report_user' not in context.user_data:
        return
    
    user_id = context.user_data['daily_report_user']
    report_text = update.message.text
    
    # Hisobotni saqlash
    cursor.execute('INSERT INTO daily_reports (user_id, report_text, report_date) VALUES (?, ?, ?)',
                  (user_id, report_text, datetime.now()))
    conn.commit()
    
    await update.message.reply_text("✅ Hisobotingiz qabul qilindi! Rahmat!")
    del context.user_data['daily_report_user']

# Obunachilar ro'yxati
async def subscribers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cursor.execute('SELECT user_id, first_name, last_name, join_date, subscription_end FROM users ORDER BY join_date DESC')
    users = cursor.fetchall()
    
    message_text = "👥 Obunachilar ro'yxati:\n\n"
    for user in users:
        user_id, first_name, last_name, join_date, subscription_end = user
        join_date = datetime.strptime(join_date, "%Y-%m-%d %H:%M:%S.%f")
        subscription_end = datetime.strptime(subscription_end, "%Y-%m-%d %H:%M:%S.%f")
        
        message_text += f"👤 {first_name} {last_name}\n"
        message_text += f"   📅 Qo'shilgan: {join_date.strftime('%Y-%m-%d')}\n"
        message_text += f"   ⏰ Obuna tugashi: {subscription_end.strftime('%Y-%m-%d')}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message_text, reply_markup=reply_markup)

# Yaqin to'lovchilarni ko'rsatish
async def upcoming_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # 3 kundan kam qolgan obunalarni topish
    three_days_later = datetime.now() + timedelta(days=3)
    cursor.execute('SELECT user_id, first_name, last_name, subscription_end FROM users WHERE subscription_end < ? ORDER BY subscription_end ASC', (three_days_later,))
    users = cursor.fetchall()
    
    message_text = "⏰ Yaqin to'lovchilar (3 kundan kam qolgan):\n\n"
    
    if users:
        for user in users:
            user_id, first_name, last_name, subscription_end = user
            subscription_end = datetime.strptime(subscription_end, "%Y-%m-%d %H:%M:%S.%f")
            days_left = (subscription_end - datetime.now()).days
            
            message_text += f"👤 {first_name} {last_name}\n"
            message_text += f"   📅 Obuna tugashi: {subscription_end.strftime('%Y-%m-%d')}\n"
            message_text += f"   ⏰ Qolgan kun: {days_left} kun\n\n"
            
            # Foydalanuvchiga ogohlantirish yuborish
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Ogohlantirish: Sizning obunangizga {days_left} kun qoldi. Obunangizni yanglang!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Tushundim", callback_data="understand_warning")]
                    ])
                )
            except Exception as e:
                logger.error(f"Xabar yuborishda xatolik: {e}")
    else:
        message_text += "Hozircha yaqin to'lovchilar yo'q."
    
    keyboard = [
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message_text, reply_markup=reply_markup)

# Admin paneliga qaytish
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await admin_panel(update, context)

# Kunlik xabarlarni yuborish uchun alohida thread
def daily_notification_thread():
    while True:
        now = datetime.now()
        # Har kuni soat 18:00 da xabar yuborish
        target_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if now > target_time:
            target_time += timedelta(days=1)
        
        wait_seconds = (target_time - now).total_seconds()
        time.sleep(wait_seconds)
        
        # Xabarlarni yuborish
        asyncio.run(send_daily_notification())

# Asosiy funksiya
def main():
    # Ma'lumotlar bazasini ishga tushirish
    init_database()
    
    # Kunlik xabarlar uchun thread yaratish
    notification_thread = threading.Thread(target=daily_notification_thread, daemon=True)
    notification_thread.start()
    
    # Botni yaratish
    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # Handlerlar
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_members))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(assign_task, pattern="^assign_task$"))
    application.add_handler(CallbackQueryHandler(select_user, pattern="^select_user_"))
    application.add_handler(CallbackQueryHandler(view_task, pattern="^view_task_"))
    application.add_handler(CallbackQueryHandler(complete_task, pattern="^complete_task_"))
    application.add_handler(CallbackQueryHandler(admin_review_task, pattern="^admin_review_task_"))
    application.add_handler(CallbackQueryHandler(rate_task, pattern="^rate_"))
    application.add_handler(CallbackQueryHandler(ask_reason, pattern="^ask_reason_"))
    application.add_handler(CallbackQueryHandler(daily_report, pattern="^daily_report_"))
    application.add_handler(CallbackQueryHandler(subscribers_list, pattern="^subscribers_list$"))
    application.add_handler(CallbackQueryHandler(upcoming_payments, pattern="^upcoming_payments$"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_back$"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^understand_reason$"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^understand_warning$"))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task_text))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_reason))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_daily_report))
    
    # Botni ishga tushirish
    application.run_polling()

if __name__ == '__main__':
    main()
