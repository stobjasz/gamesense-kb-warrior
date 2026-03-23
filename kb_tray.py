from __future__ import annotations

import sys
import threading

from PIL import Image

from kb_config import TILE_SIZE, WARRIOR_IDLE_PATH

try:
    import pystray
except ImportError:
    pystray = None


ICON_SIZE = 64


def _create_fallback_icon() -> Image.Image:
    icon = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    for y in range(16, 48):
        for x in range(16, 48):
            icon.putpixel((x, y), (255, 255, 255, 255))
    return icon


def create_tray_icon_image() -> Image.Image:
    if WARRIOR_IDLE_PATH.is_file():
        try:
            sheet = Image.open(WARRIOR_IDLE_PATH).convert("RGBA")
            frame = sheet.crop((0, 0, TILE_SIZE, TILE_SIZE))
            return frame.resize((ICON_SIZE, ICON_SIZE), Image.NEAREST)
        except OSError:
            pass

    return _create_fallback_icon()


def start_tray_icon(stop_event: threading.Event):
    if pystray is None:
        print("Warning: pystray is not installed; tray icon disabled.", file=sys.stderr)
        return None

    def on_quit(icon, item) -> None:
        del item
        stop_event.set()
        icon.stop()

    tray_icon = pystray.Icon(
        "kb_warrior",
        create_tray_icon_image(),
        "Keyboard Warrior",
        menu=pystray.Menu(pystray.MenuItem("Quit", on_quit)),
    )

    thread = threading.Thread(target=tray_icon.run, daemon=True)
    thread.start()
    return tray_icon


def update_tray_tooltip(tray_icon, tooltip: str) -> None:
    if tray_icon is None:
        return

    try:
        tray_icon.title = tooltip[:127]
    except Exception:
        pass
