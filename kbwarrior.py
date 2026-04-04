"""
Keyboard Warrior entrypoint.

Run:
    python kbwarrior.py
"""
from __future__ import annotations

import atexit
import ctypes
import ctypes.wintypes as wt
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Literal
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
StopReason         = Literal["manual_quit", "tray_quit", "hotkey", "keyboard_interrupt", "system_shutdown"]


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


@dataclass
class DropState:
    tile: List[List[int]]
    x: float
    y: float
    expires_at: float
    spawned_at: float


@dataclass
class TransitionPixel:
    x: float
    y: int
    target_x: float
    speed: float


@dataclass
class SceneTransitionState:
    phase: str  # "out" or "in"
    target_scene_index: int
    target_scene_cfg: kb_sprites.CorridorSceneConfig
    target_static_sprites: dict
    target_animated_sprites: dict
    target_wall_bricks: list
    target_floor_tile: list
    old_pixels: List[TransitionPixel]
    new_pixels: List[TransitionPixel]
    warrior_x: float
    run_frame_index: int = 0
    run_tick_accumulator: float = 0.0


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


def spawn_monster(character_frames, level: int, warrior_x: int) -> tuple:
    frames, target_x, max_hp = kb_sprites.spawn_right_sprite(
        character_frames, warrior_x, cfg.LEFT_SPRITE_COLLISION_RIGHTMOST, level)
    return frames, target_x, max_hp


def render_scene_background_canvas(
    scene_cfg: kb_sprites.CorridorSceneConfig,
    static_sprites: dict,
    animated_sprites: dict,
    wall_bricks: list,
    floor_tile: list,
    scroll_x: float,
    anim_tick: int,
) -> List[List[int]]:
    del wall_bricks, floor_tile
    return kb_render.compose_scene_background_canvas(
        scene_layers=scene_cfg.layers,
        scene_mode=scene_cfg.scene_mode,
        background_wall_brick_tiles=[],
        background_floor_tile=[[0]],
        scene_static_sprites=static_sprites,
        scene_animated_sprites=animated_sprites,
        scene_placements=scene_cfg.placements,
        scene_sky_horizon=scene_cfg.sky_horizon,
        roof_eli_sprite_id=scene_cfg.roof_eli_sprite_id,
        background_scroll_x=scroll_x,
        background_anim_tick=anim_tick,
        corridor_floor_height=scene_cfg.floor_height,
        corridor_brick_start_offset_x=scene_cfg.brick_start_offset_x,
        corridor_brick_start_offset_y=scene_cfg.brick_start_offset_y,
        corridor_wall_underlay=scene_cfg.wall_underlay,
    )


