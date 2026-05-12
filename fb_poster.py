"""
MGL Newsroom — Facebook Auto Poster
=====================================
Posts daily МХБ trading summary to Facebook.
Matches your exact post style with:
- TOP-20 index
- Per-stock: price, change%, volume
- Dividend info for key stocks
- Telegram approval before posting
- Auto image generation
- Gemini Mongolian text

Env vars needed:
  FB_PAGE_ID, FB_ACCESS_TOKEN, GEMINI_API_KEY
  BOT_TOKEN, ADMIN_CHAT_ID (same as bot.py)

Install: pip install pillow
Run daily: python fb_poster.py
Test now:  python fb_poster.py --now
"""

import requests
import re
import os
import time
import json
import io
from datetime import datetime, timezone, timedelta

# ── CONFIG ─────────────────────────────────────────────────────────────────────
FB_PAGE_ID      = os.environ.get("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.environ.get("FB_ACCESS_TOKEN")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_TRANSLATE = os.environ.get("GOOGLE_TRANSLATE_KEY")
BOT_TOKEN       = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID   = os.environ.get("ADMIN_CHAT_ID")

UB_OFFSET     = timedelta(hours=8)
TELEGRAM_LINK = "https://t.me/mglnewsroomfree"
FB_STATE_FILE = "fb_state.json"

# Dividend cache — auto-filled by fetch_dividend_info()
DIVIDEND_CACHE = {}

def now_ub():
    return datetime.now(timezone.utc) + UB_OFFSET

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

def fmt_vol(vol_str):
    """Format volume number nicely e.g. 262400000 → ₮262.4M"""
    try:
        v = float(vol_str.replace(",", ""))
        if v >= 1_000_000_000:
            return f"₮{v/1_000_000_000:.1f}тэрбум"
        elif v >= 1_000_000:
            return f"₮{v/1_000_000:.1f}M"
        elif v >= 1_000:
            return f"₮{v/1_000:.1f}K"
        return f"₮{v:,.0f}"
    except Exception:
        return f"₮{vol_str}" if vol_str else ""

# ── TELEGRAM ───────────────────────────────────────────────────────────────────
def tg(method, payload=None, files=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        if files:
            r = requests.post(url, data=payload, files=files, timeout=30)
        else:
            r = requests.post(url, json=payload, timeout=15)
        return r.json()
    except Exception as e:
        print(f"[TG ERROR] {method}: {e}")
        return {}

def tg_send(chat_id, text, markup=None):
    payload = {"chat_id": chat_id, "text": text[:4096],
               "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        payload["reply_markup"] = json.dumps(markup)
    return tg("sendMessage", payload)

def tg_send_photo(chat_id, image_bytes, caption, markup=None):
    payload = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = json.dumps(markup)
    files = {"photo": ("preview.jpg", image_bytes, "image/jpeg")}
    return tg("sendPhoto", payload, files=files)

# ── MSE DATA FETCHER ───────────────────────────────────────────────────────────
def fetch_mse_data():
    """
    Fetch top 10 stocks + TOP-20 index from bbe.mn and mse.mn.
    Returns: (stocks_list, index_value, market_cap)
    """
    stocks = []
    index_val  = None
    market_cap = None

    # ── Stocks from bbe.mn ─────────────────────────────────────────────────
    try:
        r = requests.get("https://stock.bbe.mn/", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        # Try with volume (6 groups)
        rows = re.findall(
            r'Home/Stock/([A-Z]+)[^>]*>.*?<td[^>]*>([\d,\.]+)</td>.*?<td[^>]*>([\d,\.]+)</td>.*?<td[^>]*>([-\d,\.]+)</td>.*?<td[^>]*>([-\d\.]+%)</td>.*?<td[^>]*>([\d,\.]+)</td>',
            r.text, re.DOTALL
        )
        if rows:
            for row in rows[:10]:
                symbol, prev, curr, change, pct, vol = row
                stocks.append({
                    "symbol": symbol.strip(),
                    "price":  curr.strip(),
                    "change": change.strip(),
                    "pct":    pct.strip(),
                    "vol":    vol.strip(),
                    "arrow":  "▲" if not change.strip().startswith("-") else "▼",
                })
        else:
            # Fallback: without volume
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
                    "vol":    "",
                    "arrow":  "▲" if not change.strip().startswith("-") else "▼",
                })

        # Try to get TOP-20 index from same page
        idx = re.search(r"TOP.{0,5}20[^\d]*([\d,\.]+)", r.text, re.IGNORECASE)
        if idx:
            index_val = idx.group(1)

    except Exception as e:
        print(f"[MSE] bbe.mn failed: {e}")

    # ── Index from mse.mn if not found ────────────────────────────────────
    if not index_val:
        try:
            r2 = requests.get("https://mse.mn/mn/market", timeout=12,
                              headers={"User-Agent": "Mozilla/5.0"})
            idx = re.search(r"([\d,\.]+)\s*(?:нэгж|points?)", r2.text)
            if idx:
                index_val = idx.group(1)
            cap = re.search(r"([\d,\.]+)\s*(?:их наяд|тэрбум)", r2.text)
            if cap:
                market_cap = cap.group(0)
        except Exception as e:
            print(f"[MSE] mse.mn index failed: {e}")

    return stocks, index_val, market_cap

# ── DIVIDEND FETCHER ───────────────────────────────────────────────────────────
def fetch_dividend_info(symbols):
    """
    Fetch dividend info for given stock symbols from mse.mn.
    Returns dict: { "GLMT": {"amount": "₮100", "year": "2024", "yield": "7.9%"}, ... }
    """
    global DIVIDEND_CACHE
    results = {}

    for sym in symbols[:5]:  # top 5 only to avoid slowdown
        try:
            r = requests.get(
                f"https://mse.mn/mn/company/{sym}",
                timeout=10, headers={"User-Agent": "Mozilla/5.0"}
            )
            text = r.text

            # Look for dividend amount pattern e.g. "100", "₮100", "ногдол ашиг"
            div_match = re.search(
                r'(?:ногдол ашиг|dividend)[^\d₮]*([\d,\.]+)\s*(?:₮|төгрөг)?',
                text, re.IGNORECASE
            )
            year_match = re.search(r'(20\d\d)\s*(?:он|оны|year)', text, re.IGNORECASE)
            yield_match = re.search(r'([\d\.]+)\s*%\s*(?:yield|өгөөж)', text, re.IGNORECASE)

            if div_match:
                info = {"amount": f"₮{div_match.group(1)}"}
                if year_match:
                    info["year"] = year_match.group(1)
                if yield_match:
                    info["yield"] = f"{yield_match.group(1)}%"
                results[sym] = info
                print(f"[DIV] {sym}: {info}")
        except Exception as e:
            print(f"[DIV] {sym} failed: {e}")

    DIVIDEND_CACHE = results
    return results

# ── ASSET FETCHER ──────────────────────────────────────────────────────────────
def fetch_assets():
    assets = {}
    # Crypto
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,binancecoin,ripple,solana"
            "&vs_currencies=usd&include_24hr_change=true", timeout=12
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
    except Exception as e:
        print(f"[CRYPTO] {e}")
        for cid, name in [("bitcoin", "Bitcoin"), ("ethereum", "Ethereum")]:
            try:
                r     = requests.get(f"https://api.coincap.io/v2/assets/{cid}", timeout=10)
                d     = r.json().get("data", {})
                price = float(d.get("priceUsd", 0))
                chg   = float(d.get("changePercent24Hr", 0))
                if price:
                    assets[name] = {
                        "price": f"${price:,.0f}",
                        "chg":   f"{abs(chg):.2f}%",
                        "arrow": "▲" if chg >= 0 else "▼",
                    }
            except Exception:
                pass

    # Gold
    try:
        r     = requests.get("https://api.metals.live/v1/spot/gold", timeout=10)
        d     = r.json()
        price = d[0].get("price") if isinstance(d, list) else d.get("price")
        if price:
            assets["Алт"] = {"price": f"${float(price):,.2f}/oz", "chg": "—", "arrow": "—"}
    except Exception:
        try:
            r     = requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=tether-gold&vs_currencies=usd",
                timeout=10)
            price = r.json().get("tether-gold", {}).get("usd")
            if price:
                assets["Алт"] = {"price": f"${float(price):,.2f}/oz", "chg": "—", "arrow": "—"}
        except Exception:
            pass

    # Forex
    try:
        r     = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        rates = r.json().get("rates", {})
        if rates.get("MNT"):
            assets["USD/MNT"] = {"price": f"₮{rates['MNT']:,.0f}", "chg": "—", "arrow": "—"}
    except Exception:
        pass

    return assets

# ── BUILD FACEBOOK POST TEXT ───────────────────────────────────────────────────
def build_post_text(stocks, assets, index_val, market_cap, dividends={}):
    """Build post matching your exact style."""
    ub       = now_ub()
    date_str = ub.strftime("%Y.%m.%d")

    lines = []

    # ── Header ──
    lines.append(f"МХБ-ийн арилжааны тойм | {date_str}")
    lines.append("")

    # ── Highlight top 2 stocks ──
    if len(stocks) >= 2:
        top1 = stocks[0]
        top2 = stocks[1]
        lines.append(f'"{top1["symbol"]}" болон "{top2["symbol"]}" ХК — зах зээлийн тэргүүлэгчид идэвхтэй хэвээр!')
        lines.append("")

    # ── Detailed info for top 2 stocks ──
    for s in stocks[:2]:
        sym = s["symbol"]
        lines.append(f"📌 {sym} ХК | MSE: {sym}")
        lines.append(f"Өнөөдрийн ханш: ₮{s['price']} | Өөрчлөлт: {s['change']} ({s['pct']})")
        if s.get("vol"):
            lines.append(f"Арилжааны дүн: {fmt_vol(s['vol'])}")

        # Dividend info — only show if from current year
        div          = dividends.get(sym, {})
        current_year = str(now_ub().year)
        if div.get("amount") and div.get("year") == current_year:
            dyield   = div.get("yield", "")
            div_line = f"💰 Ногдол ашиг: {div['amount']}/хувьцаа"
            if dyield:
                div_line += f" | Өгөөж: {dyield}"
            lines.append(div_line)
        lines.append("")

    # ── TOP-20 Index ──
    if index_val:
        lines.append(f"📊 МХБ ТОП-20 индекс: {index_val} нэгж")
    if market_cap:
        lines.append(f"💹 Нийт зах зээлийн хөрөнгөжилт: {market_cap}")
    if index_val or market_cap:
        lines.append("")

    # ── All 10 stocks ──
    lines.append(f"📋 МХБ-ийн 10 ЧУХАЛ ХУВЬЦАА | {date_str}")
    lines.append("")
    for s in stocks:
        arrow = "📈" if s["arrow"] == "▲" else "📉"
        line  = f"{arrow} {s['symbol']}\n₮{s['price']} | {s['arrow']}{s['pct']}"
        if s.get("vol"):
            line += f" | Vol: {fmt_vol(s['vol'])}"

        # Add dividend note only if current year
        div          = dividends.get(s["symbol"], {})
        current_year = str(now_ub().year)
        if div.get("amount") and div.get("year") == current_year:
            line += f"\n💰 Ногдол ашиг: {div['amount']}/хувьцаа"

        lines.append(line)
        lines.append("")

    # ── Disclaimer + sources ──
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ Энэхүү мэдээлэл нь зөвхөн мэдээллийн зорилготой бөгөөд")
    lines.append("хөрөнгө оруулалтын зөвлөгөө биш болно.")
    lines.append("")
    lines.append(f"📲 Илүү их мэдээллийг {TELEGRAM_LINK} - ээс")
    lines.append("")
    lines.append("#МХБ #MSE #хөрөнгөоруулалт #МонголынЗахЗээл #MGLNewsroom")

    return "\n".join(lines)

# ── GOOGLE TRANSLATE ──────────────────────────────────────────────────────────
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

# ── CLAUDE — write English intro, Gemini translates ───────────────────────────
def claude_enhance(base_text, stocks, assets):
    """Claude writes engaging English intro → Gemini translates to Mongolian."""
    if not ANTHROPIC_KEY or not stocks:
        return base_text
    try:
        top  = stocks[0]
        date = now_ub().strftime("%Y.%m.%d")
        prompt = (
            f"Write exactly 2 engaging sentences for a Mongolian stock market "
            f"Facebook page intro for today's ({date}) МХБ daily summary.\n"
            f"Top stock: {top['symbol']} at ₮{top['price']} ({top['arrow']}{top['pct']})\n\n"
            f"Rules:\n"
            f"- Write in English\n"
            f"- Use 1-2 emojis\n"
            f"- Sound professional but exciting\n"
            f"- No hashtags\n"
            f"- 2 sentences only\n\n"
            f"Output the 2 sentences only."
        )
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "messages":   [{"role": "user", "content": prompt}]
            }, timeout=20
        )
        intro_en = r.json()["content"][0]["text"].strip()

        # Google Translate → Mongolian
        intro_mn = translate(intro_en)

        lines    = base_text.split("\n")
        new_text = intro_mn + "\n\n" + "\n".join(lines[1:])
        return new_text
    except Exception as e:
        print(f"[CLAUDE FB] {e}")
        return base_text

