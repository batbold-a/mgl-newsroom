"""
MGL Newsroom Bot — Refined Version
====================================
Active hours: 8am–10pm Ulaanbaatar time (UTC+8)
News checks: 8am, 11am, 2pm, 5pm, 8pm
Morning brief: auto-posts at 8am (no approval)
Breaking alerts: instant any time during active hours
Duplicate fix: MD5 hash + URL dedup
Mongolian sources: montsame.mn, news.mn, mse.mn
Trading style: recommendations not signals
"""

import feedparser
import requests
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
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_TRANSLATE = os.environ.get("GOOGLE_TRANSLATE_KEY")
PREMIUM_INVITE   = "https://t.me/+BxQ8PEdcyc02YmM9"

UB_OFFSET  = timedelta(hours=8)
DISCLAIMER = "\n\n⚠️ Энэхүү мэдээлэл нь хөрөнгө оруулалтын зөвлөгөө биш."

# Active hours: 8am to 10pm UB time
ACTIVE_HOUR_START = 8
ACTIVE_HOUR_END   = 22

# News check times (UB hours)
CHECK_HOURS = {8, 11, 14, 17, 20}

# ── NEWS SOURCES ───────────────────────────────────────────────────────────────
# Mongolian sources
MN_FEEDS = [
    ("https://montsame.mn/rss",   "Монцамэ"),       # National news agency
    ("https://news.mn/rss",       "News.mn"),        # Business news
    ("https://ikon.mn/rss",       "Ikon.mn"),        # Finance news
]

