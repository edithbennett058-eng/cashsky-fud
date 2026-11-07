#!/usr/bin/env python3
import os
import re
import sys
import time
import asyncio
import glob
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ChatAction, ParseMode, ChatMemberStatus
from fud import bind_apk, extract_app_name_from_apk, extract_icon_from_apk
try:
    from bson import ObjectId
except Exception:
    def ObjectId(x):
        return x

try:
    import certifi
    _TLS_CA = certifi.where()
except Exception:
    _TLS_CA = None

# Created inside main() — Python 3.12+ requires a running loop for asyncio primitives
processing_semaphore = None

# Set MONGO_URI in environment (do not leave <db_password> placeholders).
# Example:
#   set MONGO_URI=mongodb+srv://USER:PASS@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0
MONGO_URI = (os.getenv("MONGO_URI") or "mongodb+srv://anahiyo28_db_user:ghqGL8lk9rg3MwZ6@cluster0.rkz1fzp.mongodb.net/?appName=Cluster0").strip()
mongo_client = None
db = None
users_collection = None
queue_collection = None
settings_collection = None
codes_collection = None

def _try_mongo(uri, **extra):
    kw = {"serverSelectionTimeoutMS": 20000}
    kw.update(extra)
    if _TLS_CA and "tlsCAFile" not in kw:
        kw["tlsCAFile"] = _TLS_CA
    client = MongoClient(uri, **kw)
    client.admin.command("ping")
    return client

# AXION: force local JSON — skip noisy Mongo SSL errors on Python 3.14
# Set USE_MONGO=1 in environment only if you really want Atlas and your SSL works.
_USE_MONGO = (os.getenv("USE_MONGO") or "").strip() in ("1", "true", "True", "yes", "YES")
if _USE_MONGO and MONGO_URI and "<db_password>" not in MONGO_URI:
    _errs = []
    for label, extra in (
        ("certifi", {}),
        ("tlsAllowInvalidCertificates", {"tlsAllowInvalidCertificates": True}),
    ):
        try:
            mongo_client = _try_mongo(MONGO_URI, **extra)
            db = mongo_client["fuddi_v2"]
            users_collection = db["users"]
            queue_collection = db["queue"]
            settings_collection = db["settings"]
            codes_collection = db["codes"]
            print(f"MongoDB: connected ({label})")
            break
        except Exception as e:
            _errs.append(f"{label}: {e}")
            mongo_client = None
            db = None
            users_collection = None
            queue_collection = None
            settings_collection = None
            codes_collection = None
    else:
        print("DB mode: LOCAL JSON (Mongo SSL failed — using BOT_DB/*.json)")
else:
    print("DB mode: LOCAL JSON (BOT_DB/*.json)")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
# ADMIN_IDS from env "7630091970" or "1,2,3" else default
_admin_env = (os.getenv("ADMIN_IDS") or "7630091970").strip()
ADMIN_IDS = []
for _p in _admin_env.replace(";", ",").split(","):
    _p = _p.strip()
    if _p.isdigit():
        ADMIN_IDS.append(int(_p))
if not ADMIN_IDS:
    ADMIN_IDS = [7630091970]
CHANNEL_USERNAME = "@tuare150"   # must join first
CHANNEL_URL = "https://t.me/tuare150"
SUPPORT_URL = "https://t.me/AxyraJi150"
BOT_BRAND = "PlayRemove FUD"

# default plan prices (admin can change with /setprice)
DEFAULT_PLANS = {
    "weekly":  {"price": 20,  "days": 7,   "label": "Weekly"},
    "monthly": {"price": 50,  "days": 30,  "label": "Monthly"},
    "yearly":  {"price": 400, "days": 365, "label": "Yearly"},
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_DB_DIR = os.path.join(SCRIPT_DIR, "BOT_DB")
TEMP_DIR = os.path.join(BOT_DB_DIR, "temp_processing")
os.makedirs(TEMP_DIR, exist_ok=True)

import json as _json
_LOCAL_DB = Path(SCRIPT_DIR) / "BOT_DB" / "local_users.json"
_LOCAL_QUEUE = Path(SCRIPT_DIR) / "BOT_DB" / "local_queue.json"
_LOCAL_SETTINGS = Path(SCRIPT_DIR) / "BOT_DB" / "local_settings.json"
_LOCAL_CODES = Path(SCRIPT_DIR) / "BOT_DB" / "local_codes.json"

class _LocalColl:
    def __init__(self, path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]")
    def _load(self):
        try:
            return _json.loads(self.path.read_text())
        except Exception:
            return []
    def _save(self, data):
        self.path.write_text(_json.dumps(data, indent=2, default=str))
    def find_one(self, query):
        data = self._load()
        for doc in data:
            if all(str(doc.get(k)) == str(v) for k, v in query.items()):
                return doc
        return None
    def insert_one(self, doc):
        data = self._load()
        if "_id" not in doc:
            doc["_id"] = str(int(time.time() * 1000)) + str(len(data))
        data.append(doc)
        self._save(data)
        return type("R", (), {"inserted_id": doc.get("_id")})()
    def update_one(self, query, update, upsert=False):
        data = self._load()
        for i, doc in enumerate(data):
            if all(str(doc.get(k)) == str(v) for k, v in query.items()):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                data[i] = doc
                self._save(data)
                return
        if upsert:
            newdoc = dict(query)
            if "$set" in update:
                newdoc.update(update["$set"])
            if "$inc" in update:
                for k, v in update["$inc"].items():
                    newdoc[k] = newdoc.get(k, 0) + v
            data.append(newdoc)
            self._save(data)
    def delete_one(self, query):
        data = self._load()
        data = [d for d in data if not all(str(d.get(k)) == str(v) for k, v in query.items())]
        self._save(data)
    def count_documents(self, query):
        data = self._load()
        return sum(1 for d in data if all(str(d.get(k)) == str(v) for k, v in query.items()))
    def find(self, query=None):
        data = self._load()
        if not query:
            return data
        return [d for d in data if all(str(d.get(k)) == str(v) for k, v in query.items())]
    def delete_many(self, query):
        data = self._load()
        data = [d for d in data if not all(str(d.get(k)) == str(v) for k, v in query.items())]
        self._save(data)

_USING_LOCAL_DB = False
if users_collection is None:
    users_collection = _LocalColl(_LOCAL_DB)
    _USING_LOCAL_DB = True
if queue_collection is None:
    queue_collection = _LocalColl(_LOCAL_QUEUE)
    _USING_LOCAL_DB = True
if settings_collection is None:
    settings_collection = _LocalColl(_LOCAL_SETTINGS)
if codes_collection is None:
    codes_collection = _LocalColl(_LOCAL_CODES)
if _USING_LOCAL_DB:
    print("DB mode: LOCAL JSON (Python 3.14-friendly, no Atlas needed)")
else:
    print("DB mode: MongoDB")

# ---------- settings helpers ----------
def get_setting(key, default=None):
    doc = settings_collection.find_one({"_id": "config"}) or {}
    return doc.get(key, default)

def set_setting(key, value):
    settings_collection.update_one(
        {"_id": "config"},
        {"$set": {key: value}},
        upsert=True
    )

def get_plans():
    plans = get_setting("plans")
    if not plans:
        plans = DEFAULT_PLANS
        set_setting("plans", plans)
    return plans

def shop_enabled():
    return get_setting("shop_on", True)

def v2_enabled():
    return get_setting("v2_on", True)

def free_credit_on():
    return get_setting("free_credit_on", False)  # OFF by default

def free_credit_amount():
    return int(get_setting("free_credit_amount", 1))

# ========== UI options ==========
UI_OPTIONS = {
    "Playstore": "Playstore", "Simple": "Simple", "Dark UI": "Dark UI",
    "CyberEye": "CyberEye", "Base": "Base", "Hybrid": "Hybrid",
}
LANG_OPTIONS = {
    "English": "English", "हिंदी": "Hindi", "Português": "Portuguese",
    "中文": "Chinese", "Español": "Spanish", "Русский": "Russian",
    "العربية": "Arabic", "日本語": "Japanese",
}
UI_BUTTONS = ["▶ Playstore", "▶ Simple", "▶ Dark UI", "▶ CyberEye", "▶ Base", "▶ Hybrid"]
LANG_BUTTONS = ["🇬🇧 English", "🇮🇳 हिंदी", "🇧🇷 Português", "🇨🇳 中文",
                "🇪🇸 Español", "🇷🇺 Русский", "🇸🇦 العربية", "🇯🇵 日本語"]

def _ui_from_btn(text: str) -> str:
    t = text.replace("▶ ", "").strip()
    return UI_OPTIONS.get(t, t)

def _lang_from_btn(text: str) -> str:
    for btn, name in zip(LANG_BUTTONS, LANG_OPTIONS.values()):
        if text.strip() == btn or text.strip().endswith(btn.split(" ", 1)[-1]):
            return name
    for k, v in LANG_OPTIONS.items():
        if k in text:
            return v
    return "English"

def main_menu_keyboard(is_reseller=False, is_admin=False):
    rows = [
        [KeyboardButton("🔧 Build APK"), KeyboardButton("💎 Plans")],
        [KeyboardButton("👤 Profile"), KeyboardButton("❓ Help")],
    ]
    if is_reseller:
        rows.append([KeyboardButton("🏪 Reseller Panel")])
    if is_admin:
        rows.append([KeyboardButton("🛠 Admin Panel")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def ui_choice_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("▶ Playstore"), KeyboardButton("▶ Simple")],
            [KeyboardButton("▶ Dark UI"), KeyboardButton("▶ CyberEye")],
            [KeyboardButton("▶ Base"), KeyboardButton("▶ Hybrid")],
            [KeyboardButton("← Type"), KeyboardButton("✖ Cancel")],
        ],
        resize_keyboard=True,
    )