# ── IMAGE GENERATOR ────────────────────────────────────────────────────────────
def generate_image(stocks, assets, index_val):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[IMAGE] Run: pip install pillow")
        return None

    ub       = now_ub()
    date_str = ub.strftime("%Y.%m.%d")
    W, H     = 1200, 630

    img  = Image.new("RGB", (W, H), color=(8, 15, 40))
    draw = ImageDraw.Draw(img)

    for i in range(H):
        ratio = i / H
        draw.line([(0, i), (W, i)],
                  fill=(int(8+ratio*12), int(15+ratio*10), int(40+ratio*20)))

    draw.rectangle([0, 0, 6, H],        fill=(0, 200, 100))
    draw.rectangle([580, 40, 583, H-40], fill=(0, 180, 90))

    try:
        fp      = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
        f_title  = ImageFont.truetype(f"{fp}-Bold.ttf", 38)
        f_large  = ImageFont.truetype(f"{fp}-Bold.ttf", 28)
        f_medium = ImageFont.truetype(f"{fp}.ttf", 22)
        f_small  = ImageFont.truetype(f"{fp}.ttf", 18)
        f_tiny   = ImageFont.truetype(f"{fp}.ttf", 14)
    except Exception:
        f_title = f_large = f_medium = f_small = f_tiny = ImageFont.load_default()

    # ── LEFT: MSE stocks ──
    draw.text((30, 22),  "МХБ",                       font=f_title,  fill=(0, 220, 120))
    draw.text((30, 68),  "MONGOLIAN STOCK EXCHANGE",   font=f_tiny,   fill=(140, 170, 210))
    if index_val:
        draw.text((30, 90), f"TOP-20: {index_val}",   font=f_small,  fill=(0, 220, 120))
    draw.text((30, 112), f"Арилжааны тойм | {date_str}", font=f_small, fill=(170, 195, 235))
    draw.line([(30, 138), (555, 138)], fill=(0, 180, 100), width=2)

    y = 150
    for s in stocks[:8]:
        is_up  = s["arrow"] == "▲"
        color  = (0, 220, 120) if is_up else (255, 75, 75)
        bg     = (0, 38, 18)   if is_up else (38, 8, 8)
        draw.rectangle([28, y-3, 556, y+26], fill=bg)
        draw.text((35,  y), s["symbol"],               font=f_medium, fill=(255, 255, 255))
        draw.text((155, y), f"\u20ae{s['price']}",     font=f_medium, fill=(195, 215, 255))
        draw.text((330, y), f"{s['arrow']}{s['pct']}", font=f_medium, fill=color)
        if s.get("vol"):
            draw.text((440, y), fmt_vol(s["vol"]),     font=f_tiny,   fill=(150, 175, 220))
        y += 36

    # ── RIGHT: Assets ──
    rx = 605
    draw.text((rx, 22), "ASSETS",               font=f_title, fill=(0, 220, 120))
    draw.text((rx, 68), "Крипто | Металл | Валют", font=f_tiny, fill=(140, 170, 210))
    draw.line([(rx, 100), (1170, 100)], fill=(0, 180, 100), width=2)

    asset_rows = [
        ("Bitcoin",  "BTC", assets.get("Bitcoin")),
        ("Ethereum", "ETH", assets.get("Ethereum")),
        ("Алт",      "Au",  assets.get("Алт")),
        ("USD/MNT",  "USD", assets.get("USD/MNT")),
        ("BNB",      "BNB", assets.get("BNB")),
        ("Solana",   "SOL", assets.get("Solana")),
    ]
    y = 112
    for name, icon, data in asset_rows:
        if not data:
            continue
        is_up  = data.get("arrow") == "▲"
        color  = (0, 220, 120) if is_up else (255, 75, 75) if data.get("arrow") == "▼" else (175, 200, 235)
        bg     = (0, 33, 16)   if is_up else (33, 7, 7)    if data.get("arrow") == "▼" else (13, 22, 48)
        draw.rectangle([rx-2, y-3, 1172, y+28], fill=bg)
        draw.text((rx,       y), f"{icon} {name}", font=f_medium, fill=(215, 230, 255))
        draw.text((rx+190,   y), data["price"],    font=f_medium, fill=(255, 255, 255))
        if data.get("chg") != "—":
            draw.text((rx+400, y), f"{data.get('arrow','')}{data.get('chg','')}", font=f_medium, fill=color)
        y += 40

    # ── Bottom bar ──
    draw.rectangle([0, H-50, W, H], fill=(0, 145, 75))
    draw.text((20,  H-36), "MGL NEWSROOM",                     font=f_large,  fill=(255, 255, 255))
    draw.text((380, H-32), "Хөрөнгө оруулалтын зөвлөгөө биш", font=f_small,  fill=(200, 240, 210))
    draw.text((840, H-32), "t.me/mglnewsroomfree",             font=f_medium, fill=(255, 255, 190))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    return buf.read()

