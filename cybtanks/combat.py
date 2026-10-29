from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

from .config import (
    BOARD_HEIGHT,
    BOARD_WIDTH,
    BULLET_RADIUS,
    FIRE_RATE_DELAYS,
    MINE_COLLISION_RADIUS,
    PLAYER_MIN_RICOCHET_DISTANCE,
    SHIELD_FLASH_DURATION,
    SHOT_THINK_DELAYS,
    TANK_HALF,
)
from .geometry import (
    clamp,
    point_segment_distance_squared,
    segment_distance_squared,
)
from .models import Bullet, ShotTrace, Tank, Vec2
from .world import cell_center

if TYPE_CHECKING:
    from .game import Game


SHOT_TRACE_STEP = 3.0
FRIENDLY_FIRE_CLEARANCE = math.hypot(TANK_HALF, TANK_HALF) + BULLET_RADIUS + 5.0


class CombatSystem:
    def __init__(self, game: Game) -> None:
        self.game = game
        self._friendly_fire_paths: dict[int, list[tuple[Vec2, Vec2]]] = {}
        self._ally_route_cache: dict[
            int,
            tuple[tuple[float, float, tuple[tuple[int, int], ...]], list[tuple[Vec2, Vec2]]],
        ] = {}
        self._projectile_path_cache: dict[
            tuple[int, float],
            tuple[
                tuple[float, float, float, float, int, float, float],
                list[tuple[Vec2, Vec2]],
            ],
        ] = {}

    def active_bullets(self, tank: Tank) -> int:
        return sum(bullet.alive and bullet.owner_id == tank.tank_id for bullet in self.game.bullets)

    def can_shoot(self, tank: Tank) -> bool:
        return (
            tank.alive
            and tank.cooldown <= 0
            and tank.shot_think_timer <= 0
            and getattr(self.game, "state", "playing") == "playing"
            and self.active_bullets(tank) < tank.max_bullets
        )

    def start_shot_think_timer(self, owner_id: int) -> None:
        owner = next(
            (tank for tank in self.game.all_tanks() if tank.tank_id == owner_id),
            None,
        )
        if owner is not None:
            owner.shot_think_timer = max(
                owner.shot_think_timer,
                SHOT_THINK_DELAYS[owner.shot_think_speed],
            )

    def destroy_bullet(self, bullet: Bullet, amount: int = 5, force: float = 55) -> bool:
        if not bullet.alive:
            return False
        bullet.alive = False
        self.game.create_burst(bullet.position, bullet.color, amount, force)
        self.game.audio.play_bullet_disintegrate()
        self.start_shot_think_timer(bullet.owner_id)
        return True

    @staticmethod
    def circle_touches_tank(position: Vec2, tank: Tank) -> bool:
        return CombatSystem.circle_touches_tank_position(position, tank.position)

    @staticmethod
    def circle_touches_tank_position(position: Vec2, tank_position: Vec2) -> bool:
        nearest_x = clamp(position.x, tank_position.x - TANK_HALF, tank_position.x + TANK_HALF)
        nearest_y = clamp(position.y, tank_position.y - TANK_HALF, tank_position.y + TANK_HALF)
        return position.distance_squared_to((nearest_x, nearest_y)) <= BULLET_RADIUS**2

    def safe_muzzle(self, tank: Tank, angle: float | None = None) -> Vec2:
        angle = tank.turret_angle if angle is None else angle
        direction = Vec2(math.cos(angle), math.sin(angle))
        result = tank.position.copy()
        for distance in range(4, 27, 3):
            candidate = tank.position + direction * distance
            if self.game.world.circle_touches_wall(candidate):
                break
            result = candidate
        return result

    def shoot(self, tank: Tank) -> bool:
        if not self.can_shoot(tank):
            return False
        direction = Vec2(math.cos(tank.turret_angle), math.sin(tank.turret_angle))
        muzzle = self.safe_muzzle(tank)
        self.game.bullets.append(
            Bullet(
                position=muzzle,
                velocity=direction * tank.bullet_speed,
                team=tank.team,
                owner_id=tank.tank_id,
                color=(187, 233, 241) if tank.team == "player" else (220, 211, 174),
                speed_class=tank.bullet_speed_class,
                max_bounces=tank.max_bounces,
            )
        )
        tank.cooldown = FIRE_RATE_DELAYS[tank.fire_rate]
        self.game.create_burst(muzzle, tank.color, 4, 55)
        self.game.audio.play_shot(tank.bullet_speed_class)
        report_sound = getattr(self.game, "report_ai_sound", None)
        if report_sound is not None:
            report_sound(muzzle, f"shot_{tank.bullet_speed_class}", tank.team)
        return True

    def _shot_trajectory(
        self,
        position: Vec2,
        direction: Vec2,
        max_bounces: int,
        bounces: int = 0,
        max_distance: float | None = None,
    ) -> Iterator[tuple[Vec2, int, float]]:
        if direction.length_squared() == 0:
            return
        position = position.copy()
        direction = direction.normalize()
        max_steps = math.ceil(
            math.hypot(BOARD_WIDTH, BOARD_HEIGHT)
            * (max_bounces + 1.4)
            / SHOT_TRACE_STEP
        )

        for step_index in range(max_steps):
            distance = (step_index + 1) * SHOT_TRACE_STEP
            if max_distance is not None and distance > max_distance:
                return
            next_x = Vec2(position.x + direction.x * SHOT_TRACE_STEP, position.y)
            if self.game.world.circle_touches_wall(next_x):
                if bounces >= max_bounces:
                    return
                direction.x *= -1
                bounces += 1
            else:
                position.x = next_x.x

            next_y = Vec2(position.x, position.y + direction.y * SHOT_TRACE_STEP)
            if self.game.world.circle_touches_wall(next_y):
                if bounces >= max_bounces:
                    return
                direction.y *= -1
                bounces += 1
            else:
                position.y = next_y.y

            yield position.copy(), bounces, distance

    def ally_route_touches_shot(self, position: Vec2, ally: Tank) -> bool:
        clearance_squared = FRIENDLY_FIRE_CLEARANCE**2
        if position.distance_squared_to(ally.position) <= clearance_squared:
            return True

        for route_start, route_end in self._ally_route_segments(ally):
            if (
                point_segment_distance_squared(position, route_start, route_end)
                <= clearance_squared
            ):
                return True
        return False

    def _ally_route_segments(self, ally: Tank) -> list[tuple[Vec2, Vec2]]:
        signature = (
            round(ally.position.x, 3),
            round(ally.position.y, 3),
            tuple(ally.path[:3]),
        )
        cached = self._ally_route_cache.get(ally.tank_id)
        if cached is not None and cached[0] == signature:
            return cached[1]
        points = [ally.position.copy(), *(cell_center(cell) for cell in ally.path[:3])]
        segments = list(zip(points, points[1:]))
        self._ally_route_cache[ally.tank_id] = (signature, segments)
        return segments

    def _route_conflicts_with_shot(
        self,
        shot_segments: list[tuple[Vec2, Vec2, int]],
        ally: Tank,
        *,
        after_bounce: bool = False,
    ) -> bool:
        clearance_squared = FRIENDLY_FIRE_CLEARANCE**2
        route_segments = self._ally_route_segments(ally)
        for shot_start, shot_end, bounces in shot_segments:
            if after_bounce and bounces <= 0:
                continue
            if point_segment_distance_squared(ally.position, shot_start, shot_end) <= clearance_squared:
                return True
            if any(
                segment_distance_squared(shot_start, shot_end, route_start, route_end)
                <= clearance_squared
                for route_start, route_end in route_segments
            ):
                return True
        return False

    def trace_shot(
        self,
        shooter: Tank,
        angle: float,
        target: Tank,
        *,
        target_position_at: Callable[[float], Vec2 | None] | None = None,
    ) -> ShotTrace:
        trace = ShotTrace()
        position = self.safe_muzzle(shooter, angle)
        direction = Vec2(math.cos(angle), math.sin(angle))
        left_owner = not self.circle_touches_tank(position, shooter)
        segment_start = position.copy()
        previous = position.copy()
        previous_bounces = 0
        shot_segments: list[tuple[Vec2, Vec2, int]] = []
        target_result: tuple[int, float] | None = None

        for position, bounces, distance in self._shot_trajectory(
            position,
            direction,
            shooter.max_bounces,
        ):
            if bounces != previous_bounces:
                if segment_start.distance_squared_to(previous) > 0:
                    shot_segments.append((segment_start, previous, previous_bounces))
                segment_start = previous.copy()
                previous_bounces = bounces
            touches_owner = self.circle_touches_tank(position, shooter)
            if not touches_owner:
                left_owner = True
            elif left_owner or bounces > 0:
                trace.self_hit = True
                return trace

            target_position = (
                target_position_at(distance / shooter.bullet_speed)
                if target_position_at is not None and shooter.bullet_speed > 0.0
                else target.position
            )
            if (
                target.alive
                and target_position is not None
                and self.circle_touches_tank_position(position, target_position)
            ):
                target_result = (bounces, distance)
                previous = position.copy()
                break
            previous = position.copy()

        if segment_start.distance_squared_to(previous) > 0:
            shot_segments.append((segment_start, previous, previous_bounces))
        if self._route_conflicts_with_shot(shot_segments, shooter, after_bounce=True):
            trace.self_hit = True
            return trace
        for ally in self.game.enemies:
            if (
                not ally.alive
                or ally.team != shooter.team
                or ally.tank_id == shooter.tank_id
            ):
                continue
            if self._route_conflicts_with_shot(shot_segments, ally):
                trace.ally_hit = True
                return trace
        if target_result is not None:
            trace.target_hit = True
            trace.target_bounces, trace.target_distance = target_result

        return trace

    @staticmethod
    def _segment_circle_entry_ratio(
        start: Vec2,
        end: Vec2,
        center: Vec2,
        radius: float,
    ) -> float | None:
        segment = end - start
        length_squared = segment.length_squared()
        if length_squared <= 0.000_001:
            return 0.0 if start.distance_squared_to(center) <= radius**2 else None
        projection = clamp((center - start).dot(segment) / length_squared, 0.0, 1.0)
        closest = start + segment * projection
        perpendicular_squared = closest.distance_squared_to(center)
        if perpendicular_squared > radius**2:
            return None
        half_chord = math.sqrt(max(0.0, radius**2 - perpendicular_squared))
        return clamp(
            projection - half_chord / math.sqrt(length_squared),
            0.0,
            1.0,
        )

    def _projected_bullet_collision_ratio(
        self,
        bullet: Bullet,
        start: Vec2,
        end: Vec2,
        start_time: float,
        end_time: float,
    ) -> float | None:
        duration = end_time - start_time
        if duration <= 0.000_001:
            return None
        segment_velocity = (end - start) / duration
        earliest: float | None = None
        for other in getattr(self.game, "bullets", ()):
            if other is bullet or not other.alive or other.velocity.length_squared() == 0:
                continue
            if (
                other.owner_id == bullet.owner_id
                and segment_velocity.dot(other.velocity) > 0
            ):
                continue
            relative_start = start - (other.position + other.velocity * start_time)
            relative_velocity = segment_velocity - other.velocity
            relative_speed_squared = relative_velocity.length_squared()
            local_time = (
                clamp(
                    -relative_start.dot(relative_velocity) / relative_speed_squared,
                    0.0,
                    duration,
                )
                if relative_speed_squared > 0.000_001
                else 0.0
            )
            collision_time = start_time + local_time
            first_position = start + segment_velocity * local_time
            other_position = other.position + other.velocity * collision_time
            if not self.game.world.clear_segment(
                other.position,
                other_position,
                BULLET_RADIUS,
            ):
                continue
            first_direction = segment_velocity.normalize()
            other_direction = other.velocity.normalize()
            if (
                segment_distance_squared(
                    first_position - first_direction * 6.0,
                    first_position + first_direction * 8.0,
                    other_position - other_direction * 6.0,
                    other_position + other_direction * 8.0,
                )
                > (BULLET_RADIUS * 2.0) ** 2
            ):
                continue
            ratio = local_time / duration
            earliest = ratio if earliest is None else min(earliest, ratio)
        return earliest

    def _clip_projectile_segments(
        self,
        bullet: Bullet,
        segments: list[tuple[Vec2, Vec2, int]],
    ) -> list[tuple[Vec2, Vec2]]:
        speed = bullet.velocity.length()
        if speed <= 0.0:
            return []
        all_tanks = getattr(self.game, "all_tanks", None)
        tanks = (
            all_tanks()
            if all_tanks is not None
            else [
                *([self.game.player] if hasattr(self.game, "player") else []),
                *getattr(self.game, "enemies", ()),
            ]
        )
        elapsed = 0.0
        result = []
        for start, end, bounces in segments:
            length = start.distance_to(end)
            if length <= 0.000_001:
                continue
            duration = length / speed
            terminal_ratio = 1.0
            for tank in tanks:
                if not tank.alive or tank.speed > 0.0:
                    continue
                collision_ratio = self._segment_circle_entry_ratio(
                    start,
                    end,
                    tank.position,
                    math.hypot(TANK_HALF, TANK_HALF) + BULLET_RADIUS,
                )
                if collision_ratio is None:
                    continue
                predicted_age = bullet.age + elapsed + collision_ratio * duration
                if (
                    tank.tank_id == bullet.owner_id
                    and bounces == 0
                    and predicted_age < 0.14
                ):
                    continue
                terminal_ratio = min(terminal_ratio, collision_ratio)
            for mine in getattr(self.game, "mines", ()):
                if not mine.alive:
                    continue
                collision_ratio = self._segment_circle_entry_ratio(
                    start,
                    end,
                    mine.position,
                    MINE_COLLISION_RADIUS + BULLET_RADIUS,
                )
                if collision_ratio is not None:
                    terminal_ratio = min(terminal_ratio, collision_ratio)
            bullet_collision = self._projected_bullet_collision_ratio(
                bullet,
                start,
                end,
                elapsed,
                elapsed + duration,
            )
            if bullet_collision is not None:
                terminal_ratio = min(terminal_ratio, bullet_collision)

            clipped_end = start + (end - start) * terminal_ratio
            if start.distance_squared_to(clipped_end) > 0.000_001:
                result.append((start, clipped_end))
            if terminal_ratio < 1.0:
                break
            elapsed += duration
        return result

    def projectile_path_segments(
        self,
        bullet: Bullet,
        horizon: float | None = None,
    ) -> list[tuple[Vec2, Vec2]]:
        cache_key = (id(bullet), -1.0 if horizon is None else round(horizon, 3))
        signature = (
            round(bullet.position.x, 3),
            round(bullet.position.y, 3),
            round(bullet.velocity.x, 3),
            round(bullet.velocity.y, 3),
            bullet.bounces,
            round(bullet.distance_travelled, 3),
            round(bullet.age, 3),
        )
        cached = self._projectile_path_cache.get(cache_key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        segment_start = bullet.position.copy()
        previous = segment_start
        previous_bounces = bullet.bounces
        geometric_segments: list[tuple[Vec2, Vec2, int]] = []
        max_distance = bullet.velocity.length() * horizon if horizon is not None else None
        for position, bounces, distance in self._shot_trajectory(
            bullet.position,
            bullet.velocity,
            bullet.max_bounces,
            bullet.bounces,
            max_distance,
        ):
            if bounces != previous_bounces:
                if segment_start.distance_squared_to(previous) > 0:
                    geometric_segments.append(
                        (segment_start, previous, previous_bounces)
                    )
                if (
                    bullet.team == "player"
                    and previous_bounces == 0
                    and bullet.distance_travelled
                    + max(0.0, distance - SHOT_TRACE_STEP)
                    < PLAYER_MIN_RICOCHET_DISTANCE
                ):
                    break
                segment_start = previous
                previous_bounces = bounces
            previous = position

        if segment_start.distance_squared_to(previous) > 0:
            geometric_segments.append((segment_start, previous, previous_bounces))
        segments = self._clip_projectile_segments(bullet, geometric_segments)
        self._projectile_path_cache[cache_key] = (signature, segments)
        return segments

    def _bullet_path_segments(self, bullet: Bullet) -> list[tuple[Vec2, Vec2]]:
        settings = getattr(self.game, "ai_settings", None)
        horizon = (
            settings.global_config.friendly_fire_horizon
            if settings is not None
            else None
        )
        return self.projectile_path_segments(bullet, horizon)

    def prepare_friendly_fire_paths(self, team: str) -> None:
        self._ally_route_cache.clear()
        self._projectile_path_cache.clear()
        for tank in self.game.enemies:
            if tank.alive and tank.team == team:
                self._ally_route_segments(tank)
        self._friendly_fire_paths = {
            id(bullet): self._bullet_path_segments(bullet)
            for bullet in self.game.bullets
            if bullet.alive and bullet.team == team
        }

    def movement_safe_from_friendly_fire(self, tank: Tank, movement: Vec2) -> bool:
        if movement.length_squared() == 0:
            return True

        start = tank.position
        destination = start + movement
        clearance_squared = FRIENDLY_FIRE_CLEARANCE**2
        for bullet in self.game.bullets:
            if (
                not bullet.alive
                or bullet.team != tank.team
                or bullet.velocity.length_squared() == 0
            ):
                continue

            nearest_start = start.distance_squared_to(bullet.position)
            nearest_destination = destination.distance_squared_to(bullet.position)
            nearest_movement = point_segment_distance_squared(
                bullet.position,
                start,
                destination,
            )
            path = self._friendly_fire_paths.get(id(bullet))
            if path is None:
                path = self._bullet_path_segments(bullet)
                self._friendly_fire_paths[id(bullet)] = path
            for shot_start, shot_end in path:
                nearest_start = min(
                    nearest_start,
                    point_segment_distance_squared(start, shot_start, shot_end),
                )
                nearest_destination = min(
                    nearest_destination,
                    point_segment_distance_squared(
                        destination,
                        shot_start,
                        shot_end,
                    ),
                )
                nearest_movement = min(
                    nearest_movement,
                    segment_distance_squared(
                        start,
                        destination,
                        shot_start,
                        shot_end,
                    ),
                )

            if nearest_movement > clearance_squared:
                continue
            if (
                nearest_start <= clearance_squared
                and nearest_destination > nearest_start
                and nearest_movement >= nearest_start - 0.000_001
            ):
                continue
            return False
        return True

    def friendly_fire_destination_clearance(self, tank: Tank, movement: Vec2) -> float:
        destination = tank.position + movement
        nearest = math.inf
        for bullet in self.game.bullets:
            if (
                not bullet.alive
                or bullet.team != tank.team
                or bullet.velocity.length_squared() == 0
            ):
                continue

            nearest = min(nearest, destination.distance_squared_to(bullet.position))
            path = self._friendly_fire_paths.get(id(bullet))
            if path is None:
                path = self._bullet_path_segments(bullet)
                self._friendly_fire_paths[id(bullet)] = path
            for shot_start, shot_end in path:
                nearest = min(
                    nearest,
                    point_segment_distance_squared(
                        destination,
                        shot_start,
                        shot_end,
                    ),
                )
        return nearest

    @staticmethod
    def bullets_touch(first: Bullet, second: Bullet) -> bool:
        first_direction = first.velocity.normalize() if first.velocity.length_squared() else Vec2(1, 0)
        second_direction = second.velocity.normalize() if second.velocity.length_squared() else Vec2(1, 0)
        first_start = first.position - first_direction * 6
        first_end = first.position + first_direction * 8
        second_start = second.position - second_direction * 6
        second_end = second.position + second_direction * 8
        return segment_distance_squared(first_start, first_end, second_start, second_end) <= (BULLET_RADIUS * 2) ** 2

    def reflect_bullet(self, bullet: Bullet, axis: str) -> bool:
        if bullet.bounces >= bullet.max_bounces:
            bullet.alive = False
            self.game.create_burst(bullet.position, bullet.color, 7, 75)
            self.game.audio.play_bullet_disintegrate()
            return False
        bullet.bounces += 1
        if axis == "x":
            bullet.velocity.x *= -1
        else:
            bullet.velocity.y *= -1
        self.game.create_burst(bullet.position, bullet.color, 5, 58)
        self.game.audio.play_bullet_bounce()
        return True

    def break_close_player_bullet(self, bullet: Bullet, travelled: float) -> bool:
        if (
            bullet.team != "player"
            or bullet.bounces > 0
            or travelled >= PLAYER_MIN_RICOCHET_DISTANCE
        ):
            return False
        bullet.alive = False
        self.game.create_burst(bullet.position, bullet.color, 8, 78)
        self.game.audio.play_bullet_disintegrate()
        return True

    def hit_tank(self, tank: Tank) -> None:
        if tank.shield_hits <= 0:
            self.game.destroy_tank(tank)
            return
        tank.shield_hits -= 1
        tank.shield_flash = SHIELD_FLASH_DURATION
        self.game.create_burst(tank.position, (117, 211, 255), 18, 115)
        self.game.create_burst(tank.position, (224, 247, 255), 8, 75)

    def move_bullet_step(self, bullet: Bullet) -> None:
        if bullet.velocity.length_squared() == 0:
            return

        direction = bullet.velocity.normalize()
        step_start = bullet.position.copy()
        next_x = Vec2(
            bullet.position.x + direction.x * SHOT_TRACE_STEP,
            bullet.position.y,
        )
        if self.game.world.circle_touches_wall(next_x):
            if self.break_close_player_bullet(bullet, bullet.distance_travelled):
                return
            if not self.reflect_bullet(bullet, "x"):
                return
        else:
            bullet.position.x = next_x.x

        next_y = Vec2(
            bullet.position.x,
            bullet.position.y + direction.y * SHOT_TRACE_STEP,
        )
        if self.game.world.circle_touches_wall(next_y):
            travelled = bullet.distance_travelled + step_start.distance_to(bullet.position)
            if self.break_close_player_bullet(bullet, travelled):
                return
            if not self.reflect_bullet(bullet, "y"):
                return
        else:
            bullet.position.y = next_y.y
        bullet.distance_travelled += step_start.distance_to(bullet.position)

    def update(self, dt: float) -> None:
        bullets_before: dict[int, int] = {}
        for bullet in self.game.bullets:
            if bullet.alive:
                bullets_before[bullet.owner_id] = bullets_before.get(bullet.owner_id, 0) + 1
        tanks = self.game.all_tanks()
        for bullet in self.game.bullets:
            if not bullet.alive:
                continue
            bullet.age += dt
            bullet.travel_budget += bullet.velocity.length() * dt
        steps = max(
            1,
            max(
                (
                    math.floor((bullet.travel_budget + 0.000_001) / SHOT_TRACE_STEP)
                    for bullet in self.game.bullets
                    if bullet.alive
                ),
                default=0,
            ),
        )

        for _ in range(steps):
            for bullet in self.game.bullets:
                if (
                    not bullet.alive
                    or bullet.travel_budget + 0.000_001 < SHOT_TRACE_STEP
                ):
                    continue
                bullet.travel_budget = max(
                    0.0,
                    bullet.travel_budget - SHOT_TRACE_STEP,
                )
                self.move_bullet_step(bullet)

            for first_index, first in enumerate(self.game.bullets):
                if not first.alive:
                    continue
                for second in self.game.bullets[first_index + 1 :]:
                    if not second.alive:
                        continue
                    if (
                        first.owner_id == second.owner_id
                        and first.velocity.dot(second.velocity) > 0
                    ):
                        continue
                    if not self.bullets_touch(first, second):
                        continue
                    impact = (first.position + second.position) / 2
                    first.alive = False
                    second.alive = False
                    self.game.create_burst(impact, first.color, 5, 72)
                    self.game.create_burst(impact, second.color, 5, 72)
                    self.game.audio.play_bullet_disintegrate()
                    break

            for bullet in self.game.bullets:
                if bullet.alive:
                    self.game.mine_system.collide_bullet(bullet)

            for bullet in self.game.bullets:
                if not bullet.alive:
                    continue
                for tank in tanks:
                    if not tank.alive:
                        continue
                    if bullet.owner_id == tank.tank_id and bullet.bounces == 0 and bullet.age < 0.14:
                        continue
                    if not self.circle_touches_tank(bullet.position, tank):
                        continue
                    if bullet.owner_id == tank.tank_id and tank.self_safe:
                        self.destroy_bullet(bullet, 7, 75)
                        break
                    self.hit_tank(tank)
                    bullet.alive = False
                    self.game.audio.play_bullet_disintegrate()
                    break

        self.game.bullets = [bullet for bullet in self.game.bullets if bullet.alive]
        bullets_after: dict[int, int] = {}
        for bullet in self.game.bullets:
            bullets_after[bullet.owner_id] = bullets_after.get(bullet.owner_id, 0) + 1
        tanks_by_id = {tank.tank_id: tank for tank in tanks}
        for owner_id, previous_count in bullets_before.items():
            if bullets_after.get(owner_id, 0) >= previous_count or owner_id not in tanks_by_id:
                continue
            tank = tanks_by_id[owner_id]
            tank.shot_think_timer = max(
                tank.shot_think_timer,
                SHOT_THINK_DELAYS[tank.shot_think_speed],
            )