def lang_choice_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🇬🇧 English"), KeyboardButton("🇮🇳 हिंदी")],
            [KeyboardButton("🇧🇷 Português"), KeyboardButton("🇨🇳 中文")],
            [KeyboardButton("🇪🇸 Español"), KeyboardButton("🇷🇺 Русский")],
            [KeyboardButton("🇸🇦 العربية"), KeyboardButton("🇯🇵 日本語")],
            [KeyboardButton("← Back"), KeyboardButton("✖ Cancel")],
        ],
        resize_keyboard=True,
    )

def reseller_panel_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📦 My Stock"), KeyboardButton("💸 Sell Credits")],
            [KeyboardButton("📜 My Sales"), KeyboardButton("🔗 My Link")],
            [KeyboardButton("← Main Menu")],
        ],
        resize_keyboard=True,
    )

def admin_panel_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Add Reseller"), KeyboardButton("❌ Remove Reseller"), KeyboardButton("📋 Resellers")],
            [KeyboardButton("🔄 Toggle Reseller"), KeyboardButton("🔑 Set Token")],
            [KeyboardButton("🏷 Set Brand"), KeyboardButton("💬 Set Support"), KeyboardButton("📢 Set Force-Join")],
            [KeyboardButton("🎮 Reseller FUD Control")],
            [KeyboardButton("🛡 Dup Shield"), KeyboardButton("🚫 Ban User"), KeyboardButton("🔓 Unban User")],
            [KeyboardButton("🛒 Shop — ON"), KeyboardButton("🛑 Shop — OFF")],
            [KeyboardButton("💲 Set Price"), KeyboardButton("👁 Pack Show/Hide")],
            [KeyboardButton("🆕 New Codes"), KeyboardButton("✏ Custom Code"), KeyboardButton("📜 Code List")],
            [KeyboardButton("⚡ V2 — ON"), KeyboardButton("⏹ V2 — OFF")],
            [KeyboardButton("🎁 Free Credit ON"), KeyboardButton("🚫 Free Credit OFF"), KeyboardButton("💲 Set Amount")],
            [KeyboardButton("💙 Give All Free Users")],
            [KeyboardButton("💎 Give Premium"), KeyboardButton("💎 Remove Premium")],
            [KeyboardButton("⭐ Give Special"), KeyboardButton("⭐ Remove Special")],
            [KeyboardButton("← Main Menu")],
        ],
        resize_keyboard=True,
    )

def get_user_info(chat_id):
    return users_collection.find_one({'chat_id': str(chat_id)})

def ensure_user(chat_id):
    u = get_user_info(chat_id)
    if not u:
        credits = free_credit_amount() if free_credit_on() else 0
        users_collection.insert_one({
            'chat_id': str(chat_id),
            'user_type': 'free',
            'credits': credits,
            'stock': 0,
            'total_processed': 0,
            'total_sold': 0,
            'banned': False,
            'created_at': datetime.now().isoformat(),
        })
        u = get_user_info(chat_id)
    return u

def is_reseller(chat_id):
    u = get_user_info(chat_id) or {}
    return u.get('user_type') == 'reseller' or chat_id in ADMIN_IDS


def _log_sub_history(chat_id, plan_type, granted_iso, expiry_iso):
    """Append a subscription grant record to the user's sub_history list."""
    try:
        u = get_user_info(chat_id) or {}
        history = u.get('sub_history') or []
        history.append({
            'plan': plan_type,
            'granted': granted_iso,
            'expiry': expiry_iso,
        })
        users_collection.update_one(
            {'chat_id': str(chat_id)},
            {'$set': {'sub_history': history}}
        )
    except Exception:
        pass


def get_sub_recall_status(user):
    """
    Returns a plain-text subscription status line for this user.
    Works even if they were downgraded to free — checks sub_history and expiry field.
    Returns None if the user has never had a paid plan.
    """
    if not user:
        return None
    ut = user.get('user_type', 'free')
    now = datetime.now()

    # Currently on a paid plan
    if ut in ('premium', 'specialpremium', 'reseller'):
        expiry = user.get('expiry', '')
        if expiry:
            try:
                exp_dt = datetime.fromisoformat(expiry)
                days_left = (exp_dt - now).days
                if days_left >= 0:
                    return f"Active {ut} — {days_left}d left (exp {exp_dt.strftime('%Y-%m-%d')})"
                else:
                    return f"Expired {ut} — expired {exp_dt.strftime('%Y-%m-%d')}"
            except Exception:
                pass
        return f"Active {ut}"

    # Currently free — check if they were ever a subscriber
    history = user.get('sub_history') or []
    # Also check if they have an expiry field (auto-downgraded by bot)
    legacy_expiry = user.get('expiry', '')
    if not history and not legacy_expiry:
        return None  # never subscribed

    if history:
        last = history[-1]
        plan = last.get('plan', 'premium')
        exp = last.get('expiry', '')[:10]
        granted = last.get('granted', '')[:10]
        total = len(history)
        return f"Former {plan} subscriber — last: {granted} to {exp} ({total} plan{'s' if total != 1 else ''} total)"

    # legacy: has expiry but no sub_history (pre-history update)
    try:
        exp_dt = datetime.fromisoformat(legacy_expiry)
        return f"Former subscriber — expired {exp_dt.strftime('%Y-%m-%d')}"
    except Exception:
        return "Former subscriber"

def is_banned(chat_id):
    u = get_user_info(chat_id) or {}
    return bool(u.get('banned'))


