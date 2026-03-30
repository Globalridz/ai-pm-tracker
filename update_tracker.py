"""
AI PM Tracker — Auto-update script
Runs weekly via GitHub Actions (every Monday 9am UTC).

Sources:
  1. Releasebot       — Official Anthropic + OpenAI release notes (free)
  2. Reddit           — r/ClaudeAI, r/OpenAI, r/ChatGPT etc. (free .json endpoint)
  3. Twitter/X        — Builder handles via Nitter public mirror (free, no API key)
  4. The Neuron       — theneurondaily.com newsletter archive (free)

Claude reads all sources and writes:
  - Release cards (title, desc, PM insight, tags)
  - Reddit takes (top community reactions)
  - Builder tweets (high-engagement posts)
  - Monthly narrative (strategic theme)

Requires: ANTHROPIC_API_KEY in GitHub secrets
Cost: ~$1-2/month
"""

import json, os, re, datetime, time
import urllib.request, urllib.parse
import anthropic

# ── Config ──────────────────────────────────────────────────────────────────

RELEASES_JSON = "releases.json"

RELEASEBOT = {
    "claude": "https://releasebot.io/updates/anthropic/claude",
    "openai":  "https://releasebot.io/updates/openai",
}

# Reddit subreddits to scan per brand
SUBREDDITS = {
    "claude": ["ClaudeAI", "Anthropic", "artificial", "ProductManagement"],
    "openai": ["OpenAI", "ChatGPT", "artificial", "ProductManagement"],
}

# Twitter handles to monitor per brand
HANDLES = {
    "claude": ["bcherny", "mikeyk", "felixrieseberg", "DarioAmodei", "lydiahallie", "amorriscode"],
    "openai": ["sama", "gdb", "npew", "romainhuet", "DanielEdrisian", "OpenAI"],
}

# Public Nitter instances (Twitter mirrors, no API key)
NITTER = ["https://nitter.net", "https://nitter.privacydev.net", "https://nitter.poast.org"]

NEURON_URL = "https://www.theneurondaily.com/newsletter/"

UA = {"User-Agent": "AI-PM-Tracker/1.0 (github; non-commercial research)"}

# ── Fetch helpers ─────────────────────────────────────────────────────────

def fetch_text(url, timeout=15):
    """Fetch URL, strip HTML, return plain text."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        text = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", text).strip()[:12000]
    except Exception as e:
        print(f"    ⚠️  {url[:60]}: {e}")
        return ""

def fetch_json(url, timeout=12):
    """Fetch URL as JSON dict."""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        print(f"    ⚠️  {url[:60]}: {e}")
        return None

def claude(prompt, max_tokens=4000):
    """Call Claude API, return text."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

def parse_json(raw):
    """Strip markdown fences, parse JSON."""
    raw = re.sub(r"```json|```", "", raw).strip()
    try:
        return json.loads(raw)
    except:
        return []

def now_month():
    return datetime.datetime.utcnow().strftime("%b").lower()

def now_year():
    return datetime.datetime.utcnow().year

# ── Source 1: Releasebot ─────────────────────────────────────────────────

def get_releasebot(brand):
    print(f"  Releasebot ({brand})...")
    return fetch_text(RELEASEBOT[brand])

# ── Source 2: Reddit ────────────────────────────────────────────────────

def get_reddit(brand):
    """
    Reddit's public .json endpoint works without any API key.
    Returns top posts from this week across relevant subreddits.
    """
    print(f"  Reddit ({brand})...")
    query = "claude OR anthropic" if brand == "claude" else "openai OR chatgpt OR codex"
    posts = []

    for sub in SUBREDDITS[brand][:3]:
        url = (f"https://www.reddit.com/r/{sub}/search.json"
               f"?q={urllib.parse.quote(query)}&sort=top&t=week&limit=5")
        data = fetch_json(url)
        time.sleep(1.5)  # Polite rate limiting
        if data and "data" in data:
            for p in data["data"]["children"]:
                d = p["data"]
                posts.append({
                    "sub": f"r/{sub}",
                    "score": d.get("score", 0),
                    "title": d.get("title", ""),
                    "text": d.get("selftext", "")[:400],
                    "comments": d.get("num_comments", 0),
                })

    posts.sort(key=lambda x: x["score"], reverse=True)
    print(f"    Got {len(posts)} posts")
    return posts[:8]

# ── Source 3: Twitter/X via Nitter ──────────────────────────────────────

