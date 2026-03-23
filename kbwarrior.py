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
from dataclasses import dataclass, field
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
from kb_warrior_state import WarriorAnimations, WarriorStateController, WarriorTiming

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION      = 0x0016
WM_CLOSE           = 0x0010
LRESULT            = ctypes.c_ssize_t


# ── Windows shutdown listener ─────────────────────────────────────────────────

class WindowsShutdownListener:
    """Listens for Windows shutdown/restart and requests graceful app stop."""

    def __init__(self, on_shutdown: callable) -> None:
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

        # Set argtypes/restype once per thread
        user32.DefWindowProcW.argtypes  = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype   = LRESULT
        user32.RegisterClassW.argtypes  = [ctypes.c_void_p]
        user32.RegisterClassW.restype   = wt.ATOM
        user32.CreateWindowExW.argtypes = [
            wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
        ]
        user32.CreateWindowExW.restype  = wt.HWND
        user32.GetMessageW.argtypes     = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT]
        user32.GetMessageW.restype      = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.TranslateMessage.restype  = ctypes.c_bool
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.restype  = LRESULT
        user32.DestroyWindow.argtypes    = [wt.HWND]
        user32.DestroyWindow.restype     = ctypes.c_bool
        user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
        user32.UnregisterClassW.restype  = ctypes.c_bool
        user32.PostMessageW.argtypes     = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.PostMessageW.restype      = ctypes.c_bool

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style",         wt.UINT), ("lpfnWndProc",  WNDPROCTYPE),
                ("cbClsExtra",    ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance",     wt.HINSTANCE), ("hIcon",    wt.HICON),
                ("hCursor",       wt.HCURSOR), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName",  wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wt.HWND), ("message", wt.UINT),
                ("wParam", wt.WPARAM), ("lParam", wt.LPARAM),
                ("time", wt.DWORD), ("pt", wt.POINT),
            ]

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_QUERYENDSESSION: return 1
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
            0, self._class_name, "KBWarriorShutdownWindow",
            0, 0, 0, 0, 0, None, None, self._hinst, None,
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


# ── Game state dataclasses ────────────────────────────────────────────────────

@dataclass
class GameSenseState:
    base_url: str | None
    last_error: str | None
    next_retry_at: float


@dataclass
class MonsterState:
    frames: List[List[List[int]]]
    target_x: float
    max_hp: int
    hp: int
    level: int
    x: float
    frame_index: int = 0
    tick_accumulator: float = 0.0
    refresh_active: bool = False


@dataclass
class SessionState:
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    monsters_killed: int = 0
    warrior_level: int = 1
    player_xp: int = 0
    last_attack_end_keystrokes: int = 0
    next_stats_save_at: float = 0.0
    save_interval: float = 0.0


# ── Helper functions ──────────────────────────────────────────────────────────

def format_tray_tooltip(warrior_level: int, monsters_killed: int, keycount: int,
                        retriable_error: str | None, next_retry_at: float) -> str:
    stats = f"LV:{warrior_level} K:{monsters_killed} Keys:{keycount}"
    if not retriable_error:
        return stats
    err = retriable_error.replace("\n", " ").strip()
    if len(err) > 45:
        err = err[:42] + "..."
    retry_in = max(0.0, next_retry_at - time.monotonic())
    return f"{stats}\nErr: {err}\nRetry: {retry_in:.1f}s"


def retry_gamesense_if_due(gs: GameSenseState, loop_start: float) -> None:
    if gs.base_url is not None or loop_start < gs.next_retry_at:
        return
    url, err = kb_gamesense.connect_gamesense_with_error()
    if url is None:
        gs.last_error = err or "GameSense reconnect failed"
        gs.next_retry_at = loop_start + cfg.GAMESENSE_RETRY_SECONDS
    else:
        gs.base_url, gs.last_error, gs.next_retry_at = url, None, 0.0


