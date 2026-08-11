from __future__ import annotations

import unittest
from types import SimpleNamespace

from cybtanks.catalog import load_enemy_catalog
from cybtanks.combat import CombatSystem
from cybtanks.config import (
    BULLET_SPEEDS,
    COLS,
    FIRE_RATE_DELAYS,
    MINE_EXPLOSION_RADIUS,
    MOVEMENT_SPEEDS,
    ROWS,
    SHIELD_FLASH_DURATION,
    SHOT_THINK_DELAYS,
)
from cybtanks.enemy_ai import EnemyAISystem
from cybtanks.levels import enemy_layout, shielded_dark_gray_count
from cybtanks.mines import MineSystem
from cybtanks.models import Bullet, Mine, Tank, Vec2
from cybtanks.world import World, cell_center


def make_tank(
    tank_id: int,
    team: str,
    position: Vec2,
    *,
    kind: str = "test",
    intelligence: str = "medium",
    speed: float = 0.0,
    shield_hits: int = 0,
) -> Tank:
    return Tank(
        tank_id=tank_id,
        team=team,
        kind=kind,
        spawn_cell=(1, 1),
        position=position,
        body_angle=0.0,
        turret_angle=0.0,
        speed=speed,
        color=(100, 100, 100),
        bullet_speed_class="slow",
        bullet_speed=BULLET_SPEEDS["slow"],
        max_bullets=1,
        max_bounces=1,
        max_mines=0,
        fire_rate="slow",
        shot_think_speed="slow",
        intelligence=intelligence,
        ricochet_accuracy="accurate",
        ricochet_success_rate=1.0,
        self_safe=True,
        shield_hits=shield_hits,
    )


class PinkTankTests(unittest.TestCase):
    def test_catalog_contains_requested_pink_attributes(self) -> None:
        pink = load_enemy_catalog()["pink"]

        self.assertEqual(MOVEMENT_SPEEDS[pink["velocidad_movimiento"]], 125.0)
        self.assertEqual(BULLET_SPEEDS[pink["velocidad_bala"]], 230.0)
        self.assertEqual(int(pink["rebotes_bala"]), 1)
        self.assertEqual(int(pink["maximo_minas"]), 0)
        self.assertEqual(FIRE_RATE_DELAYS[pink["cadencia_disparo"]], 0.5)
        self.assertEqual(pink["nivel_inteligencia"], "tactical")
        self.assertEqual(BULLET_SPEEDS["fast"], 516.0)

    def test_pink_enters_level_rotation_at_level_ten(self) -> None:
        self.assertNotIn("pink", {kind for kind, _ in enemy_layout(9)})
        self.assertIn("pink", {kind for kind, _ in enemy_layout(10)})

    def test_tactical_path_keeps_standoff_distance(self) -> None:
        layout = tuple(
            tuple(
                1 if col in (0, COLS - 1) or row in (0, ROWS - 1) else 0
                for col in range(COLS)
            )
            for row in range(ROWS)
        )
        world = World()
        world.reset(layout)
        player = make_tank(1, "player", cell_center((8, 6)))
        pink = make_tank(
            2,
            "enemy",
            cell_center((1, 1)),
            kind="pink",
            intelligence="tactical",
            speed=MOVEMENT_SPEEDS["medium"],
        )
        game = SimpleNamespace(
            world=world,
            player=player,
            enemies=[pink],
            mines=[],
            combat=SimpleNamespace(
                active_bullets=lambda tank: 0,
                movement_safe_from_friendly_fire=lambda tank, movement: True,
            ),
        )
        game.all_tanks = lambda: [player, pink]
        ai = EnemyAISystem(game)

        ai.plan_path(pink)

        self.assertIsNotNone(pink.goal)
        distance = abs(pink.goal[0] - 8) + abs(pink.goal[1] - 6)
        self.assertGreaterEqual(distance, 3)
        self.assertLessEqual(distance, 5)
        self.assertTrue(pink.path)

        old_goal = pink.goal
        player.position = cell_center(old_goal)
        pink.plan_timer = 0
        pink.fire_timer = 10

        ai.update_enemy(pink, 0.0)

        new_player_cell = old_goal
        new_distance = abs(pink.goal[0] - new_player_cell[0]) + abs(
            pink.goal[1] - new_player_cell[1]
        )
        self.assertGreaterEqual(new_distance, 3)
        self.assertLessEqual(new_distance, 5)


class ShieldTests(unittest.TestCase):
    def test_advanced_levels_unlock_dark_gray_shields(self) -> None:
        self.assertEqual(shielded_dark_gray_count(11), 0)
        self.assertEqual(shielded_dark_gray_count(12), 1)
        self.assertEqual(shielded_dark_gray_count(20), 1)
        self.assertEqual(shielded_dark_gray_count(21), 2)

    def test_shield_absorbs_exactly_one_bullet_hit(self) -> None:
        tank = make_tank(1, "enemy", Vec2(200, 200), shield_hits=1)
        destroyed: list[Tank] = []
        game = SimpleNamespace(
            create_burst=lambda *args: None,
            destroy_tank=lambda target: (destroyed.append(target), setattr(target, "alive", False)),
        )
        combat = CombatSystem(game)

        combat.hit_tank(tank)

        self.assertTrue(tank.alive)
        self.assertEqual(tank.shield_hits, 0)
        self.assertEqual(tank.shield_flash, SHIELD_FLASH_DURATION)
        self.assertFalse(destroyed)

        combat.hit_tank(tank)

        self.assertFalse(tank.alive)
        self.assertEqual(destroyed, [tank])


class MineExplosionBulletTests(unittest.TestCase):
    def test_explosion_destroys_bullets_inside_and_on_radius(self) -> None:
        center = Vec2(500, 400)
        owner = make_tank(7, "enemy", Vec2(100, 100))
        inside = Bullet(center + Vec2(MINE_EXPLOSION_RADIUS - 1, 0), Vec2(), "enemy", 7, (1, 2, 3))
        boundary = Bullet(center + Vec2(MINE_EXPLOSION_RADIUS, 0), Vec2(), "enemy", 7, (1, 2, 3))
        outside = Bullet(center + Vec2(MINE_EXPLOSION_RADIUS + 0.01, 0), Vec2(), "enemy", 7, (1, 2, 3))
        mine = Mine(center.copy(), 99, "enemy")
        sounds: list[str] = []
        game = SimpleNamespace(
            bullets=[inside, boundary, outside],
            mines=[mine],
            enemies=[],
            audio=SimpleNamespace(
                play_bullet_disintegrate=lambda: sounds.append("disintegrate")
            ),
            create_burst=lambda *args: None,
            create_explosion=lambda *args: None,
            all_tanks=lambda: [owner],
            destroy_tank=lambda *args, **kwargs: None,
            world=SimpleNamespace(break_walls=lambda *args: 0),
            renderer=SimpleNamespace(rebuild_board_background=lambda: None),
        )
        game.combat = CombatSystem(game)
        game.mine_system = MineSystem(game)

        game.mine_system.explode(mine)

        self.assertFalse(inside.alive)
        self.assertFalse(boundary.alive)
        self.assertTrue(outside.alive)
        self.assertEqual(sounds, ["disintegrate", "disintegrate"])
        self.assertEqual(owner.shot_think_timer, SHOT_THINK_DELAYS["slow"])

        game.mine_system.update(0.0)
        self.assertEqual(game.bullets, [outside])


if __name__ == "__main__":
    unittest.main()
