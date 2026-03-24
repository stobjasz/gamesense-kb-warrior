from __future__ import annotations
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
from PIL import Image
from kb_config import FRAMES_PER_CHARACTER, RIGHT_SPRITE_BASE_TARGET_X, TILE_SIZE, WARRIOR_ATTACK_PATH, WARRIOR_BLOCK_PATH, WARRIOR_IDLE_PATH, WARRIOR_RUN_PATH
from kb_progression import compute_monster_hp


@dataclass(frozen=True)
class SceneSpriteConfig:
    sprite_id: str
    kind: str
    image_path: Path
    frame_count: int
    expected_size: tuple[int, int] | None


@dataclass(frozen=True)
class SceneDistributionRule:
    mode: str
    interval_px: int
    count_per_interval: int
    bootstrap_intervals: int


@dataclass(frozen=True)
class ScenePlacementRule:
    sprite_id: str
    y_anchor: str
    clear_under_sprite: bool
    composite_mode: str
    avoid_overlap_with: List[str]
    overlap_margin: int
    distribution: SceneDistributionRule


@dataclass(frozen=True)
class SceneSkyHorizonConfig:
    sky_sprite_id: str
    sky_scroll_divisor: int
    horizon_base_y: int
    horizon_scroll_divisor: int
    horizon_offsets: List[int]


@dataclass(frozen=True)
class CorridorSceneConfig:
    sprites: Dict[str, SceneSpriteConfig]
    scene_mode: str
    wall_brick_sprite_ids: List[str]
    floor_sprite_id: str
    floor_height: int
    brick_start_offset_x: int
    brick_start_offset_y: int
    wall_underlay: SceneSkyHorizonConfig | None
    placements: List[ScenePlacementRule]
    sky_horizon: SceneSkyHorizonConfig | None