def get_tweets(brand):
    """
    Fetch recent tweets from key handles via Nitter (public Twitter mirror).
    No API key required. Falls back through multiple Nitter instances.
    """
    print(f"  Tweets ({brand})...")
    all_tweets = []

    for nitter_base in NITTER:
        working = False
        for handle in HANDLES[brand][:4]:
            url = f"{nitter_base}/{handle}"
            text = fetch_text(url, timeout=10)
            time.sleep(0.5)

            if text and len(text) > 200:
                # Nitter renders tweets as text — extract meaningful chunks
                chunks = [c.strip() for c in text.split("tweet-content") if len(c.strip()) > 40]
                for chunk in chunks[:3]:
                    clean = chunk[:280].strip()
                    if clean:
                        all_tweets.append({"handle": handle, "text": clean})
                working = True

        if working:
            print(f"    Got {len(all_tweets)} tweets via {nitter_base}")
            break
        else:
            print(f"    {nitter_base} unreachable, trying next...")

    return all_tweets[:10]

# ── Source 4: The Neuron ────────────────────────────────────────────────

def get_neuron():
    print("  The Neuron newsletter...")
    return fetch_text(NEURON_URL)

# ── Claude tasks ─────────────────────────────────────────────────────────

def extract_releases(releasebot_text, brand, existing_titles):
    month, year = now_month(), now_year()
    prompt = f"""Update an AI PM Release Tracker. Brand: {brand.upper()}

Releasebot source text:
---
{releasebot_text[:7000]}
---

Already tracked (skip these):
{json.dumps(existing_titles)}

Extract ONLY new releases from {month.upper()} {year}.

Return JSON array, each item:
{{"title":"Short name max 60 chars","date":"Apr 7","day":7,
  "desc":"2-3 factual sentences about what shipped.",
  "pmInsight":"2-3 sentences: strategic PM take — build vs buy? roadmap signal? pricing shift? platform play?",
  "tags":["2-4 from: models,agents,computer-use,automation,developer-tools,enterprise,consumer,platform,MCP,ecosystem,integrations,security,productivity,mobile,reasoning,pricing,cost-efficiency,safety,trust,distribution,expansion,growth,retention,personalization,UX-innovation,real-time,long-context,flagship,frontier,research-preview,deprecation,go-to-market"],
  "signal":null,"isSignal":false}}

signal: null=shipped, "signal"=leak/intel, "confirmed"=announced-not-shipped
Return ONLY valid JSON array, empty [] if nothing new."""

    result = parse_json(claude(prompt))
    releases = result if isinstance(result, list) else []
    for r in releases:
        r["brand"] = brand
        r["month"] = month
    print(f"    → {len(releases)} new {brand} releases")
    return releases

def extract_reddit_takes(posts, brand, existing_quotes):
    if not posts:
        return []
    prompt = f"""Curate Reddit reactions for an AI PM Release Tracker. Brand: {brand.upper()}

Top Reddit posts this week:
{json.dumps(posts)}

Already tracked quotes (skip duplicates):
{json.dumps(existing_quotes[:15])}

Pick the 3 most insightful posts revealing PM-relevant user reactions:
adoption patterns, pain points, competitive comparisons, strategic insights.

Return JSON array:
{{"sub":"r/ClaudeAI","votes":"▲ 2.4k","quote":"Faithful quote max 200 chars",
  "topic":"keyword-tag · another-tag","sentiment":"pos","pct":85,"emoji":"🔥"}}

Return ONLY valid JSON array, empty [] if nothing good."""

    result = parse_json(claude(prompt, max_tokens=2000))
    takes = result if isinstance(result, list) else []
    for t in takes:
        t["brand"] = brand
    print(f"    → {len(takes)} new {brand} Reddit takes")
    return takes

def extract_tweets(raw_tweets, brand, existing_texts):
    if not raw_tweets:
        return []
    prompt = f"""Curate builder tweets for an AI PM Release Tracker. Brand: {brand.upper()}

Recent tweets from team members:
{json.dumps(raw_tweets)}

Already tracked (skip):
{json.dumps(existing_texts[:8])}

Pick 2 most PM-relevant tweets — strategy, feature announcements, or team insights.

Return JSON array:
{{"name":"Boris Cherny","handle":"@bcherny · Apr 7",
  "text":"Clean tweet text max 280 chars",
  "stats":"💬 200🔁 400❤️ 3k👁 800k",
  "url":"https://x.com/bcherny"}}

Estimate engagement if unavailable. Return ONLY valid JSON array, empty [] if nothing good."""

    result = parse_json(claude(prompt, max_tokens=1500))
    tweets = result if isinstance(result, list) else []
    for t in tweets:
        t["brand"] = brand
    print(f"    → {len(tweets)} new {brand} tweets")
    return tweets

