from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List


def load_high_scores(path: Path) -> List[dict]:
    if not path.is_file():
        return []

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, list):
        return []

    scores: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        try:
            keystrokes = max(0, int(item.get("keystrokes", 0)))
            monsters_killed = max(0, int(item.get("monsters_killed", 0)))
            level = max(1, int(item.get("level", 1)))
        except (TypeError, ValueError):
            continue

        started_at = str(item.get("started_at", ""))
        ended_at = str(item.get("ended_at", ""))
        scores.append(
            {
                "started_at": started_at,
                "ended_at": ended_at,
                "keystrokes": keystrokes,
                "monsters_killed": monsters_killed,
                "level": level,
            }
        )

    scores.sort(key=lambda s: (s["keystrokes"], s["ended_at"]), reverse=True)
    return scores


def save_high_scores(path: Path, scores: List[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)


def get_best_score(path: Path) -> dict | None:
    scores = load_high_scores(path)
    if not scores:
        return None
    return scores[0]


def upsert_high_score(
    path: Path,
    started_at: str,
    keystrokes: int,
    monsters_killed: int,
    level: int,
) -> int | None:
    scores = load_high_scores(path)
    entry = {
        "started_at": started_at,
        "ended_at": datetime.now().isoformat(timespec="seconds"),
        "keystrokes": max(0, int(keystrokes)),
        "monsters_killed": max(0, int(monsters_killed)),
        "level": max(1, int(level)),
    }

    replaced_existing = False
    for idx, score in enumerate(scores):
        if score.get("started_at") == started_at:
            scores[idx] = entry
            replaced_existing = True
            break

    if not replaced_existing:
        scores.append(entry)

    scores.sort(key=lambda s: (s["keystrokes"], s["ended_at"]), reverse=True)
    top_scores = scores[:10]
    save_high_scores(path, top_scores)

    for idx, score in enumerate(top_scores, start=1):
        if score.get("started_at") == started_at:
            return idx
    return None


def update_current_stats(
    path: Path,
    started_at: str,
    keystrokes: int,
    monsters_killed: int,
    level: int,
) -> None:
    upsert_high_score(path, started_at, keystrokes, monsters_killed, level)


def record_high_score(
    path: Path,
    started_at: str,
    keystrokes: int,
    monsters_killed: int,
    level: int,
) -> int | None:
    return upsert_high_score(path, started_at, keystrokes, monsters_killed, level)