def load_corridor_scene_config(path: Path) -> CorridorSceneConfig:
    if not path.is_file():
        raise FileNotFoundError(f"Corridor scene config not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid corridor scene config JSON '{path}': {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Corridor scene config root must be a JSON object")

    base_dir = path.parent

    sprites_raw = raw.get("sprites")
    if not isinstance(sprites_raw, list) or not sprites_raw:
        raise ValueError("Corridor scene config 'sprites' must be a non-empty array")

    def _read_size(raw_size: object, field_name: str) -> tuple[int, int] | None:
        if raw_size is None:
            return None
        if (
            not isinstance(raw_size, list)
            or len(raw_size) != 2
            or not all(isinstance(v, int) and v > 0 for v in raw_size)
        ):
            raise ValueError(f"Corridor scene config '{field_name}' must be [width, height] of positive ints")
        return (raw_size[0], raw_size[1])

    sprites: Dict[str, SceneSpriteConfig] = {}
    for i, sprite_raw in enumerate(sprites_raw):
        if not isinstance(sprite_raw, dict):
            raise ValueError(f"Corridor scene config 'sprites[{i}]' must be an object")
        sprite_id = sprite_raw.get("id")
        if not isinstance(sprite_id, str) or not sprite_id.strip():
            raise ValueError(f"Corridor scene config 'sprites[{i}].id' must be a non-empty string")
        if sprite_id in sprites:
            raise ValueError(f"Corridor scene config has duplicate sprite id: '{sprite_id}'")

        kind = sprite_raw.get("kind", "static")
        if kind not in {"static", "static_alpha", "animated_strip"}:
            raise ValueError(f"Corridor scene config sprite '{sprite_id}' kind must be 'static', 'static_alpha' or 'animated_strip'")

        image_rel = sprite_raw.get("image")
        if not isinstance(image_rel, str) or not image_rel.strip():
            raise ValueError(f"Corridor scene config 'sprites[{i}].image' must be a non-empty string")

        frame_count = sprite_raw.get("frame_count", 1)
        if not isinstance(frame_count, int) or frame_count <= 0:
            raise ValueError(f"Corridor scene config sprite '{sprite_id}' frame_count must be a positive integer")
        if kind in {"static", "static_alpha"} and frame_count != 1:
            raise ValueError(f"Corridor scene config sprite '{sprite_id}' is static and must use frame_count=1")

        sprites[sprite_id] = SceneSpriteConfig(
            sprite_id=sprite_id,
            kind=kind,
            image_path=base_dir / image_rel,
            frame_count=frame_count,
            expected_size=_read_size(sprite_raw.get("size"), f"sprites[{i}].size"),
        )

    composition = raw.get("composition")
    if not isinstance(composition, dict):
        raise ValueError("Corridor scene config 'composition' must be an object")

    scene_mode = composition.get("mode", "brick_floor")
    if scene_mode not in {"brick_floor", "sky_horizon"}:
        raise ValueError("Corridor scene config 'composition.mode' must be 'brick_floor' or 'sky_horizon'")

    wall_brick_sprite_ids: List[str] = []
    floor_sprite_id = ""
    floor_height = 0
    brick_start_offset_x = 0
    brick_start_offset_y = 0
    wall_underlay: SceneSkyHorizonConfig | None = None
    sky_horizon: SceneSkyHorizonConfig | None = None

    if scene_mode == "brick_floor":
        def _read_non_negative_int(name: str) -> int:
            value = composition.get(name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"Corridor scene config 'composition.{name}' must be a non-negative integer")
            return value

        wall_raw = composition.get("wall")
        if not isinstance(wall_raw, dict):
            raise ValueError("Corridor scene config 'composition.wall' must be an object")
        wall_brick_sprite_ids = wall_raw.get("brick_sprite_ids")
        if not isinstance(wall_brick_sprite_ids, list) or not wall_brick_sprite_ids:
            raise ValueError("Corridor scene config 'composition.wall.brick_sprite_ids' must be a non-empty array")
        for i, sprite_id in enumerate(wall_brick_sprite_ids):
            if not isinstance(sprite_id, str) or sprite_id not in sprites:
                raise ValueError(f"Corridor scene config 'composition.wall.brick_sprite_ids[{i}]' must reference an existing sprite id")

        floor_raw = composition.get("floor")
        if not isinstance(floor_raw, dict):
            raise ValueError("Corridor scene config 'composition.floor' must be an object")
        floor_sprite_id = floor_raw.get("sprite_id")
        if not isinstance(floor_sprite_id, str) or floor_sprite_id not in sprites:
            raise ValueError("Corridor scene config 'composition.floor.sprite_id' must reference an existing sprite id")
        floor_height = floor_raw.get("height")
        if not isinstance(floor_height, int) or floor_height < 0:
            raise ValueError("Corridor scene config 'composition.floor.height' must be a non-negative integer")

        brick_start_offset_x = _read_non_negative_int("brick_start_offset_x")
        brick_start_offset_y = _read_non_negative_int("brick_start_offset_y")

        wall_underlay_raw = composition.get("wall_underlay")
        if wall_underlay_raw is not None:
            if not isinstance(wall_underlay_raw, dict):
                raise ValueError("Corridor scene config 'composition.wall_underlay' must be an object")
            underlay_sprite_id = wall_underlay_raw.get("sprite_id")
            if not isinstance(underlay_sprite_id, str) or underlay_sprite_id not in sprites:
                raise ValueError("Corridor scene config 'composition.wall_underlay.sprite_id' must reference an existing sprite id")
            underlay_scroll_divisor = wall_underlay_raw.get("scroll_divisor", 1)
            if not isinstance(underlay_scroll_divisor, int) or underlay_scroll_divisor <= 0:
                raise ValueError("Corridor scene config 'composition.wall_underlay.scroll_divisor' must be > 0")
            underlay_base_y = wall_underlay_raw.get("horizon_base_y")
            if not isinstance(underlay_base_y, int):
                raise ValueError("Corridor scene config 'composition.wall_underlay.horizon_base_y' must be an integer")
            underlay_horizon_scroll_divisor = wall_underlay_raw.get("horizon_scroll_divisor", 3)
            if not isinstance(underlay_horizon_scroll_divisor, int) or underlay_horizon_scroll_divisor <= 0:
                raise ValueError("Corridor scene config 'composition.wall_underlay.horizon_scroll_divisor' must be > 0")
            underlay_offsets = wall_underlay_raw.get("horizon_offsets")
            if (
                not isinstance(underlay_offsets, list)
                or not underlay_offsets
                or not all(isinstance(v, int) for v in underlay_offsets)
            ):
                raise ValueError("Corridor scene config 'composition.wall_underlay.horizon_offsets' must be a non-empty integer array")

            wall_underlay = SceneSkyHorizonConfig(
                sky_sprite_id=underlay_sprite_id,
                sky_scroll_divisor=underlay_scroll_divisor,
                horizon_base_y=underlay_base_y,
                horizon_scroll_divisor=underlay_horizon_scroll_divisor,
                horizon_offsets=underlay_offsets,
            )
    else:
        sky_raw = composition.get("sky")
        if not isinstance(sky_raw, dict):
            raise ValueError("Corridor scene config 'composition.sky' must be an object for sky_horizon mode")
        sky_sprite_id = sky_raw.get("sprite_id")
        if not isinstance(sky_sprite_id, str) or sky_sprite_id not in sprites:
            raise ValueError("Corridor scene config 'composition.sky.sprite_id' must reference an existing sprite id")
        sky_scroll_divisor = sky_raw.get("scroll_divisor", 1)
        if not isinstance(sky_scroll_divisor, int) or sky_scroll_divisor <= 0:
            raise ValueError("Corridor scene config 'composition.sky.scroll_divisor' must be > 0")

        horizon_raw = composition.get("horizon")
        if not isinstance(horizon_raw, dict):
            raise ValueError("Corridor scene config 'composition.horizon' must be an object for sky_horizon mode")
        horizon_base_y = horizon_raw.get("base_y")
        if not isinstance(horizon_base_y, int):
            raise ValueError("Corridor scene config 'composition.horizon.base_y' must be an integer")
        horizon_scroll_divisor = horizon_raw.get("scroll_divisor", 3)
        if not isinstance(horizon_scroll_divisor, int) or horizon_scroll_divisor <= 0:
            raise ValueError("Corridor scene config 'composition.horizon.scroll_divisor' must be > 0")
        horizon_offsets = horizon_raw.get("offsets")
        if (
            not isinstance(horizon_offsets, list)
            or not horizon_offsets
            or not all(isinstance(v, int) for v in horizon_offsets)
        ):
            raise ValueError("Corridor scene config 'composition.horizon.offsets' must be a non-empty integer array")

        sky_horizon = SceneSkyHorizonConfig(
            sky_sprite_id=sky_sprite_id,
            sky_scroll_divisor=sky_scroll_divisor,
            horizon_base_y=horizon_base_y,
            horizon_scroll_divisor=horizon_scroll_divisor,
            horizon_offsets=horizon_offsets,
        )

    placements_raw = composition.get("placements", [])
    if not isinstance(placements_raw, list):
        raise ValueError("Corridor scene config 'composition.placements' must be an array")

    placements: List[ScenePlacementRule] = []
    for i, placement_raw in enumerate(placements_raw):
        if not isinstance(placement_raw, dict):
            raise ValueError(f"Corridor scene config 'composition.placements[{i}]' must be an object")
        sprite_id = placement_raw.get("sprite_id")
        if not isinstance(sprite_id, str) or sprite_id not in sprites:
            raise ValueError(f"Corridor scene config placement[{i}] sprite_id must reference an existing sprite id")

        y_anchor = placement_raw.get("y_anchor", "wall_center")
        if y_anchor not in {"wall_center", "floor_top"}:
            raise ValueError(f"Corridor scene config placement[{i}] y_anchor must be 'wall_center' or 'floor_top'")

        clear_under_sprite = bool(placement_raw.get("clear_under_sprite", False))
        composite_mode = placement_raw.get("composite_mode", "normal")
        if composite_mode not in {"normal", "transparent_cutout"}:
            raise ValueError(f"Corridor scene config placement[{i}] composite_mode must be 'normal' or 'transparent_cutout'")

        avoid_overlap_with_raw = placement_raw.get("avoid_overlap_with", [])
        if not isinstance(avoid_overlap_with_raw, list):
            raise ValueError(f"Corridor scene config placement[{i}] avoid_overlap_with must be an array")
        avoid_overlap_with: List[str] = []
        for j, avoid_id in enumerate(avoid_overlap_with_raw):
            if not isinstance(avoid_id, str) or avoid_id not in sprites:
                raise ValueError(f"Corridor scene config placement[{i}].avoid_overlap_with[{j}] must reference an existing sprite id")
            avoid_overlap_with.append(avoid_id)

        overlap_margin = placement_raw.get("overlap_margin", 0)
        if not isinstance(overlap_margin, int) or overlap_margin < 0:
            raise ValueError(f"Corridor scene config placement[{i}] overlap_margin must be a non-negative integer")

        distribution_raw = placement_raw.get("distribution")
        if not isinstance(distribution_raw, dict):
            raise ValueError(f"Corridor scene config placement[{i}] distribution must be an object")
        mode = distribution_raw.get("mode")
        if mode not in {"segmented_random", "repeat_every"}:
            raise ValueError(f"Corridor scene config placement[{i}] distribution.mode must be 'segmented_random' or 'repeat_every'")
        interval_px = distribution_raw.get("interval_px")
        if not isinstance(interval_px, int) or interval_px <= 0:
            raise ValueError(f"Corridor scene config placement[{i}] distribution.interval_px must be > 0")
        count_per_interval = distribution_raw.get("count_per_interval", 1)
        if not isinstance(count_per_interval, int) or count_per_interval <= 0:
            raise ValueError(f"Corridor scene config placement[{i}] distribution.count_per_interval must be > 0")
        bootstrap_intervals = distribution_raw.get("bootstrap_intervals", 0)
        if not isinstance(bootstrap_intervals, int) or bootstrap_intervals < 0:
            raise ValueError(f"Corridor scene config placement[{i}] distribution.bootstrap_intervals must be >= 0")

        placements.append(ScenePlacementRule(
            sprite_id=sprite_id,
            y_anchor=y_anchor,
            clear_under_sprite=clear_under_sprite,
            composite_mode=composite_mode,
            avoid_overlap_with=avoid_overlap_with,
            overlap_margin=overlap_margin,
            distribution=SceneDistributionRule(
                mode=mode,
                interval_px=interval_px,
                count_per_interval=count_per_interval,
                bootstrap_intervals=bootstrap_intervals,
            ),
        ))

    return CorridorSceneConfig(
        sprites=sprites,
        scene_mode=scene_mode,
        wall_brick_sprite_ids=wall_brick_sprite_ids,
        floor_sprite_id=floor_sprite_id,
        floor_height=floor_height,
        brick_start_offset_x=brick_start_offset_x,
        brick_start_offset_y=brick_start_offset_y,
        wall_underlay=wall_underlay,
        placements=placements,
        sky_horizon=sky_horizon,
    )


