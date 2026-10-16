import logging
import os
import sqlite3
from datetime import datetime
import openpyxl
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    ChatJoinRequestHandler,
    MessageHandler,
    CommandHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Retrieve environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Comma-separated list of Telegram numeric User IDs allowed to use /list (e.g., "123456789,987654321")
ADMIN_USER_IDS = [int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip().isdigit()]

# Temporary in-memory dictionary to track ongoing join requests: user_id -> chat_id
pending_requests = {}

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            mobile_number TEXT,
            joined_date TEXT,
            joined_time TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_user_to_db(user_id, username, mobile_number):
    now = datetime.now()
    joined_date = now.strftime("%Y-%m-%d")
    joined_time = now.strftime("%H:%M:%S")
    
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, username, mobile_number, joined_date, joined_time)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, mobile_number, joined_date, joined_time))
    conn.commit()
    conn.close()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ignored or answered minimally in private chat without unsolicited texts."""
    # Only acknowledge if requested privately, but do not trigger group actions or spam
    await update.message.reply_text(
        "👋 Bot is active. To join our group, please submit a join request through the official group link."
    )

async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers only when a user requests to join the group."""
    join_request = update.chat_join_request
    user = join_request.from_user
    chat = join_request.chat
    user_chat_id = join_request.user_chat_id  

    logger.info(f"Join request received from {user.full_name} ({user.id}) for chat: {chat.title}")

    # Track pending request mapping
    pending_requests[user.id] = chat.id

    # Create mobile sharing button
    keyboard = [[KeyboardButton("📱 Share Verified Mobile Number", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    try:
        await context.bot.send_message(
            chat_id=user_chat_id,
            text=(
                f"Hello *{user.first_name}*!\n\n"
                f"To gain access to *{chat.title}*, please share your Telegram-associated "
                "mobile number by clicking the button below."
            ),
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Failed to DM user {user.id}: {e}")

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the contact shared by the user."""
    message = update.message
    user = message.from_user
    contact = message.contact

    if contact and contact.user_id == user.id:
        user_id = user.id
        if user_id in pending_requests:
            chat_id = pending_requests[user_id]
            mobile_number = contact.phone_number
            username = f"@{user.username}" if user.username else user.full_name

            try:
                # 1. Automatically approve entry request
                await context.bot.approve_chat_join_request(
                    chat_id=chat_id, user_id=user_id
                )

                # 2. Save user details to SQLite database
                save_user_to_db(user_id, username, mobile_number)

                await message.reply_text(
                    "✅ Verification successful! Your request has been approved. Welcome to the group!",
                    reply_markup=ReplyKeyboardRemove(),
                )

                # Clean up memory mapping
                del pending_requests[user_id]
                logger.info(f"Successfully approved and logged user {username} ({user_id})")

            except Exception as e:
                logger.error(f"Failed to approve user {user_id}: {e}")
                await message.reply_text(
                    "⚠️ An error occurred while approving your request. Please contact a group admin.",
                    reply_markup=ReplyKeyboardRemove(),
                )
        else:
            await message.reply_text(
                "⚠️ No pending join requests were found for your account, or it has already been processed.",
                reply_markup=ReplyKeyboardRemove(),
            )
    else:
        await message.reply_text(
            "❌ Please share your *own* valid Telegram account mobile number using the button provided.",
            parse_mode="Markdown",
        )

async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates and sends an Excel list of verified members. Restricted to bot owners/admins."""
    user_id = update.effective_user.id

    if ADMIN_USER_IDS and user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    # Fetch data from SQLite
    conn = sqlite3.connect("verified_users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, mobile_number, joined_date, joined_time FROM users")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📂 No verified users found in the database yet.")
        return

    # Create Excel Workbook using openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Verified Members"

    # Define requested columns
    headers = ["SNO", "USERNAME", "USER ID", "MOBILE NUMBER", "JOINED DATE", "JOINED TIME"]
    ws.append(headers)

    # Populate rows
    for index, row in enumerate(rows, start=1):
        uid, uname, phone, j_date, j_time = row
        ws.append([index, uname, uid, f"+{phone}", j_date, j_time])

    file_path = "verified_members.xlsx"
    wb.save(file_path)

    # Send document to admin
    try:
        with open(file_path, "rb") as f:
            await update.message.reply_document(
                document=InputFile(f, filename="verified_members.xlsx"),
                caption="📊 Here is the latest list of verified group members."
            )
    except Exception as e:
        logger.error(f"Failed to send Excel file: {e}")
        await update.message.reply_text("⚠️ Failed to generate or send the spreadsheet file.")
        
    # Clean up local file copy if needed
    if os.path.exists(file_path):
        os.remove(file_path)

def main():
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN environment variable found! Exiting...")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", export_excel))
    application.add_handler(ChatJoinRequestHandler(handle_join_request))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))

    logger.info("Bot is running with Excel tracking enabled...")
    application.run_polling()

if __name__ == "__main__":
    main()
