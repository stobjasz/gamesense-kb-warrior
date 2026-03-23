"""
Keyboard Warrior entrypoint.

Run:
    python kbwarrior.py
"""

from __future__ import annotations

import atexit
import ctypes
import ctypes.wintypes as wt
import sys
import threading
import time
from datetime import datetime
from typing import List
from urllib.error import HTTPError, URLError

import kb_config as cfg
import kb_gamesense
import kb_input
import kb_lock
import kb_progression
import kb_render
import kb_scores
import kb_sprites
import kb_tray


WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_CLOSE = 0x0010
LRESULT = ctypes.c_ssize_t


class WindowsShutdownListener:
    """Listens for Windows shutdown/restart and requests graceful app stop."""

    def __init__(self, on_shutdown: callable):
        self._on_shutdown = on_shutdown
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._ready = threading.Event()
        self._hwnd: int | None = None
        self._class_name = f"KBWarriorShutdownListener_{id(self)}"
        self._hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        self._wndproc_ref = None
        self._class_atom = 0

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def stop(self) -> None:
        self._running.clear()
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _message_loop(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.RegisterClassW.argtypes = [ctypes.c_void_p]
        user32.RegisterClassW.restype = wt.ATOM
        user32.CreateWindowExW.argtypes = [
            wt.DWORD,
            wt.LPCWSTR,
            wt.LPCWSTR,
            wt.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wt.HWND,
            wt.HMENU,
            wt.HINSTANCE,
            wt.LPVOID,
        ]
        user32.CreateWindowExW.restype = wt.HWND
        user32.GetMessageW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.TranslateMessage.restype = ctypes.c_bool
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.restype = LRESULT
        user32.DestroyWindow.argtypes = [wt.HWND]
        user32.DestroyWindow.restype = ctypes.c_bool
        user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
        user32.UnregisterClassW.restype = ctypes.c_bool
        user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.PostMessageW.restype = ctypes.c_bool

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wt.UINT),
                ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON),
                ("hCursor", wt.HCURSOR),
                ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wt.HWND),
                ("message", wt.UINT),
                ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM),
                ("time", wt.DWORD),
                ("pt", wt.POINT),
            ]

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_QUERYENDSESSION:
                return 1
            if msg == WM_ENDSESSION and wparam:
                self._on_shutdown()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROCTYPE(wnd_proc)
        wnd_class = WNDCLASSW()
        wnd_class.lpfnWndProc = self._wndproc_ref
        wnd_class.hInstance = self._hinst
        wnd_class.lpszClassName = self._class_name

        self._class_atom = user32.RegisterClassW(ctypes.byref(wnd_class))
        if not self._class_atom:
            self._ready.set()
            return

        self._hwnd = user32.CreateWindowExW(
            0,
            self._class_name,
            "KBWarriorShutdownWindow",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self._hinst,
            None,
        )
        self._ready.set()
        if not self._hwnd:
            user32.UnregisterClassW(self._class_name, self._hinst)
            return

        msg = MSG()
        while self._running.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._class_atom:
            user32.UnregisterClassW(self._class_name, self._hinst)


def format_tray_tooltip(
    warrior_level: int,
    monsters_killed: int,
    keycount: int,
    retriable_error: str | None,
    next_retry_at_monotonic: float,
) -> str:
    stats_line = f"LV:{warrior_level} K:{monsters_killed} Keys:{keycount}"

    if not retriable_error:
        return stats_line

    error_text = retriable_error.replace("\n", " ").strip()
    if len(error_text) > 45:
        error_text = error_text[:42] + "..."
    error_line = f"Err: {error_text}"
    retry_in = max(0.0, next_retry_at_monotonic - time.monotonic())
    retry_line = f"Retry: {retry_in:.1f}s"
    return f"{stats_line}\n{error_line}\n{retry_line}"


def retry_gamesense_connection_if_due(
    gamesense_base_url: str | None,
    gamesense_next_retry_at: float,
    loop_start: float,
) -> tuple[str | None, str | None, float]:
    if gamesense_base_url is not None or loop_start < gamesense_next_retry_at:
        return gamesense_base_url, None, gamesense_next_retry_at

    gamesense_base_url, connect_error = kb_gamesense.connect_gamesense_with_error()
    if gamesense_base_url is None:
        return (
            None,
            connect_error or "GameSense reconnect failed",
            loop_start + cfg.GAMESENSE_RETRY_SECONDS,
        )
    return gamesense_base_url, None, 0.0


