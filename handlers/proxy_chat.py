# START OF FILE handlers/proxy_chat.py
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import database

logger = logging.getLogger(__name__)

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forwards a user's message to the admin, unless it's a login attempt."""
    if not update.message or not update.message.text:
        return
        
    user = update.effective_user
    text = update.message.text.strip()
    
    # Heuristic check to avoid forwarding login attempts (phone numbers)
    if text.startswith("+") and len(text) > 5 and text[1:].isdigit():
        return

    # Do not forward messages from admins
    if database.is_admin(user.id):
        return

    admin_id_str = context.bot_data.get('support_id')
    if not admin_id_str or not admin_id_str.isdigit():
        logger.warning("Proxy chat failed: support_id (admin for chat) is not configured correctly.")
        return
    admin_id = int(admin_id_str)
    
    # Don't forward messages from the main admin to themselves
    if user.id == admin_id:
        return

    try:
        await context.bot.forward_message(
            chat_id=admin_id,
            from_chat_id=user.id,
            message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Failed to forward message from user {user.id} to admin {admin_id}: {e}")

async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a reply from the admin back to the user."""
    admin_user = update.effective_user
    admin_id_str = context.bot_data.get('support_id')

    # This handler is only for the configured admin
    if not admin_id_str or str(admin_user.id) != admin_id_str:
        return

    replied_to_message = update.message.reply_to_message
    # Check if the admin is replying to a message that was forwarded from a user
    if replied_to_message and replied_to_message.forward_from:
        original_user_id = replied_to_message.forward_from.id
        try:
            # Copy the admin's message (text, photo, etc.) to the original user
            await context.bot.copy_message(
                chat_id=original_user_id,
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id
            )
        except Exception as e:
            logger.error(f"Failed to send admin reply to user {original_user_id}: {e}")
            await update.message.reply_text(f"❌ Could not send reply to user `{original_user_id}`.\nReason: {e}", parse_mode=ParseMode.MARKDOWN)

# END OF FILE handlers/proxy_chat.py