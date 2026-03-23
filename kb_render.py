from __future__ import annotations

from typing import List

from kb_config import (
    BACKGROUND_DRAW_START_Y,
    BACKGROUND_TILE_SIZE,
    FONT_5X7,
    HEALTH_BAR_WIDTH,
    HEALTH_BAR_Y,
    HEIGHT,
    LEFT_SPRITE_X,
    SLASHFX_X_OFFSET,
    TILE_SIZE,
    WIDTH,
)


def _draw_centered_lines(canvas: List[List[int]], lines: List[str]) -> None:
    line_height = 7
    line_spacing = 1
    total_height = len(lines) * line_height + max(0, len(lines) - 1) * line_spacing
    start_y = max(0, (HEIGHT - total_height) // 2)

    for idx, line in enumerate(lines):
        line_width = measure_text_5x7_width(line)
        x = max(0, (WIDTH - line_width) // 2)
        y = start_y + idx * (line_height + line_spacing)
        draw_text_5x7(canvas, line, x, y)


def _extract_best_score_stats(best_score: dict | None) -> tuple[int, int, int]:
    if not isinstance(best_score, dict):
        return 0, 0, 1

    try:
        keystrokes = max(0, int(best_score.get("keystrokes", 0)))
        monsters_killed = max(0, int(best_score.get("monsters_killed", 0)))
        level = max(1, int(best_score.get("level", 1)))
    except (TypeError, ValueError):
        return 0, 0, 1

    return keystrokes, monsters_killed, level


def canvas_to_image_data(canvas: List[List[int]]) -> List[int]:
    packed: List[int] = []
    for row in canvas:
        byte = 0
        bit_count = 0
        for pixel in row:
            byte = (byte << 1) | (1 if pixel else 0)
            bit_count += 1
            if bit_count == 8:
                packed.append(byte)
                byte = 0
                bit_count = 0
        if bit_count:
            byte <<= 8 - bit_count
            packed.append(byte)
    return packed


def measure_text_5x7_width(text: str) -> int:
    char_w = 5
    spacing = 1
    return len(text) * char_w + max(0, len(text) - 1) * spacing


def draw_text_5x7(canvas: List[List[int]], text: str, start_x: int, start_y: int) -> None:
    char_w = 5
    char_h = 7
    spacing = 1

    cursor_x = start_x
    for ch in text:
        glyph = FONT_5X7.get(ch)
        if glyph is None:
            cursor_x += char_w + spacing
            continue

        for row in range(char_h):
            row_bits = glyph[row]
            for col in range(char_w):
                if (row_bits >> (char_w - 1 - col)) & 1:
                    x = cursor_x + col
                    y = start_y + row
                    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                        canvas[y][x] = 1

        cursor_x += char_w + spacing


def draw_key_counter(canvas: List[List[int]], count: int) -> None:
    text = str(count)
    text_width = measure_text_5x7_width(text)
    start_x = max(0, WIDTH - text_width - 1)
    draw_text_5x7(canvas, text, start_x, 0)


def draw_rounded_health_bar(
    canvas: List[List[int]], x: int, y: int, width: int, current_value: int, max_value: int
) -> None:
    height = 5
    if width < 4:
        return

    left = x
    right = x + width - 1
    top = y
    bottom = y + height - 1

    for px in range(left + 1, right):
        if 0 <= px < WIDTH:
            if 0 <= top < HEIGHT:
                canvas[top][px] = 1
            if 0 <= bottom < HEIGHT:
                canvas[bottom][px] = 1

    for py in range(top + 1, bottom):
        if 0 <= py < HEIGHT:
            if 0 <= left < WIDTH:
                canvas[py][left] = 1
            if 0 <= right < WIDTH:
                canvas[py][right] = 1

    inner_left = left + 1
    inner_right = right - 1
    inner_top = top + 1
    inner_bottom = bottom - 1
    inner_width = max(0, inner_right - inner_left + 1)

    if max_value <= 0:
        fill_ratio = 0.0
    else:
        clamped_current = max(0, min(current_value, max_value))
        fill_ratio = clamped_current / max_value

    fill_width = int(round(inner_width * fill_ratio))
    for py in range(inner_top, inner_bottom + 1):
        if not (0 <= py < HEIGHT):
            continue
        for px in range(inner_left, inner_left + fill_width):
            if 0 <= px < WIDTH:
                canvas[py][px] = 1


def draw_level_label(canvas: List[List[int]], level: int) -> None:
    draw_text_5x7(canvas, f"LV:{level}", 1, 0)


def draw_tile_on_canvas(
    canvas: List[List[int]], tile: List[List[int]], x_offset: int, y_offset: int
) -> None:
    for y in range(TILE_SIZE):
        target_y = y_offset + y
        if not (0 <= target_y < HEIGHT):
            continue
        for x in range(TILE_SIZE):
            pixel = tile[y][x]
            if pixel == 0:
                continue
            target_x = x_offset + x
            if 0 <= target_x < WIDTH:
                canvas[target_y][target_x] = 1 if pixel == 1 else 0


def make_minimal_background_tile() -> List[List[int]]:
    tile = [[0 for _ in range(BACKGROUND_TILE_SIZE)] for _ in range(BACKGROUND_TILE_SIZE)]
    tile[0][0] = 1
    tile[5][3] = 1
    return tile


def draw_scrolling_background(
    canvas: List[List[int]], tile: List[List[int]], scroll_x: int
) -> None:
    tile_w = len(tile[0])
    tile_h = len(tile)
    offset_x = scroll_x % tile_w

    for y in range(BACKGROUND_DRAW_START_Y, HEIGHT):
        ty = y % tile_h
        for x in range(WIDTH):
            tx = (x + offset_x) % tile_w
            if tile[ty][tx]:
                canvas[y][x] = 1


def compose_frame(
    background_tile: List[List[int]],
    background_scroll_x: int,
    right_sprite_tile: List[List[int]],
    right_sprite_x: int,
    left_sprite_tile: List[List[int]],
    left_sprite_x: int,
    warrior_level: int,
    keypress_count: int,
    right_sprite_value: int,
    right_sprite_max_value: int,
    show_health_bar: bool,
    show_hud: bool,
    slashfx_tile: List[List[int]] | None,
) -> List[int]:
    canvas = [[0 for _ in range(WIDTH)] for _ in range(HEIGHT)]
    draw_scrolling_background(canvas, background_tile, background_scroll_x)
    draw_tile_on_canvas(canvas, right_sprite_tile, right_sprite_x, HEIGHT - TILE_SIZE)
    draw_tile_on_canvas(canvas, left_sprite_tile, left_sprite_x, HEIGHT - TILE_SIZE)

    if slashfx_tile is not None:
        slashfx_x = LEFT_SPRITE_X + ((right_sprite_x - LEFT_SPRITE_X) // 2) + SLASHFX_X_OFFSET
        draw_tile_on_canvas(canvas, slashfx_tile, slashfx_x, HEIGHT - TILE_SIZE)

    if show_hud:
        level_text = f"LV:{warrior_level}"
        level_text_right = 1 + measure_text_5x7_width(level_text) - 1
        draw_level_label(canvas, warrior_level)
    else:
        level_text_right = -2

    if show_health_bar:
        desired_bar_x = right_sprite_x + ((TILE_SIZE - HEALTH_BAR_WIDTH) // 2)
        min_bar_x = level_text_right + 2
        max_bar_x = WIDTH - HEALTH_BAR_WIDTH
        bar_x = min(max(desired_bar_x, min_bar_x), max_bar_x)
        draw_rounded_health_bar(
            canvas,
            bar_x,
            HEALTH_BAR_Y,
            HEALTH_BAR_WIDTH,
            right_sprite_value,
            right_sprite_max_value,
        )

    if show_hud:
        draw_key_counter(canvas, keypress_count)

    return canvas_to_image_data(canvas)


def compose_shutdown_summary_frame(
    keystrokes: int, monsters_killed: int, level: int, top_place: int | None
) -> List[int]:
    canvas = [[0 for _ in range(WIDTH)] for _ in range(HEIGHT)]

    lines = [
        f"KEYS:{keystrokes}",
        f"KILLS:{monsters_killed}",
        f"LV:{level}",
    ]
    if top_place is not None:
        lines.append(f"TOP:{top_place}")

    _draw_centered_lines(canvas, lines)

    return canvas_to_image_data(canvas)


def compose_best_score_frame(best_score: dict | None) -> List[int]:
    canvas = [[0 for _ in range(WIDTH)] for _ in range(HEIGHT)]

    keystrokes, monsters_killed, level = _extract_best_score_stats(best_score)

    lines = [
        f"TOP KEYS:{keystrokes}",
        f"KILLS:{monsters_killed}",
        f"LV:{level}",
    ]

    _draw_centered_lines(canvas, lines)

    return canvas_to_image_data(canvas)
