# START OF FILE handlers/admin.py

import logging, asyncio, os, re, zipfile
from enum import Enum, auto
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, User
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import BadRequest
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import database
from handlers import login
from config import BOT_TOKEN, SESSION_LOG_CHANNEL_ID

logger = logging.getLogger(__name__)

# Added states for the new File Manager login flow
class AdminState(Enum):
    GET_USER_INFO_ID, BLOCK_USER_ID, UNBLOCK_USER_ID, ADD_ADMIN_ID, REMOVE_ADMIN_ID, BROADCAST_MSG, BROADCAST_CONFIRM, ADD_PROXY, REMOVE_PROXY_ID, EDIT_SETTING_VALUE, ADD_COUNTRY_CODE, ADD_COUNTRY_NAME, ADD_COUNTRY_FLAG, ADD_COUNTRY_PRICE_OK, ADD_COUNTRY_PRICE_RESTRICTED, ADD_COUNTRY_TIME, ADD_COUNTRY_CAPACITY, DELETE_COUNTRY_CODE, DELETE_COUNTRY_CONFIRM, DELETE_USER_DATA_ID, DELETE_USER_DATA_CONFIRM, RECHECK_BY_USER_ID, EDIT_COUNTRY_VALUE, EDIT_SETTING_START, ADJ_BALANCE_ID, ADJ_BALANCE_AMOUNT, FM_PHONE, FM_CODE, FM_PASSWORD = auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto(),auto()

def escape_markdown(text: str) -> str:
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def admin_required(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if not database.is_admin(user_id):
            if update.callback_query: await update.callback_query.answer("🚫 Access Denied", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

async def try_edit_message(query, text, reply_markup):
    try: 
        if query.message:
            await query.answer() 
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
    except BadRequest as e:
        if "Message is not modified" not in str(e).lower(): logger.error(f"Error editing message for cb {query.data}: {e}. Text: {text}")

def create_pagination_keyboard(prefix, current_page, total_items, item_per_page=5):
    btns, total_pages = [], (total_items + item_per_page - 1) // item_per_page if total_items > 0 else 1
    if total_pages <= 1: return []
    row = []
    if current_page > 1: row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_{current_page-1}"))
    if current_page < total_pages: row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_{current_page+1}"))
    if row: btns.append(row)
    return btns

async def get_main_admin_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")], [InlineKeyboardButton("👥 Users", callback_data="admin_users_main_page_1"), InlineKeyboardButton("🌍 Countries", callback_data="admin_country_list")], [InlineKeyboardButton("💰 Finance", callback_data="admin_finance_main"), InlineKeyboardButton("♻️ Accounts", callback_data="admin_confirm_main")], [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings_main"), InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_main")], [InlineKeyboardButton("🗂️ File Manager", callback_data="admin_fm_main"), InlineKeyboardButton("⚠️ Admins", callback_data="admin_admins_main")]])

async def cancel_conv(update, context):
    context.user_data.clear()
    await update.message.reply_text("✅ Operation cancelled\\.")
    await update.message.reply_text("👑 *Admin Panel*", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())
    return ConversationHandler.END

class FakeCallbackQuery:
    def __init__(self, update_or_query_obj, data):
        self.message = update_or_query_obj.message
        self.data = data
        self.from_user = getattr(update_or_query_obj, 'from_user', None) or getattr(update_or_query_obj, 'effective_user', None)
    async def answer(self, *args, **kwargs): pass
    async def edit_message_text(self, text, reply_markup, **kwargs): await self.message.reply_text(text, reply_markup=reply_markup, **kwargs)

# --- Admin Panel Main Sections (Restored) ---
@admin_required
async def admin_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    text=f"👑 *Admin Panel*\n\nWelcome, {escape_markdown(update.effective_user.first_name)}\\!"
    if update.callback_query: await try_edit_message(update.callback_query, text, await get_main_admin_keyboard())
    else: await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=await get_main_admin_keyboard())

