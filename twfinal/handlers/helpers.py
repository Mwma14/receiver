# START OF FILE handlers/helpers.py

import logging
import asyncio
import re
from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest  # Import BadRequest
from config import SESSION_LOG_CHANNEL_ID, ENABLE_SESSION_FORWARDING

logger = logging.getLogger(__name__)

def escape_markdown(text: str) -> str:
    """Helper function to escape telegram markdown v2 characters."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def get_user_topic_id(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> int | None:
    if not ENABLE_SESSION_FORWARDING or not SESSION_LOG_CHANNEL_ID: return None
    user_topics = context.bot_data.get("user_topics", {})
    if user_id in user_topics: return user_topics[user_id]
    try:
        user = await context.bot.get_chat(user_id)
        topic_name = f"👤 {escape_markdown(user.full_name)} ({user_id})"
        topic = await context.bot.create_forum_topic(chat_id=SESSION_LOG_CHANNEL_ID, name=topic_name)
        topic_id = topic.message_thread_id
        user_topics[user_id] = topic_id
        context.bot_data["user_topics"] = user_topics
        logger.info(f"Created new topic '{topic_name}' with ID {topic_id} for user {user_id}")
        return topic_id
    except Exception as e:
        logger.error(f"Failed to create topic for user {user_id}: {e}")
        return None

async def mirror_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str, **kwargs):
    """
    Mirrors a message to the user's topic in the admin log channel.
    If MarkdownV2 parsing fails, it sends the message as plain text to ensure the log is not lost.
    """
    topic_id = await get_user_topic_id(context, user_id)
    if not topic_id: return
    
    # We will always attempt to send with MarkdownV2 first.
    kwargs['parse_mode'] = ParseMode.MARKDOWN_V2
    kwargs['message_thread_id'] = topic_id
    
    try:
        await context.bot.send_message(
            chat_id=SESSION_LOG_CHANNEL_ID,
            text=text,
            **kwargs
        )
    except BadRequest as e:
        # FIXED: If sending with MarkdownV2 fails due to a parsing error,
        # log it once and then re-send the message as plain text.
        if "can't parse entities" in str(e).lower():
            logger.warning(f"MarkdownV2 parsing failed for mirror message. Re-sending as plain text. Error: {e}")
            kwargs.pop('parse_mode', None) # Remove parse_mode to send as plain text
            try:
                await context.bot.send_message(
                    chat_id=SESSION_LOG_CHANNEL_ID,
                    text=text, # The original, unescaped text
                    **kwargs
                )
            except Exception as final_e:
                logger.error(f"Failed to re-send mirror message as plain text to topic {topic_id}: {final_e}")
        else:
            # For other bad requests (e.g., message not found), log as an error.
            logger.error(f"Failed to mirror message to topic {topic_id}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while mirroring message to topic {topic_id}: {e}")

async def reply_and_mirror(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs) -> Message | None:
    """Sends a reply to the user and mirrors the conversation to the admin channel."""
    user = update.effective_user
    user_mention = f"@{escape_markdown(user.username)}" if user.username else f"ID: `{user.id}`"
    
    kwargs['parse_mode'] = ParseMode.MARKDOWN_V2
    is_editing = kwargs.pop('edit_original', False) and update.callback_query
    is_sending_new = kwargs.pop('send_new', False)

    # We only mirror the user's original message if we are not editing a message.
    # Editing implies the action came from a button, not a new text message.
    if not is_editing and update.message and update.message.text:
        user_log_text = f"*{user_mention}:*\n`{escape_markdown(update.message.text)}`"
        await mirror_message(context, user.id, user_log_text, disable_web_page_preview=True)

    sent_message = None
    if is_editing:
        sent_message = await update.callback_query.edit_message_text(text=text, **kwargs)
        user_action_text = f"*{user_mention}* pressed button `/{escape_markdown(update.callback_query.data)}`"
        await mirror_message(context, user.id, user_action_text, disable_web_page_preview=True)
    elif is_sending_new:
        sent_message = await context.bot.send_message(chat_id=user.id, text=text, **kwargs)
    else: # Default is to reply
        sent_message = await update.message.reply_text(text=text, **kwargs)

    # Mirror the bot's reply
    bot_log_text = f"*🤖 Bot Reply {'(Edited)' if is_editing else ''}:*\n{text}"
    mirror_kwargs = kwargs.copy()
    mirror_kwargs.pop('reply_to_message_id', None)
    # FIXED: The `bot_log_text` variable should be used here, not the raw `text`.
    await mirror_message(context, user.id, bot_log_text, **mirror_kwargs)

    return sent_message

# END OF FILE handlers/helpers.py