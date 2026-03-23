from __future__ import annotations

import threading
import time
from typing import List

from pynput import keyboard, mouse


def _is_space_key(key: keyboard.Key | keyboard.KeyCode) -> bool:
    return (key == keyboard.Key.space) or (
        isinstance(key, keyboard.KeyCode) and key.char == " "
    )


def _record_input_release(
    key_counter: List[int],
    space_counter: List[int],
    other_counter: List[int],
    last_input_time: List[float],
    is_space: bool,
) -> None:
    last_input_time[0] = time.monotonic()
    key_counter[0] += 1
    if is_space:
        space_counter[0] += 1
    else:
        other_counter[0] += 1


def start_ctrl_d_listener(
    stop_event: threading.Event,
    key_counter: List[int],
    space_counter: List[int],
    other_counter: List[int],
    last_input_time: List[float],
    counter_lock: threading.Lock,
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
            with counter_lock:
                last_input_time[0] = time.monotonic()
        pressed_keys.add(key)

        return None

    def on_release(key: keyboard.Key | keyboard.KeyCode) -> None:
        nonlocal ctrl_pressed, alt_pressed

        if key in pressed_keys:
            pressed_keys.discard(key)
            with counter_lock:
                _record_input_release(
                    key_counter,
                    space_counter,
                    other_counter,
                    last_input_time,
                    _is_space_key(key),
                )

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
                with counter_lock:
                    last_input_time[0] = time.monotonic()
            pressed_mouse_buttons.add(button)
            return None

        if button in pressed_mouse_buttons:
            pressed_mouse_buttons.discard(button)
            with counter_lock:
                _record_input_release(
                    key_counter,
                    space_counter,
                    other_counter,
                    last_input_time,
                    button == mouse.Button.right,
                )

        return None

    keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    mouse_listener = mouse.Listener(on_click=on_click)

    keyboard_listener.start()
    mouse_listener.start()
    return keyboard_listener, mouse_listener
