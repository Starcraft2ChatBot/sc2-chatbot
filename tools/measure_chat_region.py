#!/usr/bin/env python3
"""Measure the on-screen StarCraft 2 chat box for OCR.

Usage
-----
1. Start StarCraft II in Windowed or Windowed Fullscreen.
2. Open the screen where chat is visible (lobby chat is usually bottom-right).
3. Run this script:

       python tools/measure_chat_region.py

4. Move the mouse to the TOP-LEFT corner of the chat box → press Enter.
5. Move the mouse to the BOTTOM-RIGHT corner of the chat box → press Enter.
6. Copy the printed chat_region line into config/config.yaml under sc2_stub.

Requires: pyautogui  (already listed in requirements.txt)
"""
from __future__ import annotations

import sys
import time

try:
    import pyautogui
except ImportError:
    print("pyautogui is required. Install with:  pip install pyautogui")
    sys.exit(1)


def live_position(label: str) -> tuple[int, int]:
    """Show live mouse coordinates until the user presses Enter in the terminal."""
    print()
    print(f"→ Move the mouse to the {label} of the chat box.")
    print("  (coordinates update live; switch back here and press Enter when ready)")
    print()

    last = None
    try:
        while True:
            # Non-blocking-ish: print position, check if user hit Enter via a short poll.
            # We use a simple approach: print live, user presses Enter in terminal.
            x, y = pyautogui.position()
            if (x, y) != last:
                print(f"\r  mouse: ({x}, {y})   ", end="", flush=True)
                last = (x, y)

            # Windows/Unix: peek at stdin without heavy deps by using a timed input alternative.
            # Fallback: instruct user to Ctrl+C is bad UX; use input() in a second step instead.
            # For live display we just sleep briefly; actual capture uses input() below.
            time.sleep(0.05)

            # Break out of live loop when stdin has a line — platform portable approach:
            if sys.stdin in _ready_select():
                input()  # consume the Enter
                break
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)

    x, y = pyautogui.position()
    print(f"\n  captured {label}: ({x}, {y})")
    return x, y


def _ready_select():
    """Return list of ready file objects for stdin, or empty list."""
    try:
        import select
        r, _, _ = select.select([sys.stdin], [], [], 0.0)
        return r
    except (ImportError, OSError):
        # Windows often lacks select on stdin — fall back to blocking input mode
        return []


def capture_point(label: str) -> tuple[int, int]:
    """Preferred capture: live print + blocking Enter (works on all platforms)."""
    print()
    print(f"→ Move the mouse to the {label} of the chat box, then press Enter here.")
    try:
        while True:
            x, y = pyautogui.position()
            print(f"\r  mouse: ({x}, {y})   ", end="", flush=True)
            # Check for Enter without requiring select (works on Windows):
            # Use a short timeout pattern via msvcrt if available, else blocking input.
            if _enter_pressed():
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)

    x, y = pyautogui.position()
    print(f"\n  captured {label}: ({x}, {y})")
    return x, y


def _enter_pressed() -> bool:
    """Return True if the user has pressed Enter (cross-platform best-effort)."""
    try:
        import msvcrt  # Windows
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            return ch in ("\r", "\n")
        return False
    except ImportError:
        pass

    try:
        import select
        r, _, _ = select.select([sys.stdin], [], [], 0.0)
        if r:
            sys.stdin.readline()
            return True
    except (ImportError, OSError):
        pass

    return False


def main() -> None:
    print("=" * 60)
    print("  SC2 Chat Region Measurer")
    print("=" * 60)
    print()
    print("Make sure StarCraft II is visible (Windowed / Windowed Fullscreen).")
    print("Lobby / menu chat is usually in the BOTTOM-RIGHT of the screen.")
    print()
    print("You will capture TWO corners of the chat box:")
    print("  1) TOP-LEFT")
    print("  2) BOTTOM-RIGHT")
    print()
    input("Press Enter when you are ready to start…")

    x1, y1 = capture_point("TOP-LEFT corner")
    x2, y2 = capture_point("BOTTOM-RIGHT corner")

    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    if width < 20 or height < 20:
        print()
        print("WARNING: region is very small — you may have clicked the same spot twice.")

    print()
    print("=" * 60)
    print("  RESULT — paste this into config/config.yaml under sc2_stub:")
    print("=" * 60)
    print()
    print(f"  chat_region: [{left}, {top}, {width}, {height}]")
    print()
    print("Also set:")
    print('  ocr_enabled: true')
    print('  chat_backend: "sc2_stub"')
    print()


if __name__ == "__main__":
    # On Windows the live Enter-detect loop works via msvcrt.
    # If it doesn't, fall back to a simpler two-step input flow.
    try:
        main()
    except Exception:
        # Ultra-simple fallback (always works)
        print()
        print("Fallback mode (no live coordinates).")
        input("Move mouse to TOP-LEFT of chat, then press Enter…")
        x1, y1 = pyautogui.position()
        print(f"  top-left: ({x1}, {y1})")
        input("Move mouse to BOTTOM-RIGHT of chat, then press Enter…")
        x2, y2 = pyautogui.position()
        print(f"  bottom-right: ({x2}, {y2})")
        left, top = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        print()
        print(f"  chat_region: [{left}, {top}, {width}, {height}]")
