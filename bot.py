import logging
import os
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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

# Retrieve bot token from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Temporary in-memory dictionary to store pending join requests: user_id -> chat_id
pending_requests = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command in private chat."""
    await update.message.reply_text(
        "👋 Hello! I am your Group Approval Bot.\n\n"
        "To join our group, submit a join request through the group link, "
        "and I will message you here to verify your mobile number."
    )

async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers when a user requests to join the group."""
    join_request = update.chat_join_request
    user = join_request.from_user
    chat = join_request.chat
    user_chat_id = join_request.user_chat_id  # Secure private chat identifier

    logger.info(f"Join request received from {user.full_name} ({user.id}) for chat: {chat.title}")

    # Track pending request mapping
    pending_requests[user.id] = chat.id

    # Create a mobile number sharing button
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
    """Handles the contact shared by the user and checks verification."""
    message = update.message
    user = message.from_user
    contact = message.contact

    # Ensure the user shared their own contact payload securely
    if contact and contact.user_id == user.id:
        user_id = user.id
        if user_id in pending_requests:
            chat_id = pending_requests[user_id]

            try:
                # Automatically approve the user's join request
                await context.bot.approve_chat_join_request(
                    chat_id=chat_id, user_id=user_id
                )

                await message.reply_text(
                    "✅ Verification successful! Your request has been approved. Welcome to the group!",
                    reply_markup=ReplyKeyboardRemove(),
                )

                # Clean up stored data
                del pending_requests[user_id]
                logger.info(f"Successfully approved user {user.full_name} ({user_id})")

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

def main():
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN environment variable found! Exiting...")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(ChatJoinRequestHandler(handle_join_request))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))

    logger.info("Bot is up and running...")
    application.run_polling()

if __name__ == "__main__":
    main()
