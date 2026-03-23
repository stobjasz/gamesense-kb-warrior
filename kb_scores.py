from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import List


def _normalize(item: dict) -> dict | None:
    try:
        return {
            "started_at": str(item.get("started_at", "")),
            "ended_at": str(item.get("ended_at", "")),
            "keystrokes": max(0, int(item.get("keystrokes", 0))),
            "monsters_killed": max(0, int(item.get("monsters_killed", 0))),
            "level": max(1, int(item.get("level", 1))),
        }
    except (TypeError, ValueError):
        return None


def _sort_key(score: dict) -> tuple[int, str]:
    return score["keystrokes"], score["ended_at"]


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
    scores = [n for item in data if isinstance(item, dict) and (n := _normalize(item))]
    scores.sort(key=_sort_key, reverse=True)
    return scores


def save_high_scores(path: Path, scores: List[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)


def get_best_score(path: Path) -> dict | None:
    scores = load_high_scores(path)
    return scores[0] if scores else None


def upsert_high_score(path: Path, started_at: str, keystrokes: int, monsters_killed: int, level: int) -> int | None:
    scores = load_high_scores(path)
    entry = _normalize({
        "started_at": started_at,
        "ended_at": datetime.now().isoformat(timespec="seconds"),
        "keystrokes": keystrokes,
        "monsters_killed": monsters_killed,
        "level": level,
    })
    if entry is None:
        return None

    for idx, score in enumerate(scores):
        if score.get("started_at") == started_at:
            scores[idx] = entry
            break
    else:
        scores.append(entry)

    scores.sort(key=_sort_key, reverse=True)
    top_scores = scores[:10]
    save_high_scores(path, top_scores)

    for idx, score in enumerate(top_scores, start=1):
        if score.get("started_at") == started_at:
            return idx
    return None


# Aliases kept for call-site compatibility
update_current_stats = upsert_high_score
record_high_score = upsert_high_score
