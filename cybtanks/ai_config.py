from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields, replace
from functools import lru_cache
from typing import Any

from .config import AI_DATA_FILE


@dataclass(frozen=True, slots=True)
class AIProfile:
    vision_range_tiles: float
    vision_fov_degrees: float
    detection_time: float
    detection_decay_time: float
    memory_duration: float
    hearing_range_tiles: float
    hearing_memory_duration: float
    reaction_time: float
    sensor_interval_near: float
    sensor_interval_far: float
    decision_interval_near: float
    decision_interval_far: float
    aggression: float
    cover_preference: float
    flank_preference: float
    retreat_threshold: float
    preferred_distance_tiles: float
    min_distance_tiles: int
    max_distance_tiles: int
    navigation_search_radius_tiles: int
    navigation_interval_min: float
    navigation_interval_max: float
    aim_interval: float
    aim_tolerance_degrees: float
    body_turn_speed: float
    turret_turn_speed: float
    local_stuck_timeout: float
    net_stuck_timeout: float
    mine_interval_min: float
    mine_interval_max: float
    preferred_role: str
    max_ricochet_candidates: int
    ricochet_error_min_degrees: float
    ricochet_error_max_degrees: float
    ricochet_error_attempts: int
    crowd_wait_time: float
    dodge_prediction_time: float
    dodge_margin_px: float
    dodge_commit_time: float
    dodge_cooldown: float
    dodge_speed_multiplier: float
    dodge_direction_commitment: float
    predictive_aim_enabled: bool
    prediction_horizon: float
    prediction_step: float
    prediction_min_target_speed: float
    prediction_iterations: int
    prediction_max_ricochet_surfaces: int
    scan_speed: float
    scan_arc_degrees: float
    unpredictability: float


@dataclass(frozen=True, slots=True)
class InitialFireTiming:
    base: float
    stagger: float
    cycle: int = 0

    def delay(self, index: int) -> float:
        stagger_index = index % self.cycle if self.cycle > 0 else index
        return self.base + stagger_index * self.stagger


@dataclass(frozen=True, slots=True)
class GlobalAIConfig:
    max_path_plans_per_frame: int
    max_shot_plans_per_frame: int
    max_predictive_shot_plans_per_frame: int
    max_attackers: int
    attack_slot_duration: float
    communication_range_tiles: float
    alert_awareness: float
    alert_cooldown: float
    sound_event_lifetime: float
    max_sound_events: int
    omniscient_player_tracking: bool
    near_lod_distance_tiles: float
    far_lod_distance_tiles: float
    threat_horizon: float
    threat_radius_tiles: float
    cover_search_radius_tiles: int
    flank_lateral_tiles: float
    search_duration: float
    state_hysteresis: float
    guard_patrol_radius_tiles: int
    direct_aim_offsets_px: tuple[float, ...]
    dodge_candidate_angles_degrees: tuple[float, ...]
    route_occupied_penalty: float
    route_ally_path_penalty: float
    route_reserved_goal_penalty: float
    route_recent_penalty: float
    route_avoid_penalty: float
    route_noise: float
    mine_danger_penalty: float
    player_engine_sound_tiles: float
    solid_wall_sound_attenuation: float
    breakable_wall_sound_attenuation: float
    friendly_fire_horizon: float
    initial_mine_delay: float
    initial_mine_stagger: float
    mine_retry_interval: float
    max_enemy_bullets: int
    max_enemy_mines: int
    max_enemy_bounces: int
    sound_ranges_tiles: dict[str, float]
    initial_fire_default: InitialFireTiming
    initial_fire_overrides: dict[str, InitialFireTiming]


