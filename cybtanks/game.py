from __future__ import annotations

import math
import random

import pygame

from .audio import AudioSystem
from .catalog import load_enemy_catalog, parse_hex_color
from .combat import CombatSystem
from .config import (
    BOARD_HEIGHT,
    BOARD_WIDTH,
    BULLET_SPEEDS,
    HUD_HEIGHT,
    MAX_BOUNCES,
    MAX_PLAYER_BULLETS,
    MAX_PLAYER_MINES,
    MOVEMENT_SPEEDS,
    PLAYER_BULLET_SPEED,
    PLAYER_COLOR,
    PLAYER_FIRE_RATE,
    PLAYER_SPEED,
    TILE,
    WINDOW_SIZE,
)
from .enemy_ai import EnemyAISystem
from .geometry import clamp
from .levels import enemy_layout
from .mines import MineSystem
from .models import Bullet, Mine, Particle, Tank, Vec2
from .renderer import Renderer
from .world import World, cell_center


class Game:
    def __init__(self) -> None:
        pygame.mixer.pre_init(22_050, -16, 1, 256)
        pygame.init()
        pygame.display.set_caption("CybTanks")
        self.screen = pygame.display.set_mode(WINDOW_SIZE)
        self.clock = pygame.time.Clock()
        self.running = True
        self.next_tank_id = 1
        self.elapsed = 0.0
        self.mouse_world = Vec2()
        self.mouse_on_board = False
        self.state = "playing"
        self.player: Tank
        self.enemies: list[Tank]
        self.bullets: list[Bullet]
        self.mines: list[Mine]
        self.particles: list[Particle]
        self.wrecks: list[tuple[Vec2, float, tuple[int, int, int]]]

        self.enemy_catalog = load_enemy_catalog()
        self.world = World()
        self.audio = AudioSystem()
        self.combat = CombatSystem(self)
        self.mine_system = MineSystem(self)
        self.enemy_ai = EnemyAISystem(self)
        self.renderer = Renderer(self)
        self.reset_campaign()

    def make_tank(
        self,
        team: str,
        col: int,
        row: int,
        index: int = 0,
        kind: str = "player",
    ) -> Tank:
        is_player = team == "player"
        if is_player:
            speed = PLAYER_SPEED
            color = PLAYER_COLOR
            bullet_speed = PLAYER_BULLET_SPEED
            max_bullets = MAX_PLAYER_BULLETS
            max_bounces = MAX_BOUNCES
            max_mines = MAX_PLAYER_MINES
            fire_rate = PLAYER_FIRE_RATE
            intelligence = "player"
            ricochet_accuracy = "manual"
            ricochet_success_rate = 1.0
            self_safe = False
        else:
            config = self.enemy_catalog[kind]
            speed = MOVEMENT_SPEEDS[config["velocidad_movimiento"]]
            color = parse_hex_color(config["color_hex"])
            bullet_speed = BULLET_SPEEDS[config["velocidad_bala"]]
            max_bullets = int(config["maximo_balas"])
            max_bounces = int(config["rebotes_bala"])
            max_mines = int(config["maximo_minas"])
            fire_rate = config["cadencia_disparo"]
            intelligence = config["nivel_inteligencia"]
            ricochet_accuracy = config["calculo_rebote"]
            ricochet_success_rate = float(config["probabilidad_acierto_rebote"])
            self_safe = config["evita_autodestruccion"].lower() == "true"

        tank = Tank(
            tank_id=self.next_tank_id,
            team=team,
            kind=kind,
            position=cell_center((col, row)),
            body_angle=0.0 if is_player else math.pi,
            turret_angle=0.0 if is_player else math.pi,
            speed=speed,
            color=color,
            bullet_speed=bullet_speed,
            max_bullets=max_bullets,
            max_bounces=max_bounces,
            max_mines=max_mines,
            fire_rate=fire_rate,
            intelligence=intelligence,
            ricochet_accuracy=ricochet_accuracy,
            ricochet_success_rate=ricochet_success_rate,
            self_safe=self_safe,
            fire_timer=1.0 + index * 0.28,
            mine_timer=1.4 + index * 0.25,
            plan_timer=index * 0.18,
        )
        self.next_tank_id += 1
        return tank

    def reset_campaign(self) -> None:
        self.level = 1
        self.start_level()

    def start_level(self) -> None:
        self.next_tank_id = 1
        self.elapsed = 0.0
        self.state = "playing"
        self.world.reset()
        self.renderer.rebuild_board_background()
        self.bullets = []
        self.mines = []
        self.particles = []
        self.wrecks = []
        self.player = self.make_tank("player", 1, 1)

        self.enemies = [
            self.make_tank("enemy", col, row, index, kind)
            for index, (kind, (col, row)) in enumerate(enemy_layout(self.level))
        ]
        self.mouse_world = self.player.position + Vec2(TILE * 2, 0)

    def next_level(self) -> None:
        self.level += 1
        self.start_level()

    def all_tanks(self) -> list[Tank]:
        return [self.player, *self.enemies]

    def update_player(self, dt: float) -> None:
        if not self.player.alive:
            return
        keys = pygame.key.get_pressed()
        horizontal = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(
            keys[pygame.K_a] or keys[pygame.K_LEFT]
        )
        vertical = int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(
            keys[pygame.K_w] or keys[pygame.K_UP]
        )
        direction = Vec2(horizontal, vertical)

        if direction.length_squared() > 0:
            direction.normalize_ip()
            actual_movement = self.world.move_tank(
                self.player,
                direction * self.player.speed * dt,
                self.all_tanks(),
            )
            self.player.velocity = actual_movement / dt if dt > 0 else Vec2()
            if actual_movement.length_squared() > 0:
                self.player.body_angle = math.atan2(actual_movement.y, actual_movement.x)
        else:
            self.player.velocity.update(0, 0)

        aim = self.mouse_world - self.player.position
        if aim.length_squared() > 0:
            self.player.turret_angle = math.atan2(aim.y, aim.x)

    def destroy_tank(self, tank: Tank) -> None:
        if not tank.alive:
            return
        tank.alive = False
        self.wrecks.append((tank.position.copy(), tank.body_angle, tank.color))
        self.create_burst(tank.position, tank.color, 28, 145)
        self.create_burst(tank.position, (246, 224, 164), 12, 95)

    def create_burst(
        self,
        position: Vec2,
        color: tuple[int, int, int],
        amount: int,
        force: float,
    ) -> None:
        for _ in range(amount):
            angle = random.random() * math.tau
            speed = force * (0.35 + random.random() * 0.8)
            life = 0.18 + random.random() * 0.28
            self.particles.append(
                Particle(
                    position=position.copy(),
                    velocity=Vec2(math.cos(angle), math.sin(angle)) * speed,
                    color=color,
                    size=1.5 + random.random() * 3.5,
                    life=life,
                    max_life=life,
                )
            )

    def update_particles(self, dt: float) -> None:
        drag = 0.06**dt
        for particle in self.particles:
            particle.life -= dt
            particle.position += particle.velocity * dt
            particle.velocity *= drag
        self.particles = [particle for particle in self.particles if particle.life > 0]

    def evaluate_state(self) -> None:
        if not self.player.alive:
            self.state = "lost"
        elif all(not enemy.alive for enemy in self.enemies):
            self.state = "level_clear"

    def update_mouse(self, position: tuple[int, int]) -> None:
        x, y = position
        self.mouse_on_board = 0 <= x < BOARD_WIDTH and HUD_HEIGHT <= y < HUD_HEIGHT + BOARD_HEIGHT
        self.mouse_world.update(
            clamp(x, 0, BOARD_WIDTH),
            clamp(y - HUD_HEIGHT, 0, BOARD_HEIGHT),
        )

    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_r:
                    self.start_level()
                elif event.key == pygame.K_SPACE and self.state == "playing":
                    self.mine_system.place(self.player)
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.state == "level_clear":
                    self.next_level()
            elif event.type == pygame.MOUSEMOTION:
                self.update_mouse(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.update_mouse(event.pos)
                if self.state == "level_clear":
                    self.next_level()
                elif self.state == "lost":
                    self.start_level()
                elif self.mouse_on_board:
                    self.combat.shoot(self.player)

    def update(self, dt: float) -> None:
        self.elapsed += dt
        self.update_mouse(pygame.mouse.get_pos())
        for tank in self.all_tanks():
            tank.cooldown = max(0.0, tank.cooldown - dt)

        if self.state == "playing":
            self.update_player(dt)
            self.enemy_ai.update(dt)
            self.combat.update(dt)
            self.mine_system.update(dt)
            self.evaluate_state()
        self.update_particles(dt)

    def render(self) -> None:
        self.renderer.render()

    def run(self) -> None:
        while self.running:
            dt = min(self.clock.tick(60) / 1000.0, 1 / 30)
            self.handle_events()
            self.update(dt)
            self.render()
        pygame.quit()
