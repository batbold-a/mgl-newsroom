import feedparser
import requests
import time
import json
import os
from datetime import datetime, timezone

# ── CONFIG ─────────────────────────────────────────────────────────────────────
BOT_TOKEN          = os.environ.get("BOT_TOKEN")
PAID_CHANNEL       = os.environ.get("PAID_CHANNEL", "@mgl_newsroom")
FREE_CHANNEL       = os.environ.get("FREE_CHANNEL", "@mgl_newsroom_free")
ADMIN_CHAT_ID      = os.environ.get("ADMIN_CHAT_ID")
TRANSLATE_API_KEY  = os.environ.get("TRANSLATE_API_KEY")

DISCLAIMER = "\n\n⚠️ Энэхүү мэдээлэл нь хөрөнгө оруулалтын зөвлөгөө биш."

# ── NEWS SOURCES ───────────────────────────────────────────────────────────────
# Mongolian sources
MN_FEEDS = [
    "https://montsame.mn/rss",                          # Mongolia national news agency
    "https://news.mn/rss",                              # News.mn
    "https://ikon.mn/rss",                              # Ikon.mn business
]

# Global business + finance sources
GLOBAL_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",   # Reuters business
    "https://feeds.reuters.com/reuters/companyNews",    # Reuters markets
    "https://feeds.bloomberg.com/markets/news.rss",     # Bloomberg markets
    "https://techcrunch.com/feed/",                     # TechCrunch
    "https://www.mining.com/feed/",                     # Mining.com — key for Mongolia
]

# Keywords that matter for Mongolian investors
MN_KEYWORDS = [
    # Mongolian terms
    "MSE", "МХБ", "хувьцаа", "бонд", "хөрөнгө оруулалт", "банк",
    "нүүрс", "зэс", "алт", "Оюу Толгой", "Тавантолгой",
    "инфляц", "ханш", "төгрөг", "ДНБ",
    # English terms relevant to Mongolia
    "Oyu Tolgoi", "Tavan Tolgoi", "coal", "copper", "Mongolia",
    "MSE", "Mongolian", "tugrik", "MNT",
]

GLOBAL_KEYWORDS = [
    # Markets
    "market", "stock", "S&P", "NASDAQ", "rally", "crash", "Fed",
    "interest rate", "inflation", "recession", "GDP",
    # Commodities (affect Mongolia directly)
    "coal", "copper", "gold", "oil", "commodity",
    # Tech & business
    "AI", "startup", "IPO", "acquisition", "earnings", "revenue",
    "Apple", "Google", "Microsoft", "Amazon", "Tesla",
    # Crypto
    "Bitcoin", "crypto", "blockchain",
]

# ── FILE HELPERS ───────────────────────────────────────────────────────────────
SENT_FILE    = "sent_articles.json"
PENDING_FILE = "pending_articles.json"

def load_json(f, default):
    try:
        if os.path.exists(f):
            with open(f) as fp:
                return json.load(fp)
    except Exception:
        pass
    return default

def save_json(f, data):
    with open(f, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)

# ── TELEGRAM HELPERS ───────────────────────────────────────────────────────────
def tg(method, payload):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload, timeout=15
        )
        return r.json()
    except Exception as e:
        print(f"[TG ERROR] {method}: {e}")
        return {}

def send(chat_id, text, markup=None):
    payload = {"chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": False}
    if markup:
        payload["reply_markup"] = json.dumps(markup)
    tg("sendMessage", payload)

def answer_cb(cb_id, text):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

# ── TRANSLATION ────────────────────────────────────────────────────────────────
def translate(text, target="mn"):
    if not TRANSLATE_API_KEY:
        return None
    try:
        r = requests.post(
            "https://translation.googleapis.com/language/translate/v2",
            params={"key": TRANSLATE_API_KEY},
            json={"q": text, "target": target, "format": "text"},
            timeout=10
        )
        return r.json()["data"]["translations"][0]["translatedText"]
    except Exception as e:
        print(f"[TRANSLATE ERROR] {e}")
        return None

# ── RELEVANCE CHECK ────────────────────────────────────────────────────────────
def is_relevant(title, summary, keywords):
    text = (title + " " + summary).lower()
    return any(k.lower() in text for k in keywords)

