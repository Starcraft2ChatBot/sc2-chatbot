# Production Ready SC2 Chat-Only Bot (AI-powered)

**Educational / research project only.**

A modular StarCraft 2 **chat-only** bot that reads lobby/game chat, decides when to reply, and responds with a configurable AI personality. Supports Google Gemini and OpenAI-compatible providers (including free models).

---

## Console Messages

<img width="845" height="720" alt="Console output example" src="https://github.com/user-attachments/assets/5fa59b94-c6bb-49ff-8e62-ca2e132bb43d" />

Live console shows `RECV` for incoming chat, `SEND` for replies, owner command results, and a transient **AI generating reply…** spinner while the model is thinking (so you can see why some responses take longer than others).

---

## Automatic AI Responses

<img width="800" height="67" alt="Automatic AI reply demo" src="https://github.com/user-attachments/assets/a7f5b6c1-4770-40b1-9224-50a225f55b82" />

The bot picks up messages from chat (including multi-line messages), runs them through anti-spam / triggers / personality, calls the LLM when needed, then types or pastes the reply back into StarCraft II after a short human-like delay.

---

## Features

- **Pluggable chat backends**
  - `simulated` — console only (safe for development)
  - `sc2_stub` — live SC2 via OCR + keyboard (high ToS risk)
