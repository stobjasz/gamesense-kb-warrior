from __future__ import annotations
import sys
import threading
from typing import Callable
from PIL import Image, ImageDraw
from kb_config import TILE_SIZE, WARRIOR_IDLE_PATH

try:
    import pystray
except ImportError:
    pystray = None

ICON_SIZE = 64


def create_tray_icon_image() -> Image.Image:
    if WARRIOR_IDLE_PATH.is_file():
        try:
            sheet = Image.open(WARRIOR_IDLE_PATH).convert("RGBA")
            return sheet.crop((0, 0, TILE_SIZE, TILE_SIZE)).resize((ICON_SIZE, ICON_SIZE), Image.NEAREST)
        except OSError:
            pass
    icon = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(icon).rectangle([16, 16, 47, 47], fill=(255, 255, 255, 255))
    return icon


def start_tray_icon(stop_event: threading.Event, on_stop: Callable[[str], None] | None = None):
    if pystray is None:
        print("Warning: pystray is not installed; tray icon disabled.", file=sys.stderr)
        return None

    def on_quit(icon, item) -> None:
        if on_stop is not None:
            on_stop("tray_quit")
        else:
            stop_event.set()
        icon.stop()

    tray_icon = pystray.Icon(
        "kb_warrior", create_tray_icon_image(), "Keyboard Warrior",
        menu=pystray.Menu(pystray.MenuItem("Quit", on_quit)),
    )
    threading.Thread(target=tray_icon.run, daemon=True).start()
    return tray_icon


def update_tray_tooltip(tray_icon, tooltip: str) -> None:
    if tray_icon is None:
        return
    try:
        tray_icon.title = tooltip[:127]
    except Exception:
        pass