# ── CONTENT SCHEDULE ───────────────────────────────────────────────────────────
def get_schedule_label():
    """Return what type of post to send based on day of week."""
    day = datetime.now(timezone.utc).weekday()  # 0=Mon, 4=Fri, 6=Sun
    return {
        0: "weekly_outlook",   # Monday
        1: "daily_snapshot",   # Tuesday
        2: "mining_update",    # Wednesday
        3: "finance_tip",      # Thursday
        4: "weekly_recap",     # Friday
        5: "daily_snapshot",   # Saturday
        6: "daily_snapshot",   # Sunday
    }.get(day, "daily_snapshot")

def format_paid_post(article, schedule_label, is_mongolian=False):
    """Format a rich paid-channel post based on the schedule."""
    tag = {
        "weekly_outlook":  "📊 7 хоногийн тойм" if is_mongolian else "📊 Weekly outlook",
        "daily_snapshot":  "🌅 Өглөөний тойм"  if is_mongolian else "🌅 Morning snapshot",
        "mining_update":   "⛏️ Уул уурхай"      if is_mongolian else "⛏️ Mining & commodities",
        "finance_tip":     "💡 Санхүүгийн зөвлөгөө" if is_mongolian else "💡 Finance insight",
        "weekly_recap":    "📋 7 хоногийн дүн"  if is_mongolian else "📋 Weekly recap",
        "breaking":        "🚨 Яаралтай мэдээ"  if is_mongolian else "🚨 Breaking news",
    }.get(schedule_label, "📰 Мэдээ" if is_mongolian else "📰 News")

    title   = article["title_mn"] if is_mongolian else article["title_en"]
    source  = article["source"]
    link    = article["link"]
    via     = f"{source}-аас" if is_mongolian else f"via {source}"

    post = f"{tag}\n\n<b>{title}</b>\n\n🔗 {link}\n<i>{via}</i>"
    if is_mongolian:
        post += DISCLAIMER
    return post

def format_free_teaser(article, is_mongolian=False):
    """Short teaser for the free channel that drives upgrades."""
    title = article["title_mn"] if is_mongolian else article["title_en"]
    if is_mongolian:
        return (
            f"📰 <b>{title}</b>\n\n"
            f"🔒 Дэлгэрэнгүй шинжилгээг төлбөртэй суваг дээр үзнэ үү.\n"
            f"➡️ @mgl_newsroom-д нэгдэж, хөрөнгө оруулалтын мэдээг тэргүүлж аваарай."
        )
    return (
        f"📰 <b>{title}</b>\n\n"
        f"🔒 Full analysis in the paid channel.\n"
        f"➡️ Join @mgl_newsroom for full investor insights."
    )

# ── APPROVAL SYSTEM ────────────────────────────────────────────────────────────
def queue_for_approval(article_id, title_en, title_mn, link, source, schedule_label, is_breaking=False):
    pending = load_json(PENDING_FILE, {})
    pending[article_id] = {
        "title_en":      title_en,
        "title_mn":      title_mn or title_en,
        "link":          link,
        "source":        source,
        "schedule":      schedule_label,
        "is_breaking":   is_breaking,
        "queued_at":     datetime.now(timezone.utc).isoformat(),
    }
    save_json(PENDING_FILE, pending)

    label_display = "🚨 BREAKING" if is_breaking else f"📅 {schedule_label.replace('_',' ').title()}"
    preview = (
        f"<b>{label_display}</b>\n\n"
        f"🇬🇧 {title_en}\n\n"
        f"🇲🇳 {title_mn or '(translation pending)'}\n\n"
        f"🔗 {link}\n"
        f"<i>via {source}</i>"
    )
    markup = {"inline_keyboard": [[
        {"text": "✅ Approve both",   "callback_data": f"approve:{article_id}"},
        {"text": "🇬🇧 EN only",       "callback_data": f"en_only:{article_id}"},
        {"text": "🇲🇳 MN only",       "callback_data": f"mn_only:{article_id}"},
        {"text": "❌ Skip",           "callback_data": f"skip:{article_id}"},
    ]]}
    send(ADMIN_CHAT_ID, f"New article for review:\n\n{preview}", markup=markup)

def post_article(article, channels):
    """Post approved article to specified channels."""
    schedule = article.get("schedule", "daily_snapshot")
    is_breaking = article.get("is_breaking", False)
    if is_breaking:
        schedule = "breaking"

    for ch in channels:
        is_mn = (ch == FREE_CHANNEL)
        # paid channel gets full post, free channel gets teaser
        if ch == PAID_CHANNEL:
            # post in English
            send(ch, format_paid_post(article, schedule, is_mongolian=False))
            time.sleep(2)
        elif ch == FREE_CHANNEL:
            # post Mongolian teaser on free channel
            send(ch, format_free_teaser(article, is_mongolian=True))
            time.sleep(2)

    # Also post Mongolian version to paid channel
    if PAID_CHANNEL in channels and article.get("title_mn"):
        time.sleep(2)
        send(PAID_CHANNEL, format_paid_post(article, schedule, is_mongolian=True))

