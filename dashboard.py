"""
My Personal Business Dashboard — GitHub version (Gemini)
==========================================================
This version runs automatically on GitHub every morning:
- Uses Google Gemini's free API tier for the AI filtering.
- The API key is read from the repository's protected Secrets vault
  (GEMINI_API_KEY), never written in this file.
- The output is always written to index.html, which GitHub Pages
  serves as the website's homepage.
"""

import feedparser
import requests
import re
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo


def china_today():
    """Today's date in China time, so the 6am brief carries the right day."""
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()

# ── YOUR SETTINGS ─────────────────────────────────────────────────────────
# On GitHub, the API key comes from the repository's protected Secrets vault
# (Settings -> Secrets and variables -> Actions -> GEMINI_API_KEY).
API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "gemini-2.5-flash-lite:generateContent")


def ask_gemini(system, user_text, max_tokens=1500):
    """Send one request to Google Gemini and return its text reply."""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user_text}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    r = requests.post(
        GEMINI_URL,
        params={"key": API_KEY},
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

SEEN_FILE = "seen_links.json"

FEEDS = {
    "Business": [
        "https://www.china-briefing.com/feed",
        "https://www.chinadaily.com.cn/rss/china_rss.xml",
        "https://feeds.bbci.co.uk/news/world/asia/china/rss.xml",
        "https://technode.com/feed",
        "https://www.ghanaweb.com/GhanaHomePage/rss/business.xml",
        "https://www.myjoyonline.com/business/feed/",
    ],
    "Jobs": [
        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
        "https://remoteok.com/rss",
    ],
    "Learning": [
        "https://hnrss.org/frontpage",
        "https://www.bleepingcomputer.com/feed/",
    ],
}

KEYWORDS = {
    "Business": [
        "visa", "permit", "immigration", "foreigner", "expat", "resident",
        "business", "trade", "investment", "entrepreneur", "company", "market",
        "tariff", "ghana", "africa", "export", "customs", "solar", "supplier",
    ],
    "Jobs": [
        "customer service", "content", "coordinator", "teaching",
        "account manager", "virtual assistant", "support",
    ],
    "Learning": [
        "security", "breach", "vulnerability", "ai ", "cyber", "privacy",
    ],
}

BATCH_SYSTEM_PROMPTS = {
    "Business": """You screen articles for someone running a cross-border
business connecting China and Ghana/Africa trade. Relevant = foreign
work/visa access, business setup or trade rules, tariffs/customs changes,
or market/investment opportunities in China or Ghana/Africa.
Return ONLY a JSON array, one element per article in the same order.
Use null for irrelevant articles. For relevant ones use:
{"title": "short headline under 12 words", "category": "Business or Visa or Market", "summary": "1-2 sentences on why it matters"}""",

    "Jobs": """You screen remote job listings for someone who wants flexible
bridge income (customer service, content, coordination, account management,
teaching). Return ONLY a JSON array, one element per listing in order.
Use null for jobs that clearly don't match. For matches use:
{"title": "job title, under 12 words", "category": "Gig", "summary": "1 sentence: role + why it fits"}""",

    "Learning": """You screen tech/security articles for someone building
cybersecurity and AI skills as a long-term career move. Only pass through
genuinely significant items — be strict, most articles should be filtered out.
Return ONLY a JSON array, one element per article in order.
Use null for anything not significant. For significant ones use:
{"title": "short headline under 12 words", "category": "Learning", "summary": "1-2 sentences on why it matters"}""",
}

RECOMMEND_PROMPT = """Suggest exactly 3 items useful this week for someone
running a cross-border business connected to foreigners living in China:
- 1 business/negotiation book
- 1 online course or certification relevant to cross-border trade or China business
- 1 professional skill worth developing right now for this kind of business

Return ONLY a JSON array of 3 objects, no other text:
{"title": "name", "category": "Book or Course or Skill", "summary": "1-2 sentences why"}"""

# ── SEEN-LINKS CACHE ──────────────────────────────────────────────────────

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# ── FETCHING ──────────────────────────────────────────────────────────────

def fetch_new_articles(category, seen):
    """Pull unseen, keyword-matching articles for one category."""
    articles = []
    keywords = KEYWORDS.get(category, [])
    for feed_url in FEEDS[category]:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:15]:
                link = entry.get("link", "")
                if not link or link in seen:
                    continue
                title = entry.get("title", "")
                summary = re.sub("<[^<]+?>", "", entry.get("summary", ""))
                text = f"{title} {summary}".lower()
                if keywords and not any(k in text for k in keywords):
                    continue
                articles.append({"title": title, "summary": summary, "link": link})
        except Exception as e:
            print(f"Skipped a feed that failed ({feed_url}): {e}")
    return articles


