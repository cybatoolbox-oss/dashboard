"""
My Personal Business Dashboard — v3
=====================================
What's new in v3:
- Two tabs: Tate and Ceecy, each with their own sections.
- Discovery engine: Gemini now searches the live web (grounded search)
  for Shenzhen happenings, rotating weekly hunts (business ideas, jobs
  with visas / remote, funded scholarships, Shenzhen events & fun),
  and Ceecy's daily creative-industry brief.
- New dark, cinematic design: big serif headlines, monospace labels,
  one warm accent color, atmospheric header, gentle fade-ins.
- A rotating grounding quote for Ceecy, costs zero AI calls.
- Everything fails gracefully: if a search or feed breaks, that
  section is skipped for the day instead of crashing the build.

Runs on GitHub Actions. API key comes from the GEMINI_API_KEY secret.
Output is always written to index.html for GitHub Pages.
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


# ── SETTINGS ──────────────────────────────────────────────────────────────
API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Fast, cheap model for sorting articles (no web access needed).
CLASSIFY_MODEL = "gemini-flash-lite-latest"
# Model used with live Google Search for the discovery sections.
SEARCH_MODEL = "gemini-flash-latest"

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent")

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
        "shenzhen",
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
business connecting China and Ghana/Africa trade, about to move to Shenzhen.
Relevant = foreign work/visa access, business setup or trade rules,
tariffs/customs changes, Shenzhen developments, or market/investment
opportunities in China or Ghana/Africa.
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

# The rotating weekly discovery hunts for Tate's tab (0=Monday ... 6=Sunday).
WEEKLY_HUNTS = {
    0: ("Business ideas & trends",
        """Search the web for what is trending RIGHT NOW in cross-border
business between China and Africa, e-commerce, and small-business
opportunities a foreigner in Shenzhen could realistically act on.
Find 3 concrete, current opportunities or trends people are talking about."""),
    1: ("Jobs & visa-friendly work",
        """Search the web for CURRENT job opportunities suited to an
English-speaking foreigner: either fully remote roles, or companies/programs
known to sponsor work visas (any country). Focus on customer success,
operations, content, account management, teaching. Find 3 promising,
current leads (companies hiring, platforms, or programs)."""),
    2: ("Funded study opportunities",
        """Search the web for currently open, FULLY FUNDED scholarships or
PhD/Masters programs (stipend + tuition covered) available to international
students — in China (CSC and university scholarships) or worldwide.
Find 3 that are open now or opening soon, with deadlines if known."""),
    3: ("Shenzhen events & fun",
        """Search the web for upcoming events in and around Shenzhen (also
Guangzhou/Hong Kong day-trip range): business expos, trade fairs, tech
meetups, plus fun things — markets, festivals, nightlife spots people rate
highly. Find 3-4 current or upcoming picks a young couple would enjoy."""),
    4: ("Business ideas & trends",
        """Search the web for what is trending RIGHT NOW in cross-border
business, e-commerce and side businesses with low startup costs that a
foreigner based in Shenzhen could act on. Find 3 concrete current ideas."""),
    5: ("Shenzhen events & fun",
        """Search the web for what's happening in Shenzhen THIS WEEKEND and
the coming week: expos, markets, meetups, festivals, and well-rated fun or
nightlife. Find 3-4 current picks for a young couple new to the city."""),
    6: ("Funded study opportunities",
        """Search the web for currently open, fully funded scholarships or
graduate programs for international students, in China or worldwide.
Find 3 that are open now, with deadlines if known."""),
}

SHENZHEN_DAILY_PROMPT = """Search the web for what is happening in Shenzhen
right now: local news that affects residents or foreigners, new policies,
big openings, and any notable events in the next few days. The reader is a
foreign couple about to move to Shenzhen. Find the 3 most useful items today."""

CEECY_PROMPT = """Search the web and produce today's brief for a creative
professional (design, content creation, branding, social media). Return
EXACTLY 4 items:
1. category "Industry" — one current happening in the design/content/influencer
   space worth knowing today.
2. category "Tools" — one new or newly-updated tool, bot, or AI agent for
   creative workflow or project management, and what it's good for.