# ── FACEBOOK POST ──────────────────────────────────────────────────────────────
def post_to_facebook(image_bytes, message):
    if not FB_PAGE_ID or not FB_ACCESS_TOKEN:
        print("[FB] Missing credentials!")
        return False
    try:
        url   = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
        files = {"source": ("post.jpg", image_bytes, "image/jpeg")}
        data  = {"access_token": FB_ACCESS_TOKEN, "message": message, "published": "true"}
        r     = requests.post(url, data=data, files=files, timeout=30)
        result = r.json()
        if "id" in result:
            print(f"[FB] ✅ Posted with image! ID: {result['id']}")
            return True
        # Fallback text only
        r2 = requests.post(
            f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed",
            data={"message": message, "access_token": FB_ACCESS_TOKEN}, timeout=15
        )
        if "id" in r2.json():
            print(f"[FB] ✅ Text only posted.")
            return True
        print(f"[FB ERROR] {result}")
        return False
    except Exception as e:
        print(f"[FB ERROR] {e}")
        return False

# ── TELEGRAM APPROVAL ──────────────────────────────────────────────────────────
def send_for_approval(image_bytes, post_text, stocks):
    state = load_json(FB_STATE_FILE, {})
    top   = stocks[0] if stocks else {}

    preview = (
        f"📱 <b>Facebook Post Preview</b>\n"
        f"📅 {now_ub().strftime('%Y.%m.%d %H:%M')} UB\n\n"
        f"📊 Топ хувьцаа: <b>{top.get('symbol','')}</b> "
        f"₮{top.get('price','')} {top.get('arrow','')+top.get('pct','')}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{post_text[:800]}..."
    )
    markup = {"inline_keyboard": [[
        {"text": "✅ Facebook-т нийтлэх", "callback_data": "fb_approve"},
        {"text": "❌ Алгасах",            "callback_data": "fb_skip"},
    ]]}

    if image_bytes:
        result = tg_send_photo(ADMIN_CHAT_ID, image_bytes, preview, markup)
    else:
        result = tg_send(ADMIN_CHAT_ID, preview, markup)

    state["pending"] = {
        "date":           now_ub().strftime("%Y-%m-%d"),
        "post_text":      post_text,
        "preview_msg_id": result.get("result", {}).get("message_id"),
    }
    save_json(FB_STATE_FILE, state)
    print("[FB] Preview sent to Telegram — waiting for your approval")

