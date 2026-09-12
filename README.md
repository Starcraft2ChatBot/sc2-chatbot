# Console Messages
<img width="845" height="720" alt="image" src="https://github.com/user-attachments/assets/5fa59b94-c6bb-49ff-8e62-ca2e132bb43d" />

# SC2 Chat-Only Bot (Gemini-powered) | Multiple AI Support Available

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
- Can be shipped as a **portable folder** (one build supports **both** Simulated and OCR modes via config)

## ⚠️ Blizzard Terms of Service Warning

Any software that automatically reads chat from or injects keystrokes into the live StarCraft II client is third-party automation. Blizzard’s Terms of Service and Code of Conduct prohibit unauthorized third-party programs. Using this (or any similar) tool on a live account can result in temporary or permanent bans.

**Use at your own risk.** Prefer the included **Simulated** backend for development and testing.

---

## How the bot works (automatic replies)

1. A **Chat Backend** continuously yields new messages.
2. Names are normalized (clan tags stripped); game-request patterns are flagged.
3. The **Decision Engine** checks anti-spam, triggers, game-request handling, and memory.
4. If needed, it calls **Google Gemini** with the current personality settings.
5. The reply is sent after a human-like delay (optional typos).

### Two backends (same program / same portable build)

| Backend       | Reads live SC2 chat? | Sends replies? | Recommended for          |
|---------------|----------------------|----------------|--------------------------|
| `simulated`   | No                   | Yes (console)  | Development & testing   |
| `sc2_stub`    | Yes (OCR)            | Yes (keyboard) | Live client (high risk) |

Switch only by editing `config/config.yaml` → `chat_backend`, then restart.

**Chat position:** OCR uses one `chat_region` rectangle. Lobby chat is usually **bottom-right**. Measure with `tools/measure_chat_region.py`.

---

## Quick Start (from source)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Edit `config/config.yaml` and set your Gemini API key (or `GEMINI_API_KEY`).

---

## Portable folder (Simulated + OCR in one package)

Users can run a self-contained folder **without installing Python**. One build includes **both** modes; users switch by editing config.

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

Zip and share `dist/SC2ChatBot/`. Paths are resolved next to the executable so config/logs work after moving the folder.

### End-user: Simulated mode

1. Open `config/config.yaml`
2. Set `gemini.api_key`
3. Keep `chat_backend: "simulated"`
4. Run `SC2ChatBot.exe`

### End-user: OCR mode (same folder)

1. Install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) on the PC
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

---

## Player names, game requests & memory

- **Clan tags** stripped for memory/mute/owner keys; display name kept when useful
- **Game requests** (`[1v1]`, `[host]`, LFG text, …) can use short canned replies
- **Memory:** up to 30 messages/player; optional `persist_path: "logs/memory.json"`

```yaml
behaviour:
  reply_to_game_requests: true
  game_request_use_canned: true
```

---

## Obtaining a Gemini API Key

1. https://aistudio.google.com/
2. Create an API key
3. Put it in `config/config.yaml` or set `GEMINI_API_KEY`

---

## Configuration overview

All settings: `config/config.yaml`

- `personality`, `triggers`, `canned_blocks`, `anti_spam`, `behaviour`, `memory`, `owner`
- `chat_backend`: `simulated` | `sc2_stub`
- `sc2_stub`: OCR region, keys, Tesseract path

Owner commands: `!tone`, `!prop`, `!mute`, `!reload`, `!status`, `!length`, …

---

## Architecture

```
sc2_chatbot/
├── config/
├── portable/                 # texts shipped inside dist/
├── scripts/build_portable.*  # build the portable folder
├── tools/measure_chat_region.py
├── SC2ChatBot.spec           # PyInstaller
├── src/
│   ├── paths.py              # portable/frozen path helpers
│   ├── chat/
│   └── …
└── main.py
```

---

## License

MIT – use at your own risk.