def get_fx_rates():
    try:
        r = requests.get(
            "https://api.frankfurter.dev/v2/rates",
            params={"base": "USD", "quotes": "CNY,GHS"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("rates", {})
    except Exception as e:
        print(f"Couldn't fetch exchange rates: {e}")
        return None


# ── AI CLASSIFICATION (batched — cheaper and faster) ─────────────────────

def classify_batch(category, articles):
    if not articles:
        return []
    cards = []
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        chunk = articles[i:i + batch_size]
        numbered = "\n\n".join(
            f"[{j}] Title: {a['title']}\nSummary: {a['summary']}"
            for j, a in enumerate(chunk)
        )
        try:
            raw = ask_gemini(BATCH_SYSTEM_PROMPTS[category], numbered)
            raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()
            results = json.loads(raw)
        except Exception as e:
            print(f"Batch classify failed for {category}: {e}")
            continue

        for j, item in enumerate(results):
            if not item:
                continue
            cards.append({
                "title": item.get("title", chunk[j]["title"]),
                "category": item.get("category", category),
                "summary": item.get("summary", ""),
                "source": chunk[j]["link"],
            })
    return cards


def get_recommendation_cards():
    try:
        raw = ask_gemini("You are a helpful business advisor.", RECOMMEND_PROMPT, 500)
        raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE)
        items = json.loads(raw)
        for item in items:
            item["source"] = "Recommended for you"
        return items
    except Exception as e:
        print(f"Couldn't get recommendations: {e}")
        return []


# ── RENDERING ─────────────────────────────────────────────────────────────

CATEGORY_COLORS = {
    "Business": "#1F5C52", "Visa": "#3D4A7A", "Market": "#A6763A",
    "Gig": "#8C4A2F", "Learning": "#2E4057", "Book": "#5B6B3A",
    "Course": "#A6763A", "Skill": "#8C4A2F",
}


def render_card(card):
    accent = CATEGORY_COLORS.get(card["category"], "#6B6F76")
    return f"""
    <div class="card" style="border-left-color:{accent}">
      <p class="label" style="color:{accent}">{card['category']}</p>
      <p class="title">{card['title']}</p>
      <p class="summary">{card['summary']}</p>
      <p class="source">{card['source']}</p>
    </div>"""


def render_section(name, cards):
    if not cards:
        return ""
    cards_html = "\n".join(render_card(c) for c in cards)
    return f'<div class="section"><h2>{name}</h2><div class="rule"></div>{cards_html}</div>'


def render_fx_row(rates):
    if not rates:
        return ""
    parts = " &nbsp;/&nbsp; ".join(f"USD&rarr;{k} {v:.2f}" for k, v in rates.items())
    return f'<div class="ticker"><span class="ticker-label">Exchange</span>{parts}</div>'


def build_html(fx_rates, sections, rec_cards):
    body = render_section("Business & trade", sections["Business"])
    body += render_section("Jobs", sections["Jobs"])
    body += render_section("Learning & cybersecurity", sections["Learning"])
    body += render_section("This week's picks", rec_cards)
    if not body.strip():
        body = "<p style='color:#888'>Nothing new today — check back tomorrow.</p>"

    weekday_date = china_today().strftime("%A, %d %B %Y")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Daily brief — {china_today()}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#F7F6F2; --surface:#FFFFFF; --border:#E4E2DA;
    --ink:#1F2420; --slate:#6B6F76;
  }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:'Inter',-apple-system,Arial,sans-serif; background:var(--bg);
         color:var(--ink); margin:0; padding:56px 20px 80px; }}
  .container {{ max-width:640px; margin:0 auto; }}
  .masthead {{ text-align:center; margin-bottom:36px; }}
  .eyebrow {{ font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:0.12em;
             text-transform:uppercase; color:var(--slate); margin:0 0 10px; }}
  h1 {{ font-family:'Fraunces',serif; font-weight:600; font-size:34px; margin:0 0 8px; }}
  .dateline {{ font-family:'IBM Plex Mono',monospace; font-size:12px; color:var(--slate); margin:0; }}
  .ticker {{ background:var(--ink); color:#F4F2EC; font-family:'IBM Plex Mono',monospace;
            font-size:12px; padding:12px 20px; border-radius:6px; text-align:center;
            margin-bottom:40px; letter-spacing:0.02em; }}
  .ticker-label {{ text-transform:uppercase; letter-spacing:0.12em; opacity:0.6; margin-right:14px; }}
  .section {{ margin-bottom:36px; }}
  .section h2 {{ font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:0.1em;
                text-transform:uppercase; color:var(--slate); font-weight:500; margin:0 0 8px; }}
  .rule {{ height:1px; background:var(--border); margin-bottom:16px; }}
  .card {{ background:var(--surface); border:1px solid var(--border); border-left:3px solid;
          border-radius:4px; padding:18px 22px; margin-bottom:10px; }}
  .label {{ font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:0.08em;
           text-transform:uppercase; margin:0 0 6px; }}
  .title {{ font-weight:600; font-size:16px; margin:0 0 6px; color:var(--ink); }}
  .summary {{ font-size:14px; line-height:1.55; color:#454A44; margin:0 0 10px; }}
  .source {{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--slate); margin:0;
            word-break:break-all; }}
</style>
</head>
<body>
  <div class="container">
    <div class="masthead">
      <p class="eyebrow">Cross-border business briefing</p>
      <h1>Your daily brief</h1>
      <p class="dateline">{weekday_date}</p>
    </div>
    {render_fx_row(fx_rates)}
    {body}
  </div>
</body>
</html>"""


def main():
    seen = load_seen()

    sections = {}
    for category in FEEDS:
        print(f"Checking {category} feeds...")
        new_articles = fetch_new_articles(category, seen)
        sections[category] = classify_batch(category, new_articles)
        for a in new_articles:
            seen.add(a["link"])

    print("Getting this week's picks...")
    rec_cards = get_recommendation_cards()

    fx_rates = get_fx_rates()

    html = build_html(fx_rates, sections, rec_cards)
    filename = "index.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    save_seen(seen)
    print(f"Done. Open {filename} in your browser to see your dashboard.")


if __name__ == "__main__":
    main()