def check_user_plan(chat_id):
    user = ensure_user(chat_id)
    if user.get('banned'):
        return 'banned', False, "🚫 You are banned."
    # AXION: Admin is always unlimited
    if chat_id in ADMIN_IDS:
        return 'admin', True, None
    user_type = user.get('user_type', 'free')

    if user_type == 'reseller':
        credits = user.get('credits', 0)
        if credits > 0:
            return 'reseller', True, None
        return 'reseller', False, "❌ No personal credits left."

    if user_type == 'premium':
        expiry = user.get('expiry', '')
        if expiry:
            try:
                if datetime.fromisoformat(expiry) < datetime.now():
                    _log_sub_history(chat_id, 'premium', user.get('sub_granted', expiry), expiry)
                    users_collection.update_one(
                        {'chat_id': str(chat_id)},
                        {'$set': {'user_type': 'free', 'credits': 0}}
                    )
                    return 'free', False, None
            except Exception:
                pass
        return 'premium', True, None

    if user_type == 'specialpremium':
        expiry = user.get('expiry', '')
        if expiry:
            try:
                if datetime.fromisoformat(expiry) < datetime.now():
                    _log_sub_history(chat_id, 'specialpremium', user.get('sub_granted', expiry), expiry)
                    users_collection.update_one(
                        {'chat_id': str(chat_id)},
                        {'$set': {'user_type': 'free', 'credits': 0}}
                    )
                    return 'free', False, None
            except Exception:
                pass
        today = datetime.now().strftime('%Y-%m-%d')
        last_reset = user.get('last_reset', '')
        daily_count = user.get('daily_count', 0)
        if last_reset != today:
            users_collection.update_one(
                {'chat_id': str(chat_id)},
                {'$set': {'daily_count': 0, 'last_reset': today}}
            )
            daily_count = 0
        if daily_count >= 3:
            return 'specialpremium', False, "❌ Daily limit reached (3/3)."
        return 'specialpremium', True, None

    if user_type == 'credit':
        credits = user.get('credits', 0)
        if credits > 0:
            return 'credit', True, None
        return 'credit', False, None

    credits = user.get('credits', 0)
    if credits > 0:
        return 'free', True, None
    return 'free', False, None

def deduct_credit(chat_id):
    # AXION: Admin never loses credits
    if chat_id in ADMIN_IDS:
        return True
    user = get_user_info(chat_id)
    if not user:
        return False
    user_type = user.get('user_type', 'free')
    today = datetime.now().strftime('%Y-%m-%d')
    last_date = user.get('last_processed_date', '')
    today_count = 0 if last_date != today else user.get('today_processed', 0)

    if user_type == 'premium':
        users_collection.update_one(
            {'chat_id': str(chat_id)},
            {'$inc': {'total_processed': 1},
             '$set': {'last_processed_date': today, 'today_processed': today_count + 1}}
        )
        return True
    if user_type == 'specialpremium':
        users_collection.update_one(
            {'chat_id': str(chat_id)},
            {'$inc': {'daily_count': 1, 'total_processed': 1},
             '$set': {'last_processed_date': today, 'today_processed': today_count + 1}}
        )
        return True
    users_collection.update_one(
        {'chat_id': str(chat_id)},
        {'$inc': {'credits': -1, 'total_processed': 1},
         '$set': {'last_processed_date': today, 'today_processed': today_count + 1}}
    )
    return True

def plan_label(chat_id):
    if chat_id in ADMIN_IDS:
        return "🛠 Admin · Unlimited"
    user = get_user_info(chat_id) or {}
    ut = user.get('user_type', 'free')
    if ut == 'premium':
        return "💎 Premium"
    if ut == 'specialpremium':
        rem = max(0, 3 - user.get('daily_count', 0))
        return f"⭐ Special Premium · {rem}/3 today"
    if ut == 'reseller':
        return f"🏪 Reseller · stock {user.get('stock', 0)} · credits {user.get('credits', 0)}"
    credits = user.get('credits', 0)
    if ut == 'credit':
        return f"💳 Credit · {credits} left"
    return f"🆓 Free · {credits} left"

# ---------- channel gate ----------
async def is_member_of_channel(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            "member", "administrator", "creator",
        )
    except Exception:
        # if bot is not admin in channel, treat as joined so bot still works
        return True

