from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from pynput import keyboard, mouse


def _is_space_key(key) -> bool:
    return key == keyboard.Key.space or (isinstance(key, keyboard.KeyCode) and key.char == " ")


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
            return self.key_count, self.space_count, self.other_count, self.last_input_time


def start_ctrl_d_listener(stop_event: threading.Event, input_stats: InputStats):
    ctrl_pressed = False
    alt_pressed = False
    pressed_keys: set = set()
    pressed_buttons: set = set()

    def is_ctrl(key) -> bool:
        return key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r)

    def is_alt(key) -> bool:
        return key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr)

    def on_press(key):
        nonlocal ctrl_pressed, alt_pressed
        if is_ctrl(key): ctrl_pressed = True
        elif is_alt(key): alt_pressed = True
        if key == keyboard.Key.backspace and ctrl_pressed and alt_pressed:
            stop_event.set()
            return False
        if key not in pressed_keys:
            input_stats.mark_input_started()
            pressed_keys.add(key)

    def on_release(key):
        nonlocal ctrl_pressed, alt_pressed
        if key in pressed_keys:
            pressed_keys.discard(key)
            input_stats.record_release(_is_space_key(key))
        if is_ctrl(key): ctrl_pressed = False
        if is_alt(key): alt_pressed = False

    def on_click(x, y, button, pressed):
        del x, y
        if pressed:
            if button not in pressed_buttons:
                input_stats.mark_input_started()
                pressed_buttons.add(button)
        elif button in pressed_buttons:
            pressed_buttons.discard(button)
            input_stats.record_release(button == mouse.Button.right)

    kb_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    m_listener = mouse.Listener(on_click=on_click)
    kb_listener.start()
    m_listener.start()
    return kb_listener, m_listener
