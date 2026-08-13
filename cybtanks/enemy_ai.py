from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ai_config import AIProfile, load_ai_settings
from .ai_decision import TacticalDecision, UtilityDecisionSystem
from .ai_perception import PerceptionSnapshot, PerceptionSystem
from .ai_squad import SquadCoordinator
from .config import (
    BULLET_RADIUS,
    COLS,
    FIRE_RATE_DELAYS,
    MINE_ESCAPE_MARGIN,
    MINE_EXPLOSION_RADIUS,
    ROWS,
    TANK_HALF,
    TILE,
)
from .geometry import angle_difference, clamp, point_segment_distance_squared, turn_towards
from .models import Bullet, EnemyMemory, Tank, Vec2
from .world import cell_center, grid_cell

if TYPE_CHECKING:
    from .game import Game


@dataclass(frozen=True, slots=True)
class EnemyUpdateContext:
    profile: AIProfile
    perception: PerceptionSnapshot
    decision: TacticalDecision


@dataclass(frozen=True, slots=True)
class TargetPrediction:
    positions: tuple[Vec2, ...]
    step: float
    horizon: float

    def position_at(self, time: float) -> Vec2 | None:
        if time < 0.0 or time > self.horizon or not self.positions:
            return None
        if len(self.positions) == 1:
            return self.positions[0].copy()
        sample = time / self.step
        index = min(int(sample), len(self.positions) - 2)
        fraction = min(1.0, max(0.0, sample - index))
        return self.positions[index].lerp(self.positions[index + 1], fraction)


