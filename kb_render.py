from __future__ import annotations
from dataclasses import dataclass
from typing import List
from kb_config import BACKGROUND_TILE_SIZE, BRICK_START_OFFSET_X, BRICK_START_OFFSET_Y, CORRIDOR_FLOOR_HEIGHT, DOOR_FIRST_SCREENS, DOOR_SEGMENT_SCREENS, FONT_5X7, HEALTH_BAR_WIDTH, HEALTH_BAR_Y, HEIGHT, LEFT_SPRITE_X, SLASHFX_X_OFFSET, TILE_SIZE, TORCHES_PER_SCREEN, WIDTH


@dataclass(frozen=True)
class RenderState:
    background_brick_tiles: List[List[List[int]]]
    background_floor_tile: List[List[int]]
    background_door_tile: List[List[int]]
    background_torch_frames: List[List[List[int]]]
    background_scroll_x: float
    background_anim_tick: int
    right_sprite_tile: List[List[int]]
    right_sprite_x: int
    left_sprite_tile: List[List[int]]
    left_sprite_x: int
    warrior_level: int
    keypress_count: int
    right_sprite_value: int
    right_sprite_max_value: int
    show_health_bar: bool
    show_hud: bool
    slashfx_tile: List[List[int]] | None
    drop_tile: List[List[int]] | None
    drop_x: int
    drop_y: int
    show_drop: bool


def canvas_to_image_data(canvas: List[List[int]]) -> List[int]:
    packed = []
    for row in canvas:
        for i in range(0, len(row), 8):
            chunk = row[i:i + 8]
            byte = 0
            for bit in chunk:
                byte = (byte << 1) | (1 if bit else 0)
            byte <<= (8 - len(chunk))
            packed.append(byte)
    return packed


def measure_text_width(text: str) -> int:
    return len(text) * 5 + max(0, len(text) - 1)


def draw_text_5x7(canvas: List[List[int]], text: str, start_x: int, start_y: int) -> None:
    cursor_x = start_x
    for ch in text:
        glyph = FONT_5X7.get(ch)
        if glyph is None:
            cursor_x += 6
            continue
        for row in range(7):
            row_bits = glyph[row]
            for col in range(5):
                if (row_bits >> (4 - col)) & 1:
                    x, y = cursor_x + col, start_y + row
                    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                        canvas[y][x] = 1
        cursor_x += 6


def fill_rect(canvas: List[List[int]], x: int, y: int, w: int, h: int, value: int = 0) -> None:
    if w <= 0 or h <= 0:
        return
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(WIDTH, x + w)
    y1 = min(HEIGHT, y + h)
    for py in range(y0, y1):
        for px in range(x0, x1):
            canvas[py][px] = 1 if value else 0


def draw_tile_on_canvas(canvas: List[List[int]], tile: List[List[int]], x_offset: int, y_offset: int) -> None:
    tile_h = len(tile)
    tile_w = len(tile[0]) if tile_h > 0 else 0
    for y in range(tile_h):
        ty = y_offset + y
        if not (0 <= ty < HEIGHT):
            continue
        for x in range(tile_w):
            pixel = tile[y][x]
            if pixel == 0:
                continue
            tx = x_offset + x
            if 0 <= tx < WIDTH:
                canvas[ty][tx] = 1 if pixel == 1 else 0


def draw_scrolling_background(canvas: List[List[int]], tile: List[List[int]], scroll_x: int) -> None:
    raise NotImplementedError("use draw_scrolling_corridor_background")


def _hash2(a: int, b: int) -> int:
    return ((a * 73856093) ^ (b * 19349663) ^ 0x9E3779B9) & 0x7FFFFFFF


def _pick_alt_indices(variant_count: int) -> tuple[int | None, int | None]:
    """Pick at most two alternative variant indices globally."""
    if variant_count <= 1:
        return None, None
    alt_count = variant_count - 1
    a = 1
    if alt_count == 1:
        return a, None
    b = 2
    if b > alt_count:
        b = 1
    if b == a:
        return a, None
    return a, b


