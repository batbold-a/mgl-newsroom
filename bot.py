import feedparser
import requests
import time
import json
import os
from datetime import datetime, timezone

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BOT_TOKEN         = os.environ.get("BOT_TOKEN")
FREE_CHANNEL      = os.environ.get("FREE_CHANNEL",    "@mgl_newsroom")
PREMIUM_CHANNEL   = os.environ.get("PREMIUM_CHANNEL", "@mgl_newsroom")  # set via Railway var
PREMIUM_INVITE    = "https://t.me/+BxQ8PEdcyc02YmM9"                    # private channel invite
ADMIN_CHAT_ID     = os.environ.get("ADMIN_CHAT_ID")
ANTHROPIC_KEY     = os.environ.get("ANTHROPIC_API_KEY")

DISCLAIMER = "\n\n⚠️ Энэхүү мэдээлэл нь хөрөнгө оруулалтын зөвлөгөө биш."

# ── NEWS SOURCES ───────────────────────────────────────────────────────────────
RSS_FEEDS = [
    ("https://feeds.reuters.com/reuters/businessNews",           "Reuters Business"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml","NY Times Business"),
    ("https://feeds.feedburner.com/entrepreneur/latest",         "Entrepreneur"),
    ("https://techcrunch.com/feed/",                             "TechCrunch"),
    ("https://www.mining.com/feed/",                             "Mining.com"),
    ("https://www.investing.com/rss/news_301.rss",               "Investing.com"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/",          "CoinDesk"),
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
SENT_FILE       = "sent_articles.json"
PENDING_FILE    = "pending_articles.json"
EDIT_STATE_FILE = "edit_state.json"

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

def send(chat_id, text, markup=None):
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if markup:
        payload["reply_markup"] = json.dumps(markup)
    return tg("sendMessage", payload)

def answer_cb(cb_id, text):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

# ── CLAUDE AI ──────────────────────────────────────────────────────────────────
def generate_mongolian_summary(title, summary, source):
    if not ANTHROPIC_KEY:
        return f"TITLE: {title}\nSUMMARY: (AI disabled)\nANALYSIS: Add ANTHROPIC_API_KEY in Railway."

    prompt = f"""You are a financial news editor for a Mongolian investment channel.

Article title: {title}
Article summary: {summary}
Source: {source}

Write a response in this EXACT format in Mongolian:

TITLE: [Translate the title naturally into Mongolian — sound like a real Mongolian news headline]

SUMMARY: [2-3 sentences in simple clear Mongolian explaining what happened and why it matters]

ANALYSIS: [1-2 sentences explaining what this means specifically for Mongolian investors — MSE stocks, tugrug, commodity prices, or Mongolian businesses]

Write ONLY Mongolian content. No English. No extra explanation."""

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
                "max_tokens": 600,
                "messages":   [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        result = r.json()
        print(f"[CLAUDE RAW] {result}")
        if "error" in result:
            print(f"[CLAUDE API ERROR] {result['error']}")
            return f"TITLE: {title}\nSUMMARY: AI алдаа гарлаа.\nANALYSIS:"
        return result["content"][0]["text"].strip()
    except Exception as e:
        print(f"[CLAUDE ERROR] {e}")
        return f"TITLE: {title}\nSUMMARY: AI алдаа гарлаа.\nANALYSIS:"

def parse_ai_response(ai_text):
    title_mn = summary_mn = analysis_mn = ""
    current = None
    for line in ai_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("TITLE:"):
            title_mn = line.replace("TITLE:", "").strip()
            current = "title"
        elif line.startswith("SUMMARY:"):
            summary_mn = line.replace("SUMMARY:", "").strip()
            current = "summary"
        elif line.startswith("ANALYSIS:"):
            analysis_mn = line.replace("ANALYSIS:", "").strip()
            current = "analysis"
        elif line and current == "summary":
            summary_mn += " " + line
        elif line and current == "analysis":
            analysis_mn += " " + line
    return title_mn.strip(), summary_mn.strip(), analysis_mn.strip()

# ── SCHEDULE ───────────────────────────────────────────────────────────────────
def get_tag(is_breaking=False):
    if is_breaking:
        return "🚨", "Breaking News", "Яаралтай мэдээ"
    return SCHEDULE.get(datetime.now(timezone.utc).weekday(),
                        ("📰", "News", "Мэдээ"))

# ── FORMAT POSTS ───────────────────────────────────────────────────────────────
def build_premium_post(article):
    """Full AI post for premium private channel — English + Mongolian."""
    emoji, label_en, label_mn = get_tag(article.get("is_breaking", False))

    en = (
        f"{emoji} <b>{label_en}</b>\n\n"
        f"<b>{article['title_en']}</b>\n\n"
        f"🔗 {article['link']}\n"
        f"<i>via {article['source']}</i>"
    )

    mn = (
        f"{emoji} <b>{label_mn}</b>\n\n"
        f"<b>{article.get('title_mn', article['title_en'])}</b>\n\n"
        f"{article.get('summary_mn', '')}\n\n"
        f"💡 <i>{article.get('analysis_mn', '')}</i>\n\n"
        f"🔗 {article['link']}\n"
        f"<i>{article['source']}-аас</i>"
        f"{DISCLAIMER}"
    )
    return en, mn

def build_free_teaser(article):
    """Short teaser for free public channel — drives upgrades to premium."""
    emoji, _, label_mn = get_tag(article.get("is_breaking", False))
    teaser_text = article.get('summary_mn', '')[:120]

    return (
        f"{emoji} <b>{article.get('title_mn', article['title_en'])}</b>\n\n"
        f"{teaser_text}...\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔒 <b>Дэлгэрэнгүй шинжилгээ Premium сувгаас</b>\n\n"
        f"✅ Бүтэн мэдээ + хөрөнгө оруулалтын шинжилгээ\n"
        f"✅ Монгол хэл дээр AI тайлбар\n"
        f"✅ Өдөр бүрийн зах зээлийн мэдээлэл\n\n"
        f"➡️ <b>Нэгдэх: {PREMIUM_INVITE}</b>"
    )

def build_admin_preview(article):
    """Full preview for admin approval."""
    emoji, label_en, _ = get_tag(article.get("is_breaking", False))
    tag = "🚨 BREAKING" if article.get("is_breaking") else f"{emoji} {label_en}"

    return (
        f"<b>New article — {tag}</b>\n\n"
        f"🇬🇧 <b>{article['title_en']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🇲🇳 <b>{article.get('title_mn', '...')}</b>\n\n"
        f"{article.get('summary_mn', '')}\n\n"
        f"💡 {article.get('analysis_mn', '')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔗 {article['link']}\n"
        f"<i>via {article['source']}</i>"
    )

def build_edit_template(article):
    """Editable template for admin."""
    emoji, label_en, label_mn = get_tag(article.get("is_breaking", False))
    return (
        f"✏️ Edit and send back:\n\n"
        f"── ENGLISH (Premium) ──\n"
        f"{emoji} {label_en}\n\n"
        f"{article['title_en']}\n\n"
        f"🔗 {article['link']}\n"
        f"via {article['source']}\n\n"
        f"── MONGOLIAN (Premium) ──\n"
        f"{emoji} {label_mn}\n\n"
        f"{article.get('title_mn', '')}\n\n"
        f"{article.get('summary_mn', '')}\n\n"
        f"💡 {article.get('analysis_mn', '')}\n\n"
        f"🔗 {article['link']}\n"
        f"{article['source']}-аас"
        f"{DISCLAIMER}\n\n"
        f"── FREE TEASER ──\n"
        f"{emoji} {article.get('title_mn', article['title_en'])}\n\n"
        f"{article.get('summary_mn', '')[:120]}...\n\n"
        f"🔒 Дэлгэрэнгүй шинжилгээг Premium сувгаас үзнэ үү\n"
        f"➡️ MGL Newsroom Premium-д нэгдэх"
    )

# ── POST HELPERS ───────────────────────────────────────────────────────────────
def post_approved(article):
    """Post full post to premium + teaser to free channel."""
    en_post, mn_post = build_premium_post(article)
    teaser = build_free_teaser(article)

    # Premium channel — English then Mongolian
    send(PREMIUM_CHANNEL, en_post)
    time.sleep(2)
    send(PREMIUM_CHANNEL, mn_post)
    time.sleep(2)

    # Free channel — Mongolian teaser only
    send(FREE_CHANNEL, teaser)
    print(f"[POSTED] Premium + Free teaser")

def post_custom(custom_text):
    """Post admin-edited text to channels."""
    if "── MONGOLIAN (Premium) ──" in custom_text:
        parts = custom_text.split("──")
        en_part = ""
        mn_part = ""
        teaser_part = ""
        current = None
        for part in parts:
            p = part.strip()
            if "ENGLISH (Premium)" in p:
                current = "en"
            elif "MONGOLIAN (Premium)" in p:
                current = "mn"
            elif "FREE TEASER" in p:
                current = "teaser"
            elif current == "en" and p:
                en_part = p
            elif current == "mn" and p:
                mn_part = p
            elif current == "teaser" and p:
                teaser_part = p

        if en_part:
            send(PREMIUM_CHANNEL, en_part)
            time.sleep(2)
        if mn_part:
            send(PREMIUM_CHANNEL, mn_part)
            time.sleep(2)
        if teaser_part:
            send(FREE_CHANNEL, teaser_part)
    else:
        # Free-form — post to premium only
        send(PREMIUM_CHANNEL, custom_text)
    print(f"[POSTED CUSTOM]")

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
    msg_id = result.get("result", {}).get("message_id")
    if msg_id:
        pending[aid]["preview_msg_id"] = msg_id
        save_json(PENDING_FILE, pending)

# ── HANDLE UPDATES ─────────────────────────────────────────────────────────────
def handle_updates():
    sent       = load_json(SENT_FILE, {})
    pending    = load_json(PENDING_FILE, {})
    edit_state = load_json(EDIT_STATE_FILE, {})
    offset     = sent.get("_offset", 0)

    resp    = tg("getUpdates", {"offset": offset, "timeout": 5})
    updates = resp.get("result", [])

    for update in updates:
        offset = update["update_id"] + 1

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
                post_approved(art)
                answer_cb(cb["id"], "✅ Posted to both channels!")
                tg("editMessageText", {
                    "chat_id":    ADMIN_CHAT_ID,
                    "message_id": art.get("preview_msg_id"),
                    "text":       f"✅ Posted: <b>{art['title_en'][:80]}</b>",
                    "parse_mode": "HTML"
                })
                del pending[aid]
                save_json(PENDING_FILE, pending)

            elif action == "edit":
                result = send(ADMIN_CHAT_ID, build_edit_template(art))
                tmpl_msg_id = result.get("result", {}).get("message_id")
                edit_state["waiting"] = {
                    "aid":             aid,
                    "template_msg_id": tmpl_msg_id,
                    "preview_msg_id":  art.get("preview_msg_id"),
                }
                save_json(EDIT_STATE_FILE, edit_state)
                answer_cb(cb["id"], "✏️ Edit and send back!")

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

        msg = update.get("message")
        if msg and str(msg.get("chat", {}).get("id")) == str(ADMIN_CHAT_ID):
            text = msg.get("text", "").strip()
            waiting = edit_state.get("waiting")
            if not text or text.startswith("/"):
                continue
            if waiting:
                aid = waiting.get("aid")
                art = pending.get(aid)
                if art:
                    post_custom(text)
                    send(ADMIN_CHAT_ID, "✅ Your edited version has been posted!")
                    tg("editMessageText", {
                        "chat_id":    ADMIN_CHAT_ID,
                        "message_id": waiting.get("preview_msg_id"),
                        "text":       f"✅ Posted (edited): <b>{art['title_en'][:80]}</b>",
                        "parse_mode": "HTML"
                    })
                    del pending[aid]
                    save_json(PENDING_FILE, pending)
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
                raw_id = getattr(entry, "id", None) or entry.get("link", "")
                # Telegram callback_data max is 64 chars — use short hash as ID
                import hashlib
                aid = hashlib.md5(raw_id.encode()).hexdigest()[:16]
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

                print(f"[AI] Generating summary: {title[:60]}")
                ai_response = generate_mongolian_summary(title, summary, source_name)
                title_mn, summary_mn, analysis_mn = parse_ai_response(ai_response)

                if not title_mn:
                    title_mn    = title
                    summary_mn  = summary[:200] if summary else ""
                    analysis_mn = ""

                article = {
                    "id":          aid,
                    "title_en":    title,
                    "title_mn":    title_mn,
                    "summary_mn":  summary_mn,
                    "analysis_mn": analysis_mn,
                    "link":        link,
                    "source":      source_name,
                    "is_breaking": is_breaking,
                }

                queue_for_approval(article)
                sent_ids.add(aid)
                sent[aid] = True
                queued += 1
                time.sleep(2)

                if queued >= 4:
                    break

        except Exception as e:
            print(f"[FEED ERROR] {source_name}: {e}")

        if queued >= 4:
            break

    save_json(SENT_FILE, sent)
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] Queued {queued} articles")

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("MGL Newsroom Bot — Final Version")
    print(f"  Free channel    : {FREE_CHANNEL}")
    print(f"  Premium channel : {PREMIUM_CHANNEL}")
    print(f"  Admin           : {ADMIN_CHAT_ID}")
    print(f"  AI              : {'enabled' if ANTHROPIC_KEY else 'DISABLED'}")
    print("=" * 50)

    if not BOT_TOKEN:
        print("[FATAL] BOT_TOKEN missing!")
        return
    if not ADMIN_CHAT_ID:
        print("[FATAL] ADMIN_CHAT_ID missing!")
        return

    send(ADMIN_CHAT_ID,
        "🤖 <b>MGL Newsroom Bot — Final Version</b>\n\n"
        f"📢 Free channel: {FREE_CHANNEL}\n"
        f"💎 Premium channel: private (invite only)\n"
        f"🤖 AI summaries: {'✅ on' if ANTHROPIC_KEY else '❌ off — add ANTHROPIC_API_KEY'}\n\n"
        "<b>How it works:</b>\n"
        "✅ Agree → Full post to Premium + teaser to Free\n"
        "✏️ Edit → Edit text then send back\n"
        "❌ Skip → Discard article\n\n"
        "Checking news every 2 hours.")

    last_feed_check = 0  # force immediate check on startup

    while True:
        try:
            # Check button taps every 10 seconds
            handle_updates()

            # Check feeds every 2 hours
            now = time.time()
            if now - last_feed_check >= 7200:
                check_feeds()
                last_feed_check = now

        except Exception as e:
            print(f"[LOOP ERROR] {e}")

        time.sleep(10)

if __name__ == "__main__":
    main()
