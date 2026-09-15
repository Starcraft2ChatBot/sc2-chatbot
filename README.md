# SC2 Chat-Only Bot (AI-powered)

**Educational / research project only.**

A modular StarCraft 2 **chat-only** bot that reads lobby and in-game chat, decides when to reply, performs targeted web research when facts are needed, and responds with a configurable AI personality. Supports **Google Gemini**, **OpenAI-compatible** cloud APIs (NVIDIA, OpenRouter, etc.), and **local models via Ollama**.

---

## Table of contents

- [What it does](#what-it-does)
- [Screenshots](#screenshots)
- [Features](#features)
- [Blizzard Terms of Service warning](#blizzard-terms-of-service-warning)
- [How a reply is generated](#how-a-reply-is-generated)
- [Research engine](#research-engine)
  - [When research fires](#when-research-fires)
  - [Research topics and what the bot looks up](#research-topics-and-what-the-bot-looks-up)
  - [Conversation-aware query building](#conversation-aware-query-building)
  - [Entity extraction](#entity-extraction)
  - [Lookup backends](#lookup-backends)
  - [Structured brief format](#structured-brief-format)
  - [Paraphrase enforcement](#paraphrase-enforcement)
  - [Empty-research honesty guard](#empty-research-honesty-guard)
  - [Caching and cooldown](#caching-and-cooldown)
- [Personality system](#personality-system)
- [Blacklist, favorites, and output guards](#blacklist-favorites-and-output-guards)
- [Configuration reference](#configuration-reference)
- [Quick start](#quick-start)
- [Running with live SC2 (OCR)](#running-with-live-sc2-ocr)
- [Owner commands](#owner-commands)
- [Project layout](#project-layout)
- [Development notes](#development-notes)
- [License](#license)

---

## What it does

The bot sits in a StarCraft 2 chat channel (via OCR or a simulated backend), watches incoming messages, and decides whether to reply. When it replies, it:

1. Runs the message through anti-spam and trigger checks.
2. Optionally performs **web research** if the message is a question, a factual claim, a dispute, or an explicit lookup request.
3. Builds an LLM prompt from a configurable personality plus the research brief.
4. Generates a short, casual chat line in character.
5. Rejects and rewrites the line if it echoes the player, repeats the bot's own recent lines, or pastes the research verbatim.
6. Types or pastes the final line back into SC2 after a short human-like delay.

If the model returns empty, only meta/planning text, or a reply that fails the output guards, **no reply is sent**.

---

## Screenshots

**Live console output**

<img width="845" height="720" alt="Console output example" src="https://github.com/user-attachments/assets/5fa59b94-c6bb-49ff-8e62-ca2e132bb43d" />

Shows `RECV` for incoming chat, `SEND` for replies, owner command results, the startup **ACTIVE CONFIG** dump, and the transient **AI generating reply…** spinner while the model is running.

**Automatic AI reply**

<img width="800" height="67" alt="Automatic AI reply demo" src="https://github.com/user-attachments/assets/a7f5b6c1-4770-40b1-9224-50a225f55b82" />

The bot picks up messages from chat (including multi-line messages), runs them through the pipeline, calls the LLM, then types or pastes the reply into SC2.

---

## Features

### Chat pipeline
- **Pluggable chat backends** — `simulated` for development, `sc2_stub` for live OCR.
- **Multi-line chat support** — joins wrapped SC2 chat lines under `[1. General] Name: ...` so long messages are read in full.
- **Human-like typing delays** — configurable min/max reply delay, optional typos.
- **Name addressing** — optional chance to prefix replies with the player's name.
- **AI progress spinner** in the console while the LLM runs.

### LLM integration
- **Multi-provider** — Gemini, OpenAI-compatible (NVIDIA, OpenRouter, custom), and local **Ollama**.
- **`llm.think` toggle** for reasoning models that emit `<think>` blocks.
- **Request and connection timeouts**, health checks, and detailed error diagnostics.
- **Automatic fallback** from Ollama's native API to the OpenAI-compatible path when the native call returns empty.

### Research engine
- **Scored triggering** — explicit triggers, questions, factual claims, disputes, escalation, and the bot's own recent claims.
- **Conversation-aware query building** — context-dependent follow-ups ("how tall was he?") inherit the subject from prior turns.
- **Entity extraction** — complex questions are reduced to searchable noun phrases.
- **Multi-tier lookup** — Google News RSS (recent events), Wikipedia full-text search with entity verification, Google Fact Check Explorer, DuckDuckGo Lite, DuckDuckGo HTML fallback, and the Bible API for verse references.
- **Structured brief** — labeled, numbered sources with a `topic:` header, capped per source so one loud result can't crowd out others.
- **Paraphrase enforcement** — the reply pipeline rejects any line that shares a long verbatim span with the brief.
- **Empty-research honesty guard** — when research is attempted but returns nothing, the bot is explicitly instructed not to invent facts.
- **Session cache** — identical queries within 5 minutes return the cached brief (including negative results).
- **Per-player cooldown** — configurable minimum gap between lookups for the same player.

### Personality system
- **Prebuilt modes** — `neutral`, `left`, `right`, `propaganda_left`, `propaganda_right`, `troll`, `ragebait`.
- **Custom personality** — free-text prompt that fully replaces prebuilt modes when enabled.
- **Emojis disabled** in both prompt and output.
- **Topic toggles** — politics, current events, in-game strategy, memes, personal.
- **Aggressiveness scale** (1–10) and **response length** (short/medium/long).
- **SC2 reference level** (0–10) — 0 forbids any game talk, 10 allows full ladder banter.

### Output guards
- **Echo guard** — rejects replies that copy the player's message in whole or in large partial chunks.
- **Self-repeat guard** — rejects replies too similar to the bot's own recent lines (per-player and global).
- **Research-echo guard** — rejects replies that paste sentences from the research brief.
- **Blacklist** — word, substring, symbol, letter, and replacement rules applied to every outgoing line.
- **Favorites** — nudges the model toward preferred vocabulary at soft/medium/strong intensity.

### Operations
- **Anti-spam** — global cooldown, per-player cooldown, per-minute cap, mute list.
- **Per-player memory** — rolling conversation window with optional JSON persistence.
- **Canned triggers** — regex-based instant replies with cooldowns and per-player limits.
- **Owner commands** — runtime control of tone, mode, length, mute, reload, and status.
- **Startup diagnostics** — package, API key, OCR, and Tesseract checks.
- **Structured logging** — colored console output plus rotating file log.
- **Portable build support** — `paths.py` resolves config/logs relative to the app root, whether running from source or a frozen executable.

---

## Blizzard Terms of Service warning

Third-party automation that reads or injects into the live SC2 client can violate Blizzard's Terms of Service. **Use at your own risk.** Prefer `chat_backend: simulated` for development and testing.

---

## How a reply is generated

For each incoming message the bot runs this pipeline:

1. **Self-check** — ignore messages from the bot's own account unless they look like owner commands.
2. **Anti-spam** — global cooldown, per-player cooldown, per-minute cap, mute list.
3. **Trigger check** — if a canned trigger matches, and it isn't a recent self-repeat, send it and stop.
4. **Game-request branch** — optional canned replies for lobby requests.
5. **System prompt** — built from the active personality (custom or prebuilt).
6. **Per-player context** — the last 10 lines feed the LLM as conversation history; the last 15 feed research for escalation and query building.
7. **Research call** — may return a structured brief or nothing.
8. **Prompt assembly** — the brief is wrapped with explicit paraphrase rules and delimited with `--- BEGIN/END RESEARCH ---`.
9. **Empty-research guard** — if research was attempted but returned nothing, the prompt forbids inventing facts.
10. **LLM generation** — one short in-character chat line.
11. **Rejection pass 1** — echo, self-repeat, and research-echo checks; failure triggers one rewrite with an explicit "do not copy the brief" instruction.
12. **Cleanup** — typo chance, quote stripping, channel-prefix removal.
13. **Rejection pass 2** — the same three guards after cleanup.
14. **Blacklist + name addressing** — final output filter.
15. **Rejection pass 3** — guards one last time before send.
16. **Record** — anti-spam counters updated and the exchange stored in per-player memory.

---

## Research engine

Research is what makes the bot answer factual questions instead of inventing. It's split across two layers: **scoring** (should we look anything up?) and **lookup** (what do we fetch, and how do we present it?).

### When research fires

Each incoming message is scored. The default threshold is `min_score: 2.0`.

| Signal | Points |
|--------|--------|
| Explicit trigger substring (`source`, `prove it`, …) | +3.0 |
| Dispute marker (`you're wrong`, `cap`, `source?`, `debunked`, …) | +2.5 |
| Question (contains `?` or starts with a question word) | +1.5 |
| Factual claim marker (`studies show`, `the bible says`, percentages, `died`, `killed`, …) | +1.0 |
| Bot's own recent line was a claim or dispute | +0.75 |
| Escalation — same topic repeated in the per-player history | +1.0 or +0.5 |

Trivial messages (`lol`, `gg`, `gl hf`, anything under two content words) score 0 and never trigger a lookup. Questions alone (1.5) stay under the default threshold.

Raise `min_score` to `3.0` to only fire on explicit triggers and disputes. Lower it to `1.5` to also research claims and light escalation.

### Research topics and what the bot looks up

The bot is **topic-agnostic**. Its lookup backends cover essentially anything a chat participant could ask about, but each backend has a natural strength. This table shows what fires for which kind of question and where the answer comes from.

| Topic category | Example question | Primary backend | Notes |
|---|---|---|---|
| **Recent events** | "what happened to the guy that killed that ukrainian woman on the train" | Google News RSS | Best for murders, trials, arrests, verdicts, breaking news. Uses news headlines directly. |
| **Current politics** | "did trump sign the bill", "what's the inflation rate" | Google News RSS → Wikipedia | News for the event, Wikipedia for background. |
| **Historical facts** | "when did ww2 end", "was napoleon short" | Wikipedia full-text search | Verified against entities from the query so unrelated pages are rejected. |
| **Science / geography** | "how many moons does jupiter have", "capital of australia" | Wikipedia full-text search | Stable, uncontested facts. |
| **Pop culture** | "who directed inception", "when did that band break up" | Wikipedia → DDG Lite | Wikipedia for well-known entities, DDG for smaller subjects. |
| **Sports** | "who won the 2022 world cup" | Google News RSS → Wikipedia | News for the latest result, Wikipedia for historical. |
| **Contested claims** | "the earth is flat", "vaccines cause autism" | Google Fact Check Explorer | Fires only when a fact-check organization has already rated the claim. |
| **Death / alive checks** | "when did charlie kirk die", "is X still alive" | Google News RSS → Wikipedia | Explicitly guarded: if research fails, the bot refuses to invent a death claim. |
| **Verse references** | "john 3:16", "what does romans 8:28 say" | bible-api.com | Only fires when a `Book C:V` pattern is detected. |
| **Religious topics (general)** | "what does islam say about x", "bible verse about patience" | Wikipedia → DDG Lite | General religious questions go through the general backends. |
| **Math / unit conversions** | "how many km in a mile" | DDG Lite → Wikipedia | No dedicated calculator backend; falls back to web snippets. |
| **Definitions** | "what does X mean" | Wikipedia → DDG Lite | Dictionary-style lookups. |
| **Weather / live data** | "what's the weather" | ❌ None | No live-data backend. The bot will say it doesn't know. |
| **Stock / crypto prices** | "what's bitcoin at" | ❌ None | Same — no live market backend. |
| **Personal / private info** | "where does X live" | ❌ None | No people-search backend. |

The bot never researches on its own initiative. Everything is gated by the scoring table above, so casual banter, "gg", "gl hf", and short reactions never hit the network.

### Conversation-aware query building

The query sent to search backends is built from the current message **plus** recent per-player history:

- If the message has its own subject, use it directly.
- If it's a dangling follow-up ("how tall was he", "what about that", "tell me more"), prepend the most recent subject-bearing line from the player's history.

So after `"tell me about napoleon"` → `"how tall was he?"`, the bot searches for `"tell me about napoleon — how tall was he"` instead of just `"how tall was he"`.

### Entity extraction

For long or complex questions, `_extract_entities()` strips stopwords and question scaffolding, keeping meaningful nouns. Example:

> `"What happened to that guy that killed that ukrainian woman on the train"`
> → `"ukrainian woman train"`

Stopwords removed include question words (`what`, `who`, `when`), filler (`that guy`, `happened`, `like`, `just`), and generic nouns (`person`, `someone`, `killed`, `murdered`). This is why the bot can turn a rambling chat question into a query a search engine can actually answer.

### Lookup backends

Lookups run in priority order. The first tiers that return results fill the brief; lower tiers only fire when higher ones come back empty.

| Tier | Backend | Best for | Notes |
|------|---------|----------|-------|
| 1 | **Google News RSS** | Recent events — murders, trials, releases, breaking news | Free, no API key. Returns headlines directly. |
| 2 | **Wikipedia full-text search** | Factual background — history, science, people, places | Uses `list=search`, not `opensearch`. Results are verified against extracted entities. |
| 3 | **Google Fact Check Explorer** | Contested claims that already have published fact-checks | Free public endpoint, no key required. |
| 4 | **DuckDuckGo Lite** | General web fallback | `lite.duckduckgo.com` — different endpoint that often works when the HTML one doesn't. |
| 5 | **DuckDuckGo HTML** | Last-resort fallback | `html.duckduckgo.com` — frequently blocked, kept as a safety net. |
| 6 | **Bible API** | Only fires when a `Book C:V` reference is present | Independent of the tier list — a verse reference always runs. |

**Wikipedia entity verification** is what prevents the classic failure mode where a query about a Charlotte train stabbing returns a page about "Russian attacks on civilians" just because both contain "Ukrainian". The search pulls the top 3 results, extracts entity words from the query, and requires at least 2 of those words to appear in the result's title or snippet. If nothing matches, the backend returns an empty string rather than a bad result.

### Structured brief format

Lookups are combined into a labeled, delimited brief:

```
[RESEARCH BRIEF — topic: ukrainian woman train stabbing charlotte]
Source 1 (news):
Man accused of killing Ukrainian refugee on Charlotte train ruled incompetent...
Source 2 (news):
Judge orders psychiatric treatment for suspect in Charlotte light rail stabbing...
Source 3 (Wikipedia):
...
```

Each source is capped at `max_chars / num_sources` (minimum 150 characters) so one loud result can't dominate the brief. The `[RESEARCH BRIEF — topic: ...]` header anchors the LLM to the actual topic.

### Paraphrase enforcement

The brief is reference material, not text to paste. The prompt tells the model to:

- Paraphrase in its own voice.
- Never quote whole sentences.
- Never mention Wikipedia, sources, or research.
- Only use the parts that answer the conversation.
- Ignore the brief if it's off-topic.
- Prefer the brief over prior claims but stay in character without announcing a correction.

After generation, `_is_research_echo()` compares the reply against the **source body lines only** (not the header) and rejects it if:

- A ≥20-character span matches either direction, or
- A 6- or 8-word **consecutive** n-gram matches, or
- Jaccard word-set similarity is ≥ 0.80.

A rejected reply gets one rewrite attempt with an explicit "do not copy sentences from the brief" instruction. If it still fails, the bot stays silent.

### Empty-research honesty guard

If research was attempted (`was_research_attempted()` returns `True`) but the brief is empty, the prompt is extended with:

> **CRITICAL:** You tried to look this up but found NO reliable information. Do NOT invent facts. Do NOT make up dates, events, deaths, or claims. If you cannot answer factually, say something short like 'i cant find that' or 'no idea' or change the subject.

This is the key fix that stops the bot from confidently asserting fabricated facts when lookup fails. It's what turns "Charlie Kirk is still alive" into "i cant find that" instead of a conspiracy rant.

### Caching and cooldown

- **Session cache** — 5-minute TTL, 200 entries. Identical queries (including negative results) skip the network entirely.
- **Per-player cooldown** — `per_player_cooldown_sec` (default 45s). One spammy player can't burn your API calls.

### Research tuning quick reference

| If you want… | Change |
|--------------|--------|
| Fewer lookups | Raise `research.min_score` to `3.0` |
| More lookups | Lower `research.min_score` to `1.5` |
| Fewer lookups per player | Raise `research.per_player_cooldown_sec` |
| Longer briefs | Raise `research.max_chars` |
| Research only on triggers | Set `trigger_substrings` and raise `min_score` to `3.0` |
| More aggressive entity extraction | Add words to the stopword sets in `research.py` |
| Add a new backend | Add a `_<backend>(query, timeout)` function and slot it into the tier list in `research_topic()` |

---

## Personality system

### Custom vs prebuilt priority

| `custom_enabled` | `custom_prompt` | Effective mode |
|------------------|-----------------|----------------|
| `true` | non-empty text | **`custom`** — prebuilt modes fully ignored |
| `true` | empty | Falls back to `political_mode` (warning logged) |
| `false` | (ignored) | Uses `political_mode` as usual |

When custom is on, `!prop` cannot switch prebuilt modes. Set `custom_enabled: false` in config and run `!reload` to return to prebuilt behaviour.

### Prebuilt modes (`political_mode`)

| Mode | Type | Behaviour |
|------|------|-----------|
| `neutral` | Neutral | Light sarcasm |
| `left` / `right` | Political | Soft lean |
| `propaganda_left` / `propaganda_right` | Political (hard) | Hostile propaganda with hard stance lock |
| `troll` | Non-political | Provoke and mock |
| `ragebait` | Non-political | Dismiss and bait |

### Example custom personality

```yaml
personality:
  aggressiveness: 8
  political_mode: "troll"      # only used when custom is off
  response_length: "medium"
  sc2_reference_level: 0
  topics:
    politics: true
    current_events: true
    in_game_strategy: false
    memes: false
    personal: true

  custom_enabled: true
  custom_prompt: |
    You are a chill older gamer in lobby chat.
    Short replies, mild sarcasm, never lecture. No AI vibes.
```

The startup log shows `custom_enabled`, a preview of `custom_prompt`, and `mode: custom` when active. `!status` shows `Custom=on|off`.

### Other knobs

| Setting | Effect |
|---------|--------|
| `aggressiveness` | 1 = friendly, 10 = extremely toxic |
| `response_length` | `short` / `medium` / `long` |
| `emoji_intensity` | Ignored — emojis are always stripped |
| `sc2_reference_level` | 0 = never mention SC2 … 10 = full ladder banter |
| `topics.politics` | Allow political content in political modes |
| `topics.current_events` | Allow news and current events |
| `topics.in_game_strategy` | Allow builds, races, ladder talk |
| `topics.memes` | Allow memes |
| `topics.personal` | Allow personal small-talk |

---

## Blacklist, favorites, and output guards

### Blacklist

Applied to every outgoing line **after** the guards pass. Configured under `blacklist:` in `config.yaml`.

| Key | Type | Effect |
|-----|------|--------|
| `words` | list | Whole-word removal (word boundaries enforced) |
| `substrings` | list | Literal substring removal |
| `symbols` | list | Symbol removal (e.g. `—`) |
| `letters` | list | First character of each entry removed globally |
| `replacements` | dict | Ordered key → value replacements, longest key first |
| `case_sensitive` | bool | Whether matching respects case |

### Favorites

Nudges the model toward preferred vocabulary.

| Intensity | Instruction injected into the prompt |
|-----------|--------------------------------------|
| `soft` / `low` / `light` | "When natural, lightly prefer vocabulary like: …" |
| `medium` (default) | "Prefer using these … often when they fit the reply (do not force them awkwardly)" |
| `strong` / `high` / `force` | "Strongly prefer … (use at least one when possible)" |

### Output guards

Three independent checks run on every candidate reply:

1. **`_is_echo(msg.text, reply)`** — rejects a reply that copies the player's message in whole or in large partial chunks (character spans, word-overlap ratios, n-grams, and bigram hits).
2. **`_is_self_repeat(reply, player)`** — rejects a reply that's too similar to the bot's own recent lines, per-player and globally (Jaccard ≥ 0.78, or ≥ 4 shared tokens at ≥ 0.85 coverage).
3. **`_is_research_echo(reply, brief)`** — rejects a reply that pastes sentences from the research brief.

If any guard fails, the bot issues one rewrite request that names the failure reason. If the rewrite also fails, the reply is dropped.

---

## Configuration reference

### Top-level sections

| Section | Purpose |
|---------|---------|
| `llm` | Provider, model, `think`, timeouts, `base_url` |
| `gemini` | Fallback Gemini key/model used only when `llm.provider` is `gemini` |
| `owner` | Bot names (used for self-detection) and command prefix |
| `personality` | Prebuilt mode, custom prompt, aggro, topics, SC2 reference level |
| `research` | Scoring threshold, trigger substrings, timeouts, cooldowns, cache size |
| `blacklist` | Output filter rules |
| `favorites` | Vocabulary nudges |
| `behaviour` | Delays, typo chance, reply probability, name addressing, game requests |
| `anti_spam` | Cooldowns, per-minute cap, mute list |
| `memory` | Per-player history length and optional persistence path |
| `triggers` / `canned_blocks` | Regex-based instant replies |
| `logging` | Level, file path, console output |
| `chat_backend` | `simulated` or `sc2_stub` |
| `sc2_stub` | OCR settings for the live SC2 backend |

### Example `llm` block

```yaml
llm:
  provider: "ollama"            # or gemini | openai | openai_compatible | openrouter | custom
  api_key: ""                   # prefer env var LLM_API_KEY
  model: "qwen2.5:7b-instruct"
  temperature: 0.7
  max_output_tokens: 350
  base_url: "http://127.0.0.1:11434/v1"
  think: false
  request_timeout_sec: 120
```

### Example `research` block

```yaml
research:
  enabled: true
  timeout_sec: 8
  max_chars: 900
  min_score: 2.0
  per_player_cooldown_sec: 45
  trigger_substrings:
    - "prove it"
    - "source"
    - "citation"
    - "look it up"
    - "fact check"
    - "bible say"
    - "scripture"
```

Leave `trigger_substrings` empty (`[]`) to use the built-in defaults only.

### Example `sc2_stub` block

```yaml
chat_backend: "sc2_stub"
sc2_stub:
  window_title: "StarCraft II"
  chat_key: "enter"
  send_key: "enter"
  input_method: "paste"
  ocr_enabled: true
  poll_interval_sec: 0.45
  chat_region: [1420, 680, 480, 300]   # [left, top, WIDTH, HEIGHT]
  tesseract_cmd: ""                    # leave blank to use PATH
  switch_channels: false
  channel_switch_key: "tab"
  assume_chat_opens_on_tab: 1
  max_chat_tabs: 8
  self_name: "YourInGameName"          # must match owner.names
```

`chat_region` uses **width and height**, not bottom-right coordinates. Measure with `tools/measure_chat_region.py`.

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Then edit `config/config.yaml`. If the file doesn't exist, it's created automatically from `config/config.example.yaml`.

### Environment variables

The loader reads these before falling back to the config file:

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | Preferred key for `llm.api_key` |
| `GEMINI_API_KEY` | Fallback key for Gemini |

Copy `.env.example` to `.env` and fill in your keys, or export them in your shell.

---

## Running with live SC2 (OCR)

1. Install Tesseract OCR and confirm it's on your PATH (or set `sc2_stub.tesseract_cmd`).
2. Install the OCR Python packages: `pip install mss Pillow pytesseract pyautogui PyGetWindow pyperclip`.
3. Run `python tools/measure_chat_region.py` and paste the resulting rectangle into `sc2_stub.chat_region`.
4. Set `chat_backend: "sc2_stub"` and `sc2_stub.ocr_enabled: true`.
5. Set `sc2_stub.self_name` to your exact in-game name and make sure it also appears in `owner.names`.
6. Launch SC2 in **Windowed** mode with chat visible.

The bot will seed the currently visible chat as "already seen" on the first poll and only act on messages that appear afterward.

---

## Owner commands

Only names listed under `owner.names` (plus `sc2_stub.self_name`) can issue commands. The default prefix is `!`.

| Command | Effect |
|---------|--------|
| `!prop troll` | Set prebuilt mode (blocked while custom is on) |
| `!prop left` / `!prop right` / `!prop neutral` | Soft political lean |
| `!prop propaganda_left` / `!prop propaganda_right` | Hard propaganda lock |
| `!prop ragebait` | Rage-bait mode |
| `!tone 9` | Aggressiveness 1–10 |
| `!length short` | Response length: `short` / `medium` / `long` |
| `!mute PlayerName` | Add a player to the mute list |
| `!unmute PlayerName` | Remove a player from the mute list |
| `!reload` | Reload `config.yaml` at runtime |
| `!status` | Show aggro, mode, custom on/off, mute count |

The OCR backend also accepts mangled prefixes like `|status` or `1tone 5` because Tesseract often misreads `!`.

---

## Project layout

```
.
├── main.py                     Entry point (dev + portable)
├── requirements.txt
├── config/
│   ├── config.example.yaml     Template copied to config.yaml on first run
│   └── config.yaml             Local config (git-ignored)
├── logs/                       Runtime logs + persisted memory (git-ignored)
├── tools/
│   └── measure_chat_region.py  Helper for OCR region calibration
└── src/
    ├── anti_spam.py            Cooldowns, per-minute caps, mute list
    ├── bot.py                  Orchestrator — wires everything together
    ├── chat/
    │   ├── base.py             ChatBackend interface
    │   ├── sc2_stub.py         Live SC2 OCR + keyboard backend
    │   └── simulated.py        In-memory simulated backend
    ├── commands.py             Owner command handler
    ├── config_loader.py        Pydantic config + env overrides
    ├── decision_engine.py      Reply pipeline + output guards
    ├── diagnostics.py          Startup health checks
    ├── game_requests.py        Lobby/game-request detection
    ├── gemini_client.py        Standalone Gemini client (legacy)
    ├── llm_client.py           Multi-provider LLM client
    ├── logger.py               Rich console + rotating file logger
    ├── memory.py               Per-player rolling history
    ├── models.py               ChatMessage, Channel, GameRequestInfo
    ├── names.py                Player-name cleanup + memory keys
    ├── paths.py                App-root resolution (dev + frozen)
    ├── personality.py          System prompt builder
    ├── research.py             Scoring, query building, lookups, brief formatting
    └── triggers.py             Canned regex triggers
```

---

## Development notes

### Recommended local setup

```yaml
llm:
  provider: "ollama"
  model: "qwen2.5:7b-instruct"
  think: false
  base_url: "http://127.0.0.1:11434/v1"
```

`think: false` is strongly recommended for chat — reasoning models that emit `<think>` blocks are cleaned, but a non-thinking model produces tighter chat lines.

### Debugging research

The log emits several useful lines:

```
Research skipped (trivial,score=0.00): 'lol'
Research skipped (question,score=1.50): 'what time is it'
Researching (explicit_trigger,dispute,score=5.50) query='source?'
Research brief (612 chars): [RESEARCH BRIEF — topic: ...]
Research skipped — per-player cooldown for SomePlayer
Research cache hit: <query>
LLM reply rejected (research_echo): '...' — requesting rewrite
```

If the bot is answering factual questions wrong, check whether `Researching ...` is followed by `Research brief ...` or by `Research returned no snippets`. The latter means the honesty guard will kick in and the bot should say it doesn't know.

### Debugging OCR

If `RECV` never fires in `sc2_stub` mode:

1. Confirm `chat_region` matches the on-screen chat box (`[left, top, WIDTH, HEIGHT]`).
2. Confirm Tesseract is reachable (startup diagnostics print the detected path and version).
3. Watch for `OCR text but no parse` — that means OCR is working but the message format isn't matching `Name: text`.

### Extending

- **New chat backend** — implement `ChatBackend` in `src/chat/` and register it in `bot._create_backend()`.
- **New LLM provider** — add a branch to `LLMClient.__init__` and a `_generate_<provider>` method.
- **New research backend** — add a `_<backend>(query, timeout)` function in `research.py` and slot it into the tier list in `research_topic()`.
- **New personality mode** — add a key to `POLITICAL_PROMPTS`, extend `_mode_priority()`, and include it in `commands.ALLOWED_MODES`.
- **New output guard** — add a `_is_<guard>` method to `DecisionEngine` and call it inside `_needs_rewrite()` and the post-cleanup checks.

---

## License

MIT — use at your own risk.