- **Multi-line chat support** — long SC2 messages that wrap under the `[1. General] Name:` header are joined into one full message before being sent to the AI
- **AI progress indicator** — Rich spinner (`AI generating reply…`) appears only while the LLM is running; canned/trigger replies stay silent
- **Multi-provider LLM** — Gemini by default; also OpenAI / OpenRouter / any OpenAI-compatible endpoint (including free models from [build.nvidia.com](https://build.nvidia.com/models))
- **Rich personality controls** — aggressiveness, 7 reply modes (political + pure troll/ragebait), length, emoji, SC2 reference level, topic toggles
- **Blacklist** — block words, symbols (e.g. em dashes), letters, substrings; optional replacements
- **Favorites** — nudge the model to use preferred words/phrases more often
- **Trigger / canned-response engine** — regex patterns, priority, cooldowns, per-player limits, channel filters
- **Per-player conversation memory** (default 30 messages) with optional disk persistence
- **Clan-tag stripping** — `[LG]Serral` → `Serral` for stable memory, mute, and owner keys
- **Game-request detection** — `[1v1]`, `[2v2]`, `[host]`, `[lfg]`, etc. (optional canned replies)
- **Anti-spam** — global + per-player cooldowns, rate limits, mute list
- **Owner-only in-chat commands** (see below)
- **Human-like behaviour** — configurable reply delay, optional typos, address-by-name
- **Portable build** — one folder supports both Simulated and OCR modes via config

---

## ⚠️ Blizzard Terms of Service Warning

Any software that automatically reads chat from or injects keystrokes into the live StarCraft II client is third-party automation. Blizzard’s Terms of Service and Code of Conduct prohibit unauthorized third-party programs. Using this (or any similar) tool on a live account can result in temporary or permanent bans.

**Use at your own risk.** Prefer the **Simulated** backend for development and testing.

---

## How the bot works

1. A **Chat Backend** continuously yields new messages (OCR or simulated).
2. Names are normalized (clan tags stripped); multi-line OCR text is joined; game-request patterns are flagged.
3. The **Decision Engine** checks anti-spam, triggers, game-request handling, and memory.
4. If an LLM reply is needed, a progress spinner is shown while the model generates text (with blacklist / favorites guidance).
5. The reply is filtered through the blacklist, then sent after a short human-like delay (optional typos).

### Two backends (same program / same portable build)

| Backend     | Reads live SC2 chat? | Sends replies?     | Recommended for         |
|-------------|----------------------|--------------------|-------------------------|
| `simulated` | No                   | Yes (console)      | Development & testing   |
| `sc2_stub`  | Yes (OCR)            | Yes (keyboard)     | Live client (high risk) |

Switch by editing `config/config.yaml` → `chat_backend`, then restart.

**Chat position:** OCR uses one `chat_region` rectangle. Lobby chat is usually **bottom-right**. Measure with `tools/measure_chat_region.py`.

---

## Personality modes

The bot’s voice is controlled by `personality.political_mode` in config (the field name is historical — it also covers non-political modes).

### All modes

| Mode | Type | Behaviour |
|------|------|-----------|
| `neutral` | Neutral | Light sarcasm OK. No left/right talking points. |
| `left` | Political | Soft left lean when it fits (inequality, labor, climate, critique of the right). Chat-length, not a lecture. |
| `right` | Political | Soft right lean when it fits (free speech, borders, personal responsibility, critique of the left). Chat-length. |
| `propaganda_left` | Political (hard) | Hostile left propaganda: push progressive takes, attack the right, culture-war framing. Mean and punchy. |
| `propaganda_right` | Political (hard) | Hostile right propaganda: push conservative takes, attack the left, culture-war framing. Mean and punchy. |
| `troll` | **Non-political** | Classic internet troll. Provoke, mock, bad-faith questions, sarcasm. **No politics, no news lectures.** |
| `ragebait` | **Non-political** | Maximize annoyance: dismiss, twist their words, act superior, bait arguments. **No politics.** |

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

**Rough difference:** `troll` is a clown who wants a reaction; `ragebait` is colder and frames *them* as the problem. Political modes push ideology instead of pure mockery.

Actual wording varies with the LLM, aggressiveness, memory, length, favorites, and blacklist settings.

### Other personality knobs

| Setting | Range / values | Effect |
|---------|----------------|--------|
| `aggressiveness` | `1`–`10` | 1 = friendly, 5 = normal trash-talk, 10 = max toxic |
| `response_length` | `short` / `medium` / `long` | Word-count guidance for the model |
| `emoji_intensity` | `0`–`10` | 0 = none, 10 = emoji spam |
| `sc2_reference_level` | `0`–`10` | 0 = never mention SC2/game; 10 = full game talk |
| `topics` | booleans | Toggle politics, current_events, in_game_strategy, memes, personal |

In `troll` / `ragebait`, politics and current-events topic flags are overridden so the bot stays non-political.

### Edit in config

`config/config.yaml`:

```yaml
personality:
  aggressiveness: 8
  political_mode: "troll"    # neutral|left|right|propaganda_left|propaganda_right|troll|ragebait
  response_length: "medium"  # short|medium|long
  emoji_intensity: 0
  sc2_reference_level: 0
  topics:
    politics: true
    current_events: true
    in_game_strategy: false
    memes: false
    personal: true
```

Restart the bot after editing config, **or** use `!reload` in chat if you only changed values that reload supports (personality fields are reloaded).

### Change live with owner commands

| Command | Example | Effect |
|---------|---------|--------|
| `!prop` / `!political` / `!mode` | `!prop troll` | Set mode (`troll`, `ragebait`, `neutral`, `left`, …) |
| `!tone` / `!aggro` | `!tone 9` | Aggressiveness 1–10 |
| `!length` | `!length short` | `short` / `medium` / `long` |
| `!status` | `!status` | Show current aggro, mode, mute count |

Examples:

```text
!prop ragebait
!tone 9
!length short
!status
```

---

## Blacklist (block words & symbols)

Stops the AI (and canned replies) from using specific words, symbols, letters, or substrings. Applied **after** generation so banned text cannot slip through.

```yaml
blacklist:
  case_sensitive: false
  words: []                 # whole words/phrases removed
  symbols:                  # removed (unless replaced first)
    - "—"                   # em dash
    - "–"                   # en dash
    - "“"
    - "”"
  letters: []               # single characters to strip
  substrings: []            # removed anywhere in the string
  replacements:             # applied first
    "—": "-"
    "–": "-"
```

**Order:** `replacements` → `symbols` → `letters` → `substrings` → `words`.

The model is also told not to use banned items; the filter enforces it. If a reply becomes empty after filtering, a short fallback is used. Counts appear in the startup **ACTIVE CONFIG** log. `!reload` picks up changes.

---

## Favorites (prefer certain words)

Nudges the model to use your preferred words/phrases **more often** when they fit naturally. This is prompt guidance (not a hard insert), so intensity controls how strongly it is pushed.

```yaml
favorites:
  intensity: medium          # soft | medium | strong
  words:
    - "bruh"
    - "lmao"
    - "nah"
    - "bet"
```

| Intensity | Effect |
|-----------|--------|
| `soft` | Light preference when natural |
| `medium` | Prefer these often when they fit (default) |
| `strong` | Strongly prefer; try to use at least one when possible |

Favorites only affect **LLM** replies (not pure canned/trigger lines). They work together with the blacklist: favorite a slang word while still banning em dashes, etc.

---

## Owner commands

Only names listed under `owner.names` (and `sc2_stub.self_name`) can use these. Default prefix is `!`.

| Command | Example | Effect |
|---------|---------|--------|
| `!tone` / `!aggro` | `!tone 7` | Set aggressiveness 1–10 |
| `!prop` / `!political` / `!mode` | `!prop troll` | Set personality mode (see table above) |
| `!mute` | `!mute PlayerName` | Mute a player |
| `!unmute` | `!unmute PlayerName` | Unmute a player |
| `!length` | `!length short` | Set reply length (`short` / `medium` / `long`) |
| `!status` | `!status` | Show current aggro, mode, mute count |
| `!reload` | `!reload` | Reload config (personality, triggers, blacklist, favorites, etc.) |

Clan tags are ignored for matching, so `!mute [LG]Bob` and `!mute Bob` are the same.

Put your in-game name in **both** `owner.names` and `sc2_stub.self_name` so in-game commands are recognized.

---

## Quick Start (from source)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Edit `config/config.yaml` and set your API key (`llm.api_key` / `gemini.api_key` or environment variable).

---

## Portable folder (Simulated + OCR in one package)

Users can run a self-contained folder **without installing Python**. One build includes **both** modes; switch by editing config.

### Build the portable folder (developer machine)

**Windows:**
```bat
scripts\build_portable.bat
```

**Linux / macOS:**
```bash
chmod +x scripts/build_portable.sh
./scripts/build_portable.sh
```

Output:

```text
dist/SC2ChatBot/
├── SC2ChatBot.exe          # or SC2ChatBot on Unix
├── config/
│   ├── config.yaml         # users edit this
│   └── config.example.yaml
├── tools/
│   └── measure_chat_region.py
├── README_PORTABLE.txt
└── SWITCH_MODES.txt
```

Zip and share `dist/SC2ChatBot/`. Paths resolve next to the executable so config/logs work after moving the folder.

### End-user: Simulated mode

1. Open `config/config.yaml`
2. Set your API key
3. Keep `chat_backend: "simulated"`
4. Run `SC2ChatBot.exe`

### End-user: OCR mode (same folder)

1. Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
2. Measure chat box → set `sc2_stub.chat_region`
3. Set:
   ```yaml
   chat_backend: "sc2_stub"
   sc2_stub:
     ocr_enabled: true
     chat_region: [left, top, width, height]
   ```
4. Restart the exe with SC2 visible (windowed)

See `portable/SWITCH_MODES.txt` (copied into the dist folder).

**Note:** OCR still depends on system Tesseract unless you separately bundle it. Keyboard/OCR access is OS-dependent.

---

## Enabling live SC2 chat (from source)

```bash
pip install mss Pillow pytesseract pyautogui PyGetWindow
python tools/measure_chat_region.py
```

Then in `config/config.yaml`:

```yaml
chat_backend: "sc2_stub"
sc2_stub:
  ocr_enabled: true
  chat_region: [1420, 680, 480, 300]   # your values
```

Run SC2 in Windowed / Windowed Fullscreen. Lobby chat is typically bottom-right.

The OCR parser joins multi-line messages: text that continues below a `[1. General] Name:` header is treated as part of the same message and sent in full to the AI.

---

## Player names, game requests & memory

- **Clan tags** stripped for memory / mute / owner keys; display name kept when useful
- **Game requests** (`[1v1]`, `[host]`, LFG text, …) can use short canned replies
- **Memory:** up to 30 messages per player; optional `persist_path: "logs/memory.json"`

```yaml
behaviour:
  reply_to_game_requests: true
  game_request_use_canned: true
```

---

## API keys

### Gemini
1. Go to https://aistudio.google.com/
2. Create an API key
3. Put it in `config/config.yaml` (`llm.api_key` or `gemini.api_key`) or set `GEMINI_API_KEY`

### NVIDIA models (build.nvidia.com)

[build.nvidia.com/models](https://build.nvidia.com/models) hosts many free / freemium LLMs (Llama, Nemotron, DeepSeek, Mixtral, Gemma, etc.) behind an **OpenAI-compatible** API.

**How it works with this bot**

1. You pick a model on the site and get an NVIDIA API key.
2. The bot’s `LLMClient` talks to NVIDIA’s hosted endpoint using the standard OpenAI chat-completions protocol (`base_url` + `api_key` + `model`).
3. No special NVIDIA SDK is required beyond the optional `openai` Python package.

**Endpoint used by the bot**

| Setting | Value |
|---------|--------|
| Base URL | `https://integrate.api.nvidia.com/v1` |
| Auth | Bearer token = your NVIDIA API key |
| Protocol | OpenAI Chat Completions (`/v1/chat/completions`) |

**Get an API key**

1. Open https://build.nvidia.com/models and sign in (NVIDIA account).
2. Click your profile → **API Keys** (or the key prompt on a model page).
3. Generate a key and copy it (you won’t see it again).

**Install the dependency (PowerShell)**

The NVIDIA path uses the OpenAI-compatible client, which is optional in `requirements.txt`. Install it in your venv:

```powershell
# From the project root, with the venv activated
.\.venv\Scripts\Activate.ps1
pip install openai>=1.0.0
```

Or install everything needed for OpenAI-compatible providers in one go:

```powershell
pip install openai>=1.0.0
```

**Configure `config/config.yaml`**

```yaml
llm:
  provider: "openai_compatible"   # or openai / custom / openrouter
  api_key: "nvapi-YOUR_KEY_HERE"
  model: "meta/llama-3.3-70b-instruct"   # any id from build.nvidia.com/models
  base_url: "https://integrate.api.nvidia.com/v1"
  temperature: 0.9
  max_output_tokens: 120
```

Model IDs are the full names shown on the site (e.g. `meta/llama-3.3-70b-instruct`, `nvidia/llama-3.1-nemotron-70b-instruct`, `mistralai/mixtral-8x22b-instruct-v0.1`). Check the model card for the exact string and rate limits / free tier details.

Restart the bot after changing the config. The console will log something like `LLM provider=openai_compatible model=… base_url=https://integrate.api.nvidia.com/v1`.

### Other OpenAI-compatible providers

Set `llm.provider` to `openai`, `openai_compatible`, `openrouter`, or `custom`, and supply `api_key`, `model`, and optionally `base_url`. Same `openai` package as above.

---

## Configuration overview

All settings live in `config/config.yaml`:

| Section | Purpose |
|---------|---------|
| `llm` / `gemini` | Provider, model, API key, temperature, max tokens |
| `owner` | Owner names + command prefix |
| `personality` | Aggressiveness, mode (`troll` / political / …), length, emoji, SC2 ref level, topics |
| `blacklist` | Ban words, symbols, letters, substrings; replacements |
| `favorites` | Preferred words/phrases + intensity (`soft` / `medium` / `strong`) |
| `behaviour` | Reply delays, probability, typos, game-request handling, address-by-name |
| `anti_spam` | Cooldowns, rate limits, mute list |
| `memory` | Per-player history size + optional persistence path |
| `triggers` / `canned_blocks` | Regex triggers and canned replies |
| `chat_backend` | `simulated` or `sc2_stub` |
| `sc2_stub` | OCR region, keys, Tesseract path, tab switching |
| `logging` | Level, file, console |

---

## Architecture

```text
sc2_chatbot/
├── config/                     # config.yaml + example
├── portable/                   # texts shipped inside dist/
├── scripts/build_portable.*    # build the portable folder
├── tools/measure_chat_region.py
├── SC2ChatBot.spec             # PyInstaller
├── src/
│   ├── bot.py                  # main loop, process message, send
│   ├── decision_engine.py      # triggers → LLM → blacklist/favorites → reply
│   ├── llm_client.py           # Gemini + OpenAI-compatible
│   ├── chat/
│   │   ├── sc2_stub.py         # OCR + multi-line parse + keyboard send
│   │   └── simulated.py        # console backend
│   ├── personality.py          # system prompt builder
│   ├── triggers.py             # regex / canned engine
│   ├── anti_spam.py
│   ├── memory.py
│   ├── commands.py             # owner !commands
│   ├── names.py                # clan-tag strip, OCR name cleanup
│   └── …
└── main.py
```

---

## License

MIT – use at your own risk.
