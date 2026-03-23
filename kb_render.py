from __future__ import annotations
from dataclasses import dataclass
from typing import List
from kb_config import BACKGROUND_DRAW_START_Y, BACKGROUND_TILE_SIZE, FONT_5X7, HEALTH_BAR_WIDTH, HEALTH_BAR_Y, HEIGHT, LEFT_SPRITE_X, SLASHFX_X_OFFSET, TILE_SIZE, WIDTH


@dataclass(frozen=True)
class RenderState:
    background_tile: List[List[int]]
    background_scroll_x: int
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


def draw_tile_on_canvas(canvas: List[List[int]], tile: List[List[int]], x_offset: int, y_offset: int) -> None:
    for y in range(TILE_SIZE):
        ty = y_offset + y
        if not (0 <= ty < HEIGHT):
            continue
        for x in range(TILE_SIZE):
            pixel = tile[y][x]
            if pixel == 0:
                continue
            tx = x_offset + x
            if 0 <= tx < WIDTH:
                canvas[ty][tx] = 1 if pixel == 1 else 0


def draw_scrolling_background(canvas: List[List[int]], tile: List[List[int]], scroll_x: int) -> None:
    tile_w, tile_h = len(tile[0]), len(tile)
    offset_x = scroll_x % tile_w
    for y in range(BACKGROUND_DRAW_START_Y, HEIGHT):
        ty = y % tile_h
        for x in range(WIDTH):
            if tile[ty][(x + offset_x) % tile_w]:
                canvas[y][x] = 1


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
    draw_scrolling_background(canvas, state.background_tile, state.background_scroll_x)
    draw_tile_on_canvas(canvas, state.right_sprite_tile, state.right_sprite_x, HEIGHT - TILE_SIZE)
    draw_tile_on_canvas(canvas, state.left_sprite_tile, state.left_sprite_x, HEIGHT - TILE_SIZE)

    if state.slashfx_tile is not None:
        slashfx_x = LEFT_SPRITE_X + ((state.right_sprite_x - LEFT_SPRITE_X) // 2) + SLASHFX_X_OFFSET
        draw_tile_on_canvas(canvas, state.slashfx_tile, slashfx_x, HEIGHT - TILE_SIZE)

    level_text_right = -2
    if state.show_hud:
        draw_text_5x7(canvas, f"LV:{state.warrior_level}", 1, 0)
        level_text_right = measure_text_width(f"LV:{state.warrior_level}")
        draw_text_5x7(canvas, str(state.keypress_count), max(0, WIDTH - measure_text_width(str(state.keypress_count)) - 1), 0)

    if state.show_health_bar:
        desired_x = state.right_sprite_x + ((TILE_SIZE - HEALTH_BAR_WIDTH) // 2)
        bar_x = min(max(desired_x, level_text_right + 2), WIDTH - HEALTH_BAR_WIDTH)
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
