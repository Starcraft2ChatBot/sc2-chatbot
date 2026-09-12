# SC2 Chat-Only Bot (AI-powered)

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
- **Rich personality controls**
  - Aggressiveness 1–10
  - Political modes: `neutral` | `left` | `right` | `propaganda_left` | `propaganda_right`
  - Response length: `short` | `medium` | `long`
  - Emoji intensity, SC2 reference level (0 = never mention the game), topic toggles
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
4. If an LLM reply is needed, a progress spinner is shown while the model generates text.
5. The reply is sent after a short human-like delay (optional typos).

### Two backends (same program / same portable build)

| Backend     | Reads live SC2 chat? | Sends replies?     | Recommended for         |
|-------------|----------------------|--------------------|-------------------------|
| `simulated` | No                   | Yes (console)      | Development & testing   |
| `sc2_stub`  | Yes (OCR)            | Yes (keyboard)     | Live client (high risk) |

Switch by editing `config/config.yaml` → `chat_backend`, then restart.

**Chat position:** OCR uses one `chat_region` rectangle. Lobby chat is usually **bottom-right**. Measure with `tools/measure_chat_region.py`.

---

## Owner commands

Only names listed under `owner.names` in config can use these. Default prefix is `!`.

| Command | Example | Effect |
|---------|---------|--------|
| `!tone` / `!aggro` | `!tone 7` | Set aggressiveness 1–10 |
| `!prop` / `!political` | `!prop propaganda_left` | Set political mode |
| `!mute` | `!mute PlayerName` | Mute a player |
| `!unmute` | `!unmute PlayerName` | Unmute a player |
| `!length` | `!length short` | Set reply length (`short` / `medium` / `long`) |
| `!status` | `!status` | Show current aggro, political mode, mute count |
| `!reload` | `!reload` | Reload config (personality, triggers, etc.) |

Clan tags are ignored for matching, so `!mute [LG]Bob` and `!mute Bob` are the same.

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
1. https://aistudio.google.com/
2. Create an API key
3. Put it in `config/config.yaml` (`llm.api_key` or `gemini.api_key`) or set `GEMINI_API_KEY`

### Other providers
Set `llm.provider` to `openai`, `openai_compatible`, `openrouter`, or `custom`, and supply `api_key`, `model`, and optionally `base_url`. Free models from NVIDIA and similar hosts work via the OpenAI-compatible path.

---

## Configuration overview

All settings live in `config/config.yaml`:

| Section | Purpose |
|---------|---------|
| `llm` / `gemini` | Provider, model, API key, temperature, max tokens |
| `owner` | Owner names + command prefix |
| `personality` | Aggressiveness, political mode, length, emoji, SC2 ref level, topics |
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
│   ├── decision_engine.py      # triggers → LLM → reply (+ progress spinner)
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
