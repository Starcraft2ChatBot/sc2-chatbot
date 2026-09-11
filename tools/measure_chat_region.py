#!/usr/bin/env python3
"""Measure the on-screen StarCraft 2 chat box for OCR.

Usage
-----
1. Start StarCraft II in Windowed or Windowed Fullscreen.
2. Open the screen where chat is visible (lobby chat is usually bottom-right).
3. Run:

       python tools/measure_chat_region.py

4. Move the mouse to the TOP-LEFT corner of the chat box → press Enter.
5. Move the mouse to the BOTTOM-RIGHT corner of the chat box → press Enter.
6. Copy the printed chat_region line into config/config.yaml under sc2_stub.

Requires: pyautogui  (listed in requirements.txt)
"""
from __future__ import annotations

import sys
import threading
import time

try:
    import pyautogui
except ImportError:
    print("pyautogui is required. Install with:  pip install pyautogui")
    input("\nPress Enter to close…")
    sys.exit(1)


def _live_coords(stop: threading.Event) -> None:
    """Background thread: print live mouse position until stop is set."""
    last = None
    while not stop.is_set():
        pos = pyautogui.position()
        if pos != last:
            print(f"\r  mouse: ({pos.x}, {pos.y})   ", end="", flush=True)
            last = pos
        time.sleep(0.05)


def capture_point(label: str) -> tuple[int, int]:
    print()
    print(f"→ Move the mouse to the {label} of the chat box, then press Enter here.")
    stop = threading.Event()
    t = threading.Thread(target=_live_coords, args=(stop,), daemon=True)
    t.start()
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        stop.set()
        print("\nCancelled.")
        input("\nPress Enter to close…")
        sys.exit(0)
    stop.set()
    t.join(timeout=0.5)
    x, y = pyautogui.position()
    print(f"\n  captured {label}: ({x}, {y})")
    return int(x), int(y)


def main() -> None:
    print("=" * 60)
    print("  SC2 Chat Region Measurer")
    print("=" * 60)
    print()
    print("Make sure StarCraft II is visible (Windowed / Windowed Fullscreen).")
    print("Lobby / menu chat is usually in the BOTTOM-RIGHT of the screen.")
    print()
    print("IMPORTANT: result is [left, top, WIDTH, HEIGHT]")
    print("  (not left/top/right/bottom)")
    print()
    print("You will capture TWO corners of the chat box:")
    print("  1) TOP-LEFT")
    print("  2) BOTTOM-RIGHT")
    print()
    try:
        input("Press Enter when you are ready to start…")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        input("\nPress Enter to close…")
        sys.exit(0)

    x1, y1 = capture_point("TOP-LEFT corner")
    x2, y2 = capture_point("BOTTOM-RIGHT corner")

    left = min(x1, x2)
    top = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    if width < 20 or height < 20:
        print()
        print("WARNING: region is very small — you may have captured the same spot twice.")

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
    print("Window will stay open so you can copy the numbers.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        # Keep the window open (double-click / RUN from explorer)
        try:
            input("\nPress Enter to close…")
        except (KeyboardInterrupt, EOFError):
            pass
