from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

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
        player_cell = grid_cell(self.game.player.position)
        tactical = enemy.intelligence == "tactical"
        search_radius = 5 if tactical else 2
        blocked = self.mine_blocked_cells()
        blocked.discard(start)

        penalties = self.route_penalties(enemy)
        reserved_goals = {
            ally.goal
            for ally in self.game.enemies
            if ally.alive and ally.tank_id != enemy.tank_id and ally.goal is not None
        }
        candidates = []
        for row in range(
            max(1, player_cell[1] - search_radius),
            min(ROWS - 1, player_cell[1] + search_radius + 1),
        ):
            for col in range(
                max(1, player_cell[0] - search_radius),
                min(COLS - 1, player_cell[0] + search_radius + 1),
            ):
                candidate = (col, row)
                if (
                    self.game.world.is_wall(candidate)
                    or candidate in blocked
                    or (enemy.speed > 0 and candidate == start)
                ):
                    continue
                distance_to_player = abs(col - player_cell[0]) + abs(row - player_cell[1])
                if tactical and not 3 <= distance_to_player <= 5:
                    continue
                if not tactical and distance_to_player > 2:
                    continue
                path = self.game.world.find_path(start, candidate, blocked, penalties)
                if path is None:
                    continue
                overlap_cost = sum(penalties.get(cell, 0.0) for cell in path)
                reservation_cost = 8.0 if candidate in reserved_goals else 0.0
                variant_hash = (
                    col * 73_856_093
                    ^ row * 19_349_663
                    ^ enemy.route_seed
                    ^ enemy.route_variant * 83_492_791
                )
                variant = (variant_hash & 0xFFFF) / 0xFFFF * 1.8
                if tactical:
                    has_firing_lane = self.game.world.clear_segment(
                        cell_center(candidate),
                        self.game.player.position,
                        BULLET_RADIUS + 1,
                    )
                    score = (
                        len(path) * 0.65
                        + overlap_cost
                        + abs(distance_to_player - 4) * 1.4
                        + reservation_cost
                        + (0.0 if has_firing_lane else 4.5)
                        + variant
                    )
                else:
                    score = (
                        len(path)
                        + overlap_cost
                        + distance_to_player * 0.7
                        + reservation_cost
                        + variant
                    )
                candidates.append((score, candidate, path))

        if not candidates:
            col, row = start
            for candidate in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
                if self.game.world.is_wall(candidate) or candidate in blocked:
                    continue
                path = self.game.world.find_path(start, candidate, blocked, penalties)
                if path:
                    score = len(path) + sum(penalties.get(cell, 0.0) for cell in path)
                    candidates.append((score, candidate, path))

        if candidates:
            _, enemy.goal, enemy.path = min(candidates, key=lambda item: item[0])
        else:
            enemy.goal = start
            enemy.path = []
        enemy.plan_timer = (
            0.55 + random.random() * 0.25
            if tactical
            else 0.75 + random.random() * 0.4
        )

    def route_penalties(self, enemy: Tank) -> dict[tuple[int, int], float]:
        penalties: dict[tuple[int, int], float] = {}
        for ally in self.game.enemies:
            if not ally.alive or ally.tank_id == enemy.tank_id:
                continue
            occupied = grid_cell(ally.position)
            penalties[occupied] = penalties.get(occupied, 0.0) + 12.0
            for index, cell in enumerate(ally.path[:10]):
                penalty = max(1.0, 6.0 - index * 0.5)
                penalties[cell] = penalties.get(cell, 0.0) + penalty
            if ally.goal is not None:
                penalties[ally.goal] = penalties.get(ally.goal, 0.0) + 4.0

        for index, cell in enumerate(reversed(enemy.recent_cells[-10:])):
            penalties[cell] = penalties.get(cell, 0.0) + max(0.5, 3.5 - index * 0.35)

        if enemy.avoid_cell is not None and enemy.avoid_timer > 0:
            penalties[enemy.avoid_cell] = penalties.get(enemy.avoid_cell, 0.0) + 10.0

        noise_seed = enemy.route_seed ^ (enemy.route_variant * 83_492_791)
        for row in range(1, ROWS - 1):
            for col in range(1, COLS - 1):
                cell = (col, row)
                if self.game.world.is_wall(cell):
                    continue
                value = (col * 73_856_093) ^ (row * 19_349_663) ^ noise_seed
                penalties[cell] = penalties.get(cell, 0.0) + (value & 0xFFFF) / 0xFFFF * 0.45
        return penalties

    def mine_blocked_cells(self) -> set[tuple[int, int]]:
        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        return {
            (col, row)
            for row in range(1, ROWS - 1)
            for col in range(1, COLS - 1)
            if any(
                mine.alive and cell_center((col, row)).distance_to(mine.position) < safe_distance
                for mine in self.game.mines
            )
        }

    def mine_danger(self, enemy: Tank) -> bool:
        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        return any(
            mine.alive and enemy.position.distance_to(mine.position) < safe_distance
            for mine in self.game.mines
        )

    def route_has_mine_danger(self, enemy: Tank) -> bool:
        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        return any(
            mine.alive
            and any(
                cell_center(cell).distance_to(mine.position) < safe_distance
                for cell in enemy.path
            )
            for mine in self.game.mines
        )

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
            and grid_cell(ally.position) == current_cell
        ]
        if not cellmates or max(
            tank.stationary_timer for tank in (enemy, *cellmates)
        ) < 0.12:
            return movement
        if any(self.mine_danger(tank) for tank in (enemy, *cellmates)):
            return movement

        center = cell_center(current_cell)
        group = [enemy, *cellmates]
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
        candidates = []
        for row in range(1, ROWS - 1):
            for col in range(1, COLS - 1):
                cell = (col, row)
                if self.game.world.is_wall(cell):
                    continue
                position = cell_center(cell)
                closest_mine = min(
                    (position.distance_to(mine.position) for mine in self.game.mines if mine.alive),
                    default=math.inf,
                )
                if closest_mine < safe_distance:
                    continue
                grid_distance = abs(col - start[0]) + abs(row - start[1])
                candidates.append((grid_distance, -closest_mine, cell))

        candidates.sort()
        for _, _, candidate in candidates:
            path = self.game.world.find_path(
                start,
                candidate,
                penalties=self.route_penalties(enemy),
            )
            if path is None:
                continue
            if not path and enemy.position.distance_to(cell_center(candidate)) >= 0.5:
                path = [candidate]
            enemy.goal = candidate
            enemy.path = path
            enemy.plan_timer = 0.22
            return
        enemy.path = []
        enemy.plan_timer = 0.15

    def update_enemy(self, enemy: Tank, dt: float) -> None:
        enemy.fire_timer -= dt
        enemy.mine_timer -= dt
        enemy.plan_timer -= dt
        enemy.aim_timer -= dt
        enemy.detour_timer = max(0.0, enemy.detour_timer - dt)
        enemy.avoid_timer = max(0.0, enemy.avoid_timer - dt)
        if enemy.avoid_timer == 0:
            enemy.avoid_cell = None
        self.track_movement_progress(enemy, dt)
        if enemy.net_stuck_timer >= 0.45:
            self.abandon_stuck_route(enemy)
        has_active_bullet = self.game.combat.active_bullets(enemy) >= enemy.max_bullets
        mine_danger = self.mine_danger(enemy)
        player_cell = grid_cell(self.game.player.position)
        goal_distance = (
            math.inf
            if enemy.goal is None
            else abs(enemy.goal[0] - player_cell[0])
            + abs(enemy.goal[1] - player_cell[1])
        )
        goal_outdated = (
            not 3 <= goal_distance <= 5
            if enemy.intelligence == "tactical"
            else goal_distance > 4
        )
        route_unsafe = enemy.plan_timer <= 0 and self.route_has_mine_danger(enemy)
        if enemy.speed > 0:
            if mine_danger and (
                not enemy.escaping_mines or not enemy.path or route_unsafe
            ):
                self.plan_mine_escape(enemy)
            elif not mine_danger and (
                enemy.escaping_mines
                or not enemy.path
                or route_unsafe
                or (enemy.plan_timer <= 0 and goal_outdated)
            ):
                self.plan_path(enemy)
        if mine_danger:
            enemy.detour_timer = 0
        enemy.escaping_mines = mine_danger

        movement = Vec2()
        if enemy.speed > 0:
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
                    self.plan_mine_escape(enemy)
                else:
                    self.plan_path(enemy)

        if (
            enemy.detour_timer > 0
            and not mine_danger
            and enemy.velocity.length_squared() > 0
        ):
            movement = enemy.velocity.normalize() * enemy.speed * dt
        if not mine_danger:
            movement = self.coordinate_crowded_cell(enemy, movement, dt)
        movement = self.steer_around_friendly_fire(enemy, movement)

        waypoint = cell_center(enemy.path[0]) if enemy.path else None
        waypoint_distance = (
            enemy.position.distance_to(waypoint) if waypoint is not None else math.inf
        )
        starting_position = enemy.position.copy()
        actual_movement = self.move_enemy(enemy, movement) if movement.length_squared() > 0 else Vec2()
        expected_distance = movement.length()
        if expected_distance <= 0.000_001 and enemy.speed > 0:
            expected_distance = enemy.speed * dt
        if expected_distance > 0 and actual_movement.length() < expected_distance * 0.2:
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
            if movement.length_squared() > 0:
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

        if enemy.stuck_timer >= 0.35:
            self.abandon_stuck_route(enemy)
        if actual_movement.length_squared() > 0:
            move_angle = math.atan2(actual_movement.y, actual_movement.x)
            enemy.body_angle = turn_towards(enemy.body_angle, move_angle, 5.5 * dt)
        elif movement.length_squared() > 0:
            enemy.plan_timer = 0.0

        if (
            enemy.max_mines > 0
            and enemy.mine_timer <= 0
            and not mine_danger
            and self.allies_safe_from_new_mine(enemy)
        ):
            if self.game.mine_system.place(enemy):
                enemy.mine_timer = 2.4 + random.random() * 0.8
                enemy.plan_timer = 0
            else:
                enemy.mine_timer = 0.45

        direct_aim = self.game.player.position - enemy.position
        if direct_aim.length_squared() == 0:
            return
        direct_angle = math.atan2(direct_aim.y, direct_aim.x)

        if has_active_bullet or enemy.fire_timer > 0:
            enemy.aim_angle = direct_angle
            enemy.shot_ready = False
        elif enemy.aim_timer <= 0 or enemy.aim_angle is None:
            enemy.aim_angle, enemy.shot_ready = self.choose_shot(enemy)
            if enemy.intelligence == "tactical":
                enemy.aim_timer = 0.25
            elif enemy.ricochet_accuracy == "accurate":
                enemy.aim_timer = 0.35
            elif enemy.intelligence == "medium":
                enemy.aim_timer = 0.4
            else:
                enemy.aim_timer = 0.5

        desired_angle = enemy.aim_angle if enemy.aim_angle is not None else direct_angle
        enemy.turret_angle = turn_towards(enemy.turret_angle, desired_angle, 2.25 * dt)
        aim_tolerance = 0.045 if enemy.kind == "dark_green" else 0.075
        turret_ready = abs(angle_difference(desired_angle, enemy.turret_angle)) < aim_tolerance

        if enemy.fire_timer <= 0 and enemy.shot_ready and turret_ready:
            safety_check = self.game.combat.trace_shot(
                enemy,
                enemy.turret_angle,
                self.game.player,
            )
            if safety_check.self_hit or safety_check.ally_hit:
                enemy.aim_timer = 0
                enemy.shot_ready = False
                return
        if enemy.fire_timer <= 0 and enemy.shot_ready and turret_ready and self.game.combat.shoot(enemy):
            enemy.fire_timer = FIRE_RATE_DELAYS[enemy.fire_rate]
            enemy.aim_timer = 0
            enemy.shot_ready = False

    def allies_safe_from_new_mine(self, enemy: Tank) -> bool:
        danger_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        for ally in self.game.enemies:
            if not ally.alive or ally.tank_id == enemy.tank_id:
                continue
            future_positions = [ally.position, *(cell_center(cell) for cell in ally.path[:3])]
            if any(position.distance_to(enemy.position) < danger_distance for position in future_positions):
                return False
        return True

    def update(self, dt: float) -> None:
        if not self.game.player.alive:
            return
        self.game.combat.prepare_friendly_fire_paths("enemy")
        for enemy in self.game.enemies:
            if enemy.alive:
                self.update_enemy(enemy, dt)
