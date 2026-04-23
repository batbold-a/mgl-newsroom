# MGL Newsroom Bot

Automated Telegram news bot for Mongolian investors.
Posts curated business, finance, and mining news to paid and free channels.

---

## Channels

| Channel | Purpose |
|---------|---------|
| Paid channel | Full posts in English + Mongolian with analysis label |
| Free channel | Mongolian teaser only — drives paid upgrades |

---

## Weekly Schedule

| Day | Content type |
|-----|-------------|
| Monday | 📊 Weekly market outlook |
| Tuesday | 🌅 Daily snapshot |
| Wednesday | ⛏️ Mining & commodities update |
| Thursday | 💡 Personal finance insight |
| Friday | 📋 Weekly recap + preview |
| Breaking news | 🚨 Sent immediately any day |

---

## News Sources

**Mongolian:**
- montsame.mn — national news agency
- news.mn
- ikon.mn

**Global:**
- Reuters Business
- Reuters Markets
- Bloomberg Markets
- TechCrunch
- Mining.com (key for Mongolia)

---

## Environment Variables (set in Railway)

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | From @BotFather |
| `PAID_CHANNEL` | e.g. @mgl_newsroom |
| `FREE_CHANNEL` | e.g. @mgl_newsroom_free |
| `ADMIN_CHAT_ID` | Your personal Telegram ID (from @userinfobot) |
| `TRANSLATE_API_KEY` | Google Cloud Translation API key |

---

## How Approval Works

Every article found is sent to your personal Telegram with 4 buttons:

- ✅ **Approve both** — posts English to paid channel + Mongolian teaser to free channel
- 🇬🇧 **EN only** — posts English to paid channel only
- 🇲🇳 **MN only** — posts Mongolian to both channels
- ❌ **Skip** — discards the article

---

## Deploy to Railway

1. Push this repo to GitHub
2. Connect GitHub repo to Railway
3. Add all environment variables in Railway → Variables
4. Railway auto-deploys and runs 24/7

---

## Legal Disclaimer

Every Mongolian post automatically includes:
> ⚠️ Энэхүү мэдээлэл нь хөрөнгө оруулалтын зөвлөгөө биш.
> (This information is not investment advice.)
