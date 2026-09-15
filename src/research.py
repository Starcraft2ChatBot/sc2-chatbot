"""Lightweight topic research for chat replies (no extra pip deps).

Uses public HTTP endpoints:
  - Google News RSS (recent events — primary for news queries)
  - Wikipedia search + REST summary (factual background)
  - Google Fact Check Explorer (contested claims)
  - DuckDuckGo Lite + HTML (general web fallback)
  - bible-api.com (scripture when the query looks like a verse)

Research is triggered by a *scoring* system rather than a single substring
match. Signals considered:
  - explicit trigger substrings (config)
  - direct questions
  - factual claims
  - disputes ("you're wrong", "cap", "source?")
  - escalation (same topic repeats in the per-player history)

Query building extracts entities from the question so that complex
questions like "What happened to that guy that killed that ukrainian
woman on the train" become searchable queries like
"ukrainian woman train stabbing charlotte".
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sc2_chatbot.research")

_USER_AGENT = (
    "Mozilla/5.0 (compatible; SC2ChatBot/1.0; +https://github.com/Starcraft2ChatBot)"
)

# ---------------------------------------------------------------------------
# Trigger keyword sets
# ---------------------------------------------------------------------------

_DEFAULT_TRIGGERS = [
    "prove it", "prove that", "source", "citation", "cite",
    "look it up", "look up", "google it", "fact check", "fact-check",
    "according to", "what does the bible", "bible say", "scripture",
    "verse about", "where in the bible",
]

_CLAIM_MARKERS = (
    "is actually", "was actually", "in reality", "in fact", "the truth is",
    "studies show", "research shows", "scientists say", "everyone knows",
    "it's a fact", "its a fact", "historically", "statistically",
    "the bible says", "the quran says", "the constitution says",
    "percent", "%", "billion", "million", "died in", "was born",
    "killed", "assassinated", "murdered", "died on", "died at",
)

_DISPUTE_MARKERS = (
    "you're wrong", "youre wrong", "your wrong", "ur wrong",
    "no it isn't", "no it isnt", "no it's not", "no its not",
    "cap", "cope", "lies", "lying", "fake news", "misinformation",
    "nonsense", "bs", "bullshit", "debunked", "source?", "proof?",
    "where did you", "who told you", "since when",
)

_TRIVIAL_PATTERNS = re.compile(
    r"^(?:\s*(?:lol|lmao|rofl|kek|gg|gl|hf|glhf|wp|ez|nice|cool|ok|okay|"
    r"k|yeah|yep|nah|nope|sup|hi|hey|hello|yo|thanks|thx|ty|np|"
    r"brb|afk|omw|wtf|lolw|xd|haha+)\s*[.!?]*\s*)$",
    re.IGNORECASE,
)

_QUESTION_WORDS = (
    "who", "what", "when", "where", "why", "how",
    "is ", "are ", "was ", "were ", "does ", "do ", "did ",
    "can ", "could ", "should ", "would ",
)

_CONTEXT_DEPENDENT_STARTS = re.compile(
    r"^\s*(?:"
    r"how (?:tall|big|old|many|much|long|far|fast|deep|wide|heavy|rich|strong)|"
    r"how (?:is|are|was|were|does|do|did|can|could|would|should)|"
    r"what about|what of|and what|what else|"
    r"is it|is he|is she|is that|is this|"
    r"was it|was he|was she|was that|"
    r"does it|does he|does she|"
    r"did it|did he|did she|"
    r"why is|why are|why was|why were|why did|why does|"
    r"when did|when was|when is|"
    r"where is|where was|where did|"
    r"tell me more|more about that|go on|continue"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Query cleaning + entity extraction
# ---------------------------------------------------------------------------

# Words to strip when building a search query
_QUESTION_STRIP_RE = re.compile(
    r"(?i)\b(?:"
    r"where are|where is|where was|where were|"
    r"what are|what is|what was|what were|"
    r"when did|when was|when is|when were|"
    r"who was|who is|who were|who are|"
    r"how many|how much|how did|how was|"
    r"tell me about|look up|look it up|"
    r"did |does |do |"
    r"happened to|go to|went to|"
    r"that guy|that girl|that man|that woman|that person|"
    r"the guy|the girl|the man|the woman|the person|"
    r"someone|somebody|"
    r"you know|i mean|like"
    r")\b"
)

# Common stopwords removed from entity extraction
_ENTITY_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "with", "and", "or", "but",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "my", "your", "his", "their", "our", "this", "that", "these", "those",
    "what", "who", "when", "where", "why", "how", "which",
    "did", "does", "do", "was", "were", "is", "are",
    "happened", "happen", "happens",
    "guy", "girl", "man", "woman", "person", "people",
    "someone", "somebody", "anyone", "anybody",
    "killed", "killer", "murdered", "murderer", "died", "dead",
    "train", "plane", "car", "bus",
    "like", "just", "really", "very", "actually",
    "know", "think", "said", "says", "say",
    "about", "into", "over", "after", "before", "during",
    "there", "here", "where", "when",
    "get", "got", "went", "going", "come", "came",
    "make", "made", "take", "took", "give", "gave",
}


def _extract_entities(text: str, max_entities: int = 6) -> List[str]:
    """Extract meaningful words/phrases from a question for search.

    "What happened to that guy that killed that ukrainian woman on the train"
    → ["ukrainian", "woman", "train"]  (plus we might add "killed" if no other verb)
    """
    # Lowercase, remove punctuation
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    words = t.split()

    entities: List[str] = []
    for w in words:
        if len(w) < 3:
            continue
        if w in _ENTITY_STOPWORDS:
            continue
        # Keep words that carry meaning
        entities.append(w)

    # Deduplicate while preserving order
    seen = set()
    out = []
    for e in entities:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out[:max_entities]


def _clean_query(text: str, max_len: int = 120) -> str:
    """Convert a message into a search-friendly query.

    For complex questions, extracts entities instead of using the raw text.
    """
    # First, try simple cleaning
    t = re.sub(r"\s+", " ", (text or "").strip())
    t = re.sub(
        r"(?i)\b(prove it|source\??|citation|cite that|look it up|google it)\b",
        " ",
        t,
    )
    t = _QUESTION_STRIP_RE.sub(" ", t)
    t = re.sub(r"^[?!.\s]+|[?!.\s]+$", "", t)
    t = re.sub(r"\s+", " ", t).strip()

    # If the result is still too long or looks like a full sentence, extract entities
    if len(t.split()) > 6:
        entities = _extract_entities(text)
        if entities:
            t = " ".join(entities)

    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0]
    return t.strip()


# ---------------------------------------------------------------------------
# Scoring: should we research this message?
# ---------------------------------------------------------------------------

def _is_trivial(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _TRIVIAL_PATTERNS.match(t):
        return True
    words = re.findall(r"[A-Za-z]{2,}", t)
    return len(words) < 2


def _is_question(text: str) -> bool:
    low = (text or "").lower()
    if "?" not in low and not any(low.startswith(w) for w in _QUESTION_WORDS):
        return False
    return any(w in low for w in _QUESTION_WORDS)


def _looks_like_claim(text: str) -> bool:
    low = (text or "").lower()
    if any(m in low for m in _CLAIM_MARKERS):
        return True
    if re.search(r"\b\d{2,}\s*(?:%|percent|million|billion|years?|people)\b", low):
        return True
    return False


def _looks_like_dispute(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _DISPUTE_MARKERS)


def _explicit_trigger(text: str, triggers: List[str]) -> bool:
    low = (text or "").lower()
    return any(t and str(t).lower() in low for t in triggers)


def _topic_words(text: str) -> set:
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "to", "of", "in", "on", "at", "for", "with", "and", "or", "but",
        "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
        "my", "your", "his", "their", "our", "this", "that", "these", "those",
        "so", "just", "really", "very", "lol", "bro", "dude", "man", "like",
        "what", "who", "when", "where", "why", "how", "isnt", "isn't", "dont",
        "don't", "didnt", "didn't", "cant", "can't", "wont", "won't",
    }
    words = re.findall(r"[A-Za-z]{3,}", (text or "").lower())
    return {w for w in words if w not in stop}


def _escalation_score(history_texts: List[str], current: str) -> float:
    cur = _topic_words(current)
    if not cur:
        return 0.0
    hits = 0
    total = 0
    for h in history_texts:
        hw = _topic_words(h)
        if not hw:
            continue
        total += 1
        if len(cur & hw) >= 2:
            hits += 1
    if total == 0:
        return 0.0
    return min(1.0, hits / float(total))


def _research_score(
    message: str,
    *,
    history_texts: List[str],
    bot_history_texts: List[str],
    triggers: List[str],
) -> Tuple[float, List[str]]:
    reasons: List[str] = []
    score = 0.0

    if _is_trivial(message):
        return 0.0, ["trivial"]

    if _explicit_trigger(message, triggers):
        score += 3.0
        reasons.append("explicit_trigger")

    if _looks_like_dispute(message):
        score += 2.5
        reasons.append("dispute")

    if _is_question(message):
        score += 1.5
        reasons.append("question")

    if _looks_like_claim(message):
        score += 1.0
        reasons.append("claim")

    for line in bot_history_texts[-3:]:
        if _looks_like_claim(line) or _looks_like_dispute(line):
            score += 0.75
            reasons.append("bot_claim")
            break

    esc = _escalation_score(history_texts, message)
    if esc >= 0.5:
        score += 1.0
        reasons.append(f"escalation={esc:.2f}")
    elif esc >= 0.3:
        score += 0.5
        reasons.append(f"escalation={esc:.2f}")

    return score, reasons


def _should_research(
    message: str,
    cfg: Dict[str, Any],
    *,
    history_texts: Optional[List[str]] = None,
    bot_history_texts: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    if not cfg or not cfg.get("enabled", False):
        return False, ["disabled"]
    if not (message or "").strip():
        return False, ["empty"]

    triggers = cfg.get("trigger_substrings")
    if triggers is None:
        triggers = _DEFAULT_TRIGGERS
    triggers = [t for t in triggers if t] if triggers else []

    min_score = float(cfg.get("min_score", 2.0) or 2.0)

    score, reasons = _research_score(
        message,
        history_texts=history_texts or [],
        bot_history_texts=bot_history_texts or [],
        triggers=triggers,
    )
    if score >= min_score:
        return True, reasons + [f"score={score:.2f}"]
    return False, reasons + [f"score={score:.2f}"]


# ---------------------------------------------------------------------------
# Lookup backends
# ---------------------------------------------------------------------------

def _google_news_rss(query: str, timeout: float, limit: int = 3) -> List[str]:
    """Google News RSS — best for recent events like murders, trials, etc."""
    try:
        url = (
            "https://news.google.com/rss/search?"
            + urllib.parse.urlencode({
                "q": query,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            })
        )
        xml = _http_get(url, timeout)
        # Parse <title> and <description> from RSS
        titles = re.findall(r"<title>(.*?)</title>", xml, re.DOTALL)
        descriptions = re.findall(r"<description>(.*?)</description>", xml, re.DOTALL)
        out = []
        # Skip the first title (it's the feed name)
        for i, title in enumerate(titles[1:], 1):
            title = re.sub(r"<[^>]+>", "", title).strip()
            title = re.sub(r"\s+", " ", title)
            if title and len(title) > 10:
                out.append(f"News: {title}")
                if len(out) >= limit:
                    break
        return out
    except Exception as e:
        logger.debug("Google News RSS failed: %s", e)
        return []


def _wiki_summary(query: str, timeout: float) -> str:
    """Wikipedia full-text search + summary. Rejects poor matches."""
    try:
        search_url = (
            "https://en.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode({
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 3,
                "format": "json",
            })
        )
        raw = _http_get(search_url, timeout)
        data = json.loads(raw)
        results = data.get("query", {}).get("search", [])
        if not results:
            return ""

        # Verify the top result actually contains key entities from the query
        query_entities = set(_extract_entities(query))
        if query_entities:
            for r in results[:3]:
                title = r.get("title", "").lower()
                snippet = re.sub(r"<[^>]+>", "", r.get("snippet", "")).lower()
                combined = title + " " + snippet
                # Require at least 2 entity words to match
                matches = sum(1 for e in query_entities if e in combined)
                if matches >= min(2, len(query_entities)):
                    # This result looks relevant
                    sum_url = (
                        "https://en.wikipedia.org/api/rest_v1/page/summary/"
                        + urllib.parse.quote(r["title"])
                    )
                    body = json.loads(_http_get(sum_url, timeout))
                    extract = (body.get("extract") or "").strip()
                    if extract:
                        return f"Wikipedia ({r['title']}): {extract}"
        # No good match — return empty rather than a bad result
        return ""
    except Exception as e:
        logger.debug("Wikipedia research failed: %s", e)
        return ""


def _fact_check_lookup(query: str, timeout: float) -> str:
    try:
        url = (
            "https://factchecktools.googleapis.com/v1alpha1/claims:search?"
            + urllib.parse.urlencode({"query": query, "pageSize": 1})
        )
        raw = _http_get(url, timeout)
        data = json.loads(raw)
        claims = data.get("claims", [])
        if not claims:
            return ""
        claim = claims[0]
        text = claim.get("text", "")
        reviews = claim.get("claimReview", [])
        if not reviews:
            return ""
        review = reviews[0]
        publisher = review.get("publisher", {}).get("name", "Unknown")
        rating = review.get("textualRating", "Unknown")
        return f"FactCheck ({publisher}): '{text}' — rated: {rating}"
    except Exception as e:
        logger.debug("FactCheck lookup failed: %s", e)
        return ""


def _ddg_lite_snippets(query: str, timeout: float, limit: int = 3) -> List[str]:
    try:
        url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
        html = _http_get(url, timeout)
        results = []
        for match in re.finditer(r'<a[^>]*class="result-link"[^>]*>(.*?)</a>', html, re.DOTALL):
            text = re.sub(r'<[^>]+>', '', match.group(1))
            text = re.sub(r'\s+', ' ', text).strip()
            if text and len(text) > 15:
                results.append(text)
                if len(results) >= limit:
                    break
        return results
    except Exception as e:
        logger.debug("DDG Lite failed: %s", e)
        return []


def _ddg_snippets(query: str, timeout: float, limit: int = 3) -> List[str]:
    try:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        html = _http_get(url, timeout)
        parser = _DDGLinkParser()
        parser.feed(html)
        out: List[str] = []
        seen = set()
        for r in parser.results:
            key = r[:80].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        logger.debug("DuckDuckGo research failed: %s", e)
        return []


_VERSE_RE = re.compile(
    r"\b(?:genesis|exodus|leviticus|numbers|deuteronomy|joshua|judges|ruth|"
    r"samuel|kings|chronicles|ezra|nehemiah|esther|job|psalm|psalms|proverbs|"
    r"ecclesiastes|song\s+of\s+solomon|isaiah|jeremiah|lamentations|ezekiel|"
    r"daniel|hosea|joel|amos|obadiah|jonah|micah|nahum|habakkuk|zephaniah|"
    r"haggai|zechariah|malachi|matthew|mark|luke|john|acts|romans|"
    r"corinthians|galatians|ephesians|philippians|colossians|thessalonians|"
    r"timothy|titus|philemon|hebrews|james|peter|jude|revelation)"
    r"\s+\d{1,3}:\d{1,3}(?:\s*-\s*\d{1,3})?\b",
    re.IGNORECASE,
)


def _bible_lookup(message: str, timeout: float) -> str:
    try:
        m = _VERSE_RE.search(message or "")
        if m:
            ref = re.sub(r"\s+", " ", m.group(0)).strip()
            url = "https://bible-api.com/" + urllib.parse.quote(ref)
            data = json.loads(_http_get(url, timeout))
            text = (data.get("text") or "").strip()
            ref_out = (data.get("reference") or ref).strip()
            if text:
                text = re.sub(r"\s+", " ", text)
                return f"Bible {ref_out}: {text}"
    except Exception as e:
        logger.debug("Bible API lookup failed: %s", e)
    return ""


# ---------------------------------------------------------------------------
# Conversation-aware query building
# ---------------------------------------------------------------------------

def _needs_context(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return True
    if _CONTEXT_DEPENDENT_STARTS.match(q):
        return True
    words = re.findall(r"[A-Za-z]{3,}", q)
    return len(words) < 2


def _extract_topic_from_history(history_texts: List[str]) -> str:
    for line in reversed(history_texts or []):
        t = (line or "").strip()
        if not t:
            continue
        if _needs_context(t):
            continue
        cleaned = _clean_query(t)
        if cleaned and len(cleaned) >= 3:
            return cleaned
    return ""


def _build_research_query(message: str, history_texts: List[str]) -> str:
    current = _clean_query(message)
    if current and not _needs_context(current):
        return current

    prior = _extract_topic_from_history(history_texts)
    if not prior:
        return current or (message or "").strip()[:120]

    if current:
        return f"{prior} — {current}"
    return prior


# ---------------------------------------------------------------------------
# Structured brief builder
# ---------------------------------------------------------------------------

def _format_brief(topic: str, sources: List[Tuple[str, str]], max_chars: int) -> str:
    if not sources:
        return ""

    lines = [f"[RESEARCH BRIEF — topic: {topic}]"]
    for i, (label, text) in enumerate(sources, 1):
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        per_source_cap = max(150, max_chars // max(len(sources), 1))
        if len(text) > per_source_cap:
            text = text[: per_source_cap - 3].rsplit(" ", 1)[0] + "..."
        lines.append(f"Source {i} ({label}):")
        lines.append(text)

    brief = "\n".join(lines)
    if len(brief) > max_chars:
        brief = brief[: max_chars - 3].rsplit(" ", 1)[0] + "..."
    return brief


# ---------------------------------------------------------------------------
# Session cache + per-player cooldown
# ---------------------------------------------------------------------------

class _ResearchCache:
    def __init__(self, ttl_sec: float = 300.0, max_entries: int = 200):
        self.ttl = ttl_sec
        self.max = max_entries
        self._data: Dict[str, Tuple[float, str]] = {}

    def get(self, key: str) -> Optional[str]:
        entry = self._data.get(key)
        if not entry:
            return None
        ts, val = entry
        if time.time() - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def put(self, key: str, value: str) -> None:
        if len(self._data) >= self.max:
            oldest = min(self._data.items(), key=lambda kv: kv[1][0])
            self._data.pop(oldest[0], None)
        self._data[key] = (time.time(), value)


_CACHE = _ResearchCache()
_LAST_PLAYER_LOOKUP: Dict[str, float] = {}


def _player_cooldown_ok(player: str, cooldown_sec: float) -> bool:
    if not player or cooldown_sec <= 0:
        return True
    last = _LAST_PLAYER_LOOKUP.get(player, 0.0)
    return (time.time() - last) >= cooldown_sec


def _mark_player_lookup(player: str) -> None:
    if player:
        _LAST_PLAYER_LOOKUP[player] = time.time()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def research_topic(
    message: str,
    cfg: Optional[Dict[str, Any]] = None,
    *,
    player: str = "",
    history_texts: Optional[List[str]] = None,
    bot_history_texts: Optional[List[str]] = None,
) -> str:
    """Return a structured research brief for the LLM, or empty string."""
    cfg = cfg or {}
    if not cfg.get("enabled", False):
        return ""

    history_texts = history_texts or []
    bot_history_texts = bot_history_texts or []

    should, reasons = _should_research(
        message,
        cfg,
        history_texts=history_texts,
        bot_history_texts=bot_history_texts,
    )
    if not should:
        logger.debug("Research skipped (%s): %r", ",".join(reasons), (message or "")[:80])
        return ""

    cooldown = float(cfg.get("per_player_cooldown_sec", 45) or 45)
    if player and not _player_cooldown_ok(player, cooldown):
        logger.debug("Research skipped — per-player cooldown for %s", player)
        return ""

    timeout = float(cfg.get("timeout_sec", 8) or 8)
    max_chars = int(cfg.get("max_chars", 900) or 900)

    query = _build_research_query(message, history_texts)
    if not query or len(query) < 3:
        query = (message or "").strip()[:120]
    if not query:
        return ""

    cache_key = query.lower()
    cached = _CACHE.get(cache_key)
    if cached is not None:
        logger.debug("Research cache hit: %s", cache_key[:60])
        _mark_player_lookup(player)
        return cached

    logger.info("Researching (%s) query=%r", ",".join(reasons), query[:120])

    sources: List[Tuple[str, str]] = []

    # Tier 1: Google News RSS (best for recent events)
    for snip in _google_news_rss(query, timeout, limit=3):
        sources.append(("news", snip))

    # Tier 2: Wikipedia (factual background)
    if len(sources) < 2:
        wiki = _wiki_summary(query, timeout)
        if wiki:
            sources.append(("Wikipedia", wiki))

    # Tier 3: Google Fact Check (contested claims)
    if not sources:
        fact = _fact_check_lookup(query, timeout)
        if fact:
            sources.append(("FactCheck", fact))

    # Tier 4: DuckDuckGo Lite
    if not sources:
        for snip in _ddg_lite_snippets(query, timeout, limit=3):
            sources.append(("web", snip))

    # Tier 5: DuckDuckGo HTML fallback
    if not sources:
        for snip in _ddg_snippets(query, timeout, limit=3):
            sources.append(("web", snip))

    # Bible lookup (only if verse reference present)
    bible = _bible_lookup(message, timeout)
    if bible:
        sources.append(("Bible", bible))

    if not sources:
        logger.info("Research returned no snippets for: %s", query[:80])
        _CACHE.put(cache_key, "")
        _mark_player_lookup(player)
        return ""

    brief = _format_brief(query, sources, max_chars)
    logger.info("Research brief (%d chars): %s", len(brief), brief[:160].replace("\n", " "))
    _CACHE.put(cache_key, brief)
    _mark_player_lookup(player)
    return brief


def was_research_attempted(
    message: str,
    cfg: Optional[Dict[str, Any]] = None,
    *,
    history_texts: Optional[List[str]] = None,
    bot_history_texts: Optional[List[str]] = None,
) -> bool:
    if not cfg or not cfg.get("enabled", False):
        return False
    should, _ = _should_research(
        message,
        cfg,
        history_texts=history_texts or [],
        bot_history_texts=bot_history_texts or [],
    )
    return should