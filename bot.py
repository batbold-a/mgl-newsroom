import feedparser
import requests
import time
import json
import os
from datetime import datetime, timezone

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN")
PAID_CHANNEL   = os.environ.get("PAID_CHANNEL", "@mgl_newsroom")
ADMIN_CHAT_ID  = os.environ.get("ADMIN_CHAT_ID")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY")

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

# ── CLAUDE AI — Mongolian summary + analysis ───────────────────────────────────
def generate_mongolian_summary(title, summary, source):
    """Call Claude API to write a proper Mongolian summary with investor analysis."""
    if not ANTHROPIC_KEY:
        return title + " (AI тайлбар байхгүй — ANTHROPIC_API_KEY тохируулаагүй)"

    prompt = f"""You are a financial news editor for a Mongolian investment channel.

Article title: {title}
Article summary: {summary}
Source: {source}

Write a response in this EXACT format in Mongolian:

TITLE: [Translate the title naturally into Mongolian — not word for word, make it sound like a real Mongolian news headline]

SUMMARY: [Write 2-3 sentences in Mongolian explaining what happened and why it matters. Use simple, clear Mongolian that anyone can understand. No jargon.]

ANALYSIS: [Write 1-2 sentences explaining what this means specifically for Mongolian investors — how does this affect MSE stocks, the tugrug, commodity prices, or Mongolian businesses?]

Write ONLY the Mongolian content. No English. No explanations."""

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
        return result["content"][0]["text"].strip()
    except Exception as e:
        print(f"[CLAUDE ERROR] {e}")
        return title + " (AI тайлбар алдаа гарлаа)"

def parse_ai_response(ai_text):
    """Parse Claude's structured response into title, summary, analysis."""
    lines = ai_text.strip().split("\n")
    title_mn   = ""
    summary_mn = ""
    analysis_mn = ""

    current = None
    for line in lines:
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

# ── FORMAT ─────────────────────────────────────────────────────────────────────
def get_schedule_tag(is_breaking=False):
    if is_breaking:
        return "🚨", "Breaking News", "Яаралтай мэдээ"
    day = datetime.now(timezone.utc).weekday()
    return SCHEDULE.get(day, ("📰", "News", "Мэдээ"))

def build_channel_post(article):
    """Build the final English + Mongolian post for the channel."""
    emoji, label_en, label_mn = get_schedule_tag(article.get("is_breaking", False))

    # English post — clean headline + link
    en_post = (
        f"{emoji} <b>{label_en}</b>\n\n"
        f"<b>{article['title_en']}</b>\n\n"
        f"🔗 {article['link']}\n"
        f"<i>via {article['source']}</i>"
    )

    # Mongolian post — AI title + summary + analysis
    mn_parts = [f"{emoji} <b>{label_mn}</b>\n\n"]

    if article.get("title_mn"):
        mn_parts.append(f"<b>{article['title_mn']}</b>\n\n")
    if article.get("summary_mn"):
        mn_parts.append(f"{article['summary_mn']}\n\n")
    if article.get("analysis_mn"):
        mn_parts.append(f"💡 <i>{article['analysis_mn']}</i>\n\n")

    mn_parts.append(f"🔗 {article['link']}\n")
    mn_parts.append(f"<i>{article['source']}-аас</i>")
    mn_parts.append(DISCLAIMER)

    mn_post = "".join(mn_parts)
    return en_post, mn_post