def generate_narrative(month_releases, neuron_text):
    month_name = datetime.datetime.utcnow().strftime("%B")
    year = now_year()
    if not month_releases:
        return None

    prompt = f"""Write a monthly narrative for an AI PM Release Tracker (100+ PM audience).

{month_name} {year} releases:
{json.dumps([r['title'] + ': ' + r['desc'] for r in month_releases])}

The Neuron newsletter context (framing only, do not copy):
---
{neuron_text[:2500]}
---

Return JSON:
{{"headline":"{month_name} was the month... (max 12 words, punchy)",
  "body":"3-4 sentences. Strategic theme? What changed for PMs? Competitive signal? Be direct.",
  "stats":[{{"num":"23","label":"Releases shipped"}},{{"num":"2","label":"Key theme"}},{{"num":"97M","label":"Stat"}},{{"num":"18","label":"Active days"}}],
  "tags":["🤖 Theme one","🔗 Theme two","💰 Theme three"]}}

Use real numbers from releases where possible. Return ONLY valid JSON."""

    result = parse_json(claude(prompt, max_tokens=1200))
    if isinstance(result, dict) and "headline" in result:
        print(f"    → {result['headline'][:60]}")
        return result
    return None

# ── Main ──────────────────────────────────────────────────────────────────

def main():
    month, year = now_month(), now_year()
    print(f"\n🚀 AI PM Tracker — {month.upper()} {year}")
    print(f"   {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 50)

    with open(RELEASES_JSON) as f:
        data = json.load(f)

    existing_titles = [r["title"] for r in data["releases"]]
    existing_quotes = [r.get("quote","") for r in data.get("reddit",[])]
    existing_texts  = [t.get("text","")[:80] for t in data.get("tweets",[])]
    changed = False

    # Fetch all sources
    print("\n📡 Fetching sources...")
    rel_claude  = get_releasebot("claude")
    rel_openai  = get_releasebot("openai")
    neuron      = get_neuron()
    reddit_cl   = get_reddit("claude")
    reddit_oa   = get_reddit("openai")
    tweets_cl   = get_tweets("claude")
    tweets_oa   = get_tweets("openai")

    # Extract releases
    print("\n🔍 Extracting releases...")
    new_rel = extract_releases(rel_claude, "claude", existing_titles)
    time.sleep(3)
    new_rel += extract_releases(rel_openai, "openai", existing_titles)

    if new_rel:
        data["releases"].extend(new_rel)
        changed = True

    # Extract Reddit takes
    print("\n💬 Extracting Reddit takes...")
    new_reddit = extract_reddit_takes(reddit_cl, "claude", existing_quotes)
    time.sleep(2)
    new_reddit += extract_reddit_takes(reddit_oa, "openai", existing_quotes)

    if new_reddit:
        data["reddit"] = (new_reddit + data.get("reddit", []))[:20]
        changed = True

    # Extract tweets
    print("\n🐦 Extracting tweets...")
    new_tweets = extract_tweets(tweets_cl, "claude", existing_texts)
    time.sleep(2)
    new_tweets += extract_tweets(tweets_oa, "openai", existing_texts)

    if new_tweets:
        data["tweets"] = (new_tweets + data.get("tweets", []))[:12]
        changed = True

    # Update narrative
    print(f"\n✍️  Updating narrative...")
    month_rels = [r for r in data["releases"] if r["month"] == month]
    if month_rels and neuron:
        narrative = generate_narrative(month_rels, neuron)
        if narrative:
            data.setdefault("narratives", {})[month] = narrative
            changed = True

    # Save
    if changed:
        data["meta"]["lastUpdated"] = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        with open(RELEASES_JSON, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Updated releases.json")
        print(f"   Releases: {len(data['releases'])}")
        print(f"   Tweets:   {len(data.get('tweets',[]))}")
        print(f"   Reddit:   {len(data.get('reddit',[]))}")
        print(f"   🚀 Vercel deploys in ~30 seconds")
    else:
        print(f"\n✅ No changes this week")

if __name__ == "__main__":
    main()
