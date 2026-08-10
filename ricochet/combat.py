from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .config import (
    BOARD_HEIGHT,
    BOARD_WIDTH,
    BULLET_RADIUS,
    FIRE_RATE_DELAYS,
    PLAYER_MIN_RICOCHET_DISTANCE,
    TANK_HALF,
)
from .geometry import clamp, segment_distance_squared
from .models import Bullet, ShotTrace, Tank, Vec2

if TYPE_CHECKING:
    from .game import Game


class CombatSystem:
    def __init__(self, game: Game) -> None:
        self.game = game

    def active_bullets(self, tank: Tank) -> int:
        return sum(bullet.alive and bullet.owner_id == tank.tank_id for bullet in self.game.bullets)

    @staticmethod
    def circle_touches_tank(position: Vec2, tank: Tank) -> bool:
        nearest_x = clamp(position.x, tank.position.x - TANK_HALF, tank.position.x + TANK_HALF)
        nearest_y = clamp(position.y, tank.position.y - TANK_HALF, tank.position.y + TANK_HALF)
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
        if not tank.alive or tank.cooldown > 0 or self.game.state != "playing":
            return False
        if self.active_bullets(tank) >= tank.max_bullets:
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
                max_bounces=tank.max_bounces,
            )
        )
        tank.cooldown = FIRE_RATE_DELAYS[tank.fire_rate]
        self.game.create_burst(muzzle, tank.color, 4, 55)
        return True

    def trace_shot(self, shooter: Tank, angle: float, target: Tank) -> ShotTrace:
        trace = ShotTrace()
        position = self.safe_muzzle(shooter, angle)
        direction = Vec2(math.cos(angle), math.sin(angle))
        bounces = 0
        left_owner = not self.circle_touches_tank(position, shooter)
        step_size = 3.0
        max_steps = math.ceil((math.hypot(BOARD_WIDTH, BOARD_HEIGHT) * 2.4) / step_size)

        for step_index in range(max_steps):
            next_x = Vec2(position.x + direction.x * step_size, position.y)
            if self.game.world.circle_touches_wall(next_x):
                if bounces >= shooter.max_bounces:
                    break
                direction.x *= -1
                bounces += 1
            else:
                position.x = next_x.x

            next_y = Vec2(position.x, position.y + direction.y * step_size)
            if self.game.world.circle_touches_wall(next_y):
                if bounces >= shooter.max_bounces:
                    break
                direction.y *= -1
                bounces += 1
            else:
                position.y = next_y.y

            touches_owner = self.circle_touches_tank(position, shooter)
            if not touches_owner:
                left_owner = True
            elif left_owner:
                trace.self_hit = True

            for ally in self.game.enemies:
                if ally.alive and ally.tank_id != shooter.tank_id and self.circle_touches_tank(position, ally):
                    trace.ally_hit = True
                    break

            if not trace.target_hit and target.alive and self.circle_touches_tank(position, target):
                trace.target_hit = True
                trace.target_bounces = bounces
                trace.target_distance = step_index * step_size

        return trace

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
            return False
        bullet.bounces += 1
        if axis == "x":
            bullet.velocity.x *= -1
        else:
            bullet.velocity.y *= -1
        self.game.create_burst(bullet.position, bullet.color, 5, 58)
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
        return True

    def update(self, dt: float) -> None:
        tanks = self.game.all_tanks()
        maximum_speed = max(
            (bullet.velocity.length() for bullet in self.game.bullets if bullet.alive),
            default=0,
        )
        steps = max(1, math.ceil(maximum_speed * dt / 3.0))
        step_time = dt / steps

        for _ in range(steps):
            for bullet in self.game.bullets:
                if not bullet.alive:
                    continue
                bullet.age += step_time
                substep_start = bullet.position.copy()

                next_x = Vec2(bullet.position.x + bullet.velocity.x * step_time, bullet.position.y)
                if self.game.world.circle_touches_wall(next_x):
                    if self.break_close_player_bullet(bullet, bullet.distance_travelled):
                        continue
                    if not self.reflect_bullet(bullet, "x"):
                        continue
                else:
                    bullet.position.x = next_x.x

                next_y = Vec2(bullet.position.x, bullet.position.y + bullet.velocity.y * step_time)
                if self.game.world.circle_touches_wall(next_y):
                    travelled = bullet.distance_travelled + substep_start.distance_to(bullet.position)
                    if self.break_close_player_bullet(bullet, travelled):
                        continue
                    if not self.reflect_bullet(bullet, "y"):
                        continue
                else:
                    bullet.position.y = next_y.y
                bullet.distance_travelled += substep_start.distance_to(bullet.position)

            for first_index, first in enumerate(self.game.bullets):
                if not first.alive:
                    continue
                for second in self.game.bullets[first_index + 1 :]:
                    if not second.alive or not self.bullets_touch(first, second):
                        continue
                    impact = (first.position + second.position) / 2
                    first.alive = False
                    second.alive = False
                    self.game.create_burst(impact, first.color, 5, 72)
                    self.game.create_burst(impact, second.color, 5, 72)
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
                    self.game.destroy_tank(tank)
                    bullet.alive = False
                    break

        self.game.bullets = [bullet for bullet in self.game.bullets if bullet.alive]
