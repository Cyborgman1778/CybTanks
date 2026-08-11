from __future__ import annotations

import math
from dataclasses import dataclass

from .ai_config import AIProfile, AISettings
from .ai_perception import PerceptionSnapshot
from .config import (
    BULLET_RADIUS,
    COLS,
    MINE_ESCAPE_MARGIN,
    MINE_EXPLOSION_RADIUS,
    ROWS,
    TANK_HALF,
    TILE,
)
from .geometry import clamp, point_segment_distance_squared
from .models import Tank, Vec2
from .world import cell_center


@dataclass(frozen=True, slots=True)
class TacticalDecision:
    state: str
    target_position: Vec2 | None
    threat: float
    can_engage: bool


class UtilityDecisionSystem:
    def __init__(self, game: object, settings: AISettings) -> None:
        self.game = game
        self.settings = settings

    def update(
        self,
        enemy: Tank,
        profile: AIProfile,
        perception: PerceptionSnapshot,
        dt: float,
    ) -> TacticalDecision:
        memory = enemy.ai
        memory.decision_timer -= dt
        memory.state_elapsed += dt
        mine_danger = any(
            mine.alive
            and enemy.position.distance_to(mine.position)
            < MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
            for mine in getattr(self.game, "mines", ())
        )
        if mine_danger:
            memory.state = "evade"
            return TacticalDecision(
                "evade",
                perception.target_position,
                1.0,
                perception.can_engage,
            )
        if memory.state == "evade":
            memory.decision_timer = 0.0
        if memory.decision_timer > 0.0:
            can_engage = perception.can_engage and memory.state not in {
                "guard",
                "investigate",
                "search",
            }
            return TacticalDecision(
                memory.state,
                memory.navigation_target.copy() if memory.navigation_target is not None else None,
                memory.threat,
                can_engage,
            )

        threat = self._threat_level(enemy, perception)
        target = perception.target_position
        if target is None:
            state = "guard"
            target = self._patrol_target(enemy)
        elif not perception.target_visible:
            if perception.heard_contact:
                state = "investigate"
            elif memory.state == "search" and memory.state_elapsed >= self.settings.global_config.search_duration:
                state = "guard"
                target = self._patrol_target(enemy)
            else:
                state = "search"
        elif enemy.speed <= 0:
            state = "attack"
        else:
            state = self._combat_state(enemy, profile, threat)

        previous_target = memory.navigation_target
        target_changed = (
            previous_target is None
            or target is None
            or int(previous_target.x // TILE) != int(target.x // TILE)
            or int(previous_target.y // TILE) != int(target.y // TILE)
        )
        if state != memory.state or target_changed:
            memory.state = state
            memory.state_elapsed = 0.0
            memory.navigation_target = target.copy() if target is not None else None
            enemy.path = []
            enemy.goal = None
            enemy.plan_timer = 0.0
        memory.threat = threat
        memory.decision_index += 1
        interval = profile.decision_interval_near + (
            profile.decision_interval_far - profile.decision_interval_near
        ) * memory.lod_factor
        jitter = self._noise(enemy, "interval") * 0.24 - 0.12
        memory.decision_timer = max(0.03, interval * (1.0 + jitter))
        can_engage = perception.can_engage and state not in {"guard", "investigate", "search"}
        return TacticalDecision(state, target.copy() if target is not None else None, threat, can_engage)

    def _combat_state(self, enemy: Tank, profile: AIProfile, threat: float) -> str:
        role = enemy.ai.role
        exposed = self.game.world.clear_segment(
            enemy.position,
            self.game.player.position,
            BULLET_RADIUS + 1.0,
        )
        utilities = {
            "attack": profile.aggression * (0.82 + (1.0 - threat) * 0.25),
            "cover": profile.cover_preference * (0.22 + threat * 0.95 + (0.12 if exposed else 0.0)),
            "flank": profile.flank_preference * (0.52 + (0.34 if role == "flanker" else 0.1)) * (1.0 - threat * 0.3),
            "retreat": max(
                0.0,
                (threat - profile.retreat_threshold)
                / max(0.01, 1.0 - profile.retreat_threshold),
            )
            * (1.15 - profile.aggression * 0.25),
        }
        if role == "assault":
            utilities["attack"] += 0.12
        elif role == "support":
            utilities["cover"] += 0.1
            utilities["attack"] += 0.04
        if enemy.max_shield_hits > 0 and enemy.shield_hits == 0:
            utilities["cover"] += 0.16
            utilities["retreat"] += 0.12

        current = enemy.ai.state
        if current in utilities:
            utilities[current] += self.settings.global_config.state_hysteresis
        for state in utilities:
            utilities[state] += (self._noise(enemy, state) - 0.5) * profile.unpredictability
        return max(utilities, key=utilities.get)

    def _threat_level(self, enemy: Tank, perception: PerceptionSnapshot) -> float:
        config = self.settings.global_config
        incoming = 0.0
        danger_radius = config.threat_radius_tiles * TILE
        for bullet in getattr(self.game, "bullets", ()):
            if not bullet.alive or bullet.team == enemy.team or bullet.velocity.length_squared() == 0:
                continue
            projector = getattr(getattr(self.game, "combat", None), "projectile_path_segments", None)
            if projector is not None:
                segments = projector(bullet, config.threat_horizon)
            else:
                endpoint = bullet.position + bullet.velocity * config.threat_horizon
                segment = endpoint - bullet.position
                ratio = clamp(
                    (enemy.position - bullet.position).dot(segment)
                    / max(segment.length_squared(), 0.000_001),
                    0.0,
                    1.0,
                )
                closest = bullet.position + segment * ratio
                segments = (
                    [(bullet.position, endpoint)]
                    if self.game.world.clear_segment(bullet.position, closest, BULLET_RADIUS)
                    else []
                )
            for segment_start, segment_end in segments:
                distance = math.sqrt(
                    point_segment_distance_squared(
                        enemy.position,
                        segment_start,
                        segment_end,
                    )
                )
                if distance >= danger_radius:
                    continue
                direction = segment_end - segment_start
                approaching = direction.dot(enemy.position - segment_start) > 0
                incoming = max(
                    incoming,
                    (1.0 - distance / danger_radius) * (1.0 if approaching else 0.45),
                )

        distance_to_player = enemy.position.distance_to(self.game.player.position)
        close_pressure = max(0.0, 1.0 - distance_to_player / (TILE * 2.5))
        exposure = 0.2 if perception.has_line_of_sight else 0.0
        shield_loss = 0.12 if enemy.max_shield_hits > 0 and enemy.shield_hits == 0 else 0.0
        return clamp(incoming * 0.78 + close_pressure * 0.28 + exposure + shield_loss, 0.0, 1.0)

    def _patrol_target(self, enemy: Tank) -> Vec2:
        radius = self.settings.global_config.guard_patrol_radius_tiles
        start_col, start_row = enemy.spawn_cell
        offsets = []
        for distance in range(1, radius + 1):
            offsets.extend(
                (
                    (distance, 0),
                    (0, distance),
                    (-distance, 0),
                    (0, -distance),
                    (distance, distance),
                    (-distance, distance),
                    (-distance, -distance),
                    (distance, -distance),
                )
            )
        if not offsets:
            return cell_center(enemy.spawn_cell)
        start_index = (enemy.route_seed + enemy.ai.decision_index * 5) % len(offsets)
        for offset_index in range(len(offsets)):
            offset = offsets[(start_index + offset_index) % len(offsets)]
            cell = (
                int(clamp(start_col + offset[0], 1, COLS - 2)),
                int(clamp(start_row + offset[1], 1, ROWS - 2)),
            )
            if not self.game.world.is_wall(cell):
                return cell_center(cell)
        return cell_center(enemy.spawn_cell)

    @staticmethod
    def _noise(enemy: Tank, label: str) -> float:
        label_value = sum((index + 1) * ord(character) for index, character in enumerate(label))
        value = (
            enemy.route_seed
            ^ (enemy.ai.decision_index * 83_492_791)
            ^ (label_value * 19_349_663)
        )
        return (value & 0xFFFF) / 0xFFFF