async def require_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if user can continue, False if blocked by channel gate."""
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        return True
    if await is_member_of_channel(context.bot, user_id):
        return True
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I've joined", callback_data="check_join")],
    ])
    await update.effective_message.reply_text(
        "🔒 Join our channel to continue\n\n"
        "You must join the channel below before using this bot.\n"
        "After joining, tap I've joined.",
        reply_markup=kb,
    )
    return False

# ===================== COMMANDS =====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if is_banned(chat_id):
        await update.message.reply_text("🚫 You are banned.")
        return

    # referral
    if context.args and context.args[0].startswith("ref_"):
        ref_id = context.args[0][4:]
        ensure_user(chat_id)
        u = get_user_info(chat_id)
        if u and not u.get('referred_by'):
            users_collection.update_one(
                {'chat_id': str(chat_id)},
                {'$set': {'referred_by': str(ref_id)}}
            )

    if not await require_channel(update, context):
        return

    ensure_user(chat_id)
    first_name = update.effective_user.first_name or "User"
    u = get_user_info(chat_id)
    free_left = u.get('credits', 0) if u.get('user_type') in ('free', 'credit') else 0
    brand = get_setting("brand", BOT_BRAND)

    sub_line = ""
    recall = get_sub_recall_status(u)
    if recall:
        sub_line = f"\n\n📋 Sub status: {recall}"

    msg = (
        f"👋 Welcome to {brand}\n\n"
        f"🎁 You have {free_left} free build{'s' if free_left != 1 else ''} to start."
        f"{sub_line}\n\n"
        f"📌 Quick commands:\n"
        f"• /build — start a build\n"
        f"• /plans — subscriptions\n"
        f"• /profile — your status\n"
        f"• /help — support\n"
        f"• /cancel — leave the queue / reset session"
    )
    await update.message.reply_text(
        msg,
        reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS),
    )
    _ann = (get_setting("announce_text", "") or "").strip()
    if _ann:
        try:
            await update.message.reply_text(f"📢 {_ann}")
        except Exception:
            pass

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if await is_member_of_channel(context.bot, user_id):
        await query.edit_message_text("✅ Channel joined. Send /start to continue.")
    else:
        await query.answer("Still not joined. Join the channel first.", show_alert=True)

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await require_channel(update, context):
        return
    user = ensure_user(chat_id)
    plan = plan_label(chat_id)
    lines = [
        f"👤 Profile\n",
        f"🆔 `{chat_id}`",
        f"📋 Plan: {plan}",
        f"📦 Total processed: {user.get('total_processed', 0)}",
    ]
    if user.get('user_type') == 'reseller':
        lines.append(f"📦 Stock: {user.get('stock', 0)}")
        lines.append(f"💸 Total sold: {user.get('total_sold', 0)}")
        lines.append(f"💳 Personal credits: {user.get('credits', 0)}")
    if user.get('referred_by'):
        lines.append(f"🔗 Referred by: `{user.get('referred_by')}`")
    # Sub recall — full history
    history = user.get('sub_history') or []
    if history:
        lines.append(f"\n📜 Sub history ({len(history)} plan{'s' if len(history) != 1 else ''}):")
        for entry in history[-5:]:  # show last 5
            p = entry.get('plan', '?')
            g = (entry.get('granted') or '')[:10]
            e = (entry.get('expiry') or '')[:10]
            lines.append(f"  • {p}: {g} → {e}")
    elif user.get('expiry') and user.get('user_type') == 'free':
        try:
            exp_dt = datetime.fromisoformat(user['expiry'])
            lines.append(f"\n📜 Former subscriber — expired {exp_dt.strftime('%Y-%m-%d')}")
        except Exception:
            pass
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS)
    )

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await require_channel(update, context):
        return
    if not shop_enabled():
        await update.message.reply_text("🛒 Shop is currently OFF. Contact support.")
        return
    plans = get_plans()
    lines = ["💎 Plans\n"]
    for key in ("weekly", "monthly", "yearly"):
        p = plans.get(key, DEFAULT_PLANS[key])
        lines.append(f"• {p['label']} — ${p['price']} / {key} · ∞ builds")
    lines.append("\n👇 Pick a plan:")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Weekly · ${plans.get('weekly', DEFAULT_PLANS['weekly'])['price']}", callback_data="plan_weekly")],
        [InlineKeyboardButton(f"Monthly · ${plans.get('monthly', DEFAULT_PLANS['monthly'])['price']}", callback_data="plan_monthly")],
        [InlineKeyboardButton(f"Yearly · ${plans.get('yearly', DEFAULT_PLANS['yearly'])['price']}", callback_data="plan_yearly")],
        [InlineKeyboardButton("✖ Cancel", callback_data="plan_cancel")],
    ])
    await update.message.reply_text("\n".join(lines), reply_markup=kb)

async def plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "plan_cancel":
        await query.edit_message_text("Cancelled.")
        return
    key = data.replace("plan_", "")
    plans = get_plans()
    p = plans.get(key, DEFAULT_PLANS.get(key))
    if not p:
        await query.edit_message_text("Unknown plan.")
        return
    support = get_setting("support", SUPPORT_URL)
    await query.edit_message_text(
        f"💎 {p['label']} — ${p['price']}\n\n"
        f"∞ builds for {p['days']} days.\n\n"
        f"To pay / activate, contact support:\n{support}\n\n"
        f"Send your Chat ID + plan name."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_channel(update, context):
        return
    support = get_setting("support", SUPPORT_URL)
    await update.message.reply_text(
        "❓ Help\n\n"
        "1. Join channel (required)\n"
        "2. /build or 🔧 Build APK\n"
        "3. Choose UI + language\n"
        "4. Send APK (max 20 MB)\n"
        "5. Get protected APK\n\n"
        f"Support: {support}"
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "✅ Session reset.",
        reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS)
    )

async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_channel(update, context):
        return
    await show_choose_ui(update, context)

# ---------- admin core ----------
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "🛠 Admin Panel",
        reply_markup=admin_panel_keyboard()
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    all_users = list(users_collection.find({}))
    total = len(all_users)
    prem = sum(1 for u in all_users if u.get('user_type') == 'premium')
    special = sum(1 for u in all_users if u.get('user_type') == 'specialpremium')
    credit = sum(1 for u in all_users if u.get('user_type') == 'credit')
    resellers = sum(1 for u in all_users if u.get('user_type') == 'reseller')
    banned = sum(1 for u in all_users if u.get('banned'))
    free = total - prem - special - credit - resellers
    q = queue_collection.count_documents({'status': {'$in': ['pending', 'processing']}})
    await update.message.reply_text(
        f"📊 Stats\n\nUsers: {total}\n"
        f"Premium: {prem} | Special: {special}\n"
        f"Credit: {credit} | Reseller: {resellers}\n"
        f"Free: {free} | Banned: {banned}\n"
        f"Queue: {q}\n"
        f"Shop: {'ON' if shop_enabled() else 'OFF'} | V2: {'ON' if v2_enabled() else 'OFF'}"
    )

async def clearqueue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    queue_collection.delete_many({})
    await update.message.reply_text("✅ Queue cleared.")

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /premium <chat_id> <days>")
        return
    try:
        target = str(context.args[0])
        days = int(context.args[1])
        granted_iso = datetime.now().isoformat()
        expiry = (datetime.now() + timedelta(days=days)).isoformat()
        ensure_user(target)
        users_collection.update_one(
            {'chat_id': target},
            {'$set': {'user_type': 'premium', 'expiry': expiry, 'credits': 0, 'sub_granted': granted_iso}},
            upsert=True
        )
        _log_sub_history(target, 'premium', granted_iso, expiry)
        await update.message.reply_text(f"✅ Premium → {target} · {days}d")
        try:
            await context.bot.send_message(int(target), f"💎 Premium activated for {days} days!")
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def removepremium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removepremium <chat_id>")
        return
    target = str(context.args[0])
    users_collection.update_one({'chat_id': target}, {'$set': {'user_type': 'free', 'credits': 0}})
    await update.message.reply_text(f"✅ Premium removed from {target}")

async def specialpremium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /specialpremium <chat_id> <days>")
        return
    try:
        target = str(context.args[0])
        days = int(context.args[1])
        granted_iso = datetime.now().isoformat()
        expiry = (datetime.now() + timedelta(days=days)).isoformat()
        ensure_user(target)
        users_collection.update_one(
            {'chat_id': target},
            {'$set': {
                'user_type': 'specialpremium', 'expiry': expiry,
                'daily_count': 0, 'last_reset': datetime.now().strftime('%Y-%m-%d'),
                'sub_granted': granted_iso
            }},
            upsert=True
        )
        _log_sub_history(target, 'specialpremium', granted_iso, expiry)
        await update.message.reply_text(f"✅ Special Premium → {target} · {days}d")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def removespecialpremium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removespecialpremium <chat_id>")
        return
    target = str(context.args[0])
    users_collection.update_one({'chat_id': target}, {'$set': {'user_type': 'free', 'credits': 0}})
    await update.message.reply_text(f"✅ Special removed from {target}")

async def credit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /credit <chat_id> <amount>")
        return
    try:
        target = str(context.args[0])
        amount = int(context.args[1])
        ensure_user(target)
        users_collection.update_one(
            {'chat_id': target},
            {'$set': {'user_type': 'credit'}, '$inc': {'credits': amount}},
            upsert=True
        )
        await update.message.reply_text(f"✅ +{amount} credits → {target}")
        try:
            await context.bot.send_message(int(target), f"💳 You received {amount} credits.")
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def removecredit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removecredit <chat_id>")
        return
    target = str(context.args[0])
    users_collection.update_one({'chat_id': target}, {'$set': {'credits': 0}})
    await update.message.reply_text(f"✅ Credits zeroed for {target}")

# reseller admin
async def addreseller_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addreseller <chat_id> <stock>")
        return
    try:
        target = str(context.args[0])
        stock = int(context.args[1])
        ensure_user(target)
        users_collection.update_one(
            {'chat_id': target},
            {'$set': {'user_type': 'reseller', 'stock': stock, 'total_sold': 0}},
            upsert=True
        )
        await update.message.reply_text(f"✅ Reseller {target} · stock {stock}")
        try:
            await context.bot.send_message(
                int(target),
                f"🏪 You are now a Reseller!\n📦 Stock: {stock}\nUse 🏪 Reseller Panel or /sell <id> <credits>"
            )
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def removereseller_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removereseller <chat_id>")
        return
    target = str(context.args[0])
    users_collection.update_one({'chat_id': target}, {'$set': {'user_type': 'free', 'stock': 0}})
    await update.message.reply_text(f"✅ Reseller removed: {target}")

async def giveresellerstock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /giveresellerstock <chat_id> <amount>")
        return
    try:
        target = str(context.args[0])
        amount = int(context.args[1])
        u = get_user_info(target)
        if not u or u.get('user_type') != 'reseller':
            await update.message.reply_text("❌ Not a reseller. /addreseller first.")
            return
        users_collection.update_one({'chat_id': target}, {'$inc': {'stock': amount}})
        new_stock = (u.get('stock', 0) or 0) + amount
        await update.message.reply_text(f"✅ +{amount} stock → {target}. Now {new_stock}")
        try:
            await context.bot.send_message(int(target), f"📦 +{amount} stock. Now {new_stock}.")
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def listresellers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    resellers = [u for u in users_collection.find({}) if u.get('user_type') == 'reseller']
    if not resellers:
        await update.message.reply_text("No resellers.")
        return
    lines = [f"`{u.get('chat_id')}` · stock {u.get('stock', 0)} · sold {u.get('total_sold', 0)}" for u in resellers[:50]]
    await update.message.reply_text("Resellers:\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def listusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    users = list(users_collection.find({}))[:50]
    lines = [f"`{u.get('chat_id')}` · {u.get('user_type')} · c={u.get('credits', 0)} · ban={u.get('banned', False)}" for u in users]
    await update.message.reply_text("Users:\n" + "\n".join(lines) if lines else "No users", parse_mode=ParseMode.MARKDOWN)


async def subscribers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: full subscriber list grouped by plan, with expiry status."""
    if update.effective_chat.id not in ADMIN_IDS:
        return
    all_users = list(users_collection.find({}))
    now = datetime.utcnow()

    premium, special, resellers, former, free_users = [], [], [], [], []

    for u in all_users:
        ut = u.get('user_type', 'free')
        cid = u.get('chat_id', '?')
        created = (u.get('created_at') or '')[:10] or '?'
        expiry_raw = u.get('expiry')
        processed = u.get('total_processed', 0)
        banned = u.get('banned', False)
        history = u.get('sub_history') or []

        if expiry_raw:
            try:
                exp_dt = datetime.fromisoformat(str(expiry_raw).replace('Z', '').split('+')[0])
                expired = exp_dt < now
                exp_str = exp_dt.strftime('%Y-%m-%d')
                status_icon = 'EXPIRED' if expired else 'ACTIVE'
            except Exception:
                exp_str = str(expiry_raw)[:10]
                status_icon = '?'
                expired = False
            exp_line = f"  {status_icon} · exp {exp_str}"
        else:
            exp_line = ''
            expired = False

        ban_tag = ' [BANNED]' if banned else ''
        line = f"`{cid}`{ban_tag} · joined {created} · {processed} builds{exp_line}"

        if ut == 'premium':
            premium.append(line)
        elif ut == 'specialpremium':
            special.append(line)
        elif ut == 'reseller':
            resellers.append(line)
        else:
            # Check if this free user was ever a subscriber
            is_former = bool(history) or bool(expiry_raw)
            if is_former:
                # Build a former-subscriber line with last plan info
                if history:
                    last = history[-1]
                    last_plan = last.get('plan', 'premium')
                    last_exp = (last.get('expiry') or '')[:10]
                    total_plans = len(history)
                    former_line = f"`{cid}`{ban_tag} · {processed} builds · last {last_plan} exp {last_exp} ({total_plans} total)"
                else:
                    former_line = f"`{cid}`{ban_tag} · {processed} builds · {exp_line.strip()}"
                former.append(former_line)
            else:
                free_users.append(line)

    sections = []
    if premium:
        sections.append(f"💎 PREMIUM ({len(premium)})\n" + "\n".join(premium))
    if special:
        sections.append(f"⭐ SPECIAL PREMIUM ({len(special)})\n" + "\n".join(special))
    if resellers:
        sections.append(f"🏪 RESELLERS ({len(resellers)})\n" + "\n".join(resellers))
    if former:
        sections.append(f"📜 FORMER SUBSCRIBERS ({len(former)})\n" + "\n".join(former))

    free_preview = free_users[:30]
    free_extra = len(free_users) - len(free_preview)
    free_block = "\n".join(free_preview)
    if free_extra > 0:
        free_block += f"\n... +{free_extra} more free"
    if free_users:
        sections.append(f"👤 FREE ({len(free_users)})\n{free_block}")

    active_count = len(premium) + len(special) + len(resellers)
    total = len(all_users)
    header = f"📊 All Users: {total} total · {active_count} active paid · {len(former)} former\n\n"
    full_text = header + "\n\n".join(sections) if sections else "No users yet."

    for i in range(0, len(full_text), 4000):
        chunk = full_text[i:i+4000]
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


