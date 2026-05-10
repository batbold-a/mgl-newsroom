"""
MGL Newsroom Bot — with Premium Subscription Manager
====================================
Active hours: 8am–10pm Ulaanbaatar time (UTC+8)
News checks: 8am, 11am, 2pm, 5pm, 8pm
Morning brief: auto-posts at 8am (no approval)
Breaking alerts: instant any time during active hours
Duplicate fix: MD5 hash + URL dedup
Mongolian sources: montsame.mn, news.mn, mse.mn
Trading style: recommendations not signals

NEW — Premium subscription system:
- Customer DMs bot → gets bank info automatically
- Sends payment screenshot → you get Approve/Reject buttons
- You approve → bot sends them 1-use invite link to premium channel
- Bot auto-reminds at 7 days and 1 day before expiry
- Bot auto-removes expired members

Railway variables needed (new ones):
  ADMIN_ID       - your personal Telegram user ID (get from @userinfobot)
  BANK_ACCOUNT   - your bank account number
  BANK_NAME      - your bank name e.g. Голомт банк
  ACCOUNT_NAME   - your name on the account
  PRICE_MNT      - monthly price e.g. 9900
"""

import feedparser
import requests
import re
import time
import json
import os
import hashlib
from datetime import datetime, timezone, timedelta

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BOT_TOKEN        = os.environ.get("BOT_TOKEN")
FREE_CHANNEL     = os.environ.get("FREE_CHANNEL",    "@mglnewsroomfree")
PREMIUM_CHANNEL  = os.environ.get("PREMIUM_CHANNEL", "-1003833538418")
ADMIN_CHAT_ID    = os.environ.get("ADMIN_CHAT_ID")
ADMIN_ID         = int(os.environ.get("ADMIN_ID", os.environ.get("ADMIN_CHAT_ID", "0")))
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_TRANSLATE = os.environ.get("GOOGLE_TRANSLATE_KEY")
PREMIUM_INVITE   = "https://t.me/+BxQ8PEdcyc02YmM9"

BANK_ACCOUNT   = os.environ.get("BANK_ACCOUNT",  "1234567890")
BANK_NAME      = os.environ.get("BANK_NAME",     "Голомт банк")
ACCOUNT_NAME   = os.environ.get("ACCOUNT_NAME",  "Батболд")
PRICE_MONTHLY  = int(os.environ.get("PRICE_MNT",    "9900"))
PRICE_YEARLY   = int(os.environ.get("PRICE_YEARLY", "89900"))

UB_OFFSET  = timedelta(hours=8)
DISCLAIMER = "\n\n⚠️ Энэхүү мэдээлэл нь хөрөнгө оруулалтын зөвлөгөө биш."

ACTIVE_HOUR_START = 8
ACTIVE_HOUR_END   = 22
CHECK_HOURS = {8, 11, 14, 17, 20}

# ── NEWS SOURCES ───────────────────────────────────────────────────────────────
MN_FEEDS = [
    ("https://montsame.mn/rss",   "Монцамэ"),
    ("https://news.mn/rss",       "News.mn"),
    ("https://ikon.mn/rss",       "Ikon.mn"),
]
GLOBAL_FEEDS = [
    ("https://feeds.reuters.com/reuters/businessNews",            "Reuters"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NY Times"),
    ("https://www.mining.com/feed/",                              "Mining.com"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/",           "CoinDesk"),
    ("https://feeds.reuters.com/reuters/companyNews",             "Reuters Markets"),
    ("https://techcrunch.com/feed/",                              "TechCrunch"),
]
ALL_FEEDS = MN_FEEDS + GLOBAL_FEEDS

KEYWORDS = [
    "market", "stock", "stocks", "S&P", "nasdaq", "rally", "crash",
    "fed", "federal reserve", "interest rate", "inflation", "recession", "GDP",
    "coal", "copper", "gold", "silver", "oil", "commodity", "mineral",
    "mining revenue", "mining export", "оюу толгой", "тавантолгой",
    "oyu tolgoi", "tavan tolgoi",
    "мхб", "хувьцаа", "бонд", "хөрөнгө оруулалт", "банк",
    "инфляц", "ханш", "төгрөг", "эдийн засаг", "экспорт",
    "борлуулалт", "ашиг", "алдагдал", "санхүү",
    "IPO", "earnings", "revenue", "profit", "quarterly results",
    "investment", "investor", "fund", "bond", "yield", "dividend",
    "bankruptcy", "acquisition", "merger",
    "bitcoin", "crypto", "ethereum", "blockchain",
    "apple earnings", "google revenue", "microsoft profit",
    "nvidia earnings", "tesla earnings",
]
REJECT_KEYWORDS = [
    "mma", "boxing", "fight", "wrestler", "tournament", "sports",
    "football", "basketball", "soccer", "athlete", "champion",
    "concert", "movie", "film", "celebrity", "entertainment",
    "weather", "accident", "crime", "police", "court case",
    "тулаан", "спорт", "тамирчин", "бокс", "цаг агаар",
]
BREAKING_WORDS = [
    "breaking", "urgent", "flash", "crash", "collapse",
    "emergency", "ban", "sanction", "plunge", "halt",
    "bankrupt", "crisis", "default", "surge"
]
SCHEDULE = {
    0: ("📊", "Weekly Market Outlook",    "7 хоногийн зах зээлийн тойм",
        "Focus on MSE stocks to watch this week and global market direction."),
    1: ("🌅", "Morning Snapshot",         "Өглөөний тойм",
        "Summarize the most important business and finance news today."),
    2: ("⛏️", "Mining & Commodities",     "Уул уурхай ба түүхий эд",
        "Focus on coal, copper, gold prices and impact on Mongolia's mining sector and MSE stocks."),
    3: ("💡", "Crypto & Finance Insight", "Крипто ба санхүүгийн мэдээлэл",
        "Focus on Bitcoin, Ethereum movements and personal finance insights for Mongolian investors."),
    4: ("📋", "Weekly Recap & Outlook",   "7 хоногийн дүн",
        "Summarize the week's key events and what Mongolian investors should watch next week."),
    5: ("🌅", "Weekend Snapshot",         "Амралтын өдрийн тойм",
        "Weekend financial news and crypto market movements."),
    6: ("🌅", "Weekend Snapshot",         "Амралтын өдрийн тойм",
        "Weekend financial news and crypto market movements."),
}

# ── FILES ──────────────────────────────────────────────────────────────────────
SENT_FILE        = "sent_articles.json"
PENDING_FILE     = "pending_articles.json"
EDIT_STATE_FILE  = "edit_state.json"
STATE_FILE       = "bot_state.json"
SUBSCRIBERS_FILE = "subscribers.json"

# ── HELPERS ────────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_ub():
    return datetime.now(timezone.utc) + UB_OFFSET

def make_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:16]

def fmt_date(iso):
    return datetime.fromisoformat(iso).strftime("%Y/%m/%d")

def days_until(iso):
    dt = datetime.fromisoformat(iso).replace(tzinfo=None)
    return (dt - datetime.now()).days

def is_active_hours():
    state = load_json(STATE_FILE, {})
    if state.get("paused", False):
        return False
    h_start = state.get("hour_start", ACTIVE_HOUR_START)
    h_end   = state.get("hour_end",   ACTIVE_HOUR_END)
    return h_start <= now_ub().hour < h_end

def should_check_feeds():
    ub    = now_ub()
    state = load_json(STATE_FILE, {})
    key   = f"feed_check_{ub.strftime('%Y-%m-%d_%H')}"
    if ub.hour in CHECK_HOURS and not state.get(key):
        state[key] = True
        today = ub.strftime("%Y-%m-%d")
        state = {k: v for k, v in state.items()
                 if today in k or not k.startswith("feed_check_")}
        save_json(STATE_FILE, state)
        return True
    return False

def should_post_morning_brief():
    ub    = now_ub()
    state = load_json(STATE_FILE, {})
    today = ub.strftime("%Y-%m-%d")
    key   = f"morning_brief_{today}"
    if ub.hour == 8 and ub.minute < 10 and not state.get(key):
        state[key] = True
        save_json(STATE_FILE, state)
        return True
    return False

def should_check_subscriptions():
    ub    = now_ub()
    state = load_json(STATE_FILE, {})
    key   = f"sub_check_{ub.strftime('%Y-%m-%d_%H')}"
    if not state.get(key):
        state[key] = True
        today = ub.strftime("%Y-%m-%d")
        state = {k: v for k, v in state.items()
                 if today in k or not k.startswith("sub_check_")}
        save_json(STATE_FILE, state)
        return True
    return False

# ── TELEGRAM ───────────────────────────────────────────────────────────────────
def tg(method, payload):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload, timeout=15
        )
        result = r.json()
        if not result.get("ok"):
            print(f"[TG WARN] {method}: {result.get('description')}")
        return result
    except Exception as e:
        print(f"[TG ERROR] {method}: {e}")
        return {}

