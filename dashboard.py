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


def render_card(card, featured=False):
    src = ""
    if card.get("source"):
        src = ('<a class="source" href="' + esc(card["source"]) +
               '" target="_blank" rel="noopener">Source'
               '<svg width="11" height="11" viewBox="0 0 12 12" fill="none">'
               '<path d="M3.5 8.5L8.5 3.5M8.5 3.5H4.5M8.5 3.5V7.5" '
               'stroke="currentColor" stroke-width="1.2" stroke-linecap="round" '
               'stroke-linejoin="round"/></svg></a>')
    cls = "card featured" if featured else "card"
    return ('<article class="' + cls + ' reveal">'
            '<span class="label">' + esc(card["category"]) + '</span>'
            '<h3>' + esc(card["title"]) + '</h3>'
            '<p class="summary">' + esc(card["summary"]) + '</p>'
            + src + '</article>')


def render_section(name, cards, lead=False):
    if not cards:
        return ""
    count = str(len(cards))
    inner = ""
    for i, c in enumerate(cards):
        inner += render_card(c, featured=(lead and i == 0))
    return ('<section class="block reveal">'
            '<div class="section-head"><h2>' + name + '</h2>'
            '<span class="count">' + count + '</span></div>'
            '<div class="grid">' + inner + '</div></section>')


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily brief — %%DATE%%</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#030712;
    --card:rgba(15,23,42,.45);
    --card-border:rgba(255,255,255,.05);
    --border:rgba(255,255,255,.06);
    --ink:#F8FAFC; --body:#B4BAC6; --muted:#64748B;
    --accent:#f59e0b; --accent-dim:rgba(245,158,11,.05);
    --accent-glow:rgba(245,158,11,.08);
  }
  body.ceecy-mode {
    --accent:#14b8a6; --accent-dim:rgba(20,184,166,.05);
    --accent-glow:rgba(20,184,166,.08);
  }
  * { box-sizing:border-box; margin:0; }
  html { scroll-behavior:smooth; }
  body {
    font-family:'Geist',-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--ink); padding-bottom:120px;
    overflow-x:hidden; -webkit-font-smoothing:antialiased;
    transition:color .3s;
  }
  a { color:var(--accent); text-decoration:none; transition:opacity .2s; }
  a:hover { opacity:.8; }
  a:focus-visible,.tab:focus-visible { outline:2px solid var(--accent);
    outline-offset:3px; border-radius:6px; }
  .mono { font-family:'JetBrains Mono',monospace; }

  /* ── Header ──────────────────────────────────────────────────── */
  .hero { position:relative; text-align:center; padding:108px 20px 56px;
          overflow:hidden; }
  .hero::before { content:""; position:absolute; inset:0; pointer-events:none;
    background:radial-gradient(600px 320px at 50% -8%, var(--accent-glow), transparent 70%),
               radial-gradient(900px 460px at 50% -18%, rgba(148,163,184,.05), transparent 75%);
    transition:background .5s; }
  .hero-inner { position:relative; }
  .eyebrow { font-family:'JetBrains Mono',monospace; font-size:11px;
             letter-spacing:.14em; text-transform:uppercase; color:var(--muted);
             margin-bottom:18px; display:inline-flex; align-items:center; gap:9px; }
  .eyebrow::before { content:""; width:5px; height:5px; border-radius:50%;
                     background:var(--accent); box-shadow:0 0 10px var(--accent);
                     transition:background .3s, box-shadow .3s; }
  h1 { font-weight:600; font-size:clamp(38px,5.4vw,58px); line-height:1.06;
       letter-spacing:-0.03em; color:var(--ink); }
  .dateline { font-family:'JetBrains Mono',monospace; font-size:12px;
              color:var(--muted); margin-top:14px; letter-spacing:.02em; }
  .dateline .clock { color:var(--accent); transition:color .3s; }

  /* Segmented control */
  .tabs { display:inline-flex; position:relative; margin-top:36px;
          background:rgba(255,255,255,.04); border:1px solid var(--border);
          border-radius:999px; padding:4px; }
  .tab-indicator { position:absolute; top:4px; bottom:4px; width:calc(50% - 4px);
    left:4px; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.08);
    border-radius:999px; transition:transform .35s cubic-bezier(.4,0,.2,1);
    box-shadow:0 1px 8px rgba(0,0,0,.35); }
  body.ceecy-mode .tab-indicator,
  .tabs.pos-1 .tab-indicator { transform:translateX(100%); }
  .tab { position:relative; z-index:1; font-family:'Geist',sans-serif;
         font-size:13.5px; font-weight:500; letter-spacing:-.01em;
         color:var(--muted); background:none; border:none; border-radius:999px;
         padding:8px 34px; cursor:pointer; transition:color .3s; }
  .tab.active { color:var(--ink); }

  /* ── FX ticker ───────────────────────────────────────────────── */
  .marquee { border-top:1px solid var(--border); border-bottom:1px solid var(--border);
             background:rgba(255,255,255,.015); overflow:hidden; padding:10px 0;
             mask-image:linear-gradient(90deg,transparent,#000 8%,#000 92%,transparent); }
  .marquee-track { display:inline-flex; white-space:nowrap; align-items:center;
                   animation:scroll 42s linear infinite; }
  .metric { display:inline-flex; align-items:center; gap:8px; margin:0 26px;
            font-family:'JetBrains Mono',monospace; font-size:11.5px;
            letter-spacing:.02em; color:var(--body); }
  .metric .pair { color:var(--muted); }
  .metric .val { color:var(--ink); font-weight:500; }
  .metric .dot { width:4px; height:4px; border-radius:50%; background:var(--accent);
                 transition:background .3s; }
  @keyframes scroll { to { transform:translateX(-50%); } }

  /* ── Content ─────────────────────────────────────────────────── */
  .container { max-width:720px; margin:0 auto; padding:52px 20px 0; }
  .panel { display:none; }
  .panel.active { display:block; animation:panein .4s ease; }
  @keyframes panein { from { opacity:0; transform:translateY(8px); } }

  .block { margin-top:52px; }
  .section-head { display:flex; align-items:center; justify-content:space-between;
                  padding-bottom:12px; border-bottom:1px solid var(--border);
                  margin-bottom:16px; }
  .block h2 { font-size:13px; font-weight:600; letter-spacing:-.01em;
              color:var(--ink); }
  .count { font-family:'JetBrains Mono',monospace; font-size:11px;
           color:var(--muted); background:rgba(255,255,255,.04);
           border:1px solid var(--border); border-radius:6px; padding:2px 8px; }
  .grid { display:grid; gap:12px; }

  .card { position:relative; background:var(--card);
          border:1px solid var(--card-border); border-radius:12px;
          padding:22px 24px; overflow:hidden;
          transition:box-shadow .3s, border-color .3s, transform .3s; }
  .card::before { content:""; position:absolute; inset:0; opacity:0;
    transition:opacity .3s;
    background:radial-gradient(360px circle at var(--mx,50%) var(--my,50%),
      var(--accent-glow), transparent 45%); }
  .card:hover { transform:translateY(-2px); border-color:rgba(255,255,255,.1);
    box-shadow:0 4px 30px rgba(0,0,0,.4), inset 0 1px 0 rgba(255,255,255,.05); }
  .card:hover::before { opacity:1; }
  .card > * { position:relative; }
  .card.featured { padding:28px; background:var(--accent-dim);
                   border-color:rgba(255,255,255,.07); }
  .card.featured h3 { font-size:clamp(21px,3vw,27px); letter-spacing:-.025em; }
  .label { display:inline-block; font-family:'JetBrains Mono',monospace;
           font-size:10px; font-weight:500; letter-spacing:.1em;
           text-transform:uppercase; color:var(--accent);
           background:var(--accent-dim); border:1px solid var(--card-border);
           border-radius:5px; padding:3px 8px; margin-bottom:12px;
           transition:color .3s, background .3s; }
  .card h3 { font-size:17px; font-weight:600; letter-spacing:-.02em;
             line-height:1.35; margin-bottom:7px; }
  .summary { font-size:14px; line-height:1.65; color:var(--body);
             letter-spacing:-.005em; }
  .source { display:inline-flex; align-items:center; gap:5px; margin-top:14px;
            font-family:'JetBrains Mono',monospace; font-size:11px;
            letter-spacing:.02em; }
  .empty { color:var(--muted); text-align:center; margin-top:60px; font-size:14px; }

  /* Quote */
  .quote-block blockquote { border-left:2px solid var(--accent);
    padding:6px 0 6px 22px; font-size:19px; font-weight:400; line-height:1.6;
    letter-spacing:-.015em; color:var(--body); transition:border-color .3s; }

  .reveal { opacity:0; transform:translateY(12px);
            transition:opacity .6s ease, transform .6s ease; }
  .reveal.in { opacity:1; transform:none; }

  @media (prefers-reduced-motion: reduce) {
    .marquee-track { animation:none; }
    .reveal { opacity:1; transform:none; transition:none; }
    .tab-indicator { transition:none; }
  }
  @media (max-width:560px) {
    .hero { padding:76px 16px 44px; }
    .card { padding:18px; }
    .tab { padding:8px 24px; }
  }
</style>
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <p class="eyebrow">早报 &middot; Cross-border briefing</p>
      <h1>Your daily brief</h1>
      <p class="dateline">%%WEEKDAY%% &middot; Shenzhen edition &middot; <span class="clock" id="szclock"></span></p>
      <div class="tabs" id="tabs">
        <div class="tab-indicator"></div>
        <button class="tab active" onclick="show('tate', this)">Tate</button>
        <button class="tab" onclick="show('ceecy', this)">Ceecy</button>
      </div>
    </div>
  </header>

  %%MARQUEE%%

  <main class="container">
    <div id="tate" class="panel active">%%TATE%%</div>
    <div id="ceecy" class="panel">%%CEECY%%</div>
  </main>

<script>
function show(id, btn) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  document.body.classList.toggle('ceecy-mode', id === 'ceecy');
  observeAll();
}
function tick() {
  const t = new Intl.DateTimeFormat('en-GB', { timeZone:'Asia/Shanghai',
    hour:'2-digit', minute:'2-digit', second:'2-digit' }).format(new Date());
  const el = document.getElementById('szclock');
  if (el) el.textContent = t + ' SZT';
}
setInterval(tick, 1000); tick();
let obs;
function observeAll() {
  if (!('IntersectionObserver' in window)) {
    document.querySelectorAll('.reveal').forEach(el => el.classList.add('in'));
    return;
  }
  obs = obs || new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); obs.unobserve(e.target); }
  }), { threshold: .1 });
  document.querySelectorAll('.reveal:not(.in)').forEach(el => obs.observe(el));
}
observeAll();
document.addEventListener('pointermove', e => {
  const card = e.target.closest('.card');
  if (!card) return;
  const r = card.getBoundingClientRect();
  card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
  card.style.setProperty('--my', (e.clientY - r.top) + 'px');
});
</script>
</body>
</html>"""


def build_html(fx_rates, tate_sections, ceecy_cards, quote):
    today = china_today()
    weekday_date = today.strftime("%A, %d %B %Y")

    marquee = ""
    if fx_rates:
        items = "".join(
            '<span class="metric"><span class="dot"></span>'
            '<span class="pair">USD/' + k + '</span>'
            '<span class="val">' + ("%.2f" % v) + '</span></span>'
            for k, v in fx_rates.items())
        items += ('<span class="metric"><span class="dot"></span>'
                  '<span class="pair">早安</span>'
                  '<span class="val">Good morning, Shenzhen</span></span>')
        marquee = ('<div class="marquee"><div class="marquee-track">'
                   + items + items + items + items + '</div></div>')

    tate_html = ""
    for i, (name, cards) in enumerate(tate_sections):
        tate_html += render_section(name, cards, lead=(i == 0))
    if not tate_html:
        tate_html = '<p class="empty">Nothing new today. Check back tomorrow.</p>'

    ceecy_html = ""
    for name, cards in ceecy_cards:
        ceecy_html += render_section(name, cards)
    ceecy_html += ('<section class="block quote-block reveal">'
                   '<div class="section-head"><h2>Stay grounded</h2></div>'
                   '<blockquote>' + esc(quote) + '</blockquote></section>')

    return (HTML_TEMPLATE
            .replace("%%DATE%%", str(today))
            .replace("%%WEEKDAY%%", weekday_date)
            .replace("%%MARQUEE%%", marquee)
            .replace("%%TATE%%", tate_html)
            .replace("%%CEECY%%", ceecy_html))


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