@dataclass(frozen=True, slots=True)
class AISettings:
    profiles: dict[str, AIProfile]
    archetype_overrides: dict[str, dict[str, Any]]
    global_config: GlobalAIConfig

    def profile_for(self, kind: str, intelligence: str) -> AIProfile:
        try:
            profile = self.profiles[intelligence]
        except KeyError as error:
            raise ValueError(f"Unknown AI profile {intelligence!r} for {kind!r}") from error
        override = self.archetype_overrides.get(kind)
        return replace(profile, **override) if override else profile

    def initial_fire_delay(self, kind: str, index: int) -> float:
        timing = self.global_config.initial_fire_overrides.get(
            kind,
            self.global_config.initial_fire_default,
        )
        return timing.delay(index)


def _strict_fields(data: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown fields in {label}: {sorted(unknown)}")


def _profile_from_data(profile_id: str, data: dict[str, Any]) -> AIProfile:
    names = {field.name for field in fields(AIProfile)}
    _strict_fields(data, names, f"AI profile {profile_id!r}")
    missing = names - set(data)
    if missing:
        raise ValueError(f"Missing fields in AI profile {profile_id!r}: {sorted(missing)}")
    profile = AIProfile(**data)
    _validate_profile(profile_id, profile)
    return profile


def _validate_profile(profile_id: str, profile: AIProfile) -> None:
    if not 0 < profile.vision_fov_degrees <= 360:
        raise ValueError(f"Invalid field of view in AI profile {profile_id!r}")
    if profile.vision_range_tiles <= 0 or profile.hearing_range_tiles <= 0:
        raise ValueError(f"Invalid perception range in AI profile {profile_id!r}")
    positive_values = (
        profile.detection_time,
        profile.detection_decay_time,
        profile.memory_duration,
        profile.hearing_memory_duration,
        profile.sensor_interval_near,
        profile.sensor_interval_far,
        profile.decision_interval_near,
        profile.decision_interval_far,
        profile.navigation_interval_min,
        profile.navigation_interval_max,
        profile.aim_interval,
        profile.aim_tolerance_degrees,
        profile.body_turn_speed,
        profile.turret_turn_speed,
        profile.local_stuck_timeout,
        profile.net_stuck_timeout,
        profile.mine_interval_min,
        profile.mine_interval_max,
        profile.ricochet_error_min_degrees,
        profile.ricochet_error_max_degrees,
        profile.crowd_wait_time,
        profile.dodge_prediction_time,
        profile.dodge_margin_px,
        profile.dodge_commit_time,
        profile.dodge_cooldown,
        profile.dodge_speed_multiplier,
        profile.prediction_step,
        profile.scan_speed,
        profile.scan_arc_degrees,
    )
    if any(value <= 0 for value in positive_values) or profile.reaction_time < 0:
        raise ValueError(f"Non-positive timing or speed in AI profile {profile_id!r}")
    unit_values = (
        profile.aggression,
        profile.cover_preference,
        profile.flank_preference,
        profile.retreat_threshold,
        profile.unpredictability,
        profile.dodge_direction_commitment,
    )
    if any(not 0 <= value <= 1 for value in unit_values):
        raise ValueError(f"Utility weight outside [0, 1] in AI profile {profile_id!r}")
    if not 0 <= profile.min_distance_tiles <= profile.preferred_distance_tiles <= profile.max_distance_tiles:
        raise ValueError(f"Invalid engagement distances in AI profile {profile_id!r}")
    if profile.navigation_search_radius_tiles < profile.max_distance_tiles:
        raise ValueError(f"Navigation radius is too small in AI profile {profile_id!r}")
    if profile.navigation_interval_min > profile.navigation_interval_max:
        raise ValueError(f"Invalid navigation interval in AI profile {profile_id!r}")
    if profile.sensor_interval_near > profile.sensor_interval_far:
        raise ValueError(f"Invalid sensor LOD interval in AI profile {profile_id!r}")
    if profile.decision_interval_near > profile.decision_interval_far:
        raise ValueError(f"Invalid decision LOD interval in AI profile {profile_id!r}")
    if profile.mine_interval_min > profile.mine_interval_max:
        raise ValueError(f"Invalid mine interval in AI profile {profile_id!r}")
    if profile.preferred_role not in {"assault", "support", "flanker"}:
        raise ValueError(f"Invalid squad role in AI profile {profile_id!r}")
    if profile.max_ricochet_candidates < 0:
        raise ValueError(f"Invalid ricochet budget in AI profile {profile_id!r}")
    if (
        profile.ricochet_error_min_degrees > profile.ricochet_error_max_degrees
        or profile.ricochet_error_attempts < 0
    ):
        raise ValueError(f"Invalid ricochet error in AI profile {profile_id!r}")
    if profile.scan_arc_degrees > 360:
        raise ValueError(f"Invalid scan arc in AI profile {profile_id!r}")
    if not isinstance(profile.predictive_aim_enabled, bool):
        raise ValueError(f"Invalid predictive-aim flag in AI profile {profile_id!r}")
    prediction_values = (
        profile.prediction_horizon,
        profile.prediction_step,
        profile.prediction_min_target_speed,
    )
    if any(not math.isfinite(value) for value in prediction_values):
        raise ValueError(f"Non-finite prediction value in AI profile {profile_id!r}")
    if profile.prediction_horizon < 0 or profile.prediction_min_target_speed < 0:
        raise ValueError(f"Invalid prediction range in AI profile {profile_id!r}")
    if (
        type(profile.prediction_iterations) is not int
        or not 1 <= profile.prediction_iterations <= 16
    ):
        raise ValueError(f"Invalid prediction iterations in AI profile {profile_id!r}")
    if (
        type(profile.prediction_max_ricochet_surfaces) is not int
        or profile.prediction_max_ricochet_surfaces < 0
        or profile.prediction_max_ricochet_surfaces > 128
    ):
        raise ValueError(f"Invalid predictive ricochet budget in AI profile {profile_id!r}")
    if profile.predictive_aim_enabled and profile.prediction_horizon <= 0:
        raise ValueError(f"Predictive AI profile {profile_id!r} needs a horizon")
    if math.ceil(profile.prediction_horizon / profile.prediction_step) > 256:
        raise ValueError(f"Prediction sample budget exceeded in AI profile {profile_id!r}")


def _timing_from_data(data: dict[str, Any], label: str) -> InitialFireTiming:
    allowed = {field.name for field in fields(InitialFireTiming)}
    _strict_fields(data, allowed, label)
    timing = InitialFireTiming(**data)
    if timing.base < 0 or timing.stagger < 0 or timing.cycle < 0:
        raise ValueError(f"Invalid initial fire timing in {label}")
    return timing


def _global_from_data(data: dict[str, Any]) -> GlobalAIConfig:
    names = {field.name for field in fields(GlobalAIConfig)}
    _strict_fields(data, names, "global AI configuration")
    missing = names - set(data)
    if missing:
        raise ValueError(f"Missing global AI fields: {sorted(missing)}")
    values = dict(data)
    values["direct_aim_offsets_px"] = tuple(float(value) for value in values["direct_aim_offsets_px"])
    values["dodge_candidate_angles_degrees"] = tuple(
        float(value) for value in values["dodge_candidate_angles_degrees"]
    )
    values["sound_ranges_tiles"] = {
        str(kind): float(radius) for kind, radius in values["sound_ranges_tiles"].items()
    }
    values["initial_fire_default"] = _timing_from_data(
        values["initial_fire_default"],
        "default initial fire timing",
    )
    values["initial_fire_overrides"] = {
        kind: _timing_from_data(timing, f"initial fire timing for {kind!r}")
        for kind, timing in values["initial_fire_overrides"].items()
    }
    config = GlobalAIConfig(**values)
    frame_budgets = (
        config.max_path_plans_per_frame,
        config.max_shot_plans_per_frame,
        config.max_predictive_shot_plans_per_frame,
        config.max_attackers,
    )
    if any(type(value) is not int or not 1 <= value <= 64 for value in frame_budgets):
        raise ValueError("AI frame budgets must be positive")
    if (
        type(config.max_sound_events) is not int
        or not 1 <= config.max_sound_events <= 1024
        or not config.sound_ranges_tiles
    ):
        raise ValueError("AI sound configuration cannot be empty")
    if any(radius <= 0 for radius in config.sound_ranges_tiles.values()):
        raise ValueError("AI sound ranges must be positive")
    if not config.direct_aim_offsets_px:
        raise ValueError("AI direct-aim offsets cannot be empty")
    if not config.dodge_candidate_angles_degrees:
        raise ValueError("AI dodge candidate angles cannot be empty")
    if not isinstance(config.omniscient_player_tracking, bool):
        raise ValueError("AI omniscient-player tracking must be boolean")
    if not 0 <= config.alert_awareness <= 1:
        raise ValueError("AI alert awareness must be in [0, 1]")
    if not 0 < config.near_lod_distance_tiles < config.far_lod_distance_tiles:
        raise ValueError("Invalid AI LOD distances")
    if not 0 <= config.solid_wall_sound_attenuation <= 1:
        raise ValueError("Invalid solid-wall sound attenuation")
    if not 0 <= config.breakable_wall_sound_attenuation <= 1:
        raise ValueError("Invalid breakable-wall sound attenuation")
    if not 0 <= config.state_hysteresis <= 1:
        raise ValueError("Invalid AI state hysteresis")
    entity_limits = (
        config.max_enemy_bullets,
        config.max_enemy_mines,
        config.max_enemy_bounces,
    )
    if any(type(value) is not int or not 0 <= value <= 64 for value in entity_limits):
        raise ValueError("Enemy entity limits cannot be negative")
    positive_values = (
        config.attack_slot_duration,
        config.communication_range_tiles,
        config.alert_cooldown,
        config.sound_event_lifetime,
        config.threat_horizon,
        config.threat_radius_tiles,
        config.search_duration,
        config.friendly_fire_horizon,
        config.initial_mine_delay,
        config.mine_retry_interval,
    )
    if any(value <= 0 for value in positive_values):
        raise ValueError("Global AI timings and ranges must be positive")
    if config.cover_search_radius_tiles < 1 or config.guard_patrol_radius_tiles < 0:
        raise ValueError("Invalid global AI search radius")
    nonnegative_values = (
        config.route_occupied_penalty,
        config.route_ally_path_penalty,
        config.route_reserved_goal_penalty,
        config.route_recent_penalty,
        config.route_avoid_penalty,
        config.route_noise,
        config.mine_danger_penalty,
        config.initial_mine_stagger,
    )
    if any(value < 0 for value in nonnegative_values):
        raise ValueError("AI costs and staggers cannot be negative")
    return config


@lru_cache(maxsize=1)
def load_ai_settings() -> AISettings:
    try:
        raw = json.loads(AI_DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot load AI configuration from {AI_DATA_FILE}") from error
    if raw.get("version") != 1:
        raise ValueError(f"Unsupported AI configuration version in {AI_DATA_FILE}")
    required_sections = {"version", "global", "profiles", "archetype_overrides"}
    if set(raw) != required_sections:
        raise ValueError(f"Invalid top-level AI configuration in {AI_DATA_FILE}")

    profiles = {
        profile_id: _profile_from_data(profile_id, profile_data)
        for profile_id, profile_data in raw["profiles"].items()
    }
    profile_fields = {field.name for field in fields(AIProfile)}
    overrides: dict[str, dict[str, Any]] = {}
    for kind, override in raw["archetype_overrides"].items():
        _strict_fields(override, profile_fields, f"AI override for {kind!r}")
        overrides[kind] = override

    settings = AISettings(
        profiles=profiles,
        archetype_overrides=overrides,
        global_config=_global_from_data(raw["global"]),
    )
    for profile_id, profile in profiles.items():
        _validate_profile(profile_id, profile)
    for kind, override in overrides.items():
        for profile_id, profile in profiles.items():
            _validate_profile(f"{profile_id}/{kind}", replace(profile, **override))
    return settings
