SC2 Chat-Only Bot — Portable folder
=====================================

This folder runs WITHOUT installing Python yourself (after you build it
with scripts/build_portable.bat or .sh).

Contents
--------
  SC2ChatBot.exe          (or SC2ChatBot on Linux/macOS)  — main program
  config/config.yaml      — EDIT THIS (API key + mode switch)
  config/config.example.yaml
  tools/measure_chat_region.py
  SWITCH_MODES.txt        — how to switch Simulated ↔ OCR
  logs/                   — created automatically when you run

Quick start
-----------
1. Open config/config.yaml
2. Set gemini.api_key (or set env var GEMINI_API_KEY)
3. Leave chat_backend: "simulated" for safe testing
4. Double-click SC2ChatBot.exe

Both modes are in the SAME build
--------------------------------
You do NOT need two different executables.
Switch modes only by editing config/config.yaml (see SWITCH_MODES.txt),
then restart the exe.

OCR mode still needs on the PC
------------------------------
- Tesseract OCR installed and on PATH (or set sc2_stub.tesseract_cmd)
- StarCraft II in Windowed / Windowed Fullscreen
- chat_region measured with tools/measure_chat_region.py

WARNING: Live OCR + keyboard automation may violate Blizzard ToS.