def build_pixel_swarm(canvas: List[List[int]], direction: str) -> List[TransitionPixel]:
    pixels: List[TransitionPixel] = []
    for y in range(cfg.HEIGHT):
        for x in range(cfg.WIDTH):
            if not canvas[y][x]:
                continue
            if direction == "out_right":
                target_x = float(cfg.WIDTH + random.randint(8, 80))
                speed = float(random.randint(14, 50))
                pixels.append(TransitionPixel(x=float(x), y=y, target_x=target_x, speed=speed))
            else:
                start_x = float(x - cfg.WIDTH - random.randint(8, cfg.WIDTH + 20))
                speed = float(random.randint(85, 240))
                pixels.append(TransitionPixel(x=start_x, y=y, target_x=float(x), speed=speed))
    return pixels


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    instance_lock = kb_lock.acquire_instance_lock()
    if instance_lock is None:
        print("Another Keyboard Warrior instance is already running.", file=sys.stderr)
        return 1
    lock_fd, lock_path = instance_lock
    atexit.register(kb_lock.release_instance_lock, lock_fd, lock_path)

    scene_paths = [
        cfg.NIGHT01_SCENE_CONFIG_PATH,
        cfg.CORRIDOR_SCENE_CONFIG_PATH,
        cfg.ROOF01_SCENE_CONFIG_PATH,
    ]
    active_scene_index = random.randrange(len(scene_paths))

    def load_scene_for_path(scene_path):
        scene_cfg = kb_sprites.load_corridor_scene_config(scene_path)
        static_sprites, animated_sprites = kb_sprites.load_corridor_scene_assets(scene_cfg)

        wall_brick_tiles: List[List[List[int]]] = []
        floor_tile: List[List[int]] = [[0]]
        for layer in scene_cfg.layers:
            params = layer.params
            if layer.layer_type == "corridor":
                wall_brick_tiles = []
                for sprite_id in list(params["wall_brick_sprite_ids"]):
                    tile = static_sprites.get(sprite_id)
                    if tile is None:
                        raise ValueError(f"Scene wall sprite '{sprite_id}' must be a static sprite")
                    wall_brick_tiles.append(tile)
                if not wall_brick_tiles:
                    raise ValueError("Corridor layer must define at least one wall brick sprite")
                floor_tile = static_sprites.get(str(params["floor_sprite_id"]))
                if floor_tile is None:
                    raise ValueError(f"Scene floor sprite '{params['floor_sprite_id']}' must be a static sprite")
            elif layer.layer_type == "roof01":
                floor_tile = static_sprites.get(str(params["floor_sprite_id"]))
                if floor_tile is None:
                    raise ValueError(f"Scene floor sprite '{params['floor_sprite_id']}' must be a static sprite")
                eli_sprite_id = str(params["roof_eli_sprite_id"])
                eli_tile = static_sprites.get(eli_sprite_id)
                if eli_tile is None:
                    raise ValueError(f"Roof ELI sprite '{eli_sprite_id}' must be a static sprite")
            elif layer.layer_type == "sky_horizon":
                sky_sprite_id = str(params["sky_sprite_id"])
                sky_tile = static_sprites.get(sky_sprite_id)
                if sky_tile is None:
                    raise ValueError(f"Sky sprite '{sky_sprite_id}' must be a static sprite")

        return scene_cfg, static_sprites, animated_sprites, wall_brick_tiles, floor_tile

    try:
        corridor_scene, scene_static_sprites, scene_animated_sprites, background_wall_brick_tiles, background_floor_tile = load_scene_for_path(
            scene_paths[active_scene_index]
        )

        character_frames = kb_sprites.load_character_frames(cfg.SPRITESHEET_PATH)
        warrior_animations = kb_sprites.load_warrior_animations()
        deathfx_frames = kb_sprites.load_sprite_strip_frames(cfg.DEATH_FX_PATH, 4)
        slashfx_frames = kb_sprites.load_slashfx_frames(cfg.SLASH_FX_PATH)
        drop_tiles = kb_sprites.load_drop_tiles(cfg.DROPS_PATH)
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

    # Initial monster + warrior horizontal positioning
    session = SessionState()
    session.save_interval = max(0.0, cfg.CURRENT_STATS_SAVE_INTERVAL_SECONDS)

    warrior_x = float(cfg.LEFT_SPRITE_X)
    warrior_target_x = float(cfg.LEFT_SPRITE_X)

    def pick_warrior_spawn_target_x(current_x: float) -> float:
        delta = random.randint(-cfg.WARRIOR_SPAWN_SHIFT_MAX_PX, cfg.WARRIOR_SPAWN_SHIFT_MAX_PX)
        return float(min(cfg.WARRIOR_MAX_X, max(cfg.WARRIOR_MIN_X, int(round(current_x)) + delta)))

    warrior_target_x = pick_warrior_spawn_target_x(warrior_x)
    mon_frames, mon_target_x, mon_max_hp = spawn_monster(character_frames, session.warrior_level, int(round(warrior_target_x)))
    monster = MonsterState(
        frames=mon_frames, target_x=mon_target_x, max_hp=mon_max_hp, hp=mon_max_hp,
        level=session.warrior_level, x=float(cfg.RIGHT_SPRITE_START_X),
    )

    background_scroll_x = 0.0
    background_anim_tick = 0
    deathfx_active      = False
    deathfx_frame_index = 0
    deathfx_tick_acc    = 0.0
    active_drop: DropState | None = None

    # GameSense
    gs_url, gs_err = kb_gamesense.connect_gamesense_with_error()
    gs = GameSenseState(
        base_url=gs_url, last_error=gs_err,
        next_retry_at=0.0 if gs_url else time.monotonic() + cfg.GAMESENSE_RETRY_SECONDS,
    )

    stop_event = threading.Event()
    stop_reason: StopReason = "manual_quit"
    stop_reason_lock = threading.Lock()

    def request_stop(reason: StopReason) -> None:
        nonlocal stop_reason
        with stop_reason_lock:
            if reason == "system_shutdown" or not stop_event.is_set():
                stop_reason = reason
        stop_event.set()

    # Stop event + Windows shutdown listener
    shutdown_listener = None
    if sys.platform == "win32":
        def on_windows_shutdown() -> None:
            request_stop("system_shutdown")

        shutdown_listener = WindowsShutdownListener(on_windows_shutdown)
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
    keyboard_listener, mouse_listener = kb_input.start_ctrl_d_listener(stop_event, input_stats, on_stop=request_stop)
    tray_icon = kb_tray.start_tray_icon(stop_event, on_stop=request_stop)
    last_scene_toggle_count = input_stats.get_scene_toggle_count()
    pending_scene_steps = 0
    scene_transition: SceneTransitionState | None = None
    next_auto_scene_switch_at = time.monotonic() + cfg.SCENE_AUTO_SWITCH_SECONDS

    last_seen_space   = 0
    last_seen_other   = 0
    was_sliding = monster.x > monster.target_x
    initial_keys, _, _, last_input_time = input_stats.snapshot()
    next_idle_refresh_at = last_input_time + cfg.MONSTER_REFRESH_AFTER_INACTIVITY_SECONDS
    session.next_stats_save_at = time.monotonic() + session.save_interval
    tray_update_interval = 0.25
    next_tray_update_at = 0.0
    last_tray_tooltip: str | None = None

    def maybe_update_tray_tooltip(keys_count: int, force: bool = False) -> None:
        nonlocal next_tray_update_at, last_tray_tooltip
        if tray_icon is None:
            return
        now = time.monotonic()
        if not force and now < next_tray_update_at:
            return
        tooltip = format_tray_tooltip(
            session.warrior_level, session.monsters_killed, keys_count,
            gs.last_error, gs.next_retry_at,
        )
        if force or tooltip != last_tray_tooltip:
            kb_tray.update_tray_tooltip(tray_icon, tooltip)
            last_tray_tooltip = tooltip
        next_tray_update_at = now + tray_update_interval

    maybe_update_tray_tooltip(initial_keys, force=True)

    target_updates_per_second = max(1, min(cfg.FRAMES_PER_SECOND, cfg.DEVICE_UPDATES_PER_SECOND))
    update_interval = 1.0 / target_updates_per_second
    last_loop_time   = time.monotonic()

    try:
        while not stop_event.is_set():
            loop_start = time.monotonic()
            retry_gamesense_if_due(gs, loop_start)

            delta = max(0.0, min(loop_start - last_loop_time, 0.25))
            last_loop_time = loop_start
            keys, spaces, others, current_input_time = input_stats.snapshot()

            current_scene_toggle_count = input_stats.get_scene_toggle_count()
            if current_scene_toggle_count != last_scene_toggle_count:
                toggle_steps = max(0, current_scene_toggle_count - last_scene_toggle_count)
                last_scene_toggle_count = current_scene_toggle_count
                if toggle_steps > 0:
                    pending_scene_steps += toggle_steps
                    next_auto_scene_switch_at = time.monotonic() + cfg.SCENE_AUTO_SWITCH_SECONDS

            if time.monotonic() >= next_auto_scene_switch_at:
                pending_scene_steps += 1
                next_auto_scene_switch_at = time.monotonic() + cfg.SCENE_AUTO_SWITCH_SECONDS

            if scene_transition is None and pending_scene_steps > 0:
                next_scene_index = active_scene_index
                for _ in range(pending_scene_steps):
                    if len(scene_paths) <= 1:
                        break
                    candidates = [idx for idx in range(len(scene_paths)) if idx != next_scene_index]
                    next_scene_index = random.choice(candidates)
                pending_scene_steps = 0
                try:
                    (
                        target_scene_cfg,
                        target_static_sprites,
                        target_animated_sprites,
                        target_wall_bricks,
                        target_floor_tile,
                    ) = load_scene_for_path(scene_paths[next_scene_index])

                    old_canvas = render_scene_background_canvas(
                        corridor_scene,
                        scene_static_sprites,
                        scene_animated_sprites,
                        background_wall_brick_tiles,
                        background_floor_tile,
                        background_scroll_x,
                        background_anim_tick,
                    )
                    new_canvas = render_scene_background_canvas(
                        target_scene_cfg,
                        target_static_sprites,
                        target_animated_sprites,
                        target_wall_bricks,
                        target_floor_tile,
                        background_scroll_x,
                        background_anim_tick,
                    )

                    scene_transition = SceneTransitionState(
                        phase="out",
                        target_scene_index=next_scene_index,
                        target_scene_cfg=target_scene_cfg,
                        target_static_sprites=target_static_sprites,
                        target_animated_sprites=target_animated_sprites,
                        target_wall_bricks=target_wall_bricks,
                        target_floor_tile=target_floor_tile,
                        old_pixels=build_pixel_swarm(old_canvas, "out_right"),
                        new_pixels=build_pixel_swarm(new_canvas, "in_from_left"),
                        warrior_x=float(warrior_x),
                    )
                    deathfx_active = False
                    active_drop = None
                except (OSError, ValueError) as exc:
                    print(f"Warning: scene switch failed: {exc}", file=sys.stderr)

            if scene_transition is not None:
                st = scene_transition
                st.run_tick_accumulator, adv = kb_progression.advance_frame_timer(
                    st.run_tick_accumulator,
                    delta,
                    warrior_controller.timing.run_seconds_per_frame,
                )
                if adv > 0:
                    st.run_frame_index = (st.run_frame_index + adv) % len(warrior_animations["run"])
                warrior_tile = warrior_animations["run"][st.run_frame_index]

                center_x = float((cfg.WIDTH - cfg.TILE_SIZE) // 2)
                run_speed = cfg.WARRIOR_SHIFT_SPEED_PX_PER_SECOND * 2.5

                for px in st.old_pixels:
                    px.x += px.speed * delta

                if st.phase == "out":
                    st.warrior_x = min(center_x, st.warrior_x + run_speed * delta)
                    left_cleared = not any(0 <= px.x < (cfg.WIDTH * 0.2) for px in st.old_pixels)
                    if left_cleared and st.warrior_x >= center_x - 0.5:
                        st.phase = "in"
                else:
                    st.warrior_x = max(float(cfg.LEFT_SPRITE_X), st.warrior_x - run_speed * delta)
                    for px in st.new_pixels:
                        px.x = min(px.target_x, px.x + px.speed * delta)

                    all_new_in_place = all(px.x >= px.target_x - 0.01 for px in st.new_pixels)
                    warrior_back = st.warrior_x <= (cfg.LEFT_SPRITE_X + 0.5)
                    if all_new_in_place and warrior_back:
                        corridor_scene = st.target_scene_cfg
                        scene_static_sprites = st.target_static_sprites
                        scene_animated_sprites = st.target_animated_sprites
                        background_wall_brick_tiles = st.target_wall_bricks
                        background_floor_tile = st.target_floor_tile
                        active_scene_index = st.target_scene_index

                        warrior_x = float(cfg.LEFT_SPRITE_X)
                        warrior_target_x = pick_warrior_spawn_target_x(warrior_x)
                        mon_frames, mon_target_x, mon_max_hp = spawn_monster(
                            character_frames,
                            session.warrior_level,
                            int(round(warrior_target_x)),
                        )
                        monster = MonsterState(
                            frames=mon_frames,
                            target_x=mon_target_x,
                            max_hp=mon_max_hp,
                            hp=mon_max_hp,
                            level=session.warrior_level,
                            x=float(cfg.RIGHT_SPRITE_START_X),
                        )
                        scene_transition = None

                transition_canvas = [[0] * cfg.WIDTH for _ in range(cfg.HEIGHT)]
                for px in st.old_pixels:
                    sx = int(round(px.x))
                    if 0 <= sx < cfg.WIDTH and 0 <= px.y < cfg.HEIGHT:
                        transition_canvas[px.y][sx] = 1
                if st.phase == "in":
                    for px in st.new_pixels:
                        sx = int(round(px.x))
                        if 0 <= sx < cfg.WIDTH and 0 <= px.y < cfg.HEIGHT:
                            transition_canvas[px.y][sx] = 1

                kb_render.draw_tile_on_canvas(
                    transition_canvas,
                    warrior_tile,
                    int(round(st.warrior_x)),
                    cfg.HEIGHT - cfg.TILE_SIZE,
                )

                frame = kb_render.canvas_to_image_data(transition_canvas)
                background_anim_tick += 1
                send_frame_with_retry(gs, frame)
                maybe_update_tray_tooltip(keys)

                last_seen_space = spaces
                last_seen_other = others
                was_sliding = False

                remaining = update_interval - (time.monotonic() - loop_start)
                if remaining > 0:
                    time.sleep(remaining)
                continue

            is_sliding = monster.x > monster.target_x

            # Advance monster sprite frame
            monster.tick_accumulator, adv = kb_progression.advance_frame_timer(monster.tick_accumulator, delta, right_spf)
            if adv > 0:
                monster.frame_index = (monster.frame_index + adv) % cfg.FRAMES_PER_CHARACTER

            if is_sliding:
                background_scroll_x += cfg.BACKGROUND_SCROLL_PX_PER_SECOND * delta
                if warrior_x < warrior_target_x:
                    warrior_x = min(warrior_target_x, warrior_x + cfg.WARRIOR_SHIFT_SPEED_PX_PER_SECOND * delta)
                elif warrior_x > warrior_target_x:
                    warrior_x = max(warrior_target_x, warrior_x - cfg.WARRIOR_SHIFT_SPEED_PX_PER_SECOND * delta)

            warrior_controller.on_slide_state(was_sliding, is_sliding)

            maybe_save_stats(session, loop_start, keys)

            if current_input_time != last_input_time:
                last_input_time = current_input_time
                next_idle_refresh_at = current_input_time + cfg.MONSTER_REFRESH_AFTER_INACTIVITY_SECONDS

            inactivity = time.monotonic() - current_input_time
            show_hud    = inactivity < cfg.HUD_HIDE_AFTER_INACTIVITY_SECONDS

            if (not monster.refresh_active and not deathfx_active
                    and loop_start >= next_idle_refresh_at):
                monster.refresh_active = True
                next_idle_refresh_at = loop_start + cfg.MONSTER_REFRESH_AFTER_INACTIVITY_SECONDS

            new_spaces = max(0, spaces - last_seen_space)
            new_others = max(0, others - last_seen_other)

            warrior_controller.maybe_start_action(
                is_sliding, deathfx_active, monster.refresh_active,
                new_spaces, new_others, slashfx_frames,
            )
            warrior_tile, slashfx_tile, attack_finished = warrior_controller.advance(delta, is_sliding)

            if attack_finished:
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
                    now = time.monotonic()
                    drop_tile = random.choice(drop_tiles)
                    drop_x = monster.target_x + ((cfg.TILE_SIZE - cfg.DROP_TILE_SIZE) // 2)
                    # Put drop on the ground line (monster feet baseline).
                    drop_y = cfg.HEIGHT - cfg.DROP_TILE_SIZE
                    active_drop = DropState(
                        tile=drop_tile,
                        x=float(drop_x),
                        y=float(drop_y),
                        spawned_at=now,
                        expires_at=now + cfg.DROP_DISPLAY_SECONDS,
                    )

            if active_drop is not None:
                now = time.monotonic()
                if now >= active_drop.expires_at:
                    active_drop = None
                # Remove early only when someone actually reaches the drop position.
                elif (not deathfx_active) and monster.x <= active_drop.x:
                    active_drop = None
                elif warrior_x >= active_drop.x:
                    active_drop = None

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
                    warrior_target_x = pick_warrior_spawn_target_x(warrior_x)
                    mon_frames, mon_target_x, mon_max_hp = spawn_monster(
                        character_frames,
                        session.warrior_level,
                        int(round(warrior_target_x)),
                    )
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
                    warrior_target_x = pick_warrior_spawn_target_x(warrior_x)
                    mon_frames, mon_target_x, mon_max_hp = spawn_monster(
                        character_frames,
                        session.warrior_level,
                        int(round(warrior_target_x)),
                    )
                    monster = MonsterState(
                        frames=mon_frames, target_x=mon_target_x, max_hp=mon_max_hp, hp=mon_max_hp,
                        level=session.warrior_level, x=float(cfg.RIGHT_SPRITE_START_X),
                    )
            elif monster.x > monster.target_x:
                monster.x = max(monster.target_x, monster.x - cfg.RIGHT_SPRITE_SLIDE_PX_PER_SECOND * delta)

            show_health_bar = (
                monster.x <= monster.target_x and not deathfx_active and not monster.refresh_active
            )
            show_drop = False
            drop_tile = None
            drop_x = 0
            drop_y = 0
            if active_drop is not None:
                show_drop = (int((time.monotonic() - active_drop.spawned_at) / cfg.DROP_BLINK_SECONDS) % 2) == 0
                drop_tile = active_drop.tile
                drop_x = int(active_drop.x)
                drop_y = int(active_drop.y)

            frame = kb_render.compose_frame(kb_render.RenderState(
                scene_layers=corridor_scene.layers,
                scene_mode=corridor_scene.scene_mode,
                background_wall_brick_tiles=background_wall_brick_tiles,
                background_floor_tile=background_floor_tile,
                scene_static_sprites=scene_static_sprites,
                scene_animated_sprites=scene_animated_sprites,
                scene_placements=corridor_scene.placements,
                scene_sky_horizon=corridor_scene.sky_horizon,
                roof_eli_sprite_id=corridor_scene.roof_eli_sprite_id,
                background_scroll_x=background_scroll_x,
                background_anim_tick=background_anim_tick,
                corridor_floor_height=corridor_scene.floor_height,
                corridor_brick_start_offset_x=corridor_scene.brick_start_offset_x,
                corridor_brick_start_offset_y=corridor_scene.brick_start_offset_y,
                corridor_wall_underlay=corridor_scene.wall_underlay,
                right_sprite_tile=right_sprite_tile,
                right_sprite_x=int(monster.x),
                left_sprite_tile=warrior_tile,
                left_sprite_x=int(warrior_x),
                warrior_level=session.warrior_level,
                keypress_count=keys,
                right_sprite_value=monster.hp,
                right_sprite_max_value=monster.max_hp,
                show_health_bar=show_health_bar,
                show_hud=show_hud,
                slashfx_tile=slashfx_tile,
                drop_tile=drop_tile,
                drop_x=drop_x,
                drop_y=drop_y,
                show_drop=show_drop,
            ))
            background_anim_tick += 1
            send_frame_with_retry(gs, frame)

            maybe_update_tray_tooltip(keys)

            last_seen_space = spaces
            last_seen_other = others
            was_sliding = monster.x > monster.target_x

            remaining = update_interval - (time.monotonic() - loop_start)
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        request_stop("keyboard_interrupt")
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

        with stop_reason_lock:
            final_stop_reason = stop_reason
        final_keys, _, _, _ = input_stats.snapshot()
        top_place = None

        if final_stop_reason != "system_shutdown":
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

        cleanup_base_url = gs.base_url
        if cleanup_base_url is None and final_stop_reason == "system_shutdown":
            cleanup_base_url, _ = kb_gamesense.connect_gamesense_with_error()
        if cleanup_base_url:
            kb_gamesense.clear_and_stop(cleanup_base_url)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
