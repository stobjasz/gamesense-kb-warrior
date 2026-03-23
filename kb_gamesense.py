from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kb_config import EVENT_NAME, GAME_NAME, HEIGHT, WIDTH


def _blank_image_data() -> List[int]:
    return [0] * ((WIDTH * HEIGHT + 7) // 8)


def find_coreprops_file() -> Path | None:
    roots: List[Path] = []

    env_programdata = os.environ.get("PROGRAMDATA")
    if env_programdata:
        roots.append(Path(env_programdata))
    roots.append(Path("C:/ProgramData"))

    checked = set()
    for root in roots:
        root = root.resolve()
        if root in checked:
            continue
        checked.add(root)

        exact_candidates = [
            root / "SteelSeries" / "SteelSeries Engine 3" / "coreProps.json",
            root / "SteelSeries" / "GG" / "coreProps.json",
        ]
        for candidate in exact_candidates:
            if candidate.is_file():
                return candidate

        steelseries_dir = root / "SteelSeries"
        if steelseries_dir.exists():
            matches = list(steelseries_dir.rglob("coreProps.json"))
            if matches:
                matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return matches[0]

    return None


def read_gamesense_address(coreprops_path: Path) -> str:
    with coreprops_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    address = data.get("address")
    if not address or not isinstance(address, str):
        raise ValueError("Missing or invalid 'address' in coreProps.json")
    return address


def post_json(base_url: str, endpoint: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url=f"{base_url}/{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5):
        pass


def bind_screen_event(base_url: str) -> None:
    payload = {
        "game": GAME_NAME,
        "event": EVENT_NAME,
        "min_value": 0,
        "max_value": 100,
        "value_optional": True,
        "handlers": [
            {
                "device-type": "screened-128x40",
                "zone": "one",
                "mode": "screen",
                "datas": [
                    {
                        "has-text": False,
                        "image-data": _blank_image_data(),
                    }
                ],
            }
        ],
    }
    post_json(base_url, "bind_game_event", payload)


def stop_game(base_url: str) -> None:
    post_json(base_url, "stop_game", {"game": GAME_NAME})


def connect_gamesense() -> str | None:
    base_url, _ = connect_gamesense_with_error()
    return base_url


def connect_gamesense_with_error() -> tuple[str | None, str | None]:
    coreprops_path = find_coreprops_file()
    if coreprops_path is None:
        return None, "coreProps.json not found"

    try:
        address = read_gamesense_address(coreprops_path)
        base_url = f"http://{address}"
        post_json(
            base_url,
            "game_metadata",
            {
                "game": GAME_NAME,
                "game_display_name": "Keyboard Warrior",
                "developer": "Sebastian Tobjasz",
            },
        )
        bind_screen_event(base_url)
    except (URLError, HTTPError, OSError, ValueError, json.JSONDecodeError) as exc:
        err_text = str(exc).strip() or "unknown GameSense error"
        return None, err_text

    return base_url, None


def send_frame(base_url: str, image_data: List[int]) -> None:
    payload = {
        "game": GAME_NAME,
        "event": EVENT_NAME,
        "data": {
            "value": 0,
            "frame": {
                "image-data-128x40": image_data,
            },
        },
    }
    post_json(base_url, "game_event", payload)


def clear_and_stop(base_url: str) -> None:
    clear_payload = {
        "game": GAME_NAME,
        "event": EVENT_NAME,
        "data": {
            "value": 0,
            "frame": {
                "image-data-128x40": _blank_image_data(),
            },
        },
    }

    try:
        post_json(base_url, "game_event", clear_payload)
    except (URLError, HTTPError, OSError):
        pass

    try:
        stop_game(base_url)
    except (URLError, HTTPError, OSError):
        pass