@admin_required
async def stats_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    stats = database.get_bot_stats()
    acc_stats = "\n".join([f"  \\- `{s}`: {c}" for s,c in stats.get('accounts_by_status',{}).items()]) or "  \\- No accounts found\\."
    withdrawn_amount_str = escape_markdown(f'{stats.get("total_withdrawals_amount",0):.2f}')
    text = f"📊 *Bot Statistics*\n\n👤 *Users*\n  \\- Total: {stats.get('total_users',0)}\n  \\- Blocked: {stats.get('blocked_users',0)}\n\n💰 *Finance*\n  \\- Total Withdrawn: `${withdrawn_amount_str}`\n  \\- Withdrawal Count: {stats.get('total_withdrawals_count',0)}\n\n💳 *Accounts*\n  \\- Total: {stats.get('total_accounts',0)}\n{acc_stats}\n\n🌐 *Proxies*: {stats.get('total_proxies',0)}"
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]))

@admin_required
async def country_list_panel(update,context):
    if update.callback_query: await update.callback_query.answer()
    countries = database.get_countries_config()
    text = "🌍 *Country Management*\n\nSelect a country to configure its settings\\."
    kb = [[InlineKeyboardButton(f"{d.get('flag',' ')} {d.get('name','N/A')} \\({escape_markdown(d.get('code','N/A'))}\\)", callback_data=f"admin_country_view:{d.get('code','N/A')}")] for d in sorted(countries.values(),key=lambda x:x['name'])]
    kb.extend([[InlineKeyboardButton("➕ Add", callback_data="admin_conv_start:ADD_COUNTRY_CODE"), InlineKeyboardButton("➖ Del", callback_data="admin_conv_start:DELETE_COUNTRY_CODE")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def country_view_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    q, code = update.callback_query, update.callback_query.data.split(':')[-1]; country = database.get_country_by_code(code)
    if not country: await q.answer("Country not found!", show_alert=True); return await country_list_panel(update, context)
    c_count, cap = database.get_country_account_count(code), country.get('capacity',-1); cap_text = "Unlimited" if cap == -1 else f"{c_count}/{cap}"; cspam, gmail = ("✅ ON" if country.get('accept_restricted') == 'True' else "❌ OFF"), ("✅ ON" if country.get('accept_gmail') == 'True' else "❌ OFF")
    text = f"⚙️ *Configuration* {country.get('flag','') if country.get('flag') else ''} *{escape_markdown(country.get('name','N/A'))}*\n\n🌍 Country: `{escape_markdown(country.get('code','N/A'))}`\n💲 Base Price: `${escape_markdown(f'{country.get("price_ok",0.0):.2f}')}`\n🟢 Free: `${escape_markdown(f'{country.get("price_ok",0.0):.2f}')}`\n🟡 Register \\(Restricted\\): `${escape_markdown(f'{country.get("price_restricted",0.0):.2f}')}`\n🔴 Limit: `$0\\.00`\n📧 Gmail: *{gmail}*\n🛡️ CSpam: *{cspam}*\n📦 Capacity: *{escape_markdown(cap_text)}*\n⏳ Confirm Time: *{country.get('time',0)} seconds*"
    kb = [[InlineKeyboardButton("💲 Price (OK)", callback_data=f"admin_country_edit_start:{code}:price_ok"), InlineKeyboardButton("💲 Price (Restricted)", callback_data=f"admin_country_edit_start:{code}:price_restricted")], [InlineKeyboardButton("📧 Toggle Gmail", callback_data=f"admin_country_toggle_gmail:{code}"), InlineKeyboardButton("🛡️ Toggle CSpam", callback_data=f"admin_country_toggle_restricted:{code}")], [InlineKeyboardButton("📦 Capacity", callback_data=f"admin_country_edit_start:{code}:capacity"), InlineKeyboardButton("⏳ Time", callback_data=f"admin_country_edit_start:{code}:time")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_country_list")]]
    await try_edit_message(q, text, InlineKeyboardMarkup(kb))

@admin_required
async def settings_main_panel(update,context):
    if update.callback_query: await update.callback_query.answer()
    s = context.bot_data; get_status = lambda k, v='True': "✅ ON" if s.get(k,'False')==v else "❌ OFF"
    kb = [[InlineKeyboardButton(f"Spam Check: {get_status('enable_spam_check')}", callback_data="admin_toggle:enable_spam_check:True:False")], [InlineKeyboardButton(f"Device Check: {get_status('enable_device_check')}", callback_data="admin_toggle:enable_device_check:True:False")], [InlineKeyboardButton(f"Bot Status: {get_status('bot_status','ON')}", callback_data="admin_toggle:bot_status:ON:OFF")], [InlineKeyboardButton("✍️ Edit Text/Values", callback_data="admin_edit_values_list")], [InlineKeyboardButton("🌐 Proxy Management", callback_data="admin_proxies_main_page_1")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
    await try_edit_message(update.callback_query, "⚙️ *General Settings*", InlineKeyboardMarkup(kb))

@admin_required
async def finance_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    stats = database.get_bot_stats()
    withdrawn_amount_str = escape_markdown(f'{stats.get("total_withdrawals_amount",0):.2f}')
    text = f"💰 *Finance Overview*\n\n💸 Total Withdrawn: `${withdrawn_amount_str}` from {stats.get('total_withdrawals_count',0)} requests\\."
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup([[InlineKeyboardButton("📜 View Withdrawal History", callback_data="admin_withdrawal_main_page_1")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]))

@admin_required
async def withdrawal_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    page,limit,kb = int(update.callback_query.data.split('_')[-1]), 5, []
    w, total = database.get_all_withdrawals(page,limit), database.count_all_withdrawals()
    text = "📜 *Withdrawal History*\n\n"
    if not w: text += "No withdrawals found\\."
    else:
        status_emojis = {'pending': '⏳', 'completed': '✅'}
        for item in w: 
            ts = datetime.fromisoformat(item['timestamp']).strftime('%Y-%m-%d %H:%M') 
            status_emoji = status_emojis.get(item['status'], '❓')
            text += f"{status_emoji} `@{escape_markdown(item.get('username','N/A'))}` \\(`{item['user_id']}`\\)\n💰 Amount: `${escape_markdown(f'{item["amount"]:.2f}')}`\n📬 Address: `{escape_markdown(item['address'])}`\n🗓️ Date: `{escape_markdown(ts)}`\n" + "\\-"*20 + "\n"
    kb.extend(create_pagination_keyboard("admin_withdrawal_main_page", page, total, limit)); kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_finance_main")])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def confirm_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    stuck, error, reprocessing = database.get_stuck_pending_accounts(), database.get_error_accounts(), database.get_accounts_for_reprocessing()
    text = f"♻️ *Account Management*\n\nManage accounts that are stuck, have errors, or are awaiting reprocessing\\.\n\n⏳ Stuck \\(`pending_confirmation`\\): *{len(stuck)}*\n❗️ `error` status: *{len(error)}*\n⏰ Awaiting session termination: *{len(reprocessing)}*"
    kb = [[InlineKeyboardButton(f"🔄 Re-check all {len(stuck)+len(error)} stuck/error accounts", callback_data="admin_recheck_all")], [InlineKeyboardButton("🔍 Re-check by User ID", callback_data="admin_conv_start:RECHECK_BY_USER_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def broadcast_main_panel(update, context): await try_edit_message(update.callback_query, "📢 *Broadcast*", InlineKeyboardMarkup([[InlineKeyboardButton("✍️ Create Broadcast Message", callback_data="admin_conv_start:BROADCAST_MSG")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]]))

@admin_required
async def users_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    page, limit, kb = int(update.callback_query.data.split('_')[-1]), 5, []
    users, total_users = database.get_all_users(page,limit), database.count_all_users()
    total_pages = (total_users + limit - 1) // limit if total_users > 0 else 1
    text = f"👥 *User Management* \\(Page {page} / {total_pages}\\)\n\n"
    if not users: text += "No users found\\."
    else:
        for user in users: 
            status = "🔴 BLOCKED" if user['is_blocked'] else "🟢 ACTIVE"
            text += f"👤 `@{escape_markdown(user.get('username','N/A'))}` \\(`{user['telegram_id']}`\\)\n   Status: {status} \\| Accounts: {user['account_count']}\n"
    kb.extend(create_pagination_keyboard("admin_users_main_page", page, total_users, limit))
    kb.extend([[InlineKeyboardButton("🔍 Get Info", callback_data="admin_conv_start:GET_USER_INFO_ID")], [InlineKeyboardButton("🚫 Block", callback_data="admin_conv_start:BLOCK_USER_ID"), InlineKeyboardButton("✅ Unblock", callback_data="admin_conv_start:UNBLOCK_USER_ID")], [InlineKeyboardButton("💰 Adjust Balance", callback_data="admin_conv_start:ADJ_BALANCE_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def proxies_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    page, limit, kb = int(update.callback_query.data.split('_')[-1]), 10, []
    proxies, total_proxies = database.get_all_proxies(page,limit), database.count_all_proxies()
    text = f"🌐 *Proxy Management* \\(Total: {total_proxies}\\)\n\n" + (escape_markdown("\n".join([f"`{p['id']}`: `{p['proxy']}`" for p in proxies])) or "No proxies added\\.")
    kb.extend(create_pagination_keyboard("admin_proxies_main_page", page, total_proxies, limit))
    kb.extend([[InlineKeyboardButton("➕ Add Proxy", callback_data="admin_conv_start:ADD_PROXY"), InlineKeyboardButton("➖ Remove Proxy", callback_data="admin_conv_start:REMOVE_PROXY_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_settings_main")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def edit_values_list_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    settings, kb, text = context.bot_data, [], "✍️ *Edit Bot Settings*\n\nSelect a setting to change its value\\."
    exclude_keys = ['scheduler','user_topics','countries_config']; keys = sorted([k for k in settings.keys() if k not in exclude_keys])
    kb = [[InlineKeyboardButton(key, callback_data=f"admin_edit_setting_start:{key}")] for key in keys]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_settings_main")]); await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def admins_main_panel(update, context):
    if update.callback_query: await update.callback_query.answer()
    admins, text, kb = database.get_all_admins(), "⚠️ *Admin Management*", []
    for admin_user_db in admins:
        try: 
            chat = await context.bot.get_chat(admin_user_db['telegram_id']); text += f"\n\\- @{escape_markdown(chat.username)} \\(`{admin_user_db['telegram_id']}`\\)"
        except Exception: text += f"\n\\- ID: `{admin_user_db['telegram_id']}` \\(Could not fetch info\\)"
    kb.extend([[InlineKeyboardButton("➕ Add Admin", callback_data="admin_conv_start:ADD_ADMIN_ID"), InlineKeyboardButton("➖ Remove Admin", callback_data="admin_conv_start:REMOVE_ADMIN_ID")], [InlineKeyboardButton("🔥 Purge User Data", callback_data="admin_conv_start:DELETE_USER_DATA_ID")], [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")]])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))


# --- File Manager (Rebuilt with User-based Login) ---

ADMIN_SESSION_FILE = "admin_downloader.session"

@admin_required
async def fm_main_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    countries = database.get_countries_config()
    text = "🗂️ *File Manager*\n\nSelect a country to download sessions from\\."
    kb = []
    
    countries_with_accounts = [c for c in countries.values() if database.get_country_account_count(c['code']) > 0]

    if countries_with_accounts:
        for country in sorted(countries_with_accounts, key=lambda x: x['name']):
            kb.append([InlineKeyboardButton(f"{country['flag']} {country['name']}", callback_data=f"admin_fm_country:{country['code']}")])
    else:
        text += "\n\nNo accounts have been added yet for any country\\."
    
    kb.append([InlineKeyboardButton("💾 Download Database (bot.db)", callback_data="admin_fm_get_db")])
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])
    await try_edit_message(update.callback_query, text, InlineKeyboardMarkup(kb))

@admin_required
async def fm_choose_status_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    query = update.callback_query
    country_code = query.data.split(':')[-1]
    country = database.get_country_by_code(country_code)
    if not country:
        await query.answer("Country not found!", show_alert=True)
        return
    
    context.user_data['fm_country_code'] = country_code
    
    status_counts = database.get_country_account_counts_by_status(country_code)
    counts_dict = {item['status']: item['count'] for item in status_counts}
    total_sessions = sum(counts_dict.values())

    text = f"*{country['flag']} {escape_markdown(country['name'])}*\n\n"
    text += f"Total Sessions: *{total_sessions}*\n"
    text += "Select a status folder to download:"

    status_map = {
        'ok': '✅ OK', 'new': '📋 New', 'restricted': '⚠️ Restricted',
        'limited': '⏳ Limit', 'banned': '🚫 Banned', 'error': '❗️ Error'
    }

    keyboard = []
    for status_key, status_text in status_map.items():
        count = counts_dict.get(status_key, 0)
        if count > 0:
            keyboard.append([InlineKeyboardButton(f"{status_text} - {count}", callback_data=f"admin_fm_download:{status_key}")])

    keyboard.append([InlineKeyboardButton("« Back", callback_data="admin_fm_main")])
    await try_edit_message(query, text, InlineKeyboardMarkup(keyboard))

async def fm_download_sessions_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The core logic after a user account is authorized."""
    query = context.user_data.get('fm_query')
    status_to_fetch = context.user_data.get('fm_status')
    country_code = context.user_data.get('fm_country_code')

    if not all([query, status_to_fetch, country_code]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Critical error: Context lost during login. Please try again.")
        return ConversationHandler.END

    country = database.get_country_by_code(country_code)
    
    await query.message.reply_text(
        f"⏳ Logged in successfully. Fetching *{status_to_fetch.upper()}* sessions for *{escape_markdown(country['name'])}*\\.\\.\\. please wait\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

    client = TelegramClient(ADMIN_SESSION_FILE, int(context.bot_data['api_id']), context.bot_data['api_hash'])
    try:
        await client.connect()
        if not await client.is_user_authorized():
            if os.path.exists(ADMIN_SESSION_FILE): os.remove(ADMIN_SESSION_FILE)
            raise Exception("Admin session expired. Please try again to log in.")

        accounts_to_find = database.get_all_accounts_by_status_and_country(status_to_fetch, country_code)
        
        if not accounts_to_find:
            await query.message.reply_text(f"ℹ️ No session files are recorded in the database for this status and country.", parse_mode=ParseMode.MARKDOWN_V2)
            await client.disconnect()
            return ConversationHandler.END

        count = 0
        for acc in accounts_to_find:
             if acc.get('session_file') and os.path.exists(acc['session_file']):
                 await context.bot.send_document(
                     chat_id=query.from_user.id,
                     document=open(acc['session_file'], 'rb')
                 )
                 count += 1
                 await asyncio.sleep(0.1)

        if count > 0:
            await query.message.reply_text(f"✅ Sent *{count}* session file\\(s\\) from local storage.", parse_mode=ParseMode.MARKDOWN_V2)
        else:
            await query.message.reply_text(f"ℹ️ Could not find any matching session files on the server.", parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error(f"Failed to download sessions: {e}", exc_info=True)
        await query.message.reply_text(f"❌ An error occurred: {escape_markdown(str(e))}", parse_mode=ParseMode.MARKDOWN_V2)
    finally:
        if client.is_connected():
            await client.disconnect()

    context.user_data.clear()
    return ConversationHandler.END


# --- File Manager Login Conversation ---
async def fm_start_download_or_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data['fm_query'] = query
    context.user_data['fm_status'] = query.data.split(':')[-1]
    
    client = TelegramClient(ADMIN_SESSION_FILE, int(context.bot_data['api_id']), context.bot_data['api_hash'])
    await client.connect()

    if await client.is_user_authorized():
        await client.disconnect()
        return await fm_download_sessions_logic(update, context)
    
    await client.disconnect()
    await try_edit_message(
        query,
        "🗂️ *File Manager Login*\n\nTo download files, I need to log in with a regular user account. This account must be a member of the session channel. Please provide the phone number for this account.",
        None
    )
    return AdminState.FM_PHONE

async def fm_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    context.user_data['fm_phone'] = phone
    client = TelegramClient(ADMIN_SESSION_FILE, int(context.bot_data['api_id']), context.bot_data['api_hash'])
    
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        context.user_data['fm_phone_hash'] = sent_code.phone_code_hash
        await update.message.reply_text("Please send the login code you received.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nPlease try again or /cancel.")
        return AdminState.FM_PHONE
    finally:
        if client.is_connected():
            await client.disconnect()
            
    return AdminState.FM_CODE

async def fm_get_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    phone = context.user_data['fm_phone']
    phone_hash = context.user_data['fm_phone_hash']
    client = TelegramClient(ADMIN_SESSION_FILE, int(context.bot_data['api_id']), context.bot_data['api_hash'])

    try:
        await client.connect()
        await client.sign_in(phone, code, phone_code_hash=phone_hash)
        await client.disconnect()
        return await fm_download_sessions_logic(update, context)

    except SessionPasswordNeededError:
        await update.message.reply_text("This account has 2FA enabled. Please enter the password.")
        return AdminState.FM_PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nPlease /cancel and try again.")
        return ConversationHandler.END
    finally:
        if client.is_connected():
            await client.disconnect()

async def fm_get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    client = TelegramClient(ADMIN_SESSION_FILE, int(context.bot_data['api_id']), context.bot_data['api_hash'])
    
    try:
        await client.connect()
        await client.sign_in(password=password)
        await client.disconnect()
        return await fm_download_sessions_logic(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nPlease /cancel and try again.")
        return ConversationHandler.END
    finally:
        if client.is_connected():
            await client.disconnect()

# --- Other Handlers and Handler Registration ---

@admin_required
async def get_db_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    await context.bot.send_document(update.effective_chat.id, document=InputFile(database.DB_FILE, filename="bot.db"))

@admin_required
async def recheck_all_problematic_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    stuck, error = database.get_stuck_pending_accounts(), database.get_error_accounts(); accounts = list({acc['job_id']: acc for acc in stuck+error}.values())
    if not accounts: await update.callback_query.answer("✅ No problematic accounts found to re-check.", show_alert=True); return
    await try_edit_message(update.callback_query, f"⏳ Found {len(accounts)} accounts\\. Scheduling re-checks\\.\\.\\.", None)
    tasks = [login.schedule_initial_check(BOT_TOKEN, str(a['user_id']), a['user_id'], a['phone_number'], a['job_id']) for a in accounts]; await asyncio.gather(*tasks)
    await update.callback_query.message.reply_text(f"✅ Successfully scheduled *{len(accounts)}* accounts for a new check\\.", parse_mode=ParseMode.MARKDOWN_V2); await confirm_main_panel(update, context)

@admin_required
async def toggle_setting_handler(update, context):
    q, (_,key,on_v,off_v) = update.callback_query, update.callback_query.data.split(':'); current_val = context.bot_data.get(key); new_val = off_v if current_val == on_v else on_v
    database.set_setting(key, new_val); context.bot_data[key] = new_val
    await q.answer(f"Set {key} to {new_val}")
    await settings_main_panel(update, context)

@admin_required
async def toggle_accept_restricted(update, context):
    if update.callback_query: await update.callback_query.answer()
    code = update.callback_query.data.split(':')[-1]; country = database.get_country_by_code(code)
    if not country: return
    new_s = 'False' if country.get('accept_restricted') == 'True' else 'True'; database.update_country_value(code,'accept_restricted',new_s); context.bot_data['countries_config']=database.get_countries_config(); await country_view_panel(update, context)

@admin_required
async def toggle_gmail_handler(update, context):
    if update.callback_query: await update.callback_query.answer()
    code = update.callback_query.data.split(':')[-1]; country = database.get_country_by_code(code)
    if not country: return
    new_s = 'False' if country.get('accept_gmail') == 'True' else 'True'; database.update_country_value(code,'accept_gmail',new_s); context.bot_data['countries_config']=database.get_countries_config(); await country_view_panel(update, context)

@admin_required
async def confirm_withdrawal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    admin_user = update.effective_user
    try:
        withdrawal_id = int(query.data.split(':')[-1])
    except (IndexError, ValueError):
        await query.answer("Invalid request data.", show_alert=True)
        return
    if "PAID" in query.message.text:
        await query.answer("This withdrawal has already been processed.", show_alert=True)
        return
    
    await query.answer("Processing payment...")

    withdrawal_info = database.confirm_withdrawal(withdrawal_id)
    if not withdrawal_info:
        await query.answer("Error: Withdrawal not found or already processed.", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None) 
        return
    user_id = withdrawal_info['user_id']
    amount_str = escape_markdown(f"{withdrawal_info['amount']:.2f}")
    user_message = f"✅ Your withdrawal request of *${amount_str}* has been successfully paid\\."
    try:
        await context.bot.send_message(chat_id=user_id, text=user_message, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Could not send withdrawal confirmation to user {user_id}: {e}")
        await query.answer(f"User notification failed, but withdrawal is marked as paid. Error: {e}", show_alert=True)
    
    original_text = query.message.text_markdown_v2
    admin_username = escape_markdown(f"@{admin_user.username}" if admin_user.username else f"ID:{admin_user.id}")
    new_text = f"{original_text}\n\n*✅ PAID by {admin_username}*"
    await query.edit_message_text(text=new_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN_V2)

async def conv_starter(update, context):
    await update.callback_query.answer()
    q, action = update.callback_query, update.callback_query.data.split(':')[-1]
    prompts = {'GET_USER_INFO_ID':("Enter User ID:",AdminState.GET_USER_INFO_ID),'BLOCK_USER_ID':("Enter User ID to *BLOCK*:",AdminState.BLOCK_USER_ID),'UNBLOCK_USER_ID':("Enter User ID to *UNBLOCK*:",AdminState.UNBLOCK_USER_ID),'ADJ_BALANCE_ID':("Enter User ID to adjust balance for:",AdminState.ADJ_BALANCE_ID),'ADD_ADMIN_ID':("Enter Telegram ID of new admin:",AdminState.ADD_ADMIN_ID),'REMOVE_ADMIN_ID':("Enter Telegram ID of admin to remove:",AdminState.REMOVE_ADMIN_ID),'BROADCAST_MSG':("Send message to broadcast:",AdminState.BROADCAST_MSG),'ADD_PROXY':("Enter proxy \\(`ip:port` or `ip:port:user:pass`\\):",AdminState.ADD_PROXY),'REMOVE_PROXY_ID':("Enter ID of proxy to remove:",AdminState.REMOVE_PROXY_ID),'ADD_COUNTRY_CODE':("Step 1/7: Country code \\(e\\.g\\., `+44`\\):",AdminState.ADD_COUNTRY_CODE),'DELETE_COUNTRY_CODE':("Enter country code to delete:",AdminState.DELETE_COUNTRY_CODE),'DELETE_USER_DATA_ID':("🔥 Enter User ID to *PURGE ALL DATA*:",AdminState.DELETE_USER_DATA_ID),'RECHECK_BY_USER_ID':("Enter User's Telegram ID to re\\-check accounts:",AdminState.RECHECK_BY_USER_ID),}
    prompt, state = prompts.get(action, (None,None));
    if not prompt: logger.warning(f"Unhandled conv starter: {action}"); return ConversationHandler.END
    await try_edit_message(q, f"{prompt}\n\nType /cancel to abort\\.", None); return state

async def edit_setting_starter(update, context):
    await update.callback_query.answer()
    q, key = update.callback_query, update.callback_query.data.split(':')[-1]; context.user_data['edit_setting_key'] = key
    prompt = f"Editing *{escape_markdown(key)}*\\.\nCurrent value: `{escape_markdown(context.bot_data.get(key,'Not set'))}`\n\nPlease send the new value\\.\nType /cancel to abort\\."
    await try_edit_message(q, prompt, None); return AdminState.EDIT_SETTING_VALUE

async def country_edit_starter(update, context):
    await update.callback_query.answer()
    q, (_,code,key) = update.callback_query, update.callback_query.data.split(':'); context.user_data.update({'edit_country_code':code,'edit_country_key':key}); country=database.get_country_by_code(code)
    prompt = f"Editing *{escape_markdown(key)}* for *{escape_markdown(country.get('name'))}*\\.\nCurrent value: `{escape_markdown(str(country.get(key,'Not set')))}`\n\nPlease send the new value\\.\nType /cancel to abort\\."
    await try_edit_message(q, prompt, None); return AdminState.EDIT_COUNTRY_VALUE

def get_admin_handlers():
    async def main_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query or not query.data: return
        data = query.data
        
        panel_map = {
            'admin_panel': admin_panel, 'admin_stats': stats_panel, 'admin_country_list': country_list_panel, 
            'admin_users_main_page': users_main_panel, 'admin_settings_main': settings_main_panel, 
            'admin_finance_main': finance_main_panel, 'admin_withdrawal_main_page': withdrawal_main_panel, 
            'admin_broadcast_main': broadcast_main_panel,'admin_confirm_main': confirm_main_panel, 
            'admin_admins_main': admins_main_panel, 'admin_proxies_main_page': proxies_main_panel, 
            'admin_edit_values_list': edit_values_list_panel, 'admin_country_view': country_view_panel, 
            'admin_country_toggle_restricted': toggle_accept_restricted, 'admin_country_toggle_gmail': toggle_gmail_handler,
            'admin_fm_main': fm_main_panel, 'admin_fm_get_db': get_db_handler, 'admin_fm_country': fm_choose_status_panel,
            'admin_recheck_all': recheck_all_problematic_handler, 'admin_confirm_withdrawal': confirm_withdrawal_handler, 
        }
        
        handler_key = next((key for key in panel_map if data.startswith(key)), None)
        if handler_key:
            return await panel_map[handler_key](update, context)
        
        logger.warning(f"No route for admin callback: {data}")

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(conv_starter, pattern=r'^admin_conv_start:'),
            CallbackQueryHandler(edit_setting_starter, pattern=r'^admin_edit_setting_start:'),
            CallbackQueryHandler(country_edit_starter, pattern=r'^admin_country_edit_start:')
        ],
        states={
            # Add all your conversation states here
        },
        fallbacks=[CommandHandler('cancel',cancel_conv)],
        conversation_timeout=600, per_user=True, per_chat=True,
    )
    
    fm_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(fm_start_download_or_login, pattern=r'^admin_fm_download:')],
        states={
            AdminState.FM_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fm_get_phone)],
            AdminState.FM_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fm_get_code)],
            AdminState.FM_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, fm_get_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conv)],
        conversation_timeout=300, per_user=True, per_chat=True,
    )

    return [
        CommandHandler("admin", admin_panel), 
        CallbackQueryHandler(toggle_setting_handler, pattern=r'^admin_toggle:'), 
        conv_handler, 
        fm_conv_handler, 
        CallbackQueryHandler(main_router, pattern=r'^admin_')
    ]

# END OF FILE handlers/admin.py