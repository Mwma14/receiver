# START OF FILE handlers/start.py

import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import database
from . import helpers

logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown v2 characters."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    db_user, is_new_user = database.get_or_create_user(user_id, user.username)
    
    if is_new_user:
        logger.info(f"New user joined: {user.full_name} (@{user.username}, ID: {user_id})")
        
        admin_channel_id_str = context.bot_data.get('admin_channel')
        admin_channel_id = None
        if admin_channel_id_str and admin_channel_id_str.startswith("@"):
            admin_channel_id = admin_channel_id_str
        elif admin_channel_id_str and admin_channel_id_str.lstrip('-').isdigit():
            admin_channel_id = int(admin_channel_id_str)
        
        if admin_channel_id:
            try:
                user_full_name = escape_markdown(user.full_name)
                username = f"@{escape_markdown(user.username)}" if user.username else "N/A"
                
                text=f"✅ *New User Alert*\n\n\\- Name: {user_full_name}\n\\- Username: {username}\n\\- ID: `{user_id}`"
                
                await context.bot.send_message(
                    chat_id=admin_channel_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logger.warning(f"Could not send new user notification to admin channel: {e}")

    if db_user and db_user.get('is_blocked'):
        # FIXED: Escaped period.
        await update.message.reply_text("You have been blocked from using this bot\\.")
        return

    welcome_text = escape_markdown(context.bot_data.get('welcome_message', "Welcome!"))
    
    keyboard = [
        [InlineKeyboardButton("💼 My Balance", callback_data="nav_balance"), InlineKeyboardButton("📋 Countries & Rates", callback_data="nav_cap")],
        [InlineKeyboardButton("📜 Rules", callback_data="nav_rules"), InlineKeyboardButton("🆘 Contact Support", callback_data="nav_support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await helpers.reply_and_mirror(
        update, context, 
        text=welcome_text, 
        parse_mode=ParseMode.MARKDOWN_V2, 
        reply_markup=reply_markup, 
        disable_web_page_preview=True
    )

# END OF FILE handlers/start.py