3. category "Insight" — one short business insight about what clients are
   currently paying for in a creative niche.
4. category "Inspiration" — one competitor or inspiration account/studio/campaign
   of the day, summarized in 3-4 short bullet-like sentences.
"""

DISCOVERY_FORMAT = """
Return ONLY a JSON array of objects, no other text, each object:
{"title": "short punchy title under 12 words",
 "category": "one or two word label",
 "summary": "2-3 sentences, concrete and specific",
 "source": "the main source URL, or empty string"}
Only include real findings from the search results. If you can't verify
something is current, say so briefly in the summary."""

# Grounding quotes for Ceecy — rotated by day, zero AI cost.
QUOTES = [
    "Rest is part of the work, not a break from it.",
    "You don't have to be the best today. You have to show up today.",
    "Comparison is a thief; craft is a friend. Return to the craft.",
    "Small consistent days beat rare heroic ones.",
    "Your taste got you here. Trust it a little more.",
    "Done and shared beats perfect and hidden.",
    "The goal isn't to hustle harder — it's to build a life you don't need a vacation from.",
    "Creativity loves a calm nervous system. Breathe first.",
    "You are allowed to grow slowly and still be growing.",
    "Protect the hours when you feel most alive; spend them on what matters.",
    "Not every season is for harvest. Some are for planting.",
    "One honest piece of work today is enough.",
    "Drink water, stretch, then make the thing.",
    "The people you admire also doubted themselves this morning.",
]


# ── SEEN-LINKS CACHE ──────────────────────────────────────────────────────

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


# ── GEMINI HELPERS ────────────────────────────────────────────────────────

def ask_gemini(system, user_text, max_tokens=1500, model=None, grounded=False):
    """One request to Gemini. grounded=True lets it search the live web."""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user_text}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if grounded:
        body["tools"] = [{"google_search": {}}]
    url = GEMINI_URL.format(model=model or CLASSIFY_MODEL)
    r = requests.post(url, params={"key": API_KEY}, json=body, timeout=120)
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts).strip()


def parse_json_cards(raw):
    """Extract a JSON array of cards from a model reply."""
    raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    items = json.loads(raw)
    cards = []
    for item in items:
        if not item or not item.get("title"):
            continue
        cards.append({
            "title": str(item.get("title", "")).strip(),
            "category": str(item.get("category", "")).strip() or "Note",
            "summary": str(item.get("summary", "")).strip(),
            "source": str(item.get("source", "") or "").strip(),
        })
    return cards


def discovery_search(name, prompt):
    """Run one grounded web search and return cards. Never crashes the build."""
    try:
        raw = ask_gemini(
            "You are a sharp, honest research assistant. Use web search." ,
            prompt + DISCOVERY_FORMAT,
            max_tokens=2000, model=SEARCH_MODEL, grounded=True,
        )
        cards = parse_json_cards(raw)
        print(f"{name}: {len(cards)} card(s)")
        return cards
    except Exception as e:
        print(f"{name} search skipped: {e}")
        return []


# ── FEEDS ─────────────────────────────────────────────────────────────────

def fetch_new_articles(category, seen):
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
        cards = parse_json_cards(raw)
        for c in cards:
            c["source"] = ""
        return cards
    except Exception as e:
        print(f"Couldn't get recommendations: {e}")
        return []


def get_fx_rates():
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        r.raise_for_status()
        all_rates = r.json().get("rates", {})
        return {k: all_rates[k] for k in ("CNY", "GHS") if k in all_rates} or None
    except Exception as e:
        print(f"Couldn't fetch exchange rates: {e}")
        return None


# ── RENDERING ─────────────────────────────────────────────────────────────

def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_card(card):
    src = ""
    if card.get("source"):
        src = (f'<a class="source" href="{esc(card["source"])}" '
               f'target="_blank" rel="noopener">source &rarr;</a>')
    return f"""
      <article class="card">
        <p class="label">{esc(card['category'])}</p>
        <h3>{esc(card['title'])}</h3>
        <p class="summary">{esc(card['summary'])}</p>
        {src}
      </article>"""


def render_section(name, cards):
    if not cards:
        return ""
    return (f'<section class="block"><h2>{esc(name)}</h2>'
            f'<div class="grid">{"".join(render_card(c) for c in cards)}</div>'
            f'</section>')


def build_html(fx_rates, tate_sections, ceecy_cards, quote):
    today = china_today()
    weekday_date = today.strftime("%A, %d %B %Y")

    fx_html = ""
    if fx_rates:
        parts = ' <span class="dim">/</span> '.join(
            f"USD&rarr;{k} {v:.2f}" for k, v in fx_rates.items())
        fx_html = (f'<div class="ticker"><span class="ticker-label">Exchange'
                   f'</span>{parts}</div>')

    tate_html = fx_html
    for name, cards in tate_sections:
        tate_html += render_section(name, cards)
    if tate_html == fx_html and not fx_rates:
        tate_html = '<p class="empty">Nothing new today — check back tomorrow.</p>'

    ceecy_html = ""
    for name, cards in ceecy_cards:
        ceecy_html += render_section(name, cards)
    ceecy_html += (f'<section class="block quote-block">'
                   f'<h2>Stay grounded</h2>'
                   f'<blockquote>&ldquo;{esc(quote)}&rdquo;</blockquote></section>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily brief — {today}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:#0F110F; --surface:#171A17; --border:#262A25;
    --ink:#EDEBE4; --muted:#9A9E96; --accent:#E3B26A;
  }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ font-family:'Inter',-apple-system,sans-serif; background:var(--bg);
         color:var(--ink); padding-bottom:100px; }}
  a {{ color:var(--accent); text-decoration:none; }}

  .hero {{ position:relative; padding:110px 20px 70px; text-align:center;
          background:
            linear-gradient(180deg, rgba(15,17,15,.55) 0%, rgba(15,17,15,.92) 78%, var(--bg) 100%),
            url('https://images.unsplash.com/photo-1506905925346-21bda4d32df4?auto=format&fit=crop&w=1800&q=55')
            center 35%/cover no-repeat; }}
  .eyebrow {{ font-family:'IBM Plex Mono',monospace; font-size:11px;
             letter-spacing:.22em; text-transform:uppercase; color:var(--accent);
             margin-bottom:18px; }}
  h1 {{ font-family:'Fraunces',serif; font-weight:500; font-size:clamp(44px,7vw,84px);
       line-height:1.02; letter-spacing:-.01em; }}
  .dateline {{ font-family:'IBM Plex Mono',monospace; font-size:12px;
              color:var(--muted); margin-top:16px; letter-spacing:.06em; }}

  .tabs {{ display:flex; justify-content:center; gap:8px; margin:44px 0 8px; }}
  .tab {{ font-family:'IBM Plex Mono',monospace; font-size:12px; letter-spacing:.14em;
         text-transform:uppercase; color:var(--muted); background:none;
         border:1px solid var(--border); border-radius:999px; padding:10px 26px;
         cursor:pointer; transition:all .25s; }}
  .tab.active {{ color:var(--bg); background:var(--accent); border-color:var(--accent); }}
  .tab:hover:not(.active) {{ color:var(--ink); border-color:var(--muted); }}

  .container {{ max-width:760px; margin:0 auto; padding:26px 20px 0; }}
  .panel {{ display:none; }}
  .panel.active {{ display:block; }}

  .ticker {{ font-family:'IBM Plex Mono',monospace; font-size:12px;
            border:1px solid var(--border); border-radius:8px; padding:14px 20px;
            text-align:center; color:var(--ink); letter-spacing:.04em;
            margin-bottom:14px; background:var(--surface); }}
  .ticker-label {{ color:var(--accent); text-transform:uppercase;
                  letter-spacing:.18em; margin-right:16px; font-size:11px; }}
  .dim {{ color:var(--muted); }}

  .block {{ margin-top:44px; opacity:0; transform:translateY(14px);
           animation:rise .7s ease forwards; }}
  .block:nth-of-type(2) {{ animation-delay:.08s; }}
  .block:nth-of-type(3) {{ animation-delay:.16s; }}
  .block:nth-of-type(4) {{ animation-delay:.24s; }}
  @keyframes rise {{ to {{ opacity:1; transform:none; }} }}

  .block h2 {{ font-family:'IBM Plex Mono',monospace; font-size:12px;
              letter-spacing:.2em; text-transform:uppercase; color:var(--muted);
              padding-bottom:12px; border-bottom:1px solid var(--border);
              margin-bottom:18px; font-weight:500; }}
  .grid {{ display:grid; gap:12px; }}
  .card {{ background:var(--surface); border:1px solid var(--border);
          border-radius:10px; padding:22px 24px; transition:border-color .25s; }}
  .card:hover {{ border-color:var(--accent); }}
  .label {{ font-family:'IBM Plex Mono',monospace; font-size:10px;
           letter-spacing:.16em; text-transform:uppercase; color:var(--accent);
           margin-bottom:10px; }}
  .card h3 {{ font-family:'Fraunces',serif; font-weight:500; font-size:21px;
             line-height:1.25; margin-bottom:8px; }}
  .summary {{ font-size:14px; line-height:1.65; color:#C7C9C0; }}
  .source {{ display:inline-block; margin-top:12px;
            font-family:'IBM Plex Mono',monospace; font-size:11px;
            letter-spacing:.06em; }}
  .empty {{ color:var(--muted); text-align:center; margin-top:60px; }}

  .quote-block blockquote {{ font-family:'Fraunces',serif; font-size:24px;
    font-weight:400; line-height:1.5; color:var(--ink); padding:8px 4px 0;
    font-style:italic; }}
</style>
</head>
<body>
  <header class="hero">
    <p class="eyebrow">Cross-border business briefing</p>
    <h1>Your daily brief</h1>
    <p class="dateline">{weekday_date} &middot; Shenzhen edition</p>
    <div class="tabs">
      <button class="tab active" onclick="show('tate', this)">Tate</button>
      <button class="tab" onclick="show('ceecy', this)">Ceecy</button>
    </div>
  </header>

  <main class="container">
    <div id="tate" class="panel active">{tate_html}</div>
    <div id="ceecy" class="panel">{ceecy_html}</div>
  </main>

<script>
function show(id, btn) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body>
</html>"""