# ── CALLBACK HANDLER ───────────────────────────────────────────────────────────
def handle_callbacks():
    sent    = load_json(SENT_FILE, {})
    pending = load_json(PENDING_FILE, {})
    offset  = sent.get("_offset", 0)

    resp    = tg("getUpdates", {"offset": offset, "timeout": 5})
    updates = resp.get("result", [])

    for update in updates:
        offset = update["update_id"] + 1
        cb = update.get("callback_query")
        if not cb:
            continue

        data = cb.get("data", "")
        if ":" not in data:
            continue
        action, article_id = data.split(":", 1)

        if article_id not in pending:
            answer_cb(cb["id"], "Already handled.")
            continue

        art = pending[article_id]

        if action == "approve":
            post_article(art, [PAID_CHANNEL, FREE_CHANNEL])
            answer_cb(cb["id"], "Posted to both channels!")
        elif action == "en_only":
            post_article(art, [PAID_CHANNEL])
            answer_cb(cb["id"], "Posted English only.")
        elif action == "mn_only":
            # post Mongolian to paid + free
            send(PAID_CHANNEL, format_paid_post(art, art.get("schedule","daily_snapshot"), is_mongolian=True))
            send(FREE_CHANNEL, format_free_teaser(art, is_mongolian=True))
            answer_cb(cb["id"], "Posted Mongolian only.")
        elif action == "skip":
            answer_cb(cb["id"], "Skipped.")

        del pending[article_id]
        save_json(PENDING_FILE, pending)

    if updates:
        sent["_offset"] = offset
        save_json(SENT_FILE, sent)

# ── FEED CHECKER ───────────────────────────────────────────────────────────────
def check_feeds():
    sent     = load_json(SENT_FILE, {})
    sent_ids = set(k for k in sent if not k.startswith("_"))
    schedule = get_schedule_label()
    new_count = 0

    all_feeds = [
        (url, True,  MN_KEYWORDS)     for url in MN_FEEDS
    ] + [
        (url, False, GLOBAL_KEYWORDS) for url in GLOBAL_FEEDS
    ]

    for feed_url, is_mn_source, keywords in all_feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                article_id = getattr(entry, "id", entry.get("link", ""))
                if not article_id or article_id in sent_ids:
                    continue

                title_en   = entry.get("title", "").strip()
                summary    = entry.get("summary", "")
                link       = entry.get("link", "")
                source     = feed.feed.get("title", "News")

                if not is_relevant(title_en, summary, keywords):
                    continue

                # Translate to Mongolian
                title_mn = translate(title_en) if not is_mn_source else title_en
                if not title_mn:
                    title_mn = title_en + " (орчуулга хийгдсэнгүй)"

                # Detect breaking news by keywords
                is_breaking = any(w in title_en.lower() for w in [
                    "breaking", "urgent", "flash", "alert", "crash",
                    "collapse", "emergency", "ban", "sanction"
                ])

                queue_for_approval(
                    article_id, title_en, title_mn,
                    link, source, schedule, is_breaking
                )

                sent_ids.add(article_id)
                sent[article_id] = True
                new_count += 1
                time.sleep(2)

                if new_count >= 5:   # max 5 queued per cycle
                    break
            if new_count >= 5:
                break
        except Exception as e:
            print(f"[FEED ERROR] {feed_url}: {e}")

    save_json(SENT_FILE, sent)
    print(f"[{datetime.now().strftime('%H:%M')}] Queued {new_count} articles for approval | Schedule: {schedule}")

# ── MAIN LOOP ──────────────────────────────────────────────────────────────────
def main():
    print("MGL Newsroom Bot started.")
    send(ADMIN_CHAT_ID,
         "🤖 <b>MGL Newsroom Bot started!</b>\n\n"
         "I will send articles here for your approval before posting.\n"
         "Tap ✅ Approve, 🇬🇧/🇲🇳 for single language, or ❌ Skip.")

    while True:
        handle_callbacks()
        check_feeds()
        time.sleep(7200)   # check every 2 hours

if __name__ == "__main__":
    main()