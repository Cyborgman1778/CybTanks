from __future__ import annotations

import math
from dataclasses import dataclass

from .ai_config import AIProfile, AISettings
from .config import BULLET_RADIUS, TILE
from .geometry import angle_difference, clamp
from .models import Tank, Vec2


@dataclass(slots=True)
class SoundEvent:
    event_id: int
    position: Vec2
    kind: str
    source_team: str
    radius: float
    age: float = 0.0


@dataclass(frozen=True, slots=True)
class PerceptionSnapshot:
    target_position: Vec2 | None
    target_visible: bool
    has_line_of_sight: bool
    can_engage: bool
    heard_contact: bool
    remembered_contact: bool
    just_confirmed: bool


class PerceptionSystem:
    def __init__(self, world: object, settings: AISettings) -> None:
        self.world = world
        self.settings = settings
        self.events: list[SoundEvent] = []
        self._next_event_id = 1

    def reset(self) -> None:
        self.events.clear()
        self._next_event_id = 1

    def report_sound(self, position: Vec2, kind: str, source_team: str) -> None:
        radius_tiles = self.settings.global_config.sound_ranges_tiles.get(kind)
        if radius_tiles is None:
            return
        self.events.append(
            SoundEvent(
                event_id=self._next_event_id,
                position=position.copy(),
                kind=kind,
                source_team=source_team,
                radius=radius_tiles * TILE,
            )
        )
        self._next_event_id += 1
        del self.events[: -self.settings.global_config.max_sound_events]

    def begin_frame(self, dt: float) -> None:
        for event in self.events:
            event.age += dt
        lifetime = self.settings.global_config.sound_event_lifetime
        self.events = [event for event in self.events if event.age <= lifetime]

    def update(
        self,
        enemy: Tank,
        player: Tank,
        profile: AIProfile,
        dt: float,
    ) -> PerceptionSnapshot:
        memory = enemy.ai
        memory.reaction_remaining = max(0.0, memory.reaction_remaining - dt)
        if not memory.target_visible:
            memory.memory_remaining = max(0.0, memory.memory_remaining - dt)
        memory.hearing_remaining = max(0.0, memory.hearing_remaining - dt)
        memory.sensor_timer -= dt
        memory.sensor_elapsed += dt
        omniscient = self.settings.global_config.omniscient_player_tracking
        if omniscient and player.alive:
            memory.last_known_position = player.position.copy()
            memory.memory_remaining = profile.memory_duration

        distance_tiles = enemy.position.distance_to(player.position) / TILE
        memory.lod_factor = self._lod_factor(distance_tiles)
        just_confirmed = False
        if memory.sensor_timer <= 0.0:
            interval = self._sensor_interval(profile, memory.lod_factor)
            sample_elapsed = max(0.0, memory.sensor_elapsed)
            memory.sensor_timer = interval
            memory.sensor_elapsed = 0.0
            just_confirmed = self._sample_vision(
                enemy,
                player,
                profile,
                sample_elapsed,
            )
            self._sample_hearing(enemy, player, profile)
            if omniscient and player.alive:
                memory.last_known_position = player.position.copy()
                memory.memory_remaining = profile.memory_duration

        heard_contact = memory.hearing_remaining > 0.0 and memory.last_heard_position is not None
        remembered_contact = memory.memory_remaining > 0.0 and memory.last_known_position is not None
        if omniscient and player.alive:
            target_position = player.position.copy()
            remembered_contact = True
        elif memory.target_visible:
            target_position = player.position.copy()
        elif heard_contact or remembered_contact:
            target_position = (
                memory.last_known_position.copy()
                if memory.last_known_position is not None
                else None
            )
        else:
            target_position = None
            memory.last_known_position = None

        return PerceptionSnapshot(
            target_position=target_position,
            target_visible=memory.target_visible,
            has_line_of_sight=memory.has_line_of_sight,
            can_engage=(memory.target_visible or omniscient)
            and player.alive
            and memory.reaction_remaining <= 0.0,
            heard_contact=heard_contact,
            remembered_contact=remembered_contact,
            just_confirmed=just_confirmed,
        )

    def _sample_vision(
        self,
        enemy: Tank,
        player: Tank,
        profile: AIProfile,
        sample_elapsed: float,
    ) -> bool:
        memory = enemy.ai
        difference = player.position - enemy.position
        distance = difference.length()
        target_angle = math.atan2(difference.y, difference.x) if distance > 0 else enemy.turret_angle
        half_fov = math.radians(profile.vision_fov_degrees) * 0.5
        if memory.target_visible:
            half_fov = min(math.pi, half_fov * 1.3)
        in_view = (
            player.alive
            and distance <= profile.vision_range_tiles * TILE
            and abs(angle_difference(target_angle, enemy.turret_angle)) <= half_fov
        )
        memory.has_line_of_sight = bool(
            in_view
            and self.world.clear_segment(
                enemy.position,
                player.position,
                BULLET_RADIUS,
            )
        )
        was_confirmed = memory.target_visible
        if memory.has_line_of_sight:
            distance_factor = 1.0 - clamp(
                distance / (profile.vision_range_tiles * TILE),
                0.0,
                1.0,
            )
            movement_bonus = 1.15 if player.velocity.length_squared() > 25.0 else 1.0
            gain = (
                sample_elapsed
                / profile.detection_time
                * (0.55 + distance_factor * 0.45)
                * movement_bonus
            )
            memory.awareness = min(1.0, memory.awareness + gain)
            if memory.awareness >= 1.0:
                memory.target_visible = True
                memory.last_seen_position = player.position.copy()
                memory.last_known_position = player.position.copy()
                memory.memory_remaining = profile.memory_duration
                if not was_confirmed:
                    memory.reaction_remaining = profile.reaction_time
                    memory.decision_timer = 0.0
        else:
            memory.target_visible = False
            memory.awareness = max(
                0.0,
                memory.awareness - sample_elapsed / profile.detection_decay_time,
            )
        return memory.target_visible and not was_confirmed

    def _sample_hearing(self, enemy: Tank, player: Tank, profile: AIProfile) -> None:
        if enemy.ai.target_visible:
            enemy.ai.last_sound_event_id = max(
                (
                    event.event_id
                    for event in self.events
                    if event.source_team != enemy.team or event.kind == "tank_destroyed"
                ),
                default=enemy.ai.last_sound_event_id,
            )
            return
        best_score = 0.0
        best_position: Vec2 | None = None
        best_event_id = enemy.ai.last_sound_event_id
        hearing_limit = profile.hearing_range_tiles * TILE
        global_config = self.settings.global_config

        for event in self.events:
            if event.event_id <= enemy.ai.last_sound_event_id or (
                event.source_team == enemy.team and event.kind != "tank_destroyed"
            ):
                continue
            radius = min(event.radius, hearing_limit)
            score = self._audibility(enemy.position, event.position, radius)
            if score <= best_score:
                continue
            best_score = score
            best_position = event.position
            best_event_id = event.event_id

        if player.alive and player.velocity.length_squared() > 100.0:
            engine_radius = min(
                hearing_limit,
                global_config.player_engine_sound_tiles * TILE,
            )
            engine_score = self._audibility(enemy.position, player.position, engine_radius)
            if engine_score > best_score:
                best_score = engine_score
                best_position = player.position

        if best_position is None or best_score <= 0.0:
            return
        memory = enemy.ai
        memory.last_sound_event_id = best_event_id
        memory.last_heard_position = best_position.copy()
        memory.last_known_position = best_position.copy()
        memory.hearing_remaining = profile.hearing_memory_duration
        memory.memory_remaining = max(memory.memory_remaining, profile.hearing_memory_duration)
        memory.awareness = max(memory.awareness, min(0.82, 0.25 + best_score * 0.57))
        memory.decision_timer = 0.0

    def _audibility(self, listener: Vec2, source: Vec2, radius: float) -> float:
        distance = listener.distance_to(source)
        if radius <= 0.0 or distance > radius:
            return 0.0
        config = self.settings.global_config
        attenuation = self.world.sound_attenuation(
            listener,
            source,
            config.solid_wall_sound_attenuation,
            config.breakable_wall_sound_attenuation,
        )
        return max(0.0, 1.0 - distance / radius) * attenuation

    def _lod_factor(self, distance_tiles: float) -> float:
        config = self.settings.global_config
        return clamp(
            (distance_tiles - config.near_lod_distance_tiles)
            / (config.far_lod_distance_tiles - config.near_lod_distance_tiles),
            0.0,
            1.0,
        )

    @staticmethod
    def _sensor_interval(profile: AIProfile, lod_factor: float) -> float:
        return profile.sensor_interval_near + (
            profile.sensor_interval_far - profile.sensor_interval_near
        ) * lod_factor
