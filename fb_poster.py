"""
MGL Newsroom — Facebook Auto Poster (Text Only)
=================================================
- Fetches MSE + crypto + gold + forex data daily
- Claude writes post, Google Translate to Mongolian
- Sends YOU Telegram preview with ✅ Post / ❌ Skip
- Posts to Facebook via Make.com webhook (no image)
- Runs at 15:30 UB daily after MSE closes

Env vars needed:
  MAKE_WEBHOOK_URL    — from Make.com scenario
  BOT_TOKEN           — same as bot.py
  ADMIN_CHAT_ID       — same as bot.py
  ANTHROPIC_API_KEY   — same as bot.py
  GOOGLE_TRANSLATE_KEY — same as bot.py

Run daily: python fb_poster.py
Test now:  python fb_poster.py --now
"""

import requests
import re
import os
import time
import json
from datetime import datetime, timezone, timedelta

# ── CONFIG ─────────────────────────────────────────────────────────────────────
MAKE_WEBHOOK_URL = os.environ.get("MAKE_WEBHOOK_URL")
BOT_TOKEN        = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID    = os.environ.get("ADMIN_CHAT_ID")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_TRANSLATE = os.environ.get("GOOGLE_TRANSLATE_KEY")

UB_OFFSET     = timedelta(hours=8)
TELEGRAM_LINK = "https://t.me/mglnewsroomfree"
FB_STATE_FILE = "fb_state.json"

# ── COMPANY NAMES ─────────────────────────────────────────────────────────────
COMPANY_NAMES = {
    "AARD": "Ард Санхүү",
    "ADB":  "Ардын банк",
    "AIC":  "Ард Иншуранс",
    "AMT":  "Ар Монгол Трейд",
    "APU":  "АПУ ХК",
    "BODI": "Боди Интернэшнл",
    "CNF":  "Кан Файнанс",
    "CUMN": "Камминс Монгол",
    "ERDN": "Эрдэнэт Үйлдвэр",
    "GAZR": "Газрын тос",
    "GLMT": "Голомт Банк",
    "KHAN": "ХААН Банк",
    "MIK":  "МИК ХК",
    "MSE":  "МХБ ХК",
    "MNDL": "Мандал Даатгал",
    "ORD":  "Ордер ХК",
    "QPAY": "QPay ХК",
    "SHV":  "Шивээ-Овоо",
    "TDB":  "Худалдаа Хөгжлийн Банк",
    "TTL":  "Тавантолгой ХК",
    "XAC":  "ХАС Банк",
    "MMRE": "Монгол Морин Эрдэнэ",
}

def now_ub():
    return datetime.now(timezone.utc) + UB_OFFSET
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

def fmt_vol(vol_str):
    try:
        v = float(vol_str.replace(",", ""))
        if v >= 1_000_000_000: return f"₮{v/1_000_000_000:.1f}тэрбум"
        elif v >= 1_000_000:   return f"₮{v/1_000_000:.1f}M"
        elif v >= 1_000:       return f"₮{v/1_000:.1f}K"
        return f"₮{v:,.0f}"
    except Exception:
        return f"₮{vol_str}" if vol_str else ""

# ── TELEGRAM ───────────────────────────────────────────────────────────────────
def tg(method, payload=None):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload, timeout=15
        )
        return r.json()
    except Exception as e:
        print(f"[TG ERROR] {method}: {e}")
        return {}