async def check_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    """Daily job: auto-notify expired premium/special users and alert admin."""
    now = datetime.utcnow()
    all_users = list(users_collection.find({}))
    newly_expired = []

    for u in all_users:
        ut = u.get('user_type', 'free')
        if ut not in ('premium', 'special'):
            continue
        expiry_raw = u.get('expiry')
        if not expiry_raw:
            continue
        try:
            exp_dt = datetime.fromisoformat(str(expiry_raw).replace('Z', '').split('+')[0])
        except Exception:
            continue
        if exp_dt >= now:
            continue  # still active

        cid = u.get('chat_id')
        newly_expired.append((cid, ut, str(expiry_raw)[:10]))

        # Notify the user
        try:
            await context.bot.send_message(
                chat_id=int(cid),
                text=(
                    "Your subscription has expired.\n\n"
                    "You have been moved to the free plan.\n"
                    "Contact admin to renew your access."
                )
            )
        except Exception:
            pass

    # Alert admin with summary
    if newly_expired:
        lines = [f"`{cid}` ({ut}) expired {exp}" for cid, ut, exp in newly_expired]
        msg = f"Expired subscriptions ({len(newly_expired)}):\n" + "\n".join(lines)
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass

async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /userinfo <chat_id>")
        return
    u = get_user_info(context.args[0])
    await update.message.reply_text(str(u) if u else "Not found")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: drop a message to all users."""
    if update.effective_chat.id not in ADMIN_IDS:
        return
    text = " ".join(context.args) if context.args else None
    if not text:
        await update.message.reply_text(
            "Drop message to all users:\n"
            "/broadcast Your message here\n\n"
            "Save update notice (also on /start):\n"
            "/announce Your update text\n"
            "/clearannounce"
        )
        return
    users = list(users_collection.find({}))
    ok = 0
    fail = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=int(u["chat_id"]), text=f"📢 Update\n\n{text}")
            ok += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"✅ Sent {ok}/{len(users)} (failed {fail})")


async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: sticky update + broadcast."""
    if update.effective_chat.id not in ADMIN_IDS:
        return
    text = " ".join(context.args) if context.args else None
    if not text:
        cur = get_setting("announce_text", "") or ""
        await update.message.reply_text(
            "Usage: /announce <message>\n"
            f"Current: {cur or '(none)'}"
        )
        return
    set_setting("announce_text", text)
    users = list(users_collection.find({}))
    ok = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=int(u["chat_id"]), text=f"📢 Update\n\n{text}")
            ok += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Announce saved + sent {ok}/{len(users)}")


async def clearannounce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    set_setting("announce_text", "")
    await update.message.reply_text("✅ Cleared announce.")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /ban <chat_id>")
        return
    target = str(context.args[0])
    ensure_user(target)
    users_collection.update_one({'chat_id': target}, {'$set': {'banned': True}})
    await update.message.reply_text(f"🚫 Banned {target}")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /unban <chat_id>")
        return
    target = str(context.args[0])
    users_collection.update_one({'chat_id': target}, {'$set': {'banned': False}})
    await update.message.reply_text(f"🔓 Unbanned {target}")

async def setprice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setprice <weekly|monthly|yearly> <price>\nExample: /setprice weekly 20")
        return
    key = context.args[0].lower()
    if key not in ("weekly", "monthly", "yearly"):
        await update.message.reply_text("Key must be weekly / monthly / yearly")
        return
    try:
        price = int(context.args[1])
        plans = get_plans()
        plans[key]["price"] = price
        set_setting("plans", plans)
        await update.message.reply_text(f"✅ {key} price set to ${price}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def setbrand_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /setbrand <name>")
        return
    name = " ".join(context.args)
    set_setting("brand", name)
    await update.message.reply_text(f"✅ Brand set to: {name}")

async def setsupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /setsupport <url or @user>")
        return
    set_setting("support", context.args[0])
    await update.message.reply_text(f"✅ Support set to: {context.args[0]}")

async def setforcejoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text(f"Current force-join channel: {CHANNEL_USERNAME}\nUsage: /setforcejoin @channel")
        return
    # note: runtime CHANNEL_USERNAME is const; store override
    set_setting("force_join", context.args[0])
    await update.message.reply_text(f"✅ Force-join channel set to: {context.args[0]} (restart to fully apply if needed)")