# Global sources
GLOBAL_FEEDS = [
    ("https://feeds.reuters.com/reuters/businessNews",            "Reuters"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NY Times"),
    ("https://www.mining.com/feed/",                              "Mining.com"),
    ("https://www.coindesk.com/arc/outboundfeeds/rss/",           "CoinDesk"),
    ("https://feeds.reuters.com/reuters/companyNews",             "Reuters Markets"),
    ("https://techcrunch.com/feed/",                              "TechCrunch"),
]

ALL_FEEDS = MN_FEEDS + GLOBAL_FEEDS

# STRICT financial keywords — article must contain at least one
KEYWORDS = [
    # Markets
    "market", "stock", "stocks", "S&P", "nasdaq", "rally", "crash",
    "fed", "federal reserve", "interest rate", "inflation", "recession", "GDP",
    # Commodities — critical for Mongolia
    "coal", "copper", "gold", "silver", "oil", "commodity", "mineral",
    "mining revenue", "mining export", "оюу толгой", "тавантолгой",
    "oyu tolgoi", "tavan tolgoi",
    # Mongolian financial terms
    "мхб", "хувьцаа", "бонд", "хөрөнгө оруулалт", "банк",
    "инфляц", "ханш", "төгрөг", "эдийн засаг", "экспорт",
    "борлуулалт", "ашиг", "алдагдал", "санхүү",
    # English financial terms
    "IPO", "earnings", "revenue", "profit", "quarterly results",
    "investment", "investor", "fund", "bond", "yield", "dividend",
    "bankruptcy", "acquisition", "merger",
    # Crypto
    "bitcoin", "crypto", "ethereum", "blockchain",
    # Big tech only when market-moving
    "apple earnings", "google revenue", "microsoft profit",
    "nvidia earnings", "tesla earnings",
]

# Hard reject — never post these regardless of keywords
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

# ── WEEKLY SCHEDULE ────────────────────────────────────────────────────────────
SCHEDULE = {
    0: ("📊", "Weekly Market Outlook",       "7 хоногийн зах зээлийн тойм",
        "Focus on MSE stocks to watch this week and global market direction."),
    1: ("🌅", "Morning Snapshot",            "Өглөөний тойм",
        "Summarize the most important business and finance news today."),
    2: ("⛏️", "Mining & Commodities",        "Уул уурхай ба түүхий эд",
        "Focus on coal, copper, gold prices and impact on Mongolia's mining sector and MSE stocks."),
    3: ("💡", "Crypto & Finance Insight",    "Крипто ба санхүүгийн мэдээлэл",
        "Focus on Bitcoin, Ethereum movements and personal finance insights for Mongolian investors."),
    4: ("📋", "Weekly Recap & Outlook",      "7 хоногийн дүн",
        "Summarize the week's key events and what Mongolian investors should watch next week."),
    5: ("🌅", "Weekend Snapshot",            "Амралтын өдрийн тойм",
        "Weekend financial news and crypto market movements."),
    6: ("🌅", "Weekend Snapshot",            "Амралтын өдрийн тойм",
        "Weekend financial news and crypto market movements."),
}

# ── FILES ──────────────────────────────────────────────────────────────────────
SENT_FILE       = "sent_articles.json"
PENDING_FILE    = "pending_articles.json"
EDIT_STATE_FILE = "edit_state.json"
STATE_FILE      = "bot_state.json"

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
    """Short unique ID from URL — fixes duplicate posting."""
    return hashlib.md5(url.encode()).hexdigest()[:16]

def is_active_hours():
    """Only operate during configured hours — reads from state file."""
    state   = load_json(STATE_FILE, {})
    if state.get("paused", False):
        return False
    h_start = state.get("hour_start", ACTIVE_HOUR_START)
    h_end   = state.get("hour_end",   ACTIVE_HOUR_END)
    h       = now_ub().hour
    return h_start <= h < h_end

def should_check_feeds():
    """Check feeds at 8, 11, 14, 17, 20 UB time."""
    ub   = now_ub()
    state = load_json(STATE_FILE, {})
    key  = f"feed_check_{ub.strftime('%Y-%m-%d_%H')}"
    if ub.hour in CHECK_HOURS and not state.get(key):
        state[key] = True
        # Clean old keys — keep only today's
        today = ub.strftime("%Y-%m-%d")
        state = {k: v for k, v in state.items()
                 if today in k or not k.startswith("feed_check_")}
        save_json(STATE_FILE, state)
        return True
    return False

def should_post_morning_brief():
    """Post morning brief once at 8am UB time."""
    ub    = now_ub()
    state = load_json(STATE_FILE, {})
    today = ub.strftime("%Y-%m-%d")
    key   = f"morning_brief_{today}"
    if ub.hour == 8 and ub.minute < 10 and not state.get(key):
        state[key] = True
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

# ── PRICE FETCHER ──────────────────────────────────────────────────────────────
def fetch_mse_top10():
    """Fetch top 10 MSE stocks by volume from stock.bbe.mn."""
    try:
        from html.parser import HTMLParser
        r = requests.get("https://stock.bbe.mn/", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        stocks = []
        lines = r.text.split("\n")
        for line in lines:
            if "/Home/Stock/" in line and "<td>" in line:
                continue
        # Parse table rows
        import re
        rows = re.findall(
            r"Home/Stock/([A-Z]+).*?>([\d,\.]+)</td>.*?>([\d,\.]+)</td>.*?([-\d,\.]+)</td>.*?([-\d\.]+%)</td>",
            r.text, re.DOTALL
        )
        for row in rows[:10]:
            symbol, prev, curr, change, pct = row
            arrow = "▲" if not change.startswith("-") else "▼"
            stocks.append({
                "symbol": symbol,
                "price":  curr.strip(),
                "change": change.strip(),
                "pct":    pct.strip(),
                "arrow":  arrow,
            })
        return stocks[:10]
    except Exception as e:
        print(f"[MSE ERROR] {e}")
        return []

def fetch_global_stocks():
    """Fetch major global stock indices and prices."""
    stocks = {}
    try:
        # Yahoo Finance compatible API
        symbols = {
            "S&P 500": "^GSPC",
            "NASDAQ":  "^IXIC",
            "Apple":   "AAPL",
            "Nvidia":  "NVDA",
        }
        for name, sym in symbols.items():
            try:
                r = requests.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                    "?interval=1d&range=2d",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10
                )
                d = r.json()
                meta  = d["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice", 0)
                prev  = meta.get("chartPreviousClose", price)
                chg   = price - prev
                pct   = (chg / prev * 100) if prev else 0
                arrow = "▲" if chg >= 0 else "▼"
                stocks[name] = {
                    "price": f"{price:,.2f}",
                    "pct":   f"{abs(pct):.2f}%",
                    "arrow": arrow,
                }
            except Exception:
                pass
    except Exception as e:
        print(f"[GLOBAL STOCKS ERROR] {e}")
    return stocks

def fetch_assets():
    """Fetch 10 key assets: crypto + metals + forex."""
    assets = {}

    # Crypto — Bitcoin, Ethereum, BNB, XRP, SOL
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,binancecoin,ripple,solana"
            "&vs_currencies=usd&include_24hr_change=true",
            timeout=10
        )
        d = r.json()
        mapping = {
            "bitcoin":     "Bitcoin",
            "ethereum":    "Ethereum",
            "binancecoin": "BNB",
            "ripple":      "XRP",
            "solana":      "Solana",
        }
        for key, name in mapping.items():
            if key in d:
                price = d[key]["usd"]
                chg   = d[key].get("usd_24h_change", 0)
                arrow = "▲" if chg >= 0 else "▼"
                assets[name] = {
                    "price": f"${price:,.2f}" if price < 100 else f"${price:,.0f}",
                    "chg":   f"{abs(chg):.2f}%",
                    "arrow": arrow,
                }
    except Exception as e:
        print(f"[CRYPTO ERROR] {e}")

    # Metals — Gold, Silver, Platinum
    try:
        for metal, symbol in [("Алт", "gold"), ("Мөнгө", "silver"), ("Платин", "platinum")]:
            r = requests.get(f"https://api.metals.live/v1/spot/{symbol}", timeout=10)
            d = r.json()
            price = d[0].get("price") if isinstance(d, list) else d.get("price")
            if price:
                assets[metal] = {
                    "price": f"${price:,.2f}/oz",
                    "chg":   "—",
                    "arrow": "—",
                }
    except Exception as e:
        print(f"[METALS ERROR] {e}")

    # Forex
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        rates = r.json().get("rates", {})
        if "MNT" in rates:
            assets["USD/MNT"] = {
                "price": f"₮{rates['MNT']:,.0f}",
                "chg":   "—",
                "arrow": "—",
            }
        if "CNY" in rates:
            assets["USD/CNY"] = {
                "price": f"¥{rates['CNY']:.4f}",
                "chg":   "—",
                "arrow": "—",
            }
    except Exception as e:
        print(f"[FOREX ERROR] {e}")

    return assets