def maybe_save_current_stats(
    loop_start: float,
    next_stats_save_at: float,
    stats_save_interval_seconds: float,
    session_started_at: str,
    current_keypress_count: int,
    monsters_killed: int,
    warrior_level: int,
) -> float:
    if stats_save_interval_seconds <= 0 or loop_start < next_stats_save_at:
        return next_stats_save_at

    try:
        kb_scores.update_current_stats(
            cfg.HIGH_SCORES_PATH,
            session_started_at,
            current_keypress_count,
            monsters_killed,
            warrior_level,
        )
    except OSError as exc:
        print(
            f"Warning: could not update current stats: {exc}",
            file=sys.stderr,
        )
    return loop_start + stats_save_interval_seconds


def maybe_start_warrior_action(
    warrior_state: str,
    is_sliding: bool,
    deathfx_active: bool,
    monster_refresh_active: bool,
    run_post_slide_remaining: int,
    new_space_presses: int,
    new_other_presses: int,
    slashfx_frames: List[List[List[int]]],
) -> tuple[str, int, float, List[List[List[int]]] | None]:
    if (
        is_sliding
        or deathfx_active
        or monster_refresh_active
        or warrior_state != "idle"
        or run_post_slide_remaining != 0
    ):
        return warrior_state, 0, 0.0, None

    if new_space_presses > 0:
        return "block", 0, 0.0, None

    if new_other_presses > 0:
        return "attack", 0, 0.0, slashfx_frames

    return warrior_state, 0, 0.0, None


def send_frame_with_retry(
    gamesense_base_url: str | None,
    combined_frame: dict,
) -> tuple[str | None, str | None, float]:
    if gamesense_base_url is None:
        return None, None, 0.0

    try:
        kb_gamesense.send_frame(gamesense_base_url, combined_frame)
        return gamesense_base_url, None, 0.0
    except (URLError, HTTPError, OSError) as exc:
        return (
            None,
            f"send failed: {exc}",
            time.monotonic() + cfg.GAMESENSE_RETRY_SECONDS,
        )


def update_monster_slide_and_refresh(
    monster_refresh_active: bool,
    right_sprite_x: float,
    right_sprite_target_x: float,
    delta_seconds: float,
    character_frames: List[List[List[int]]],
    warrior_level: int,
) -> tuple[bool, float, float, int, List[List[List[int]]], int]:
    selected_character_frames: List[List[List[int]]] | None = None
    right_sprite_max_hp = 0
    right_sprite_frame_index = 0

    if monster_refresh_active:
        right_sprite_x = min(
            cfg.RIGHT_SPRITE_START_X,
            right_sprite_x + cfg.RIGHT_SPRITE_SLIDE_PX_PER_SECOND * delta_seconds,
        )

        if right_sprite_x >= cfg.RIGHT_SPRITE_START_X:
            (
                selected_character_frames,
                right_sprite_target_x,
                right_sprite_max_hp,
            ) = kb_sprites.spawn_right_sprite(
                character_frames,
                cfg.LEFT_SPRITE_X,
                cfg.LEFT_SPRITE_COLLISION_RIGHTMOST,
                warrior_level,
            )
            right_sprite_x = float(cfg.RIGHT_SPRITE_START_X)
            right_sprite_frame_index = 0
            monster_refresh_active = False
    elif right_sprite_x > right_sprite_target_x:
        right_sprite_x = max(
            right_sprite_target_x,
            right_sprite_x - cfg.RIGHT_SPRITE_SLIDE_PX_PER_SECOND * delta_seconds,
        )

    return (
        monster_refresh_active,
        right_sprite_x,
        right_sprite_target_x,
        right_sprite_max_hp,
        selected_character_frames,
        right_sprite_frame_index,
    )