def handle_fb_updates(image_bytes):
    state  = load_json(FB_STATE_FILE, {})
    offset = state.get("tg_offset", 0)
    resp   = tg("getUpdates", {"offset": offset, "timeout": 5})

    for update in resp.get("result", []):
        offset = update["update_id"] + 1
        cb     = update.get("callback_query")

        # ONLY process fb_ callbacks — ignore everything else
        # This prevents interfering with bot.py's updates
        if not cb:
            state["tg_offset"] = offset
            continue

        data    = cb.get("data", "")
        cb_id   = cb["id"]
        chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))

        # Ignore non-fb callbacks completely — let bot.py handle them
        if not data.startswith("fb_"):
            state["tg_offset"] = offset
            continue

        if chat_id != str(ADMIN_CHAT_ID):
            continue

        if data == "fb_approve":
            pending   = state.get("pending", {})
            post_text = pending.get("post_text", "")
            tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": "✅ Нийтэлж байна..."})
            success = post_to_facebook(image_bytes, post_text)
            msg     = "✅ Facebook-т амжилттай нийтлэгдлээ!" if success else "❌ Facebook алдаа гарлаа!"
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

    stocks, index_val, market_cap = fetch_mse_data()
    assets    = fetch_assets()
    symbols   = [s["symbol"] for s in stocks[:5]]
    dividends = fetch_dividend_info(symbols)

    print(f"[FB] Stocks: {len(stocks)}, Index: {index_val}, Assets: {len(assets)}, Dividends: {len(dividends)}")

    image_bytes = generate_image(stocks, assets, index_val)
    print(f"[FB] Image: {'✅' if image_bytes else '❌'}")

    post_text = build_post_text(stocks, assets, index_val, market_cap, dividends)
    post_text = claude_enhance(post_text, stocks, assets)

    send_for_approval(image_bytes, post_text, stocks)

    # Wait up to 2 hours for approval
    deadline = time.time() + 7200
    while time.time() < deadline:
        result = handle_fb_updates(image_bytes)
        if result in ("posted", "skipped", "failed"):
            return
        time.sleep(15)

    tg_send(ADMIN_CHAT_ID, "⏰ Facebook пост 2 цагийн дотор зөвшөөрөгдөөгүй тул алгасагдлаа.")

def main():
    print("=" * 50)
    print("MGL Newsroom — Facebook Auto Poster")
    print(f"  FB Page : {FB_PAGE_ID or '❌ MISSING'}")
    print(f"  Token   : {'✅' if FB_ACCESS_TOKEN else '❌ MISSING'}")
    print(f"  Claude  : {'✅' if ANTHROPIC_KEY    else '❌ MISSING'}")
    print(f"  Google  : {'✅' if GOOGLE_TRANSLATE else '❌ MISSING'}")
    print(f"  Bot     : {'✅' if BOT_TOKEN      else '❌ MISSING'}")
    print("=" * 50)
    print("Posts at 15:30 UB daily after MSE closes.\n")

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