def _pick_brick_variant(
    brick_col: int,
    brick_row: int,
    variant_count: int,
    alt_a: int | None,
    alt_b: int | None,
) -> int:
    """Use base brick by default; place rare, isolated alternatives per world brick tile."""
    if variant_count <= 1:
        return 0
    h = _hash2(brick_col, brick_row)
    # Very rare anchor candidate.
    if (h % 97) != 0:
        return 0
    # Prevent grouped alternates by rejecting if immediate neighbors are candidates too.
    if (_hash2(brick_col - 1, brick_row) % 97) == 0 or (_hash2(brick_col + 1, brick_row) % 97) == 0:
        return 0
    if (_hash2(brick_col, brick_row - 1) % 97) == 0 or (_hash2(brick_col, brick_row + 1) % 97) == 0:
        return 0

    if alt_a is not None and (h % 2) == 0:
        return alt_a
    if alt_b is not None:
        return alt_b
    return 0


def _pick_door_world_x(segment_idx: int, segment_width: int, door_w: int) -> int | None:
    start_x = segment_idx * segment_width
    span = max(1, segment_width - door_w)
    h = _hash2(segment_idx, 131)
    return start_x + (h % span)


def _pick_bootstrap_door_world_x(bootstrap_width: int, door_w: int) -> int:
    span = max(1, bootstrap_width - door_w)
    return _hash2(0, 911) % span


def _rects_touch_or_overlap(ax: int, ay: int, aw: int, ah: int, bx: int, by: int, bw: int, bh: int, margin: int = 0) -> bool:
    return not (
        (ax + aw + margin) < bx
        or (bx + bw + margin) < ax
        or (ay + ah + margin) < by
        or (by + bh + margin) < ay
    )


