from __future__ import annotations

import math
from array import array

import pygame


class AudioSystem:
    def __init__(self) -> None:
        self.mine_beep: pygame.mixer.Sound | None = None
        if pygame.mixer.get_init() is None:
            return
        try:
            self.mine_beep = self._build_beep()
            self.mine_beep.set_volume(0.22)
        except pygame.error:
            self.mine_beep = None

    @staticmethod
    def _build_beep() -> pygame.mixer.Sound:
        sample_rate = 22_050
        duration = 0.055
        sample_count = int(sample_rate * duration)
        samples = array("h")
        for index in range(sample_count):
            time = index / sample_rate
            fade_in = min(1.0, index / (sample_rate * 0.004))
            fade_out = min(1.0, (sample_count - index) / (sample_rate * 0.012))
            envelope = min(fade_in, fade_out)
            samples.append(int(math.sin(math.tau * 1_050 * time) * 9_000 * envelope))
        return pygame.mixer.Sound(buffer=samples)

    def play_mine_beep(self) -> None:
        if self.mine_beep is not None:
            self.mine_beep.play()
