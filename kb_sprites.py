from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List

from PIL import Image

from kb_config import (
    FRAMES_PER_CHARACTER,
    RIGHT_SPRITE_BASE_TARGET_X,
    TILE_SIZE,
    WARRIOR_ATTACK_PATH,
    WARRIOR_BLOCK_PATH,
    WARRIOR_IDLE_PATH,
    WARRIOR_RUN_PATH,
)
from kb_progression import compute_monster_hp


def get_tile_x_bounds(tile: List[List[int]]) -> tuple[int, int] | None:
    min_x = TILE_SIZE
    max_x = -1
    for y in range(TILE_SIZE):
        for x in range(TILE_SIZE):
            if tile[y][x]:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
    if max_x < 0:
        return None
    return min_x, max_x


def get_frames_x_bounds(frames: List[List[List[int]]]) -> tuple[int, int] | None:
    min_x = TILE_SIZE
    max_x = -1
    for tile in frames:
        bounds = get_tile_x_bounds(tile)
        if bounds is None:
            continue
        min_x = min(min_x, bounds[0])
        max_x = max(max_x, bounds[1])
    if max_x < 0:
        return None
    return min_x, max_x


def compute_right_sprite_target_x(
    right_frames: List[List[List[int]]], left_sprite_x: int, left_collision_rightmost: int
) -> int:
    bounds = get_frames_x_bounds(right_frames)
    if bounds is None:
        return RIGHT_SPRITE_BASE_TARGET_X
    right_leftmost = bounds[0]
    return max(0, left_sprite_x + left_collision_rightmost - right_leftmost + 1)


def load_character_frames(path: Path) -> List[List[List[List[int]]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Spritesheet not found: {path}")

    image = Image.open(path).convert("RGBA")
    sheet_w, sheet_h = image.size

    if sheet_w % TILE_SIZE != 0 or sheet_h % TILE_SIZE != 0:
        raise ValueError("Spritesheet size is not divisible by 32x32 tiles")

    tiles_x = sheet_w // TILE_SIZE
    tiles_y = sheet_h // TILE_SIZE
    if tiles_x % FRAMES_PER_CHARACTER != 0:
        raise ValueError("Spritesheet width must contain groups of 4 frames per character")

    characters_per_row = tiles_x // FRAMES_PER_CHARACTER
    frames: List[List[List[List[int]]]] = []

    for row in range(tiles_y):
        for char_in_row in range(characters_per_row):
            char_frames: List[List[List[int]]] = []
            for frame_idx in range(FRAMES_PER_CHARACTER):
                tile_x = (char_in_row * FRAMES_PER_CHARACTER + frame_idx) * TILE_SIZE
                tile_y = row * TILE_SIZE
                tile = image.crop((tile_x, tile_y, tile_x + TILE_SIZE, tile_y + TILE_SIZE))

                tile_canvas = [[0 for _ in range(TILE_SIZE)] for _ in range(TILE_SIZE)]
                px = tile.load()
                for y in range(TILE_SIZE):
                    for x in range(TILE_SIZE):
                        r, g, b, a = px[x, y]
                        if a == 0:
                            continue
                        is_white = (r + g + b) >= (255 * 3 // 2)
                        tile_canvas[y][x] = 1 if is_white else 2
                char_frames.append(tile_canvas)
            frames.append(char_frames)

    if not frames:
        raise ValueError("No character frames extracted from spritesheet")
    return frames


def load_sprite_strip_frames(path: Path, frame_count: int) -> List[List[List[int]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Sprite sheet not found: {path}")

    image = Image.open(path).convert("RGBA")
    sheet_w, sheet_h = image.size

    expected_w = frame_count * TILE_SIZE
    if sheet_w < expected_w or sheet_h < TILE_SIZE:
        raise ValueError(
            f"Sprite sheet '{path}' must contain at least {frame_count} frames of 32x32"
        )

    frames: List[List[List[int]]] = []
    for frame_idx in range(frame_count):
        tile_x = frame_idx * TILE_SIZE
        tile = image.crop((tile_x, 0, tile_x + TILE_SIZE, TILE_SIZE))

        tile_canvas = [[0 for _ in range(TILE_SIZE)] for _ in range(TILE_SIZE)]
        px = tile.load()
        for y in range(TILE_SIZE):
            for x in range(TILE_SIZE):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                is_white = (r + g + b) >= (255 * 3 // 2)
                tile_canvas[y][x] = 1 if is_white else 2

        frames.append(tile_canvas)

    return frames


def load_warrior_animations() -> Dict[str, List[List[List[int]]]]:
    specs = {
        "idle": (WARRIOR_IDLE_PATH, 4),
        "run": (WARRIOR_RUN_PATH, 8),
        "block": (WARRIOR_BLOCK_PATH, 5),
        "attack": (WARRIOR_ATTACK_PATH, 9),
    }
    animations: Dict[str, List[List[List[int]]]] = {}
    for name, (path, frame_count) in specs.items():
        animations[name] = load_sprite_strip_frames(path, frame_count)
    return animations


def load_slashfx_frames(path: Path) -> List[List[List[int]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Slash FX sheet not found: {path}")

    image = Image.open(path).convert("RGBA")
    sheet_w, sheet_h = image.size
    if sheet_h < TILE_SIZE or sheet_w < TILE_SIZE or (sheet_w % TILE_SIZE) != 0:
        raise ValueError("Slash FX sheet must be at least 32px high and width divisible by 32")

    frame_count = sheet_w // TILE_SIZE
    if frame_count <= 0:
        raise ValueError("Slash FX sheet contains no frames")

    return load_sprite_strip_frames(path, frame_count)


def spawn_right_sprite(
    all_characters: List[List[List[List[int]]]],
    left_sprite_x: int,
    left_collision_rightmost: int,
    monster_level: int,
) -> tuple[List[List[List[int]]], int, int]:
    selected_character_frames = random.choice(all_characters)
    right_sprite_target_x = compute_right_sprite_target_x(
        selected_character_frames,
        left_sprite_x,
        left_collision_rightmost,
    )
    monster_hp = compute_monster_hp(monster_level)
    return selected_character_frames, right_sprite_target_x, monster_hp