# ── MAIN ──────────────────────────────────────────────────────────────────

def main():
    seen = load_seen()
    today = china_today()

    # 1. Feed-based sections (cheap, ungrounded)
    feed_sections = {}
    for category in FEEDS:
        print(f"Checking {category} feeds...")
        new_articles = fetch_new_articles(category, seen)
        feed_sections[category] = classify_batch(category, new_articles)
        for a in new_articles:
            seen.add(a["link"])

    print("Getting this week's picks...")
    rec_cards = get_recommendation_cards()

    # 2. Discovery engine (grounded web search)
    shenzhen_cards = discovery_search("Shenzhen today", SHENZHEN_DAILY_PROMPT)
    hunt_name, hunt_prompt = WEEKLY_HUNTS[today.weekday()]
    hunt_cards = discovery_search(f"Hunt: {hunt_name}", hunt_prompt)
    ceecy_raw_cards = discovery_search("Ceecy brief", CEECY_PROMPT)

    # 3. Assemble
    fx_rates = get_fx_rates()
    quote = QUOTES[today.toordinal() % len(QUOTES)]

    tate_sections = [
        ("Shenzhen today", shenzhen_cards),
        ("News & visas", feed_sections.get("Business", [])),
        (f"Discovery &middot; {hunt_name}", hunt_cards),
        ("Jobs", feed_sections.get("Jobs", [])),
        ("Learning & cybersecurity", feed_sections.get("Learning", [])),
        ("This week's picks", rec_cards),
    ]
    ceecy_cards = [("Today's creative brief", ceecy_raw_cards)]

    html = build_html(fx_rates, tate_sections, ceecy_cards, quote)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    save_seen(seen)
    print("Done. Open index.html in your browser to see your dashboard.")


if __name__ == "__main__":
    main()
