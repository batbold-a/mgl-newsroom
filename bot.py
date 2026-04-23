import feedparser
import requests
import time
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@mgl_newsroom")  # or the -100... number

RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.reuters.com/reuters/topNews",
    "https://rsshub.app/apnews/topics/apf-topnews",
]

SENT_FILE = "sent_articles.json"

def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE) as f:
            return set(json.load(f))
    return set()

def save_sent(sent):
    with open(SENT_FILE, "w") as f:
        json.dump(list(sent), f)

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})

def check_feeds():
    sent = load_sent()
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:5]:  # only latest 5 per feed
            if entry.id not in sent:
                message = f"<b>{entry.title}</b>\n\n{entry.link}"
                send_message(message)
                sent.add(entry.id)
                time.sleep(2)  # avoid spam
    save_sent(sent)

while True:
    print("Checking feeds...")
    check_feeds()
    time.sleep(600)  # check every 10 minutes