async def setamount_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /setamount <n>  (free credit amount for new users)")
        return
    try:
        n = int(context.args[0])
        set_setting("free_credit_amount", n)
        await update.message.reply_text(f"✅ Free credit amount = {n}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def giveallfree_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    amount = free_credit_amount()
    if context.args:
        try:
            amount = int(context.args[0])
        except Exception:
            pass
    users = list(users_collection.find({}))
    n = 0
    for u in users:
        if u.get('user_type') in ('free', 'credit', None):
            users_collection.update_one(
                {'chat_id': u['chat_id']},
                {'$inc': {'credits': amount}, '$set': {'user_type': 'credit'}}
            )
            n += 1
    await update.message.reply_text(f"✅ Gave {amount} credits to {n} free/credit users.")

# codes
async def newcodes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /newcodes <count> <credits_each>\nExample: /newcodes 5 3")
        return
    try:
        count = int(context.args[0])
        credits = int(context.args[1])
        import random, string
        created = []
        for _ in range(min(count, 50)):
            code = "CR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            codes_collection.insert_one({
                "code": code, "credits": credits, "used": False,
                "created_at": datetime.now().isoformat()
            })
            created.append(code)
        await update.message.reply_text(
            f"✅ Created {len(created)} codes ({credits} credits each):\n" +
            "\n".join(f"`{c}`" for c in created),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def customcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /customcode <CODE> <credits>")
        return
    code = context.args[0].upper()
    credits = int(context.args[1])
    codes_collection.insert_one({
        "code": code, "credits": credits, "used": False,
        "created_at": datetime.now().isoformat()
    })
    await update.message.reply_text(f"✅ Code `{code}` = {credits} credits", parse_mode=ParseMode.MARKDOWN)

async def codelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in ADMIN_IDS:
        return
    codes = [c for c in codes_collection.find({}) if not c.get('used')][:30]
    if not codes:
        await update.message.reply_text("No active codes.")
        return
    lines = [f"`{c['code']}` · {c.get('credits', 0)} cr" for c in codes]
    await update.message.reply_text("Active codes:\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await require_channel(update, context):
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /redeem <CODE>")
        return
    code = context.args[0].upper()
    doc = codes_collection.find_one({"code": code})
    if not doc:
        await update.message.reply_text("❌ Invalid code.")
        return
    if doc.get("used"):
        await update.message.reply_text("❌ Code already used.")
        return
    credits = int(doc.get("credits", 0))
    ensure_user(chat_id)
    users_collection.update_one(
        {'chat_id': str(chat_id)},
        {'$inc': {'credits': credits}, '$set': {'user_type': 'credit'}}
    )
    codes_collection.update_one({"code": code}, {"$set": {"used": True, "used_by": str(chat_id)}})
    await update.message.reply_text(f"✅ Redeemed! +{credits} credits.")

# reseller user cmds
async def mystock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    u = ensure_user(chat_id)
    if u.get('user_type') != 'reseller' and chat_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Reseller only.")
        return
    await update.message.reply_text(
        f"📦 Stock: {u.get('stock', 0)}\n💸 Sold: {u.get('total_sold', 0)}\n💳 Personal: {u.get('credits', 0)}"
    )

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    u = ensure_user(chat_id)
    if u.get('user_type') != 'reseller' and chat_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Reseller only.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /sell <user_chat_id> <credits>")
        return
    try:
        target = str(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            await update.message.reply_text("Amount must be > 0")
            return
        stock = u.get('stock', 0) or 0
        if chat_id not in ADMIN_IDS and stock < amount:
            await update.message.reply_text(f"❌ Stock {stock} only.")
            return
        ensure_user(target)
        if chat_id not in ADMIN_IDS:
            users_collection.update_one(
                {'chat_id': str(chat_id)},
                {'$inc': {'stock': -amount, 'total_sold': amount}}
            )
        target_u = get_user_info(target)
        keep = target_u.get('user_type') if target_u and target_u.get('user_type') in ('premium', 'specialpremium', 'reseller') else 'credit'
        users_collection.update_one(
            {'chat_id': target},
            {'$set': {'user_type': keep if keep != 'free' else 'credit'}, '$inc': {'credits': amount}},
            upsert=True
        )
        left = max(0, stock - amount) if chat_id not in ADMIN_IDS else "∞"
        await update.message.reply_text(f"✅ Sold {amount} → `{target}` · stock left {left}", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(int(target), f"💳 You received {amount} credits from a reseller.")
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def mylink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    u = ensure_user(chat_id)
    if u.get('user_type') != 'reseller' and chat_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Reseller only.")
        return
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{chat_id}"
    await update.message.reply_text(f"🔗 Your link:\n`{link}`", parse_mode=ParseMode.MARKDOWN)

async def mysales_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    u = ensure_user(chat_id)
    if u.get('user_type') != 'reseller' and chat_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Reseller only.")
        return
    await update.message.reply_text(f"📜 Sold: {u.get('total_sold', 0)}\n📦 Stock: {u.get('stock', 0)}")

# ===================== UI FLOW =====================

async def show_choose_ui(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if is_banned(chat_id):
        await update.message.reply_text("🚫 Banned.")
        return
    user_type, can_process, error_msg = check_user_plan(chat_id)
    if not can_process:
        if error_msg:
            await update.message.reply_text(error_msg)
        else:
            await update.message.reply_text(
                "❌ No credits/plan. Use /plans or contact support.",
                reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS)
            )
        return
    user = get_user_info(chat_id) or {}
    credits = user.get('credits', 0)
    if user.get('user_type') == 'premium':
        card = "🎨 Choose a UI\n\n📌 Type: Normal\nUpdating screen with traditional\ninstallation steps.\n\n💎 Plan: Premium · Unlimited"
    else:
        card = f"🎨 Choose a UI\n\n📌 Type: Normal\nUpdating screen with traditional\ninstallation steps.\n\n💳 Plan: Free · {credits} left"
    context.user_data['flow'] = 'choose_ui'
    context.user_data.pop('selected_ui', None)
    context.user_data.pop('selected_lang', None)
    await update.message.reply_text(card, reply_markup=ui_choice_keyboard())

async def show_dropper_language(update: Update, context: ContextTypes.DEFAULT_TYPE, ui_name: str):
    context.user_data['selected_ui'] = ui_name
    context.user_data['flow'] = 'choose_lang'
    await update.message.reply_text(
        f"🌐 Dropper language\n\nThis is the language shown on the phone\nduring install.\n\n🎨 UI: {ui_name}",
        reply_markup=lang_choice_keyboard()
    )

async def show_selected_ready(update: Update, context: ContextTypes.DEFAULT_TYPE, ui_name: str, lang_name: str):
    context.user_data['selected_ui'] = ui_name
    context.user_data['selected_lang'] = lang_name
    context.user_data['flow'] = 'waiting_apk'
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"✅ Selected\n\n🎨 UI: {ui_name}\n🌐 Language: {lang_name}\n\n📤 Send your APK as a file (max 20 MB).",
        reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS)
    )

# ===================== KEYBOARD HANDLER =====================

async def handle_keyboard_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id
    flow = context.user_data.get('flow')

    if text in ("✖ Cancel", "Cancel", "❌ Cancel"):
        context.user_data.clear()
        await update.message.reply_text("Cancelled.", reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS))
        return

    if text in ("← Main Menu",):
        await update.message.reply_text("Main menu.", reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS))
        return

    # force channel for non-admin
    if chat_id not in ADMIN_IDS and text not in ("❓ Help",):
        if not await require_channel(update, context):
            return

    # Auto-recall: on first button click of the session, remind former/current subscribers
    if not context.user_data.get('recall_shown'):
        context.user_data['recall_shown'] = True
        u_recall = get_user_info(chat_id)
        recall_msg = get_sub_recall_status(u_recall)
        if recall_msg and (u_recall or {}).get('user_type', 'free') == 'free':
            # Only surface this for users who are currently free but have history
            try:
                await context.bot.send_message(
                    chat_id,
                    f"📋 Account recognized\n{recall_msg}\n\nType /plans to renew."
                )
            except Exception:
                pass

    if text in ("🔧 Build APK", "Build APK"):
        await show_choose_ui(update, context)
        return
    if text in ("💎 Plans", "Plans"):
        await plans_command(update, context)
        return
    if text in ("👤 Profile", "Profile", "📊 My Info"):
        await info_command(update, context)
        return
    if text in ("❓ Help", "Help"):
        await help_command(update, context)
        return
    if text in ("🏪 Reseller Panel",):
        if not is_reseller(chat_id):
            await update.message.reply_text("❌ Reseller only.")
            return
        u = ensure_user(chat_id)
        await update.message.reply_text(
            f"🏪 Reseller Panel\n\n📦 Stock: {u.get('stock', 0)}\n💸 Sold: {u.get('total_sold', 0)}\n💳 Personal: {u.get('credits', 0)}\n\n/sell <id> <amount>",
            reply_markup=reseller_panel_keyboard()
        )
        return
    if text in ("📦 My Stock",):
        await mystock_command(update, context)
        return
    if text in ("💸 Sell Credits",):
        await update.message.reply_text("Send:\n/sell <user_chat_id> <credits>")
        return
    if text in ("📜 My Sales",):
        await mysales_command(update, context)
        return
    if text in ("🔗 My Link",):
        await mylink_command(update, context)
        return
    # ---- ADMIN PANEL BUTTONS ----
    if chat_id in ADMIN_IDS:

        if text in ("📢 Drop Message",):
            await update.message.reply_text(
                "Send to all users:\n/broadcast your message\n\n"
                "Save + send update:\n/announce your text\n/clearannounce"
            )
            return
        if text in ("📌 Set Announce",):
            await update.message.reply_text("Usage: /announce Your update message")
            return

        if text in ("🛠 Admin Panel",):
            await admin_command(update, context)
            return
        if text in ("➕ Add Reseller",):
            await update.message.reply_text("Send: /addreseller <chat_id> <stock>")
            return
        if text in ("❌ Remove Reseller",):
            await update.message.reply_text("Send: /removereseller <chat_id>")
            return
        if text in ("📋 Resellers",):
            await listresellers_command(update, context)
            return
        if text in ("🔄 Toggle Reseller",):
            await update.message.reply_text("Use /addreseller or /removereseller")
            return
        if text in ("🔑 Set Token",):
            await update.message.reply_text("Set BOT_TOKEN in .env and restart.")
            return
        if text in ("🏷 Set Brand",):
            await update.message.reply_text("Send: /setbrand <name>")
            return
        if text in ("💬 Set Support",):
            await update.message.reply_text("Send: /setsupport <url>")
            return
        if text in ("📢 Set Force-Join",):
            await update.message.reply_text(f"Current: {CHANNEL_USERNAME}\nSend: /setforcejoin @channel")
            return
        if text in ("🎮 Reseller FUD Control",):
            await update.message.reply_text("Reseller FUD uses same bind_apk pipeline. Stock controls access.")
            return
        if text in ("🛡 Dup Shield",):
            await update.message.reply_text("Dup shield: one APK at a time via semaphore (already ON).")
            return
        if text in ("🚫 Ban User",):
            await update.message.reply_text("Send: /ban <chat_id>")
            return
        if text in ("🔓 Unban User",):
            await update.message.reply_text("Send: /unban <chat_id>")
            return
        if text in ("🛒 Shop — ON",):
            set_setting("shop_on", True)
            await update.message.reply_text("✅ Shop ON")
            return
        if text in ("🛑 Shop — OFF",):
            set_setting("shop_on", False)
            await update.message.reply_text("✅ Shop OFF")
            return
        if text in ("💲 Set Price",):
            await update.message.reply_text("Send: /setprice weekly|monthly|yearly <price>\nExample: /setprice weekly 20")
            return
        if text in ("👁 Pack Show/Hide",):
            await update.message.reply_text("Plans visibility follows Shop ON/OFF.")
            return
        if text in ("🆕 New Codes",):
            await update.message.reply_text("Send: /newcodes <count> <credits_each>")
            return
        if text in ("✏ Custom Code",):
            await update.message.reply_text("Send: /customcode <CODE> <credits>")
            return
        if text in ("📜 Code List",):
            await codelist_command(update, context)
            return
        if text in ("⚡ V2 — ON",):
            set_setting("v2_on", True)
            await update.message.reply_text("✅ V2 ON")
            return
        if text in ("⏹ V2 — OFF",):
            set_setting("v2_on", False)
            await update.message.reply_text("✅ V2 OFF")
            return
        if text in ("🎁 Free Credit ON",):
            set_setting("free_credit_on", True)
            await update.message.reply_text("✅ Free credit ON for new users")
            return
        if text in ("🚫 Free Credit OFF",):
            set_setting("free_credit_on", False)
            await update.message.reply_text("✅ Free credit OFF")
            return
        if text in ("💲 Set Amount",):
            await update.message.reply_text("Send: /setamount <n>")
            return
        if text in ("💙 Give All Free Users",):
            await giveallfree_command(update, context)
            return
        if text in ("💎 Give Premium",):
            await update.message.reply_text("Send: /premium <chat_id> <days>")
            return
        if text in ("💎 Remove Premium",):
            await update.message.reply_text("Send: /removepremium <chat_id>")
            return
        if text in ("⭐ Give Special",):
            await update.message.reply_text("Send: /specialpremium <chat_id> <days>")
            return
        if text in ("⭐ Remove Special",):
            await update.message.reply_text("Send: /removespecialpremium <chat_id>")
            return

    # UI selection
    if flow == 'choose_ui' or text.startswith("▶ "):
        if text in ("← Type", "← Back"):
            await show_choose_ui(update, context)
            return
        if text.startswith("▶ ") or any(x in text for x in UI_OPTIONS.keys()):
            ui = _ui_from_btn(text)
            await show_dropper_language(update, context, ui)
            return

    if flow == 'choose_lang' or any(b.split(" ", 1)[-1] in text for b in LANG_BUTTONS):
        if text in ("← Back", "← Type"):
            await show_choose_ui(update, context)
            return
        lang = _lang_from_btn(text)
        ui = context.user_data.get('selected_ui', 'Playstore')
        await show_selected_ready(update, context, ui, lang)
        return

    await update.message.reply_text("Use the menu buttons.", reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS))

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if is_banned(chat_id):
        await update.message.reply_text("🚫 Banned.")
        return
    if not await require_channel(update, context):
        return
    document = update.message.document
    file_name = document.file_name or "app.apk"
    if not file_name.lower().endswith('.apk'):
        await update.message.reply_text("❌ Send an APK file only.")
        return
    if context.user_data.get('flow') != 'waiting_apk' or not context.user_data.get('selected_ui'):
        await update.message.reply_text(
            "Start with 🔧 Build APK → UI → language, then send APK.",
            reply_markup=main_menu_keyboard(is_reseller(chat_id), chat_id in ADMIN_IDS)
        )
        return
    user_type, can_process, error_msg = check_user_plan(chat_id)
    if not can_process:
        await update.message.reply_text(error_msg or "❌ No credits/plan.")
        return
    file_size_mb = (document.file_size or 0) / (1024 * 1024)
    # Telegram Bot API hard cap: get_file() only works for files ≤ 20 MB.
    # Anything larger downloads as 0 bytes / truncated → apktool NotAZipFileException.
    if file_size_mb > 20:
        await update.message.reply_text(
            f"❌ APK too large ({file_size_mb:.1f} MB).\n\n"
            "Telegram bots can only receive files up to 20 MB.\n"
            "Compress or trim the APK and try again."
        )
        return
    status_msg = await update.message.reply_text("📥 Downloading APK…")
    user_dir = os.path.join(TEMP_DIR, str(chat_id))
    os.makedirs(user_dir, exist_ok=True)
    apk_path = os.path.join(user_dir, file_name)
    try:
        tg_file = await context.bot.get_file(document.file_id)
        await tg_file.download_to_drive(apk_path)

        # ── Validate the downloaded file is a real APK (ZIP) ─────────────────
        downloaded_size = os.path.getsize(apk_path) if os.path.exists(apk_path) else 0
        if downloaded_size == 0:
            await status_msg.edit_text(
                "❌ Download failed — file arrived empty.\n"
                "Try again or send a smaller APK (max 20 MB)."
            )
            shutil.rmtree(user_dir, ignore_errors=True)
            return
        if not zipfile.is_zipfile(apk_path):
            await status_msg.edit_text(
                "❌ Invalid APK — the file is not a valid Android package.\n\n"
                "Make sure you're sending a real `.apk` file, not an XAPK, AAB, or split APK."
            )
            shutil.rmtree(user_dir, ignore_errors=True)
            return
        # ─────────────────────────────────────────────────────────────────────

        original_name = file_name
        icon_path = None
        try:
            icon_path = extract_icon_from_apk(apk_path)
        except Exception:
            pass
        ui = context.user_data.get('selected_ui', 'Playstore')
        lang = context.user_data.get('selected_lang', 'English')
        await status_msg.edit_text(
            f"✅ APK received\n\n📦 `{file_name}` · {file_size_mb:.2f} MB\n🎨 UI: {ui}\n🌐 Language: {lang}\n\n⚙️ Processing…",
            parse_mode=ParseMode.MARKDOWN
        )
        queue_entry = {
            'chat_id': str(chat_id), 'apk_path': apk_path, 'icon_path': icon_path or '',
            'original_name': original_name, 'file_name': file_name, 'ui': ui, 'language': lang,
            'status': 'processing', 'submitted_at': datetime.now().isoformat(),
            'message_id': status_msg.message_id,
        }
        result = queue_collection.insert_one(queue_entry)
        queue_id = str(result.inserted_id)
        context.user_data['flow'] = None
        asyncio.create_task(process_apk(context, queue_id, chat_id, apk_path, icon_path, original_name, status_msg.message_id, ui, lang))
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")
        try:
            shutil.rmtree(user_dir, ignore_errors=True)
        except Exception:
            pass

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('flow') == 'waiting_apk':
        try:
            photo = update.message.photo[-1]
            user_dir = os.path.join(TEMP_DIR, str(update.effective_chat.id))
            os.makedirs(user_dir, exist_ok=True)
            icon_path = os.path.join(user_dir, "custom_icon.png")
            tg_file = await context.bot.get_file(photo.file_id)
            await tg_file.download_to_drive(icon_path)
            context.user_data['custom_icon'] = icon_path
            await update.message.reply_text("✅ Custom icon saved. Now send the APK.")
        except Exception as e:
            await update.message.reply_text(f"❌ Icon error: {e}")

