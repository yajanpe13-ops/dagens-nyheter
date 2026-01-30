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
# 1. NYHETSKÄLLOR
# ==================================================
FEEDS = [
    "https://www.svt.se/nyheter/rss.xml",
    "https://www.dn.se/m/rss/",
    "https://sverigesradio.se/rss.xml",
    "https://www.di.se/rss/",
    "https://www.affarsvarlden.se/rss",
    "https://www.svt.se/nyheter/inrikes/rss.xml",
    "https://www.dn.se/nyheter/utrikes/m/rss/",
    "https://sverigesradio.se/rss/ekot/utrikes",
    "https://omni.se/rss/inrikes",
    "https://omni.se/rss/utrikes",
    "https://omni.se/rss/ekonomi",
]

LOW_PRIORITY_SOURCES = ["aftonbladet", "expressen"]

# ==================================================
# 2. ÄMNEN (HÅRDA + MJUKA SIGNALER – VIKTIGA NYHETER)
# ==================================================
KEYWORDS = {
    "Ekonomi": {
        "hard": {
            "styrränta": 5, "räntebesked": 5,
            "inflation": 4, "recession": 5,
            "finanskris": 5, "centralbank": 4,
            "statsbudget": 4, "skattehöjning": 4
        },
        "soft": {
            "bnp": 2, "börs": 2,
            "arbetslöshet": 2,
            "krona": 1
        }
    },

    "Krig / Säkerhet": {
        "hard": {
            "krig": 6, "invasion": 6,
            "flyganfall": 6, "missilattack": 6,
            "terrorattack": 6,
            "mobilisering": 5,
            "undantagstillstånd": 5,
            "kärnvapen": 6
        },
        "soft": {
            "militär": 2,
            "frontlinje": 2,
            "eskalering": 3,
            "vapenvila": 2
        }
    },

    "Utrikes / Geopolitik": {
        "hard": {
            "usa": 4, "kina": 4,
            "ryssland": 5, "ukraina": 5,
            "israel": 5, "iran": 5,
            "nato": 5, "sanktioner": 5,
            "eu-toppmöte": 4
        },
        "soft": {
            "utrikesminister": 2,
            "fredssamtal": 2,
            "allierade": 2,
            "utrikespolitik": 2
        }
    },

    "Politik / Stat": {
        "hard": {
            "regeringskris": 6,
            "misstroende": 6,
            "statsminister": 5,
            "val": 5,
            "undantagslag": 6,
            "statskupp": 6
        },
        "soft": {
            "riksdag": 2,
            "minister": 2,
            "utredning": 1
        }
    }
}

# ==================================================
# HÅRDA NYHETSORD (ALLTID VIKTIGT)
# ==================================================
HARD_NEWS_WORDS = [
    "krig", "invasion", "terrorattack",
    "flyganfall", "missil",
    "kärnvapen", "mobilisering",
    "undantagstillstånd",
    "sanktioner", "nato",
    "styrränta", "räntebesked",
    "regeringskris", "statskupp"
]

# ==================================================
# 3. SPORT- & CLICKBAIT-BLOCK
# ==================================================
SPORT_WORDS = [
    "fotboll", "match", "mål", "vann", "förlorade", "föll",
    "premier league", "champions league", "allsvenskan",
    "arsenal", "united", "chelsea", "liverpool",
    "aik", "djurgården", "malmö ff",
    "hockey", "shl", "nhl", "tennis", "basket"
]