def draw_scrolling_corridor_background(
    canvas: List[List[int]],
    brick_tiles: List[List[List[int]]],
    floor_tile: List[List[int]],
    door_tile: List[List[int]],
    torch_frames: List[List[List[int]]],
    scroll_x: int,
    anim_tick: int,
) -> None:
    if not brick_tiles:
        return
    brick_w, brick_h = len(brick_tiles[0][0]), len(brick_tiles[0])
    floor_w, floor_h = len(floor_tile[0]), len(floor_tile)

    floor_draw_h = min(CORRIDOR_FLOOR_HEIGHT, HEIGHT, floor_h)
    wall_h = max(0, HEIGHT - floor_draw_h)

    scroll_px = int(scroll_x)
    # Keep full world-space scroll for wall mapping to avoid wrap-induced jumps.
    offset_x = scroll_px

    # Overlap 1px brick borders on both axes to avoid double-thick seams.
    brick_step_x = max(1, brick_w - 1)
    brick_step_y = max(1, brick_h - 1)
    half_brick_step_x = max(1, brick_step_x // 2)
    alt_a, alt_b = _pick_alt_indices(len(brick_tiles))

    # Wall (brick) region; odd rows are shifted by half-brick for overlap pattern.
    for y in range(wall_h):
        world_y = y + BRICK_START_OFFSET_Y
        brick_row = world_y // brick_step_y
        brick_y = world_y % brick_step_y
        row_shift = half_brick_step_x if (brick_row % 2) else 0
        # Draw one extra brick-step worth of columns as right-side buffer.
        for x in range(WIDTH + brick_step_x):
            world_x = x + offset_x + BRICK_START_OFFSET_X + row_shift
            brick_col = world_x // brick_step_x
            brick_x = world_x % brick_step_x
            variant_idx = _pick_brick_variant(brick_col, brick_row, len(brick_tiles), alt_a, alt_b)
            brick_tile = brick_tiles[variant_idx]
            pixel = brick_tile[brick_y][brick_x]
            if pixel and x < WIDTH:
                canvas[y][x] = 1

    # Floor region (bottom N pixels), scrolling at the same rate.
    floor_src_y_start = max(0, floor_h - floor_draw_h)
    for dy in range(floor_draw_h):
        y = HEIGHT - floor_draw_h + dy
        fy = floor_src_y_start + dy
        for x in range(WIDTH):
            fx = (x + scroll_px) % floor_w
            if floor_tile[fy][fx]:
                canvas[y][x] = 1

    # Rare door on wall: aligned so door bottom touches floor top.
    # Drawn after bricks so it appears on top of the wall pattern.
    door_h = len(door_tile)
    door_w = len(door_tile[0]) if door_h > 0 else 0
    if door_w > 0 and door_h > 0:
        world_left = scroll_px
        world_right = world_left + WIDTH
        door_y = HEIGHT - floor_draw_h - door_h
        visible_door_rects: List[tuple[int, int, int, int]] = []

        # Guarantee one door within the first N full screens.
        bootstrap_width = max(1, DOOR_FIRST_SCREENS * WIDTH)
        if world_left < bootstrap_width:
            door_world_x = _pick_bootstrap_door_world_x(bootstrap_width, door_w)
            door_screen_x = door_world_x - world_left
            visible_door_rects.append((door_world_x, door_y, door_w, door_h))
            fill_rect(canvas, door_screen_x, door_y, door_w, door_h, 0)
            draw_tile_on_canvas(canvas, door_tile, door_screen_x, door_y)

        # After the bootstrap area: one door every M screens.
        segment_width = max(1, DOOR_SEGMENT_SCREENS * WIDTH)
        shifted_left = max(0, world_left - bootstrap_width)
        shifted_right = max(0, world_right - bootstrap_width)
        seg_start = shifted_left // segment_width
        seg_end = shifted_right // segment_width
        for seg in range(seg_start, seg_end + 1):
            door_world_x = bootstrap_width + _pick_door_world_x(seg, segment_width, door_w)
            door_screen_x = door_world_x - world_left
            visible_door_rects.append((door_world_x, door_y, door_w, door_h))
            fill_rect(canvas, door_screen_x, door_y, door_w, door_h, 0)
            draw_tile_on_canvas(canvas, door_tile, door_screen_x, door_y)

        # Torches on the middle of the wall, randomized in world space and animated.
        if torch_frames:
            torch_frame = torch_frames[anim_tick % len(torch_frames)]
            torch_h = len(torch_frame)
            torch_w = len(torch_frame[0]) if torch_h > 0 else 0
            if torch_w > 0 and torch_h > 0 and wall_h > 0:
                torch_y = max(0, (wall_h - torch_h) // 2)
                screen_idx_start = (world_left // WIDTH) - 1
                screen_idx_end = (world_right // WIDTH) + 1
                for screen_idx in range(screen_idx_start, screen_idx_end + 1):
                    for i in range(max(0, TORCHES_PER_SCREEN)):
                        x_span = max(1, WIDTH - torch_w)
                        local_x = _hash2(screen_idx, 4001 + i * 97) % x_span
                        torch_world_x = screen_idx * WIDTH + local_x

                        blocked_by_door = False
                        for door_world_x, dy, dw, dh in visible_door_rects:
                            if _rects_touch_or_overlap(torch_world_x, torch_y, torch_w, torch_h, door_world_x, dy, dw, dh, margin=1):
                                blocked_by_door = True
                                break
                        if blocked_by_door:
                            continue

                        torch_screen_x = torch_world_x - world_left
                        if torch_screen_x <= -torch_w or torch_screen_x >= WIDTH:
                            continue
                        draw_tile_on_canvas(canvas, torch_frame, torch_screen_x, torch_y)


def draw_rounded_health_bar(canvas: List[List[int]], x: int, y: int, width: int, current: int, max_val: int) -> None:
    if width < 4:
        return
    l, r, t, b = x, x + width - 1, y, y + 4
    for px in range(l + 1, r):
        if 0 <= t < HEIGHT: canvas[t][px] = 1
        if 0 <= b < HEIGHT: canvas[b][px] = 1
    for py in range(t + 1, b):
        if 0 <= py < HEIGHT:
            if 0 <= l < WIDTH: canvas[py][l] = 1
            if 0 <= r < WIDTH: canvas[py][r] = 1
    il, ir, it, ib = l + 1, r - 1, t + 1, b - 1
    inner_w = max(0, ir - il + 1)
    fill = int(round(inner_w * max(0, min(current, max_val)) / max_val)) if max_val > 0 else 0
    for py in range(it, ib + 1):
        if not (0 <= py < HEIGHT): continue
        for px in range(il, il + fill):
            if 0 <= px < WIDTH: canvas[py][px] = 1


def make_minimal_background_tile() -> List[List[int]]:
    tile = [[0] * BACKGROUND_TILE_SIZE for _ in range(BACKGROUND_TILE_SIZE)]
    tile[0][0] = 1
    tile[5][3] = 1
    return tile


def _draw_centered_lines(canvas: List[List[int]], lines: List[str]) -> None:
    line_h = 8  # 7px + 1 spacing
    total_h = len(lines) * line_h - 1
    start_y = max(0, (HEIGHT - total_h) // 2)
    for i, line in enumerate(lines):
        x = max(0, (WIDTH - measure_text_width(line)) // 2)
        draw_text_5x7(canvas, line, x, start_y + i * line_h)


def _extract_best_score_stats(best_score: dict | None) -> tuple[int, int, int]:
    if not isinstance(best_score, dict):
        return 0, 0, 1
    try:
        return (
            max(0, int(best_score.get("keystrokes", 0))),
            max(0, int(best_score.get("monsters_killed", 0))),
            max(1, int(best_score.get("level", 1))),
        )
    except (TypeError, ValueError):
        return 0, 0, 1


def compose_frame(state: RenderState) -> List[int]:
    canvas = [[0] * WIDTH for _ in range(HEIGHT)]
    draw_scrolling_corridor_background(
        canvas,
        state.background_brick_tiles,
        state.background_floor_tile,
        state.background_door_tile,
        state.background_torch_frames,
        state.background_scroll_x,
        state.background_anim_tick,
    )
    draw_tile_on_canvas(canvas, state.right_sprite_tile, state.right_sprite_x, HEIGHT - TILE_SIZE)
    draw_tile_on_canvas(canvas, state.left_sprite_tile, state.left_sprite_x, HEIGHT - TILE_SIZE)

    if state.slashfx_tile is not None:
        slashfx_x = state.left_sprite_x + ((state.right_sprite_x - state.left_sprite_x) // 2) + SLASHFX_X_OFFSET
        draw_tile_on_canvas(canvas, state.slashfx_tile, slashfx_x, HEIGHT - TILE_SIZE)

    if state.show_drop and state.drop_tile is not None:
        draw_tile_on_canvas(canvas, state.drop_tile, state.drop_x, state.drop_y)

    level_text_right = -2
    if state.show_hud:
        level_text = f"LV:{state.warrior_level}"
        level_w = measure_text_width(level_text)
        level_x = 1
        level_y = 0
        fill_rect(canvas, level_x - 1, level_y, level_w + 2, 8, 0)
        draw_text_5x7(canvas, level_text, level_x, level_y)
        level_text_right = level_w

        keys_text = str(state.keypress_count)
        keys_w = measure_text_width(keys_text)
        keys_x = max(0, WIDTH - keys_w - 1)
        keys_y = 0
        fill_rect(canvas, keys_x - 1, keys_y, keys_w + 2, 8, 0)
        draw_text_5x7(canvas, keys_text, keys_x, keys_y)

    if state.show_health_bar:
        desired_x = state.right_sprite_x + ((TILE_SIZE - HEALTH_BAR_WIDTH) // 2)
        bar_x = min(max(desired_x, level_text_right + 2), WIDTH - HEALTH_BAR_WIDTH)
        fill_rect(canvas, bar_x - 1, HEALTH_BAR_Y - 1, HEALTH_BAR_WIDTH + 2, 7, 0)
        draw_rounded_health_bar(canvas, bar_x, HEALTH_BAR_Y, HEALTH_BAR_WIDTH, state.right_sprite_value, state.right_sprite_max_value)

    return canvas_to_image_data(canvas)


def compose_shutdown_summary_frame(keystrokes: int, monsters_killed: int, level: int, top_place: int | None) -> List[int]:
    canvas = [[0] * WIDTH for _ in range(HEIGHT)]
    lines = [f"KEYS:{keystrokes}", f"KILLS:{monsters_killed}", f"LV:{level}"]
    if top_place is not None:
        lines.append(f"TOP:{top_place}")
    _draw_centered_lines(canvas, lines)
    return canvas_to_image_data(canvas)


def compose_best_score_frame(best_score: dict | None) -> List[int]:
    canvas = [[0] * WIDTH for _ in range(HEIGHT)]
    keystrokes, monsters_killed, level = _extract_best_score_stats(best_score)
    _draw_centered_lines(canvas, [f"TOP KEYS:{keystrokes}", f"KILLS:{monsters_killed}", f"LV:{level}"])
    return canvas_to_image_data(canvas)
