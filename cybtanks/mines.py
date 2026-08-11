from __future__ import annotations

from typing import TYPE_CHECKING

from .config import (
    BULLET_RADIUS,
    MINE_AUTO_TRIGGER_TIME,
    MINE_BEEP_INTERVAL,
    MINE_COLLISION_RADIUS,
    MINE_EXPLOSION_RADIUS,
    MINE_MIN_SEPARATION,
    MINE_TRIGGER_RADIUS,
    MINE_WARNING_DURATION,
)
from .geometry import point_segment_distance_squared
from .models import Bullet, Mine, Tank, Vec2

if TYPE_CHECKING:
    from .game import Game


class MineSystem:
    def __init__(self, game: Game) -> None:
        self.game = game

    def active_mines(self, tank: Tank) -> int:
        return sum(mine.alive and mine.owner_id == tank.tank_id for mine in self.game.mines)

    def place(self, tank: Tank) -> bool:
        if not tank.alive or tank.max_mines <= 0 or self.game.state != "playing":
            return False
        if self.active_mines(tank) >= tank.max_mines:
            return False
        if any(
            mine.alive and mine.position.distance_to(tank.position) < MINE_MIN_SEPARATION
            for mine in self.game.mines
        ):
            return False
        self.game.mines.append(
            Mine(
                position=tank.position.copy(),
                owner_id=tank.tank_id,
                team=tank.team,
            )
        )
        self.game.create_burst(tank.position, (116, 137, 121), 4, 25)
        self.game.audio.play_mine_place()
        for enemy in self.game.enemies:
            enemy.plan_timer = 0
        return True

    def trigger(self, mine: Mine) -> None:
        if not mine.alive or mine.triggered:
            return
        mine.triggered = True
        mine.warning_elapsed = 0.0
        mine.beep_timer = MINE_BEEP_INTERVAL
        self.game.audio.play_mine_beep()

    @staticmethod
    def bullet_touches_mine(bullet: Bullet, mine: Mine) -> bool:
        direction = bullet.velocity.normalize() if bullet.velocity.length_squared() else Vec2(1, 0)
        bullet_start = bullet.position - direction * 6
        bullet_end = bullet.position + direction * 8
        collision_radius = MINE_COLLISION_RADIUS + BULLET_RADIUS
        return point_segment_distance_squared(mine.position, bullet_start, bullet_end) <= collision_radius**2

    def collide_bullet(self, bullet: Bullet) -> bool:
        for mine in self.game.mines:
            if not mine.alive or not self.bullet_touches_mine(bullet, mine):
                continue
            self.game.combat.destroy_bullet(bullet)
            self.explode(mine)
            return True
        return False

    def update(self, dt: float) -> None:
        tanks = self.game.all_tanks()
        for mine in self.game.mines:
            if not mine.alive:
                continue
            mine.age += dt
            owner = next((tank for tank in tanks if tank.tank_id == mine.owner_id), None)
            if not mine.owner_has_left and (
                owner is None or not owner.alive or owner.position.distance_to(mine.position) > MINE_TRIGGER_RADIUS
            ):
                mine.owner_has_left = True

            for tank in tanks:
                if not tank.alive:
                    continue
                if tank.tank_id == mine.owner_id and not mine.owner_has_left:
                    continue
                if tank.position.distance_to(mine.position) <= MINE_TRIGGER_RADIUS:
                    self.explode(mine)
                    break

            if not mine.alive:
                continue
            if not mine.triggered and mine.age >= MINE_AUTO_TRIGGER_TIME:
                self.trigger(mine)

            if not mine.triggered:
                continue
            mine.warning_elapsed += dt
            mine.beep_timer -= dt
            if mine.beep_timer <= 0:
                self.game.audio.play_mine_beep()
                mine.beep_timer += MINE_BEEP_INTERVAL
            if mine.warning_elapsed >= MINE_WARNING_DURATION:
                self.explode(mine)

        self.game.mines = [mine for mine in self.game.mines if mine.alive]
        self.game.bullets = [bullet for bullet in self.game.bullets if bullet.alive]

    def explode(self, mine: Mine) -> None:
        if not mine.alive:
            return
        mine.alive = False
        self.game.create_explosion(mine.position, MINE_EXPLOSION_RADIUS)
        for bullet in tuple(self.game.bullets):
            if (
                bullet.alive
                and bullet.position.distance_squared_to(mine.position)
                <= MINE_EXPLOSION_RADIUS**2
            ):
                self.game.combat.destroy_bullet(bullet, amount=8, force=95)
        chained_mines = [
            other
            for other in self.game.mines
            if other.alive and other.position.distance_to(mine.position) <= MINE_EXPLOSION_RADIUS
        ]
        self.game.create_burst(mine.position, (255, 116, 66), 42, 190)
        self.game.create_burst(mine.position, (246, 224, 164), 24, 125)
        self.game.create_burst(mine.position, (52, 49, 40), 18, 85)

        for other in chained_mines:
            self.explode(other)

        for tank in self.game.all_tanks():
            if tank.alive and tank.position.distance_to(mine.position) <= MINE_EXPLOSION_RADIUS:
                self.game.destroy_tank(tank, play_destruction_sound=False)

        if self.game.world.break_walls(mine.position, MINE_EXPLOSION_RADIUS):
            self.game.renderer.rebuild_board_background()
        for enemy in self.game.enemies:
            enemy.plan_timer = 0
            enemy.aim_timer = 0
