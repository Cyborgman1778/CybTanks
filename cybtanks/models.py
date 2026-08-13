from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame

from .config import EXPLOSION_EFFECT_DURATION, MAX_BOUNCES, TRACK_LIFETIME


Vec2 = pygame.Vector2
GridCell = tuple[int, int]


@dataclass
class EnemyMemory:
    state: str = "guard"
    role: str = "assault"
    awareness: float = 0.0
    has_line_of_sight: bool = False
    target_visible: bool = False
    last_known_position: Vec2 | None = None
    last_seen_position: Vec2 | None = None
    last_heard_position: Vec2 | None = None
    memory_remaining: float = 0.0
    hearing_remaining: float = 0.0
    reaction_remaining: float = 0.0
    sensor_timer: float = 0.0
    sensor_elapsed: float = 0.0
    decision_timer: float = 0.0
    state_elapsed: float = 0.0
    navigation_target: Vec2 | None = None
    decision_index: int = 0
    last_alert_time: float = -math.inf
    last_sound_event_id: int = 0
    threat: float = 0.0
    lod_factor: float = 0.0
    dodge_timer: float = 0.0
    dodge_cooldown: float = 0.0
    dodge_direction: Vec2 = field(default_factory=Vec2)
    aim_predictive: bool = False
    aim_requires_hit: bool = False
    aim_expected_bounces: int = -1


@dataclass
class Tank:
    tank_id: int
    team: str
    kind: str
    spawn_cell: GridCell
    position: Vec2
    body_angle: float
    turret_angle: float
    speed: float
    color: tuple[int, int, int]
    bullet_speed_class: str
    bullet_speed: float
    max_bullets: int
    max_bounces: int
    max_mines: int
    fire_rate: str
    shot_think_speed: str
    intelligence: str
    ricochet_accuracy: str
    ricochet_success_rate: float
    self_safe: bool
    shield_hits: int = 0
    max_shield_hits: int = 0
    shield_flash: float = 0.0
    alive: bool = True
    velocity: Vec2 = field(default_factory=Vec2)
    cooldown: float = 0.0
    fire_timer: float = 0.0
    mine_timer: float = 0.0
    shot_think_timer: float = 0.0
    plan_timer: float = 0.0
    path: list[GridCell] = field(default_factory=list)
    goal: GridCell | None = None
    aim_angle: float | None = None
    aim_timer: float = 0.0
    shot_ready: bool = False
    escaping_mines: bool = False
    stuck_timer: float = 0.0
    net_stuck_timer: float = 0.0
    stationary_timer: float = 0.0
    detour_timer: float = 0.0
    progress_anchor: Vec2 | None = None
    last_frame_position: Vec2 | None = None
    avoid_cell: GridCell | None = None
    avoid_timer: float = 0.0
    route_variant: int = 0
    route_seed: int = 0
    recent_cells: list[GridCell] = field(default_factory=list)
    ai: EnemyMemory = field(default_factory=EnemyMemory)


@dataclass
class Bullet:
    position: Vec2
    velocity: Vec2
    team: str
    owner_id: int
    color: tuple[int, int, int]
    speed_class: str = "slow"
    max_bounces: int = MAX_BOUNCES
    bounces: int = 0
    age: float = 0.0
    distance_travelled: float = 0.0
    travel_budget: float = 0.0
    alive: bool = True


@dataclass
class Mine:
    position: Vec2
    owner_id: int
    team: str
    age: float = 0.0
    triggered: bool = False
    warning_elapsed: float = 0.0
    beep_timer: float = 0.0
    owner_has_left: bool = False
    alive: bool = True


@dataclass
class Particle:
    position: Vec2
    velocity: Vec2
    color: tuple[int, int, int]
    size: float
    life: float
    max_life: float


@dataclass
class ExplosionEffect:
    position: Vec2
    radius: float
    age: float = 0.0
    duration: float = EXPLOSION_EFFECT_DURATION


@dataclass
class TrackMark:
    position: Vec2
    angle: float
    age: float = 0.0
    lifetime: float = TRACK_LIFETIME


@dataclass
class ShotTrace:
    target_hit: bool = False
    target_bounces: int = -1
    self_hit: bool = False
    ally_hit: bool = False
    target_distance: float = math.inf