def send_frame_with_retry(gs: GameSenseState, frame: List[int]) -> None:
    if gs.base_url is None:
        return
    try:
        kb_gamesense.send_frame(gs.base_url, frame)
        gs.last_error = None
        gs.next_retry_at = 0.0
    except (URLError, HTTPError, OSError) as exc:
        gs.base_url = None
        gs.last_error = f"send failed: {exc}"
        gs.next_retry_at = time.monotonic() + cfg.GAMESENSE_RETRY_SECONDS


def maybe_save_stats(session: SessionState, loop_start: float, keystrokes: int) -> None:
    if session.save_interval <= 0 or loop_start < session.next_stats_save_at:
        return
    try:
        kb_scores.upsert_high_score(
            cfg.HIGH_SCORES_PATH, session.started_at,
            keystrokes, session.monsters_killed, session.warrior_level,
        )
    except OSError as exc:
        print(f"Warning: could not update current stats: {exc}", file=sys.stderr)
    session.next_stats_save_at = loop_start + session.save_interval


def spawn_monster(character_frames, level: int) -> tuple:
    frames, target_x, max_hp = kb_sprites.spawn_right_sprite(
        character_frames, cfg.LEFT_SPRITE_X, cfg.LEFT_SPRITE_COLLISION_RIGHTMOST, level)
    return frames, target_x, max_hp


