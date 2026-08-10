from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame

from .config import MAX_BOUNCES


Vec2 = pygame.Vector2
GridCell = tuple[int, int]


@dataclass
class Tank:
    tank_id: int
    team: str
    kind: str
    position: Vec2
    body_angle: float
    turret_angle: float
    speed: float
    color: tuple[int, int, int]
    bullet_speed: float
    max_bullets: int
    max_bounces: int
    max_mines: int
    fire_rate: str
    intelligence: str
    ricochet_accuracy: str
    ricochet_success_rate: float
    self_safe: bool
    alive: bool = True
    velocity: Vec2 = field(default_factory=Vec2)
    cooldown: float = 0.0
    fire_timer: float = 0.0
    mine_timer: float = 0.0
    plan_timer: float = 0.0
    path: list[GridCell] = field(default_factory=list)
    goal: GridCell | None = None
    aim_angle: float | None = None
    aim_timer: float = 0.0
    shot_ready: bool = False
    escaping_mines: bool = False
    stuck_timer: float = 0.0
    avoid_cell: GridCell | None = None
    avoid_timer: float = 0.0
    route_variant: int = 0


@dataclass
class Bullet:
    position: Vec2
    velocity: Vec2
    team: str
    owner_id: int
    color: tuple[int, int, int]
    max_bounces: int = MAX_BOUNCES
    bounces: int = 0
    age: float = 0.0
    distance_travelled: float = 0.0
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
class ShotTrace:
    target_hit: bool = False
    target_bounces: int = -1
    self_hit: bool = False
    ally_hit: bool = False
    target_distance: float = math.inf
