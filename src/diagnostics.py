"""Startup health checks printed to the console."""
from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any, List, Tuple

logger = logging.getLogger("sc2_chatbot.diagnostics")


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _check_import(name: str, pip_name: str | None = None) -> bool:
    try:
        __import__(name)
        _ok(f"Python package '{name}' is installed")
        return True
    except ImportError:
        pkg = pip_name or name
        _fail(f"Missing package '{name}'. Install with:  pip install {pkg}")
        return False


def _check_tesseract_binary(tesseract_cmd: str | None) -> bool:
    cmd = tesseract_cmd or shutil.which("tesseract")
    if not cmd:
        _fail(
            "Tesseract OCR binary not found on PATH. "
            "Install from https://github.com/tesseract-ocr/tesseract "
            "or set sc2_stub.tesseract_cmd in config.yaml"
        )
        return False
    try:
        r = subprocess.run(
            [cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        line = (r.stdout or r.stderr or "").splitlines()[:1]
        ver = line[0] if line else "unknown version"
        _ok(f"Tesseract binary: {cmd} ({ver})")
        return True
    except Exception as e:
        _fail(f"Tesseract binary found but failed to run: {e}")
        return False


def _check_chat_region(region: Any) -> bool:
    if not region:
        _fail("chat_region is empty. Run:  python tools/measure_chat_region.py")
        return False
    try:
        left, top, width, height = [int(x) for x in region]
    except Exception:
        _fail(f"chat_region must be [left, top, width, height], got: {region}")
        return False

    print(f"  [INFO] chat_region = left={left}, top={top}, width={width}, height={height}")

    if width < 40 or height < 40:
        _fail("chat_region is too small (width/height < 40). Re-measure the chat box.")
        return False

    # Common mistake: putting bottom-right X/Y as width/height
    if width > 1200 or height > 900:
        _warn(
            "width or height looks unusually large. "
            "Remember format is [left, top, WIDTH, HEIGHT], not [left, top, right, bottom]."
        )
        if left > 0 and width > left:
            guess_w = width - left
            guess_h = height - top if height > top else height
            if 50 < guess_w < 900 and 50 < guess_h < 700:
                _warn(
                    f"If you measured corners ({left},{top}) and ({width},{height}), "
                    f"try instead:  chat_region: [{left}, {top}, {guess_w}, {guess_h}]"
                )

    _ok("chat_region values look usable (still verify against the on-screen chat box)")
    return True


def _check_gemini(api_key: str, model_name: str) -> bool:
    if not api_key or api_key.strip() in ("", "YOUR_KEY_HERE", "changeme"):
        _fail("Gemini API key is missing. Set gemini.api_key in config.yaml")
        return False
    if len(api_key) < 20:
        _warn("Gemini API key looks unusually short")

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(
            "Reply with exactly: OK",
            generation_config={"max_output_tokens": 8, "temperature": 0},
        )
        text = (getattr(resp, "text", None) or "").strip()
        if text:
            _ok(f"Gemini connected (model={model_name}, sample reply={text[:40]!r})")
            return True
        _warn("Gemini responded but returned empty text (check model name / quota)")
        return False
    except Exception as e:
        _fail(f"Gemini connection failed: {e}")
        _fail("Check API key, billing/quota, and model name in config.yaml")
        return False


def run_startup_diagnostics(config: Any) -> None:
    """Print a human-readable health report. Does not stop the bot."""
    print()
    print("=" * 60)
    print("  STARTUP DIAGNOSTICS")
    print("=" * 60)

    print("\n-- Core Python packages --")
    _check_import("yaml", "pyyaml")
    _check_import("pydantic")
    _check_import("google.generativeai", "google-generativeai")
    _check_import("rich")

    backend = getattr(config, "chat_backend", "simulated")
    print(f"\n-- Backend: {backend} --")

    print("\n-- Gemini --")
    key = getattr(getattr(config, "gemini", None), "api_key", "") or ""
    model = getattr(getattr(config, "gemini", None), "model", "gemini-2.0-flash")
    _check_gemini(key, model)

    if backend == "sc2_stub":
        print("\n-- Live SC2 / OCR packages --")
        has_gui = _check_import("pyautogui")
        _check_import("pygetwindow", "PyGetWindow")
        has_mss = _check_import("mss")
        _check_import("PIL", "Pillow")
        has_tess_py = _check_import("pytesseract")

        stub = getattr(config, "sc2_stub", {}) or {}
        print("\n-- Tesseract binary --")
        has_tess_bin = _check_tesseract_binary(stub.get("tesseract_cmd"))

        print("\n-- OCR config --")
        ocr_on = bool(stub.get("ocr_enabled", False))
        if ocr_on:
            _ok("ocr_enabled: true")
        else:
            _fail("ocr_enabled is false — set ocr_enabled: true under sc2_stub")

        region_ok = _check_chat_region(stub.get("chat_region"))

        if not (has_mss and has_tess_py and has_tess_bin and region_ok and ocr_on):
            print()
            _warn("OCR will not read chat until the FAIL items above are fixed.")
            print("  Typical fix order:")
            print("    1. pip install mss Pillow pytesseract pyautogui PyGetWindow")
            print("    2. Install Tesseract OCR for Windows")
            print("    3. python tools\\measure_chat_region.py")
            print("    4. Paste chat_region into config\\config.yaml")
            print("    5. SC2 in Windowed mode with chat visible")
        else:
            print()
            _ok("OCR prerequisites look present. If still silent, region may miss the chat box.")
            print("  Tip: chat is usually bottom-right in the arcade/lobby browser.")
            print("  Tip: bot only logs RECV when OCR sees lines like  Name: message")
    else:
        print("\n-- Simulated mode --")
        _ok("No OCR required. Messages must be injected (or switch to sc2_stub for live chat).")

    print()
    print("=" * 60)
    print("  End diagnostics — bot will continue starting")
    print("=" * 60)
    print()
