# SC2 Chat-Only Bot (Gemini-powered)

**Educational / research project only.**

A modular, production-oriented StarCraft 2 **chat-only** bot that:
- Monitors in-game chat (all / team / whispers)
- Replies using Google Gemini with highly configurable personality
- Supports aggressiveness slider (1–10), political modes (neutral / left / right / full propaganda), topic controls, response length & emoji intensity
- Has a powerful trigger / canned-response engine (regex, priority, cooldowns, per-player limits)
- Maintains short per-player conversation memory
- Includes anti-spam, mute list, rate limiting and owner-only commands
- Uses realistic human-like delays and occasional typos

## ⚠️ Blizzard Terms of Service Warning

Any software that automatically reads chat from or injects keystrokes into the live StarCraft II client is third-party automation. Blizzard’s Terms of Service and Code of Conduct prohibit unauthorized third-party programs. Using this (or any similar) tool on a live account can result in temporary or permanent bans.

**Use at your own risk.** Prefer the included **Simulated** backend for development and testing.

## Features

- Continuous monitoring of all-chat / team-chat / whispers (pluggable backend)
- Google Gemini replies with configurable personality
- Aggressiveness 1–10, political modes (neutral | left | right | propaganda_left | propaganda_right)
- Topic bias, response length, emoji intensity
- Powerful trigger / canned-response engine
- Per-player conversation memory
- Anti-spam, mute list, rate limits
- Owner commands (`!tone`, `!prop`, `!mute`, `!reload`, `!status` …)
- Human-like delays + occasional typos
- Full local logging
- Clean YAML configuration

## Quick Start (Simulated mode – recommended)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
# Edit config.yaml and put your Gemini API key (or set GEMINI_API_KEY env var)
python main.py
```

## Obtaining a Gemini API Key

1. Go to https://aistudio.google.com/
2. Create an API key
3. Restrict it if possible

## Configuration

See the extensive comments inside `config/config.example.yaml`. All personality, trigger, anti-spam and logging options are documented there.

## Architecture

```
sc2_chatbot/
├── config/
├── src/
│   ├── chat/          # abstract backend + simulated + SC2 stub
│   ├── models.py
│   ├── config_loader.py
│   ├── logger.py
│   ├── gemini_client.py
│   ├── personality.py
│   ├── triggers.py
│   ├── memory.py
│   ├── anti_spam.py
│   ├── commands.py
│   ├── decision_engine.py
│   └── bot.py
└── main.py
```

## Extending for real SC2

Implement a class that inherits from `ChatBackend` and supplies reliable `listen()` + `send()`. A keyboard + optional OCR stub is already provided in `src/chat/sc2_stub.py`. Memory reading / advanced OCR solutions exist in the community but carry high ban risk and are outside the scope of this repository.

## License

MIT – use at your own risk.