def main() -> int:
    instance_lock = kb_lock.acquire_instance_lock()
    if instance_lock is None:
        print("Another Keyboard Warrior instance is already running.", file=sys.stderr)
        return 1

    lock_fd, lock_path = instance_lock
    atexit.register(kb_lock.release_instance_lock, lock_fd, lock_path)

    try:
        character_frames = kb_sprites.load_character_frames(cfg.SPRITESHEET_PATH)
        warrior_animations = kb_sprites.load_warrior_animations()
        deathfx_frames = kb_sprites.load_sprite_strip_frames(cfg.DEATH_FX_PATH, 4)
        slashfx_frames = kb_sprites.load_slashfx_frames(cfg.SLASH_FX_PATH)
    except (OSError, ValueError) as exc:
        print(f"Asset loading error: {exc}", file=sys.stderr)
        return 1

    idle_warrior_frames = warrior_animations["idle"]
    run_warrior_frames = warrior_animations["run"]
    block_warrior_frames = warrior_animations["block"]
    attack_warrior_frames = warrior_animations["attack"]

    right_sprite_x = float(cfg.RIGHT_SPRITE_START_X)
    warrior_level = 1
    player_xp = 0
    current_monster_level = warrior_level

    selected_character_frames, right_sprite_target_x, right_sprite_max_hp = (
        kb_sprites.spawn_right_sprite(
            character_frames,
            cfg.LEFT_SPRITE_X,
            cfg.LEFT_SPRITE_COLLISION_RIGHTMOST,
            current_monster_level,
        )
    )

    right_sprite_value = right_sprite_max_hp
    deathfx_active = False
    deathfx_frame_index = 0
    active_slashfx_frames: List[List[List[int]]] | None = None
    background_tile = kb_render.make_minimal_background_tile()
    background_scroll_x = 0.0

    right_sprite_seconds_per_frame = kb_progression.compute_seconds_per_frame(
        cfg.RIGHT_SPRITE_CYCLE_SECONDS,
        cfg.FRAMES_PER_CHARACTER,
    )
    idle_seconds_per_frame = kb_progression.compute_seconds_per_frame(
        cfg.WARRIOR_IDLE_CYCLE_SECONDS,
        len(idle_warrior_frames),
    )
    run_seconds_per_frame = kb_progression.compute_seconds_per_frame(
        cfg.WARRIOR_RUN_CYCLE_SECONDS,
        len(run_warrior_frames),
    )
    block_seconds_per_frame = kb_progression.compute_seconds_per_frame(
        cfg.WARRIOR_BLOCK_DURATION_SECONDS,
        len(block_warrior_frames),
    )
    attack_seconds_per_frame = kb_progression.compute_seconds_per_frame(
        cfg.WARRIOR_ATTACK_DURATION_SECONDS,
        len(attack_warrior_frames),
    )
    deathfx_seconds_per_frame = kb_progression.compute_seconds_per_frame(
        cfg.DEATH_FX_DURATION_SECONDS,
        len(deathfx_frames),
    )

    right_sprite_frame_index = 0
    right_sprite_tick_accumulator = 0.0
    idle_frame_index = 0
    idle_tick_accumulator = 0.0
    run_tick_accumulator = 0.0
    state_tick_accumulator = 0.0
    deathfx_tick_accumulator = 0.0

    gamesense_base_url, gamesense_last_error = kb_gamesense.connect_gamesense_with_error()
    gamesense_next_retry_at = 0.0
    if gamesense_base_url is None:
        gamesense_next_retry_at = time.monotonic() + cfg.GAMESENSE_RETRY_SECONDS

    stop_event = threading.Event()
    shutdown_listener = None
    if sys.platform == "win32":
        shutdown_listener = WindowsShutdownListener(stop_event.set)
        shutdown_listener.start()

    best_score = kb_scores.get_best_score(cfg.HIGH_SCORES_PATH)
    if gamesense_base_url is not None and best_score is not None:
        try:
            best_score_frame = kb_render.compose_best_score_frame(best_score)
            kb_gamesense.send_frame(gamesense_base_url, best_score_frame)
            display_until = (
                time.monotonic() + max(0.0, cfg.STARTUP_BEST_SCORE_DISPLAY_SECONDS)
            )
            while not stop_event.is_set() and time.monotonic() < display_until:
                time.sleep(min(0.1, display_until - time.monotonic()))
        except (URLError, HTTPError, OSError) as exc:
            gamesense_base_url = None
            gamesense_last_error = f"send failed: {exc}"
            gamesense_next_retry_at = time.monotonic() + cfg.GAMESENSE_RETRY_SECONDS

    key_counter = [0]
    space_counter = [0]
    other_counter = [0]
    last_input_time = [time.monotonic()]
    counter_lock = threading.Lock()

    keyboard_listener, mouse_listener = kb_input.start_ctrl_d_listener(
        stop_event,
        key_counter,
        space_counter,
        other_counter,
        last_input_time,
        counter_lock,
    )
    tray_icon = kb_tray.start_tray_icon(stop_event)

    warrior_state = "idle"
    state_frame_index = 0
    last_seen_space_count = 0
    last_seen_other_count = 0
    run_frame_index = 0
    run_post_slide_remaining = 0
    was_sliding = right_sprite_x > right_sprite_target_x
    last_attack_end_keystrokes = 0
    monsters_killed = 0
    session_started_at = datetime.now().isoformat(timespec="seconds")
    stats_save_interval_seconds = max(0.0, cfg.CURRENT_STATS_SAVE_INTERVAL_SECONDS)
    next_stats_save_at = time.monotonic() + stats_save_interval_seconds
    monster_refresh_active = False
    idle_refresh_done_for_current_idle = False
    last_seen_input_time = last_input_time[0]
    kb_tray.update_tray_tooltip(
        tray_icon,
        format_tray_tooltip(
            warrior_level,
            monsters_killed,
            key_counter[0],
            gamesense_last_error,
            gamesense_next_retry_at,
        ),
    )

    try:
        update_interval = 1.0 / cfg.FRAMES_PER_SECOND
        last_loop_time = time.monotonic()

        while not stop_event.is_set():
            loop_start = time.monotonic()

            (
                gamesense_base_url,
                reconnect_error,
                gamesense_next_retry_at,
            ) = retry_gamesense_connection_if_due(
                gamesense_base_url,
                gamesense_next_retry_at,
                loop_start,
            )
            if reconnect_error is not None or gamesense_base_url is not None:
                gamesense_last_error = reconnect_error

            delta_seconds = max(0.0, min(loop_start - last_loop_time, 0.25))
            last_loop_time = loop_start
            is_sliding = right_sprite_x > right_sprite_target_x

            right_sprite_tick_accumulator, right_sprite_advances = (
                kb_progression.advance_frame_timer(
                    right_sprite_tick_accumulator,
                    delta_seconds,
                    right_sprite_seconds_per_frame,
                )
            )
            if right_sprite_advances > 0:
                right_sprite_frame_index = (
                    right_sprite_frame_index + right_sprite_advances
                ) % cfg.FRAMES_PER_CHARACTER

            if is_sliding:
                background_scroll_x += cfg.BACKGROUND_SCROLL_PX_PER_SECOND * delta_seconds

            if (
                was_sliding
                and (not is_sliding)
                and (warrior_state == "idle")
                and (run_post_slide_remaining == 0)
                and (run_frame_index != 0)
            ):
                run_post_slide_remaining = len(run_warrior_frames) - run_frame_index

            with counter_lock:
                current_keypress_count = key_counter[0]
                current_space_count = space_counter[0]
                current_other_count = other_counter[0]
                current_last_input_time = last_input_time[0]

            next_stats_save_at = maybe_save_current_stats(
                loop_start,
                next_stats_save_at,
                stats_save_interval_seconds,
                session_started_at,
                current_keypress_count,
                monsters_killed,
                warrior_level,
            )

            if current_last_input_time != last_seen_input_time:
                idle_refresh_done_for_current_idle = False
                last_seen_input_time = current_last_input_time

            hud_inactivity_seconds = time.monotonic() - current_last_input_time
            show_hud = hud_inactivity_seconds < cfg.HUD_HIDE_AFTER_INACTIVITY_SECONDS

            should_refresh_monster = (
                (not idle_refresh_done_for_current_idle)
                and (not monster_refresh_active)
                and (not deathfx_active)
                and (hud_inactivity_seconds >= cfg.MONSTER_REFRESH_AFTER_INACTIVITY_SECONDS)
            )
            if should_refresh_monster:
                monster_refresh_active = True
                idle_refresh_done_for_current_idle = True

            new_space_presses = max(0, current_space_count - last_seen_space_count)
            new_other_presses = max(0, current_other_count - last_seen_other_count)

            (
                next_state,
                next_state_frame_index,
                next_state_tick_accumulator,
                next_active_slashfx_frames,
            ) = maybe_start_warrior_action(
                warrior_state,
                is_sliding,
                deathfx_active,
                monster_refresh_active,
                run_post_slide_remaining,
                new_space_presses,
                new_other_presses,
                slashfx_frames,
            )
            if next_state != warrior_state:
                warrior_state = next_state
                state_frame_index = next_state_frame_index
                state_tick_accumulator = next_state_tick_accumulator
                active_slashfx_frames = next_active_slashfx_frames

            current_slashfx_tile: List[List[int]] | None = None

            if warrior_state == "attack":
                if active_slashfx_frames is not None and attack_warrior_frames:
                    attack_len = len(attack_warrior_frames)
                    slash_len = len(active_slashfx_frames)
                    if slash_len > 0:
                        slash_frame_idx = min(
                            slash_len - 1,
                            int(state_frame_index * slash_len / attack_len),
                        )
                        current_slashfx_tile = active_slashfx_frames[slash_frame_idx]

                warrior_tile = attack_warrior_frames[state_frame_index]
                state_tick_accumulator, attack_advances = kb_progression.advance_frame_timer(
                    state_tick_accumulator,
                    delta_seconds,
                    attack_seconds_per_frame,
                )
                if attack_advances > 0:
                    state_frame_index += attack_advances

                if state_frame_index >= len(attack_warrior_frames):
                    warrior_state = "idle"
                    state_frame_index = 0
                    state_tick_accumulator = 0.0
                    active_slashfx_frames = None

                    with counter_lock:
                        current_keypress_count = key_counter[0]

                    damage_per_keystroke = kb_progression.compute_damage_per_keystroke(
                        warrior_level
                    )
                    attack_damage = max(
                        0,
                        (current_keypress_count - last_attack_end_keystrokes)
                        * damage_per_keystroke,
                    )
                    last_attack_end_keystrokes = current_keypress_count
                    right_sprite_value -= attack_damage

                    if right_sprite_value <= 0:
                        monsters_killed += 1
                        player_xp += kb_progression.compute_monster_xp(
                            current_monster_level
                        )
                        while player_xp >= kb_progression.xp_total_for_level(
                            warrior_level + 1
                        ):
                            warrior_level += 1

                        deathfx_active = True
                        deathfx_frame_index = 0
                        deathfx_tick_accumulator = 0.0
                        right_sprite_x = right_sprite_target_x

            elif warrior_state == "block":
                warrior_tile = block_warrior_frames[state_frame_index]
                state_tick_accumulator, block_advances = kb_progression.advance_frame_timer(
                    state_tick_accumulator,
                    delta_seconds,
                    block_seconds_per_frame,
                )
                if block_advances > 0:
                    state_frame_index += block_advances
                if state_frame_index >= len(block_warrior_frames):
                    warrior_state = "idle"
                    state_frame_index = 0
                    state_tick_accumulator = 0.0

            else:
                if is_sliding or run_post_slide_remaining > 0:
                    warrior_tile = run_warrior_frames[run_frame_index]
                    run_tick_accumulator, run_advances = kb_progression.advance_frame_timer(
                        run_tick_accumulator,
                        delta_seconds,
                        run_seconds_per_frame,
                    )
                    if run_advances > 0:
                        run_frame_index = (run_frame_index + run_advances) % len(
                            run_warrior_frames
                        )
                    if (not is_sliding) and run_post_slide_remaining > 0 and run_advances > 0:
                        run_post_slide_remaining = max(
                            0,
                            run_post_slide_remaining - run_advances,
                        )
                else:
                    warrior_tile = idle_warrior_frames[idle_frame_index]
                    idle_tick_accumulator, idle_advances = kb_progression.advance_frame_timer(
                        idle_tick_accumulator,
                        delta_seconds,
                        idle_seconds_per_frame,
                    )
                    if idle_advances > 0:
                        idle_frame_index = (idle_frame_index + idle_advances) % len(
                            idle_warrior_frames
                        )
                    run_frame_index = 0
                    run_tick_accumulator = 0.0

            if deathfx_active:
                right_sprite_tile = deathfx_frames[deathfx_frame_index]
                deathfx_tick_accumulator, deathfx_advances = kb_progression.advance_frame_timer(
                    deathfx_tick_accumulator,
                    delta_seconds,
                    deathfx_seconds_per_frame,
                )
                if deathfx_advances > 0:
                    deathfx_frame_index += deathfx_advances

                if deathfx_frame_index >= len(deathfx_frames):
                    deathfx_active = False
                    deathfx_frame_index = 0
                    deathfx_tick_accumulator = 0.0
                    (
                        selected_character_frames,
                        right_sprite_target_x,
                        right_sprite_max_hp,
                    ) = kb_sprites.spawn_right_sprite(
                        character_frames,
                        cfg.LEFT_SPRITE_X,
                        cfg.LEFT_SPRITE_COLLISION_RIGHTMOST,
                        warrior_level,
                    )
                    current_monster_level = warrior_level
                    right_sprite_value = right_sprite_max_hp
                    right_sprite_x = cfg.RIGHT_SPRITE_START_X
            else:
                right_sprite_tile = selected_character_frames[right_sprite_frame_index]

            show_health_bar = (
                right_sprite_x <= right_sprite_target_x
                and (not deathfx_active)
                and (not monster_refresh_active)
            )

            combined_frame = kb_render.compose_frame(
                background_tile,
                int(background_scroll_x),
                right_sprite_tile,
                int(right_sprite_x),
                warrior_tile,
                cfg.LEFT_SPRITE_X,
                warrior_level,
                current_keypress_count,
                right_sprite_value,
                right_sprite_max_hp,
                show_health_bar,
                show_hud,
                current_slashfx_tile,
            )

            (
                gamesense_base_url,
                send_error,
                send_retry_at,
            ) = send_frame_with_retry(gamesense_base_url, combined_frame)
            if send_error is not None:
                gamesense_last_error = send_error
                gamesense_next_retry_at = send_retry_at
            elif gamesense_base_url is not None:
                gamesense_last_error = None
                gamesense_next_retry_at = 0.0

            kb_tray.update_tray_tooltip(
                tray_icon,
                format_tray_tooltip(
                    warrior_level,
                    monsters_killed,
                    current_keypress_count,
                    gamesense_last_error,
                    gamesense_next_retry_at,
                ),
            )

            last_seen_space_count = current_space_count
            last_seen_other_count = current_other_count

            (
                monster_refresh_active,
                right_sprite_x,
                right_sprite_target_x,
                refreshed_max_hp,
                refreshed_character_frames,
                refreshed_frame_index,
            ) = update_monster_slide_and_refresh(
                monster_refresh_active,
                right_sprite_x,
                right_sprite_target_x,
                delta_seconds,
                character_frames,
                warrior_level,
            )
            if refreshed_character_frames is not None:
                selected_character_frames = refreshed_character_frames
                current_monster_level = warrior_level
                right_sprite_max_hp = refreshed_max_hp
                right_sprite_value = right_sprite_max_hp
                right_sprite_frame_index = refreshed_frame_index

            was_sliding = right_sprite_x > right_sprite_target_x
            remaining = update_interval - (time.monotonic() - loop_start)
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()

        if shutdown_listener is not None:
            shutdown_listener.stop()

        keyboard_listener.stop()
        mouse_listener.stop()
        keyboard_listener.join(timeout=1)
        mouse_listener.join(timeout=1)

        if tray_icon is not None:
            try:
                tray_icon.stop()
            except Exception:
                pass

        with counter_lock:
            final_keystrokes = key_counter[0]

        top_place: int | None = None
        try:
            top_place = kb_scores.record_high_score(
                cfg.HIGH_SCORES_PATH,
                session_started_at,
                final_keystrokes,
                monsters_killed,
                warrior_level,
            )
        except OSError as exc:
            print(f"Warning: could not save high scores: {exc}", file=sys.stderr)

        if gamesense_base_url is not None:
            try:
                summary_frame = kb_render.compose_shutdown_summary_frame(
                    final_keystrokes,
                    monsters_killed,
                    warrior_level,
                    top_place,
                )
                kb_gamesense.send_frame(gamesense_base_url, summary_frame)
                time.sleep(5)
            except (URLError, HTTPError, OSError):
                pass

            kb_gamesense.clear_and_stop(gamesense_base_url)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