def fetch_prices():
    """Legacy wrapper — keeps compatibility."""
    assets = fetch_assets()
    return {
        "bitcoin":  assets.get("Bitcoin", {}).get("price", "N/A"),
        "ethereum": assets.get("Ethereum", {}).get("price", "N/A"),
        "gold":     assets.get("Алт", {}).get("price", "N/A"),
        "usd_mnt":  assets.get("USD/MNT", {}).get("price", "N/A"),
    }

# ── GOOGLE TRANSLATE ───────────────────────────────────────────────────────────
def translate(text):
    if not GOOGLE_TRANSLATE or not text:
        return text
    try:
        r = requests.post(
            "https://translation.googleapis.com/language/translate/v2",
            params={"key": GOOGLE_TRANSLATE},
            json={"q": text, "target": "mn", "format": "text"},
            timeout=10
        )
        result = r.json()
        if "error" in result:
            print(f"[TRANSLATE ERROR] {result['error'].get('message')}")
            return text
        return result["data"]["translations"][0]["translatedText"]
    except Exception as e:
        print(f"[TRANSLATE ERROR] {e}")
        return text

# ── CLAUDE AI ──────────────────────────────────────────────────────────────────
def claude_write(title, summary, source, day_context, is_mn_source=False):
    """
    Claude writes structured English content.
    For Mongolian sources it writes a proper English version first.
    Includes trading RECOMMENDATION (not signal) style.
    """
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

SKIP only if the article is clearly about:
- Pure sports (MMA, football, basketball etc) with NO financial angle
- Entertainment, celebrities, movies, music
- Weather, natural disasters (unless major economic impact)
- Crime, accidents, politics (unless direct market impact)

If unsure — ACCEPT it. Respond with SKIP only when obviously non-financial.

Article title: {title}
Summary: {summary[:400]}
Source: {source}
Today's editorial focus: {day_context}

Write a structured response in EXACTLY this format:

HEADLINE: [Clear punchy headline, max 12 words]

SUMMARY: [2-3 sentences. What happened, why it matters. Simple language, no jargon.]

