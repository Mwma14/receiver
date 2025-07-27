# START OF FILE handlers/callbacks.py

import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest
import re

import database
from . import commands
from . import helpers

logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown v2 characters."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def on_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all non-admin callback queries from inline buttons."""
    query = update.callback_query
    if not query or not query.data: return

    if query.data.startswith("admin_"):
        await query.answer()
        logger.debug(f"Ignoring admin callback '{query.data}' in user handler.")
        return

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to answer callback query for data {query.data}: {e}")

    data = query.data
    user_id = query.from_user.id

    text, keyboard = None, None

    if data == "nav_start": text, keyboard = commands.get_start_menu_content(context)
    elif data == "nav_balance": text, keyboard = commands.get_balance_content(context, user_id)
    elif data == "nav_cap": text, keyboard = commands.get_cap_content(context)
    elif data == "nav_rules": text, keyboard = commands.get_rules_content(context)
    elif data == "nav_support": text, keyboard = commands.get_support_content(context)
    elif data == "withdraw":
        await handle_withdraw_callback(update, context)
        return
    else:
        logger.info(f"[USER] Unhandled callback query from {user_id}: {data}")
        return

    if text and keyboard:
        try:
            await helpers.reply_and_mirror(
                update, context, text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
                edit_original=True
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e).lower():
                logger.error(f"Error editing message for callback {data}: {e}")

async def handle_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the 'withdraw' button press from the /balance command."""
    query = update.callback_query
    telegram_id = query.from_user.id
    
    context.user_data.pop('state', None)

    summary, balance, _, _, _ = database.get_user_balance_details(telegram_id)
    min_withdraw = float(context.bot_data.get('min_withdraw', 1.0))

    base_text, keyboard = commands.get_balance_content(context, telegram_id)
    
    if balance < min_withdraw:
        balance_str = f"{balance:.2f}"
        min_withdraw_str = f"{min_withdraw:.2f}"
        # Edit the message to show the error clearly.
        error_text = base_text + f"\n\n*⚠️ Your balance of `${escape_markdown(balance_str)}` is below the minimum of `${escape_markdown(min_withdraw_str)}`\\.*"
        try:
            await query.edit_message_text(error_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)
        except BadRequest: # Message not modified, ignore
            pass
        return

    # FIXED: The check for `withdrawable_accounts` is removed. Now the flow will continue
    # even if the balance is purely from manual adjustments.

    # If all checks pass, proceed with withdrawal
    await query.edit_message_reply_markup(reply_markup=None)
    
    prompt_text = (
        "💳 *WITHDRAWAL REQUEST*\n\n"
        "Please enter your wallet address \\(e\\.g\\., USDT TRC20\\)\\.\n\n"
        "Type /cancel to abort\\."
    )
    context.user_data['state'] = "waiting_for_address"
    
    await helpers.reply_and_mirror(
        update, context, text=prompt_text, 
        parse_mode=ParseMode.MARKDOWN_V2, 
        reply_to_message_id=query.message.message_id,
        send_new=True
    )
# END OF FILE handlers/callbacks.py