def build_admin_preview(article):
    """Full preview card for admin — shows AI-generated content."""
    emoji, label_en, _ = get_schedule_tag(article.get("is_breaking", False))
    tag = "🚨 BREAKING" if article.get("is_breaking") else f"{emoji} {label_en}"

    preview = (
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
    return preview

def build_edit_template(article):
    """Editable template sent to admin when they tap Edit."""
    emoji, label_en, label_mn = get_schedule_tag(article.get("is_breaking", False))
    return (
        f"✏️ Copy, edit and send back:\n\n"
        f"── ENGLISH ──\n"
        f"{emoji} {label_en}\n\n"
        f"{article['title_en']}\n\n"
        f"🔗 {article['link']}\n"
        f"via {article['source']}\n\n"
        f"── MONGOLIAN ──\n"
        f"{emoji} {label_mn}\n\n"
        f"{article.get('title_mn', '')}\n\n"
        f"{article.get('summary_mn', '')}\n\n"
        f"💡 {article.get('analysis_mn', '')}\n\n"
        f"🔗 {article['link']}\n"
        f"{article['source']}-аас"
        f"{DISCLAIMER}"
    )

# ── POST TO CHANNEL ────────────────────────────────────────────────────────────
def post_to_channel(en_text, mn_text):
    send(PAID_CHANNEL, en_text)
    time.sleep(2)
    send(PAID_CHANNEL, mn_text)
    print(f"[POSTED] {PAID_CHANNEL}")

def post_custom_to_channel(custom_text):
    """Post admin-edited text — splits on ── MONGOLIAN ── if present."""
    if "── MONGOLIAN ──" in custom_text:
        parts = custom_text.split("── MONGOLIAN ──")
        en_part = parts[0].replace("── ENGLISH ──", "").strip()
        mn_part = parts[1].strip() if len(parts) > 1 else ""
        if en_part:
            send(PAID_CHANNEL, en_part)
            time.sleep(2)
        if mn_part:
            send(PAID_CHANNEL, mn_part)
    else:
        send(PAID_CHANNEL, custom_text)
    print(f"[POSTED CUSTOM] {PAID_CHANNEL}")

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

        # Button taps
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
                en_post, mn_post = build_channel_post(art)
                post_to_channel(en_post, mn_post)
                answer_cb(cb["id"], "✅ Posted!")
                tg("editMessageText", {
                    "chat_id":    ADMIN_CHAT_ID,
                    "message_id": art.get("preview_msg_id"),
                    "text":       f"✅ Posted: <b>{art['title_en'][:80]}</b>",
                    "parse_mode": "HTML"
                })
                del pending[aid]
                save_json(PENDING_FILE, pending)

            elif action == "edit":
                template = build_edit_template(art)
                result = send(ADMIN_CHAT_ID, template)
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

        # Admin text reply (edited post)
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
                    post_custom_to_channel(text)
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

                # Generate AI Mongolian summary
                print(f"[AI] Generating Mongolian summary for: {title[:60]}")
                ai_response  = generate_mongolian_summary(title, summary, source_name)
                title_mn, summary_mn, analysis_mn = parse_ai_response(ai_response)

                # Fallback if parsing failed
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
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    print(f"[{now}] Queued {queued} articles with AI summaries")

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("MGL Newsroom Bot (AI Edition) starting...")
    print(f"  Channel : {PAID_CHANNEL}")
    print(f"  Admin   : {ADMIN_CHAT_ID}")
    print(f"  AI      : {'enabled' if ANTHROPIC_KEY else 'DISABLED - add ANTHROPIC_API_KEY'}")
    print("=" * 50)

    if not BOT_TOKEN:
        print("[FATAL] BOT_TOKEN missing!")
        return
    if not ADMIN_CHAT_ID:
        print("[FATAL] ADMIN_CHAT_ID missing!")
        return

    send(ADMIN_CHAT_ID,
        "🤖 <b>MGL Newsroom Bot (AI Edition) is running!</b>\n\n"
        f"AI summaries: {'✅ enabled' if ANTHROPIC_KEY else '❌ disabled — add ANTHROPIC_API_KEY in Railway'}\n\n"
        "Each article will include:\n"
        "🇬🇧 English headline\n"
        "🇲🇳 AI-written Mongolian title\n"
        "📝 Mongolian summary\n"
        "💡 Investor analysis for Mongolia\n\n"
        "Buttons: ✅ Agree  ✏️ Edit  ❌ Skip\n\n"
        f"Posting to: {PAID_CHANNEL}")

    while True:
        try:
            handle_updates()
            check_feeds()
        except Exception as e:
            print(f"[LOOP ERROR] {e}")
        time.sleep(7200)

if __name__ == "__main__":
    main()