async def process_apk(context, queue_id, chat_id, apk_path, icon_path, original_name, message_id, ui="Playstore", language="English"):
    async with processing_semaphore:
        output_apk = None
        user_temp_dir = os.path.join(TEMP_DIR, str(chat_id))
        start_time = time.time()
        timer_job_name = f'timer_{chat_id}_{message_id}'
        try:
            context.application.job_queue.run_repeating(
                update_processing_timer, interval=10, first=5,
                data={'chat_id': chat_id, 'message_id': message_id, 'start_time': start_time, 'ui': ui, 'language': language},
                name=timer_job_name
            )
        except Exception:
            pass
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            timestamp = int(time.time())
            base_name = original_name.replace('.apk', '')
            # AXION: filename = app name only
            try:
                real_name = extract_app_name_from_apk(apk_path)
                if real_name and real_name.strip() and real_name != "App":
                    safe = "".join(c if c.isalnum() or c in (" ", "-", "_") else "" for c in real_name).strip()
                    safe = safe.replace(" ", "_")[:40] or base_name
                    base_name = safe
            except Exception:
                pass
            output_name = f"{base_name}.apk"
            output_apk = await asyncio.to_thread(
                bind_apk, target_apk_path=apk_path,
                user_icon_path=icon_path if icon_path else None, output_name=output_name
            )
            processing_time = (time.time() - start_time) / 60
            if output_apk and os.path.exists(output_apk):
                deduct_credit(chat_id)
                user = get_user_info(chat_id) or {}
                ut = user.get('user_type', 'free')
                if ut == 'premium':
                    credit_msg = "\n💎 Premium — unlimited"
                elif ut == 'specialpremium':
                    rem = max(0, 3 - user.get('daily_count', 0))
                    credit_msg = f"\n⭐ Special — {rem}/3 today"
                elif ut == 'reseller':
                    credit_msg = f"\n🏪 Reseller · credits left: {user.get('credits', 0)}"
                else:
                    credit_msg = f"\n💳 Credits left: {user.get('credits', 0)}"
                with open(output_apk, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=chat_id, document=f, filename=os.path.basename(output_apk),
                        caption=(
                            f"✅ Processing complete!\n\n🎨 UI: {ui}\n🌐 Language: {language}\n"
                            f"⏱️ Time: {processing_time:.2f} min\n🔐 Protected APK ready.{credit_msg}"
                        ),
                        read_timeout=120, write_timeout=120, connect_timeout=60,
                    )
                try:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f"✅ Done · {ui} · {language} · {processing_time:.1f}m")
                except Exception:
                    pass
                try:
                    queue_collection.delete_one({'_id': queue_id})
                except Exception:
                    pass
                try:
                    queue_collection.delete_one({'_id': ObjectId(queue_id)})
                except Exception:
                    try:
                        queue_collection.delete_one({'chat_id': str(chat_id), 'status': 'processing'})
                    except Exception:
                        pass
            else:
                await context.bot.send_message(chat_id=chat_id, text="❌ Build failed.")
                try:
                    queue_collection.delete_one({'_id': queue_id})
                except Exception:
                    pass
        except Exception as e:
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {e}")
            except Exception:
                pass
            try:
                queue_collection.delete_one({'_id': queue_id})
            except Exception:
                pass
        finally:
            try:
                for job in context.application.job_queue.get_jobs_by_name(timer_job_name):
                    job.schedule_removal()
            except Exception:
                pass
            if os.path.exists(user_temp_dir):
                shutil.rmtree(user_temp_dir, ignore_errors=True)
            if output_apk and os.path.exists(output_apk):
                try:
                    os.remove(output_apk)
                except Exception:
                    pass
            for temp_pattern in ['temp_*.apk', 'aligned_*.apk', 'dropper_work_*', 'target_work_*']:
                for temp_file in glob.glob(temp_pattern):
                    try:
                        if os.path.isfile(temp_file):
                            os.remove(temp_file)
                        elif os.path.isdir(temp_file):
                            shutil.rmtree(temp_file, ignore_errors=True)
                    except Exception:
                        pass