def tg_send(chat_id, text, markup=None):
    payload = {
        "chat_id":    chat_id,
        "text":       text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if markup:
        payload["reply_markup"] = json.dumps(markup)
    return tg("sendMessage", payload)

# ── DATA FETCHERS ──────────────────────────────────────────────────────────────
def fetch_mse_data():
    stocks    = []
    index_val = None

    try:
        r = requests.get("https://stock.bbe.mn/", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        rows = re.findall(
            r"Home/Stock/([A-Z]+).*?>([\d,\.]+)</td>.*?>([\d,\.]+)</td>.*?([-\d,\.]+)</td>.*?([-\d\.]+%)</td>",
            r.text, re.DOTALL
        )
        for row in rows[:10]:
            symbol, prev, curr, change, pct = row
            stocks.append({
                "symbol": symbol.strip(),
                "price":  curr.strip(),
                "change": change.strip(),
                "pct":    pct.strip(),
                "arrow":  "▲" if not change.strip().startswith("-") else "▼",
            })
        idx = re.search(r"TOP.{0,5}20[^\d]*([\d,\.]+)", r.text, re.IGNORECASE)
        if idx:
            index_val = idx.group(1)
    except Exception as e:
        print(f"[MSE] failed: {e}")

    return stocks, index_val

def fetch_assets():
    assets = {}

    # Crypto — Bitcoin and Ethereum
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true",
            timeout=12
        )
        for key, name in [("bitcoin", "Bitcoin"), ("ethereum", "Ethereum")]:
            d = r.json().get(key, {})
            if d.get("usd"):
                price = d["usd"]
                chg   = d.get("usd_24h_change", 0)
                assets[name] = {
                    "price": f"${price:,.0f}",
                    "chg":   f"{abs(chg):.2f}%",
                    "arrow": "▲" if chg >= 0 else "▼",
                }
    except Exception as e:
        print(f"[CRYPTO] {e}")

    # Metals — Gold and Silver
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        d = r.json()
        price = d[0].get("price") if isinstance(d, list) else d.get("price")
        if price:
            assets["Алт"] = {"price": f"${float(price):,.2f}/oz", "arrow": "—", "chg": "—"}
    except Exception:
        pass

    try:
        r = requests.get("https://api.metals.live/v1/spot/silver", timeout=10)
        d = r.json()
        price = d[0].get("price") if isinstance(d, list) else d.get("price")
        if price:
            assets["Мөнгө"] = {"price": f"${float(price):,.2f}/oz", "arrow": "—", "chg": "—"}
    except Exception:
        pass

    # Forex
    try:
        r     = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        rates = r.json().get("rates", {})
        if rates.get("MNT"):
            assets["USD/MNT"] = {"price": f"₮{rates['MNT']:,.0f}", "arrow": "—", "chg": "—"}
        if rates.get("CNY"):
            assets["USD/CNY"] = {"price": f"¥{rates['CNY']:.4f}", "arrow": "—", "chg": "—"}
    except Exception:
        pass

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

# ── CLAUDE — write engaging intro ─────────────────────────────────────────────
def claude_intro(stocks, assets):
    if not ANTHROPIC_KEY or not stocks:
        return ""
    try:
        top  = stocks[0]
        date = now_ub().strftime("%Y.%m.%d")
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 120,
                "messages":   [{
                    "role":    "user",
                    "content": (
                        f"Write 2 engaging sentences for a Mongolian stock market "
                        f"Facebook post intro for {date}. "
                        f"Top stock: {top['symbol']} ₮{top['price']} {top['arrow']}{top['pct']}. "
                        f"Use 1-2 emojis. Professional but exciting. English only. No hashtags."
                    )
                }]
            }, timeout=20
        )
        intro_en = r.json()["content"][0]["text"].strip()
        return translate(intro_en)
    except Exception as e:
        print(f"[CLAUDE] {e}")
        return ""

