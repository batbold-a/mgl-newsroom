# ═══════════════════════════════════════════════════════════
# PASTE THIS INTO bot.py — REPLACE your 3 fetch functions:
#   fetch_mse_top10()
#   fetch_global_stocks()
#   fetch_assets()
# ═══════════════════════════════════════════════════════════

def fetch_mse_top10():
    """Fetch top 10 MSE stocks — tries 2 sources."""
    import re

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
                "symbol": symbol,
                "price":  curr.strip(),
                "change": change.strip(),
                "pct":    pct.strip(),
                "arrow":  "▲" if not change.strip().startswith("-") else "▼",
            })
        if stocks:
            print(f"[MSE] ✅ Got {len(stocks)} stocks from bbe.mn")
            return stocks[:10]
    except Exception as e:
        print(f"[MSE] bbe.mn failed: {e}")

    # Source 2: mse.mn API fallback
    try:
        r = requests.get("https://mse.mn/api/v1/market/top",
                         timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        stocks = []
        for item in (data.get("data") or data)[:10]:
            change = float(item.get("change", 0) or 0)
            stocks.append({
                "symbol": item.get("symbol", ""),
                "price":  str(item.get("close") or item.get("price", "N/A")),
                "change": str(change),
                "pct":    f"{abs(change):.2f}%",
                "arrow":  "▲" if change >= 0 else "▼",
            })
        if stocks:
            print(f"[MSE] ✅ Got {len(stocks)} stocks from mse.mn fallback")
            return stocks[:10]
    except Exception as e:
        print(f"[MSE] mse.mn fallback failed: {e}")

    print("[MSE] ⚠️ Both sources failed — returning empty")
    return []


def fetch_global_stocks():
    """Fetch S&P 500, NASDAQ, Apple, Nvidia — with fallback."""
    stocks = {}
    symbols = {
        "S&P 500": "^GSPC",
        "NASDAQ":  "^IXIC",
        "Apple":   "AAPL",
        "Nvidia":  "NVDA",
    }

    for name, sym in symbols.items():
        # Try Yahoo Finance v8
        try:
            r = requests.get(
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

        # Fallback: Yahoo Finance v7
        try:
            r = requests.get(
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
    """Fetch crypto + metals + forex with fallback APIs — no more N/A."""
    assets = {}

    # ── CRYPTO: CoinGecko first, CoinCap fallback ──────────────────────────
    crypto_ids = {
        "bitcoin":     "Bitcoin",
        "ethereum":    "Ethereum",
        "binancecoin": "BNB",
        "ripple":      "XRP",
        "solana":      "Solana",
    }

    coingecko_ok = False
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,binancecoin,ripple,solana"
            "&vs_currencies=usd&include_24hr_change=true",
            timeout=12
        )
        d = r.json()
        for key, name in crypto_ids.items():
            if key in d and d[key].get("usd"):
                price = d[key]["usd"]
                chg   = d[key].get("usd_24h_change", 0)
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

    # CoinCap fallback if CoinGecko failed
    if not coingecko_ok:
        coincap_ids = {
            "bitcoin":  "Bitcoin",
            "ethereum": "Ethereum",
            "solana":   "Solana",
        }
        for cid, name in coincap_ids.items():
            try:
                r = requests.get(
                    f"https://api.coincap.io/v2/assets/{cid}", timeout=10
                )
                d = r.json().get("data", {})
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

    # ── METALS: metals.live first, gold-api fallback ───────────────────────
    metals = [("Алт", "gold"), ("Мөнгө", "silver"), ("Платин", "platinum")]

    for metal_name, symbol in metals:
        fetched = False

        # Source 1: metals.live
        try:
            r = requests.get(
                f"https://api.metals.live/v1/spot/{symbol}", timeout=10
            )
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

        # Source 2: frankfurter/gold fallback for gold only
        if not fetched and symbol == "gold":
            try:
                r = requests.get(
                    "https://api.coingecko.com/api/v3/simple/price"
                    "?ids=tether-gold&vs_currencies=usd",
                    timeout=10
                )
                price = r.json().get("tether-gold", {}).get("usd")
                if price:
                    assets[metal_name] = {
                        "price": f"${float(price):,.2f}/oz",
                        "chg":   "—",
                        "arrow": "—",
                    }
                    fetched = True
            except Exception:
                pass

        if not fetched:
            print(f"[METALS] ⚠️ {metal_name} both sources failed")

    # ── FOREX: exchangerate-api first, frankfurter fallback ───────────────
    forex_ok = False
    try:
        r     = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD", timeout=10
        )
        rates = r.json().get("rates", {})
        if rates.get("MNT"):
            assets["USD/MNT"] = {
                "price": f"₮{rates['MNT']:,.0f}",
                "chg":   "—",
                "arrow": "—",
            }
            forex_ok = True
        if rates.get("CNY"):
            assets["USD/CNY"] = {
                "price": f"¥{rates['CNY']:.4f}",
                "chg":   "—",
                "arrow": "—",
            }
    except Exception as e:
        print(f"[FOREX] exchangerate-api failed: {e}")

    # Frankfurter fallback (no MNT but has CNY at least)
    if not forex_ok:
        try:
            r     = requests.get(
                "https://api.frankfurter.app/latest?from=USD&to=CNY",
                timeout=10
            )
            rates = r.json().get("rates", {})
            if rates.get("CNY"):
                assets["USD/CNY"] = {
                    "price": f"¥{rates['CNY']:.4f}",
                    "chg":   "—",
                    "arrow": "—",
                }
        except Exception as e:
            print(f"[FOREX] frankfurter fallback failed: {e}")

    print(f"[ASSETS] ✅ Total fetched: {len(assets)} assets")
    return assets