async def update_processing_timer(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data['chat_id']
    message_id = job.data['message_id']
    start_time = job.data['start_time']
    ui = job.data.get('ui', '')
    language = job.data.get('language', '')
    elapsed = int(time.time() - start_time)
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=f"⚙️ Processing…\n🎨 {ui} · 🌐 {language}\n⏱️ {elapsed // 60:02d}:{elapsed % 60:02d}"
        )
    except Exception:
        pass


def main():
    global processing_semaphore
    processing_semaphore = asyncio.Semaphore(1)
    if not BOT_TOKEN:
        print("ERROR: set BOT_TOKEN in .env or environment")
        sys.exit(1)
    # seed default plans
    get_plans()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("plans", plans_command))
    app.add_handler(CommandHandler("profile", info_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("clearqueue", clearqueue_command))
    app.add_handler(CommandHandler("userinfo", userinfo_command))
    app.add_handler(CommandHandler("listusers", listusers_command))
    app.add_handler(CommandHandler("subscribers", subscribers_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("announce", announce_command))
    app.add_handler(CommandHandler("clearannounce", clearannounce_command))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("removepremium", removepremium_command))
    app.add_handler(CommandHandler("specialpremium", specialpremium_command))
    app.add_handler(CommandHandler("removespecialpremium", removespecialpremium_command))
    app.add_handler(CommandHandler("credit", credit_command))
    app.add_handler(CommandHandler("removecredit", removecredit_command))
    app.add_handler(CommandHandler("addreseller", addreseller_command))
    app.add_handler(CommandHandler("removereseller", removereseller_command))
    app.add_handler(CommandHandler("giveresellerstock", giveresellerstock_command))
    app.add_handler(CommandHandler("listresellers", listresellers_command))
    app.add_handler(CommandHandler("mystock", mystock_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("mylink", mylink_command))
    app.add_handler(CommandHandler("mysales", mysales_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("setprice", setprice_command))
    app.add_handler(CommandHandler("setbrand", setbrand_command))
    app.add_handler(CommandHandler("setsupport", setsupport_command))
    app.add_handler(CommandHandler("setforcejoin", setforcejoin_command))
    app.add_handler(CommandHandler("setamount", setamount_command))
    app.add_handler(CommandHandler("giveallfree", giveallfree_command))
    app.add_handler(CommandHandler("newcodes", newcodes_command))
    app.add_handler(CommandHandler("customcode", customcode_command))
    app.add_handler(CommandHandler("codelist", codelist_command))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(plan_callback, pattern="^plan_"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_buttons))
    # Daily job: auto-expire and notify users whose premium/special plan ran out
    app.job_queue.run_repeating(check_expired_subscriptions, interval=86400, first=60)
    print("PlayRemove FUD started — channel gate + plans + full admin panel")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Python 3.12+ removed the implicit event loop in the main thread
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    main()
