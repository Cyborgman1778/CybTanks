from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from .config import BULLET_RADIUS, FIRE_RATE_DELAYS
from .geometry import angle_difference, turn_towards
from .models import Tank, Vec2
from .world import cell_center, grid_cell

if TYPE_CHECKING:
    from .game import Game


class EnemyAISystem:
    def __init__(self, game: Game) -> None:
        self.game = game

    def direct_shot_angle(self, enemy: Tank) -> float | None:
        difference = self.game.player.position - enemy.position
        if difference.length_squared() == 0:
            return None
        perpendicular = Vec2(-difference.y, difference.x).normalize()
        candidates = []
        for offset in (0, -8, 8, -14, 14):
            aim_point = self.game.player.position + perpendicular * offset
            if not self.game.world.clear_segment(enemy.position, aim_point, BULLET_RADIUS + 1):
                continue
            angle = math.atan2(aim_point.y - enemy.position.y, aim_point.x - enemy.position.x)
            trace = self.game.combat.trace_shot(enemy, angle, self.game.player)
            if trace.target_hit and trace.target_bounces == 0 and not trace.self_hit and not trace.ally_hit:
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
        for angle in self.ricochet_angles(enemy, self.game.player):
            trace = self.game.combat.trace_shot(enemy, angle, self.game.player)
            if trace.target_hit and trace.target_bounces == 1 and not trace.self_hit and not trace.ally_hit:
                return angle
        return None

    def choose_shot(self, enemy: Tank) -> tuple[float, bool]:
        direct_angle = self.direct_shot_angle(enemy)
        if direct_angle is not None:
            return direct_angle, True

        ricochet_angle = self.accurate_ricochet_angle(enemy)
        fallback = math.atan2(
            self.game.player.position.y - enemy.position.y,
            self.game.player.position.x - enemy.position.x,
        )
        if ricochet_angle is None:
            return fallback, False
        if enemy.ricochet_accuracy == "accurate" or random.random() < enemy.ricochet_success_rate:
            return ricochet_angle, True

        for _ in range(8):
            error = random.choice((-1, 1)) * random.uniform(0.045, 0.14)
            inaccurate_angle = ricochet_angle + error
            trace = self.game.combat.trace_shot(enemy, inaccurate_angle, self.game.player)
            if not trace.self_hit and not trace.ally_hit:
                return inaccurate_angle, True
        return fallback, False

    def plan_path(self, enemy: Tank) -> None:
        start = grid_cell(enemy.position)
        enemy.goal = grid_cell(self.game.player.position)
        enemy.path = self.game.world.find_path(start, enemy.goal) or []
        enemy.plan_timer = 0.75 + random.random() * 0.4

    def update_enemy(self, enemy: Tank, dt: float) -> None:
        enemy.fire_timer -= dt
        enemy.plan_timer -= dt
        enemy.aim_timer -= dt
        has_active_bullet = self.game.combat.active_bullets(enemy) >= enemy.max_bullets
        can_move = not (enemy.self_safe and has_active_bullet)
        if enemy.speed > 0 and can_move and enemy.plan_timer <= 0:
            self.plan_path(enemy)

        movement = Vec2()
        if enemy.speed > 0 and can_move and enemy.path:
            target_position = cell_center(enemy.path[0])
            difference = target_position - enemy.position
            if difference.length() < 3.0:
                enemy.path.pop(0)
            elif difference.length_squared() > 0:
                movement = difference.normalize() * enemy.speed * dt

        actual_movement = (
            self.game.world.move_tank(enemy, movement, self.game.all_tanks())
            if movement.length_squared() > 0
            else Vec2()
        )
        enemy.velocity = actual_movement / dt if dt > 0 else Vec2()
        if actual_movement.length_squared() > 0:
            move_angle = math.atan2(actual_movement.y, actual_movement.x)
            enemy.body_angle = turn_towards(enemy.body_angle, move_angle, 5.5 * dt)
        elif movement.length_squared() > 0:
            enemy.plan_timer = 0.0

        direct_aim = self.game.player.position - enemy.position
        if direct_aim.length_squared() == 0:
            return
        direct_angle = math.atan2(direct_aim.y, direct_aim.x)

        if has_active_bullet or enemy.fire_timer > 0:
            enemy.aim_angle = direct_angle
            enemy.shot_ready = False
        elif enemy.aim_timer <= 0 or enemy.aim_angle is None:
            enemy.aim_angle, enemy.shot_ready = self.choose_shot(enemy)
            enemy.aim_timer = 0.35 if enemy.ricochet_accuracy == "accurate" else 0.5

        desired_angle = enemy.aim_angle if enemy.aim_angle is not None else direct_angle
        enemy.turret_angle = turn_towards(enemy.turret_angle, desired_angle, 2.25 * dt)
        turret_ready = abs(angle_difference(desired_angle, enemy.turret_angle)) < 0.075

        if enemy.fire_timer <= 0 and enemy.shot_ready and turret_ready:
            safety_check = self.game.combat.trace_shot(enemy, desired_angle, self.game.player)
            if safety_check.self_hit or safety_check.ally_hit:
                enemy.aim_timer = 0
                enemy.shot_ready = False
                return
        if enemy.fire_timer <= 0 and enemy.shot_ready and turret_ready and self.game.combat.shoot(enemy):
            enemy.fire_timer = FIRE_RATE_DELAYS[enemy.fire_rate]
            enemy.aim_timer = 0
            enemy.shot_ready = False

    def update(self, dt: float) -> None:
        if not self.game.player.alive:
            return
        for enemy in self.game.enemies:
            if enemy.alive:
                self.update_enemy(enemy, dt)
