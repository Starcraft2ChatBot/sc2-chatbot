# SC2 Chat-Only Bot (Gemini-powered)

**Educational / research project only.**

A modular, production-oriented StarCraft 2 **chat-only** bot that:
- Monitors in-game chat (all / team / whispers)
- Automatically decides whether to reply
- Uses Google Gemini with highly configurable personality
- Supports aggressiveness slider (1–10), political modes (neutral / left / right / full propaganda), topic controls, response length & emoji intensity
- Has a powerful trigger / canned-response engine (regex, priority, cooldowns, per-player limits)
- Maintains short per-player conversation memory
- Includes anti-spam, mute list, rate limiting and owner-only commands
- Uses realistic human-like delays and occasional typos

## ⚠️ Blizzard Terms of Service Warning

Any software that automatically reads chat from or injects keystrokes into the live StarCraft II client is third-party automation. Blizzard’s Terms of Service and Code of Conduct prohibit unauthorized third-party programs. Using this (or any similar) tool on a live account can result in temporary or permanent bans.

**Use at your own risk.** Prefer the included **Simulated** backend for development and testing.

---

## How the bot works (automatic replies)

The full pipeline is already implemented and automatic:

1. A **Chat Backend** continuously yields new messages.
2. The **Decision Engine** checks anti-spam rules, reply probability, triggers, and conversation memory.
3. If no canned trigger matches, it builds a system prompt from the current personality settings and calls **Google Gemini**.
4. The reply is sent back through the same backend after a human-like delay (with optional minor typos).

So once messages are successfully fed into the bot, it **will automatically respond with AI-generated replies** according to your personality, aggressiveness, political mode, etc.

### Two backends are included

| Backend       | Reads live SC2 chat? | Sends replies? | Recommended for          |
|---------------|----------------------|----------------|--------------------------|
| `simulated`   | No (you inject messages) | Yes (prints)  | Development & testing   |
| `sc2_stub`    | Yes (via OCR)        | Yes (keyboard) | Live client (high risk) |

The **completed SC2 stub** (`src/chat/sc2_stub.py`) includes:
- Robust window focusing + human-like keyboard typing for sending
- Optional screen OCR reader (mss + pytesseract) for reading the on-screen chat box
- Message parsing, deduplication, and basic channel detection

---

## Quick Start (Simulated mode – recommended)

This is the safe way to test personality, triggers, and Gemini replies.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

On the first run the bot automatically creates `config/config.yaml` from the example.  
Then edit that file and put your Gemini API key (or set the `GEMINI_API_KEY` environment variable) and run again.

You can inject test messages into the simulated backend to see the AI reply in real time.

---

## Enabling live SC2 chat reading + automatic AI replies

To make the bot **read real in-game chat and automatically respond with Gemini**:

### 1. Install extra dependencies
```bash
pip install mss Pillow pytesseract pyautogui PyGetWindow
```
Also install the [Tesseract OCR binary](https://github.com/tesseract-ocr/tesseract) on your system.

### 2. Edit `config/config.yaml`

```yaml
chat_backend: "sc2_stub"          # switch from "simulated"

sc2_stub:
  window_title: "StarCraft II"
  chat_key: "enter"
  send_key: "enter"
  typing_speed_cps: 11

  # Enable the OCR reader
  ocr_enabled: true
  poll_interval_sec: 1.8

  # Critical: pixel coordinates of the chat box (left, top, width, height)
  # Measure these carefully while SC2 is running in Windowed / Windowed Fullscreen
  chat_region: [20, 650, 480, 220]   # ← example only – change to your values

  # Optional: full path to tesseract executable if not in PATH
  # tesseract_cmd: "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
```

### 3. Important requirements for OCR to work
- Run StarCraft II in **Windowed** or **Windowed Fullscreen** mode (exclusive fullscreen usually fails).
- The chat box must be visible on screen.
- Measure the exact pixel region of the chat area (tools like ShareX, Greenshot, or a simple Python screenshot script help).
- OCR quality depends on resolution, UI scale, font, and background. It is never 100 % accurate.

### 4. Run the bot
```bash
python main.py
```

Once messages appear in the configured screen region, the bot will automatically process them through the full decision engine and reply with Gemini (or a canned trigger if one matches).

---

## Obtaining a Gemini API Key

1. Go to https://aistudio.google.com/
2. Create an API key
3. Restrict it if possible

---

## Configuration overview

All settings live in `config/config.yaml` (auto-created from the example on first run).

Key sections:
- `personality` – aggressiveness, political mode, length, emoji intensity, topic biases
- `triggers` / `canned_blocks` – regex or phrase → fixed reply (takes priority over Gemini)
- `anti_spam` – cooldowns, mute list, rate limits
- `behaviour` – reply probability, delay range, typo chance
- `owner` – names that can use `!tone`, `!prop`, `!mute`, `!reload`, `!status`, etc.

Owner commands work in any channel when sent by a name listed under `owner.names`.

---

## Architecture

```
sc2_chatbot/
├── config/
├── src/
│   ├── chat/               # abstract backend + simulated + completed SC2 stub
│   ├── models.py
│   ├── config_loader.py
│   ├── logger.py
│   ├── gemini_client.py
│   ├── personality.py
│   ├── triggers.py
│   ├── memory.py
│   ├── anti_spam.py
│   ├── commands.py
│   ├── decision_engine.py  # decides when/how to reply (triggers → Gemini)
│   └── bot.py              # main loop
└── main.py
```

The design is deliberately modular: swap the backend and the rest of the AI/personality/anti-spam stack continues to work unchanged.

---

## Extending further

You can implement your own `ChatBackend` subclass if you prefer a different reading method (memory reading, log tailing, etc.). Just implement `connect`, `disconnect`, `listen`, `send`, and `is_connected`.

Memory-reading approaches exist in the community but carry even higher detection risk and are outside the scope of this repository.

---

## License

MIT – use at your own risk.
