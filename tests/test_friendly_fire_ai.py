from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from cybtanks.catalog import load_enemy_catalog
from cybtanks.combat import CombatSystem
from cybtanks.config import COLS, FIRE_RATE_DELAYS, MAP_LAYOUTS, ROWS, SHOT_THINK_DELAYS
from cybtanks.enemy_ai import EnemyAISystem
from cybtanks.game import enemy_initial_fire_delay
from cybtanks.models import Bullet, Mine, ShotTrace, Tank, Vec2
from cybtanks.world import World, cell_center


def make_tank(
    tank_id: int,
    team: str,
    position: Vec2,
    speed: float = 0.0,
    kind: str = "test",
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
        color=(0, 0, 0),
        bullet_speed_class="slow",
        bullet_speed=230.0,
        max_bullets=1,
        max_bounces=1,
        max_mines=0,
        fire_rate="slow",
        shot_think_speed="slow",
        intelligence="medium",
        ricochet_accuracy="accurate",
        ricochet_success_rate=1.0,
        self_safe=True,
    )


class FriendlyFireTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        layout = tuple(
            tuple(
                1 if col in (0, COLS - 1) or row in (0, ROWS - 1) else 0
                for col in range(COLS)
            )
            for row in range(ROWS)
        )
        self.world = World()
        self.world.reset(layout)

    def make_combat(
        self,
        enemies: list[Tank],
        bullets: list[Bullet] | None = None,
    ) -> CombatSystem:
        game = SimpleNamespace(
            world=self.world,
            enemies=enemies,
            bullets=bullets or [],
        )
        return CombatSystem(game)

    def test_trace_blocks_crossing_between_route_points(self) -> None:
        shooter = make_tank(1, "enemy", Vec2(120, 175))
        target = make_tank(2, "player", Vec2(720, 175))
        ally = make_tank(3, "enemy", Vec2(330, 140))
        ally.path = [(5, 3)]
        combat = self.make_combat([shooter, ally])

        trace = combat.trace_shot(shooter, 0.0, target)

        self.assertTrue(trace.ally_hit)
        self.assertFalse(trace.target_hit)

    def test_trace_stops_at_target_before_ally_behind_it(self) -> None:
        shooter = make_tank(1, "enemy", Vec2(120, 175))
        target = make_tank(2, "player", Vec2(420, 175))
        ally = make_tank(3, "enemy", Vec2(600, 175))
        combat = self.make_combat([shooter, ally])

        trace = combat.trace_shot(shooter, 0.0, target)

        self.assertTrue(trace.target_hit)
        self.assertFalse(trace.ally_hit)

    def test_trace_rejects_ricochet_that_runtime_can_deflect_into_ally(self) -> None:
        self.world.reset(MAP_LAYOUTS[1])
        shooter = make_tank(1, "enemy", cell_center((11, 7)))
        target = make_tank(2, "player", cell_center((15, 3)))
        ally = make_tank(3, "enemy", Vec2(812.393, 258.522))
        combat = self.make_combat([shooter, ally])

        trace = combat.trace_shot(shooter, -1.1462992097, target)

        self.assertTrue(trace.ally_hit)
        self.assertFalse(trace.target_hit)

    def test_trace_rejects_immediate_bounce_while_bullet_touches_owner(self) -> None:
        shooter = make_tank(1, "enemy", Vec2(132.88, 78.48), speed=180.0)
        target = make_tank(2, "player", Vec2(800, 500))
        shooter.path = [(1, 1)]
        combat = self.make_combat([shooter])

        trace = combat.trace_shot(shooter, 3.79667, target)

        self.assertTrue(trace.self_hit)
        self.assertFalse(trace.target_hit)

    def test_runtime_follows_the_same_ricochet_authorized_by_trace(self) -> None:
        self.world.reset(MAP_LAYOUTS[7])
        shooter = make_tank(1, "enemy", cell_center((8, 2)))
        target = make_tank(2, "player", cell_center((14, 4)))
        ally = make_tank(3, "enemy", Vec2(571.179, 152.462))
        audio = SimpleNamespace(
            play_shot=lambda speed: None,
            play_bullet_bounce=lambda: None,
            play_bullet_disintegrate=lambda: None,
        )
        game = SimpleNamespace(
            world=self.world,
            player=target,
            enemies=[shooter, ally],
            bullets=[],
            state="playing",
            audio=audio,
            mine_system=SimpleNamespace(collide_bullet=lambda bullet: None),
            create_burst=lambda *args: None,
        )
        game.all_tanks = lambda: [target, shooter, ally]
        game.destroy_tank = lambda tank: setattr(tank, "alive", False)
        combat = CombatSystem(game)
        angle = 0.6798016278

        trace = combat.trace_shot(shooter, angle, target)
        shooter.turret_angle = angle
        self.assertTrue(combat.shoot(shooter))
        for _ in range(120):
            combat.update(1 / 60)

        self.assertTrue(trace.target_hit)
        self.assertFalse(trace.ally_hit)
        self.assertFalse(target.alive)
        self.assertTrue(ally.alive)

    def test_movement_does_not_enter_friendly_bullet_path(self) -> None:
        shooter = make_tank(1, "enemy", Vec2(120, 175))
        ally = make_tank(2, "enemy", Vec2(330, 220))
        bullet = Bullet(
            position=Vec2(145, 175),
            velocity=Vec2(230, 0),
            team="enemy",
            owner_id=shooter.tank_id,
            color=(0, 0, 0),
            max_bounces=0,
        )
        combat = self.make_combat([shooter, ally], [bullet])

        self.assertFalse(
            combat.movement_safe_from_friendly_fire(ally, Vec2(0, -20))
        )
        self.assertTrue(combat.movement_safe_from_friendly_fire(ally, Vec2(0, 10)))

    def test_self_safe_owner_disintegrates_own_bounced_bullet(self) -> None:
        owner = make_tank(1, "enemy", Vec2(300, 300))
        player = make_tank(2, "player", Vec2(800, 500))
        bullet = Bullet(
            position=owner.position.copy(),
            velocity=Vec2(),
            team="enemy",
            owner_id=owner.tank_id,
            color=(0, 0, 0),
            bounces=1,
            age=1.0,
        )
        audio = SimpleNamespace(
            play_bullet_disintegrate=lambda: None,
        )
        game = SimpleNamespace(
            world=self.world,
            player=player,
            enemies=[owner],
            bullets=[bullet],
            audio=audio,
            mine_system=SimpleNamespace(collide_bullet=lambda projectile: None),
            create_burst=lambda *args: None,
            destroy_tank=lambda tank: self.fail("Self-safe owner was destroyed"),
        )
        game.all_tanks = lambda: [player, owner]
        combat = CombatSystem(game)

        combat.update(0.0)

        self.assertTrue(owner.alive)
        self.assertEqual(game.bullets, [])
        self.assertEqual(owner.shot_think_timer, SHOT_THINK_DELAYS["slow"])

    def test_owner_without_self_safety_can_still_hit_itself(self) -> None:
        owner = make_tank(1, "enemy", Vec2(300, 300))
        owner.self_safe = False
        player = make_tank(2, "player", Vec2(800, 500))
        bullet = Bullet(
            position=owner.position.copy(),
            velocity=Vec2(),
            team="enemy",
            owner_id=owner.tank_id,
            color=(0, 0, 0),
            bounces=1,
            age=1.0,
        )
        game = SimpleNamespace(
            world=self.world,
            player=player,
            enemies=[owner],
            bullets=[bullet],
            audio=SimpleNamespace(play_bullet_disintegrate=lambda: None),
            mine_system=SimpleNamespace(collide_bullet=lambda projectile: None),
            create_burst=lambda *args: None,
            destroy_tank=lambda tank: setattr(tank, "alive", False),
        )
        game.all_tanks = lambda: [player, owner]
        combat = CombatSystem(game)

        combat.update(0.0)

        self.assertFalse(owner.alive)