class EnemyAISystem:
    def __init__(self, game: Game) -> None:
        self.game = game
        self.settings = getattr(game, "ai_settings", None) or load_ai_settings()
        self.perception = PerceptionSystem(getattr(game, "world", None), self.settings)
        self.squad = SquadCoordinator(self.settings)
        self.decisions = UtilityDecisionSystem(game, self.settings)
        self._profiles: dict[tuple[str, str], AIProfile] = {}
        self._mine_cache_key: tuple[tuple[int, float, float], ...] | None = None
        self._mine_blocked_cache: set[tuple[int, int]] = set()
        self._cell_metrics_cache: dict[
            tuple[int, tuple[float, float], tuple[int, int]],
            tuple[float, bool],
        ] = {}
        self._path_budget: int | None = None
        self._shot_budget: int | None = None
        self._predictive_shot_budget: int | None = None
        self._planned_this_frame: set[int] = set()
        self._update_cursor = 0
        self._now = 0.0

    def profile_for(self, enemy: Tank) -> AIProfile:
        key = (enemy.kind, enemy.intelligence)
        if key not in self._profiles:
            self._profiles[key] = self.settings.profile_for(*key)
        return self._profiles[key]

    def reset(self) -> None:
        self.perception.reset()
        self.squad.reset()
        self._mine_cache_key = None
        self._mine_blocked_cache.clear()
        self._cell_metrics_cache.clear()
        self._path_budget = None
        self._shot_budget = None
        self._predictive_shot_budget = None
        self._planned_this_frame.clear()
        self._update_cursor = 0
        self._now = 0.0

    def initialize_enemy(self, enemy: Tank, index: int) -> None:
        profile = self.profile_for(enemy)
        enemy.ai = EnemyMemory(
            sensor_timer=(index % 6) * profile.sensor_interval_near / 6.0,
            decision_timer=(index % 5) * profile.decision_interval_near / 5.0,
        )
        enemy.velocity.update(0, 0)
        enemy.cooldown = 0.0
        enemy.shot_think_timer = 0.0
        enemy.fire_timer = self.settings.initial_fire_delay(enemy.kind, index)
        enemy.mine_timer = (
            self.settings.global_config.initial_mine_delay
            + index * self.settings.global_config.initial_mine_stagger
        )
        enemy.path = []
        enemy.goal = None
        enemy.plan_timer = index * 0.03
        enemy.aim_angle = None
        enemy.aim_timer = 0.0
        enemy.shot_ready = False
        enemy.escaping_mines = False
        enemy.stuck_timer = 0.0
        enemy.net_stuck_timer = 0.0
        enemy.stationary_timer = 0.0
        enemy.detour_timer = 0.0
        enemy.progress_anchor = None
        enemy.last_frame_position = None
        enemy.avoid_cell = None
        enemy.avoid_timer = 0.0
        enemy.route_variant += 1
        enemy.route_seed = random.getrandbits(31)
        enemy.recent_cells.clear()
        self.squad.release_attack_slot(enemy.tank_id)

    def report_sound(self, position: Vec2, kind: str, source_team: str) -> None:
        self.perception.report_sound(position, kind, source_team)

    def _cell_tactical_metrics(
        self,
        cell: tuple[int, int],
        target_position: Vec2,
    ) -> tuple[float, bool]:
        key = (
            getattr(self.game.world, "revision", 0),
            (round(target_position.x, 1), round(target_position.y, 1)),
            cell,
        )
        cached = self._cell_metrics_cache.get(key)
        if cached is not None:
            return cached
        position = cell_center(cell)
        metrics = (
            self.game.world.cover_quality(cell, target_position),
            self.game.world.clear_segment(
                position,
                target_position,
                BULLET_RADIUS + 1.0,
            ),
        )
        if len(self._cell_metrics_cache) >= 2048:
            self._cell_metrics_cache.clear()
        self._cell_metrics_cache[key] = metrics
        return metrics

    def _prediction_position_clear(
        self,
        target: Tank,
        position: Vec2,
        blockers: tuple[Tank, ...],
    ) -> tuple[bool, bool]:
        if self.game.world.tank_touches_wall(position):
            return False, False
        minimum_distance_squared = (TANK_HALF * 2) ** 2
        uncertain_collision = any(
            tank.alive
            and tank.tank_id != target.tank_id
            and position.distance_squared_to(tank.position) < minimum_distance_squared
            for tank in blockers
        )
        return not uncertain_collision, uncertain_collision

    def target_prediction(
        self,
        enemy: Tank,
        *,
        ignore_speed_threshold: bool = False,
    ) -> TargetPrediction | None:
        profile = self.profile_for(enemy)
        target = self.game.player
        if (
            not profile.predictive_aim_enabled
            or not target.alive
            or (
                not ignore_speed_threshold
                and target.velocity.length() < profile.prediction_min_target_speed
            )
        ):
            return None

        position = target.position.copy()
        velocity = target.velocity.copy()
        steps = max(1, math.ceil(profile.prediction_horizon / profile.prediction_step))
        blockers = tuple(self.game.all_tanks())
        positions = [position.copy()]
        for _ in range(steps):
            next_position = position.copy()
            next_position.x += velocity.x * profile.prediction_step
            x_clear, x_uncertain = self._prediction_position_clear(
                target,
                next_position,
                blockers,
            )
            if x_uncertain:
                break
            if not x_clear:
                next_position.x = position.x
            next_position.y += velocity.y * profile.prediction_step
            y_clear, y_uncertain = self._prediction_position_clear(
                target,
                next_position,
                blockers,
            )
            if y_uncertain:
                break
            if not y_clear:
                next_position.y = position.y
            position = next_position
            positions.append(position.copy())
        horizon = min(
            profile.prediction_horizon,
            (len(positions) - 1) * profile.prediction_step,
        )
        return TargetPrediction(
            positions=tuple(positions),
            step=profile.prediction_step,
            horizon=horizon,
        )

    @staticmethod
    def _linear_intercept_time(
        origin: Vec2,
        target_position: Vec2,
        target_velocity: Vec2,
        projectile_speed: float,
    ) -> float | None:
        relative = target_position - origin
        a = target_velocity.length_squared() - projectile_speed**2
        b = 2.0 * relative.dot(target_velocity)
        c = relative.length_squared()
        if abs(a) <= 0.000_001:
            if abs(b) <= 0.000_001:
                return 0.0 if c <= 0.000_001 else None
            time = -c / b
            return time if time > 0.0 else None
        discriminant = b * b - 4.0 * a * c
        if discriminant < 0.0:
            return None
        root = math.sqrt(discriminant)
        times = [
            time
            for time in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a))
            if time > 0.0
        ]
        return min(times) if times else None

    def _predictive_direct_candidates(
        self,
        enemy: Tank,
        prediction: TargetPrediction,
    ) -> list[tuple[float, float]]:
        profile = self.profile_for(enemy)
        intercept_time = self._linear_intercept_time(
            enemy.position,
            self.game.player.position,
            self.game.player.velocity,
            enemy.bullet_speed,
        )
        if intercept_time is None:
            return []
        intercept_time = min(intercept_time, prediction.horizon)

        origin = enemy.position
        for _ in range(profile.prediction_iterations):
            future_position = prediction.position_at(intercept_time)
            if future_position is None:
                return []
            difference = future_position - origin
            if difference.length_squared() == 0.0:
                return []
            angle = math.atan2(difference.y, difference.x)
            origin = self.game.combat.safe_muzzle(enemy, angle)
            intercept_time = origin.distance_to(future_position) / enemy.bullet_speed
            intercept_time = min(intercept_time, prediction.horizon)

        future_position = prediction.position_at(intercept_time)
        if future_position is None:
            return []
        difference = future_position - origin
        if difference.length_squared() == 0.0:
            return []
        perpendicular = Vec2(-difference.y, difference.x).normalize()
        candidates = []
        for offset in self.settings.global_config.direct_aim_offsets_px:
            aim_point = future_position + perpendicular * offset
            if not self.game.world.clear_segment(
                enemy.position,
                aim_point,
                BULLET_RADIUS + 1.0,
            ):
                continue
            angle = math.atan2(
                aim_point.y - enemy.position.y,
                aim_point.x - enemy.position.x,
            )
            trace = self.game.combat.trace_shot(
                enemy,
                angle,
                self.game.player,
                target_position_at=prediction.position_at,
            )
            if (
                trace.target_hit
                and trace.target_bounces == 0
                and not trace.self_hit
                and not trace.ally_hit
            ):
                candidates.append((trace.target_distance, angle))
                if offset == 0:
                    break
        return candidates

    def predictive_direct_shot_angle(
        self,
        enemy: Tank,
        prediction: TargetPrediction,
    ) -> float | None:
        candidates = self._predictive_direct_candidates(enemy, prediction)
        return min(candidates)[1] if candidates else None

    def predictive_ricochet_angles(
        self,
        enemy: Tank,
        prediction: TargetPrediction,
    ) -> list[float]:
        if enemy.max_bounces <= 0:
            return []
        profile = self.profile_for(enemy)
        candidates = []
        seen: set[int] = set()
        predicted_endpoint = prediction.position_at(prediction.horizon)

        def surface_cost(surface: tuple[str, float, float, float]) -> float:
            axis, coordinate, minimum, maximum = surface
            if axis == "x":
                bounce_point = Vec2(
                    coordinate,
                    clamp(predicted_endpoint.y, minimum, maximum),
                )
            else:
                bounce_point = Vec2(
                    clamp(predicted_endpoint.x, minimum, maximum),
                    coordinate,
                )
            return enemy.position.distance_to(bounce_point) + bounce_point.distance_to(
                predicted_endpoint
            )

        ordered_surfaces = sorted(
            self.game.world.bounce_surfaces,
            key=surface_cost,
        )
        surface_limit = profile.prediction_max_ricochet_surfaces
        surfaces = ordered_surfaces[:surface_limit]
        for axis, coordinate, minimum, maximum in surfaces:
            intercept_time = enemy.position.distance_to(self.game.player.position) / enemy.bullet_speed
            angle = 0.0
            valid = True
            for _ in range(profile.prediction_iterations):
                target_position = prediction.position_at(intercept_time)
                if target_position is None:
                    valid = False
                    break
                if axis == "x":
                    mirrored = Vec2(coordinate * 2.0 - target_position.x, target_position.y)
                else:
                    mirrored = Vec2(target_position.x, coordinate * 2.0 - target_position.y)
                delta = mirrored - enemy.position
                if delta.length_squared() == 0.0:
                    valid = False
                    break
                angle = math.atan2(delta.y, delta.x)
                origin = self.game.combat.safe_muzzle(enemy, angle)
                unfolded_distance = origin.distance_to(mirrored)
                intercept_time = unfolded_distance / enemy.bullet_speed
                if intercept_time > prediction.horizon:
                    valid = False
                    break
            if not valid:
                continue

            target_position = prediction.position_at(intercept_time)
            if target_position is None:
                continue
            origin = self.game.combat.safe_muzzle(enemy, angle)
            if axis == "x":
                mirrored = Vec2(coordinate * 2.0 - target_position.x, target_position.y)
                delta = mirrored - origin
                if abs(delta.x) < 0.001:
                    continue
                ratio = (coordinate - origin.x) / delta.x
                along = origin.y + delta.y * ratio
            else:
                mirrored = Vec2(target_position.x, coordinate * 2.0 - target_position.y)
                delta = mirrored - origin
                if abs(delta.y) < 0.001:
                    continue
                ratio = (coordinate - origin.y) / delta.y
                along = origin.x + delta.x * ratio
            corner_margin = BULLET_RADIUS + 4.0
            if (
                not 0.0 < ratio < 1.0
                or not minimum + corner_margin < along < maximum - corner_margin
            ):
                continue
            angle = math.atan2(mirrored.y - enemy.position.y, mirrored.x - enemy.position.x)
            angle_key = round(angle * 10_000)
            if angle_key in seen:
                continue
            seen.add(angle_key)
            candidates.append((intercept_time, angle))
        candidates.sort()
        return [angle for _, angle in candidates]

    def predictive_ricochet_angle(
        self,
        enemy: Tank,
        prediction: TargetPrediction,
    ) -> float | None:
        candidate_limit = self.profile_for(enemy).max_ricochet_candidates
        for angle in self.predictive_ricochet_angles(enemy, prediction)[:candidate_limit]:
            trace = self.game.combat.trace_shot(
                enemy,
                angle,
                self.game.player,
                target_position_at=prediction.position_at,
            )
            if (
                trace.target_hit
                and trace.target_bounces == 1
                and not trace.self_hit
                and not trace.ally_hit
            ):
                return angle
        return None

    def direct_shot_angle(self, enemy: Tank) -> float | None:
        difference = self.game.player.position - enemy.position
        if difference.length_squared() == 0:
            return None
        perpendicular = Vec2(-difference.y, difference.x).normalize()
        candidates = []
        for offset in self.settings.global_config.direct_aim_offsets_px:
            aim_point = self.game.player.position + perpendicular * offset
            if not self.game.world.clear_segment(enemy.position, aim_point, BULLET_RADIUS + 1):
                continue
            angle = math.atan2(aim_point.y - enemy.position.y, aim_point.x - enemy.position.x)
            trace = self.game.combat.trace_shot(enemy, angle, self.game.player)
            if trace.target_hit and trace.target_bounces == 0 and not trace.self_hit and not trace.ally_hit:
                if offset == 0:
                    return angle
                candidates.append((trace.target_distance, angle))
        return min(candidates)[1] if candidates else None

    def ricochet_angles(self, shooter: Tank, target: Tank) -> list[float]:
        candidates = []
        seen: set[int] = set()
        for axis, coordinate, minimum, maximum in self.game.world.bounce_surfaces:
            if axis == "x":
                mirrored = Vec2(coordinate * 2 - target.position.x, target.position.y)
                delta = mirrored - shooter.position
                if abs(delta.x) < 0.001:
                    continue
                ratio = (coordinate - shooter.position.x) / delta.x
                along = shooter.position.y + delta.y * ratio
            else:
                mirrored = Vec2(target.position.x, coordinate * 2 - target.position.y)
                delta = mirrored - shooter.position
                if abs(delta.y) < 0.001:
                    continue
                ratio = (coordinate - shooter.position.y) / delta.y
                along = shooter.position.x + delta.x * ratio

            corner_margin = BULLET_RADIUS + 4
            if not 0.0 < ratio < 1.0 or not minimum + corner_margin < along < maximum - corner_margin:
                continue
            angle = math.atan2(delta.y, delta.x)
            angle_key = round(angle * 10_000)
            if angle_key in seen:
                continue
            seen.add(angle_key)
            candidates.append((delta.length(), angle))
        candidates.sort()
        return [angle for _, angle in candidates]

    def accurate_ricochet_angle(self, enemy: Tank) -> float | None:
        if enemy.max_bounces <= 0:
            return None
        candidate_limit = self.profile_for(enemy).max_ricochet_candidates
        for angle in self.ricochet_angles(enemy, self.game.player)[:candidate_limit]:
            trace = self.game.combat.trace_shot(enemy, angle, self.game.player)
            if trace.target_hit and trace.target_bounces == 1 and not trace.self_hit and not trace.ally_hit:
                return angle
        return None

    def choose_shot(self, enemy: Tank) -> tuple[float, bool]:
        enemy.ai.aim_predictive = False
        enemy.ai.aim_requires_hit = False
        enemy.ai.aim_expected_bounces = -1
        profile = self.profile_for(enemy)
        prediction = self.target_prediction(enemy)
        prediction_required = (
            profile.predictive_aim_enabled
            and self.game.player.velocity.length()
            >= profile.prediction_min_target_speed
        )
        if prediction_required and prediction is None:
            fallback = math.atan2(
                self.game.player.position.y - enemy.position.y,
                self.game.player.position.x - enemy.position.x,
            )
            return fallback, False
        if prediction is not None:
            direct_angle = self.predictive_direct_shot_angle(enemy, prediction)
            if direct_angle is not None:
                enemy.ai.aim_predictive = True
                enemy.ai.aim_requires_hit = True
                enemy.ai.aim_expected_bounces = 0
                return direct_angle, True

            ricochet_angle = self.predictive_ricochet_angle(enemy, prediction)
            fallback_position = prediction.position_at(prediction.horizon)
            fallback = math.atan2(
                fallback_position.y - enemy.position.y,
                fallback_position.x - enemy.position.x,
            )
            if ricochet_angle is not None and (
                enemy.ricochet_accuracy == "accurate"
                or random.random() < enemy.ricochet_success_rate
            ):
                enemy.ai.aim_predictive = True
                enemy.ai.aim_requires_hit = True
                enemy.ai.aim_expected_bounces = 1
                return ricochet_angle, True

            if ricochet_angle is not None:
                for _ in range(profile.ricochet_error_attempts):
                    error = random.choice((-1, 1)) * math.radians(
                        random.uniform(
                            profile.ricochet_error_min_degrees,
                            profile.ricochet_error_max_degrees,
                        )
                    )
                    inaccurate_angle = ricochet_angle + error
                    trace = self.game.combat.trace_shot(
                        enemy,
                        inaccurate_angle,
                        self.game.player,
                        target_position_at=prediction.position_at,
                    )
                    if not trace.self_hit and not trace.ally_hit:
                        enemy.ai.aim_predictive = True
                        enemy.ai.aim_requires_hit = False
                        return inaccurate_angle, True
            predicted_fallback = fallback
        else:
            predicted_fallback = None

        if prediction_required:
            return predicted_fallback, False

        direct_angle = self.direct_shot_angle(enemy)
        if direct_angle is not None:
            return direct_angle, True

        ricochet_angle = self.accurate_ricochet_angle(enemy)
        fallback = (
            predicted_fallback
            if predicted_fallback is not None
            else math.atan2(
                self.game.player.position.y - enemy.position.y,
                self.game.player.position.x - enemy.position.x,
            )
        )
        if ricochet_angle is None:
            return fallback, False
        if enemy.ricochet_accuracy == "accurate" or random.random() < enemy.ricochet_success_rate:
            return ricochet_angle, True

        profile = self.profile_for(enemy)
        for _ in range(profile.ricochet_error_attempts):
            error = random.choice((-1, 1)) * math.radians(
                random.uniform(
                    profile.ricochet_error_min_degrees,
                    profile.ricochet_error_max_degrees,
                )
            )
            inaccurate_angle = ricochet_angle + error
            trace = self.game.combat.trace_shot(enemy, inaccurate_angle, self.game.player)
            if not trace.self_hit and not trace.ally_hit:
                return inaccurate_angle, True
        return fallback, False

    def plan_path(self, enemy: Tank) -> None:
        start = grid_cell(enemy.position)
        profile = self.profile_for(enemy)
        target_position = enemy.ai.navigation_target or self.game.player.position
        target_cell = grid_cell(target_position)
        state = enemy.ai.state if enemy.ai.navigation_target is not None else "attack"
        blocked = self.mine_blocked_cells()
        blocked.discard(start)
        penalties = self.route_penalties(enemy)
        reserved_goals = {
            ally.goal
            for ally in self.game.enemies
            if ally.alive and ally.tank_id != enemy.tank_id and ally.goal is not None
        }
        search_radius = profile.navigation_search_radius_tiles
        search_center = target_cell
        if state in {"cover", "retreat"}:
            search_center = start
            search_radius = self.settings.global_config.cover_search_radius_tiles

        candidate_cells = []
        current_target_distance = abs(start[0] - target_cell[0]) + abs(start[1] - target_cell[1])
        for row in range(max(1, search_center[1] - search_radius), min(ROWS - 1, search_center[1] + search_radius + 1)):
            for col in range(max(1, search_center[0] - search_radius), min(COLS - 1, search_center[0] + search_radius + 1)):
                candidate = (col, row)
                if (
                    self.game.world.is_wall(candidate)
                    or candidate in blocked
                    or (enemy.speed > 0 and candidate == start)
                ):
                    continue
                distance_to_target = abs(col - target_cell[0]) + abs(row - target_cell[1])
                if state in {"attack", "flank"} and not (
                    profile.min_distance_tiles <= distance_to_target <= profile.max_distance_tiles
                ):
                    continue
                if state == "investigate" and distance_to_target > 1:
                    continue
                if state == "search" and distance_to_target > 3:
                    continue
                if state == "retreat" and distance_to_target <= current_target_distance:
                    continue
                candidate_cells.append(candidate)

        costs, came_from = self.game.world.navigation_field(start, blocked, penalties)
        candidates = []
        for candidate in candidate_cells:
            if candidate not in costs:
                continue
            col, row = candidate
            position = cell_center(candidate)
            distance_to_target = abs(col - target_cell[0]) + abs(row - target_cell[1])
            reservation_cost = (
                self.settings.global_config.route_reserved_goal_penalty
                if candidate in reserved_goals
                else 0.0
            )
            variant_hash = (
                col * 73_856_093
                ^ row * 19_349_663
                ^ enemy.route_seed
                ^ enemy.route_variant * 83_492_791
            )
            variant = (
                (variant_hash & 0xFFFF)
                / 0xFFFF
                * self.settings.global_config.route_noise
                * (1.0 + profile.unpredictability)
            )
            if state in {"attack", "flank", "cover", "retreat"}:
                cover, firing_lane = self._cell_tactical_metrics(candidate, target_position)
            else:
                cover, firing_lane = 0.0, False
            score = costs[candidate] + reservation_cost + variant
            if state == "attack":
                score += abs(distance_to_target - profile.preferred_distance_tiles) * 1.35
                score += 0.0 if firing_lane else 3.2 + profile.aggression
                score -= cover * profile.cover_preference * 1.4
            elif state == "flank":
                target_to_enemy = enemy.position - target_position
                target_to_candidate = position - target_position
                if target_to_enemy.length_squared() > 0 and target_to_candidate.length_squared() > 0:
                    side = 1.0 if enemy.route_seed & 1 else -1.0
                    desired_side = Vec2(-target_to_enemy.y, target_to_enemy.x).normalize() * side
                    lateral_alignment = desired_side.dot(target_to_candidate.normalize())
                    score += (1.0 - lateral_alignment) * self.settings.global_config.flank_lateral_tiles
                score += abs(distance_to_target - profile.preferred_distance_tiles)
                score -= cover * profile.cover_preference
            elif state == "cover":
                score -= cover * (5.0 + profile.cover_preference * 4.0)
                if cover < 0.6:
                    score += 6.0
            elif state == "retreat":
                score -= distance_to_target * 1.45
                score -= cover * (2.5 + profile.cover_preference * 2.5)
            elif state in {"investigate", "search"}:
                score += distance_to_target * (2.0 if state == "investigate" else 0.65)
                score -= cover * profile.cover_preference * 0.5
            else:
                score += distance_to_target * 1.5
            candidates.append((score, candidate))

        if not candidates:
            col, row = start
            for candidate in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
                if candidate in costs and candidate not in blocked:
                    candidates.append((costs[candidate], candidate))

        if candidates:
            _, enemy.goal = min(candidates, key=lambda item: item[0])
            enemy.path = self.game.world.reconstruct_path(start, enemy.goal, came_from) or []
        else:
            enemy.goal = start
            enemy.path = []
        enemy.plan_timer = profile.navigation_interval_min + random.random() * (
            profile.navigation_interval_max - profile.navigation_interval_min
        )

    def route_penalties(self, enemy: Tank) -> dict[tuple[int, int], float]:
        config = self.settings.global_config
        penalties: dict[tuple[int, int], float] = {}
        for ally in self.game.enemies:
            if not ally.alive or ally.tank_id == enemy.tank_id:
                continue
            occupied = grid_cell(ally.position)
            penalties[occupied] = penalties.get(occupied, 0.0) + config.route_occupied_penalty
            for index, cell in enumerate(ally.path[:10]):
                penalty = max(1.0, config.route_ally_path_penalty - index * 0.5)
                penalties[cell] = penalties.get(cell, 0.0) + penalty
            if ally.goal is not None:
                penalties[ally.goal] = penalties.get(ally.goal, 0.0) + config.route_reserved_goal_penalty

        for index, cell in enumerate(reversed(enemy.recent_cells[-10:])):
            penalties[cell] = penalties.get(cell, 0.0) + max(
                0.5,
                config.route_recent_penalty - index * 0.35,
            )

        if enemy.avoid_cell is not None and enemy.avoid_timer > 0:
            penalties[enemy.avoid_cell] = penalties.get(enemy.avoid_cell, 0.0) + config.route_avoid_penalty

        noise_seed = enemy.route_seed ^ (enemy.route_variant * 83_492_791)
        for row in range(1, ROWS - 1):
            for col in range(1, COLS - 1):
                cell = (col, row)
                if self.game.world.is_wall(cell):
                    continue
                value = (col * 73_856_093) ^ (row * 19_349_663) ^ noise_seed
                penalties[cell] = penalties.get(cell, 0.0) + (value & 0xFFFF) / 0xFFFF * config.route_noise
        return penalties

    def mine_blocked_cells(self) -> set[tuple[int, int]]:
        cache_key = tuple(
            sorted(
                (id(mine), round(mine.position.x, 3), round(mine.position.y, 3))
                for mine in self.game.mines
                if mine.alive
            )
        )
        if cache_key == self._mine_cache_key:
            return set(self._mine_blocked_cache)
        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        self._mine_blocked_cache = {
            (col, row)
            for row in range(1, ROWS - 1)
            for col in range(1, COLS - 1)
            if any(
                mine.alive and cell_center((col, row)).distance_to(mine.position) < safe_distance
                for mine in self.game.mines
            )
        }
        self._mine_cache_key = cache_key
        return set(self._mine_blocked_cache)

    def mine_danger(self, enemy: Tank) -> bool:
        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        return any(
            mine.alive and enemy.position.distance_to(mine.position) < safe_distance
            for mine in self.game.mines
        )

    def route_has_mine_danger(self, enemy: Tank) -> bool:
        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        route_points = [enemy.position, *(cell_center(cell) for cell in enemy.path)]
        for mine in self.game.mines:
            if not mine.alive:
                continue
            if any(point.distance_to(mine.position) < safe_distance for point in route_points):
                return True
            if any(
                point_segment_distance_squared(mine.position, start, end) < safe_distance**2
                for start, end in zip(route_points, route_points[1:])
            ):
                return True
        return False

    def steer_around_friendly_fire(self, enemy: Tank, movement: Vec2) -> Vec2:
        if self.game.combat.movement_safe_from_friendly_fire(enemy, movement):
            return movement

        base_angle = math.atan2(movement.y, movement.x)
        side = 1 if enemy.route_seed & 1 else -1
        offsets = (
            side * math.pi / 4,
            -side * math.pi / 4,
            side * math.pi / 2,
            -side * math.pi / 2,
            side * math.pi * 3 / 4,
            -side * math.pi * 3 / 4,
            math.pi,
        )
        distance = movement.length()
        best_movement = movement
        best_clearance = self.game.combat.friendly_fire_destination_clearance(
            enemy,
            movement,
        )
        for offset in offsets:
            angle = base_angle + offset
            candidate = Vec2(math.cos(angle), math.sin(angle)) * distance
            if self.game.world.tank_touches_wall(enemy.position + candidate):
                continue
            if self.game.combat.movement_safe_from_friendly_fire(enemy, candidate):
                return candidate
            clearance = self.game.combat.friendly_fire_destination_clearance(
                enemy,
                candidate,
            )
            if clearance > best_clearance:
                best_movement = candidate
                best_clearance = clearance
        return best_movement

    def enemy_push_safe_from_friendly_fire(self, tank: Tank, movement: Vec2) -> bool:
        if tank.team != "enemy":
            return True
        if self.mine_danger(tank):
            current_distance = min(
                mine.position.distance_to(tank.position)
                for mine in self.game.mines
                if mine.alive
            )
            future_position = tank.position + movement
            future_distance = min(
                mine.position.distance_to(future_position)
                for mine in self.game.mines
                if mine.alive
            )
            if future_distance <= current_distance:
                return False
        return self.game.combat.movement_safe_from_friendly_fire(tank, movement)

    def move_enemy(self, enemy: Tank, movement: Vec2) -> Vec2:
        return self.game.world.move_tank(
            enemy,
            movement,
            self.game.all_tanks(),
            lambda tank, pushed: tank.tank_id == enemy.tank_id
            or self.enemy_push_safe_from_friendly_fire(tank, pushed),
        )

    def coordinate_crowded_cell(self, enemy: Tank, movement: Vec2, dt: float) -> Vec2:
        current_cell = grid_cell(enemy.position)
        cellmates = [
            ally
            for ally in self.game.enemies
            if ally.alive
            and ally.tank_id != enemy.tank_id
            and (
                grid_cell(ally.position) == current_cell
                or ally.position.distance_to(enemy.position)
                <= TANK_HALF * 2 + max(enemy.speed, ally.speed) * dt + 1.0
            )
        ]
        group = [enemy, *cellmates]
        wait_time = min(self.profile_for(tank).crowd_wait_time for tank in group)
        if not cellmates or max(tank.stationary_timer for tank in group) < wait_time:
            return movement
        if any(self.mine_danger(tank) for tank in group):
            return movement

        center = cell_center(current_cell)
        leader = min(group, key=lambda tank: tank.tank_id)
        maximum_distance = enemy.speed * dt
        if leader.tank_id == enemy.tank_id:
            enemy.detour_timer = 0
            to_center = center - enemy.position
            if to_center.length() > 2.0:
                return to_center.normalize() * min(maximum_distance, to_center.length())
            return movement

        retreat = enemy.position - leader.position
        if retreat.length_squared() == 0:
            retreat = enemy.position - center
        if retreat.length_squared() == 0:
            retreat = -movement
        if retreat.length_squared() == 0:
            retreat = Vec2(1 if enemy.route_seed & 1 else -1, 0)
        enemy.detour_timer = max(enemy.detour_timer, 0.32)
        return retreat.normalize() * maximum_distance

    def abandon_stuck_route(self, enemy: Tank) -> None:
        enemy.avoid_cell = enemy.path[0] if enemy.path else enemy.goal
        enemy.avoid_timer = 1.4
        enemy.route_variant += 1
        enemy.path = []
        enemy.plan_timer = 0
        enemy.stuck_timer = 0
        enemy.net_stuck_timer = 0
        enemy.stationary_timer = 0
        enemy.detour_timer = 0
        enemy.progress_anchor = enemy.position.copy()
        enemy.last_frame_position = enemy.position.copy()

    @staticmethod
    def track_movement_progress(enemy: Tank, dt: float) -> None:
        if enemy.speed <= 0 or dt <= 0:
            return
        if enemy.progress_anchor is None:
            enemy.progress_anchor = enemy.position.copy()
            enemy.last_frame_position = enemy.position.copy()
            return
        if enemy.last_frame_position is not None:
            frame_distance = enemy.position.distance_to(enemy.last_frame_position)
            if frame_distance < max(0.05, enemy.speed * dt * 0.15):
                enemy.stationary_timer += dt
            else:
                enemy.stationary_timer = max(0.0, enemy.stationary_timer - dt * 2)
        enemy.last_frame_position = enemy.position.copy()
        if enemy.position.distance_to(enemy.progress_anchor) >= TILE * 0.25:
            enemy.progress_anchor = enemy.position.copy()
            enemy.net_stuck_timer = 0
        else:
            enemy.net_stuck_timer += dt

    def plan_mine_escape(self, enemy: Tank) -> None:
        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        start = grid_cell(enemy.position)
        active_mines = [mine for mine in self.game.mines if mine.alive]
        if not active_mines:
            enemy.path = []
            enemy.plan_timer = 0.15
            return

        def clearance(cell: tuple[int, int]) -> float:
            position = cell_center(cell)
            return min(position.distance_to(mine.position) for mine in active_mines)

        penalties = self.route_penalties(enemy)
        config = self.settings.global_config
        safe_candidates = []
        for row in range(1, ROWS - 1):
            for col in range(1, COLS - 1):
                cell = (col, row)
                if self.game.world.is_wall(cell):
                    continue
                cell_clearance = clearance(cell)
                if cell_clearance < safe_distance:
                    exposure = (safe_distance - cell_clearance) / TILE
                    penalties[cell] = penalties.get(cell, 0.0) + exposure * config.mine_danger_penalty
                else:
                    safe_candidates.append(cell)

        starting_clearance = min(enemy.position.distance_to(mine.position) for mine in active_mines)

        def transition_safe(
            current: tuple[int, int],
            neighbour: tuple[int, int],
        ) -> bool:
            current_position = enemy.position if current == start else cell_center(current)
            neighbour_position = cell_center(neighbour)
            segment_clearance = min(
                math.sqrt(
                    point_segment_distance_squared(
                        mine.position,
                        current_position,
                        neighbour_position,
                    )
                )
                for mine in active_mines
            )
            return segment_clearance + 0.01 >= starting_clearance

        costs, came_from = self.game.world.navigation_field(
            start,
            penalties=penalties,
            transition_allowed=transition_safe,
        )
        if not any(candidate in costs for candidate in safe_candidates):
            costs, came_from = self.game.world.navigation_field(start, penalties=penalties)
        candidates = []
        for candidate in safe_candidates:
            if candidate not in costs:
                continue
            path = self.game.world.reconstruct_path(start, candidate, came_from)
            if path is None:
                continue
            route_points = [enemy.position, *(cell_center(cell) for cell in path)]
            route_clearance = min(
                (
                    math.sqrt(point_segment_distance_squared(mine.position, start_point, end_point))
                    for mine in active_mines
                    for start_point, end_point in zip(route_points, route_points[1:])
                ),
                default=starting_clearance,
            )
            regression = max(0.0, starting_clearance - route_clearance)
            candidate_clearance = clearance(candidate)
            score = (
                regression > 0.01,
                regression,
                costs[candidate] - candidate_clearance / safe_distance * 0.35,
            )
            candidates.append((score, candidate, path))

        if candidates:
            _, enemy.goal, enemy.path = min(candidates, key=lambda item: item[0])
            if not enemy.path and enemy.position.distance_to(cell_center(enemy.goal)) >= 0.5:
                enemy.path = [enemy.goal]
            enemy.plan_timer = 0.22
            enemy.ai.state = "evade"
            return
        enemy.path = []
        enemy.plan_timer = 0.15

    def _try_plan(self, enemy: Tank, planner: Callable[[Tank], None]) -> bool:
        if self._path_budget is not None:
            if enemy.tank_id in self._planned_this_frame or self._path_budget <= 0:
                return False
            self._path_budget -= 1
            self._planned_this_frame.add(enemy.tank_id)
        planner(enemy)
        return True

    def _steer_away_from_mines(self, enemy: Tank, movement: Vec2) -> Vec2:
        active_mines = [mine for mine in self.game.mines if mine.alive]
        if not active_mines or movement.length_squared() == 0:
            return movement
        current_clearance = min(enemy.position.distance_to(mine.position) for mine in active_mines)
        future_position = enemy.position + movement
        movement_clearance = min(
            math.sqrt(
                point_segment_distance_squared(
                    mine.position,
                    enemy.position,
                    future_position,
                )
            )
            for mine in active_mines
        )
        if (
            movement_clearance + 0.01 >= current_clearance
            and self.game.combat.movement_safe_from_friendly_fire(enemy, movement)
        ):
            return movement
        escape = sum(
            (
                (enemy.position - mine.position).normalize()
                for mine in active_mines
                if enemy.position.distance_squared_to(mine.position) > 0
            ),
            Vec2(),
        )
        if escape.length_squared() == 0:
            return Vec2()
        base_angle = math.atan2(escape.y, escape.x)
        for offset in (0.0, math.pi / 4, -math.pi / 4, math.pi / 2, -math.pi / 2):
            direction = Vec2(math.cos(base_angle + offset), math.sin(base_angle + offset))
            candidate = direction * movement.length()
            if self.game.world.tank_touches_wall(enemy.position + candidate):
                continue
            candidate_position = enemy.position + candidate
            candidate_clearance = min(
                math.sqrt(
                    point_segment_distance_squared(
                        mine.position,
                        enemy.position,
                        candidate_position,
                    )
                )
                for mine in active_mines
            )
            if (
                candidate_clearance + 0.01 >= current_clearance
                and self.game.combat.movement_safe_from_friendly_fire(enemy, candidate)
            ):
                return candidate
        return Vec2()

    def _projectile_segments(
        self,
        bullet: Bullet,
        horizon: float,
    ) -> list[tuple[Vec2, Vec2]]:
        projector = getattr(self.game.combat, "projectile_path_segments", None)
        if projector is not None:
            return projector(bullet, horizon)
        return [(bullet.position, bullet.position + bullet.velocity * horizon)]

    def _dodge_candidate_clearance(
        self,
        enemy: Tank,
        movement: Vec2,
        projectile_segments: list[tuple[Vec2, Vec2]],
    ) -> float:
        destination = enemy.position + movement
        intermediate_positions = []
        if abs(movement.x) > 0.000_001:
            intermediate_positions.append(enemy.position + Vec2(movement.x, 0.0))
        intermediate_positions.append(destination)
        tanks = self.game.all_tanks()
        for position in intermediate_positions:
            if self.game.world.tank_touches_wall(position):
                return -math.inf
            if self.game.world.tank_touches_tank(enemy, position, tanks):
                return -math.inf
        if not self.game.combat.movement_safe_from_friendly_fire(enemy, movement):
            return -math.inf

        mine_clearance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        if any(
            mine.alive
            and point_segment_distance_squared(
                mine.position,
                enemy.position,
                destination,
            )
            < mine_clearance**2
            for mine in self.game.mines
        ):
            return -math.inf
        return min(
            (
                math.sqrt(
                    point_segment_distance_squared(
                        destination,
                        segment_start,
                        segment_end,
                    )
                )
                for segment_start, segment_end in projectile_segments
            ),
            default=math.inf,
        )

    def dodge_incoming_fire(self, enemy: Tank, dt: float) -> Vec2:
        if enemy.speed <= 0.0 or dt <= 0.0:
            return Vec2()
        profile = self.profile_for(enemy)
        trigger_clearance = (
            math.hypot(TANK_HALF, TANK_HALF)
            + BULLET_RADIUS
            + profile.dodge_margin_px
        )
        projectile_segments: list[tuple[Vec2, Vec2]] = []
        imminent: tuple[float, Vec2, Vec2] | None = None

        for bullet in self.game.bullets:
            if (
                not bullet.alive
                or bullet.team == enemy.team
                or bullet.velocity.length_squared() == 0
            ):
                continue
            segments = self._projectile_segments(
                bullet,
                profile.dodge_prediction_time,
            )
            projectile_segments.extend(segments)
            speed = bullet.velocity.length()
            travelled = 0.0
            for segment_start, segment_end in segments:
                segment = segment_end - segment_start
                length_squared = segment.length_squared()
                if length_squared <= 0.000_001:
                    continue
                length = math.sqrt(length_squared)
                ratio = clamp(
                    (enemy.position - segment_start).dot(segment) / length_squared,
                    0.0,
                    1.0,
                )
                closest = segment_start + segment * ratio
                clearance = enemy.position.distance_to(closest)
                time_to_closest = (travelled + ratio * length) / speed
                travelled += length
                if (
                    clearance > trigger_clearance
                    or time_to_closest > profile.dodge_prediction_time
                    or ratio >= 0.999_999
                    or (
                        ratio <= 0.000_001
                        and segment.dot(enemy.position - segment_start) <= 0.0
                        and clearance > TANK_HALF + BULLET_RADIUS
                    )
                ):
                    continue
                threat = (time_to_closest, segment.normalize(), closest)
                if imminent is None or threat[0] < imminent[0]:
                    imminent = threat

        memory = enemy.ai
        if memory.dodge_timer <= 0.0:
            memory.dodge_direction.update(0, 0)
        movement_distance = enemy.speed * profile.dodge_speed_multiplier * dt
        if imminent is None:
            if memory.dodge_timer <= 0.0 or memory.dodge_direction.length_squared() == 0:
                return Vec2()
            committed = memory.dodge_direction.normalize() * movement_distance
            if self._dodge_candidate_clearance(enemy, committed, projectile_segments) > -math.inf:
                return committed
            memory.dodge_timer = 0.0
            memory.dodge_cooldown = max(
                memory.dodge_cooldown,
                profile.dodge_cooldown,
            )
            memory.dodge_direction.update(0, 0)
            return Vec2()
        dodge_speed = enemy.speed * profile.dodge_speed_multiplier
        escape_time = trigger_clearance / dodge_speed if dodge_speed > 0.0 else math.inf
        if (
            memory.dodge_cooldown > 0.0
            and memory.dodge_timer <= 0.0
            and imminent[0] > memory.dodge_cooldown + escape_time
        ):
            return Vec2()

        _, shot_direction, closest_point = imminent
        candidate_directions = []
        if memory.dodge_direction.length_squared() > 0.0:
            candidate_directions.append(memory.dodge_direction.normalize())
        side = 1.0 if enemy.route_seed & 1 else -1.0
        for configured_angle in self.settings.global_config.dodge_candidate_angles_degrees:
            angle = math.atan2(shot_direction.y, shot_direction.x) + math.radians(
                configured_angle * side
            )
            candidate_directions.append(Vec2(math.cos(angle), math.sin(angle)))
        away = enemy.position - closest_point
        if away.length_squared() > 0.0:
            candidate_directions.append(away.normalize())

        current_clearance = min(
            (
                math.sqrt(
                    point_segment_distance_squared(
                        enemy.position,
                        segment_start,
                        segment_end,
                    )
                )
                for segment_start, segment_end in projectile_segments
            ),
            default=math.inf,
        )
        best: tuple[float, float, Vec2] | None = None
        seen: set[tuple[int, int]] = set()
        for direction in candidate_directions:
            if direction.length_squared() == 0.0:
                continue
            direction = direction.normalize()
            key = (round(direction.x * 1000), round(direction.y * 1000))
            if key in seen:
                continue
            seen.add(key)
            movement = direction * movement_distance
            clearance = self._dodge_candidate_clearance(
                enemy,
                movement,
                projectile_segments,
            )
            if clearance <= current_clearance + 0.01:
                continue
            commitment = (
                direction.dot(memory.dodge_direction.normalize())
                if memory.dodge_direction.length_squared() > 0.0
                else 0.0
            )
            score = (
                clearance
                + commitment
                * movement_distance
                * profile.dodge_direction_commitment
            )
            candidate = (score, clearance, movement)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return Vec2()

        movement = best[2]
        memory.dodge_direction = movement.normalize()
        memory.dodge_timer = profile.dodge_commit_time
        memory.dodge_cooldown = 0.0
        enemy.net_stuck_timer = 0.0
        enemy.stationary_timer = 0.0
        enemy.progress_anchor = enemy.position.copy()
        return movement

    def _weapon_ready(self, enemy: Tank) -> bool:
        can_shoot = getattr(self.game.combat, "can_shoot", None)
        if can_shoot is not None:
            return bool(can_shoot(enemy))
        return (
            enemy.alive
            and enemy.cooldown <= 0.0
            and enemy.shot_think_timer <= 0.0
            and self.game.combat.active_bullets(enemy) < enemy.max_bullets
        )

    def _standalone_context(self, enemy: Tank) -> EnemyUpdateContext:
        target = self.game.player.position.copy()
        perception = PerceptionSnapshot(
            target_position=target,
            target_visible=True,
            has_line_of_sight=True,
            can_engage=True,
            heard_contact=False,
            remembered_contact=True,
            just_confirmed=False,
        )
        decision = TacticalDecision("attack", target, 0.0, True)
        return EnemyUpdateContext(self.profile_for(enemy), perception, decision)

    def update_enemy(
        self,
        enemy: Tank,
        dt: float,
        context: EnemyUpdateContext | None = None,
    ) -> None:
        managed_update = context is not None
        context = context or self._standalone_context(enemy)
        profile = context.profile
        enemy.fire_timer -= dt
        enemy.mine_timer -= dt
        enemy.plan_timer -= dt
        enemy.aim_timer -= dt
        enemy.detour_timer = max(0.0, enemy.detour_timer - dt)
        previous_dodge_timer = enemy.ai.dodge_timer
        enemy.ai.dodge_timer = max(0.0, enemy.ai.dodge_timer - dt)
        enemy.ai.dodge_cooldown = max(0.0, enemy.ai.dodge_cooldown - dt)
        if previous_dodge_timer > 0.0 and enemy.ai.dodge_timer <= 0.0:
            enemy.ai.dodge_direction.update(0, 0)
            enemy.ai.dodge_cooldown = max(
                enemy.ai.dodge_cooldown,
                profile.dodge_cooldown,
            )
        enemy.avoid_timer = max(0.0, enemy.avoid_timer - dt)
        if enemy.avoid_timer == 0:
            enemy.avoid_cell = None
        mine_danger = self.mine_danger(enemy)
        dodge_movement = Vec2() if mine_danger else self.dodge_incoming_fire(enemy, dt)
        is_dodging = dodge_movement.length_squared() > 0.0
        if is_dodging:
            enemy.net_stuck_timer = 0.0
            enemy.stationary_timer = 0.0
            enemy.progress_anchor = enemy.position.copy()
        else:
            self.track_movement_progress(enemy, dt)
            if enemy.net_stuck_timer >= profile.net_stuck_timeout:
                self.abandon_stuck_route(enemy)
        has_active_bullet = self.game.combat.active_bullets(enemy) >= enemy.max_bullets
        target_position = (
            context.decision.target_position
            or enemy.ai.navigation_target
            or self.game.player.position
        )
        target_cell = grid_cell(target_position)
        goal_distance = (
            math.inf
            if enemy.goal is None
            else abs(enemy.goal[0] - target_cell[0])
            + abs(enemy.goal[1] - target_cell[1])
        )
        goal_outdated = context.decision.state in {"attack", "flank"} and not (
            profile.min_distance_tiles <= goal_distance <= profile.max_distance_tiles
        )
        route_unsafe = enemy.plan_timer <= 0 and self.route_has_mine_danger(enemy)
        if enemy.speed > 0:
            if mine_danger and (
                not enemy.escaping_mines or not enemy.path or route_unsafe
            ):
                self._try_plan(enemy, self.plan_mine_escape)
            elif not mine_danger and (
                enemy.escaping_mines
                or not enemy.path
                or route_unsafe
                or (enemy.plan_timer <= 0 and goal_outdated)
            ):
                self._try_plan(enemy, self.plan_path)
        if mine_danger:
            enemy.detour_timer = 0
        enemy.escaping_mines = mine_danger

        movement = dodge_movement
        if enemy.speed > 0 and not is_dodging:
            for attempt in range(2):
                while enemy.path:
                    target_position = cell_center(enemy.path[0])
                    difference = target_position - enemy.position
                    current_cell = grid_cell(enemy.position)
                    shares_cell = any(
                        ally.alive
                        and ally.tank_id != enemy.tank_id
                        and grid_cell(ally.position) == current_cell
                        for ally in self.game.enemies
                    )
                    arrival_distance = 0.5 if mine_danger else TILE / 2 - TANK_HALF
                    if current_cell == enemy.path[0] and shares_cell and not mine_danger:
                        enemy.path.pop(0)
                        enemy.plan_timer = 0
                        continue
                    if difference.length() >= arrival_distance:
                        movement = difference.normalize() * min(
                            enemy.speed * dt,
                            difference.length(),
                        )
                        break
                    enemy.path.pop(0)
                    enemy.plan_timer = 0
                if enemy.path or attempt > 0:
                    break
                if mine_danger:
                    planned = self._try_plan(enemy, self.plan_mine_escape)
                else:
                    planned = self._try_plan(enemy, self.plan_path)
                if not planned:
                    break

        if (
            enemy.detour_timer > 0
            and not mine_danger
            and not is_dodging
            and enemy.velocity.length_squared() > 0
        ):
            movement = enemy.velocity.normalize() * enemy.speed * dt
        if not mine_danger and not is_dodging:
            movement = self.coordinate_crowded_cell(enemy, movement, dt)
        movement = self.steer_around_friendly_fire(enemy, movement)
        if mine_danger:
            movement = self._steer_away_from_mines(enemy, movement)

        waypoint = cell_center(enemy.path[0]) if enemy.path else None
        waypoint_distance = (
            enemy.position.distance_to(waypoint) if waypoint is not None else math.inf
        )
        starting_position = enemy.position.copy()
        actual_movement = self.move_enemy(enemy, movement) if movement.length_squared() > 0 else Vec2()
        expected_distance = movement.length()
        if (
            expected_distance > 0
            and not is_dodging
            and actual_movement.length() < expected_distance * 0.2
        ):
            base_angle = math.atan2(movement.y, movement.x)
            side = 1 if (enemy.route_seed + enemy.route_variant) & 1 else -1
            detour_succeeded = False
            for offset in (side * math.pi / 2, -side * math.pi / 2, math.pi):
                travelled = enemy.position.distance_to(starting_position)
                remaining = expected_distance - travelled
                if remaining <= 0.000_001:
                    break
                angle = base_angle + offset
                detour = Vec2(math.cos(angle), math.sin(angle)) * remaining
                detour = self.steer_around_friendly_fire(enemy, detour)
                if mine_danger:
                    detour = self._steer_away_from_mines(enemy, detour)
                if self.game.world.tank_touches_wall(enemy.position + detour):
                    continue
                detour_start = enemy.position.copy()
                self.move_enemy(enemy, detour)
                if enemy.position.distance_to(detour_start) > 0.000_001:
                    enemy.detour_timer = 0.24
                    detour_succeeded = True
                    break
            if not detour_succeeded:
                enemy.detour_timer = 0
            actual_movement = enemy.position - starting_position
        if dt > 0:
            enemy.velocity = actual_movement / dt
        current_cell = grid_cell(enemy.position)
        if not enemy.recent_cells or enemy.recent_cells[-1] != current_cell:
            enemy.recent_cells.append(current_cell)
            del enemy.recent_cells[:-12]
        if dt > 0:
            if is_dodging:
                enemy.stuck_timer = max(0.0, enemy.stuck_timer - dt * 2.0)
            elif movement.length_squared() > 0:
                made_progress = (
                    waypoint is None
                    or enemy.position.distance_to(waypoint) < waypoint_distance - 0.05
                )
                if actual_movement.length() < expected_distance * 0.2 or not made_progress:
                    enemy.stuck_timer += dt
                else:
                    enemy.stuck_timer = max(0.0, enemy.stuck_timer - dt * 2)
            else:
                enemy.stuck_timer = 0.0

        if enemy.stuck_timer >= profile.local_stuck_timeout:
            self.abandon_stuck_route(enemy)
        if actual_movement.length_squared() > 0:
            move_angle = math.atan2(actual_movement.y, actual_movement.x)
            enemy.body_angle = turn_towards(
                enemy.body_angle,
                move_angle,
                profile.body_turn_speed * dt,
            )
        elif movement.length_squared() > 0:
            enemy.plan_timer = 0.0

        if (
            enemy.max_mines > 0
            and enemy.mine_timer <= 0
            and not mine_danger
            and (not managed_update or context.perception.target_position is not None)
            and self.allies_safe_from_new_mine(enemy)
        ):
            if self.game.mine_system.place(enemy):
                enemy.mine_timer = profile.mine_interval_min + random.random() * (
                    profile.mine_interval_max - profile.mine_interval_min
                )
                enemy.plan_timer = 0
            else:
                enemy.mine_timer = self.settings.global_config.mine_retry_interval

        direct_aim = self.game.player.position - enemy.position
        if direct_aim.length_squared() == 0:
            return
        direct_angle = math.atan2(direct_aim.y, direct_aim.x)

        if (
            not context.perception.target_visible
            and not self.settings.global_config.omniscient_player_tracking
        ):
            if context.perception.target_position is not None:
                search_aim = context.perception.target_position - enemy.position
                desired_angle = (
                    math.atan2(search_aim.y, search_aim.x)
                    if search_aim.length_squared() > 0
                    else enemy.body_angle
                )
            else:
                scan_phase = self._now * profile.scan_speed + (enemy.route_seed & 0xFF) / 255.0 * math.tau
                desired_angle = enemy.body_angle + math.sin(scan_phase) * math.radians(profile.scan_arc_degrees) * 0.5
            enemy.aim_angle = desired_angle
            enemy.shot_ready = False
            enemy.turret_angle = turn_towards(
                enemy.turret_angle,
                desired_angle,
                profile.turret_turn_speed * dt,
            )
            return

        weapon_ready = (
            not has_active_bullet
            and enemy.fire_timer <= 0.0
            and self._weapon_ready(enemy)
            and context.decision.can_engage
        )
        needs_solution = enemy.aim_timer <= 0 or enemy.aim_angle is None
        has_attack_slot = True
        if managed_update and weapon_ready:
            shot_budget_available = (
                not needs_solution
                or self._shot_budget is None
                or self._shot_budget > 0
            )
            has_attack_slot = (
                self.squad.request_attack_slot(enemy, self._now)
                if shot_budget_available and (enemy.shot_ready or needs_solution)
                else False
            )

        if not weapon_ready or not has_attack_slot:
            enemy.aim_angle = direct_angle
            enemy.shot_ready = False
        elif needs_solution:
            if managed_update and self._shot_budget is not None:
                self._shot_budget -= 1
            predictive_profile = (
                profile.predictive_aim_enabled
                and self.game.player.velocity.length()
                >= profile.prediction_min_target_speed
            )
            predictive_budget_available = (
                not managed_update
                or self._predictive_shot_budget is None
                or self._predictive_shot_budget > 0
            )
            if predictive_profile and not predictive_budget_available:
                enemy.aim_angle = direct_angle
                enemy.shot_ready = False
            else:
                if (
                    managed_update
                    and predictive_profile
                    and self._predictive_shot_budget is not None
                ):
                    self._predictive_shot_budget -= 1
                enemy.aim_angle, enemy.shot_ready = self.choose_shot(enemy)
            enemy.aim_timer = profile.aim_interval
            if managed_update and not enemy.shot_ready:
                self.squad.release_attack_slot(enemy.tank_id)

        desired_angle = enemy.aim_angle if enemy.aim_angle is not None else direct_angle
        enemy.turret_angle = turn_towards(
            enemy.turret_angle,
            desired_angle,
            profile.turret_turn_speed * dt,
        )
        aim_tolerance = math.radians(profile.aim_tolerance_degrees)
        turret_ready = abs(angle_difference(desired_angle, enemy.turret_angle)) < aim_tolerance

        if enemy.fire_timer <= 0 and enemy.shot_ready and turret_ready:
            prediction = (
                self.target_prediction(enemy, ignore_speed_threshold=True)
                if enemy.ai.aim_predictive
                else None
            )
            predictive_target = (
                prediction.position_at
                if prediction is not None
                else (
                    (lambda _time: self.game.player.position.copy())
                    if enemy.ai.aim_predictive
                    else None
                )
            )
            safety_check = self.game.combat.trace_shot(
                enemy,
                enemy.turret_angle,
                self.game.player,
                **(
                    {"target_position_at": predictive_target}
                    if predictive_target is not None
                    else {}
                ),
            )
            predictive_target_lost = (
                enemy.ai.aim_predictive
                and (
                    predictive_target is None
                    or (
                        enemy.ai.aim_requires_hit
                        and not safety_check.target_hit
                    )
                    or (
                        enemy.ai.aim_requires_hit
                        and
                        enemy.ai.aim_expected_bounces >= 0
                        and safety_check.target_bounces
                        != enemy.ai.aim_expected_bounces
                    )
                )
            )
            if (
                safety_check.self_hit
                or safety_check.ally_hit
                or predictive_target_lost
            ):
                if managed_update:
                    self.squad.release_attack_slot(enemy.tank_id)
                enemy.aim_timer = 0
                enemy.shot_ready = False
                enemy.ai.aim_predictive = False
                enemy.ai.aim_requires_hit = False
                enemy.ai.aim_expected_bounces = -1
                return
        if enemy.fire_timer <= 0 and enemy.shot_ready and turret_ready and self.game.combat.shoot(enemy):
            enemy.fire_timer = FIRE_RATE_DELAYS[enemy.fire_rate]
            enemy.aim_timer = 0
            enemy.shot_ready = False
            enemy.ai.aim_predictive = False
            enemy.ai.aim_requires_hit = False
            enemy.ai.aim_expected_bounces = -1

    def allies_safe_from_new_mine(self, enemy: Tank) -> bool:
        danger_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        for ally in self.game.enemies:
            if not ally.alive or ally.tank_id == enemy.tank_id:
                continue
            future_positions = [ally.position, *(cell_center(cell) for cell in ally.path[:3])]
            if any(position.distance_to(enemy.position) <= danger_distance for position in future_positions):
                return False
            if any(
                point_segment_distance_squared(enemy.position, start, end) <= danger_distance**2
                for start, end in zip(future_positions, future_positions[1:])
            ):
                return False
        return True

    def update(self, dt: float) -> None:
        if not self.game.player.alive:
            return
        self._now += dt
        self.perception.begin_frame(dt)
        alive_enemies = [enemy for enemy in self.game.enemies if enemy.alive]
        self.squad.begin_frame(
            alive_enemies,
            self._now,
            self.profile_for,
        )
        self.game.combat.prepare_friendly_fire_paths("enemy")
        self._path_budget = self.settings.global_config.max_path_plans_per_frame
        self._shot_budget = self.settings.global_config.max_shot_plans_per_frame
        self._predictive_shot_budget = (
            self.settings.global_config.max_predictive_shot_plans_per_frame
        )
        self._planned_this_frame.clear()
        if alive_enemies:
            start = self._update_cursor % len(alive_enemies)
            ordered_enemies = alive_enemies[start:] + alive_enemies[:start]
            self._update_cursor = (
                start + 1
            ) % len(alive_enemies)
        else:
            ordered_enemies = []
        try:
            for enemy in ordered_enemies:
                profile = self.profile_for(enemy)
                perception = self.perception.update(
                    enemy,
                    self.game.player,
                    profile,
                    dt,
                )
                if perception.target_visible:
                    self.squad.share_contact(
                        enemy,
                        alive_enemies,
                        self._now,
                        self.profile_for,
                    )
                decision = self.decisions.update(enemy, profile, perception, dt)
                self.update_enemy(
                    enemy,
                    dt,
                    EnemyUpdateContext(profile, perception, decision),
                )
        finally:
            self._path_budget = None
            self._shot_budget = None
            self._predictive_shot_budget = None
            self._planned_this_frame.clear()