def send(chat_id, text, markup=None):
    payload = {
        "chat_id":    chat_id,
        "text":       text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if markup:
        payload["reply_markup"] = json.dumps(markup)
    return tg("sendMessage", payload)

def answer_cb(cb_id, text):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

# ── SUBSCRIPTION MESSAGES ──────────────────────────────────────────────────────
def plan_label(plan):
    return "📅 Жилийн" if plan == "yearly" else "🗓 Сарын"

def plan_price(plan):
    return PRICE_YEARLY if plan == "yearly" else PRICE_MONTHLY

def plan_days(plan):
    return 365 if plan == "yearly" else 30

def join_instructions_msg():
    yearly_save = PRICE_MONTHLY * 12 - PRICE_YEARLY
    return (
        f"👋 Сайн байна уу!\n\n"
        f"🔒 <b>MGL Newsroom Premium</b> сувагт тавтай морилно уу!\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>Үнийн санал:</b>\n\n"
        f"🗓 <b>Сарын төлбөр:</b> ₮{PRICE_MONTHLY:,}\n"
        f"📅 <b>Жилийн төлбөр:</b> ₮{PRICE_YEARLY:,} "
        f"<i>(2 сар үнэгүй! ₮{yearly_save:,} хэмнэнэ)</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>Дансны мэдээлэл:</b>\n"
        f"  Банк: <b>{BANK_NAME}</b>\n"
        f"  Дансны дугаар: <b>{BANK_ACCOUNT}</b>\n"
        f"  Эзэмшигч: <b>{ACCOUNT_NAME}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Яаж нэгдэх вэ?</b>\n"
        f"1️⃣ Сарын <b>₮{PRICE_MONTHLY:,}</b> эсвэл жилийн <b>₮{PRICE_YEARLY:,}</b> шилжүүлнэ\n"
        f"2️⃣ Гүйлгээний баримтын <b>зургийг энд илгээнэ</b>\n"
        f"3️⃣ Бид шалгаад <b>30 минутын дотор</b> нэвтрэх эрх өгнө\n\n"
        f"❓ Асуулт байвал шууд энд бичнэ үү!"
    )

def welcome_premium_msg(expiry_iso, invite_url, plan="monthly"):
    label = "жилийн" if plan == "yearly" else "сарын"
    return (
        f"🎉 <b>MGL Newsroom Premium-д тавтай морил!</b>\n\n"
        f"✅ Таны <b>{label}</b> эрх идэвхжлээ\n"
        f"📅 Дуусах огноо: <b>{fmt_date(expiry_iso)}</b>\n"
        f"⏳ Нийт хугацаа: <b>{plan_days(plan)} хоног</b>\n\n"
        f"🔗 <b>Premium сувагт нэвтрэх линк:</b>\n{invite_url}\n\n"
        f"🔔 Дуусахаас <b>7 хоног</b> болон <b>1 хоног</b> өмнө мэдэгдэл илгээнэ үү.\n\n"
        f"Баярлалаа! 🙏"
    )

def reminder_msg(days, expiry_iso, plan="monthly"):
    urgency     = "⚠️" if days <= 1 else "🔔"
    renew_price = plan_price(plan)
    label       = "жилийн" if plan == "yearly" else "сарын"
    return (
        f"{urgency} <b>Premium эрхийн сануулга</b>\n\n"
        f"Таны MGL Newsroom Premium эрх <b>{days} хоногийн дараа</b> дуусна.\n"
        f"Дуусах огноо: <b>{fmt_date(expiry_iso)}</b>\n\n"
        f"🔄 Сунгахын тулд {label} төлбөр <b>₮{renew_price:,}</b> "
        f"дансанд шилжүүлж баримт илгээнэ үү:\n\n"
        f"🏦 Банк: <b>{BANK_NAME}</b>\n"
        f"💳 Данс: <b>{BANK_ACCOUNT}</b>\n"
        f"👤 Нэр: <b>{ACCOUNT_NAME}</b>\n\n"
        f"❓ Асуулт байвал шууд бичнэ үү!"
    )

def expired_msg(plan="monthly"):
    label = "жилийн" if plan == "yearly" else "сарын"
    return (
        f"😔 <b>Таны Premium эрх дууслаа</b>\n\n"
        f"MGL Newsroom Premium сувгаас гарлаа.\n\n"
        f"🔄 <b>Дахин нэгдэх бол:</b>\n"
        f"  🗓 Сарын: <b>₮{PRICE_MONTHLY:,}</b>\n"
        f"  📅 Жилийн: <b>₮{PRICE_YEARLY:,}</b> (2 сар үнэгүй!)\n\n"
        f"🏦 Банк: <b>{BANK_NAME}</b>\n"
        f"💳 Данс: <b>{BANK_ACCOUNT}</b>\n\n"
        f"Баримт илгээвэл 30 минутын дотор эрхийг сэргээнэ!"
    )

# ── SUBSCRIPTION HANDLERS ──────────────────────────────────────────────────────
def handle_private_message(msg):
    user    = msg.get("from", {})
    user_id = str(user.get("id", ""))
    chat_id = msg.get("chat", {}).get("id")
    text    = msg.get("text", "").strip()
    photo   = msg.get("photo")
    if not user_id or not chat_id:
        return
    data = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
    if text and not photo:
        if user_id in data["subscribers"]:
            sub   = data["subscribers"][user_id]
            days  = days_until(sub["expiry"])
            plan  = sub.get("plan", "monthly")
            label = "Жилийн" if plan == "yearly" else "Сарын"
            send(chat_id,
                f"✅ <b>Та Premium гишүүн байна!</b>\n\n"
                f"📋 Төлөвлөгөө: <b>{label}</b>\n"
                f"📅 Дуусах огноо: <b>{fmt_date(sub['expiry'])}</b>\n"
                f"⏳ Үлдсэн хоног: <b>{max(0, days)}</b>\n\n"
                f"Сунгах бол дуусахаас өмнө баримт илгээнэ үү."
            )
        else:
            markup = {"inline_keyboard": [[
                {"text": f"🗓 Сарын — ₮{PRICE_MONTHLY:,}",  "callback_data": f"plan_select:{user_id}:monthly"},
                {"text": f"📅 Жилийн — ₮{PRICE_YEARLY:,}", "callback_data": f"plan_select:{user_id}:yearly"},
            ]]}
            send(chat_id,
                f"👋 Сайн байна уу!\n\n"
                f"🔒 <b>MGL Newsroom Premium</b>\n\n"
                f"Та аль төлөвлөгөөг сонгох вэ?\n\n"
                f"🗓 <b>Сарын:</b> ₮{PRICE_MONTHLY:,}\n"
                f"📅 <b>Жилийн:</b> ₮{PRICE_YEARLY:,} <i>(2 сар үнэгүй!)</i>",
                markup=markup
            )
        return
    if photo:
        is_renewal   = user_id in data["subscribers"]
        pending_plan = data["pending"].get(user_id, {}).get("plan", "monthly")
        data["pending"][user_id] = {
            "user_id":       user.get("id"),
            "username":      user.get("username", ""),
            "first_name":    user.get("first_name", ""),
            "last_name":     user.get("last_name", ""),
            "photo_file_id": photo[-1]["file_id"],
            "requested_at":  datetime.now().isoformat(),
            "is_renewal":    is_renewal,
            "chat_id":       chat_id,
            "plan":          pending_plan,
        }
        save_json(SUBSCRIBERS_FILE, data)
        plan_str = "Жилийн" if pending_plan == "yearly" else "Сарын"
        send(chat_id,
            f"✅ <b>Баримт хүлээн авлаа!</b>\n\n"
            f"📋 Сонгосон төлөвлөгөө: <b>{plan_str} (₮{plan_price(pending_plan):,})</b>\n\n"
            f"Бид 30 минутын дотор шалгаад нэвтрэх эрх өгнө.\n"
            f"Түр хүлээнэ үү 🙏"
        )
        label     = "🔄 СУНГАЛТ" if is_renewal else "🆕 ШИНЭ"
        uname_str = f"@{user.get('username')}" if user.get("username") else "(username байхгүй)"
        caption   = (
            f"{label} — Premium хүсэлт\n\n"
            f"👤 Нэр: {user.get('first_name','')} {user.get('last_name','')}\n"
            f"🔗 {uname_str}\n"
            f"🆔 ID: {user.get('id')}\n"
            f"📋 Төлөвлөгөө: {plan_str} — ₮{plan_price(pending_plan):,}\n"
            f"🕐 {datetime.now().strftime('%H:%M, %Y/%m/%d')}"
        )
        markup = {"inline_keyboard": [[
            {"text": "✅ Зөвшөөрөх", "callback_data": f"sub_approve:{user_id}"},
            {"text": "❌ Татгалзах",  "callback_data": f"sub_reject:{user_id}"},
        ]]}
        tg("sendPhoto", {
            "chat_id":      ADMIN_ID,
            "photo":        photo[-1]["file_id"],
            "caption":      caption,
            "reply_markup": json.dumps(markup),
        })

def handle_plan_select_msg(user_id_str, plan, chat_id, cb_id):
    data = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
    if user_id_str not in data["pending"]:
        data["pending"][user_id_str] = {}
    data["pending"][user_id_str]["plan"]    = plan
    data["pending"][user_id_str]["chat_id"] = chat_id
    save_json(SUBSCRIBERS_FILE, data)
    label = "Жилийн" if plan == "yearly" else "Сарын"
    price = plan_price(plan)
    answer_cb(cb_id, f"✅ {label} төлөвлөгөө!")
    send(chat_id,
        f"✅ <b>{label} төлөвлөгөө сонгогдлоо!</b>\n\n"
        f"💳 Төлөх дүн: <b>₮{price:,}</b>\n\n"
        f"🏦 <b>Дансны мэдээлэл:</b>\n"
        f"  Банк: <b>{BANK_NAME}</b>\n"
        f"  Дансны дугаар: <b>{BANK_ACCOUNT}</b>\n"
        f"  Эзэмшигч: <b>{ACCOUNT_NAME}</b>\n\n"
        f"📸 Шилжүүлэг хийсний дараа <b>гүйлгээний баримтын зургийг</b> энд илгээнэ үү.\n"
        f"30 минутын дотор нэвтрэх эрх өгнө 🙏"
    )

def handle_sub_approve(user_id_str, cb_id):
    data    = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
    pending = data["pending"].get(user_id_str)
    if not pending:
        answer_cb(cb_id, "Аль хэдийн шийдэгдсэн.")
        return
    plan    = pending.get("plan", "monthly")
    expiry  = (datetime.now() + timedelta(days=plan_days(plan))).isoformat()
    user_id = pending["user_id"]
    chat_id = pending["chat_id"]
    invite_url = PREMIUM_INVITE
    try:
        expire_ts = int((datetime.now() + timedelta(hours=24)).timestamp())
        result = tg("createChatInviteLink", {
            "chat_id":      PREMIUM_CHANNEL,
            "member_limit": 1,
            "expire_date":  expire_ts,
            "name":         f"User {user_id}",
        })
        if result.get("ok"):
            invite_url = result["result"]["invite_link"]
    except Exception as e:
        print(f"[SUB INVITE ERROR] {e}")
    label_mn = "Жилийн" if plan == "yearly" else "Сарын"
    data["subscribers"][user_id_str] = {
        "user_id":         user_id,
        "chat_id":         chat_id,
        "username":        pending.get("username", ""),
        "first_name":      pending.get("first_name", ""),
        "expiry":          expiry,
        "plan":            plan,
        "approved_at":     datetime.now().isoformat(),
        "is_renewal":      pending.get("is_renewal", False),
        "reminder_7_sent": False,
        "reminder_1_sent": False,
    }
    del data["pending"][user_id_str]
    save_json(SUBSCRIBERS_FILE, data)
    send(chat_id, welcome_premium_msg(expiry, invite_url, plan))
    answer_cb(cb_id, "✅ Зөвшөөрөгдлөө!")
    name = pending.get("first_name", user_id_str)
    send(ADMIN_ID,
        f"✅ <b>Зөвшөөрөгдлөө!</b>\n\n"
        f"👤 {name}\n"
        f"📋 Төлөвлөгөө: <b>{label_mn} — ₮{plan_price(plan):,}</b>\n"
        f"📅 Дуусах огноо: <b>{fmt_date(expiry)}</b>"
    )

def handle_sub_reject(user_id_str, cb_id):
    data    = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
    pending = data["pending"].pop(user_id_str, None)
    save_json(SUBSCRIBERS_FILE, data)
    if pending:
        send(pending["chat_id"],
            "❌ <b>Таны хүсэлт татгалзагдлаа</b>\n\n"
            "Гүйлгээний баримт тодорхойгүй байсан тул баталгаажуулж чадсангүй.\n"
            "Тод харагдах баримт дахин илгээнэ үү."
        )
    answer_cb(cb_id, "❌ Татгалзагдлаа")

def check_subscriptions():
    data      = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
    subs      = data["subscribers"]
    changed   = False
    to_remove = []
    for uid, sub in subs.items():
        days    = days_until(sub["expiry"])
        chat_id = sub.get("chat_id") or sub.get("user_id")
        if days <= 7 and not sub.get("reminder_7_sent"):
            try:
                send(chat_id, reminder_msg(days, sub["expiry"], sub.get("plan", "monthly")))
                data["subscribers"][uid]["reminder_7_sent"] = True
                changed = True
            except Exception as e:
                print(f"[SUB] Reminder error {uid}: {e}")
        if days <= 1 and not sub.get("reminder_1_sent"):
            try:
                send(chat_id, reminder_msg(1, sub["expiry"], sub.get("plan", "monthly")))
                data["subscribers"][uid]["reminder_1_sent"] = True
                changed = True
            except Exception as e:
                print(f"[SUB] Reminder error {uid}: {e}")
        if days < 0:
            to_remove.append(uid)
    for uid in to_remove:
        sub     = data["subscribers"].pop(uid, {})
        changed = True
        uid_int = int(sub.get("user_id", uid))
        chat_id = sub.get("chat_id") or uid_int
        try:
            tg("banChatMember",   {"chat_id": PREMIUM_CHANNEL, "user_id": uid_int})
            tg("unbanChatMember", {"chat_id": PREMIUM_CHANNEL, "user_id": uid_int})
        except Exception as e:
            print(f"[SUB] Kick error {uid}: {e}")
        try:
            send(chat_id, expired_msg(sub.get("plan", "monthly")))
        except Exception as e:
            print(f"[SUB] Expired notify error {uid}: {e}")
        name  = sub.get("first_name", uid)
        uname = f"@{sub['username']}" if sub.get("username") else ""
        send(ADMIN_ID,
            f"⏰ <b>Гишүүнчлэл дууслаа</b>\n\n"
            f"👤 {name} {uname} (ID: {uid})\n"
            f"Сувгаас автоматаар гаргалаа."
        )
    if changed:
        save_json(SUBSCRIBERS_FILE, data)

# ── ADMIN SUBSCRIPTION COMMANDS ────────────────────────────────────────────────
def handle_sub_command(cmd_parts):
    cmd = cmd_parts[0].lower()
    if cmd == "/sublist":
        data = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
        subs = data["subscribers"]
        if not subs:
            send(ADMIN_CHAT_ID, "Одоогоор идэвхтэй гишүүн байхгүй.")
            return
        lines = ["<b>Идэвхтэй Premium гишүүд:</b>\n"]
        for uid, sub in subs.items():
            days  = days_until(sub["expiry"])
            icon  = "🟢" if days > 7 else "🟡" if days > 1 else "🔴"
            name  = sub.get("first_name", uid)
            uname = f"@{sub['username']}" if sub.get("username") else ""
            lines.append(f"{icon} {name} {uname} — {fmt_date(sub['expiry'])} ({max(0,days)}хн)")
        send(ADMIN_CHAT_ID, "\n".join(lines))
    elif cmd == "/subpending":
        data    = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
        pending = data["pending"]
        if not pending:
            send(ADMIN_CHAT_ID, "Хүлээгдэж буй хүсэлт байхгүй.")
            return
        lines = ["<b>Хүлээгдэж буй хүсэлтүүд:</b>\n"]
        for uid, p in pending.items():
            name  = p.get("first_name", uid)
            uname = f"@{p['username']}" if p.get("username") else ""
            t     = p.get("requested_at", "")[:16].replace("T", " ")
            lines.append(f"• {name} {uname} (ID: {uid}) — {t}")
        send(ADMIN_CHAT_ID, "\n".join(lines))
    elif cmd == "/subremove":
        if len(cmd_parts) < 2:
            send(ADMIN_CHAT_ID, "Хэрэглэх: /subremove 123456789")
            return
        target = cmd_parts[1]
        data   = load_json(SUBSCRIBERS_FILE, {"subscribers": {}, "pending": {}})
        if target not in data["subscribers"]:
            send(ADMIN_CHAT_ID, f"ID {target} олдсонгүй.")
            return
        sub     = data["subscribers"].pop(target)
        save_json(SUBSCRIBERS_FILE, data)
        uid_int = int(sub.get("user_id", target))
        chat_id = sub.get("chat_id") or uid_int
        try:
            tg("banChatMember",   {"chat_id": PREMIUM_CHANNEL, "user_id": uid_int})
            tg("unbanChatMember", {"chat_id": PREMIUM_CHANNEL, "user_id": uid_int})
        except Exception as e:
            print(f"[SUB] Remove kick error: {e}")
        send(chat_id, expired_msg(sub.get("plan", "monthly")))
        send(ADMIN_CHAT_ID, f"✅ {sub.get('first_name', target)} гишүүнчлэлийг цуцаллаа.")

# ── PRICE FETCHERS — FIXED WITH FALLBACKS (no more N/A) ───────────────────────
def fetch_mse_top10():
    """Fetch top 10 MSE stocks — tries 2 sources."""
    # Source 1: stock.bbe.mn
    try:
        r = requests.get("https://stock.bbe.mn/", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        rows = re.findall(
            r"Home/Stock/([A-Z]+).*?>([\d,\.]+)</td>.*?>([\d,\.]+)</td>.*?([-\d,\.]+)</td>.*?([-\d\.]+%)</td>",
            r.text, re.DOTALL
        )
        stocks = []
        for row in rows[:10]:
            symbol, prev, curr, change, pct = row
            stocks.append({
                "symbol": symbol, "price": curr.strip(),
                "change": change.strip(), "pct": pct.strip(),
                "arrow": "▲" if not change.strip().startswith("-") else "▼",
            })
        if stocks:
            print(f"[MSE] ✅ {len(stocks)} stocks from bbe.mn")
            return stocks[:10]
    except Exception as e:
        print(f"[MSE] bbe.mn failed: {e}")

    # Source 2: mse.mn fallback
    try:
        r = requests.get("https://mse.mn/api/v1/market/top",
                         timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        data   = r.json()
        stocks = []
        for item in (data.get("data") or data)[:10]:
            change = float(item.get("change", 0) or 0)
            stocks.append({
                "symbol": item.get("symbol", ""),
                "price":  str(item.get("close") or item.get("price", "—")),
                "change": str(change),
                "pct":    f"{abs(change):.2f}%",
                "arrow":  "▲" if change >= 0 else "▼",
            })
        if stocks:
            print(f"[MSE] ✅ {len(stocks)} stocks from mse.mn fallback")
            return stocks[:10]
    except Exception as e:
        print(f"[MSE] mse.mn fallback failed: {e}")

    print("[MSE] ⚠️ Both sources failed")
    return []

def fetch_global_stocks():
    """Fetch S&P 500, NASDAQ, Apple, Nvidia — Yahoo v8 then v7 fallback."""
    stocks  = {}
    symbols = {"S&P 500": "^GSPC", "NASDAQ": "^IXIC", "Apple": "AAPL", "Nvidia": "NVDA"}
    for name, sym in symbols.items():
        # Try Yahoo v8
        try:
            r    = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2d",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=12
            )
            meta  = r.json()["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev  = meta.get("chartPreviousClose", price)
            chg   = price - prev
            pct   = (chg / prev * 100) if prev else 0
            stocks[name] = {
                "price": f"{price:,.2f}",
                "pct":   f"{abs(pct):.2f}%",
                "arrow": "▲" if chg >= 0 else "▼",
            }
            continue
        except Exception:
            pass
        # Fallback Yahoo v7
        try:
            r      = requests.get(
                f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={sym}",
                headers={"User-Agent": "Mozilla/5.0"}, timeout=12
            )
            result = r.json()["quoteResponse"]["result"][0]
            price  = result.get("regularMarketPrice", 0)
            chg    = result.get("regularMarketChange", 0)
            pct    = result.get("regularMarketChangePercent", 0)
            stocks[name] = {
                "price": f"{price:,.2f}",
                "pct":   f"{abs(pct):.2f}%",
                "arrow": "▲" if chg >= 0 else "▼",
            }
        except Exception as e:
            print(f"[GLOBAL] {name} both sources failed: {e}")
    return stocks

def fetch_assets():
    """Fetch crypto + metals + forex — every source has a fallback. No more N/A."""
    assets = {}

    # ── CRYPTO: CoinGecko → CoinCap fallback ──────────────────────────────
    coingecko_ok = False
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,binancecoin,ripple,solana"
            "&vs_currencies=usd&include_24hr_change=true",
            timeout=12
        )
        mapping = {"bitcoin": "Bitcoin", "ethereum": "Ethereum",
                   "binancecoin": "BNB", "ripple": "XRP", "solana": "Solana"}
        for key, name in mapping.items():
            d = r.json().get(key, {})
            if d.get("usd"):
                price = d["usd"]
                chg   = d.get("usd_24h_change", 0)
                assets[name] = {
                    "price": f"${price:,.2f}" if price < 100 else f"${price:,.0f}",
                    "chg":   f"{abs(chg):.2f}%",
                    "arrow": "▲" if chg >= 0 else "▼",
                }
        coingecko_ok = bool(assets)
        if coingecko_ok:
            print(f"[CRYPTO] ✅ CoinGecko: {len(assets)} coins")
    except Exception as e:
        print(f"[CRYPTO] CoinGecko failed: {e}")

    if not coingecko_ok:
        for cid, name in [("bitcoin","Bitcoin"),("ethereum","Ethereum"),("solana","Solana")]:
            try:
                r     = requests.get(f"https://api.coincap.io/v2/assets/{cid}", timeout=10)
                d     = r.json().get("data", {})
                price = float(d.get("priceUsd", 0))
                chg   = float(d.get("changePercent24Hr", 0))
                if price:
                    assets[name] = {
                        "price": f"${price:,.2f}" if price < 100 else f"${price:,.0f}",
                        "chg":   f"{abs(chg):.2f}%",
                        "arrow": "▲" if chg >= 0 else "▼",
                    }
            except Exception as e:
                print(f"[CRYPTO] CoinCap {cid} failed: {e}")
        if assets:
            print(f"[CRYPTO] ✅ CoinCap fallback: {len(assets)} coins")

    # ── METALS: metals.live → CoinGecko tether-gold fallback ──────────────
    for metal_name, symbol in [("Алт", "gold"), ("Мөнгө", "silver"), ("Платин", "platinum")]:
        fetched = False
        try:
            r     = requests.get(f"https://api.metals.live/v1/spot/{symbol}", timeout=10)
            d     = r.json()
            price = d[0].get("price") if isinstance(d, list) else d.get("price")
            if price:
                assets[metal_name] = {
                    "price": f"${float(price):,.2f}/oz",
                    "chg":   "—",
                    "arrow": "—",
                }
                fetched = True
        except Exception:
            pass

        if not fetched and symbol == "gold":
            try:
                r     = requests.get(
                    "https://api.coingecko.com/api/v3/simple/price?ids=tether-gold&vs_currencies=usd",
                    timeout=10
                )
                price = r.json().get("tether-gold", {}).get("usd")
                if price:
                    assets["Алт"] = {
                        "price": f"${float(price):,.2f}/oz",
                        "chg":   "—",
                        "arrow": "—",
                    }
                    fetched = True
            except Exception:
                pass

        if not fetched:
            print(f"[METALS] ⚠️ {metal_name} both sources failed")

    # ── FOREX: exchangerate-api → frankfurter fallback ─────────────────────
    forex_ok = False
    try:
        r     = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        rates = r.json().get("rates", {})
        if rates.get("MNT"):
            assets["USD/MNT"] = {"price": f"₮{rates['MNT']:,.0f}", "chg": "—", "arrow": "—"}
            forex_ok = True
        if rates.get("CNY"):
            assets["USD/CNY"] = {"price": f"¥{rates['CNY']:.4f}", "chg": "—", "arrow": "—"}
    except Exception as e:
        print(f"[FOREX] exchangerate-api failed: {e}")

    if not forex_ok:
        try:
            r     = requests.get("https://api.frankfurter.app/latest?from=USD&to=CNY", timeout=10)
            rates = r.json().get("rates", {})
            if rates.get("CNY"):
                assets["USD/CNY"] = {"price": f"¥{rates['CNY']:.4f}", "chg": "—", "arrow": "—"}
        except Exception as e:
            print(f"[FOREX] frankfurter fallback failed: {e}")

    print(f"[ASSETS] ✅ Total: {len(assets)} assets fetched")
    return assets

# ── GOOGLE TRANSLATE ───────────────────────────────────────────────────────────
def translate(text):
    if not GOOGLE_TRANSLATE or not text:
        return text
    try:
        r = requests.post(
            "https://translation.googleapis.com/language/translate/v2",
            params={"key": GOOGLE_TRANSLATE},
            json={"q": text, "target": "mn", "format": "text"}, timeout=10
        )
        result = r.json()
        if "error" in result:
            return text
        return result["data"]["translations"][0]["translatedText"]
    except Exception:
        return text

# ── CLAUDE AI ──────────────────────────────────────────────────────────────────
def claude_write(title, summary, source, day_context, is_mn_source=False):
    if not ANTHROPIC_KEY:
        return None
    prompt = f"""You are a financial news editor for a Mongolian investment newsletter.

ACCEPT and write analysis for articles about:
- Stock markets, indices, trading (any country)
- Economy, GDP, inflation, interest rates, government budgets
- Commodities: coal, copper, gold, oil, silver
- Crypto: Bitcoin, Ethereum, blockchain
- Big tech companies: Apple, Google, Meta, Amazon, Microsoft, Nvidia, Tesla
- Banking, fintech, payments, digital currency
- Business deals: mergers, acquisitions, IPOs, earnings
- Mongolia: any economic, business, or financial news
- Energy, infrastructure, data centers, AI industry

SKIP only if clearly: pure sports, entertainment, weather, crime with no market impact.
If unsure — ACCEPT it.

Article title: {title}
Summary: {summary[:400]}
Source: {source}
Today's editorial focus: {day_context}

Write in EXACTLY this format:

HEADLINE: [Clear punchy headline, max 12 words]
SUMMARY: [2-3 sentences. What happened, why it matters.]
MONGOLIA_IMPACT: [1-2 sentences. Specific impact on Mongolian investors.]
RECOMMENDATION: [1 sentence practical observation. End with: This is not investment advice.]"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 500,
                "messages":   [{"role": "user", "content": prompt}]
            }, timeout=30
        )
        result = r.json()
        if "error" in result:
            print(f"[CLAUDE ERROR] {result['error']}")
            return None
        return result["content"][0]["text"].strip()
    except Exception as e:
        print(f"[CLAUDE ERROR] {e}")
        return None

def parse_claude(text):
    headline = summary = impact = recommendation = ""
    current = None
    for line in (text or "").strip().split("\n"):
        line = line.strip()
        if line.startswith("HEADLINE:"):
            headline = line.replace("HEADLINE:", "").strip(); current = "h"
        elif line.startswith("SUMMARY:"):
            summary = line.replace("SUMMARY:", "").strip(); current = "s"
        elif line.startswith("MONGOLIA_IMPACT:"):
            impact = line.replace("MONGOLIA_IMPACT:", "").strip(); current = "i"
        elif line.startswith("RECOMMENDATION:"):
            recommendation = line.replace("RECOMMENDATION:", "").strip(); current = "r"
        elif line:
            if current == "s": summary += " " + line
            elif current == "i": impact += " " + line
            elif current == "r": recommendation += " " + line
    return headline.strip(), summary.strip(), impact.strip(), recommendation.strip()

def process_article(title, summary, source, is_breaking, is_mn_source=False):
    _, _, _, day_context = SCHEDULE.get(now_ub().weekday(),
                                        ("", "", "", "Summarize key financial news."))
    raw = claude_write(title, summary, source, day_context, is_mn_source)
    if raw and raw.strip().upper().startswith("SKIP"):
        print(f"[CLAUDE SKIP] {title[:60]}")
        return None
    headline_en, summary_en, impact_en, rec_en = parse_claude(raw)
    if not headline_en:
        headline_en = title
        summary_en  = summary[:200] or "See full article."
        impact_en   = "Monitor for impact on Mongolian markets."
        rec_en      = "This is not investment advice."
    return {
        "headline_en": headline_en, "summary_en": summary_en,
        "impact_en":   impact_en,   "rec_en":     rec_en,
        "headline_mn": translate(headline_en),
        "summary_mn":  translate(summary_en),
        "impact_mn":   translate(impact_en),
        "rec_mn":      translate(rec_en),
    }

# ── FORMAT POSTS ───────────────────────────────────────────────────────────────
def get_tag(is_breaking=False):
    if is_breaking:
        return "🚨", "Breaking News", "Яаралтай мэдээ"
    e, en, mn, _ = SCHEDULE.get(now_ub().weekday(), ("📰", "News", "Мэдээ", ""))
    return e, en, mn

def build_premium_post(a):
    emoji, label_en, label_mn = get_tag(a.get("is_breaking", False))
    en = (
        f"{emoji} <b>{label_en}</b>\n\n"
        f"<b>{a['headline_en']}</b>\n\n"
        f"{a['summary_en']}\n\n"
        f"💡 <i>{a['impact_en']}</i>\n\n"
        f"📌 <i>{a['rec_en']}</i>\n\n"
        f"🔗 {a['link']}\n<i>via {a['source']}</i>"
    )
    mn = (
        f"{emoji} <b>{label_mn}</b>\n\n"
        f"<b>{a['headline_mn']}</b>\n\n"
        f"{a['summary_mn']}\n\n"
        f"💡 <i>{a['impact_mn']}</i>\n\n"
        f"📌 <i>{a['rec_mn']}</i>\n\n"
        f"🔗 {a['link']}\n<i>{a['source']}-аас</i>{DISCLAIMER}"
    )
    return en, mn

def build_free_teaser(a):
    emoji, _, _ = get_tag(a.get("is_breaking", False))
    teaser = a.get("summary_mn", "")[:120]
    return (
        f"{emoji} <b>{a['headline_mn']}</b>\n\n"
        f"{teaser}...\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔒 <b>Дэлгэрэнгүй шинжилгээ Premium сувгаас</b>\n\n"
        f"✅ Бүтэн мэдээ + хөрөнгө оруулалтын зөвлөмж\n"
        f"✅ Монгол хэл дээр AI тайлбар\n"
        f"✅ Өдөр бүр 8:00 - 22:00 хооронд мэдээлэл\n\n"
        f"➡️ <b>Нэгдэх: {PREMIUM_INVITE}</b>"
    )

def build_admin_preview(a):
    emoji, label_en, _ = get_tag(a.get("is_breaking", False))
    tag = "🚨 BREAKING — APPROVE FAST!" if a.get("is_breaking") else f"{emoji} {label_en}"
    return (
        f"<b>{tag}</b>\n\n"
        f"🇬🇧 <b>{a['headline_en']}</b>\n{a['summary_en']}\n"
        f"💡 {a['impact_en']}\n📌 {a['rec_en']}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🇲🇳 <b>{a['headline_mn']}</b>\n{a['summary_mn']}\n"
        f"💡 {a['impact_mn']}\n📌 {a['rec_mn']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔗 {a['link']}\n<i>via {a['source']}</i>"
    )

def build_edit_template(a):
    emoji, label_en, label_mn = get_tag(a.get("is_breaking", False))
    return (
        f"✏️ Edit and send back:\n\n"
        f"══ ENGLISH (Premium) ══\n{emoji} {label_en}\n\n"
        f"{a['headline_en']}\n\n{a['summary_en']}\n\n"
        f"💡 {a['impact_en']}\n\n📌 {a['rec_en']}\n\n"
        f"🔗 {a['link']}\nvia {a['source']}\n\n"
        f"══ MONGOLIAN (Premium) ══\n{emoji} {label_mn}\n\n"
        f"{a['headline_mn']}\n\n{a['summary_mn']}\n\n"
        f"💡 {a['impact_mn']}\n\n📌 {a['rec_mn']}\n\n"
        f"🔗 {a['link']}\n{a['source']}-аас{DISCLAIMER}\n\n"
        f"══ FREE TEASER ══\n{emoji} {a['headline_mn']}\n\n"
        f"{a['summary_mn'][:120]}...\n\n"
        f"🔒 Дэлгэрэнгүй шинжилгээ Premium сувгаас\n"
        f"➡️ Нэгдэх: {PREMIUM_INVITE}"
    )

# ── POST HELPERS ───────────────────────────────────────────────────────────────
def post_approved(a):
    en, mn = build_premium_post(a)
    teaser = build_free_teaser(a)
    send(PREMIUM_CHANNEL, en);   time.sleep(2)
    send(PREMIUM_CHANNEL, mn);   time.sleep(2)
    send(FREE_CHANNEL, teaser)
    print(f"[POSTED] {a['headline_en'][:60]}")

def post_custom(text):
    if "══ MONGOLIAN (Premium) ══" in text:
        parts = text.split("══")
        en_part = mn_part = teaser_part = ""
        current = None
        for p in parts:
            p = p.strip()
            if "ENGLISH (Premium)" in p:    current = "en"
            elif "MONGOLIAN (Premium)" in p: current = "mn"
            elif "FREE TEASER" in p:         current = "teaser"
            elif current == "en" and p:      en_part = p
            elif current == "mn" and p:      mn_part = p
            elif current == "teaser" and p:  teaser_part = p
        if en_part:     send(PREMIUM_CHANNEL, en_part);     time.sleep(2)
        if mn_part:     send(PREMIUM_CHANNEL, mn_part);     time.sleep(2)
        if teaser_part: send(FREE_CHANNEL, teaser_part)
    else:
        send(PREMIUM_CHANNEL, text)
    print("[POSTED CUSTOM]")

# ── MORNING BRIEF ──────────────────────────────────────────────────────────────
def post_morning_brief():
    print("[MORNING BRIEF] Fetching all data...")
    ub        = now_ub()
    date_str  = ub.strftime("%Y.%m.%d")
    day_names = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
    day_mn    = day_names[ub.weekday()]
    assets        = fetch_assets()
    mse_stocks    = fetch_mse_top10()
    global_stocks = fetch_global_stocks()

    # MSE post
    mse_lines = ""
    for s in mse_stocks:
        icon = "🟢" if s["arrow"] == "▲" else "🔴"
        mse_lines += f"{icon} <b>{s['symbol']}</b>  ₮{s['price']}  {s['arrow']}{s['pct']}\n"
    if not mse_lines:
        mse_lines = "<i>МХБ-ийн өгөгдөл татаж чадсангүй</i>"

    premium_mse = (
        f"🇲🇳 <b>МХБ — Өнөөдрийн Топ 10 хувьцаа</b>\n"
        f"<i>{day_mn}, {date_str}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n{mse_lines}"
        f"━━━━━━━━━━━━━━━━━━\n<i>Эх сурвалж: stock.bbe.mn</i>"
    )

    # Assets post
    asset_emojis = {
        "Bitcoin": "₿", "Ethereum": "💎", "BNB": "🔶", "XRP": "💧",
        "Solana": "🌊", "Алт": "🥇", "Мөнгө": "🥈", "Платин": "⚪",
        "USD/MNT": "💵", "USD/CNY": "🇨🇳"
    }
    asset_lines = ""
    for name, d in list(assets.items())[:10]:
        icon    = asset_emojis.get(name, "📊")
        chg_str = f"  {d.get('arrow','')}{d.get('chg','')}" if d.get("chg") != "—" else ""
        asset_lines += f"{icon} <b>{name}</b>  {d['price']}{chg_str}\n"
    premium_assets = (
        f"💰 <b>10 Хөрөнгийн үнэ</b>\n"
        f"<i>{day_mn}, {date_str}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n{asset_lines}"
        f"━━━━━━━━━━━━━━━━━━\n<i>Крипто: CoinGecko | Металл: Metals.live</i>"
    )

    # Global stocks post
    global_emojis = {"S&P 500": "🇺🇸", "NASDAQ": "💻", "Apple": "🍎", "Nvidia": "🤖"}
    global_lines  = ""
    for name, d in global_stocks.items():
        icon = global_emojis.get(name, "📈")
        global_lines += f"{icon} <b>{name}</b>  {d['price']}  {d['arrow']}{d['pct']}\n"
    btc = assets.get("Bitcoin", {})
    if btc:
        global_lines += f"₿ <b>Bitcoin</b>  {btc['price']}  {btc.get('arrow','')}{btc.get('chg','')}\n"
    # Only send global post if we have data
    if global_lines:
        premium_global = (
            f"🌍 <b>Дэлхийн томоохон хөрөнгүүд</b>\n"
            f"<i>{day_mn}, {date_str}</i>\n"
            f"━━━━━━━━━━━━━━━━━━\n{global_lines}"
            f"━━━━━━━━━━━━━━━━━━\n<i>Эх сурвалж: Yahoo Finance</i>"
        )
    else:
        premium_global = None

    # Free channel teaser — only show lines where data actually exists
    top_stock = mse_stocks[0] if mse_stocks else None
    free_post = (
        f"🌅 <b>Өглөөний зах зээлийн тойм</b>\n"
        f"<i>{day_mn}, {date_str}</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    btc = assets.get("Bitcoin")
    if btc:
        free_post += f"₿ Bitcoin:  <b>{btc['price']}</b>\n"
    gold = assets.get("Алт")
    if gold:
        free_post += f"🥇 Алт:     <b>{gold['price']}</b>\n"
    usd = assets.get("USD/MNT")
    if usd:
        free_post += f"💵 USD/MNT: <b>{usd['price']}</b>\n"
    if top_stock:
        icon = "🟢" if top_stock["arrow"] == "▲" else "🔴"
        free_post += f"{icon} МХБ топ: <b>{top_stock['symbol']}</b> ₮{top_stock['price']} {top_stock['arrow']}{top_stock['pct']}\n"
    free_post += (
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 МХБ Топ 10, 10 хөрөнгийн үнэ, дэлхийн зах зээлийг Premium сувгаас аваарай!\n"
        f"➡️ <b>Нэгдэх: {PREMIUM_INVITE}</b>"
    )

    send(PREMIUM_CHANNEL, premium_mse);    time.sleep(3)
    send(PREMIUM_CHANNEL, premium_assets); time.sleep(3)
    if premium_global:
        send(PREMIUM_CHANNEL, premium_global); time.sleep(2)
    send(FREE_CHANNEL, free_post)
    print(f"[MORNING BRIEF] Done — MSE: {len(mse_stocks)}, Assets: {len(assets)}")

# ── APPROVAL QUEUE ─────────────────────────────────────────────────────────────
def queue_for_approval(article):
    pending = load_json(PENDING_FILE, {})
    aid     = article["id"]
    pending[aid] = article
    save_json(PENDING_FILE, pending)
    markup = {"inline_keyboard": [[
        {"text": "✅ Agree", "callback_data": f"agree:{aid}"},
        {"text": "✏️ Edit",  "callback_data": f"edit:{aid}"},
        {"text": "❌ Skip",  "callback_data": f"skip:{aid}"},
    ]]}
    result = send(ADMIN_CHAT_ID, build_admin_preview(article), markup=markup)
    msg_id = result.get("result", {}).get("message_id")
    if msg_id:
        pending[aid]["preview_msg_id"] = msg_id
        save_json(PENDING_FILE, pending)

# ── ADMIN COMMANDS ─────────────────────────────────────────────────────────────
def handle_command(text):
    state = load_json(STATE_FILE, {})
    parts = text.strip().split()
    cmd   = parts[0].lower()
    if cmd in ("/sublist", "/subpending", "/subremove"):
        handle_sub_command(parts)
        return
    if cmd == "/status":
        ub = now_ub()
        send(ADMIN_CHAT_ID,
            f"🤖 <b>Bot Status</b>\n\n"
            f"⏰ UB time: <b>{ub.strftime('%H:%M')}</b>\n"
            f"🕐 Active hours: <b>{state.get('hour_start', ACTIVE_HOUR_START)}:00 – {state.get('hour_end', ACTIVE_HOUR_END)}:00</b>\n"
            f"📡 Active: <b>{'Yes' if is_active_hours() else 'No'}</b>\n"
            f"⏸ Paused: <b>{'Yes' if state.get('paused') else 'No'}</b>\n\n"
            f"<b>News commands:</b>\n"
            f"/pause /resume /hours 8 22 /checknow /morning /status\n\n"
            f"<b>Subscription commands:</b>\n"
            f"/sublist /subpending /subremove 123456"
        )
    elif cmd == "/pause":
        state["paused"] = True; save_json(STATE_FILE, state)
        send(ADMIN_CHAT_ID, "⏸ Bot paused.")
    elif cmd == "/resume":
        state["paused"] = False; save_json(STATE_FILE, state)
        send(ADMIN_CHAT_ID, f"▶️ Bot resumed! UB: {now_ub().strftime('%H:%M')}")
    elif cmd == "/hours":
        if len(parts) == 3:
            try:
                hs, he = int(parts[1]), int(parts[2])
                if 0 <= hs < he <= 24:
                    state["hour_start"] = hs; state["hour_end"] = he
                    save_json(STATE_FILE, state)
                    send(ADMIN_CHAT_ID, f"✅ Hours set: <b>{hs}:00 – {he}:00 UB</b>")
                else:
                    send(ADMIN_CHAT_ID, "❌ Invalid. Example: /hours 8 22")
            except ValueError:
                send(ADMIN_CHAT_ID, "❌ Use numbers. Example: /hours 8 22")
        else:
            send(ADMIN_CHAT_ID, f"Current: {state.get('hour_start',8)}:00–{state.get('hour_end',22)}:00\nChange: /hours 8 22")
    elif cmd == "/checknow":
        send(ADMIN_CHAT_ID, "🔍 Checking feeds now...")
        check_feeds()
    elif cmd == "/morning":
        send(ADMIN_CHAT_ID, "🌅 Posting morning brief now...")
        post_morning_brief()
    else:
        send(ADMIN_CHAT_ID,
            f"❓ Unknown: {cmd}\n\n"
            "/status /pause /resume /hours /checknow /morning\n"
            "/sublist /subpending /subremove"
        )

# ── HANDLE UPDATES ─────────────────────────────────────────────────────────────
def handle_updates():
    sent       = load_json(SENT_FILE, {})
    pending    = load_json(PENDING_FILE, {})
    edit_state = load_json(EDIT_STATE_FILE, {})
    offset     = sent.get("_offset", 0)
    resp       = tg("getUpdates", {"offset": offset, "timeout": 5})
    updates    = resp.get("result", [])

    for update in updates:
        offset = update["update_id"] + 1
        cb = update.get("callback_query")
        if cb:
            cb_data = cb.get("data", "")
            if ":" not in cb_data:
                continue
            action, aid = cb_data.split(":", 1)
            if action == "sub_approve":
                handle_sub_approve(aid, cb["id"]); continue
            if action == "sub_reject":
                handle_sub_reject(aid, cb["id"]); continue
            if action == "plan_select":
                ps_parts  = aid.split(":")
                ps_uid    = ps_parts[0]
                ps_plan   = ps_parts[1] if len(ps_parts) > 1 else "monthly"
                ps_chatid = cb.get("message", {}).get("chat", {}).get("id")
                handle_plan_select_msg(ps_uid, ps_plan, ps_chatid, cb["id"]); continue
            art = pending.get(aid)
            if not art:
                answer_cb(cb["id"], "Already handled."); continue
            if action == "agree":
                post_approved(art)
                answer_cb(cb["id"], "✅ Posted!")
                tg("editMessageText", {
                    "chat_id": ADMIN_CHAT_ID, "message_id": art.get("preview_msg_id"),
                    "text": f"✅ Posted: <b>{art['headline_en'][:80]}</b>", "parse_mode": "HTML"
                })
                del pending[aid]; save_json(PENDING_FILE, pending)
            elif action == "edit":
                result  = send(ADMIN_CHAT_ID, build_edit_template(art))
                tmpl_id = result.get("result", {}).get("message_id")
                edit_state["waiting"] = {
                    "aid": aid, "template_msg_id": tmpl_id,
                    "preview_msg_id": art.get("preview_msg_id"),
                }
                save_json(EDIT_STATE_FILE, edit_state)
                answer_cb(cb["id"], "✏️ Edit and send back!")
            elif action == "skip":
                answer_cb(cb["id"], "❌ Skipped.")
                tg("editMessageText", {
                    "chat_id": ADMIN_CHAT_ID, "message_id": art.get("preview_msg_id"),
                    "text": f"❌ Skipped: {art['headline_en'][:80]}", "parse_mode": "HTML"
                })
                del pending[aid]; save_json(PENDING_FILE, pending)

        msg = update.get("message")
        if not msg:
            continue
        chat_type = msg.get("chat", {}).get("type", "")
        chat_id   = str(msg.get("chat", {}).get("id", ""))
        text      = msg.get("text", "").strip()
        if chat_type == "private" and str(chat_id) != str(ADMIN_CHAT_ID):
            handle_private_message(msg); continue
        if chat_id == str(ADMIN_CHAT_ID):
            waiting = edit_state.get("waiting")
            if not text:
                continue
            if text.startswith("/"):
                handle_command(text); continue
            if waiting:
                aid = waiting.get("aid")
                art = pending.get(aid)
                if art:
                    post_custom(text)
                    send(ADMIN_CHAT_ID, "✅ Your edited version has been posted!")
                    tg("editMessageText", {
                        "chat_id": ADMIN_CHAT_ID, "message_id": waiting.get("preview_msg_id"),
                        "text": f"✅ Posted (edited): <b>{art['headline_en'][:80]}</b>", "parse_mode": "HTML"
                    })
                    del pending[aid]; save_json(PENDING_FILE, pending)
                edit_state.pop("waiting", None)
                save_json(EDIT_STATE_FILE, edit_state)

    if updates:
        sent["_offset"] = offset
        save_json(SENT_FILE, sent)

# ── FEED CHECKER ───────────────────────────────────────────────────────────────
def is_relevant(title, summary):
    text = (title + " " + summary).lower()
    if any(r.lower() in text for r in REJECT_KEYWORDS):
        return False
    return any(k.lower() in text for k in KEYWORDS)

def check_feeds():
    sent     = load_json(SENT_FILE, {})
    sent_ids = set(k for k in sent if not k.startswith("_"))
    queued   = 0; breaking = []; normal = []
    for feed_url, source_name in ALL_FEEDS:
        is_mn = any(feed_url == f for f, _ in MN_FEEDS)
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                link  = entry.get("link", "")
                title = entry.get("title", "").strip()
                if not link or not title:
                    continue
                link_id  = make_id(link)
                title_id = make_id(title)
                if link_id in sent_ids or title_id in sent_ids:
                    continue
                summary = entry.get("summary", "")
                if not is_relevant(title, summary):
                    continue
                item = {
                    "link_id": link_id, "title_id": title_id,
                    "title": title, "summary": summary,
                    "link": link, "source": source_name, "is_mn": is_mn,
                    "is_breaking": any(w in title.lower() for w in BREAKING_WORDS),
                }
                (breaking if item["is_breaking"] else normal).append(item)
                sent_ids.add(link_id); sent_ids.add(title_id)
                sent[link_id] = True; sent[title_id] = True
        except Exception as e:
            print(f"[FEED ERROR] {source_name}: {e}")
    for item in breaking[:2]:
        processed = process_article(item["title"], item["summary"],
                                    item["source"], True, item["is_mn"])
        if not processed: continue
        queue_for_approval({"id": item["link_id"], "link": item["link"],
                            "source": item["source"], "is_breaking": True, **processed})
        queued += 1; time.sleep(2)
    for item in normal[:3]:
        processed = process_article(item["title"], item["summary"],
                                    item["source"], False, item["is_mn"])
        if not processed: continue
        queue_for_approval({"id": item["link_id"], "link": item["link"],
                            "source": item["source"], "is_breaking": False, **processed})
        queued += 1; time.sleep(2)
    save_json(SENT_FILE, sent)
    print(f"[{now_ub().strftime('%H:%M UB')}] Queued {queued} articles")

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("MGL Newsroom Bot — with Subscription Manager")
    print(f"  Free    : {FREE_CHANNEL}")
    print(f"  Premium : {PREMIUM_CHANNEL}")
    print(f"  Admin   : {ADMIN_CHAT_ID}")
    print(f"  Claude  : {'✅' if ANTHROPIC_KEY    else '❌ missing'}")
    print(f"  Google  : {'✅' if GOOGLE_TRANSLATE else '❌ missing'}")
    print(f"  Bank    : {BANK_NAME} — {BANK_ACCOUNT}")
    print(f"  Price   : ₮{PRICE_MONTHLY:,}/сар | ₮{PRICE_YEARLY:,}/жил")
    print("=" * 55)
    if not BOT_TOKEN:     print("[FATAL] BOT_TOKEN missing!");     return
    if not ADMIN_CHAT_ID: print("[FATAL] ADMIN_CHAT_ID missing!"); return
    send(ADMIN_CHAT_ID,
        "🤖 <b>MGL Newsroom Bot — with Subscription Manager</b>\n\n"
        f"📢 Free: {FREE_CHANNEL}\n"
        f"💎 Premium: private channel\n"
        f"💳 Сарын: ₮{PRICE_MONTHLY:,} | Жилийн: ₮{PRICE_YEARLY:,}\n"
        f"🏦 Bank: {BANK_NAME}\n\n"
        "<b>Subscription commands:</b>\n"
        "/sublist — active subscribers\n"
        "/subpending — pending payments\n"
        "/subremove ID — remove subscriber\n\n"
        "<b>News commands:</b>\n"
        "/status /pause /resume /checknow /morning\n\n"
        "✅ Running!"
    )
    while True:
        try:
            handle_updates()
            if should_post_morning_brief():
                post_morning_brief()
            if is_active_hours() and should_check_feeds():
                check_feeds()
            if should_check_subscriptions():
                check_subscriptions()
        except Exception as e:
            print(f"[LOOP ERROR] {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()