class EnemyMovementTests(unittest.TestCase):
    def setUp(self) -> None:
        layout = tuple(
            tuple(
                1 if col in (0, COLS - 1) or row in (0, ROWS - 1) else 0
                for col in range(COLS)
            )
            for row in range(ROWS)
        )
        self.world = World()
        self.world.reset(layout)

    def make_ai(
        self,
        player: Tank,
        enemies: list[Tank],
        bullets: list[Bullet] | None = None,
    ) -> tuple[EnemyAISystem, CombatSystem]:
        game = SimpleNamespace(
            world=self.world,
            player=player,
            enemies=enemies,
            bullets=bullets or [],
            mines=[],
        )
        game.all_tanks = lambda: [game.player, *game.enemies]
        game.combat = CombatSystem(game)
        return EnemyAISystem(game), game.combat

    def test_occupied_cell_is_penalized_but_remains_traversable(self) -> None:
        layout = tuple(
            tuple(0 if row == 6 and 0 < col < COLS - 1 else 1 for col in range(COLS))
            for row in range(ROWS)
        )
        self.world.reset(layout)
        enemy = make_tank(1, "enemy", cell_center((2, 6)), speed=58.0)
        ally = make_tank(2, "enemy", cell_center((3, 6)), speed=58.0)
        player = make_tank(3, "player", cell_center((5, 6)))
        enemy.avoid_cell = (3, 6)
        enemy.avoid_timer = 1.0
        ai, _ = self.make_ai(player, [enemy, ally])

        ai.plan_path(enemy)

        self.assertTrue(enemy.path)
        self.assertIn((3, 6), enemy.path)

    def test_mobile_enemy_moves_with_own_active_bullet(self) -> None:
        enemy = make_tank(1, "enemy", cell_center((2, 2)), speed=58.0)
        player = make_tank(2, "player", cell_center((12, 2)))
        enemy.path = [(3, 2)]
        enemy.plan_timer = 1.0
        enemy.fire_timer = 1.0
        bullet = Bullet(
            position=cell_center((12, 8)),
            velocity=Vec2(230, 0),
            team="enemy",
            owner_id=enemy.tank_id,
            color=(0, 0, 0),
            max_bounces=0,
        )
        ai, _ = self.make_ai(player, [enemy], [bullet])
        start = enemy.position.copy()

        ai.update_enemy(enemy, 1 / 60)

        self.assertGreater(enemy.position.distance_to(start), 0)

    def test_mobile_enemy_replans_immediately_when_path_is_empty(self) -> None:
        enemy = make_tank(1, "enemy", cell_center((4, 6)), speed=58.0)
        player = make_tank(2, "player", cell_center((7, 6)))
        enemy.plan_timer = 1.0
        enemy.fire_timer = 1.0
        ai, _ = self.make_ai(player, [enemy])
        start = enemy.position.copy()

        ai.update_enemy(enemy, 1 / 60)

        self.assertTrue(enemy.path)
        self.assertGreater(enemy.position.distance_to(start), 0)

    def test_friendly_fire_avoidance_steers_without_stopping(self) -> None:
        shooter = make_tank(1, "enemy", Vec2(120, 175))
        enemy = make_tank(2, "enemy", Vec2(330, 220), speed=58.0)
        player = make_tank(3, "player", Vec2(800, 500))
        bullet = Bullet(
            position=Vec2(145, 175),
            velocity=Vec2(230, 0),
            team="enemy",
            owner_id=shooter.tank_id,
            color=(0, 0, 0),
            max_bounces=0,
        )
        ai, combat = self.make_ai(player, [shooter, enemy], [bullet])

        movement = ai.steer_around_friendly_fire(enemy, Vec2(0, -20))

        self.assertAlmostEqual(movement.length(), 20)
        self.assertTrue(combat.movement_safe_from_friendly_fire(enemy, movement))

    def test_unsafe_push_is_rejected_for_the_pushed_ally(self) -> None:
        shooter = make_tank(1, "enemy", Vec2(120, 175))
        ally = make_tank(2, "enemy", Vec2(330, 199))
        pusher = make_tank(3, "enemy", Vec2(330, 233), speed=58.0)
        player = make_tank(4, "player", Vec2(800, 500))
        bullet = Bullet(
            position=Vec2(325, 175),
            velocity=Vec2(230, 0),
            team="enemy",
            owner_id=shooter.tank_id,
            color=(0, 0, 0),
            max_bounces=0,
        )
        ai, _ = self.make_ai(player, [shooter, ally, pusher], [bullet])
        ally_start = ally.position.copy()

        movement = self.world.move_tank(
            pusher,
            Vec2(0, -6),
            [player, shooter, ally, pusher],
            lambda tank, pushed: tank.tank_id == pusher.tank_id
            or ai.enemy_push_safe_from_friendly_fire(tank, pushed),
        )

        self.assertEqual(movement, Vec2())
        self.assertEqual(ally.position, ally_start)

    def test_surrounded_enemy_chooses_safest_nonzero_direction(self) -> None:
        enemy = make_tank(1, "enemy", Vec2(300, 300), speed=58.0)
        player = make_tank(2, "player", Vec2(800, 500))
        bullets = [
            Bullet(Vec2(120, 273), Vec2(230, 0), "enemy", 10, (0, 0, 0), max_bounces=0),
            Bullet(Vec2(120, 327), Vec2(230, 0), "enemy", 11, (0, 0, 0), max_bounces=0),
            Bullet(Vec2(273, 120), Vec2(0, 230), "enemy", 12, (0, 0, 0), max_bounces=0),
            Bullet(Vec2(327, 120), Vec2(0, 230), "enemy", 13, (0, 0, 0), max_bounces=0),
        ]
        ai, _ = self.make_ai(player, [enemy], bullets)
        intended = Vec2(0, -6)

        movement = ai.steer_around_friendly_fire(enemy, intended)

        self.assertAlmostEqual(movement.length(), intended.length())
        self.assertNotEqual(movement, intended)

    def test_fast_enemy_does_not_oscillate_near_waypoint(self) -> None:
        waypoint = cell_center((3, 2))
        enemy = make_tank(1, "enemy", waypoint - Vec2(3, 0), speed=180.0)
        player = make_tank(2, "player", cell_center((8, 2)))
        enemy.path = [(3, 2), (4, 2)]
        enemy.goal = (4, 2)
        enemy.plan_timer = 1.0
        enemy.fire_timer = 1.0
        ai, _ = self.make_ai(player, [enemy])
        start_x = enemy.position.x

        ai.update_enemy(enemy, 1 / 30)

        self.assertEqual(enemy.path[0], (4, 2))
        self.assertGreater(enemy.position.x, start_x)

    def test_valid_path_is_not_replanned_just_because_timer_expired(self) -> None:
        enemy = make_tank(1, "enemy", cell_center((2, 2)), speed=58.0)
        player = make_tank(2, "player", cell_center((5, 2)))
        enemy.path = [(3, 2), (4, 2)]
        enemy.goal = (4, 2)
        enemy.plan_timer = 0.0
        enemy.fire_timer = 1.0
        ai, _ = self.make_ai(player, [enemy])
        replans = []
        original_plan_path = ai.plan_path

        def record_replan(tank: Tank) -> None:
            replans.append(tank.tank_id)
            original_plan_path(tank)

        ai.plan_path = record_replan

        ai.update_enemy(enemy, 1 / 60)

        self.assertEqual(replans, [])

    def test_successful_detour_keeps_direction_for_several_frames(self) -> None:
        enemy = make_tank(1, "enemy", Vec2(78, 150), speed=180.0)
        player = make_tank(2, "player", cell_center((3, 2)))
        enemy.path = [(0, 2)]
        enemy.goal = (0, 2)
        enemy.plan_timer = 1.0
        enemy.fire_timer = 1.0
        ai, _ = self.make_ai(player, [enemy])

        ai.update_enemy(enemy, 1 / 30)
        first_direction = enemy.velocity.normalize()
        first_timer = enemy.detour_timer
        ai.update_enemy(enemy, 1 / 30)

        self.assertGreater(first_timer, 0)
        self.assertGreater(enemy.detour_timer, 0)
        self.assertGreater(first_direction.dot(enemy.velocity.normalize()), 0.99)

    def test_stalled_tanks_in_same_cell_form_a_stable_queue(self) -> None:
        leader = make_tank(1, "enemy", Vec2(493, 522), speed=58.0)
        follower = make_tank(2, "enemy", Vec2(527, 522), speed=58.0)
        player = make_tank(3, "player", cell_center((1, 1)))
        leader.stationary_timer = 0.15
        follower.stationary_timer = 0.15
        ai, _ = self.make_ai(player, [leader, follower])
        intended = Vec2(0, 1)

        leader_movement = ai.coordinate_crowded_cell(leader, intended, 1 / 60)
        follower_movement = ai.coordinate_crowded_cell(follower, intended, 1 / 60)

        self.assertGreater(leader_movement.x, 0)
        self.assertGreater(follower_movement.x, 0)
        self.assertGreater(follower.detour_timer, 0)

    def test_touching_yellows_across_cells_form_queue_quickly(self) -> None:
        leader = make_tank(
            1,
            "enemy",
            Vec2(104.6, 98.1),
            speed=180.0,
            kind="yellow",
        )
        follower = make_tank(
            2,
            "enemy",
            Vec2(90.0, 129.2),
            speed=180.0,
            kind="yellow",
        )
        player = make_tank(3, "player", Vec2(800, 500))
        leader.stationary_timer = 0.06
        follower.stationary_timer = 0.06
        ai, _ = self.make_ai(player, [leader, follower])

        leader_movement = ai.coordinate_crowded_cell(
            leader,
            cell_center((1, 1)) - leader.position,
            1 / 60,
        )
        follower_movement = ai.coordinate_crowded_cell(
            follower,
            cell_center((1, 1)) - follower.position,
            1 / 60,
        )

        self.assertLess(leader_movement.x, 0)
        self.assertLess(follower_movement.x, 0)
        self.assertGreater(follower.detour_timer, 0)

    def test_yellow_replans_bounded_movement_after_shorter_delay(self) -> None:
        enemy = make_tank(
            1,
            "enemy",
            cell_center((2, 2)),
            speed=180.0,
            kind="yellow",
        )
        player = make_tank(2, "player", cell_center((8, 2)))
        enemy.path = [(3, 2)]
        enemy.goal = (3, 2)
        enemy.plan_timer = 1.0
        enemy.fire_timer = 1.0
        enemy.net_stuck_timer = 0.21
        ai, _ = self.make_ai(player, [enemy])

        ai.update_enemy(enemy, 0.0)

        self.assertEqual(enemy.route_variant, 1)

    def test_yellow_replans_local_blockage_after_shorter_delay(self) -> None:
        enemy = make_tank(
            1,
            "enemy",
            cell_center((2, 2)),
            speed=180.0,
            kind="yellow",
        )
        player = make_tank(2, "player", cell_center((8, 2)))
        enemy.path = [(3, 2)]
        enemy.goal = (3, 2)
        enemy.plan_timer = 1.0
        enemy.fire_timer = 1.0
        enemy.stuck_timer = 0.21
        ai, _ = self.make_ai(player, [enemy])

        ai.update_enemy(enemy, 0.0)

        self.assertEqual(enemy.route_variant, 1)

    def test_full_speed_back_and_forth_counts_as_no_net_progress(self) -> None:
        enemy = make_tank(1, "enemy", Vec2(300, 300), speed=180.0)
        first = enemy.position.copy()
        second = first + Vec2(6, 0)

        for frame in range(31):
            enemy.position = first.copy() if frame % 2 == 0 else second.copy()
            EnemyAISystem.track_movement_progress(enemy, 1 / 60)

        self.assertGreaterEqual(enemy.net_stuck_timer, 0.45)

    def test_zero_dt_does_not_count_as_stuck_time(self) -> None:
        enemy = make_tank(1, "enemy", Vec2(300, 300), speed=58.0)
        EnemyAISystem.track_movement_progress(enemy, 1 / 60)
        timer = enemy.net_stuck_timer

        for _ in range(60):
            EnemyAISystem.track_movement_progress(enemy, 0.0)

        self.assertEqual(enemy.net_stuck_timer, timer)

    def test_new_mine_invalidates_a_route_that_crosses_its_danger_zone(self) -> None:
        enemy = make_tank(1, "enemy", cell_center((2, 2)), speed=58.0)
        player = make_tank(2, "player", cell_center((8, 2)))
        enemy.path = [(3, 2), (4, 2), (5, 2)]
        enemy.goal = (5, 2)
        enemy.plan_timer = 0.0
        enemy.fire_timer = 1.0
        ai, _ = self.make_ai(player, [enemy])
        ai.game.mines = [Mine(cell_center((5, 2)), owner_id=99, team="player")]
        replans = []
        original_plan_path = ai.plan_path

        def record_replan(tank: Tank) -> None:
            replans.append(tank.tank_id)
            original_plan_path(tank)

        ai.plan_path = record_replan

        ai.update_enemy(enemy, 1 / 60)

        self.assertEqual(replans, [enemy.tank_id])

    def test_new_mine_also_invalidates_an_existing_escape_route(self) -> None:
        enemy = make_tank(1, "enemy", cell_center((2, 2)), speed=58.0)
        player = make_tank(2, "player", cell_center((8, 2)))
        enemy.path = [(3, 2), (4, 2), (5, 2)]
        enemy.goal = (5, 2)
        enemy.plan_timer = 0.0
        enemy.fire_timer = 1.0
        enemy.escaping_mines = True
        ai, _ = self.make_ai(player, [enemy])
        ai.game.mines = [
            Mine(enemy.position.copy(), owner_id=98, team="player"),
            Mine(cell_center((5, 2)), owner_id=99, team="player"),
        ]
        replans = []
        original_plan_mine_escape = ai.plan_mine_escape

        def record_replan(tank: Tank) -> None:
            replans.append(tank.tank_id)
            original_plan_mine_escape(tank)

        ai.plan_mine_escape = record_replan

        ai.update_enemy(enemy, 1 / 60)

        self.assertEqual(replans, [enemy.tank_id])

    def test_crowded_cell_coordination_does_not_override_mine_escape(self) -> None:
        enemy = make_tank(1, "enemy", Vec2(300, 300), speed=58.0)
        ally = make_tank(2, "enemy", Vec2(320, 300), speed=58.0)
        player = make_tank(3, "player", Vec2(800, 500))
        enemy.net_stuck_timer = 0.15
        enemy.fire_timer = 1.0
        ai, _ = self.make_ai(player, [enemy, ally])
        ai.game.mines = [Mine(Vec2(400, 300), owner_id=99, team="player")]

        def reject_coordination(tank: Tank, movement: Vec2, dt: float) -> Vec2:
            raise AssertionError("Mine escape must take priority")

        ai.coordinate_crowded_cell = reject_coordination

        ai.update_enemy(enemy, 1 / 60)

    def test_ally_cannot_push_endangered_tank_towards_mine(self) -> None:
        ally = make_tank(1, "enemy", Vec2(276, 300), speed=58.0)
        endangered = make_tank(2, "enemy", Vec2(310, 300), speed=58.0)
        player = make_tank(3, "player", Vec2(800, 500))
        ai, _ = self.make_ai(player, [ally, endangered])
        ai.game.mines = [Mine(Vec2(400, 300), owner_id=99, team="player")]

        unsafe_push = ai.move_enemy(ally, Vec2(1, 0))
        safe_escape = ai.move_enemy(endangered, Vec2(-1, 0))

        self.assertEqual(unsafe_push, Vec2())
        self.assertLess(safe_escape.x, 0)

    def test_zero_dt_preserves_velocity_and_local_stuck_timer(self) -> None:
        enemy = make_tank(1, "enemy", cell_center((2, 2)), speed=58.0)
        player = make_tank(2, "player", cell_center((8, 2)))
        enemy.path = [(3, 2)]
        enemy.goal = (3, 2)
        enemy.plan_timer = 1.0
        enemy.fire_timer = 1.0
        enemy.velocity = Vec2(0, 58)
        enemy.stuck_timer = 0.34
        ai, _ = self.make_ai(player, [enemy])

        ai.update_enemy(enemy, 0.0)

        self.assertEqual(enemy.velocity, Vec2(0, 58))
        self.assertEqual(enemy.stuck_timer, 0.34)


