# SC2 Chat-Only Bot (Gemini-powered)

**Educational / research project only.**

A modular, production-oriented StarCraft 2 **chat-only** bot that:
- Monitors chat (all / team / whispers) via a pluggable backend
- Automatically decides whether to reply
- Uses Google Gemini with highly configurable personality
- Supports aggressiveness slider (1–10), political modes (neutral / left / right / full propaganda), topic controls, response length & emoji intensity
- Has a powerful trigger / canned-response engine (regex, priority, cooldowns, per-player limits)
- Maintains **longer per-player conversation memory** (default 30 messages) with optional disk persistence
- **Strips clan tags** from player names (`[LG]Serral` → `Serral`) for stable memory / mute keys
- **Detects game requests** such as `[1v1]`, `[2v2]`, `[host]`, `[lfg]`
- Includes anti-spam, mute list, rate limiting and owner-only commands
- Uses realistic human-like delays and occasional typos

## ⚠️ Blizzard Terms of Service Warning

Any software that automatically reads chat from or injects keystrokes into the live StarCraft II client is third-party automation. Blizzard’s Terms of Service and Code of Conduct prohibit unauthorized third-party programs. Using this (or any similar) tool on a live account can result in temporary or permanent bans.

**Use at your own risk.** Prefer the included **Simulated** backend for development and testing.

---

## How the bot works (automatic replies)

The full pipeline is already implemented and automatic:

1. A **Chat Backend** continuously yields new messages.
2. Names are normalized (clan tags stripped); game-request patterns are flagged.
3. The **Decision Engine** checks anti-spam rules, reply probability, triggers, game-request handling, and conversation memory.
4. If no canned trigger / game-request reply matches, it builds a system prompt from the current personality settings and calls **Google Gemini**.
5. The reply is sent back through the same backend after a human-like delay (with optional minor typos).

So once messages are successfully fed into the bot, it **will automatically respond with AI-generated replies** according to your personality, aggressiveness, political mode, etc.

### Two backends are included

| Backend       | Reads live SC2 chat? | Sends replies? | Recommended for          |
|---------------|----------------------|----------------|--------------------------|
| `simulated`   | No (you inject messages) | Yes (prints)  | Development & testing   |
| `sc2_stub`    | Yes (via OCR)        | Yes (keyboard) | Live client (high risk) |

The **completed SC2 stub** (`src/chat/sc2_stub.py`) includes:
- Robust window focusing + human-like keyboard typing for sending
- Optional screen OCR reader (mss + pytesseract) for reading the on-screen chat box
- Message parsing (including clan-tagged names), deduplication, and basic channel detection

**Note on chat position:** OCR does **not** auto-detect lobby vs in-game layout. You set one `chat_region` rectangle. Lobby / menu chat is usually **bottom-right**; in-game chat is often bottom-left. Use the helper script below to measure your region.

---

## Quick Start (Simulated mode – recommended)

This is the safe way to test personality, triggers, and Gemini replies.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

On the first run the bot automatically creates `config/config.yaml` from the example if it is missing.  
Edit that file and put your Gemini API key (or set the `GEMINI_API_KEY` environment variable) and run again.

---

## Enabling live SC2 chat reading + automatic AI replies

To make the bot **read real chat and automatically respond with Gemini** (high ToS risk):

