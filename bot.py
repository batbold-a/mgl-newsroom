import feedparser
import requests
import time
import json
import os
from datetime import datetime, timezone

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN")
PAID_CHANNEL  = os.environ.get("PAID_CHANNEL", "@mgl_newsroom")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
DISCLAIMER = "\n\n⚠️ Энэхүү мэдээлэл нь хөрөнгө оруулалтын зөвлөгөө биш."

# ── NEWS SOURCES ───────────────────────────────────────────────────────────────
RSS_FEEDS = [
    ("https://feeds.reuters.com/reuters/businessNews",          "Reuters Business"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml","NY Times Business"),
    ("https://feeds.feedburner.com/entrepreneur/latest",        "Entrepreneur"),
    ("https://techcrunch.com/feed/",                            "TechCrunch"),
    ("https://www.mining.com/feed/",                            "Mining.com"),
    ("https://www.investing.com/rss/news_301.rss",              "Investing.com"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/",         "CoinDesk"),
]

KEYWORDS = [
    "market", "stock", "stocks", "S&P", "nasdaq", "rally", "crash",
    "fed", "federal reserve", "interest rate", "inflation", "recession", "GDP",
    "coal", "copper", "gold", "silver", "oil", "commodity", "commodities",
    "mining", "mineral", "mongolia", "mongolian", "oyu tolgoi", "tavan tolgoi",
    "AI", "artificial intelligence", "startup", "IPO", "acquisition",
    "earnings", "revenue", "profit", "loss", "quarterly",
    "apple", "google", "microsoft", "amazon", "tesla", "nvidia",
    "bitcoin", "crypto", "ethereum", "blockchain",
    "investment", "investor", "fund", "hedge fund", "bond", "yield",
]

SCHEDULE = {
    0: ("📊", "Weekly Market Outlook",  "7 хоногийн зах зээлийн тойм"),
    1: ("🌅", "Morning Snapshot",       "Өглөөний тойм"),
    2: ("⛏️", "Mining & Commodities",   "Уул уурхай ба түүхий эд"),
    3: ("💡", "Finance Insight",        "Санхүүгийн мэдээлэл"),
    4: ("📋", "Weekly Recap",           "7 хоногийн дүн"),
    5: ("🌅", "Weekend Snapshot",       "Амралтын өдрийн тойм"),
    6: ("🌅", "Weekend Snapshot",       "Амралтын өдрийн тойм"),
}

# ── FILES ──────────────────────────────────────────────────────────────────────
SENT_FILE      = "sent_articles.json"
PENDING_FILE   = "pending_articles.json"
EDIT_STATE_FILE = "edit_state.json"   # tracks who is editing what

# ── FILE HELPERS ───────────────────────────────────────────────────────────────
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

def send(chat_id, text, markup=None, reply_to=None):
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if markup:
        payload["reply_markup"] = json.dumps(markup)
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    return tg("sendMessage", payload)

def answer_cb(cb_id, text):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

def delete_message(chat_id, message_id):
    tg("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

# ── FORMAT ─────────────────────────────────────────────────────────────────────
def get_schedule_tag(is_breaking=False):
    if is_breaking:
        return "🚨", "Breaking News", "Яаралтай мэдээ"
    day = datetime.now(timezone.utc).weekday()
    return SCHEDULE.get(day, ("📰", "News", "Мэдээ"))

def build_post_text(article):
    """Build the full post text that goes to the channel."""
    emoji, label_en, label_mn = get_schedule_tag(article.get("is_breaking", False))
    en = (
        f"{emoji} <b>{label_en}</b>\n\n"
        f"<b>{article['title_en']}</b>\n\n"
        f"🔗 {article['link']}\n"
        f"<i>via {article['source']}</i>"
    )
    mn = (
        f"{emoji} <b>{label_mn}</b>\n\n"
        f"<b>{article['title_mn']}</b>\n\n"
        f"🔗 {article['link']}\n"
        f"<i>{article['source']}-аас</i>"
        f"{DISCLAIMER}"
    )
    return en, mn

def build_edit_template(article):
    """Plain text template the admin can copy, edit, and send back."""
    emoji, label_en, label_mn = get_schedule_tag(article.get("is_breaking", False))
    return (
        f"✏️ Edit the text below and send it back to me.\n"
        f"I will post exactly what you write.\n\n"
        f"──────────────────\n"
        f"{emoji} {label_en}\n\n"
        f"{article['title_en']}\n\n"
        f"🔗 {article['link']}\n"
        f"via {article['source']}\n"
        f"──────────────────\n\n"
        f"🇲🇳 Mongolian version:\n\n"
        f"{emoji} {label_mn}\n\n"
        f"{article['title_mn']}\n\n"
        f"🔗 {article['link']}\n"
        f"{article['source']}-аас\n"
        f"{DISCLAIMER}"
    )

def build_admin_preview(article):
    """Preview card sent to admin for review."""
    emoji, label_en, _ = get_schedule_tag(article.get("is_breaking", False))
    tag = f"🚨 BREAKING" if article.get("is_breaking") else f"{emoji} {label_en}"
    return (
        f"<b>New article — {tag}</b>\n\n"
        f"🇬🇧 <b>{article['title_en']}</b>\n\n"
        f"🇲🇳 {article['title_mn']}\n\n"
        f"🔗 {article['link']}\n"
        f"<i>via {article['source']}</i>"
    )

# ── POST TO CHANNEL ────────────────────────────────────────────────────────────
def post_to_channel(en_text, mn_text):
    """Post English then Mongolian to the paid channel."""
    # Strip HTML for channel since we rebuild it
    send(PAID_CHANNEL, en_text)
    time.sleep(2)
    send(PAID_CHANNEL, mn_text)
    print(f"[POSTED] to {PAID_CHANNEL}")

def post_custom_to_channel(custom_text):
    """Post admin-edited custom text directly to channel."""
    # Split on the separator line if admin kept the template structure
    parts = custom_text.split("──────────────────")
    if len(parts) >= 3:
        # Admin used the template — post each section separately
        en_part = parts[1].strip()
        mn_part = parts[2].strip() if len(parts) > 2 else ""
        # Remove the "Mongolian version:" header if present
        mn_part = mn_part.replace("🇲🇳 Mongolian version:", "").strip()
        if en_part:
            send(PAID_CHANNEL, en_part)
            time.sleep(2)
        if mn_part:
            send(PAID_CHANNEL, mn_part)
    else:
        # Admin wrote freely — post as one message
        send(PAID_CHANNEL, custom_text)
    print(f"[POSTED CUSTOM] to {PAID_CHANNEL}")

# ── APPROVAL QUEUE ─────────────────────────────────────────────────────────────
def queue_for_approval(article):
    pending = load_json(PENDING_FILE, {})
    aid = article["id"]
    pending[aid] = article
    save_json(PENDING_FILE, pending)

    markup = {"inline_keyboard": [[
        {"text": "✅ Agree",  "callback_data": f"agree:{aid}"},
        {"text": "✏️ Edit",  "callback_data": f"edit:{aid}"},
        {"text": "❌ Skip",  "callback_data": f"skip:{aid}"},
    ]]}
    result = send(ADMIN_CHAT_ID, build_admin_preview(article), markup=markup)

    # Save the message_id so we can delete/update it later
    msg_id = result.get("result", {}).get("message_id")
    if msg_id:
        pending[aid]["preview_msg_id"] = msg_id
        save_json(PENDING_FILE, pending)

# ── CALLBACK + MESSAGE HANDLER ─────────────────────────────────────────────────
def handle_updates():
    sent       = load_json(SENT_FILE, {})
    pending    = load_json(PENDING_FILE, {})
    edit_state = load_json(EDIT_STATE_FILE, {})
    offset     = sent.get("_offset", 0)

    resp    = tg("getUpdates", {"offset": offset, "timeout": 5})
    updates = resp.get("result", [])

    for update in updates:
        offset = update["update_id"] + 1

        # ── Handle button taps ──────────────────────────────────────────────
        cb = update.get("callback_query")
        if cb:
            data = cb.get("data", "")
            if ":" not in data:
                continue
            action, aid = data.split(":", 1)
            art = pending.get(aid)
            if not art:
                answer_cb(cb["id"], "Already handled.")
                continue

            if action == "agree":
                en_text, mn_text = build_post_text(art)
                post_to_channel(en_text, mn_text)
                answer_cb(cb["id"], "✅ Posted to channel!")
                # Update preview message to show it was approved
                tg("editMessageText", {
                    "chat_id":    ADMIN_CHAT_ID,
                    "message_id": art.get("preview_msg_id"),
                    "text":       f"✅ Posted: <b>{art['title_en'][:80]}</b>",
                    "parse_mode": "HTML"
                })
                del pending[aid]
                save_json(PENDING_FILE, pending)

            elif action == "edit":
                # Send edit template to admin
                template = build_edit_template(art)
                result = send(ADMIN_CHAT_ID, template)
                template_msg_id = result.get("result", {}).get("message_id")
                # Save edit state — waiting for admin's reply
                edit_state["waiting"] = {
                    "aid":             aid,
                    "template_msg_id": template_msg_id,
                    "preview_msg_id":  art.get("preview_msg_id"),
                }
                save_json(EDIT_STATE_FILE, edit_state)
                answer_cb(cb["id"], "✏️ Edit the text and send it back!")

            elif action == "skip":
                answer_cb(cb["id"], "❌ Skipped.")
                tg("editMessageText", {
                    "chat_id":    ADMIN_CHAT_ID,
                    "message_id": art.get("preview_msg_id"),
                    "text":       f"❌ Skipped: {art['title_en'][:80]}",
                    "parse_mode": "HTML"
                })
                del pending[aid]
                save_json(PENDING_FILE, pending)

        # ── Handle text messages (admin's edited post) ──────────────────────
        msg = update.get("message")
        if msg and str(msg.get("chat", {}).get("id")) == str(ADMIN_CHAT_ID):
            text = msg.get("text", "").strip()
            waiting = edit_state.get("waiting")

            # Ignore commands and empty messages
            if not text or text.startswith("/"):
                continue

            # If we're waiting for an edit
            if waiting:
                aid = waiting.get("aid")
                art = pending.get(aid)
                if art:
                    # Post the custom edited text to channel
                    post_custom_to_channel(text)
                    # Confirm to admin
                    send(ADMIN_CHAT_ID, "✅ Your edited version has been posted to the channel!")
                    # Clean up preview message
                    tg("editMessageText", {
                        "chat_id":    ADMIN_CHAT_ID,
                        "message_id": waiting.get("preview_msg_id"),
                        "text":       f"✅ Posted (edited): <b>{art['title_en'][:80]}</b>",
                        "parse_mode": "HTML"
                    })
                    del pending[aid]
                    save_json(PENDING_FILE, pending)
                # Clear edit state
                edit_state.pop("waiting", None)
                save_json(EDIT_STATE_FILE, edit_state)

    if updates:
        sent["_offset"] = offset
        save_json(SENT_FILE, sent)

# ── FEED CHECKER ───────────────────────────────────────────────────────────────
def is_relevant(title, summary):
    text = (title + " " + summary).lower()
    return any(k.lower() in text for k in KEYWORDS)

def check_feeds():
    sent     = load_json(SENT_FILE, {})
    sent_ids = set(k for k in sent if not k.startswith("_"))
    queued   = 0

    for feed_url, source_name in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                print(f"[EMPTY] {source_name}")
                continue
            for entry in feed.entries[:10]:
                aid = getattr(entry, "id", None) or entry.get("link", "")
                if not aid or aid in sent_ids:
                    continue
                title   = entry.get("title", "").strip()
                summary = entry.get("summary", "")
                link    = entry.get("link", "")
                if not title or not link:
                    continue
                if not is_relevant(title, summary):
                    continue

                is_breaking = any(w in title.lower() for w in [
                    "breaking", "urgent", "flash", "alert", "crash",
                    "collapse", "emergency", "ban", "sanction", "plunge"
                ])

                article = {
                    "id":          aid,
                    "title_en":    title,
                    "title_mn":    title + " (Монгол орчуулга удахгүй)",
                    "link":        link,
                    "source":      source_name,
                    "is_breaking": is_breaking,
                }
                queue_for_approval(article)
                sent_ids.add(aid)
                sent[aid] = True
                queued += 1
                time.sleep(1)
                if queued >= 4:
                    break
        except Exception as e:
            print(f"[FEED ERROR] {source_name}: {e}")
        if queued >= 4:
            break

    save_json(SENT_FILE, sent)
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    print(f"[{now}] Queued {queued} articles")

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("MGL Newsroom Bot starting...")
    print(f"  Channel : {PAID_CHANNEL}")
    print(f"  Admin   : {ADMIN_CHAT_ID}")
    print("=" * 50)

    if not BOT_TOKEN:
        print("[FATAL] BOT_TOKEN missing!")
        return
    if not ADMIN_CHAT_ID:
        print("[FATAL] ADMIN_CHAT_ID missing!")
        return

    send(ADMIN_CHAT_ID,
        "🤖 <b>MGL Newsroom Bot is running!</b>\n\n"
        "For each article you will get 3 buttons:\n\n"
        "✅ <b>Agree</b> — posts immediately as is\n"
        "✏️ <b>Edit</b> — sends you the text to copy, edit and send back\n"
        "❌ <b>Skip</b> — discards the article\n\n"
        f"Posting to: {PAID_CHANNEL}\n"
        "Checking every 2 hours.")

    while True:
        try:
            handle_updates()
            check_feeds()
        except Exception as e:
            print(f"[LOOP ERROR] {e}")
        time.sleep(7200)

if __name__ == "__main__":
    main()
