import feedparser
import re
import html
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

# ==================================================
# 1. NYHETSKÄLLOR (KVALITET + UTRIKES)
# ==================================================
FEEDS = [
    "https://www.svt.se/nyheter/rss.xml",
    "https://www.svt.se/nyheter/utrikes/rss.xml",
    "https://www.dn.se/nyheter/utrikes/m/rss/",
    "https://sverigesradio.se/rss/ekot/utrikes",
    "https://omni.se/rss/utrikes",
    "https://omni.se/rss/ekonomi",
    "https://www.di.se/rss/",
]

LOW_PRIORITY_SOURCES = ["aftonbladet", "expressen"]

# ==================================================
# 2. VIKTIGA ÄMNEN (HÅRDA + MJUKA)
# ==================================================
KEYWORDS = {
    "Krig / Säkerhet": {
        "hard": {
            "krig": 6, "invasion": 6, "flyganfall": 6,
            "missil": 6, "terrorattack": 6,
            "kärnvapen": 6, "mobilisering": 5,
            "undantagstillstånd": 5
        },
        "soft": {
            "militär": 2, "eskalering": 3,
            "frontlinje": 2, "vapenvila": 2
        }
    },

    "Utrikes / Geopolitik": {
        "hard": {
            "usa": 4, "kina": 4, "ryssland": 5,
            "ukraina": 5, "israel": 5, "iran": 5,
            "nato": 5, "sanktioner": 5
        },
        "soft": {
            "utrikesminister": 2,
            "fredssamtal": 2,
            "allierade": 2
        }
    },

    "Ekonomi": {
        "hard": {
            "styrränta": 5, "räntebesked": 5,
            "inflation": 4, "recession": 5,
            "finanskris": 5, "centralbank": 4
        },
        "soft": {
            "bnp": 2, "börs": 2,
            "arbetslöshet": 2
        }
    },

    "Politik / Stat": {
        "hard": {
            "regeringskris": 6,
            "misstroende": 6,
            "statsminister": 5,
            "val": 5,
            "statskupp": 6
        },
        "soft": {
            "riksdag": 2,
            "minister": 2
        }
    }
}

# ==================================================
# 3. BLOCKERINGAR
# ==================================================
SPORT_WORDS = [
    "fotboll", "match", "mål", "premier league",
    "allsvenskan", "nhl", "shl", "tennis"
]

CLICKBAIT_WORDS = [
    "så", "därför", "här är", "lista",
    "bilder", "du måste", "chock"
]

# ==================================================
# 4. HJÄLPFUNKTIONER
# ==================================================
def clean_text(raw, max_len=600):
    txt = re.sub("<[^<]+?>", "", raw)
    txt = html.unescape(txt)
    txt = txt.replace("\n", " ").strip()
    return txt[:max_len] + ("..." if len(txt) > max_len else "")

def extract_image(entry):
    # 1. media_content / media_thumbnail
    for key in ["media_content", "media_thumbnail"]:
        if key in entry:
            for m in entry[key]:
                if "url" in m:
                    return m["url"]

    # 2. enclosures
    if "enclosures" in entry:
        for e in entry.enclosures:
            if "image" in e.get("type", ""):
                return e.get("href", "")

    # 3. Sök i summary/content HTML
    html_block = entry.get("summary", "") + " " + " ".join(c.get("value","") for c in entry.get("content", []))
    match = re.search(r'<img[^>]+src="([^"]+)"', html_block)
    if match:
        return match.group(1)

    return ""

def importance_score(text):
    score = 0
    categories = set()

    for cat, groups in KEYWORDS.items():
        for w, v in groups["hard"].items():
            if w in text:
                score += v
                categories.add(cat)
        for w, v in groups["soft"].items():
            if w in text:
                score += v
                categories.add(cat)

    return score, list(categories)

# ==================================================
# 5. HÄMTA & FILTRERA
# ==================================================
articles = []
cutoff = datetime.now() - timedelta(days=1)

for url in FEEDS:
    feed = feedparser.parse(url)

    for entry in feed.entries:
        try:
            pub = parsedate_to_datetime(entry.get("published", ""))
            pub = pub.replace(tzinfo=None)
        except Exception:
            continue

        if pub < cutoff:
            continue

        title = entry.title.lower()

        if any(cb in title for cb in CLICKBAIT_WORDS):
            continue

        raw_body = entry.get("summary", "")
        text = (title + " " + raw_body).lower()

        if any(sw in text for sw in SPORT_WORDS):
            continue

        score, categories = importance_score(text)

        # 🔑 Huvudregel: viktiga nyheter = score
        if score < 5:
            continue

        if any(src in entry.link.lower() for src in LOW_PRIORITY_SOURCES):
            if score < 6:
                continue

        articles.append({
            "title": entry.title,
            "description": clean_text(raw_body),
            "link": entry.link,
            "date": pub.strftime("%Y-%m-%d"),
            "image": extract_image(entry),
            "categories": categories,
            "score": score
        })

# ==================================================
# 6. SORTERA & BEGRÄNSA
# ==================================================
articles.sort(key=lambda x: x["score"], reverse=True)

MAX_TOTAL = 20
articles = articles[:MAX_TOTAL]

# ==================================================
# 7. BYGG HTML
# ==================================================
today = datetime.now().strftime("%Y-%m-%d")

html_content = f"""
<html><head><meta charset="utf-8">
<title>Viktiga Nyheter – {today}</title>
<style>
body {{ font-family: Arial; background:#f4f6f8; padding:20px }}
.article {{ background:white; padding:15px; border-radius:8px; margin-bottom:20px }}
.date {{ color:#777; font-size:0.85em }}
img {{ max-width:100%; border-radius:8px; margin-bottom:10px }}
</style></head><body>
<h1>DAGENS VIKTIGASTE NYHETER – {today}</h1>
"""

for a in articles:
    html_content += f"""
<div class="article">
<div class="date">{a['date']} • vikt {a['score']}</div>
<h3>{a['title']}</h3>
{"<img src='"+a['image']+"'>" if a['image'] else ""}
<p>{a['description']}</p>
<a href="{a['link']}">Läs mer</a>
</div>
"""

html_content += "</body></html>"

# ==================================================
# 8. SKICKA MAIL
# ==================================================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
TO_ADDRESS = ["yajanpe13@gmail.com"]

msg = MIMEMultipart("alternative")
msg["Subject"] = f"Dagens viktigaste nyheter – {today}"
msg["From"] = EMAIL_ADDRESS
msg["To"] = ", ".join(TO_ADDRESS)

msg.attach(MIMEText(html_content, "html", "utf-8"))

server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
server.starttls()
server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
server.sendmail(EMAIL_ADDRESS, TO_ADDRESS, msg.as_string())
server.quit()

print("✅ Mail skickat med viktiga nyheter")