# ── Main ──────────────────────────────────────────────────────────────────────

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

    # Build warrior controller
    spf = kb_progression.compute_seconds_per_frame
    anim = warrior_animations
    warrior_controller = WarriorStateController(
        WarriorAnimations(idle=anim["idle"], run=anim["run"], block=anim["block"], attack=anim["attack"]),
        WarriorTiming(
            idle_seconds_per_frame=spf(cfg.WARRIOR_IDLE_CYCLE_SECONDS, len(anim["idle"])),
            run_seconds_per_frame=spf(cfg.WARRIOR_RUN_CYCLE_SECONDS, len(anim["run"])),
            block_seconds_per_frame=spf(cfg.WARRIOR_BLOCK_DURATION_SECONDS, len(anim["block"])),
            attack_seconds_per_frame=spf(cfg.WARRIOR_ATTACK_DURATION_SECONDS, len(anim["attack"])),
        ),
    )

    # Timings
    right_spf      = spf(cfg.RIGHT_SPRITE_CYCLE_SECONDS, cfg.FRAMES_PER_CHARACTER)
    deathfx_spf    = spf(cfg.DEATH_FX_DURATION_SECONDS, len(deathfx_frames))

    # Initial monster
    session = SessionState()
    session.save_interval = max(0.0, cfg.CURRENT_STATS_SAVE_INTERVAL_SECONDS)

    mon_frames, mon_target_x, mon_max_hp = spawn_monster(character_frames, session.warrior_level)
    monster = MonsterState(
        frames=mon_frames, target_x=mon_target_x, max_hp=mon_max_hp, hp=mon_max_hp,
        level=session.warrior_level, x=float(cfg.RIGHT_SPRITE_START_X),
    )

    background_tile     = kb_render.make_minimal_background_tile()
    background_scroll_x = 0.0
    deathfx_active      = False
    deathfx_frame_index = 0
    deathfx_tick_acc    = 0.0

    # GameSense
    gs_url, gs_err = kb_gamesense.connect_gamesense_with_error()
    gs = GameSenseState(
        base_url=gs_url, last_error=gs_err,
        next_retry_at=0.0 if gs_url else time.monotonic() + cfg.GAMESENSE_RETRY_SECONDS,
    )

    # Stop event + Windows shutdown listener
    stop_event = threading.Event()
    shutdown_listener = None
    if sys.platform == "win32":
        shutdown_listener = WindowsShutdownListener(stop_event.set)
        shutdown_listener.start()

    # Show best score on startup
    best_score = kb_scores.get_best_score(cfg.HIGH_SCORES_PATH)
    if gs.base_url and best_score:
        try:
            kb_gamesense.send_frame(gs.base_url, kb_render.compose_best_score_frame(best_score))
            display_until = time.monotonic() + max(0.0, cfg.STARTUP_BEST_SCORE_DISPLAY_SECONDS)
            while not stop_event.is_set() and time.monotonic() < display_until:
                time.sleep(min(0.1, display_until - time.monotonic()))
        except (URLError, HTTPError, OSError) as exc:
            gs.base_url = None
            gs.last_error = f"send failed: {exc}"
            gs.next_retry_at = time.monotonic() + cfg.GAMESENSE_RETRY_SECONDS

    input_stats = kb_input.InputStats()
    keyboard_listener, mouse_listener = kb_input.start_ctrl_d_listener(stop_event, input_stats)
    tray_icon = kb_tray.start_tray_icon(stop_event)

    last_seen_space   = 0
    last_seen_other   = 0
    was_sliding       = monster.x > monster.target_x
    idle_refresh_done = False
    _, _, _, last_input_time = input_stats.snapshot()
    session.next_stats_save_at = time.monotonic() + session.save_interval

    kb_tray.update_tray_tooltip(tray_icon, format_tray_tooltip(
        session.warrior_level, session.monsters_killed, input_stats.snapshot()[0],
        gs.last_error, gs.next_retry_at,
    ))

    update_interval = 1.0 / cfg.FRAMES_PER_SECOND
    last_loop_time   = time.monotonic()

    try:
        while not stop_event.is_set():
            loop_start = time.monotonic()
            retry_gamesense_if_due(gs, loop_start)

            delta = max(0.0, min(loop_start - last_loop_time, 0.25))
            last_loop_time = loop_start
            is_sliding = monster.x > monster.target_x

            # Advance monster sprite frame
            monster.tick_accumulator, adv = kb_progression.advance_frame_timer(monster.tick_accumulator, delta, right_spf)
            if adv > 0:
                monster.frame_index = (monster.frame_index + adv) % cfg.FRAMES_PER_CHARACTER

            if is_sliding:
                background_scroll_x += cfg.BACKGROUND_SCROLL_PX_PER_SECOND * delta

            warrior_controller.on_slide_state(was_sliding, is_sliding)

            keys, spaces, others, current_input_time = input_stats.snapshot()

            maybe_save_stats(session, loop_start, keys)

            if current_input_time != last_input_time:
                idle_refresh_done = False
                last_input_time = current_input_time

            inactivity = time.monotonic() - current_input_time
            show_hud    = inactivity < cfg.HUD_HIDE_AFTER_INACTIVITY_SECONDS

            if (not idle_refresh_done and not monster.refresh_active and not deathfx_active
                    and inactivity >= cfg.MONSTER_REFRESH_AFTER_INACTIVITY_SECONDS):
                monster.refresh_active = True
                idle_refresh_done = True

            new_spaces = max(0, spaces - last_seen_space)
            new_others = max(0, others - last_seen_other)

            warrior_controller.maybe_start_action(
                is_sliding, deathfx_active, monster.refresh_active,
                new_spaces, new_others, slashfx_frames,
            )
            warrior_tile, slashfx_tile, attack_finished = warrior_controller.advance(delta, is_sliding)

            if attack_finished:
                keys, _, _, _ = input_stats.snapshot()
                damage = max(0, (keys - session.last_attack_end_keystrokes)
                             * kb_progression.compute_damage_per_keystroke(session.warrior_level))
                session.last_attack_end_keystrokes = keys
                monster.hp -= damage

                if monster.hp <= 0:
                    session.monsters_killed += 1
                    session.player_xp += kb_progression.compute_monster_xp(monster.level)
                    while session.player_xp >= kb_progression.xp_total_for_level(session.warrior_level + 1):
                        session.warrior_level += 1
                    deathfx_active = True
                    deathfx_frame_index = 0
                    deathfx_tick_acc = 0.0
                    monster.x = monster.target_x

            # Death FX or normal monster tile
            if deathfx_active:
                right_sprite_tile = deathfx_frames[deathfx_frame_index]
                deathfx_tick_acc, adv = kb_progression.advance_frame_timer(deathfx_tick_acc, delta, deathfx_spf)
                if adv > 0:
                    deathfx_frame_index += adv
                if deathfx_frame_index >= len(deathfx_frames):
                    deathfx_active = False
                    deathfx_frame_index = 0
                    deathfx_tick_acc = 0.0
                    mon_frames, mon_target_x, mon_max_hp = spawn_monster(character_frames, session.warrior_level)
                    monster = MonsterState(
                        frames=mon_frames, target_x=mon_target_x, max_hp=mon_max_hp, hp=mon_max_hp,
                        level=session.warrior_level, x=float(cfg.RIGHT_SPRITE_START_X),
                    )
            else:
                right_sprite_tile = monster.frames[monster.frame_index]

            # Monster refresh slide
            if monster.refresh_active:
                monster.x = min(cfg.RIGHT_SPRITE_START_X, monster.x + cfg.RIGHT_SPRITE_SLIDE_PX_PER_SECOND * delta)
                if monster.x >= cfg.RIGHT_SPRITE_START_X:
                    mon_frames, mon_target_x, mon_max_hp = spawn_monster(character_frames, session.warrior_level)
                    monster = MonsterState(
                        frames=mon_frames, target_x=mon_target_x, max_hp=mon_max_hp, hp=mon_max_hp,
                        level=session.warrior_level, x=float(cfg.RIGHT_SPRITE_START_X),
                    )
            elif monster.x > monster.target_x:
                monster.x = max(monster.target_x, monster.x - cfg.RIGHT_SPRITE_SLIDE_PX_PER_SECOND * delta)

            show_health_bar = (
                monster.x <= monster.target_x and not deathfx_active and not monster.refresh_active
            )

            frame = kb_render.compose_frame(kb_render.RenderState(
                background_tile=background_tile,
                background_scroll_x=int(background_scroll_x),
                right_sprite_tile=right_sprite_tile,
                right_sprite_x=int(monster.x),
                left_sprite_tile=warrior_tile,
                left_sprite_x=cfg.LEFT_SPRITE_X,
                warrior_level=session.warrior_level,
                keypress_count=keys,
                right_sprite_value=monster.hp,
                right_sprite_max_value=monster.max_hp,
                show_health_bar=show_health_bar,
                show_hud=show_hud,
                slashfx_tile=slashfx_tile,
            ))
            send_frame_with_retry(gs, frame)

            kb_tray.update_tray_tooltip(tray_icon, format_tray_tooltip(
                session.warrior_level, session.monsters_killed, keys, gs.last_error, gs.next_retry_at,
            ))

            last_seen_space = spaces
            last_seen_other = others
            was_sliding = monster.x > monster.target_x

            remaining = update_interval - (time.monotonic() - loop_start)
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if shutdown_listener:
            shutdown_listener.stop()
        keyboard_listener.stop()
        mouse_listener.stop()
        keyboard_listener.join(timeout=1)
        mouse_listener.join(timeout=1)
        if tray_icon:
            try: tray_icon.stop()
            except Exception: pass

        final_keys, _, _, _ = input_stats.snapshot()
        top_place = None
        try:
            top_place = kb_scores.record_high_score(
                cfg.HIGH_SCORES_PATH, session.started_at,
                final_keys, session.monsters_killed, session.warrior_level,
            )
        except OSError as exc:
            print(f"Warning: could not save high scores: {exc}", file=sys.stderr)

        if gs.base_url:
            try:
                summary = kb_render.compose_shutdown_summary_frame(
                    final_keys, session.monsters_killed, session.warrior_level, top_place)
                kb_gamesense.send_frame(gs.base_url, summary)
                time.sleep(5)
            except (URLError, HTTPError, OSError):
                pass
            kb_gamesense.clear_and_stop(gs.base_url)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
