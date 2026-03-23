from __future__ import annotations
from kb_config import DAMAGE_BASE, DAMAGE_GROWTH, MONSTER_HP_BASE, MONSTER_HP_GROWTH, MONSTER_XP_BASE, MONSTER_XP_PER_LEVEL


def _scaled_stat(base: float, growth: float, level: int) -> int:
    return max(1, int(round(base * (growth ** (level - 1)))))


def compute_seconds_per_frame(duration_seconds: float, frame_count: int) -> float:
    if frame_count <= 0:
        raise ValueError("frame_count must be > 0")
    return max(0.001, duration_seconds / frame_count)


def advance_frame_timer(accumulator: float, delta: float, spf: float) -> tuple[float, int]:
    accumulator += delta
    advances = int(accumulator / spf)
    if advances > 0:
        accumulator -= advances * spf
    return accumulator, advances


def compute_monster_hp(level: int) -> int:
    return _scaled_stat(MONSTER_HP_BASE, MONSTER_HP_GROWTH, level)


def compute_damage_per_keystroke(level: int) -> int:
    return _scaled_stat(DAMAGE_BASE, DAMAGE_GROWTH, level)


def compute_monster_xp(monster_level: int) -> int:
    return MONSTER_XP_BASE + MONSTER_XP_PER_LEVEL * monster_level


def xp_total_for_level(level: int) -> int:
    if level <= 1:
        return 0
    n = level - 1
    return 80 * (n ** 2) + 40 * n
