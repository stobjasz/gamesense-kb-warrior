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

    def on_slide_state(self, was_sliding: bool, is_sliding: bool) -> None:
        if (
            was_sliding
            and (not is_sliding)
            and (self.state == "idle")
            and (self.run_post_slide_remaining == 0)
            and (self.run_frame_index != 0)
        ):
            self.run_post_slide_remaining = (
                len(self.animations.run) - self.run_frame_index
            )

    def maybe_start_action(
        self,
        is_sliding: bool,
        deathfx_active: bool,
        monster_refresh_active: bool,
        new_space_presses: int,
        new_other_presses: int,
        slashfx_frames: List[List[List[int]]],
    ) -> None:
        if (
            is_sliding
            or deathfx_active
            or monster_refresh_active
            or self.state != "idle"
            or self.run_post_slide_remaining != 0
        ):
            return

        if new_space_presses > 0:
            self.state = "block"
            self.state_frame_index = 0
            self.state_tick_accumulator = 0.0
            return

        if new_other_presses > 0:
            self.state = "attack"
            self.state_frame_index = 0
            self.state_tick_accumulator = 0.0
            self.active_slashfx_frames = slashfx_frames

    def advance(
        self,
        delta_seconds: float,
        is_sliding: bool,
    ) -> tuple[List[List[int]], List[List[int]] | None, bool]:
        idle_warrior_frames = self.animations.idle
        run_warrior_frames = self.animations.run
        block_warrior_frames = self.animations.block
        attack_warrior_frames = self.animations.attack

        current_slashfx_tile: List[List[int]] | None = None
        attack_finished = False

        if self.state == "attack":
            if self.active_slashfx_frames is not None and attack_warrior_frames:
                attack_len = len(attack_warrior_frames)
                slash_len = len(self.active_slashfx_frames)
                if slash_len > 0:
                    slash_frame_idx = min(
                        slash_len - 1,
                        int(self.state_frame_index * slash_len / attack_len),
                    )
                    current_slashfx_tile = self.active_slashfx_frames[slash_frame_idx]

            warrior_tile = attack_warrior_frames[self.state_frame_index]
            self.state_tick_accumulator, attack_advances = kb_progression.advance_frame_timer(
                self.state_tick_accumulator,
                delta_seconds,
                self.timing.attack_seconds_per_frame,
            )
            if attack_advances > 0:
                self.state_frame_index += attack_advances

            if self.state_frame_index >= len(attack_warrior_frames):
                self.state = "idle"
                self.state_frame_index = 0
                self.state_tick_accumulator = 0.0
                self.active_slashfx_frames = None
                attack_finished = True

            return warrior_tile, current_slashfx_tile, attack_finished

        if self.state == "block":
            warrior_tile = block_warrior_frames[self.state_frame_index]
            self.state_tick_accumulator, block_advances = kb_progression.advance_frame_timer(
                self.state_tick_accumulator,
                delta_seconds,
                self.timing.block_seconds_per_frame,
            )
            if block_advances > 0:
                self.state_frame_index += block_advances
            if self.state_frame_index >= len(block_warrior_frames):
                self.state = "idle"
                self.state_frame_index = 0
                self.state_tick_accumulator = 0.0
            return warrior_tile, None, False

        if is_sliding or self.run_post_slide_remaining > 0:
            warrior_tile = run_warrior_frames[self.run_frame_index]
            self.run_tick_accumulator, run_advances = kb_progression.advance_frame_timer(
                self.run_tick_accumulator,
                delta_seconds,
                self.timing.run_seconds_per_frame,
            )
            if run_advances > 0:
                self.run_frame_index = (self.run_frame_index + run_advances) % len(
                    run_warrior_frames
                )
            if (not is_sliding) and self.run_post_slide_remaining > 0 and run_advances > 0:
                self.run_post_slide_remaining = max(
                    0,
                    self.run_post_slide_remaining - run_advances,
                )
            return warrior_tile, None, False

        warrior_tile = idle_warrior_frames[self.idle_frame_index]
        self.idle_tick_accumulator, idle_advances = kb_progression.advance_frame_timer(
            self.idle_tick_accumulator,
            delta_seconds,
            self.timing.idle_seconds_per_frame,
        )
        if idle_advances > 0:
            self.idle_frame_index = (self.idle_frame_index + idle_advances) % len(
                idle_warrior_frames
            )
        self.run_frame_index = 0
        self.run_tick_accumulator = 0.0
        return warrior_tile, None, False
