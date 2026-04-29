"""
MGL Newsroom Bot — Full Version
================================
3 core features:
1. Morning Market Brief — auto posts to free channel daily at 8am UB time
2. Weekly structured posts — Mon-Fri different format, AI writes, you approve
3. Breaking alerts — high impact news sent to you instantly for fast approval

Flow:
  RSS/Price APIs → Claude writes English summary → Google Translate → Mongolian
  → Sent to admin for approval → Posted to Premium + teaser to Free
"""

import feedparser
import requests
import time
import json
import os
import hashlib
from datetime import datetime, timezone, timedelta

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BOT_TOKEN          = os.environ.get("BOT_TOKEN")
FREE_CHANNEL       = os.environ.get("FREE_CHANNEL",    "@mglnewsroomfree")
PREMIUM_CHANNEL    = os.environ.get("PREMIUM_CHANNEL", "-1003833538418")
ADMIN_CHAT_ID      = os.environ.get("ADMIN_CHAT_ID")
ANTHROPIC_KEY      = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_TRANSLATE   = os.environ.get("GOOGLE_TRANSLATE_KEY")
PREMIUM_INVITE     = "https://t.me/+BxQ8PEdcyc02YmM9"

# Ulaanbaatar is UTC+8
UB_OFFSET = timedelta(hours=8)

DISCLAIMER = "\n\n⚠️ Энэхүү мэдээлэл нь хөрөнгө оруулалтын зөвлөгөө биш."