CLICKBAIT_WORDS = [
    "så", "därför", "här är", "lista", "bilder",
    "du måste", "chock", "otroliga", "avslöjar"
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
    if "media_content" in entry:
        for m in entry.media_content:
            if "url" in m:
                return m["url"]

    if "media_thumbnail" in entry:
        for m in entry.media_thumbnail:
            if "url" in m:
                return m["url"]

    if "enclosures" in entry:
        for e in entry.enclosures:
            if "image" in e.get("type", ""):
                return e.get("href", "")

    html_block = entry.get("summary", "")
    match = re.search(r'<img[^>]+src="([^"]+)"', html_block)
    if match:
        return match.group(1)

    return ""

def importance_score(text):
    score = 0
    has_hard = False
    categories = set()

    for cat, groups in KEYWORDS.items():
        for w, v in groups["hard"].items():
            if w in text:
                score += v
                has_hard = True
                categories.add(cat)
        for w, v in groups["soft"].items():
            if w in text:
                score += v
                categories.add(cat)

    return score, has_hard, list(categories)

def remove_duplicates(articles):
    """Tar bort dubletter baserat på titel och länk"""
    seen_titles = set()
    seen_links = set()
    unique_articles = []

    for a in articles:
        title_key = a["title"].strip().lower()
        link_key = a["link"].strip().lower()

        if title_key in seen_titles or link_key in seen_links:
            continue

        seen_titles.add(title_key)
        seen_links.add(link_key)
        unique_articles.append(a)

    return unique_articles

# ==================================================
# 5. HÄMTA & FILTRERA ARTIKLAR
# ==================================================
articles = []
one_week_ago = datetime.now() - timedelta(days=1)

for url in FEEDS:
    feed = feedparser.parse(url)

    for entry in feed.entries:
        try:
            pub_dt = parsedate_to_datetime(entry.get("published", ""))
            pub_dt = pub_dt.replace(tzinfo=None)
        except Exception:
            continue

        if pub_dt < one_week_ago:
            continue

        title = entry.title.lower()

        if any(cb in title for cb in CLICKBAIT_WORDS):
            continue

        raw_body = ""
        if "content" in entry:
            raw_body = " ".join(c.get("value", "") for c in entry.content)
        elif "summary" in entry:
            raw_body = entry.summary

        text = (title + " " + raw_body).lower()

        if any(sw in text for sw in SPORT_WORDS):
            continue

        if not any(hw in text for hw in HARD_NEWS_WORDS):
            continue

        score, has_hard, categories = importance_score(text)

        if not has_hard and score < 4:
            continue

        if any(src in entry.link.lower() for src in LOW_PRIORITY_SOURCES):
            if score < 6:
                continue

        if not categories:
            continue

        articles.append({
            "title": entry.title,
            "description": clean_text(raw_body),
            "link": entry.link,
            "date": pub_dt.strftime("%Y-%m-%d"),
            "image": extract_image(entry),
            "categories": categories,
            "score": score
        })

# ==================================================
# 5b. TA BORT DUBLETTER
# ==================================================
articles = remove_duplicates(articles)


# ==================================================
# 6. SORTERA & BEGRÄNSA (artikel en gång per kategori)
# ==================================================
MAX_PER_CATEGORY = 5
final = {cat: [] for cat in KEYWORDS}
assigned_articles = set()  # håller koll på vilka artiklar som redan används

for art in sorted(articles, key=lambda x: x["score"], reverse=True):
    # Välj kategori där artikeln har mest "hard"-poäng
    best_cat = None
    best_score = -1
    for cat in art["categories"]:
        hard_score = sum(KEYWORDS[cat]["hard"].get(w,0) for w in art["title"].lower().split() + art["description"].lower().split())
        if hard_score > best_score:
            best_score = hard_score
            best_cat = cat

    if best_cat is None:
        continue

    # Om artikeln redan lagts till (titel) så hoppa över
    title_key = art["title"].strip().lower()
    if title_key in assigned_articles:
        continue

    if len(final[best_cat]) < MAX_PER_CATEGORY:
        final[best_cat].append(art)
        assigned_articles.add(title_key)




# ==================================================
# 7. BYGG HTML I MINNET
# ==================================================
today = datetime.now().strftime("%Y-%m-%d")

html_content = f"""
<html><head><meta charset="utf-8">
<title>Viktiga Nyheter – {today}</title>
<style>
body {{ font-family: Arial; background:#f4f6f8; padding:20px }}
.article {{ background:white; padding:15px; border-radius:8px; margin-bottom:20px }}
h2 {{ border-bottom:3px solid #2c7be5 }}
.date {{ color:#777; font-size:0.85em }}
img {{ max-width:100%; border-radius:8px; margin-bottom:10px }}
</style></head><body>
<h1>DAGENS VIKTIGASTE NYHETER – {today}</h1>
"""

for cat, items in final.items():
    if not items:
        continue
    html_content += f"<h2>{cat}</h2>"
    for a in items:
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

print("✅ HTML klar i minnet")



# ==================================================
# 9. SKICKA E-POST (NYTT MAIL VARJE GÅNG)
# -------------------------------
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
TO_ADDRESS = ["yajanpe13@gmail.com", "franziska.hauer2005@gmail.com"]

msg = MIMEMultipart("alternative")

msg["Subject"] = f"Dagens nyheter – {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
msg["From"] = EMAIL_ADDRESS
msg["To"] = ", ".join(TO_ADDRESS)
msg["Message-ID"] = f"<{datetime.now().timestamp()}@dagensnyheter>"
msg.add_header("X-Unique-ID", str(datetime.now().timestamp()))

html = html_content.replace("\xa0", " ")  # använd HTML-strängen som redan finns i minnet
msg.attach(MIMEText(html, "html", "utf-8"))

try:
    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    server.sendmail(EMAIL_ADDRESS, TO_ADDRESS, msg.as_string())
    server.quit()
    print("✅ Nytt mail skickat: Dagens nyheter")
except Exception as e:
    print("❌ Misslyckades:", e)









