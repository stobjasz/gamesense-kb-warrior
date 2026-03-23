from __future__ import annotations
from dataclasses import dataclass
from typing import List
import kb_progression


@dataclass(frozen=True)
class WarriorAnimations:
    idle: List[List[List[int]]]
    run: List[List[List[int]]]
    block: List[List[List[int]]]
    attack: List[List[List[int]]]


@dataclass(frozen=True)
class WarriorTiming:
    idle_seconds_per_frame: float
    run_seconds_per_frame: float
    block_seconds_per_frame: float
    attack_seconds_per_frame: float


class WarriorStateController:
    """Encapsulates warrior animation state and transitions."""

    def __init__(self, animations: WarriorAnimations, timing: WarriorTiming) -> None:
        self.animations = animations
        self.timing = timing
        self.state = "idle"
        self.state_frame_index = 0
        self.state_tick_accumulator = 0.0
        self.idle_frame_index = 0
        self.idle_tick_accumulator = 0.0
        self.run_frame_index = 0
        self.run_tick_accumulator = 0.0
        self.run_post_slide_remaining = 0
        self.active_slashfx_frames: List[List[List[int]]] | None = None

    def _return_to_idle(self) -> None:
        self.state = "idle"
        self.state_frame_index = 0
        self.state_tick_accumulator = 0.0
        self.active_slashfx_frames = None

    def on_slide_state(self, was_sliding: bool, is_sliding: bool) -> None:
        if (was_sliding and not is_sliding and self.state == "idle"
                and self.run_post_slide_remaining == 0 and self.run_frame_index != 0):
            self.run_post_slide_remaining = len(self.animations.run) - self.run_frame_index

    def maybe_start_action(self, is_sliding: bool, deathfx_active: bool, monster_refresh_active: bool,
                           new_space_presses: int, new_other_presses: int, slashfx_frames: List) -> None:
        if is_sliding or deathfx_active or monster_refresh_active or self.state != "idle" or self.run_post_slide_remaining != 0:
            return
        if new_space_presses > 0:
            self.state = "block"
            self.state_frame_index = 0
            self.state_tick_accumulator = 0.0
        elif new_other_presses > 0:
            self.state = "attack"
            self.state_frame_index = 0
            self.state_tick_accumulator = 0.0
            self.active_slashfx_frames = slashfx_frames

    def advance(self, delta_seconds: float, is_sliding: bool) -> tuple[List[List[int]], List[List[int]] | None, bool]:
        anim = self.animations
        timing = self.timing
        current_slashfx_tile = None
        attack_finished = False

        if self.state == "attack":
            frames = anim.attack
            if self.active_slashfx_frames and frames:
                sl = len(self.active_slashfx_frames)
                idx = min(sl - 1, int(self.state_frame_index * sl / len(frames)))
                current_slashfx_tile = self.active_slashfx_frames[idx]
            warrior_tile = frames[self.state_frame_index]
            self.state_tick_accumulator, adv = kb_progression.advance_frame_timer(
                self.state_tick_accumulator, delta_seconds, timing.attack_seconds_per_frame)
            if adv > 0:
                self.state_frame_index += adv
            if self.state_frame_index >= len(frames):
                self._return_to_idle()
                attack_finished = True
            return warrior_tile, current_slashfx_tile, attack_finished

        if self.state == "block":
            frames = anim.block
            warrior_tile = frames[self.state_frame_index]
            self.state_tick_accumulator, adv = kb_progression.advance_frame_timer(
                self.state_tick_accumulator, delta_seconds, timing.block_seconds_per_frame)
            if adv > 0:
                self.state_frame_index += adv
            if self.state_frame_index >= len(frames):
                self._return_to_idle()
            return warrior_tile, None, False

        if is_sliding or self.run_post_slide_remaining > 0:
            warrior_tile = anim.run[self.run_frame_index]
            self.run_tick_accumulator, adv = kb_progression.advance_frame_timer(
                self.run_tick_accumulator, delta_seconds, timing.run_seconds_per_frame)
            if adv > 0:
                self.run_frame_index = (self.run_frame_index + adv) % len(anim.run)
                if not is_sliding and self.run_post_slide_remaining > 0:
                    self.run_post_slide_remaining = max(0, self.run_post_slide_remaining - adv)
            return warrior_tile, None, False

        warrior_tile = anim.idle[self.idle_frame_index]
        self.idle_tick_accumulator, adv = kb_progression.advance_frame_timer(
            self.idle_tick_accumulator, delta_seconds, timing.idle_seconds_per_frame)
        if adv > 0:
            self.idle_frame_index = (self.idle_frame_index + adv) % len(anim.idle)
            self.run_frame_index = 0
            self.run_tick_accumulator = 0.0
        return warrior_tile, None, False