MONGOLIA_IMPACT: [1-2 sentences. How does this specifically affect Mongolian investors? Think: MSE stocks, tugrug rate, coal/copper/gold prices, Mongolian banks or businesses. Be specific and practical.]

RECOMMENDATION: [1 sentence. A practical observation — NOT a buy/sell signal. Example: "Investors monitoring MSE mining stocks may want to watch price action this week." or "This could be a good time to review commodity exposure in your portfolio." Always end with: This is not investment advice.]

Keep everything factual, clear and useful for a Mongolian investor reading this on Telegram."""

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
    return (headline.strip(), summary.strip(),
            impact.strip(), recommendation.strip())

# ── PROCESS ARTICLE ────────────────────────────────────────────────────────────
def process_article(title, summary, source, is_breaking, is_mn_source=False):
    day = now_ub().weekday()
    _, _, _, day_context = SCHEDULE.get(day, ("", "", "", "Summarize key financial news."))

    # Claude writes English content — may return SKIP for irrelevant articles
    raw = claude_write(title, summary, source, day_context, is_mn_source)

    # Claude rejected the article as non-financial
    if raw and raw.strip().upper().startswith("SKIP"):
        print(f"[CLAUDE SKIP] Not financial: {title[:60]}")
        return None

    headline_en, summary_en, impact_en, rec_en = parse_claude(raw)

    # Fallbacks
    if not headline_en:
        headline_en = title
        summary_en  = summary[:200] or "See full article."
        impact_en   = "Monitor for impact on Mongolian markets."
        rec_en      = "This is not investment advice."

    # Google Translate → Mongolian
    headline_mn = translate(headline_en)
    summary_mn  = translate(summary_en)
    impact_mn   = translate(impact_en)
    rec_mn      = translate(rec_en)

    return {
        "headline_en":    headline_en,
        "summary_en":     summary_en,
        "impact_en":      impact_en,
        "rec_en":         rec_en,
        "headline_mn":    headline_mn,
        "summary_mn":     summary_mn,
        "impact_mn":      impact_mn,
        "rec_mn":         rec_mn,
    }

# ── FORMAT POSTS ───────────────────────────────────────────────────────────────
def get_tag(is_breaking=False):
    if is_breaking:
        return "🚨", "Breaking News", "Яаралтай мэдээ"
    day = now_ub().weekday()
    e, en, mn, _ = SCHEDULE.get(day, ("📰", "News", "Мэдээ", ""))
    return e, en, mn

def build_premium_post(a):
    emoji, label_en, label_mn = get_tag(a.get("is_breaking", False))
    en = (
        f"{emoji} <b>{label_en}</b>\n\n"
        f"<b>{a['headline_en']}</b>\n\n"
        f"{a['summary_en']}\n\n"
        f"💡 <i>{a['impact_en']}</i>\n\n"
        f"📌 <i>{a['rec_en']}</i>\n\n"
        f"🔗 {a['link']}\n"
        f"<i>via {a['source']}</i>"
    )
    mn = (
        f"{emoji} <b>{label_mn}</b>\n\n"
        f"<b>{a['headline_mn']}</b>\n\n"
        f"{a['summary_mn']}\n\n"
        f"💡 <i>{a['impact_mn']}</i>\n\n"
        f"📌 <i>{a['rec_mn']}</i>\n\n"
        f"🔗 {a['link']}\n"
        f"<i>{a['source']}-аас</i>"
        f"{DISCLAIMER}"
    )
    return en, mn

def build_free_teaser(a):
    emoji, _, label_mn = get_tag(a.get("is_breaking", False))
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
        f"🇬🇧 <b>{a['headline_en']}</b>\n"
        f"{a['summary_en']}\n"
        f"💡 {a['impact_en']}\n"
        f"📌 {a['rec_en']}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🇲🇳 <b>{a['headline_mn']}</b>\n"
        f"{a['summary_mn']}\n"
        f"💡 {a['impact_mn']}\n"
        f"📌 {a['rec_mn']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔗 {a['link']}\n"
        f"<i>via {a['source']}</i>"
    )

def build_edit_template(a):
    emoji, label_en, label_mn = get_tag(a.get("is_breaking", False))
    return (
        f"✏️ Edit and send back:\n\n"
        f"══ ENGLISH (Premium) ══\n"
        f"{emoji} {label_en}\n\n"
        f"{a['headline_en']}\n\n"
        f"{a['summary_en']}\n\n"
        f"💡 {a['impact_en']}\n\n"
        f"📌 {a['rec_en']}\n\n"
        f"🔗 {a['link']}\n"
        f"via {a['source']}\n\n"
        f"══ MONGOLIAN (Premium) ══\n"
        f"{emoji} {label_mn}\n\n"
        f"{a['headline_mn']}\n\n"
        f"{a['summary_mn']}\n\n"
        f"💡 {a['impact_mn']}\n\n"
        f"📌 {a['rec_mn']}\n\n"
        f"🔗 {a['link']}\n"
        f"{a['source']}-аас"
        f"{DISCLAIMER}\n\n"
        f"══ FREE TEASER ══\n"
        f"{emoji} {a['headline_mn']}\n\n"
        f"{a['summary_mn'][:120]}...\n\n"
        f"🔒 Дэлгэрэнгүй шинжилгээ Premium сувгаас\n"
        f"➡️ Нэгдэх: {PREMIUM_INVITE}"
    )

# ── POST HELPERS ───────────────────────────────────────────────────────────────
def post_approved(a):
    en, mn = build_premium_post(a)
    teaser = build_free_teaser(a)
    send(PREMIUM_CHANNEL, en)
    time.sleep(2)
    send(PREMIUM_CHANNEL, mn)
    time.sleep(2)
    send(FREE_CHANNEL, teaser)
    print(f"[POSTED] {a['headline_en'][:60]}")

def post_custom(text):
    if "══ MONGOLIAN (Premium) ══" in text:
        parts = text.split("══")
        en_part = mn_part = teaser_part = ""
        current = None
        for p in parts:
            p = p.strip()
            if "ENGLISH (Premium)" in p: current = "en"
            elif "MONGOLIAN (Premium)" in p: current = "mn"
            elif "FREE TEASER" in p: current = "teaser"
            elif current == "en" and p: en_part = p
            elif current == "mn" and p: mn_part = p
            elif current == "teaser" and p: teaser_part = p
        if en_part:   send(PREMIUM_CHANNEL, en_part);   time.sleep(2)
        if mn_part:   send(PREMIUM_CHANNEL, mn_part);   time.sleep(2)
        if teaser_part: send(FREE_CHANNEL, teaser_part)
    else:
        send(PREMIUM_CHANNEL, text)
    print(f"[POSTED CUSTOM]")

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

    # POST 1 — МХБ Top 10
    mse_lines = ""
    for s in mse_stocks:
        icon = "🟢" if s["arrow"] == "▲" else "🔴"
        mse_lines += icon + " <b>" + s["symbol"] + "</b>  ₮" + s["price"] + "  " + s["arrow"] + s["pct"] + "\n"
    if not mse_lines:
        mse_lines = "<i>МХБ-ийн өгөгдөл татаж чадсангүй</i>\n"

    premium_mse = (
        "🇲🇳 <b>МХБ — Өнөөдрийн Топ 10 хувьцаа</b>\n"
        "<i>" + day_mn + ", " + date_str + "</i>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        + mse_lines +
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>Эх сурвалж: stock.bbe.mn</i>"
    )

    # POST 2 — 10 Assets
    asset_emojis = {
        "Bitcoin": "₿", "Ethereum": "💎", "BNB": "🔶",
        "XRP": "💧", "Solana": "🌊", "Алт": "🥇",
        "Мөнгө": "🥈", "Платин": "⚪", "USD/MNT": "💵", "USD/CNY": "🇨🇳"
    }
    asset_lines = ""
    for name, data in list(assets.items())[:10]:
        icon  = asset_emojis.get(name, "📊")
        arrow = data.get("arrow", "")
        chg   = data.get("chg", "")
        chg_str = "  " + arrow + chg if chg and chg != "—" else ""
        asset_lines += icon + " <b>" + name + "</b>  " + data["price"] + chg_str + "\n"

    premium_assets = (
        "💰 <b>10 Хөрөнгийн үнэ</b>\n"
        "<i>" + day_mn + ", " + date_str + "</i>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        + asset_lines +
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>Крипто: CoinGecko | Металл: Metals.live</i>"
    )

    # POST 3 — Global stocks
    global_emojis = {
        "S&P 500": "🇺🇸", "NASDAQ": "💻", "Apple": "🍎", "Nvidia": "🤖"
    }
    global_lines = ""
    for name, data in global_stocks.items():
        icon = global_emojis.get(name, "📈")
        global_lines += icon + " <b>" + name + "</b>  " + data["price"] + "  " + data["arrow"] + data["pct"] + "\n"
    btc = assets.get("Bitcoin", {})
    if btc:
        global_lines += "₿ <b>Bitcoin</b>  " + btc.get("price","N/A") + "  " + btc.get("arrow","") + btc.get("chg","") + "\n"
    if not global_lines:
        global_lines = "<i>Өгөгдөл татаж чадсангүй</i>\n"

    premium_global = (
        "🌍 <b>Дэлхийн томоохон хөрөнгүүд</b>\n"
        "<i>" + day_mn + ", " + date_str + "</i>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        + global_lines +
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>Эх сурвалж: Yahoo Finance</i>"
    )

    # FREE CHANNEL teaser
    btc_price  = assets.get("Bitcoin", {}).get("price", "N/A")
    gold_price = assets.get("Алт", {}).get("price", "N/A")
    usd_mnt    = assets.get("USD/MNT", {}).get("price", "N/A")
    top_stock  = mse_stocks[0] if mse_stocks else None

    free_post = (
        "🌅 <b>Өглөөний зах зээлийн тойм</b>\n"
        "<i>" + day_mn + ", " + date_str + "</i>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "₿ Bitcoin:  <b>" + btc_price + "</b>\n"
        "🥇 Алт:     <b>" + gold_price + "</b>\n"
        "💵 USD/MNT: <b>" + usd_mnt + "</b>\n"
    )
    if top_stock:
        icon = "🟢" if top_stock["arrow"] == "▲" else "🔴"
        free_post += icon + " МХБ топ: <b>" + top_stock["symbol"] + "</b> ₮" + top_stock["price"] + " " + top_stock["arrow"] + top_stock["pct"] + "\n"
    free_post += (
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📊 МХБ Топ 10, 10 хөрөнгийн үнэ, дэлхийн зах зээлийг Premium сувгаас аваарай!\n"
        "➡️ <b>Нэгдэх: " + PREMIUM_INVITE + "</b>"
    )

    send(PREMIUM_CHANNEL, premium_mse)
    time.sleep(3)
    send(PREMIUM_CHANNEL, premium_assets)
    time.sleep(3)
    send(PREMIUM_CHANNEL, premium_global)
    time.sleep(2)
    send(FREE_CHANNEL, free_post)
    print("[MORNING BRIEF] Done — MSE: " + str(len(mse_stocks)) + " stocks, Assets: " + str(len(assets)))


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


# ── ADMIN COMMANDS ─────────────────────────────────────────────────────────────
def handle_command(text):
    """Handle admin commands sent directly to the bot."""
    state = load_json(STATE_FILE, {})
    parts = text.strip().split()
    cmd   = parts[0].lower()

    # /status — show current bot settings
    if cmd == "/status":
        paused     = state.get("paused", False)
        hour_start = state.get("hour_start", ACTIVE_HOUR_START)
        hour_end   = state.get("hour_end",   ACTIVE_HOUR_END)
        ub         = now_ub()
        active     = is_active_hours()
        send(ADMIN_CHAT_ID,
            f"🤖 <b>Bot Status</b>\n\n"
            f"⏰ Current UB time: <b>{ub.strftime('%H:%M')}</b>\n"
            f"🕐 Active hours: <b>{hour_start}:00 – {hour_end}:00</b>\n"
            f"📡 Currently active: <b>{'Yes' if active and not paused else 'No'}</b>\n"
            f"⏸ Paused: <b>{'Yes' if paused else 'No'}</b>\n\n"
            f"<b>Commands:</b>\n"
            f"/pause — pause bot (no news sent to you)\n"
            f"/resume — resume bot\n"
            f"/hours 8 22 — set active hours (e.g. 8am to 10pm)\n"
            f"/checknow — fetch news immediately\n"
            f"/morning — post morning brief now\n"
            f"/status — show this message"
        )

    # /pause — pause bot
    elif cmd == "/pause":
        state["paused"] = True
        save_json(STATE_FILE, state)
        send(ADMIN_CHAT_ID,
            "⏸ <b>Bot paused.</b>\n\n"
            "No news will be sent to you until you type /resume.\n"
            "Breaking alerts also paused."
        )

    # /resume — resume bot
    elif cmd == "/resume":
        state["paused"] = False
        save_json(STATE_FILE, state)
        ub = now_ub()
        send(ADMIN_CHAT_ID,
            f"▶️ <b>Bot resumed!</b>\n\n"
            f"Current UB time: {ub.strftime('%H:%M')}\n"
            f"Active hours: {state.get('hour_start', ACTIVE_HOUR_START)}:00 – "
            f"{state.get('hour_end', ACTIVE_HOUR_END)}:00"
        )

    # /hours 8 22 — change active hours
    elif cmd == "/hours":
        if len(parts) == 3:
            try:
                h_start = int(parts[1])
                h_end   = int(parts[2])
                if 0 <= h_start < h_end <= 24:
                    state["hour_start"] = h_start
                    state["hour_end"]   = h_end
                    save_json(STATE_FILE, state)
                    send(ADMIN_CHAT_ID,
                        f"✅ <b>Active hours updated!</b>\n\n"
                        f"Bot now runs: <b>{h_start}:00 – {h_end}:00 UB time</b>\n\n"
                        f"Examples:\n"
                        f"/hours 8 22 → 8am to 10pm\n"
                        f"/hours 9 21 → 9am to 9pm\n"
                        f"/hours 8 24 → 8am to midnight"
                    )
                else:
                    send(ADMIN_CHAT_ID, "❌ Invalid hours. Example: /hours 8 22")
            except ValueError:
                send(ADMIN_CHAT_ID, "❌ Use numbers. Example: /hours 8 22")
        else:
            send(ADMIN_CHAT_ID,
                f"Current hours: {state.get('hour_start', ACTIVE_HOUR_START)}:00 – "
                f"{state.get('hour_end', ACTIVE_HOUR_END)}:00\n\n"
                "To change: /hours 8 22"
            )

    # /checknow — fetch news immediately regardless of schedule
    elif cmd == "/checknow":
        send(ADMIN_CHAT_ID, "🔍 Checking feeds now... You will receive articles shortly.")
        check_feeds()

    # /morning — post morning brief immediately
    elif cmd == "/morning":
        send(ADMIN_CHAT_ID, "🌅 Posting morning brief now...")
        post_morning_brief()

    else:
        send(ADMIN_CHAT_ID,
            f"❓ Unknown command: {cmd}\n\n"
            "<b>Available commands:</b>\n"
            "/status — bot status and settings\n"
            "/pause — pause the bot\n"
            "/resume — resume the bot\n"
            "/hours 8 22 — set active hours\n"
            "/checknow — fetch news immediately\n"
            "/morning — post morning brief now"
        )

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
            if ":" not in data: continue
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

        msg = update.get("message")
        if msg and str(msg.get("chat", {}).get("id")) == str(ADMIN_CHAT_ID):
            text    = msg.get("text", "").strip()
            waiting = edit_state.get("waiting")
            if not text: continue

            # Admin commands
            if text.startswith("/"):
                handle_command(text)
                continue

            # Edited post reply
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
    """Strict relevance check — must match finance keywords AND not match reject list."""
    text = (title + " " + summary).lower()

    # Hard reject non-financial content first
    if any(r.lower() in text for r in REJECT_KEYWORDS):
        print(f"[REJECTED] Non-financial content: {title[:60]}")
        return False

    # Must match at least one financial keyword
    return any(k.lower() in text for k in KEYWORDS)

def check_feeds():
    sent     = load_json(SENT_FILE, {})
    # Use both URL hash AND title hash to catch duplicates
    sent_ids = set(k for k in sent if not k.startswith("_"))
    queued   = 0
    breaking = []
    normal   = []

    for feed_url, source_name in ALL_FEEDS:
        is_mn = any(feed_url == f for f, _ in MN_FEEDS)
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                print(f"[EMPTY] {source_name}")
                continue

            for entry in feed.entries[:8]:
                # Use BOTH link and title as dedup keys
                link     = entry.get("link", "")
                title    = entry.get("title", "").strip()
                if not link or not title:
                    continue

                link_id  = make_id(link)
                title_id = make_id(title)

                # Skip if either ID seen before — prevents duplicates
                if link_id in sent_ids or title_id in sent_ids:
                    continue

                summary = entry.get("summary", "")
                if not is_relevant(title, summary):
                    continue

                item = {
                    "link_id":    link_id,
                    "title_id":   title_id,
                    "title":      title,
                    "summary":    summary,
                    "link":       link,
                    "source":     source_name,
                    "is_mn":      is_mn,
                    "is_breaking": any(w in title.lower() for w in BREAKING_WORDS),
                }

                if item["is_breaking"]:
                    breaking.append(item)
                else:
                    normal.append(item)

                # Mark both IDs as seen
                sent_ids.add(link_id)
                sent_ids.add(title_id)
                sent[link_id]  = True
                sent[title_id] = True

        except Exception as e:
            print(f"[FEED ERROR] {source_name}: {e}")

    # Breaking news first — max 2
    for item in breaking[:2]:
        print(f"[🚨 BREAKING] {item['title'][:60]}")
        processed = process_article(
            item["title"], item["summary"],
            item["source"], True, item["is_mn"]
        )
        if not processed:   # Claude rejected as non-financial
            continue
        queue_for_approval({
            "id": item["link_id"], "link": item["link"],
            "source": item["source"], "is_breaking": True,
            **processed
        })
        queued += 1
        time.sleep(2)

    # Normal news — max 3 per cycle
    for item in normal[:3]:
        print(f"[AI] {item['title'][:60]}")
        processed = process_article(
            item["title"], item["summary"],
            item["source"], False, item["is_mn"]
        )
        if not processed:   # Claude rejected as non-financial
            continue
        queue_for_approval({
            "id": item["link_id"], "link": item["link"],
            "source": item["source"], "is_breaking": False,
            **processed
        })
        queued += 1
        time.sleep(2)

    save_json(SENT_FILE, sent)
    ub = now_ub()
    print(f"[{ub.strftime('%H:%M UB')}] Queued {queued} articles "
          f"({len(breaking)} breaking, {len(normal)} normal found)")

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("MGL Newsroom Bot — Refined Version")
    print(f"  Free    : {FREE_CHANNEL}")
    print(f"  Premium : {PREMIUM_CHANNEL}")
    print(f"  Hours   : {ACTIVE_HOUR_START}am–{ACTIVE_HOUR_END-2}pm UB")
    print(f"  Claude  : {'✅' if ANTHROPIC_KEY    else '❌ missing'}")
    print(f"  Google  : {'✅' if GOOGLE_TRANSLATE else '❌ missing'}")
    print("=" * 55)

    if not BOT_TOKEN:    print("[FATAL] BOT_TOKEN missing!"); return
    if not ADMIN_CHAT_ID: print("[FATAL] ADMIN_CHAT_ID missing!"); return

    send(ADMIN_CHAT_ID,
        "🤖 <b>MGL Newsroom Bot — Refined</b>\n\n"
        f"📢 Free: {FREE_CHANNEL}\n"
        f"💎 Premium: private\n"
        f"🕐 Active: 8am–10pm UB time\n"
        f"📰 News checks: 8am, 11am, 2pm, 5pm, 8pm\n"
        f"🤖 Claude: {'✅' if ANTHROPIC_KEY    else '❌'} | "
        f"Google Translate: {'✅' if GOOGLE_TRANSLATE else '❌'}\n\n"
        "<b>What's new:</b>\n"
        "✅ No duplicate posts\n"
        "✅ Mongolian sources included\n"
        "✅ Trading recommendations (not signals)\n"
        "✅ Quiet after 10pm — no night spam\n"
        "✅ Breaking news instant any time\n\n"
        "Running!")

    while True:
        try:
            # Always check button taps — 10 second interval
            handle_updates()

            # Morning brief at 8am UB
            if should_post_morning_brief():
                post_morning_brief()

            # News checks at 8, 11, 14, 17, 20 UB — only during active hours
            if is_active_hours() and should_check_feeds():
                check_feeds()

        except Exception as e:
            print(f"[LOOP ERROR] {e}")

        time.sleep(10)

if __name__ == "__main__":
    main()