class FinalShotSafetyTests(unittest.TestCase):
    def test_final_check_uses_real_turret_angle(self) -> None:
        enemy = make_tank(1, "enemy", Vec2(120, 175))
        player = make_tank(2, "player", Vec2(720, 175))
        enemy.aim_angle = 0.0
        enemy.aim_timer = 1.0
        enemy.shot_ready = True
        enemy.turret_angle = 0.07

        class RecordingCombat:
            def __init__(self) -> None:
                self.traced_angles: list[float] = []

            def active_bullets(self, tank: Tank) -> int:
                return 0

            def movement_safe_from_friendly_fire(
                self,
                tank: Tank,
                movement: Vec2,
            ) -> bool:
                return True

            def trace_shot(
                self,
                shooter: Tank,
                angle: float,
                target: Tank,
                *,
                target_position_at=None,
            ) -> ShotTrace:
                self.traced_angles.append(angle)
                return ShotTrace(ally_hit=True)

            def shoot(self, tank: Tank) -> bool:
                raise AssertionError("An unsafe shot must not be fired")

        combat = RecordingCombat()
        game = SimpleNamespace(
            player=player,
            enemies=[enemy],
            bullets=[],
            mines=[],
            combat=combat,
        )
        ai = EnemyAISystem(game)

        ai.update_enemy(enemy, 0.0)

        self.assertEqual(len(combat.traced_angles), 1)
        self.assertTrue(math.isclose(combat.traced_angles[0], enemy.turret_angle))
        self.assertFalse(enemy.shot_ready)

    def test_dark_green_waits_for_tighter_alignment(self) -> None:
        enemy = make_tank(
            1,
            "enemy",
            Vec2(120, 175),
            kind="dark_green",
        )
        player = make_tank(2, "player", Vec2(720, 175))
        enemy.aim_angle = 0.0
        enemy.aim_timer = 1.0
        enemy.shot_ready = True
        enemy.turret_angle = 0.06

        class RecordingCombat:
            def __init__(self) -> None:
                self.traced_angles: list[float] = []

            def active_bullets(self, tank: Tank) -> int:
                return 0

            def movement_safe_from_friendly_fire(
                self,
                tank: Tank,
                movement: Vec2,
            ) -> bool:
                return True

            def trace_shot(
                self,
                shooter: Tank,
                angle: float,
                target: Tank,
                *,
                target_position_at=None,
            ) -> ShotTrace:
                self.traced_angles.append(angle)
                return ShotTrace()

        combat = RecordingCombat()
        game = SimpleNamespace(
            player=player,
            enemies=[enemy],
            bullets=[],
            mines=[],
            combat=combat,
        )
        ai = EnemyAISystem(game)

        ai.update_enemy(enemy, 0.0)

        self.assertEqual(combat.traced_angles, [])
        self.assertTrue(enemy.shot_ready)

    def test_dark_green_has_shorter_fire_delay_than_dark_gray(self) -> None:
        catalog = load_enemy_catalog()
        green_delay = FIRE_RATE_DELAYS[
            catalog["dark_green"]["cadencia_disparo"]
        ]
        gray_delay = FIRE_RATE_DELAYS[
            catalog["dark_gray"]["cadencia_disparo"]
        ]

        self.assertLess(green_delay, gray_delay)

    def test_dark_green_also_starts_shooting_before_dark_gray(self) -> None:
        latest_green = max(
            enemy_initial_fire_delay("dark_green", index) for index in range(12)
        )
        earliest_gray = enemy_initial_fire_delay("dark_gray", 0)

        self.assertLess(latest_green, earliest_gray)


if __name__ == "__main__":
    unittest.main()
