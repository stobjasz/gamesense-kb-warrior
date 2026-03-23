from __future__ import annotations
import random
from pathlib import Path
from typing import Dict, List
from PIL import Image
from kb_config import FRAMES_PER_CHARACTER, RIGHT_SPRITE_BASE_TARGET_X, TILE_SIZE, WARRIOR_ATTACK_PATH, WARRIOR_BLOCK_PATH, WARRIOR_IDLE_PATH, WARRIOR_RUN_PATH
from kb_progression import compute_monster_hp


def _tile_to_canvas(tile_image: Image.Image) -> List[List[int]]:
    canvas = [[0] * TILE_SIZE for _ in range(TILE_SIZE)]
    px = tile_image.load()
    threshold = 255 * 3 // 2
    for y in range(TILE_SIZE):
        for x in range(TILE_SIZE):
            r, g, b, a = px[x, y]
            if a > 0:
                canvas[y][x] = 1 if (r + g + b) >= threshold else 2
    return canvas


def _image_to_canvas(tile_image: Image.Image) -> List[List[int]]:
    rgba = tile_image.convert("RGBA")
    w, h = rgba.size
    canvas = [[0] * w for _ in range(h)]
    px = rgba.load()
    threshold = 255 * 3 // 2
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 0:
                canvas[y][x] = 1 if (r + g + b) >= threshold else 2
    return canvas


def get_tile_x_bounds(tile: List[List[int]]) -> tuple[int, int] | None:
    min_x, max_x = TILE_SIZE, -1
    for y in range(TILE_SIZE):
        for x in range(TILE_SIZE):
            if tile[y][x]:
                min_x = min(min_x, x)
                max_x = max(max_x, x)
    return (min_x, max_x) if max_x >= 0 else None


def get_frames_x_bounds(frames: List[List[List[int]]]) -> tuple[int, int] | None:
    min_x, max_x = TILE_SIZE, -1
    for tile in frames:
        b = get_tile_x_bounds(tile)
        if b:
            min_x = min(min_x, b[0])
            max_x = max(max_x, b[1])
    return (min_x, max_x) if max_x >= 0 else None


def compute_right_sprite_target_x(right_frames: List[List[List[int]]], left_sprite_x: int, left_collision_rightmost: int) -> int:
    bounds = get_frames_x_bounds(right_frames)
    if bounds is None:
        return RIGHT_SPRITE_BASE_TARGET_X
    return max(0, left_sprite_x + left_collision_rightmost - bounds[0] + 1)


