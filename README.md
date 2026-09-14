# Production Ready SC2 Chat-Only Bot (AI-powered)

**Educational / research project only.**

A modular StarCraft 2 **chat-only** bot that reads lobby/game chat, decides when to reply, and responds with a configurable AI personality. Supports Google Gemini, OpenAI-compatible cloud APIs (NVIDIA, OpenRouter, etc.), and **local models via Ollama**.

---

## Console Messages

<img width="845" height="720" alt="Console output example" src="https://github.com/user-attachments/assets/5fa59b94-c6bb-49ff-8e62-ca2e132bb43d" />

Live console shows `RECV` for incoming chat, `SEND` for replies, owner command results, a startup **ACTIVE CONFIG** dump (including custom personality on/off), and a transient **AI generating reply…** spinner while the model is running.

---

## Automatic AI Responses

<img width="800" height="67" alt="Automatic AI reply demo" src="https://github.com/user-attachments/assets/a7f5b6c1-4770-40b1-9224-50a225f55b82" />

The bot picks up messages from chat (including multi-line messages), runs them through anti-spam / triggers / personality, calls the LLM when needed, then types or pastes the reply back into StarCraft II after a short human-like delay.

If the model returns empty or only planning/meta text, **no reply is sent** (no canned fallback lines).

---

## Features

- **Pluggable chat backends** — `simulated` or `sc2_stub` (OCR)
- **Multi-line chat support** — joins wrapped SC2 lines under `[1. General] Name:`
- **AI progress spinner** while the LLM runs
- **Multi-provider LLM** — Gemini, OpenAI-compatible (NVIDIA, OpenRouter, …), **Ollama**
- **`llm.think` toggle** + request timeouts + error diagnostics
- **Prebuilt personalities** — neutral / left / right / propaganda_* / troll / ragebait
- **Custom personality** — free-text prompt that **overrides** all prebuilt modes when enabled
- **Emojis disabled** in prompts and output
- **Blacklist / favorites**, name addressing chance, triggers, memory, anti-spam
- **Owner commands**, human-like delays/typos, portable build

---

## ⚠️ Blizzard Terms of Service Warning

Third-party automation that reads or injects into the live SC2 client can violate Blizzard ToS. **Use at your own risk.** Prefer **Simulated** for development.

---

## Personality modes

### Priority: custom vs prebuilt

| `custom_enabled` | `custom_prompt` | Effective mode |
|------------------|-----------------|----------------|
| `true` | non-empty text | **`custom`** — prebuilt modes ignored |
| `true` | empty | Falls back to `political_mode` (warning logged) |
| `false` | (ignored) | Uses `political_mode` as usual |

When custom is on, the effective mode is always **`custom`**. Set `custom_enabled: false` (and optionally keep your preferred `political_mode`) to return to prebuilt behaviour. `!reload` picks this up.

### Prebuilt modes (`political_mode`)

| Mode | Type | Behaviour |
|------|------|-----------|
| `neutral` | Neutral | Light sarcasm |
| `left` / `right` | Political | Soft lean |
| `propaganda_left` / `propaganda_right` | Political (hard) | Hostile propaganda |
| `troll` | Non-political | Provoke / mock |
| `ragebait` | Non-political | Dismiss / bait |

### Custom personality

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

  # --- Custom (takes priority when enabled) ---
  custom_enabled: true
  custom_prompt: |
    You are a chill older gamer in lobby chat.
    Short replies, mild sarcasm, never lecture. No AI vibes.
```

Startup log shows `custom_enabled`, a preview of `custom_prompt`, and `mode: custom` when active. `!status` shows `Custom=on|off`.

While custom is on, `!prop` cannot switch prebuilt modes (turn custom off in config + `!reload` first).

### Other knobs

| Setting | Effect |
|---------|--------|
| `aggressiveness` | 1–10 |
| `response_length` | short / medium / long |
| `emoji_intensity` | ignored (emojis always off) |
| `sc2_reference_level` | 0 = no game talk … 10 = full SC2 |
| `topics` | politics, current_events, in_game_strategy, memes, personal |

### Owner commands

| Command | Effect |
|---------|--------|
| `!prop troll` | Set prebuilt mode (blocked if custom is on) |
| `!tone 9` | Aggressiveness |
| `!length short` | Length |
| `!status` | Aggro, mode, **Custom=on/off**, mutes |
| `!reload` | Reload config (including custom on/off) |

---

## LLM providers (summary)

```yaml
llm:
  provider: "ollama"            # or gemini | openai_compatible | openrouter
  model: "qwen3.5:9b"
  think: false                  # recommended off for SC2 chat
  request_timeout_sec: 120
  base_url: "http://127.0.0.1:11434/v1"
```

See earlier docs in this README / config comments for Gemini, NVIDIA (`https://integrate.api.nvidia.com/v1`), and OpenRouter.

---

## Blacklist / favorites / behaviour

Same as before: post-generation blacklist, favorite-word nudges, `address_by_name_chance`, delays, typos.

---

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Edit `config/config.yaml`.

---

## Live SC2 (OCR)

```yaml
chat_backend: "sc2_stub"
sc2_stub:
  ocr_enabled: true
  chat_region: [1420, 680, 480, 300]
  self_name: "YourInGameName"
```

Measure region with `tools/measure_chat_region.py`.

---

## Configuration overview

| Section | Purpose |
|---------|---------|
| `llm` | Provider, model, `think`, timeouts, `base_url` |
| `personality` | Prebuilt `political_mode`, **`custom_enabled` / `custom_prompt`**, aggro, topics |
| `blacklist` / `favorites` | Output filter + vocabulary nudge |
| `behaviour` | Delays, name chance, game requests |
| `anti_spam` / `memory` / `triggers` | Spam control, history, canned |
| `chat_backend` / `sc2_stub` | Simulated vs OCR |

Startup **ACTIVE CONFIG** logs mode, custom on/off, and prompt preview.

---

## License

MIT – use at your own risk.
