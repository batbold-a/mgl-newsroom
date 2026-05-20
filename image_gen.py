"""
MGL Newsroom — Image Generator
================================
Generates signature branded infographic for Facebook posts.
Uses HTML + Playwright to render professional images.

Install: pip install playwright && playwright install chromium
"""

import asyncio
import io
import os
from datetime import datetime, timezone, timedelta

UB_OFFSET = timedelta(hours=8)

def now_ub():
    return datetime.now(timezone.utc) + UB_OFFSET

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
    "QPAY": "QPay ХК",
    "SHV":  "Шивээ-Овоо",
    "TDB":  "ХХБанк",
    "TTL":  "Тавантолгой",
    "XAC":  "ХАС Банк",
}

def build_html(stocks, assets, index_val):
    ub       = now_ub()
    date_str = ub.strftime("%Y.%m.%d")
    day_names = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
    day_mn   = day_names[ub.weekday()]

    # Find max pct for bar scaling
    def parse_pct(s):
        try:
            return abs(float(s.get("pct","0").replace("%","").replace("-","").replace("+","").strip()))
        except:
            return 0

    max_pct = max((parse_pct(s) for s in stocks), default=1) or 1

    # Build stock rows
    stock_rows = ""
    for s in stocks[:10]:
        is_up   = s["arrow"] == "▲"
        color   = "#00C878" if is_up else "#FF4444"
        bg      = "rgba(0,200,120,0.08)" if is_up else "rgba(255,68,68,0.08)"
        pct_val = parse_pct(s)
        bar_w   = max(4, int((pct_val / max_pct) * 120))
        pct_str = s["pct"].replace("-","").replace("+","")
        name    = COMPANY_NAMES.get(s["symbol"], s["symbol"])
        arrow   = "▲" if is_up else "▼"

        stock_rows += f"""
        <div class="stock-row" style="background:{bg}">
            <div class="stock-left">
                <span class="stock-symbol">{s["symbol"]}</span>
                <span class="stock-name">{name}</span>
            </div>
            <div class="stock-mid">
                <div class="bar-track">
                    <div class="bar-fill" style="width:{bar_w}px;background:{color}"></div>
                </div>
            </div>
            <div class="stock-right">
                <span class="stock-price">₮{s["price"]}</span>
                <span class="stock-pct" style="color:{color}">{arrow}{pct_str}</span>
            </div>
        </div>"""

    # Build assets
    asset_rows = ""
    asset_map = [
        ("₿", "Bitcoin",  assets.get("Bitcoin")),
        ("Ξ", "Ethereum", assets.get("Ethereum")),
        ("Au", "Алт",     assets.get("Алт")),
        ("Ag", "Мөнгө",   assets.get("Мөнгө")),
        ("$",  "USD/MNT", assets.get("USD/MNT")),
        ("¥",  "USD/CNY", assets.get("USD/CNY")),
    ]
    for icon, name, data in asset_map:
        if not data:
            continue
        is_up  = data.get("arrow") == "▲"
        is_dn  = data.get("arrow") == "▼"
        color  = "#00C878" if is_up else "#FF4444" if is_dn else "#8BA3C7"
        chg    = data.get("chg","")
        arrow  = data.get("arrow","")
        chg_str = f"{arrow}{chg}" if chg and chg != "—" else ""

        asset_rows += f"""
        <div class="asset-row">
            <div class="asset-icon">{icon}</div>
            <div class="asset-info">
                <span class="asset-name">{name}</span>
                <span class="asset-price">{data["price"]}</span>
            </div>
            <span class="asset-chg" style="color:{color}">{chg_str}</span>
        </div>"""

    # Gainers and losers count
    gainers = sum(1 for s in stocks if s["arrow"] == "▲")
    losers  = sum(1 for s in stocks if s["arrow"] == "▼")
    idx_str = f"TOP-20: {index_val}" if index_val else "МХБ"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@300;400;500;600;700&display=swap');

  * {{ margin:0; padding:0; box-sizing:border-box; }}

  body {{
    width: 1200px;
    height: 630px;
    background: #080E26;
    font-family: 'Inter', sans-serif;
    overflow: hidden;
    position: relative;
  }}

  /* Background grid pattern */
  body::before {{
    content: '';
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,200,120,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,200,120,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
  }}

  /* Green left accent */
  .accent-left {{
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 5px;
    background: linear-gradient(180deg, #00C878, #00897B);
  }}

  /* Top bar */
  .top-bar {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 28px 14px 28px;
    border-bottom: 1px solid rgba(0,200,120,0.2);
  }}

  .brand {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}

  .brand-dot {{
    width: 10px; height: 10px;
    background: #00C878;
    border-radius: 50%;
    box-shadow: 0 0 8px #00C878;
  }}

  .brand-name {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 22px;
    letter-spacing: 3px;
    color: #FFFFFF;
  }}

  .brand-sub {{
    font-size: 11px;
    color: #8BA3C7;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}

  .top-right {{
    text-align: right;
  }}

  .date-label {{
    font-size: 13px;
    color: #8BA3C7;
    letter-spacing: 1px;
  }}

  .date-main {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 20px;
    color: #FFFFFF;
    letter-spacing: 2px;
  }}

  /* Main content */
  .content {{
    display: flex;
    padding: 16px 24px;
    gap: 20px;
    height: 520px;
  }}

  /* LEFT — stocks */
  .left-col {{
    flex: 1.4;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}

  .col-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }}

  .col-title {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 16px;
    letter-spacing: 2px;
    color: #00C878;
  }}

  .market-stats {{
    display: flex;
    gap: 10px;
    font-size: 11px;
  }}

  .stat-up {{ color: #00C878; font-weight: 600; }}
  .stat-dn {{ color: #FF4444; font-weight: 600; }}

  .stock-row {{
    display: flex;
    align-items: center;
    padding: 5px 8px;
    border-radius: 6px;
    gap: 8px;
    border: 1px solid rgba(255,255,255,0.03);
  }}

  .stock-left {{
    width: 140px;
    flex-shrink: 0;
  }}

  .stock-symbol {{
    font-size: 13px;
    font-weight: 700;
    color: #FFFFFF;
    display: block;
    letter-spacing: 0.5px;
  }}

  .stock-name {{
    font-size: 9px;
    color: #8BA3C7;
    display: block;
    margin-top: 1px;
  }}

  .stock-mid {{
    flex: 1;
  }}

  .bar-track {{
    height: 4px;
    background: rgba(255,255,255,0.06);
    border-radius: 2px;
    overflow: hidden;
  }}

  .bar-fill {{
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s;
  }}

  .stock-right {{
    width: 110px;
    text-align: right;
    flex-shrink: 0;
  }}

  .stock-price {{
    font-size: 12px;
    font-weight: 600;
    color: #D4E3FF;
    display: block;
  }}

  .stock-pct {{
    font-size: 11px;
    font-weight: 700;
    display: block;
  }}

  /* Divider */
  .divider {{
    width: 1px;
    background: linear-gradient(180deg, transparent, rgba(0,200,120,0.3), transparent);
    margin: 0 4px;
  }}

  /* RIGHT — assets */
  .right-col {{
    flex: 0.7;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}

  .asset-row {{
    display: flex;
    align-items: center;
    padding: 7px 10px;
    background: rgba(255,255,255,0.02);
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.04);
    gap: 10px;
  }}

  .asset-icon {{
    width: 30px; height: 30px;
    background: rgba(0,200,120,0.1);
    border: 1px solid rgba(0,200,120,0.2);
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    font-weight: 700;
    color: #00C878;
    flex-shrink: 0;
  }}

  .asset-info {{
    flex: 1;
  }}

  .asset-name {{
    font-size: 10px;
    color: #8BA3C7;
    display: block;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}

  .asset-price {{
    font-size: 13px;
    font-weight: 600;
    color: #FFFFFF;
    display: block;
  }}

  .asset-chg {{
    font-size: 11px;
    font-weight: 700;
    flex-shrink: 0;
  }}

  /* Index badge */
  .index-badge {{
    margin-top: auto;
    padding: 10px 14px;
    background: rgba(0,200,120,0.08);
    border: 1px solid rgba(0,200,120,0.2);
    border-radius: 10px;
    text-align: center;
  }}

  .index-label {{
    font-size: 10px;
    color: #8BA3C7;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}

  .index-value {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 28px;
    color: #00C878;
    letter-spacing: 1px;
    display: block;
    line-height: 1;
  }}

  /* Bottom bar */
  .bottom-bar {{
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 36px;
    background: linear-gradient(90deg, rgba(0,200,120,0.15), rgba(0,137,123,0.1));
    border-top: 1px solid rgba(0,200,120,0.2);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
  }}

  .bottom-left {{
    font-size: 11px;
    color: #8BA3C7;
    letter-spacing: 1px;
  }}

  .bottom-center {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 14px;
    letter-spacing: 3px;
    color: #00C878;
  }}

  .bottom-right {{
    font-size: 10px;
    color: #8BA3C7;
  }}

  .live-dot {{
    display: inline-block;
    width: 6px; height: 6px;
    background: #00C878;
    border-radius: 50%;
    margin-right: 5px;
    box-shadow: 0 0 6px #00C878;
  }}
</style>
</head>
<body>
  <div class="accent-left"></div>

  <!-- Top bar -->
  <div class="top-bar">
    <div class="brand">
      <div class="brand-dot"></div>
      <div>
        <div class="brand-name">MGL NEWSROOM</div>
        <div class="brand-sub">Mongolian Stock Exchange Daily</div>
      </div>
    </div>
    <div class="top-right">
      <div class="date-label">{day_mn}</div>
      <div class="date-main">{date_str}</div>
    </div>
  </div>

  <!-- Main content -->
  <div class="content">

    <!-- Left: Stocks -->
    <div class="left-col">
      <div class="col-header">
        <span class="col-title">МХБ — ӨДРИЙН ТОП 10</span>
        <div class="market-stats">
          <span class="stat-up">▲ {gainers} өсөлт</span>
          <span class="stat-dn">▼ {losers} уналт</span>
        </div>
      </div>
      {stock_rows}
    </div>

    <div class="divider"></div>

    <!-- Right: Assets -->
    <div class="right-col">
      <div class="col-header">
        <span class="col-title">ДЭЛХИЙН ЗАХ ЗЭЭЛ</span>
      </div>
      {asset_rows}

      <!-- Index -->
      <div class="index-badge">
        <span class="index-label">{idx_str}</span>
        <span class="index-value">{index_val or "—"}</span>
        <span style="font-size:10px;color:#8BA3C7;">нэгж</span>
      </div>
    </div>

  </div>

  <!-- Bottom bar -->
  <div class="bottom-bar">
    <span class="bottom-left"><span class="live-dot"></span>mse.mn | t.me/mglnewsroomfree</span>
    <span class="bottom-center">МХБ АРИЛЖААНЫ ТОЙМ</span>
    <span class="bottom-right">Хөрөнгө оруулалтын зөвлөгөө биш</span>
  </div>

</body>
</html>"""


async def html_to_image(html: str) -> bytes:
    """Render HTML to image using Playwright."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page    = await browser.new_page(viewport={"width": 1200, "height": 630})
        await page.set_content(html, wait_until="networkidle")
        await asyncio.sleep(1)  # wait for fonts
        screenshot = await page.screenshot(type="jpeg", quality=95)
        await browser.close()
        return screenshot


def generate_image(stocks, assets, index_val) -> bytes:
    """Generate MGL Newsroom branded image."""
    try:
        html = build_html(stocks, assets, index_val)
        return asyncio.run(html_to_image(html))
    except Exception as e:
        print(f"[IMAGE] Error: {e}")
        return None
