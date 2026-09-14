# Production Ready SC2 Chat-Only Bot (AI-powered)

**Educational / research project only.**

A modular StarCraft 2 **chat-only** bot that reads lobby/game chat, decides when to reply, and responds with a configurable AI personality. Supports Google Gemini, OpenAI-compatible cloud APIs (NVIDIA, OpenRouter, etc.), and **local models via Ollama**.

---

## Console Messages

<img width="845" height="720" alt="Console output example" src="https://github.com/user-attachments/assets/5fa59b94-c6bb-49ff-8e62-ca2e132bb43d" />

Live console shows `RECV` for incoming chat, `SEND` for replies, owner command results, a startup **ACTIVE CONFIG** dump, and a transient **AI generating reply…** spinner while the model is running (so you can see why some responses take longer than others).

---

## Automatic AI Responses

<img width="800" height="67" alt="Automatic AI reply demo" src="https://github.com/user-attachments/assets/a7f5b6c1-4770-40b1-9224-50a225f55b82" />

The bot picks up messages from chat (including multi-line messages), runs them through anti-spam / triggers / personality, calls the LLM when needed, then types or pastes the reply back into StarCraft II after a short human-like delay.

If the model returns empty or only planning/meta text, **no reply is sent** (no canned fallback lines).

---

## Features

- **Pluggable chat backends**
  - `simulated` — console only (safe for development)
  - `sc2_stub` — live SC2 via OCR + keyboard (high ToS risk)