# ── BUILD POST TEXT ────────────────────────────────────────────────────────────
def build_post_text(stocks, assets, index_val, intro):
    ub       = now_ub()
    date_str = ub.strftime("%Y.%m.%d")
    lines    = []

    # Intro from Claude
    if intro:
        lines.append(intro)
        lines.append("")

    # Header
    lines.append(f"МХБ-ийн арилжааны тойм | {date_str}")
    lines.append("")

    # Top gainers and losers
    gainers = [s for s in stocks if s["arrow"] == "▲"]
    losers  = [s for s in stocks if s["arrow"] == "▼"]
    top_gainer = gainers[0] if gainers else None
    top_loser  = losers[0]  if losers  else None

    if top_gainer:
        name = COMPANY_NAMES.get(top_gainer["symbol"], top_gainer["symbol"])
        lines.append(f"📈 Өнөөдрийн хамгийн өндөр өсөлт:")
        lines.append(f"{name} ({top_gainer['symbol']}) — ▲{top_gainer['pct']} | ₮{top_gainer['price']}")
        lines.append("")

    if top_loser:
        name = COMPANY_NAMES.get(top_loser["symbol"], top_loser["symbol"])
        lines.append(f"📉 Өнөөдрийн хамгийн их уналт:")
        lines.append(f"{name} ({top_loser['symbol']}) — ▼{top_loser['pct']} | ₮{top_loser['price']}")
        lines.append("")

    # Index
    if index_val:
        lines.append(f"📊 МХБ ТОП-20 индекс: {index_val} нэгж")
        lines.append("")

    # All 10 stocks with company names
    lines.append(f"📋 МХБ-ийн 10 ЧУХАЛ ХУВЬЦАА | {date_str}")
    lines.append("")
    for s in stocks:
        arrow  = "📈" if s["arrow"] == "▲" else "📉"
        name   = COMPANY_NAMES.get(s["symbol"], "")
        label  = f"{s['symbol']} — {name}" if name else s["symbol"]
        lines.append(f"{arrow} {label}")
        lines.append(f"₮{s['price']} | {s['arrow']}{s['pct']}")
        lines.append("")

    # Assets section
    lines.append("💰 Дэлхийн зах зээл:")
    lines.append("")

    btc  = assets.get("Bitcoin")
    eth  = assets.get("Ethereum")
    gold = assets.get("Алт")
    silv = assets.get("Мөнгө")
    usd  = assets.get("USD/MNT")
    cny  = assets.get("USD/CNY")

    if btc:
        arrow = btc.get("arrow", "")
        chg   = btc.get("chg", "")
        lines.append(f"₿ Bitcoin: {btc['price']} {arrow}{chg}")
    if eth:
        arrow = eth.get("arrow", "")
        chg   = eth.get("chg", "")
        lines.append(f"Ξ Ethereum: {eth['price']} {arrow}{chg}")
    if gold:
        lines.append(f"🥇 Алт: {gold['price']}")
    if silv:
        lines.append(f"🥈 Мөнгө: {silv['price']}")
    if usd:
        lines.append(f"💵 USD/MNT: {usd['price']}")
    if cny:
        lines.append(f"🇨🇳 USD/CNY: {cny['price']}")

    lines.append("")

    # Footer
    lines += [
        "━━━━━━━━━━━━━━━━━━",
        "⚠️ Энэхүү мэдээлэл нь зөвхөн мэдээллийн зорилготой бөгөөд",
        "хөрөнгө оруулалтын зөвлөгөө биш болно.",
        "",
        f"📲 Илүү их мэдээллийг {TELEGRAM_LINK} - ээс аваарай!",
        "",
        "#МХБ #MSE #хөрөнгөоруулалт #МонголынЗахЗээл #MGLNewsroom",
    ]

    return "\n".join(lines)

# ── POST TO FACEBOOK VIA MAKE.COM WEBHOOK ─────────────────────────────────────
def post_via_make(message):
    if not MAKE_WEBHOOK_URL:
        print("[MAKE] MAKE_WEBHOOK_URL missing!")
        return False
    try:
        r = requests.post(
            MAKE_WEBHOOK_URL,
            json={"message": message},
            timeout=30
        )
        if r.status_code == 200:
            print(f"[MAKE] ✅ Sent to Make.com!")
            return True
        print(f"[MAKE] ❌ Status: {r.status_code} — {r.text}")
        return False
    except Exception as e:
        print(f"[MAKE] ERROR: {e}")
        return False

# ── TELEGRAM APPROVAL ──────────────────────────────────────────────────────────
def send_for_approval(post_text, stocks):
    state = load_json(FB_STATE_FILE, {})
    top   = stocks[0] if stocks else {}

    preview = (
        f"📱 <b>Facebook Post Preview</b>\n"
        f"📅 {now_ub().strftime('%Y.%m.%d %H:%M')} UB\n\n"
        f"📊 Топ: <b>{top.get('symbol','')}</b> "
        f"₮{top.get('price','')} {top.get('arrow','')+top.get('pct','')}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{post_text[:800]}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"Нийтлэх үү?"
    )
    markup = {"inline_keyboard": [[
        {"text": "✅ Facebook-т нийтлэх", "callback_data": "fb_approve"},
        {"text": "❌ Алгасах",            "callback_data": "fb_skip"},
    ]]}

    result = tg_send(ADMIN_CHAT_ID, preview, markup)
    state["pending"] = {
        "date":           now_ub().strftime("%Y-%m-%d"),
        "post_text":      post_text,
        "preview_msg_id": result.get("result", {}).get("message_id"),
    }
    save_json(FB_STATE_FILE, state)
    print("[FB] Preview sent — waiting for your approval")

