from __future__ import annotations

import math
import random

import pygame

from .ai_config import load_ai_settings
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
    PLAYER_SHOT_THINK_SPEED,
    PLAYER_STARTING_LIVES,
    PLAYER_SPEED,
    TILE,
    TRACK_SPACING,
    WINDOW_SIZE,
)
from .enemy_ai import EnemyAISystem
from .geometry import clamp
from .input_manager import InputManager
from .levels import enemy_layout, map_layout, player_spawn, shielded_dark_gray_count
from .mines import MineSystem
from .models import Bullet, ExplosionEffect, Mine, Particle, Tank, TrackMark, Vec2
from .renderer import Renderer
from .world import World, cell_center


def enemy_initial_fire_delay(kind: str, index: int) -> float:
    return load_ai_settings().initial_fire_delay(kind, index)


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
        self.explosions: list[ExplosionEffect]
        self.track_marks: list[TrackMark]
        self.track_progress: dict[int, float]
        self.wrecks: list[tuple[Vec2, float, tuple[int, int, int]]]

        self.ai_settings = load_ai_settings()
        self.enemy_catalog = load_enemy_catalog()
        self.world = World()
        self.audio = AudioSystem()
        self.combat = CombatSystem(self)
        self.mine_system = MineSystem(self)
        self.enemy_ai = EnemyAISystem(self)
        self.renderer = Renderer(self)
        self.input_manager = InputManager()
        self.reset_campaign()

    def make_tank(
        self,
        team: str,
        col: int,
        row: int,
        index: int = 0,
        kind: str = "player",
        shield_hits: int = 0,
    ) -> Tank:
        is_player = team == "player"
        if is_player:
            speed = PLAYER_SPEED
            color = PLAYER_COLOR
            bullet_speed_class = "slow"
            bullet_speed = PLAYER_BULLET_SPEED
            max_bullets = MAX_PLAYER_BULLETS
            max_bounces = MAX_BOUNCES
            max_mines = MAX_PLAYER_MINES
            fire_rate = PLAYER_FIRE_RATE
            shot_think_speed = PLAYER_SHOT_THINK_SPEED
            intelligence = "player"
            ricochet_accuracy = "manual"
            ricochet_success_rate = 1.0
            self_safe = False
        else:
            config = self.enemy_catalog[kind]
            speed = MOVEMENT_SPEEDS[config["velocidad_movimiento"]]
            color = parse_hex_color(config["color_hex"])
            bullet_speed_class = config["velocidad_bala"]
            bullet_speed = BULLET_SPEEDS[bullet_speed_class]
            max_bullets = int(config["maximo_balas"])
            max_bounces = int(config["rebotes_bala"])
            max_mines = int(config["maximo_minas"])
            fire_rate = config["cadencia_disparo"]
            shot_think_speed = config["tiempo_pensar_disparo"]
            intelligence = config["nivel_inteligencia"]
            ricochet_accuracy = config["calculo_rebote"]
            ricochet_success_rate = float(config["probabilidad_acierto_rebote"])
            self_safe = config["evita_autodestruccion"].lower() == "true"

        tank = Tank(
            tank_id=self.next_tank_id,
            team=team,
            kind=kind,
            spawn_cell=(col, row),
            position=cell_center((col, row)),
            body_angle=0.0 if is_player else math.pi,
            turret_angle=0.0 if is_player else math.pi,
            speed=speed,
            color=color,
            bullet_speed_class=bullet_speed_class,
            bullet_speed=bullet_speed,
            max_bullets=max_bullets,
            max_bounces=max_bounces,
            max_mines=max_mines,
            fire_rate=fire_rate,
            shot_think_speed=shot_think_speed,
            intelligence=intelligence,
            ricochet_accuracy=ricochet_accuracy,
            ricochet_success_rate=ricochet_success_rate,
            self_safe=self_safe,
            shield_hits=shield_hits,
            max_shield_hits=shield_hits,
        )
        if not is_player:
            self.enemy_ai.initialize_enemy(tank, index)
        self.next_tank_id += 1
        return tank

    def reset_campaign(self) -> None:
        self.level = 1
        self.lives = PLAYER_STARTING_LIVES
        self.start_level(reset_lives=False)

    def start_level(self, reset_lives: bool = True) -> None:
        self.next_tank_id = 1
        self.elapsed = 0.0
        self.state = "playing"
        if reset_lives:
            self.lives = PLAYER_STARTING_LIVES
        self.world.reset(map_layout(self.level))
        self.enemy_ai.reset()
        self.renderer.rebuild_board_background()
        self.bullets = []
        self.mines = []
        self.particles = []
        self.explosions = []
        self.track_marks = []
        self.track_progress = {}
        self.wrecks = []
        self.player_spawn_cell = player_spawn(self.level)
        self.player = self.make_tank("player", *self.player_spawn_cell)

        self.enemies = []
        shielded_remaining = shielded_dark_gray_count(self.level)
        for index, (kind, (col, row)) in enumerate(enemy_layout(self.level)):
            shield_hits = int(kind == "dark_gray" and shielded_remaining > 0)
            if shield_hits:
                shielded_remaining -= 1
            self.enemies.append(
                self.make_tank(
                    "enemy",
                    col,
                    row,
                    index,
                    kind,
                    shield_hits=shield_hits,
                )
            )
        self.mouse_world = self.player.position + Vec2(TILE * 2, 0)

    def next_level(self) -> None:
        if self.level % 5 == 0:
            self.lives += 1
        self.level += 1
        self.start_level(reset_lives=False)

    def respawn_player(self) -> None:
        if self.lives <= 0:
            return
        self.world.reset()
        self.renderer.rebuild_board_background()
        self.bullets = []
        self.mines = []
        self.particles = []
        self.explosions = []
        self.track_marks = []
        self.track_progress = {}
        self.wrecks = [wreck for wreck in self.wrecks if wreck[2] != PLAYER_COLOR]
        self.enemy_ai.reset()

        for index, enemy in enumerate(self.enemies):
            if not enemy.alive:
                continue
            enemy.position = cell_center(enemy.spawn_cell)
            enemy.body_angle = math.pi
            enemy.turret_angle = math.pi
            enemy.shield_flash = 0
            self.enemy_ai.initialize_enemy(enemy, index)

        self.player = self.make_tank("player", *self.player_spawn_cell)
        self.player.position = cell_center(self.safe_respawn_cell())
        self.state = "playing"

    def safe_respawn_cell(self) -> tuple[int, int]:
        candidates = []
        for row in range(len(self.world.tiles)):
            for col in range(len(self.world.tiles[row])):
                cell = (col, row)
                if self.world.is_wall(cell):
                    continue
                position = cell_center(cell)
                if any(
                    enemy.alive and position.distance_to(enemy.position) < TILE * 1.5
                    for enemy in self.enemies
                ):
                    continue
                distance_from_start = abs(col - self.player_spawn_cell[0]) + abs(
                    row - self.player_spawn_cell[1]
                )
                candidates.append((distance_from_start, cell))
        return min(candidates)[1] if candidates else self.player_spawn_cell

    def all_tanks(self) -> list[Tank]:
        return [self.player, *self.enemies]

    def update_player(self, dt: float) -> None:
        if not self.player.alive:
            return
        input_state = self.input_manager.update(self.player.position)
        direction = input_state.move_vector.copy()

        if direction.length_squared() > 0:
            if direction.length_squared() > 1.0:
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

        aim = input_state.aim_vector
        if aim.length_squared() > 0:
            self.player.turret_angle = math.atan2(aim.y, aim.x)

        self.mouse_world = input_state.aim_world_pos
        self.mouse_on_board = (input_state.active_mode == "GAMEPAD") or (
            0 <= self.mouse_world.x <= BOARD_WIDTH and 0 <= self.mouse_world.y <= BOARD_HEIGHT
        )

        if input_state.shoot_triggered:
            self.combat.shoot(self.player)
        if input_state.special_triggered and self.state == "playing":
            self.mine_system.place(self.player)

    def destroy_tank(self, tank: Tank, play_destruction_sound: bool = True) -> None:
        if not tank.alive:
            return
        tank.alive = False
        if tank.team == "player":
            self.input_manager.rumble(0.8, 0.8, 400)
        self.wrecks.append((tank.position.copy(), tank.body_angle, tank.color))
        self.create_burst(tank.position, tank.color, 28, 145)
        self.create_burst(tank.position, (246, 224, 164), 12, 95)
        if play_destruction_sound:
            self.audio.play_tank_destroyed()
        self.report_ai_sound(tank.position, "tank_destroyed", tank.team)

    def report_ai_sound(self, position: Vec2, kind: str, source_team: str) -> None:
        self.enemy_ai.report_sound(position, kind, source_team)

    def create_explosion(self, position: Vec2, radius: float) -> None:
        self.explosions.append(ExplosionEffect(position.copy(), radius))
        self.audio.play_explosion()

    def record_tank_tracks(self, starting_positions: dict[int, Vec2]) -> None:
        for tank in self.all_tanks():
            start = starting_positions.get(tank.tank_id)
            if not tank.alive or start is None:
                continue
            movement = tank.position - start
            distance = movement.length()
            if distance <= 0.001:
                continue

            carried_distance = self.track_progress.get(tank.tank_id, 0.0)
            next_mark = TRACK_SPACING - carried_distance
            direction = movement / distance
            angle = math.atan2(direction.y, direction.x)
            while next_mark <= distance:
                self.track_marks.append(TrackMark(start + direction * next_mark, angle))
                next_mark += TRACK_SPACING
            self.track_progress[tank.tank_id] = (carried_distance + distance) % TRACK_SPACING

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

    def update_effects(self, dt: float) -> None:
        for explosion in self.explosions:
            explosion.age += dt
        self.explosions = [
            explosion for explosion in self.explosions if explosion.age < explosion.duration
        ]

        for track in self.track_marks:
            track.age += dt
        self.track_marks = [track for track in self.track_marks if track.age < track.lifetime]

    def evaluate_state(self) -> None:
        if self.state != "playing":
            return
        if not self.player.alive:
            self.lives = max(0, self.lives - 1)
            self.state = "life_lost" if self.lives > 0 else "game_over"
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
            self.input_manager.handle_event(event)
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_r:
                    if self.state == "life_lost":
                        self.respawn_player()
                    else:
                        self.start_level()
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.state == "level_clear":
                    self.next_level()
            elif event.type == pygame.MOUSEMOTION:
                self.update_mouse(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.update_mouse(event.pos)
                if self.state == "level_clear":
                    self.next_level()
                elif self.state == "life_lost":
                    self.respawn_player()
                elif self.state == "game_over":
                    self.start_level()

        if self.input_manager.restart_triggered:
            if self.state == "life_lost":
                self.respawn_player()
            else:
                self.start_level()
        elif self.input_manager.confirm_triggered:
            if self.state == "level_clear":
                self.next_level()
            elif self.state == "life_lost":
                self.respawn_player()
            elif self.state == "game_over":
                self.start_level()
        elif self.input_manager.escape_triggered:
            self.running = False

    def update(self, dt: float) -> None:
        self.elapsed += dt
        self.update_mouse(pygame.mouse.get_pos())
        for tank in self.all_tanks():
            tank.cooldown = max(0.0, tank.cooldown - dt)
            tank.shot_think_timer = max(0.0, tank.shot_think_timer - dt)
            tank.shield_flash = max(0.0, tank.shield_flash - dt)

        if self.state == "playing":
            starting_positions = {
                tank.tank_id: tank.position.copy() for tank in self.all_tanks() if tank.alive
            }
            self.update_player(dt)
            self.enemy_ai.update(dt)
            self.record_tank_tracks(starting_positions)
            self.combat.update(dt)
            self.mine_system.update(dt)
            self.evaluate_state()
        else:
            self.input_manager.update(self.player.position if hasattr(self, "player") else None)
        self.update_particles(dt)
        self.update_effects(dt)

    def render(self) -> None:
        self.renderer.render()

    def run(self) -> None:
        while self.running:
            dt = min(self.clock.tick(60) / 1000.0, 1 / 30)
            self.handle_events()
            self.update(dt)
            self.render()
        pygame.quit()