- **Multi-line chat support** — long SC2 messages that wrap under the `[1. General] Name:` header are joined into one full message before being sent to the AI
- **AI progress indicator** — Rich spinner (`AI generating reply…`) while the LLM runs; canned/trigger replies stay silent
- **Multi-provider LLM**
  - Gemini
  - OpenAI-compatible (OpenRouter, NVIDIA [build.nvidia.com](https://build.nvidia.com/models), DeepSeek, LM Studio, …)
  - **Local Ollama** (`provider: ollama`, e.g. `qwen3.5:9b`)
- **`llm.think` toggle** — enable or disable chain-of-thought for all models that support it (recommended **off** for fast lobby chat)
- **Timeouts & diagnostics** — configurable request/connect timeouts; structured logs for empty replies, timeouts, connection errors, and missing models
- **Rich personality controls** — aggressiveness, 7 modes (political + troll/ragebait), length, SC2 reference level, topic toggles
- **Emojis disabled** — prompts and output strip emojis entirely (`emoji_intensity` is ignored)
- **Blacklist** — block words, symbols (e.g. em dashes), letters, substrings; optional replacements
- **Favorites** — nudge preferred words/phrases
- **Occasional name addressing** — `address_by_name` + `address_by_name_chance` (0.0–1.0)
- **Trigger / canned-response engine** — regex, priority, cooldowns, channel filters
- **Per-player conversation memory** (default 30 messages) with optional disk persistence
- **Clan-tag stripping** — `[LG]Serral` → `Serral` for stable memory/mute/owner keys
- **Game-request detection** — optional canned replies for `[1v1]`, `[host]`, LFG, etc.
- **Anti-spam** — global + per-player cooldowns, rate limits, mute list
- **Owner-only in-chat commands**
- **Human-like behaviour** — reply delay, optional typos, casual typing rules in the system prompt
- **Portable build** — one folder for Simulated and OCR modes

---

## ⚠️ Blizzard Terms of Service Warning

Any software that automatically reads chat from or injects keystrokes into the live StarCraft II client is third-party automation. Blizzard’s Terms of Service and Code of Conduct prohibit unauthorized third-party programs. Using this (or any similar) tool on a live account can result in temporary or permanent bans.

**Use at your own risk.** Prefer the **Simulated** backend for development and testing.

---

## How the bot works

1. A **Chat Backend** yields new messages (OCR or simulated).
2. Names are normalized; multi-line OCR text is joined; game-request patterns are flagged.
3. The **Decision Engine** checks anti-spam, triggers, game-request handling, and memory.
4. If an LLM reply is needed, a spinner is shown while the model generates text (with blacklist / favorites guidance and optional `think` control).
5. The reply is cleaned (no meta/planning dumps, no emojis), filtered through the blacklist, optionally prefixed with the player name, then sent after a short delay.

### Two backends (same program)

| Backend     | Reads live SC2 chat? | Sends replies?     | Recommended for         |
|-------------|----------------------|--------------------|-------------------------|
| `simulated` | No                   | Yes (console)      | Development & testing   |
| `sc2_stub`  | Yes (OCR)            | Yes (keyboard)     | Live client (high risk) |

Switch with `chat_backend` in `config/config.yaml`, then restart.

**Chat position:** OCR uses one `chat_region` rectangle (usually bottom-right in lobby). Measure with `tools/measure_chat_region.py`.

---

## LLM providers

### Thinking (`llm.think`)

```yaml
llm:
  think: false   # recommended for SC2 chat
  # think: true  # allow chain-of-thought where the API supports it
```

| Value | Effect |
|-------|--------|
| `false` | Disable thinking (Ollama native `think: false`; OpenAI-compatible `extra_body.think: false` when accepted). Faster; avoids empty `content` / planning dumps on Qwen3-style models. |
| `true` | Allow thinking on models that support it. Slower; can help harder prompts. |

**Changing `think` requires a full bot restart** (not only `!reload`).

### Timeouts

```yaml
llm:
  request_timeout_sec: 60    # wait for full reply (default 60 cloud / 120 local if unset)
  connect_timeout_sec: 10    # initial connect
```

Raise `request_timeout_sec` (e.g. `120`–`180`) for slow local models.

### Local Ollama

1. Install [Ollama](https://ollama.com/) and pull a model:
   ```bash
   ollama pull qwen3.5:9b
   ollama list
   ```
2. Keep Ollama running (`ollama serve` if needed).
3. Config:

```yaml
llm:
  provider: "ollama"
  api_key: "ollama"
  model: "qwen3.5:9b"          # exact name from `ollama list` (no ollama/ prefix)
  temperature: 0.9
  max_output_tokens: 150
  base_url: "http://127.0.0.1:11434/v1"
  think: false
  request_timeout_sec: 120
```

The bot calls Ollama’s native `/api/chat` with `think` from config, then falls back to the OpenAI-compatible path if needed.

**Tips for Qwen3 / thinking models:** keep `think: false`, `temperature` around `0.9`, and `max_output_tokens` around `120`–`150` so replies stay short and land in `content` instead of only in a reasoning field.

### Gemini

1. https://aistudio.google.com/ → create an API key  
2. Set `llm.api_key` / `gemini.api_key` or `GEMINI_API_KEY`

```yaml
llm:
  provider: "gemini"
  api_key: "YOUR_KEY"
  model: "gemini-2.0-flash"
  think: false
```

### NVIDIA (build.nvidia.com)

[build.nvidia.com/models](https://build.nvidia.com/models) — OpenAI-compatible API.

| Setting | Value |
|---------|--------|
| Base URL | `https://integrate.api.nvidia.com/v1` |
| Auth | Bearer = NVIDIA API key |

**PowerShell dependency:**

```powershell
.\.venv\Scripts\Activate.ps1
pip install openai>=1.0.0
```

```yaml
llm:
  provider: "openai_compatible"
  api_key: "nvapi-YOUR_KEY"
  model: "meta/llama-3.3-70b-instruct"
  base_url: "https://integrate.api.nvidia.com/v1"
  temperature: 0.9
  max_output_tokens: 120
  think: false
```

### Other OpenAI-compatible (OpenRouter, LM Studio, …)

Same pattern: `provider: openai_compatible` (or `openrouter` / `custom`), `api_key`, `model`, `base_url`.

---

## Personality modes

Controlled by `personality.political_mode` (name is historical — includes non-political modes).

| Mode | Type | Behaviour |
|------|------|-----------|
| `neutral` | Neutral | Light sarcasm. No left/right talking points. |
| `left` | Political | Soft left lean when natural. |
| `right` | Political | Soft right lean when natural. |
| `propaganda_left` | Political (hard) | Hostile left propaganda; culture-war framing. |
| `propaganda_right` | Political (hard) | Hostile right propaganda; culture-war framing. |
| `troll` | **Non-political** | Classic troll: provoke, mock, bad-faith. No politics. |
| `ragebait` | **Non-political** | Maximize annoyance; dismiss and bait. No politics. |

### Example reactions

**They say:** `gg ez`

| Mode | Example reply |
|------|----------------|
| `troll` | `bro typed gg ez with 200 apm and still lost` |
| `ragebait` | `projecting already? cute` |

**They say:** `why you so toxic`

| Mode | Example reply |
|------|----------------|
| `troll` | `because you keep typing and i keep winning the argument` |
| `ragebait` | `you’re the one still talking` |

### Other knobs

| Setting | Values | Effect |
|---------|--------|--------|
| `aggressiveness` | `1`–`10` | Friendly → max toxic |
| `response_length` | `short` / `medium` / `long` | Word-count guidance |
| `emoji_intensity` | ignored | **Emojis always disabled** |
| `sc2_reference_level` | `0`–`10` | Never mention game → full game talk |
| `topics` | booleans | politics, current_events, in_game_strategy, memes, personal |

### Config example

```yaml
personality:
  aggressiveness: 8
  political_mode: "troll"
  response_length: "medium"
  emoji_intensity: 0
  sc2_reference_level: 0
  topics:
    politics: true
    current_events: true
    in_game_strategy: false
    memes: false
    personal: true
```

### Live owner commands

| Command | Example | Effect |
|---------|---------|--------|
| `!prop` / `!political` / `!mode` | `!prop troll` | Set mode |
| `!tone` / `!aggro` | `!tone 9` | Aggressiveness 1–10 |
| `!length` | `!length short` | short / medium / long |
| `!status` | `!status` | Show aggro, mode, mute count |

---

## Blacklist

Applied **after** generation to AI and canned replies.

```yaml
blacklist:
  case_sensitive: false
  words: []
  symbols:
    - "—"
  letters: []
  substrings: []
  replacements:
    "—": "-"
```

**Order:** replacements → symbols → letters → substrings → words.  
If a reply is empty after filtering, nothing is sent.

---

## Favorites

Prompt nudge only (not forced insert):

```yaml
favorites:
  intensity: medium          # soft | medium | strong
  words:
    - "bruh"
    - "lmao"
```

---

## Behaviour highlights

```yaml
behaviour:
  min_reply_delay_sec: 0.35
  max_reply_delay_sec: 0.8
  typo_chance: 0.0
  reply_probability: 1.0
  address_by_name: true
  address_by_name_chance: 0.3   # 0.0 never … 1.0 every reply
  name_separator: ", "
  reply_to_game_requests: false
  game_request_use_canned: false
```

---

## Owner commands

Only `owner.names` (and `sc2_stub.self_name`) can use these. Default prefix `!`.

| Command | Example | Effect |
|---------|---------|--------|
| `!tone` / `!aggro` | `!tone 7` | Aggressiveness 1–10 |
| `!prop` / `!mode` | `!prop troll` | Personality mode |
| `!mute` / `!unmute` | `!mute PlayerName` | Mute / unmute |
| `!length` | `!length short` | Reply length |
| `!status` | `!status` | Status |
| `!reload` | `!reload` | Reload config (personality, triggers, blacklist, favorites, …). **LLM provider / think / model need a full restart.** |

Put your in-game name in **both** `owner.names` and `sc2_stub.self_name`.

---

## Quick Start (from source)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Edit `config/config.yaml` (API key, provider, `think`, timeouts).

---

## Portable folder

**Windows:** `scripts\build_portable.bat`  
**Linux / macOS:** `./scripts/build_portable.sh`

Output under `dist/SC2ChatBot/`. Users edit `config/config.yaml` and run the executable. Switch Simulated ↔ OCR via `chat_backend` (OCR needs system Tesseract).

---

## Enabling live SC2 chat (from source)

```bash
pip install mss Pillow pytesseract pyautogui PyGetWindow
python tools/measure_chat_region.py
```

```yaml
chat_backend: "sc2_stub"
sc2_stub:
  ocr_enabled: true
  chat_region: [1420, 680, 480, 300]
  self_name: "YourInGameName"
```

Run SC2 windowed. Multi-line messages under `[1. General] Name:` are joined before the AI sees them.

---

## Configuration overview

| Section | Purpose |
|---------|---------|
| `llm` | Provider, model, key, temperature, tokens, **`think`**, **timeouts**, `base_url` |
| `gemini` | Legacy Gemini fields (used if `llm` is omitted) |
| `owner` | Owner names + command prefix |
| `personality` | Mode, aggro, length, SC2 ref, topics (emojis always off) |
| `blacklist` | Banned words/symbols/letters/substrings + replacements |
| `favorites` | Preferred vocabulary + intensity |
| `behaviour` | Delays, typos, reply probability, name addressing chance, game requests |
| `anti_spam` | Cooldowns, rate limits, mute list |
| `memory` | History size + `persist_path` |
| `triggers` / `canned_blocks` | Regex triggers and canned lines |
| `chat_backend` | `simulated` or `sc2_stub` |
| `sc2_stub` | OCR region, keys, Tesseract, tabs |
| `logging` | Level, file, console |

Startup prints an **ACTIVE CONFIG** summary (including `think`).

---

## Architecture

```text
sc2_chatbot/
├── config/                     # config.yaml + example
├── portable/
├── scripts/build_portable.*
├── tools/measure_chat_region.py
├── src/
│   ├── bot.py                  # main loop, config summary, LLM wiring
│   ├── decision_engine.py      # triggers → LLM → blacklist/favorites → reply
│   ├── llm_client.py           # Gemini + OpenAI-compatible + Ollama native
│   ├── chat/
│   │   ├── sc2_stub.py         # OCR + multi-line parse + keyboard
│   │   └── simulated.py
│   ├── personality.py
│   ├── triggers.py
│   ├── anti_spam.py
│   ├── memory.py
│   ├── commands.py
│   └── …
└── main.py
```

---

## License

MIT – use at your own risk.
