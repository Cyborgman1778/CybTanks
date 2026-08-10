from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pygame

from .config import (
    ASSET_DIR,
    ASSET_NAMES,
    BACKGROUND,
    BOARD_HEIGHT,
    BOARD_WIDTH,
    CREAM,
    FLOOR_A,
    HUD_HEIGHT,
    LIGHT_GRAY,
    MINE_WARNING_DURATION,
    MAX_PLAYER_BULLETS,
    MAX_PLAYER_LIVES,
    MUTED,
    PLAYER_COLOR,
    ROWS,
    COLS,
    TILE,
)
from .geometry import clamp, oriented_box
from .models import Bullet, Mine, Particle, Tank, Vec2

if TYPE_CHECKING:
    from .game import Game


class Renderer:
    def __init__(self, game: Game) -> None:
        self.game = game
        self.assets = self._load_assets()
        self.title_font = pygame.font.SysFont("impact", 43)
        self.hud_font = pygame.font.SysFont("consolas", 16, bold=True)
        self.small_font = pygame.font.SysFont("consolas", 12, bold=True)
        self.end_font = pygame.font.SysFont("impact", 61)
        self.board_background = self._build_board_background()

    @staticmethod
    def _load_assets() -> dict[str, pygame.Surface]:
        assets = {}
        for name in ASSET_NAMES:
            path = ASSET_DIR / f"{name}.svg"
            try:
                assets[name] = pygame.image.load(path).convert_alpha()
            except (FileNotFoundError, pygame.error) as error:
                raise RuntimeError(f"Could not load asset: {path}") from error
        return assets

    def _build_board_background(self) -> pygame.Surface:
        surface = pygame.Surface((BOARD_WIDTH, BOARD_HEIGHT))
        surface.fill(FLOOR_A)
        for row in range(ROWS):
            for col in range(COLS):
                position = (col * TILE, row * TILE)
                tile = self.game.world.tiles[row][col]
                if tile == 0:
                    floor_name = "floor_a" if (row + col) % 2 == 0 else "floor_b"
                    surface.blit(self.assets[floor_name], position)
                elif tile == 2:
                    surface.blit(self.assets["wall_breakable"], position)
                else:
                    surface.blit(self.assets["wall"], position)
        return surface

    def rebuild_board_background(self) -> None:
        self.board_background = self._build_board_background()

    @staticmethod
    def draw_wreck(
        surface: pygame.Surface,
        wreck: tuple[Vec2, float, tuple[int, int, int]],
    ) -> None:
        position, angle, color = wreck
        pygame.draw.circle(surface, (65, 61, 48), position, 23)
        dark_color = tuple(max(25, channel // 3) for channel in color)
        pygame.draw.polygon(surface, dark_color, oriented_box(position, angle, 18, 13))
        pygame.draw.line(surface, (24, 27, 23), position - Vec2(11, 11), position + Vec2(11, 11), 4)

    def draw_tank(self, surface: pygame.Surface, tank: Tank) -> None:
        if not tank.alive:
            return
        shadow = tank.position + Vec2(3, 4)
        pygame.draw.polygon(surface, (47, 48, 39), oriented_box(shadow, tank.body_angle, 21, 18))

        body = pygame.transform.rotozoom(
            self.assets[f"{tank.kind}_body"],
            -math.degrees(tank.body_angle),
            1,
        )
        surface.blit(body, body.get_rect(center=tank.position))
        turret = pygame.transform.rotozoom(
            self.assets[f"{tank.kind}_turret"],
            -math.degrees(tank.turret_angle),
            1,
        )
        surface.blit(turret, turret.get_rect(center=tank.position))

        if tank.team == "enemy":
            pygame.draw.rect(
                surface,
                (24, 31, 25),
                (tank.position.x - 11, tank.position.y - 31, 22, 4),
                border_radius=2,
            )
            pygame.draw.rect(
                surface,
                tank.color,
                (tank.position.x - 9, tank.position.y - 30, 18, 2),
                border_radius=1,
            )

    def draw_bullets(self, surface: pygame.Surface) -> None:
        for bullet in self.game.bullets:
            self._draw_bullet(surface, bullet)

    def _draw_bullet(self, surface: pygame.Surface, bullet: Bullet) -> None:
        direction = bullet.velocity.normalize() if bullet.velocity.length_squared() else Vec2(1, 0)
        rear = bullet.position - direction * 8
        pygame.draw.line(
            surface,
            tuple(channel // 3 for channel in bullet.color),
            rear,
            rear - direction * 7,
            2,
        )
        sprite_name = "bullet_player" if bullet.team == "player" else "bullet_enemy"
        sprite = pygame.transform.rotozoom(
            self.assets[sprite_name],
            -math.degrees(math.atan2(direction.y, direction.x)),
            1,
        )
        surface.blit(sprite, sprite.get_rect(center=bullet.position))

    def draw_mines(self, surface: pygame.Surface) -> None:
        for mine in self.game.mines:
            self._draw_mine(surface, mine)

    def _draw_mine(self, surface: pygame.Surface, mine: Mine) -> None:
        warning_on = mine.triggered and int(mine.warning_elapsed / 0.11) % 2 == 0
        sprite_name = "mine_warning" if warning_on else "mine"
        sprite = self.assets[sprite_name]
        surface.blit(sprite, sprite.get_rect(center=mine.position))
        if mine.triggered:
            progress = clamp(mine.warning_elapsed / MINE_WARNING_DURATION, 0, 1)
            radius = int(16 + progress * 8)
            pygame.draw.circle(surface, (241, 91, 61), mine.position, radius, 1)

    @staticmethod
    def draw_particles(surface: pygame.Surface, particles: list[Particle]) -> None:
        for particle in particles:
            alpha = clamp(particle.life / particle.max_life, 0, 1)
            color = tuple(int(channel * alpha) for channel in particle.color)
            pygame.draw.circle(surface, color, particle.position, max(1, int(particle.size * alpha)))

    def draw_reticle(self, surface: pygame.Surface) -> None:
        if not self.game.mouse_on_board or self.game.state != "playing":
            return
        radius = 10 + math.sin(self.game.elapsed * 5) * 1.5
        center = self.game.mouse_world
        pygame.draw.circle(surface, CREAM, center, int(radius), 1)
        pygame.draw.line(surface, CREAM, center + Vec2(-18, 0), center + Vec2(-6, 0), 1)
        pygame.draw.line(surface, CREAM, center + Vec2(18, 0), center + Vec2(6, 0), 1)
        pygame.draw.line(surface, CREAM, center + Vec2(0, -18), center + Vec2(0, -6), 1)
        pygame.draw.line(surface, CREAM, center + Vec2(0, 18), center + Vec2(0, 6), 1)

    def draw_aim_guide(self, surface: pygame.Surface) -> None:
        player = self.game.player
        if not player.alive or not self.game.mouse_on_board or self.game.state != "playing":
            return
        difference = self.game.mouse_world - player.position
        if difference.length() <= 35:
            return
        direction = difference.normalize()
        start = player.position + direction * 34
        length = start.distance_to(self.game.mouse_world)
        dash_length = 7
        gap = 7
        for distance in range(0, max(0, int(length - 8)), dash_length + gap):
            dash_start = start + direction * distance
            dash_end = start + direction * min(distance + dash_length, length - 8)
            pygame.draw.line(surface, (111, 205, 219), dash_start, dash_end, 1)

    def draw_hud(self) -> None:
        screen = self.game.screen
        screen.fill(BACKGROUND)
        cyb = self.title_font.render("CYB", True, CREAM)
        tanks = self.title_font.render("TANKS", True, PLAYER_COLOR)
        screen.blit(cyb, (20, 7))
        screen.blit(tanks, (20 + cyb.get_width(), 7))
        subtitle = self.small_font.render("SIMULADOR TACTICO // GRID 07", True, MUTED)
        screen.blit(subtitle, (22, 57))

        controls = self.small_font.render(
            "WASD/FLECHAS   LMB: DISPARAR   ESPACIO: MINA   R: REINTENTAR",
            True,
            MUTED,
        )
        screen.blit(controls, (285, 23))
        rule = self.small_font.render(
            "CLARO: REBOTE PRECISO   //   OSCURO: REBOTE IMPRECISO",
            True,
            CREAM,
        )
        screen.blit(rule, (285, 47))

        remaining = sum(enemy.alive for enemy in self.game.enemies)
        player_bullets = self.game.combat.active_bullets(self.game.player)
        player_mines = self.game.mine_system.active_mines(self.game.player)
        if self.game.state == "level_clear":
            status = f"NIVEL {self.game.level:02d} SUPERADO"
            status_color = (132, 232, 211)
        elif self.game.state == "life_lost":
            status = f"VIDA PERDIDA   VIDAS: {self.game.lives}/{MAX_PLAYER_LIVES}"
            status_color = (255, 181, 112)
        elif self.game.state == "game_over":
            status = "SIN VIDAS"
            status_color = (255, 135, 112)
        else:
            status = (
                f"NIVEL {self.game.level:02d}   HOSTILES: {remaining}   "
                f"BALAS: {player_bullets}/{MAX_PLAYER_BULLETS}   "
                f"MINAS: {player_mines}/{self.game.player.max_mines}   "
                f"VIDAS: {self.game.lives}/{MAX_PLAYER_LIVES}"
            )
            status_color = LIGHT_GRAY
        status_surface = self.hud_font.render(status, True, status_color)
        screen.blit(status_surface, (BOARD_WIDTH - status_surface.get_width() - 20, 63))
        pygame.draw.line(screen, (67, 82, 70), (0, HUD_HEIGHT - 1), (BOARD_WIDTH, HUD_HEIGHT - 1), 1)

    def draw_end_screen(self, board: pygame.Surface) -> None:
        if self.game.state == "playing":
            return
        overlay = pygame.Surface((BOARD_WIDTH, BOARD_HEIGHT), pygame.SRCALPHA)
        overlay.fill((7, 12, 8, 205))
        board.blit(overlay, (0, 0))
        level_clear = self.game.state == "level_clear"
        life_lost = self.game.state == "life_lost"
        if level_clear:
            text = f"NIVEL {self.game.level} SUPERADO"
            prompt_text = "CLIC O ENTER: SIGUIENTE NIVEL"
            color = (143, 232, 215)
        elif life_lost:
            text = "VIDA PERDIDA"
            prompt_text = "PULSA R O HAZ CLIC PARA REAPARECER"
            color = (255, 181, 112)
        else:
            text = "SIN VIDAS"
            prompt_text = "PULSA R O HAZ CLIC PARA REINICIAR EL NIVEL"
            color = (255, 139, 114)
        title = self.end_font.render(text, True, color)
        prompt = self.hud_font.render(prompt_text, True, CREAM)
        board.blit(title, title.get_rect(center=(BOARD_WIDTH // 2, BOARD_HEIGHT // 2 - 25)))
        board.blit(prompt, prompt.get_rect(center=(BOARD_WIDTH // 2, BOARD_HEIGHT // 2 + 34)))

    def render(self) -> None:
        self.draw_hud()
        board = self.board_background.copy()
        self.draw_aim_guide(board)
        self.draw_mines(board)
        for wreck in self.game.wrecks:
            self.draw_wreck(board, wreck)
        for enemy in self.game.enemies:
            self.draw_tank(board, enemy)
        self.draw_tank(board, self.game.player)
        self.draw_bullets(board)
        self.draw_particles(board, self.game.particles)
        self.draw_reticle(board)
        self.draw_end_screen(board)
        self.game.screen.blit(board, (0, HUD_HEIGHT))
        pygame.display.flip()