### 1. Install extra dependencies
```bash
pip install mss Pillow pytesseract pyautogui PyGetWindow
```
Also install the [Tesseract OCR binary](https://github.com/tesseract-ocr/tesseract) on your system.

### 2. Measure the chat box (`chat_region`)

Lobby / out-of-game chat is typically in the **bottom-right**. Measure it with the included helper:

```bash
python tools/measure_chat_region.py
```

1. Run SC2 in **Windowed** or **Windowed Fullscreen** with chat visible.
2. Move the mouse to the **top-left** corner of the chat box → press Enter.
3. Move the mouse to the **bottom-right** corner → press Enter.
4. Copy the printed line into config, for example:

```yaml
chat_region: [1420, 680, 480, 300]
```

### 3. Edit `config/config.yaml`

```yaml
chat_backend: "sc2_stub"          # switch from "simulated"

sc2_stub:
  window_title: "StarCraft II"
  chat_key: "enter"
  send_key: "enter"
  typing_speed_cps: 11

  ocr_enabled: true
  poll_interval_sec: 1.8

  # From tools/measure_chat_region.py — lobby chat is usually bottom-right
  chat_region: [1420, 680, 480, 300]   # ← your values

  # Optional: full path to tesseract if not in PATH
  # tesseract_cmd: "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
```

### 4. Important OCR requirements
- Run StarCraft II in **Windowed** or **Windowed Fullscreen** (exclusive fullscreen usually fails).
- The chat box must be visible on screen.
- One fixed `chat_region` cannot cover both lobby (bottom-right) and in-game (often bottom-left) at once — re-measure if you switch screens.
- OCR quality depends on resolution, UI scale, font, and background. It is never 100% accurate.

### 5. Run the bot
```bash
python main.py
```

Once messages appear in the configured screen region, the bot processes them through the full decision engine and replies with Gemini (or a canned / game-request reply if one matches).

---

## Player names, game requests & memory

### Clan-tag stripping
Names like `[LG]Serral`, `{TSM}ByuN`, or `<Liquid>Clem` are normalized for memory, mute, and owner checks. The original display name is kept when useful for prompts.

### Game-request detection
Messages that look like lobby / game invites are flagged, including:
- Bracket forms: `[1v1]`, `[2v2 me]`, `[host]`, `[lfg]`, `[zerg only]`, …
- Loose forms: `wanna 1v1`, `looking for game`, `hosting 2v2`, …

By default the bot can answer these with short natural lines (`gl hf`, `inv me`, …). Configure under `behaviour`:

```yaml
behaviour:
  reply_to_game_requests: true
  game_request_use_canned: true   # false = always use Gemini for these
```

### Longer / persistent memory
```yaml
memory:
  max_messages_per_player: 30
  persist_path: "logs/memory.json"   # set null to disable disk persistence
```

Conversation history is stored **per player** (incoming + bot replies) so Gemini gets coherent context. With `persist_path` set, memory survives restarts.

---

## Obtaining a Gemini API Key

1. Go to https://aistudio.google.com/
2. Create an API key
3. Restrict it if possible

---

## Configuration overview

All settings live in `config/config.yaml` (and `config/config.example.yaml`).

Key sections:
- `personality` – aggressiveness, political mode, length, emoji intensity, topic biases
- `triggers` / `canned_blocks` – regex or phrase → fixed reply (takes priority over Gemini)
- `anti_spam` – cooldowns, mute list, rate limits
- `behaviour` – reply probability, delay range, typo chance, game-request handling
- `memory` – history length + optional persistence path
- `owner` – names that can use `!tone`, `!prop`, `!mute`, `!reload`, `!status`, etc.
- `chat_backend` / `sc2_stub` – simulated vs live OCR + keyboard

Owner commands work in any channel when sent by a name listed under `owner.names` (clan tags optional; names are normalized).

---

## Architecture

```
sc2_chatbot/
├── config/
│   ├── config.yaml
│   └── config.example.yaml
├── tools/
│   └── measure_chat_region.py   # mouse helper for chat_region
├── src/
│   ├── chat/                    # abstract backend + simulated + SC2 stub
│   ├── names.py                 # clan-tag stripping / memory keys
│   ├── game_requests.py         # [1v1] / LFG detection
│   ├── models.py
│   ├── config_loader.py
│   ├── logger.py
│   ├── gemini_client.py
│   ├── personality.py
│   ├── triggers.py
│   ├── memory.py                # longer + optional persistent memory
│   ├── anti_spam.py
│   ├── commands.py
│   ├── decision_engine.py
│   └── bot.py
└── main.py
```

The design is modular: swap the backend and the rest of the AI / personality / anti-spam stack continues to work unchanged.

---

## Extending further

You can implement your own `ChatBackend` subclass if you prefer a different reading method (memory reading, log tailing, etc.). Just implement `connect`, `disconnect`, `listen`, `send`, and `is_connected`.

Memory-reading approaches exist in the community but carry even higher detection risk and are outside the scope of this repository.

---

## License

MIT – use at your own risk.
