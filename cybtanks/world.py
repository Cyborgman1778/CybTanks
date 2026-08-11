from __future__ import annotations

import heapq
import math
from collections.abc import Callable

import pygame

from .config import BULLET_RADIUS, COLS, MAP, ROWS, TANK_HALF, TILE
from .geometry import clamp
from .models import GridCell, Tank, Vec2


def grid_cell(position: Vec2) -> GridCell:
    return (
        int(clamp(position.x // TILE, 0, COLS - 1)),
        int(clamp(position.y // TILE, 0, ROWS - 1)),
    )


def cell_center(cell: GridCell) -> Vec2:
    return Vec2((cell[0] + 0.5) * TILE, (cell[1] + 0.5) * TILE)


def is_wall(cell: GridCell) -> bool:
    col, row = cell
    return col < 0 or col >= COLS or row < 0 or row >= ROWS or MAP[row][col] != 0


class World:
    def __init__(self) -> None:
        self.layout = MAP
        self.tiles: list[list[int]] = []
        self.bounce_surfaces: list[tuple[str, float, float, float]] = []
        self.reset()

    def reset(self, layout: tuple[tuple[int, ...], ...] | None = None) -> None:
        if layout is not None:
            self.layout = layout
        self.tiles = [list(row) for row in self.layout]
        self.bounce_surfaces = self._build_bounce_surfaces()

    def is_wall(self, cell: GridCell) -> bool:
        return self.blocks_tank(cell)

    def blocks_tank(self, cell: GridCell) -> bool:
        col, row = cell
        return col < 0 or col >= COLS or row < 0 or row >= ROWS or self.tiles[row][col] != 0

    def blocks_bullet(self, cell: GridCell) -> bool:
        col, row = cell
        return col < 0 or col >= COLS or row < 0 or row >= ROWS or self.tiles[row][col] in (1, 2)

    def tank_touches_wall(self, position: Vec2, half: float = TANK_HALF) -> bool:
        min_col = math.floor((position.x - half) / TILE)
        max_col = math.floor((position.x + half) / TILE)
        min_row = math.floor((position.y - half) / TILE)
        max_row = math.floor((position.y + half) / TILE)

        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if not self.blocks_tank((col, row)):
                    continue
                left = col * TILE
                top = row * TILE
                if (
                    position.x + half > left
                    and position.x - half < left + TILE
                    and position.y + half > top
                    and position.y - half < top + TILE
                ):
                    return True
        return False

    @staticmethod
    def tank_touches_tank(tank: Tank, position: Vec2, tanks: list[Tank]) -> bool:
        minimum_distance = TANK_HALF * 2
        for other in tanks:
            if not other.alive or other.tank_id == tank.tank_id:
                continue
            if position.distance_squared_to(other.position) < minimum_distance**2:
                return True
        return False

    def move_tank(
        self,
        tank: Tank,
        movement: Vec2,
        tanks: list[Tank],
        movement_allowed: Callable[[Tank, Vec2], bool] | None = None,
    ) -> Vec2:
        original = tank.position.copy()
        for axis, amount in (("x", movement.x), ("y", movement.y)):
            if abs(amount) <= 0.000_001:
                continue
            snapshots = {
                other.tank_id: other.position.copy()
                for other in tanks
                if other.alive
            }
            if self._push_axis(
                tank,
                amount,
                axis,
                tanks,
                set(),
                movement_allowed,
            ):
                continue
            for other in tanks:
                if other.alive and other.tank_id in snapshots:
                    other.position.update(snapshots[other.tank_id])
        return tank.position - original

    def _push_axis(
        self,
        tank: Tank,
        amount: float,
        axis: str,
        tanks: list[Tank],
        chain: set[int],
        movement_allowed: Callable[[Tank, Vec2], bool] | None,
    ) -> bool:
        if tank.tank_id in chain:
            return False
        next_chain = chain | {tank.tank_id}
        candidate = tank.position.copy()
        setattr(candidate, axis, getattr(candidate, axis) + amount)
        if self.tank_touches_wall(candidate):
            return False
        if movement_allowed is not None and not movement_allowed(
            tank,
            candidate - tank.position,
        ):
            return False

        while True:
            colliders = [
                other
                for other in tanks
                if other.alive
                and other.tank_id != tank.tank_id
                and candidate.distance_squared_to(other.position) < (TANK_HALF * 2) ** 2
            ]
            if not colliders:
                break
            if not self._push_axis(
                colliders[0],
                amount,
                axis,
                tanks,
                next_chain,
                movement_allowed,
            ):
                return False
        tank.position.update(candidate)
        return True

    def circle_touches_wall(self, position: Vec2, radius: float = BULLET_RADIUS) -> bool:
        min_col = math.floor((position.x - radius) / TILE)
        max_col = math.floor((position.x + radius) / TILE)
        min_row = math.floor((position.y - radius) / TILE)
        max_row = math.floor((position.y + radius) / TILE)

        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if not self.blocks_bullet((col, row)):
                    continue
                nearest_x = clamp(position.x, col * TILE, (col + 1) * TILE)
                nearest_y = clamp(position.y, row * TILE, (row + 1) * TILE)
                if position.distance_squared_to((nearest_x, nearest_y)) <= radius**2:
                    return True
        return False

    def find_path(
        self,
        start: GridCell,
        goal: GridCell,
        blocked: set[GridCell] | None = None,
        penalties: dict[GridCell, float] | None = None,
    ) -> list[GridCell] | None:
        blocked = blocked or set()
        penalties = penalties or {}
        if self.is_wall(start) or self.is_wall(goal) or goal in blocked:
            return None
        if start == goal:
            return []

        frontier: list[tuple[float, float, GridCell]] = [(0, 0, start)]
        came_from: dict[GridCell, GridCell] = {}
        cost_so_far: dict[GridCell, float] = {start: 0}

        while frontier:
            _, current_cost, current = heapq.heappop(frontier)
            if current == goal:
                break
            if current_cost != cost_so_far.get(current):
                continue

            col, row = current
            for neighbour in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
                if self.is_wall(neighbour) or neighbour in blocked:
                    continue
                new_cost = current_cost + 1 + penalties.get(neighbour, 0.0)
                if new_cost >= cost_so_far.get(neighbour, math.inf):
                    continue
                cost_so_far[neighbour] = new_cost
                priority = new_cost + abs(goal[0] - neighbour[0]) + abs(goal[1] - neighbour[1])
                heapq.heappush(frontier, (priority, new_cost, neighbour))
                came_from[neighbour] = current

        if goal not in came_from:
            return None

        path = []
        current = goal
        while current != start:
            path.append(current)
            current = came_from[current]
        path.reverse()
        return path

    def clear_segment(self, start: Vec2, end: Vec2, margin: float = BULLET_RADIUS) -> bool:
        min_col = max(0, math.floor((min(start.x, end.x) - margin) / TILE))
        max_col = min(COLS - 1, math.floor((max(start.x, end.x) + margin) / TILE))
        min_row = max(0, math.floor((min(start.y, end.y) - margin) / TILE))
        max_row = min(ROWS - 1, math.floor((max(start.y, end.y) + margin) / TILE))
        line = ((start.x, start.y), (end.x, end.y))

        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if self.tiles[row][col] not in (1, 2):
                    continue
                wall = pygame.Rect(col * TILE, row * TILE, TILE, TILE)
                wall.inflate_ip(math.ceil(margin * 2), math.ceil(margin * 2))
                if wall.clipline(*line):
                    return False
        return True

    def _build_bounce_surfaces(self) -> list[tuple[str, float, float, float]]:
        surfaces = []
        for row in range(ROWS):
            for col in range(COLS):
                if self.tiles[row][col] not in (1, 2):
                    continue
                top = row * TILE
                bottom = (row + 1) * TILE
                left = col * TILE
                right = (col + 1) * TILE
                if not self.blocks_bullet((col - 1, row)):
                    surfaces.append(("x", left - BULLET_RADIUS, top, bottom))
                if not self.blocks_bullet((col + 1, row)):
                    surfaces.append(("x", right + BULLET_RADIUS, top, bottom))
                if not self.blocks_bullet((col, row - 1)):
                    surfaces.append(("y", top - BULLET_RADIUS, left, right))
                if not self.blocks_bullet((col, row + 1)):
                    surfaces.append(("y", bottom + BULLET_RADIUS, left, right))
        return surfaces

    def break_walls(self, position: Vec2, radius: float) -> int:
        broken = 0
        min_col = max(0, math.floor((position.x - radius) / TILE))
        max_col = min(COLS - 1, math.floor((position.x + radius) / TILE))
        min_row = max(0, math.floor((position.y - radius) / TILE))
        max_row = min(ROWS - 1, math.floor((position.y + radius) / TILE))

        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if self.tiles[row][col] != 2:
                    continue
                nearest_x = clamp(position.x, col * TILE, (col + 1) * TILE)
                nearest_y = clamp(position.y, row * TILE, (row + 1) * TILE)
                if position.distance_squared_to((nearest_x, nearest_y)) > radius**2:
                    continue
                self.tiles[row][col] = 0
                broken += 1

        if broken:
            self.bounce_surfaces = self._build_bounce_surfaces()
        return broken