# ── NEWS SOURCES ───────────────────────────────────────────────────────────────
RSS_FEEDS = [
    ("https://feeds.reuters.com/reuters/businessNews",            "Reuters Business"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NY Times Business"),
    ("https://techcrunch.com/feed/",                              "TechCrunch"),
    ("https://www.mining.com/feed/",                              "Mining.com"),
    ("https://www.investing.com/rss/news_301.rss",                "Investing.com"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/",           "CoinDesk"),
    ("https://feeds.feedburner.com/entrepreneur/latest",          "Entrepreneur"),
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

BREAKING_KEYWORDS = [
    "breaking", "urgent", "flash", "alert", "crash", "collapse",
    "emergency", "ban", "sanction", "plunge", "surge", "halted",
    "bankrupt", "crisis", "war", "attack", "default"
]

# ── WEEKLY SCHEDULE ────────────────────────────────────────────────────────────
SCHEDULE = {
    0: ("📊", "Weekly Market Outlook",       "7 хоногийн зах зээлийн тойм",
        "Focus on MSE stocks to watch this week, global market direction, and key events."),
    1: ("🌅", "Morning Snapshot",            "Өглөөний тойм",
        "Summarize the most important business/finance news of the day."),
    2: ("⛏️", "Mining & Commodities Update", "Уул уурхай ба түүхий эд",
        "Focus on coal, copper, gold prices and what it means for Mongolia's mining sector and MSE."),
    3: ("💡", "Finance & Crypto Insight",    "Санхүүгийн мэдээлэл",
        "Focus on crypto (Bitcoin/Ethereum) and personal finance insights for Mongolian investors."),
    4: ("📋", "Weekly Recap",                "7 хоногийн дүн",
        "Summarize the week's key financial events and what to watch next week."),
    5: ("🌅", "Weekend Snapshot",            "Амралтын өдрийн тойм",
        "Summarize weekend financial news and crypto movements."),
    6: ("🌅", "Weekend Snapshot",            "Амралтын өдрийн тойм",
        "Summarize weekend financial news and crypto movements."),
}

# ── FILES ──────────────────────────────────────────────────────────────────────
SENT_FILE        = "sent_articles.json"
PENDING_FILE     = "pending_articles.json"
EDIT_STATE_FILE  = "edit_state.json"
STATE_FILE       = "bot_state.json"

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

def now_ub():
    """Current time in Ulaanbaatar (UTC+8)."""
    return datetime.now(timezone.utc) + UB_OFFSET

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

# ── PRICE FETCHER — for morning brief ─────────────────────────────────────────
def fetch_prices():
    """Fetch live prices for morning brief."""
    prices = {
        "bitcoin": "N/A", "gold": "N/A",
        "usd_mnt": "N/A", "mse": "N/A"
    }
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum&vs_currencies=usd",
            timeout=10
        )
        data = r.json()
        prices["bitcoin"]  = f"${data['bitcoin']['usd']:,.0f}"
        prices["ethereum"] = f"${data['ethereum']['usd']:,.0f}"
    except Exception as e:
        print(f"[PRICE ERROR] Crypto: {e}")

    try:
        r = requests.get(
            "https://api.metals.live/v1/spot/gold",
            timeout=10
        )
        gold = r.json()
        if isinstance(gold, list) and gold:
            prices["gold"] = f"${gold[0].get('price', 'N/A'):,.0f}/oz"
        elif isinstance(gold, dict):
            prices["gold"] = f"${gold.get('price', 'N/A'):,.0f}/oz"
    except Exception as e:
        print(f"[PRICE ERROR] Gold: {e}")

    try:
        r = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=10
        )
        rates = r.json()
        mnt = rates.get("rates", {}).get("MNT", "N/A")
        if mnt != "N/A":
            prices["usd_mnt"] = f"₮{mnt:,.0f}"
    except Exception as e:
        print(f"[PRICE ERROR] USD/MNT: {e}")

    return prices

# ── GOOGLE TRANSLATE ───────────────────────────────────────────────────────────
def google_translate(text, target="mn"):
    """Translate text to Mongolian using Google Translate API."""
    if not GOOGLE_TRANSLATE:
        return None
    try:
        r = requests.post(
            "https://translation.googleapis.com/language/translate/v2",
            params={"key": GOOGLE_TRANSLATE},
            json={"q": text, "target": target, "format": "text"},
            timeout=10
        )
        result = r.json()
        if "error" in result:
            print(f"[GOOGLE TRANSLATE ERROR] {result['error']}")
            return None
        return result["data"]["translations"][0]["translatedText"]
    except Exception as e:
        print(f"[GOOGLE TRANSLATE ERROR] {e}")
        return None

# ── CLAUDE AI ──────────────────────────────────────────────────────────────────
def claude_summarize(title, summary, source, day_context):
    """Use Claude to write a clean structured English summary."""
    if not ANTHROPIC_KEY:
        return None

    prompt = f"""You are a financial news editor for an investment channel focused on Mongolia.

Article: {title}
Details: {summary[:500]}
Source: {source}
Today's focus: {day_context}

Write a structured response in this EXACT format:

HEADLINE: [A clear, punchy English headline under 15 words]

SUMMARY: [2-3 sentences explaining what happened and why it matters to investors. Clear, simple language. No jargon.]

MONGOLIA_IMPACT: [1-2 sentences on how this specifically affects Mongolian investors, MSE stocks, tugrug exchange rate, or Mongolian businesses. Be specific.]

Write ONLY the structured response. No extra text."""

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
                "max_tokens": 400,
                "messages":   [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        result = r.json()
        if "error" in result:
            print(f"[CLAUDE ERROR] {result['error']}")
            return None
        return result["content"][0]["text"].strip()
    except Exception as e:
        print(f"[CLAUDE ERROR] {e}")
        return None

def parse_claude_response(text):
    """Parse Claude's structured response."""
    headline = summary = impact = ""
    current = None
    for line in (text or "").strip().split("\n"):
        line = line.strip()
        if line.startswith("HEADLINE:"):
            headline = line.replace("HEADLINE:", "").strip()
            current = "headline"
        elif line.startswith("SUMMARY:"):
            summary = line.replace("SUMMARY:", "").strip()
            current = "summary"
        elif line.startswith("MONGOLIA_IMPACT:"):
            impact = line.replace("MONGOLIA_IMPACT:", "").strip()
            current = "impact"
        elif line and current == "summary":
            summary += " " + line
        elif line and current == "impact":
            impact += " " + line
    return headline.strip(), summary.strip(), impact.strip()

# ── FORMAT POSTS ───────────────────────────────────────────────────────────────
def get_tag(is_breaking=False):
    if is_breaking:
        return "🚨", "Breaking News", "Яаралтай мэдээ"
    day = now_ub().weekday()
    emoji, en, mn, _ = SCHEDULE.get(day, ("📰", "News", "Мэдээ", ""))
    return emoji, en, mn

def build_premium_post(article):
    """Full post for premium channel."""
    emoji, label_en, label_mn = get_tag(article.get("is_breaking", False))

    # English version
    en = (
        f"{emoji} <b>{label_en}</b>\n\n"
        f"<b>{article['headline_en']}</b>\n\n"
        f"{article['summary_en']}\n\n"
        f"💡 <i>{article['impact_en']}</i>\n\n"
        f"🔗 {article['link']}\n"
        f"<i>via {article['source']}</i>"
    )

    # Mongolian version
    mn = (
        f"{emoji} <b>{label_mn}</b>\n\n"
        f"<b>{article['headline_mn']}</b>\n\n"
        f"{article['summary_mn']}\n\n"
        f"💡 <i>{article['impact_mn']}</i>\n\n"
        f"🔗 {article['link']}\n"
        f"<i>{article['source']}-аас</i>"
        f"{DISCLAIMER}"
    )
    return en, mn

def build_free_teaser(article):
    """Short teaser for free channel with premium invite."""
    emoji, _, label_mn = get_tag(article.get("is_breaking", False))
    teaser = article.get("summary_mn", "")[:120]

    return (
        f"{emoji} <b>{article['headline_mn']}</b>\n\n"
        f"{teaser}...\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔒 <b>Дэлгэрэнгүй шинжилгээ Premium сувгаас</b>\n\n"
        f"✅ Бүтэн мэдээ + хөрөнгө оруулалтын шинжилгээ\n"
        f"✅ Монгол хэл дээр AI тайлбар\n"
        f"✅ Өдөр бүрийн зах зээлийн мэдээлэл\n\n"
        f"➡️ <b>Нэгдэх: {PREMIUM_INVITE}</b>"
    )

def build_admin_preview(article):
    """Preview for admin approval."""
    emoji, label_en, _ = get_tag(article.get("is_breaking", False))
    tag = "🚨 BREAKING — APPROVE FAST!" if article.get("is_breaking") else f"{emoji} {label_en}"

    return (
        f"<b>{tag}</b>\n\n"
        f"🇬🇧 <b>{article['headline_en']}</b>\n"
        f"{article['summary_en']}\n"
        f"💡 {article['impact_en']}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🇲🇳 <b>{article['headline_mn']}</b>\n"
        f"{article['summary_mn']}\n"
        f"💡 {article['impact_mn']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔗 {article['link']}\n"
        f"<i>via {article['source']}</i>"
    )

def build_edit_template(article):
    """Editable template for admin."""
    emoji, label_en, label_mn = get_tag(article.get("is_breaking", False))
    return (
        f"✏️ Edit and send back:\n\n"
        f"══ ENGLISH (Premium) ══\n"
        f"{emoji} {label_en}\n\n"
        f"{article['headline_en']}\n\n"
        f"{article['summary_en']}\n\n"
        f"💡 {article['impact_en']}\n\n"
        f"🔗 {article['link']}\n"
        f"via {article['source']}\n\n"
        f"══ MONGOLIAN (Premium) ══\n"
        f"{emoji} {label_mn}\n\n"
        f"{article['headline_mn']}\n\n"
        f"{article['summary_mn']}\n\n"
        f"💡 {article['impact_mn']}\n\n"
        f"🔗 {article['link']}\n"
        f"{article['source']}-аас"
        f"{DISCLAIMER}\n\n"
        f"══ FREE TEASER ══\n"
        f"{emoji} {article['headline_mn']}\n\n"
        f"{article['summary_mn'][:120]}...\n\n"
        f"🔒 Дэлгэрэнгүй шинжилгээ Premium сувгаас\n"
        f"➡️ Нэгдэх: {PREMIUM_INVITE}"
    )

# ── MORNING BRIEF ──────────────────────────────────────────────────────────────
def post_morning_brief():
    """Auto-post morning market brief to FREE channel — no approval needed."""
    print("[MORNING BRIEF] Fetching prices...")
    prices = fetch_prices()
    ub_now = now_ub()
    date_str = ub_now.strftime("%Y.%m.%d")

    # Arrow indicators (placeholder — can be enhanced with previous day comparison)
    post = (
        f"🌅 <b>Өглөөний зах зээлийн тойм</b>\n"
        f"<i>{date_str}</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"₿ Bitcoin:  <b>{prices['bitcoin']}</b>\n"
        f"🥇 Алт:     <b>{prices['gold']}</b>\n"
        f"💵 USD/MNT: <b>{prices['usd_mnt']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Дэлгэрэнгүй шинжилгээ болон МХБ-ийн мэдээг Premium сувгаас аваарай\n\n"
        f"➡️ <b>Нэгдэх: {PREMIUM_INVITE}</b>\n\n"
        f"{DISCLAIMER}"
    )

    send(FREE_CHANNEL, post)
    # Also send prices to premium channel
    premium_post = (
        f"🌅 <b>Morning Market Brief</b>\n"
        f"<i>{date_str} — Ulaanbaatar</i>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"₿ Bitcoin:  <b>{prices['bitcoin']}</b>\n"
        f"🥇 Gold:    <b>{prices['gold']}</b>\n"
        f"💵 USD/MNT: <b>{prices['usd_mnt']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<i>Full analysis and news coming throughout the day.</i>"
    )
    send(PREMIUM_CHANNEL, premium_post)
    print(f"[MORNING BRIEF] Posted to both channels")

    # Save last morning brief time
    state = load_json(STATE_FILE, {})
    state["last_morning_brief"] = ub_now.strftime("%Y-%m-%d")
    save_json(STATE_FILE, state)

def should_post_morning_brief():
    """Check if morning brief should be posted — 8am UB time, once per day."""
    ub_now = now_ub()
    state  = load_json(STATE_FILE, {})
    today  = ub_now.strftime("%Y-%m-%d")
    last   = state.get("last_morning_brief", "")

    # Post between 8:00 and 8:10 UB time, once per day
    is_morning = ub_now.hour == 8 and ub_now.minute < 10
    not_posted_today = last != today

    return is_morning and not_posted_today

# ── PROCESS ARTICLE ────────────────────────────────────────────────────────────
def process_article(title, summary, link, source, is_breaking):
    """Run article through Claude + Google Translate pipeline."""
    day = now_ub().weekday()
    _, _, _, day_context = SCHEDULE.get(day, ("", "", "", "Summarize key financial news."))

    # Step 1 — Claude writes clean English summary
    claude_raw = claude_summarize(title, summary, source, day_context)
    headline_en, summary_en, impact_en = parse_claude_response(claude_raw)

    # Fallback if Claude fails
    if not headline_en:
        headline_en = title
        summary_en  = summary[:200] if summary else "See full article for details."
        impact_en   = "Monitor for impact on Mongolian markets and MSE stocks."

    # Step 2 — Google Translate English → Mongolian
    headline_mn = google_translate(headline_en) or headline_en
    summary_mn  = google_translate(summary_en)  or summary_en
    impact_mn   = google_translate(impact_en)   or impact_en

    return {
        "headline_en": headline_en,
        "summary_en":  summary_en,
        "impact_en":   impact_en,
        "headline_mn": headline_mn,
        "summary_mn":  summary_mn,
        "impact_mn":   impact_mn,
    }

# ── POST TO CHANNELS ───────────────────────────────────────────────────────────
def post_approved(article):
    """Post full article to premium + teaser to free."""
    en_post, mn_post = build_premium_post(article)
    teaser = build_free_teaser(article)

    send(PREMIUM_CHANNEL, en_post)
    time.sleep(2)
    send(PREMIUM_CHANNEL, mn_post)
    time.sleep(2)
    send(FREE_CHANNEL, teaser)
    print(f"[POSTED] {article['headline_en'][:60]}")

def post_custom(text):
    """Post admin-edited text."""
    if "══ MONGOLIAN (Premium) ══" in text:
        parts = text.split("══")
        en_part = mn_part = teaser_part = ""
        current = None
        for p in parts:
            p = p.strip()
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
        send(PREMIUM_CHANNEL, text)
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
                post_approved(art)
                answer_cb(cb["id"], "✅ Posted to both channels!")
                tg("editMessageText", {
                    "chat_id":    ADMIN_CHAT_ID,
                    "message_id": art.get("preview_msg_id"),
                    "text":       f"✅ Posted: <b>{art['headline_en'][:80]}</b>",
                    "parse_mode": "HTML"
                })
                del pending[aid]
                save_json(PENDING_FILE, pending)

            elif action == "edit":
                result = send(ADMIN_CHAT_ID, build_edit_template(art))
                tmpl_id = result.get("result", {}).get("message_id")
                edit_state["waiting"] = {
                    "aid":            aid,
                    "template_msg_id": tmpl_id,
                    "preview_msg_id":  art.get("preview_msg_id"),
                }
                save_json(EDIT_STATE_FILE, edit_state)
                answer_cb(cb["id"], "✏️ Edit and send back!")

            elif action == "skip":
                answer_cb(cb["id"], "❌ Skipped.")
                tg("editMessageText", {
                    "chat_id":    ADMIN_CHAT_ID,
                    "message_id": art.get("preview_msg_id"),
                    "text":       f"❌ Skipped: {art['headline_en'][:80]}",
                    "parse_mode": "HTML"
                })
                del pending[aid]
                save_json(PENDING_FILE, pending)

        # Admin text reply (edited post)
        msg = update.get("message")
        if msg and str(msg.get("chat", {}).get("id")) == str(ADMIN_CHAT_ID):
            text    = msg.get("text", "").strip()
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
                        "text":       f"✅ Posted (edited): <b>{art['headline_en'][:80]}</b>",
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

def is_breaking(title):
    return any(w in title.lower() for w in BREAKING_KEYWORDS)

def check_feeds():
    sent     = load_json(SENT_FILE, {})
    sent_ids = set(k for k in sent if not k.startswith("_"))
    queued   = 0
    breaking_found = []
    normal_found   = []

    for feed_url, source_name in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                print(f"[EMPTY] {source_name}")
                continue

            for entry in feed.entries[:10]:
                raw_id = getattr(entry, "id", None) or entry.get("link", "")
                aid    = hashlib.md5(raw_id.encode()).hexdigest()[:16]

                if not aid or aid in sent_ids:
                    continue

                title   = entry.get("title", "").strip()
                summary = entry.get("summary", "")
                link    = entry.get("link", "")

                if not title or not link:
                    continue
                if not is_relevant(title, summary):
                    continue

                item = {
                    "aid":        aid,
                    "title":      title,
                    "summary":    summary,
                    "link":       link,
                    "source":     source_name,
                    "is_breaking": is_breaking(title),
                }

                if item["is_breaking"]:
                    breaking_found.append(item)
                else:
                    normal_found.append(item)

                sent_ids.add(aid)
                sent[aid] = True

        except Exception as e:
            print(f"[FEED ERROR] {source_name}: {e}")

    # Process breaking news FIRST — immediately
    for item in breaking_found[:2]:
        print(f"[BREAKING] {item['title'][:60]}")
        processed = process_article(
            item["title"], item["summary"],
            item["link"], item["source"], True
        )
        article = {
            "id":         item["aid"],
            "link":       item["link"],
            "source":     item["source"],
            "is_breaking": True,
            **processed
        }
        queue_for_approval(article)
        queued += 1
        time.sleep(2)

    # Process normal news — max 3 per cycle
    for item in normal_found[:3]:
        print(f"[AI] Processing: {item['title'][:60]}")
        processed = process_article(
            item["title"], item["summary"],
            item["link"], item["source"], False
        )
        article = {
            "id":         item["aid"],
            "link":       item["link"],
            "source":     item["source"],
            "is_breaking": False,
            **processed
        }
        queue_for_approval(article)
        queued += 1
        time.sleep(2)

    save_json(SENT_FILE, sent)
    ub_now = now_ub()
    print(f"[{ub_now.strftime('%H:%M UB')}] Queued {queued} articles "
          f"({len(breaking_found)} breaking, {len(normal_found)} normal)")

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("MGL Newsroom Bot — Full Version")
    print(f"  Free channel    : {FREE_CHANNEL}")
    print(f"  Premium channel : {PREMIUM_CHANNEL}")
    print(f"  Admin           : {ADMIN_CHAT_ID}")
    print(f"  Claude AI       : {'✅' if ANTHROPIC_KEY    else '❌ missing ANTHROPIC_API_KEY'}")
    print(f"  Google Translate: {'✅' if GOOGLE_TRANSLATE else '❌ missing GOOGLE_TRANSLATE_KEY'}")
    print("=" * 55)

    if not BOT_TOKEN:
        print("[FATAL] BOT_TOKEN missing!")
        return
    if not ADMIN_CHAT_ID:
        print("[FATAL] ADMIN_CHAT_ID missing!")
        return

    send(ADMIN_CHAT_ID,
        "🤖 <b>MGL Newsroom Bot — Full Version</b>\n\n"
        f"📢 Free: {FREE_CHANNEL}\n"
        f"💎 Premium: private channel\n"
        f"🤖 Claude AI: {'✅' if ANTHROPIC_KEY    else '❌ add ANTHROPIC_API_KEY'}\n"
        f"🌐 Google Translate: {'✅' if GOOGLE_TRANSLATE else '❌ add GOOGLE_TRANSLATE_KEY'}\n\n"
        "<b>Features:</b>\n"
        "🌅 Morning brief auto-posts at 8am UB time\n"
        "📰 News checked every 2 hours\n"
        "🚨 Breaking news sent to you instantly\n"
        "✅ Agree / ✏️ Edit / ❌ Skip buttons\n\n"
        "Bot is running!")

    last_feed_check = 0

    while True:
        try:
            # 1. Always check button taps — every 10 seconds
            handle_updates()

            # 2. Morning brief at 8am UB time — auto, no approval
            if should_post_morning_brief():
                post_morning_brief()

            # 3. Check feeds every 2 hours
            now = time.time()
            if now - last_feed_check >= 7200:
                check_feeds()
                last_feed_check = now

        except Exception as e:
            print(f"[LOOP ERROR] {e}")

        time.sleep(10)

if __name__ == "__main__":
    main()