def load_sprite_strip_frames(path: Path, frame_count: int) -> List[List[List[int]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Sprite sheet not found: {path}")
    image = Image.open(path).convert("RGBA")
    w, h = image.size
    if w < frame_count * TILE_SIZE or h < TILE_SIZE:
        raise ValueError(f"Sprite sheet '{path}' must contain at least {frame_count} frames of {TILE_SIZE}x{TILE_SIZE}")
    return [_tile_to_canvas(image.crop((i * TILE_SIZE, 0, (i + 1) * TILE_SIZE, TILE_SIZE))) for i in range(frame_count)]


def load_character_frames(path: Path) -> List[List[List[List[int]]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Spritesheet not found: {path}")
    image = Image.open(path).convert("RGBA")
    w, h = image.size
    if w % TILE_SIZE != 0 or h % TILE_SIZE != 0:
        raise ValueError("Spritesheet size is not divisible by 32x32 tiles")
    tiles_x, tiles_y = w // TILE_SIZE, h // TILE_SIZE
    if tiles_x % FRAMES_PER_CHARACTER != 0:
        raise ValueError("Spritesheet width must contain groups of 4 frames per character")
    chars_per_row = tiles_x // FRAMES_PER_CHARACTER
    frames = []
    for row in range(tiles_y):
        for char in range(chars_per_row):
            char_frames = []
            for fi in range(FRAMES_PER_CHARACTER):
                tx = (char * FRAMES_PER_CHARACTER + fi) * TILE_SIZE
                ty = row * TILE_SIZE
                char_frames.append(_tile_to_canvas(image.crop((tx, ty, tx + TILE_SIZE, ty + TILE_SIZE))))
            frames.append(char_frames)
    if not frames:
        raise ValueError("No character frames extracted from spritesheet")
    return frames


def load_warrior_animations() -> Dict[str, List[List[List[int]]]]:
    specs = {"idle": (WARRIOR_IDLE_PATH, 4), "run": (WARRIOR_RUN_PATH, 8), "block": (WARRIOR_BLOCK_PATH, 5), "attack": (WARRIOR_ATTACK_PATH, 9)}
    return {name: load_sprite_strip_frames(path, count) for name, (path, count) in specs.items()}


def load_slashfx_frames(path: Path) -> List[List[List[int]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Slash FX sheet not found: {path}")
    frame_count = Image.open(path).size[0] // TILE_SIZE
    if frame_count <= 0:
        raise ValueError("Slash FX sheet contains no frames")
    return load_sprite_strip_frames(path, frame_count)


def load_drop_tiles(path: Path) -> List[List[List[int]]]:
    if not path.is_dir():
        raise FileNotFoundError(f"Drop tiles directory not found: {path}")
    tiles: List[List[List[int]]] = []
    for file_path in sorted(path.glob("*.png")):
        image = Image.open(file_path)
        if image.size != (16, 16):
            raise ValueError(f"Drop tile '{file_path}' must be exactly 16x16")
        tiles.append(_image_to_canvas(image))
    if not tiles:
        raise ValueError(f"No drop tiles found in: {path}")
    return tiles


def load_scrolling_background_tile(path: Path) -> List[List[int]]:
    """Load a horizontal strip image (e.g. 5x 32px tiles) as one seamless scrolling tile."""
    if not path.is_file():
        raise FileNotFoundError(f"Background image not found: {path}")
    image = Image.open(path).convert("RGBA")
    w, h = image.size
    if h != TILE_SIZE:
        raise ValueError(f"Background '{path}' height must be {TILE_SIZE}px")
    if w < TILE_SIZE:
        raise ValueError(f"Background '{path}' width must be at least {TILE_SIZE}px")
    # Background should be binary: stars/bright pixels = 1, black space = 0.
    px = image.load()
    threshold = 255 * 3 // 2
    canvas = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 0 and (r + g + b) >= threshold:
                canvas[y][x] = 1
    return canvas


def load_corridor_background(brick_paths: List[Path], floor_path: Path) -> tuple[List[List[List[int]]], List[List[int]]]:
    """Load corridor brick variants and floor layer as binary canvases."""
    if not brick_paths:
        raise ValueError("At least one corridor brick variant path is required")
    for brick_path in brick_paths:
        if not brick_path.is_file():
            raise FileNotFoundError(f"Corridor brick image not found: {brick_path}")
    if not floor_path.is_file():
        raise FileNotFoundError(f"Corridor floor image not found: {floor_path}")

    def _image_to_bright_binary_canvas(path: Path) -> List[List[int]]:
        image = Image.open(path).convert("RGBA")
        w, h = image.size
        px = image.load()
        threshold = 255 * 3 // 2
        canvas = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a > 0 and (r + g + b) >= threshold:
                    canvas[y][x] = 1
        return canvas

    bricks = [_image_to_bright_binary_canvas(path) for path in brick_paths]
    floor = _image_to_bright_binary_canvas(floor_path)

    if not bricks[0] or not bricks[0][0]:
        raise ValueError(f"Corridor brick image '{brick_paths[0]}' has invalid dimensions")
    expected_w = len(bricks[0][0])
    expected_h = len(bricks[0])
    for i, brick in enumerate(bricks, start=1):
        if not brick or not brick[0]:
            raise ValueError(f"Corridor brick image '{brick_paths[i - 1]}' has invalid dimensions")
        if len(brick) != expected_h or len(brick[0]) != expected_w:
            raise ValueError("All corridor brick variants must have identical dimensions")
    if not floor or not floor[0]:
        raise ValueError(f"Corridor floor image '{floor_path}' has invalid dimensions")

    return bricks, floor


def load_corridor_door(path: Path) -> List[List[int]]:
    if not path.is_file():
        raise FileNotFoundError(f"Corridor door image not found: {path}")
    image = Image.open(path).convert("RGBA")
    w, h = image.size
    px = image.load()
    threshold = 255 * 3 // 2
    canvas = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 0 and (r + g + b) >= threshold:
                canvas[y][x] = 1
    return canvas


def load_corridor_torch_frames(path: Path, frame_count: int = 2) -> List[List[List[int]]]:
    if not path.is_file():
        raise FileNotFoundError(f"Corridor torch image not found: {path}")
    if frame_count <= 0:
        raise ValueError("Corridor torch frame_count must be positive")

    image = Image.open(path).convert("RGBA")
    w, h = image.size
    if w % frame_count != 0:
        raise ValueError(f"Corridor torch image '{path}' width must be divisible by {frame_count}")

    frame_w = w // frame_count
    if frame_w <= 0 or h <= 0:
        raise ValueError(f"Corridor torch image '{path}' has invalid dimensions")

    frames: List[List[List[int]]] = []
    threshold = 255 * 3 // 2
    for i in range(frame_count):
        frame_img = image.crop((i * frame_w, 0, (i + 1) * frame_w, h))
        px = frame_img.load()
        frame = [[0] * frame_w for _ in range(h)]
        for y in range(h):
            for x in range(frame_w):
                r, g, b, a = px[x, y]
                if a > 0:
                    frame[y][x] = 1 if (r + g + b) >= threshold else 2
        frames.append(frame)

    return frames


def spawn_right_sprite(all_characters, left_sprite_x, left_collision_rightmost, monster_level):
    frames = random.choice(all_characters)
    target_x = compute_right_sprite_target_x(frames, left_sprite_x, left_collision_rightmost)
    return frames, target_x, compute_monster_hp(monster_level)
