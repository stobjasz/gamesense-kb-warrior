from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from pynput import keyboard, mouse


def _is_space_key(key: keyboard.Key | keyboard.KeyCode) -> bool:
    return (key == keyboard.Key.space) or (
        isinstance(key, keyboard.KeyCode) and key.char == " "
    )


@dataclass
class InputStats:
    key_count: int = 0
    space_count: int = 0
    other_count: int = 0
    last_input_time: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def mark_input_started(self) -> None:
        with self.lock:
            self.last_input_time = time.monotonic()

    def record_release(self, is_space: bool) -> None:
        with self.lock:
            self.last_input_time = time.monotonic()
            self.key_count += 1
            if is_space:
                self.space_count += 1
            else:
                self.other_count += 1

    def snapshot(self) -> tuple[int, int, int, float]:
        with self.lock:
            return (
                self.key_count,
                self.space_count,
                self.other_count,
                self.last_input_time,
            )


def start_ctrl_d_listener(
    stop_event: threading.Event,
    input_stats: InputStats,
) -> tuple[keyboard.Listener, mouse.Listener]:
    ctrl_pressed = False
    alt_pressed = False
    pressed_keys: set[keyboard.Key | keyboard.KeyCode] = set()
    pressed_mouse_buttons: set[mouse.Button] = set()

    def is_ctrl_key(key: keyboard.Key | keyboard.KeyCode) -> bool:
        return key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r)

    def is_alt_key(key: keyboard.Key | keyboard.KeyCode) -> bool:
        return key in (
            keyboard.Key.alt,
            keyboard.Key.alt_l,
            keyboard.Key.alt_r,
            keyboard.Key.alt_gr,
        )

    def on_press(key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        nonlocal ctrl_pressed, alt_pressed

        if is_ctrl_key(key):
            ctrl_pressed = True
        elif is_alt_key(key):
            alt_pressed = True

        if key == keyboard.Key.backspace and ctrl_pressed and alt_pressed:
            stop_event.set()
            return False

        # Start tracking a keypress cycle on first key-down only (ignores repeats while held).
        if key not in pressed_keys:
            input_stats.mark_input_started()
        pressed_keys.add(key)

        return None

    def on_release(key: keyboard.Key | keyboard.KeyCode) -> None:
        nonlocal ctrl_pressed, alt_pressed

        if key in pressed_keys:
            pressed_keys.discard(key)
            input_stats.record_release(_is_space_key(key))

        if is_ctrl_key(key):
            ctrl_pressed = False
        if is_alt_key(key):
            alt_pressed = False

    def on_click(
        x: int, y: int, button: mouse.Button, pressed: bool
    ) -> bool | None:
        del x, y

        if pressed:
            if button not in pressed_mouse_buttons:
                input_stats.mark_input_started()
            pressed_mouse_buttons.add(button)
            return None

        if button in pressed_mouse_buttons:
            pressed_mouse_buttons.discard(button)
            input_stats.record_release(button == mouse.Button.right)

        return None

    keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    mouse_listener = mouse.Listener(on_click=on_click)

    keyboard_listener.start()
    mouse_listener.start()
    return keyboard_listener, mouse_listener