def handle_fb_updates(post_text):
    state  = load_json(FB_STATE_FILE, {})
    offset = state.get("tg_offset", 0)
    resp   = tg("getUpdates", {"offset": offset, "timeout": 5})

    for update in resp.get("result", []):
        offset = update["update_id"] + 1
        cb     = update.get("callback_query")
        if not cb:
            state["tg_offset"] = offset
            continue

        data    = cb.get("data", "")
        cb_id   = cb["id"]
        chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))

        if not data.startswith("fb_"):
            state["tg_offset"] = offset
            continue

        if chat_id != str(ADMIN_CHAT_ID):
            continue

        if data == "fb_approve":
            tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": "✅ Нийтэлж байна..."})
            success = post_via_make(post_text)
            msg     = "✅ Make.com-оор Facebook-т илгээгдлээ!" if success else "❌ Make.com алдаа гарлаа!"
            tg_send(ADMIN_CHAT_ID, msg)
            state.pop("pending", None)
            state["tg_offset"] = offset
            save_json(FB_STATE_FILE, state)
            return "posted" if success else "failed"

        elif data == "fb_skip":
            tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": "❌ Алгасагдлаа"})
            tg_send(ADMIN_CHAT_ID, "❌ Өнөөдрийн Facebook пост алгасагдлаа.")
            state.pop("pending", None)
            state["tg_offset"] = offset
            save_json(FB_STATE_FILE, state)
            return "skipped"

    state["tg_offset"] = offset
    save_json(FB_STATE_FILE, state)
    return None

# ── MAIN ───────────────────────────────────────────────────────────────────────
def run_daily_fb_post():
    print(f"[FB] Starting — {now_ub().strftime('%Y.%m.%d %H:%M UB')}")

    stocks, index_val = fetch_mse_data()
    assets            = fetch_assets()
    intro             = claude_intro(stocks, assets)
    post_text         = build_post_text(stocks, assets, index_val, intro)

    print(f"[FB] Stocks: {len(stocks)}, Assets: {len(assets)}")
    print(f"[FB] Post length: {len(post_text)} chars")

    send_for_approval(post_text, stocks)

    # Wait up to 2 hours for approval
    deadline = time.time() + 7200
    while time.time() < deadline:
        result = handle_fb_updates(post_text)
        if result in ("posted", "skipped", "failed"):
            return
        time.sleep(15)

    tg_send(ADMIN_CHAT_ID, "⏰ Facebook пост 2 цагийн дотор зөвшөөрөгдөөгүй тул алгасагдлаа.")

def main():
    print("=" * 50)
    print("MGL Newsroom — Facebook Auto Poster (Text Only)")
    print(f"  Webhook : {'✅' if MAKE_WEBHOOK_URL else '❌ MISSING — add MAKE_WEBHOOK_URL'}")
    print(f"  Bot     : {'✅' if BOT_TOKEN        else '❌ MISSING'}")
    print(f"  Claude  : {'✅' if ANTHROPIC_KEY    else '❌ MISSING'}")
    print(f"  Google  : {'✅' if GOOGLE_TRANSLATE else '❌ MISSING'}")
    print("=" * 50)
    print("Posts at 15:30 UB daily.\n")

    posted_today = None
    while True:
        try:
            ub    = now_ub()
            today = ub.strftime("%Y-%m-%d")
            if ub.hour == 15 and ub.minute >= 30 and posted_today != today:
                posted_today = today
                run_daily_fb_post()
        except Exception as e:
            print(f"[LOOP ERROR] {e}")
        time.sleep(60)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        run_daily_fb_post()
    else:
        main()