def load_corridor_scene_assets(scene: CorridorSceneConfig) -> tuple[Dict[str, List[List[int]]], Dict[str, List[List[List[int]]]]]:
    """Load all scene sprites by id. Returns (static_sprites, animated_sprites)."""
    static_sprites: Dict[str, List[List[int]]] = {}
    animated_sprites: Dict[str, List[List[List[int]]]] = {}

    for sprite_id, sprite in scene.sprites.items():
        if sprite.kind == "animated_strip":
            frames = load_corridor_torch_frames(sprite.image_path, sprite.frame_count)
            if not frames or not frames[0] or not frames[0][0]:
                raise ValueError(f"Scene sprite '{sprite_id}' has invalid frame dimensions")
            if sprite.expected_size is not None:
                expected_w, expected_h = sprite.expected_size
                actual_h = len(frames[0])
                actual_w = len(frames[0][0])
                if actual_w != expected_w or actual_h != expected_h:
                    raise ValueError(
                        f"Scene sprite '{sprite_id}' expected frame size {sprite.expected_size}, got {(actual_w, actual_h)}"
                    )
            animated_sprites[sprite_id] = frames
            continue

        if sprite.kind == "static_alpha":
            tile = _image_to_canvas(Image.open(sprite.image_path))
            if not tile or not tile[0]:
                raise ValueError(f"Scene sprite '{sprite_id}' has invalid dimensions")
            if sprite.expected_size is not None:
                expected_w, expected_h = sprite.expected_size
                actual_h = len(tile)
                actual_w = len(tile[0])
                if actual_w != expected_w or actual_h != expected_h:
                    raise ValueError(
                        f"Scene sprite '{sprite_id}' expected size {sprite.expected_size}, got {(actual_w, actual_h)}"
                    )
            static_sprites[sprite_id] = tile
            continue

        tile = load_corridor_door(sprite.image_path)
        if not tile or not tile[0]:
            raise ValueError(f"Scene sprite '{sprite_id}' has invalid dimensions")
        if sprite.expected_size is not None:
            expected_w, expected_h = sprite.expected_size
            actual_h = len(tile)
            actual_w = len(tile[0])
            if actual_w != expected_w or actual_h != expected_h:
                raise ValueError(
                    f"Scene sprite '{sprite_id}' expected size {sprite.expected_size}, got {(actual_w, actual_h)}"
                )
        static_sprites[sprite_id] = tile

    return static_sprites, animated_sprites


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
