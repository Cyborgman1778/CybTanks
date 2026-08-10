from __future__ import annotations

import math
import random
from array import array
from collections.abc import Callable

import pygame


class AudioSystem:
    def __init__(self) -> None:
        self.mine_beep: pygame.mixer.Sound | None = None
        self.slow_shot: pygame.mixer.Sound | None = None
        self.fast_shot: pygame.mixer.Sound | None = None
        self.bullet_bounce: pygame.mixer.Sound | None = None
        self.bullet_disintegrate: pygame.mixer.Sound | None = None
        self.mine_place: pygame.mixer.Sound | None = None
        self.explosion: pygame.mixer.Sound | None = None
        self.tank_destroyed: pygame.mixer.Sound | None = None
        if pygame.mixer.get_init() is None:
            return
        try:
            self.mine_beep = self._build_beep()
            self.slow_shot = self._build_slow_shot()
            self.fast_shot = self._build_fast_shot()
            self.bullet_bounce = self._build_bullet_bounce()
            self.bullet_disintegrate = self._build_bullet_disintegrate()
            self.mine_place = self._build_mine_place()
            self.explosion = self._build_explosion()
            self.tank_destroyed = self._build_tank_destroyed()
            self.mine_beep.set_volume(0.22)
            self.slow_shot.set_volume(0.34)
            self.fast_shot.set_volume(0.28)
            self.bullet_bounce.set_volume(0.25)
            self.bullet_disintegrate.set_volume(0.27)
            self.mine_place.set_volume(0.3)
            self.explosion.set_volume(0.46)
            self.tank_destroyed.set_volume(0.4)
        except pygame.error:
            self.mine_beep = None
            self.slow_shot = None
            self.fast_shot = None
            self.bullet_bounce = None
            self.bullet_disintegrate = None
            self.mine_place = None
            self.explosion = None
            self.tank_destroyed = None

    @staticmethod
    def _build_sound(
        duration: float,
        waveform: Callable[[int, float, float], float],
    ) -> pygame.mixer.Sound:
        sample_rate = 22_050
        sample_count = int(sample_rate * duration)
        samples = array("h")
        for index in range(sample_count):
            time = index / sample_rate
            progress = index / max(1, sample_count - 1)
            value = round(waveform(index, time, progress))
            samples.append(max(-32_767, min(32_767, value)))
        return pygame.mixer.Sound(buffer=samples)

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

    @classmethod
    def _build_slow_shot(cls) -> pygame.mixer.Sound:
        noise = random.Random(2_117)

        def waveform(_index: int, time: float, progress: float) -> float:
            attack = min(1.0, time / 0.003)
            envelope = attack * (1.0 - progress) ** 2.1
            tone = math.sin(math.tau * (235 - 70 * progress) * time)
            crack = noise.uniform(-1.0, 1.0)
            return (tone * 0.72 + crack * 0.28) * 17_000 * envelope

        return cls._build_sound(0.13, waveform)

    @classmethod
    def _build_fast_shot(cls) -> pygame.mixer.Sound:
        noise = random.Random(7_031)

        def waveform(_index: int, time: float, progress: float) -> float:
            attack = min(1.0, time / 0.0015)
            envelope = attack * (1.0 - progress) ** 1.7
            phase = math.tau * (1_350 * time - 4_200 * time**2)
            tone = math.sin(phase) * 0.78 + math.sin(phase * 2.03) * 0.14
            return (tone + noise.uniform(-0.08, 0.08)) * 13_500 * envelope

        return cls._build_sound(0.085, waveform)

    @classmethod
    def _build_bullet_bounce(cls) -> pygame.mixer.Sound:
        def waveform(_index: int, time: float, progress: float) -> float:
            attack = min(1.0, time / 0.0015)
            envelope = attack * (1.0 - progress) ** 2.8
            phase = math.tau * (1_050 * time - 1_100 * time**2)
            metallic = math.sin(phase) + math.sin(phase * 2.37) * 0.42
            return metallic * 11_500 * envelope

        return cls._build_sound(0.095, waveform)

    @classmethod
    def _build_bullet_disintegrate(cls) -> pygame.mixer.Sound:
        noise = random.Random(6_283)

        def waveform(_index: int, time: float, progress: float) -> float:
            attack = min(1.0, time / 0.002)
            envelope = attack * (1.0 - progress) ** 1.8
            phase = math.tau * (1_600 * time - 3_400 * time**2)
            fragments = math.sin(phase) * 0.46 + noise.uniform(-1.0, 1.0) * 0.54
            return fragments * 11_000 * envelope

        return cls._build_sound(0.15, waveform)

    @classmethod
    def _build_mine_place(cls) -> pygame.mixer.Sound:
        noise = random.Random(4_409)

        def waveform(_index: int, time: float, _progress: float) -> float:
            first = math.exp(-time * 44)
            second_time = max(0.0, time - 0.052)
            second = math.exp(-second_time * 65) if time >= 0.052 else 0.0
            clunk = math.sin(math.tau * 175 * time) * first
            latch = math.sin(math.tau * 720 * second_time) * second
            grit = noise.uniform(-1.0, 1.0) * (first + second) * 0.18
            return (clunk * 0.75 + latch * 0.55 + grit) * 10_500

        return cls._build_sound(0.12, waveform)

    @classmethod
    def _build_explosion(cls) -> pygame.mixer.Sound:
        noise = random.Random(9_917)
        filtered_noise = 0.0

        def waveform(_index: int, time: float, progress: float) -> float:
            nonlocal filtered_noise
            raw_noise = noise.uniform(-1.0, 1.0)
            filtered_noise = filtered_noise * 0.78 + raw_noise * 0.22
            attack = min(1.0, time / 0.005)
            envelope = attack * (1.0 - progress) ** 1.65
            rumble = math.sin(math.tau * (64 - 18 * progress) * time)
            crack = raw_noise * math.exp(-time * 19)
            blast = rumble * 0.68 + filtered_noise * 0.75 + crack * 0.42
            return blast * 21_000 * envelope

        return cls._build_sound(0.48, waveform)

    @classmethod
    def _build_tank_destroyed(cls) -> pygame.mixer.Sound:
        noise = random.Random(5_723)

        def waveform(_index: int, time: float, progress: float) -> float:
            attack = min(1.0, time / 0.002)
            envelope = attack * (1.0 - progress) ** 1.45
            impact = math.sin(math.tau * 125 * time) * math.exp(-time * 13)
            metal = (
                math.sin(math.tau * 610 * time) * 0.5
                + math.sin(math.tau * 1_080 * time) * 0.27
            ) * math.exp(-time * 7.5)
            debris = noise.uniform(-1.0, 1.0) * math.exp(-time * 10)
            return (impact * 0.7 + metal + debris * 0.42) * 17_500 * envelope

        return cls._build_sound(0.34, waveform)

    def play_mine_beep(self) -> None:
        if self.mine_beep is not None:
            self.mine_beep.play()

    def play_shot(self, speed_class: str) -> None:
        sound = self.fast_shot if speed_class == "fast" else self.slow_shot
        if sound is not None:
            sound.play()

    def play_bullet_bounce(self) -> None:
        if self.bullet_bounce is not None:
            self.bullet_bounce.play()

    def play_bullet_disintegrate(self) -> None:
        if self.bullet_disintegrate is not None:
            self.bullet_disintegrate.play()

    def play_mine_place(self) -> None:
        if self.mine_place is not None:
            self.mine_place.play()

    def play_explosion(self) -> None:
        if self.explosion is not None:
            self.explosion.play()

    def play_tank_destroyed(self) -> None:
        if self.tank_destroyed is not None:
            self.tank_destroyed.play()
