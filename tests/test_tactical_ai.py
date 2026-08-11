from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from cybtanks.ai_config import load_ai_settings
from cybtanks.ai_decision import TacticalDecision, UtilityDecisionSystem
from cybtanks.ai_perception import PerceptionSnapshot, PerceptionSystem
from cybtanks.ai_squad import SquadCoordinator
from cybtanks.combat import CombatSystem
from cybtanks.config import (
    COLS,
    MAP_LAYOUTS,
    MINE_ESCAPE_MARGIN,
    MINE_EXPLOSION_RADIUS,
    ROWS,
    TANK_HALF,
)
from cybtanks.enemy_ai import EnemyAISystem, EnemyUpdateContext
from cybtanks.geometry import point_segment_distance_squared
from cybtanks.models import Bullet, Mine, Tank, Vec2
from cybtanks.world import World, cell_center


def make_tank(
    tank_id: int,
    team: str,
    cell: tuple[int, int],
    *,
    kind: str = "test",
    intelligence: str = "medium",
    speed: float = 0.0,
) -> Tank:
    return Tank(
        tank_id=tank_id,
        team=team,
        kind=kind,
        spawn_cell=cell,
        position=cell_center(cell),
        body_angle=0.0,
        turret_angle=0.0,
        speed=speed,
        color=(100, 100, 100),
        bullet_speed_class="slow",
        bullet_speed=230.0,
        max_bullets=1,
        max_bounces=1,
        max_mines=0,
        fire_rate="slow",
        shot_think_speed="slow",
        intelligence=intelligence,
        ricochet_accuracy="accurate",
        ricochet_success_rate=1.0,
        self_safe=True,
    )


def open_world() -> World:
    layout = tuple(
        tuple(
            1 if col in (0, COLS - 1) or row in (0, ROWS - 1) else 0
            for col in range(COLS)
        )
        for row in range(ROWS)
    )
    world = World()
    world.reset(layout)
    return world


class AIConfigurationTests(unittest.TestCase):
    def test_profiles_and_runtime_budgets_are_validated(self) -> None:
        settings = load_ai_settings()

        self.assertEqual(set(settings.profiles), {"medium_low", "medium", "tactical"})
        self.assertGreater(settings.global_config.max_path_plans_per_frame, 0)
        self.assertGreater(settings.global_config.max_attackers, 0)
        self.assertLess(
            settings.profile_for("dark_green", "medium").aim_tolerance_degrees,
            settings.profile_for("dark_gray", "medium_low").aim_tolerance_degrees,
        )


class PerceptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_ai_settings()
        self.world = open_world()
        self.enemy = make_tank(1, "enemy", (4, 6))
        self.player = make_tank(2, "player", (7, 6))
        self.profile = self.settings.profile_for(self.enemy.kind, self.enemy.intelligence)
        self.perception = PerceptionSystem(self.world, self.settings)

    def test_visual_detection_is_progressive_and_retains_last_position(self) -> None:
        snapshot = self.perception.update(self.enemy, self.player, self.profile, 0.1)
        self.assertFalse(snapshot.target_visible)
        self.assertGreater(self.enemy.ai.awareness, 0.0)

        for _ in range(15):
            snapshot = self.perception.update(self.enemy, self.player, self.profile, 0.1)
        self.assertTrue(snapshot.target_visible)
        seen_position = self.enemy.ai.last_known_position.copy()

        tiles = [row[:] for row in self.world.tiles]
        tiles[6][5] = 1
        self.world.reset(tuple(tuple(row) for row in tiles))
        for _ in range(4):
            snapshot = self.perception.update(self.enemy, self.player, self.profile, 0.1)

        self.assertFalse(snapshot.target_visible)
        self.assertTrue(snapshot.remembered_contact)
        self.assertEqual(snapshot.target_position, seen_position)

    def test_hearing_investigates_a_sound_occluded_by_one_wall(self) -> None:
        tiles = [row[:] for row in self.world.tiles]
        tiles[6][5] = 1
        self.world.reset(tuple(tuple(row) for row in tiles))
        self.enemy.turret_angle = math.pi
        self.perception.report_sound(self.player.position, "shot_slow", "player")

        snapshot = self.perception.update(self.enemy, self.player, self.profile, 0.2)

        self.assertFalse(snapshot.target_visible)
        self.assertTrue(snapshot.heard_contact)
        self.assertEqual(snapshot.target_position, self.player.position)

    def test_old_sound_never_overwrites_a_visible_target(self) -> None:
        for _ in range(16):
            snapshot = self.perception.update(self.enemy, self.player, self.profile, 0.1)
        self.assertTrue(snapshot.target_visible)
        old_position = self.player.position - Vec2(60, 0)
        self.perception.report_sound(old_position, "shot_slow", "player")
        self.enemy.ai.sensor_timer = 0.0

        snapshot = self.perception.update(self.enemy, self.player, self.profile, 0.1)

        self.assertTrue(snapshot.target_visible)
        self.assertEqual(self.enemy.ai.last_known_position, self.player.position)

    def test_far_agents_receive_a_lower_frequency_sensor_tick(self) -> None:
        near_enemy = make_tank(3, "enemy", (6, 6))
        far_enemy = make_tank(4, "enemy", (15, 11))
        near_profile = self.settings.profile_for(near_enemy.kind, near_enemy.intelligence)
        far_profile = self.settings.profile_for(far_enemy.kind, far_enemy.intelligence)

        self.perception.update(near_enemy, self.player, near_profile, 0.0)
        self.perception.update(far_enemy, self.player, far_profile, 0.0)

        self.assertGreater(far_enemy.ai.sensor_timer, near_enemy.ai.sensor_timer)


class OmniscientTrackingTests(unittest.TestCase):
    def test_enemy_tracks_exact_player_position_through_walls_every_frame(self) -> None:
        settings = load_ai_settings()
        world = open_world()
        tiles = [row[:] for row in world.tiles]
        tiles[6][6] = 1
        world.reset(tuple(tuple(row) for row in tiles))
        enemy = make_tank(1, "enemy", (4, 6), speed=58.0)
        player = make_tank(2, "player", (8, 6))
        perception = PerceptionSystem(world, settings)
        profile = settings.profile_for(enemy.kind, enemy.intelligence)

        first = perception.update(enemy, player, profile, 0.0)
        player.position = cell_center((9, 7))
        enemy.ai.sensor_timer = 10.0
        second = perception.update(enemy, player, profile, 1 / 60)

        self.assertFalse(first.target_visible)
        self.assertTrue(first.remembered_contact)
        self.assertTrue(first.can_engage)
        self.assertEqual(second.target_position, player.position)
        self.assertEqual(enemy.ai.last_known_position, player.position)

    def test_omniscient_enemy_uses_combat_utility_without_visual_contact(self) -> None:
        settings = load_ai_settings()
        world = open_world()
        tiles = [row[:] for row in world.tiles]
        tiles[6][6] = 1
        world.reset(tuple(tuple(row) for row in tiles))
        enemy = make_tank(1, "enemy", (4, 6), speed=58.0)
        player = make_tank(2, "player", (8, 6))
        game = SimpleNamespace(world=world, player=player, bullets=[], mines=[])
        perception_system = PerceptionSystem(world, settings)
        profile = settings.profile_for(enemy.kind, enemy.intelligence)
        snapshot = perception_system.update(enemy, player, profile, 0.0)

        decision = UtilityDecisionSystem(game, settings).update(
            enemy,
            profile,
            snapshot,
            0.0,
        )

        self.assertIn(decision.state, {"attack", "flank", "cover", "retreat"})
        self.assertEqual(decision.target_position, player.position)

    def test_cached_decision_still_receives_exact_subcell_player_position(self) -> None:
        settings = load_ai_settings()
        world = open_world()
        enemy = make_tank(1, "enemy", (4, 6), speed=58.0)
        player = make_tank(2, "player", (8, 6))
        game = SimpleNamespace(world=world, player=player, bullets=[], mines=[])
        perception_system = PerceptionSystem(world, settings)
        decision_system = UtilityDecisionSystem(game, settings)
        profile = settings.profile_for(enemy.kind, enemy.intelligence)
        first_snapshot = perception_system.update(enemy, player, profile, 0.0)
        decision_system.update(enemy, profile, first_snapshot, 0.0)
        player.position += Vec2(10, 0)
        enemy.ai.sensor_timer = 10.0
        enemy.ai.decision_timer = 10.0

        second_snapshot = perception_system.update(enemy, player, profile, 1 / 60)
        second_decision = decision_system.update(
            enemy,
            profile,
            second_snapshot,
            1 / 60,
        )

        self.assertEqual(second_decision.target_position, player.position)
        self.assertEqual(enemy.ai.navigation_target, player.position)


class ProjectileDodgeTests(unittest.TestCase):
    def make_ai(
        self,
        enemy: Tank,
        player: Tank,
        bullet: Bullet,
        world: World | None = None,
    ) -> EnemyAISystem:
        world = world or open_world()
        game = SimpleNamespace(
            world=world,
            player=player,
            enemies=[enemy],
            bullets=[bullet],
            mines=[],
            state="playing",
        )
        game.all_tanks = lambda: [player, enemy]
        game.combat = CombatSystem(game)
        return EnemyAISystem(game)

    def test_mobile_enemy_dodges_a_direct_incoming_bullet_sideways(self) -> None:
        enemy = make_tank(1, "enemy", (5, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)

        movement = ai.dodge_incoming_fire(enemy, 1 / 60)

        self.assertGreater(movement.length(), 0.0)
        self.assertGreater(abs(movement.y), abs(movement.x))
        self.assertGreater(enemy.ai.dodge_timer, 0.0)

    def test_enemy_predicts_and_dodges_a_future_ricochet(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (3, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            Vec2(100, enemy.position.y),
            Vec2(-230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=1,
        )
        ai = self.make_ai(enemy, player, bullet, world)

        movement = ai.dodge_incoming_fire(enemy, 1 / 60)

        self.assertGreater(movement.length(), 0.0)
        self.assertGreater(abs(movement.y), abs(movement.x))

    def test_dodge_is_applied_by_the_enemy_update_instead_of_route_motion(self) -> None:
        enemy = make_tank(1, "enemy", (5, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)
        enemy.path = [(6, 5)]
        enemy.goal = (6, 5)
        enemy.plan_timer = 1.0
        enemy.fire_timer = 10.0
        start = enemy.position.copy()

        ai.update_enemy(enemy, 1 / 60)

        self.assertGreater(abs(enemy.position.y - start.y), abs(enemy.position.x - start.x))

    def test_dodge_selects_the_open_side_when_one_side_is_a_wall(self) -> None:
        enemy = make_tank(1, "enemy", (5, 1), speed=58.0)
        enemy.position.y = 77.1
        player = make_tank(2, "player", (12, 1))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)

        movement = ai.dodge_incoming_fire(enemy, 1 / 60)

        self.assertGreater(movement.y, 0.0)
        self.assertFalse(ai.game.world.tank_touches_wall(enemy.position + movement))

    def test_enemy_does_not_dodge_a_bullet_destroyed_before_reaching_it(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (3, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            Vec2(80, enemy.position.y),
            Vec2(-230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet, world)

        movement = ai.dodge_incoming_fire(enemy, 1 / 60)

        self.assertEqual(movement, Vec2())

    def test_stationary_archetype_respects_zero_movement_speed(self) -> None:
        enemy = make_tank(1, "enemy", (5, 5), speed=0.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)

        self.assertEqual(ai.dodge_incoming_fire(enemy, 1 / 60), Vec2())

    def test_expired_dodge_direction_cannot_bias_a_new_threat(self) -> None:
        enemy = make_tank(1, "enemy", (5, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)
        enemy.ai.dodge_direction = Vec2(-1, 0.1).normalize()
        enemy.ai.dodge_timer = 0.0

        movement = ai.dodge_incoming_fire(enemy, 1 / 60)

        self.assertGreater(abs(movement.y), abs(movement.x))

    def test_dodge_resets_the_real_navigation_stuck_state(self) -> None:
        enemy = make_tank(1, "enemy", (5, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)
        enemy.net_stuck_timer = ai.profile_for(enemy).net_stuck_timeout - 0.01

        ai.dodge_incoming_fire(enemy, 1 / 60)

        self.assertEqual(enemy.net_stuck_timer, 0.0)
        self.assertEqual(enemy.progress_anchor, enemy.position)

    def test_update_checks_dodge_before_abandoning_an_almost_stuck_route(self) -> None:
        enemy = make_tank(1, "enemy", (5, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)
        enemy.path = [(6, 5)]
        enemy.goal = (6, 5)
        enemy.plan_timer = 1.0
        enemy.fire_timer = 10.0
        enemy.net_stuck_timer = ai.profile_for(enemy).net_stuck_timeout - 0.01

        ai.update_enemy(enemy, 1 / 60)

        self.assertEqual(enemy.route_variant, 0)
        self.assertIsNone(enemy.avoid_cell)
        self.assertEqual(enemy.net_stuck_timer, 0.0)

    def test_imminent_shot_bypasses_cooldown_when_waiting_would_be_fatal(self) -> None:
        enemy = make_tank(1, "enemy", (5, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            enemy.position - Vec2(120, 0),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        ai = self.make_ai(enemy, player, bullet)
        enemy.ai.dodge_cooldown = ai.profile_for(enemy).dodge_cooldown

        movement = ai.dodge_incoming_fire(enemy, 1 / 60)

        self.assertGreater(movement.length(), 0.0)

    def test_close_player_ricochet_that_will_disintegrate_is_not_dodged(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (3, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            Vec2(87, enemy.position.y),
            Vec2(-230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=1,
        )
        ai = self.make_ai(enemy, player, bullet, world)

        self.assertEqual(ai.dodge_incoming_fire(enemy, 1 / 60), Vec2())

    def test_bullet_absorbed_by_another_tank_does_not_trigger_dodge(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (8, 5), speed=58.0)
        blocker = make_tank(3, "enemy", (5, 5))
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            cell_center((3, 5)),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        game = SimpleNamespace(
            world=world,
            player=player,
            enemies=[blocker, enemy],
            bullets=[bullet],
            mines=[],
            state="playing",
        )
        game.all_tanks = lambda: [player, blocker, enemy]
        game.combat = CombatSystem(game)
        ai = EnemyAISystem(game)

        self.assertEqual(ai.dodge_incoming_fire(enemy, 1 / 60), Vec2())

    def test_mobile_tank_is_not_assumed_to_remain_a_permanent_bullet_shield(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (8, 5), speed=58.0)
        mobile_blocker = make_tank(3, "enemy", (6, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            Vec2(320, enemy.position.y),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        game = SimpleNamespace(
            world=world,
            player=player,
            enemies=[mobile_blocker, enemy],
            bullets=[bullet],
            mines=[],
            state="playing",
        )
        game.all_tanks = lambda: [player, mobile_blocker, enemy]
        game.combat = CombatSystem(game)
        ai = EnemyAISystem(game)

        self.assertGreater(ai.dodge_incoming_fire(enemy, 1 / 60).length(), 0.0)

    def test_bullet_absorbed_by_a_mine_does_not_trigger_dodge(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (8, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        bullet = Bullet(
            cell_center((3, 5)),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        mine = Mine(cell_center((6, 5)), owner_id=99, team="enemy")
        game = SimpleNamespace(
            world=world,
            player=player,
            enemies=[enemy],
            bullets=[bullet],
            mines=[mine],
            state="playing",
        )
        game.all_tanks = lambda: [player, enemy]
        game.combat = CombatSystem(game)
        ai = EnemyAISystem(game)

        self.assertEqual(ai.dodge_incoming_fire(enemy, 1 / 60), Vec2())

    def test_bullet_destroyed_by_another_bullet_does_not_trigger_dodge(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (8, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        hostile = Bullet(
            cell_center((3, 5)),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        interceptor = Bullet(
            cell_center((6, 5)),
            Vec2(-230, 0),
            "enemy",
            99,
            (0, 0, 0),
            max_bounces=0,
        )
        game = SimpleNamespace(
            world=world,
            player=player,
            enemies=[enemy],
            bullets=[hostile, interceptor],
            mines=[],
            state="playing",
        )
        game.all_tanks = lambda: [player, enemy]
        game.combat = CombatSystem(game)
        ai = EnemyAISystem(game)

        self.assertEqual(ai.dodge_incoming_fire(enemy, 1 / 60), Vec2())

    def test_interceptor_blocked_by_wall_cannot_hide_a_real_threat(self) -> None:
        world = open_world()
        tiles = [row[:] for row in world.tiles]
        tiles[6][7] = 1
        world.reset(tuple(tuple(row) for row in tiles))
        enemy = make_tank(1, "enemy", (8, 5), speed=58.0)
        player = make_tank(2, "player", (12, 5))
        hostile = Bullet(
            Vec2(320, enemy.position.y),
            Vec2(230, 0),
            "player",
            player.tank_id,
            (0, 0, 0),
            max_bounces=0,
        )
        blocked_interceptor = Bullet(
            Vec2(450, 460),
            Vec2(0, -230),
            "enemy",
            99,
            (0, 0, 0),
            max_bounces=0,
        )
        game = SimpleNamespace(
            world=world,
            player=player,
            enemies=[enemy],
            bullets=[hostile, blocked_interceptor],
            mines=[],
            state="playing",
        )
        game.all_tanks = lambda: [player, enemy]
        game.combat = CombatSystem(game)
        ai = EnemyAISystem(game)

        self.assertGreater(ai.dodge_incoming_fire(enemy, 1 / 60).length(), 0.0)


class SquadAndDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_ai_settings()

    def test_contact_is_shared_only_with_nearby_squad_members(self) -> None:
        observer = make_tank(1, "enemy", (4, 6), intelligence="tactical")
        nearby = make_tank(2, "enemy", (8, 6))
        distant = make_tank(3, "enemy", (15, 11))
        observer.ai.last_known_position = cell_center((6, 6))
        coordinator = SquadCoordinator(self.settings)
        profile_for = lambda tank: self.settings.profile_for(tank.kind, tank.intelligence)

        coordinator.share_contact(observer, [observer, nearby, distant], 1.0, profile_for)

        self.assertIsNotNone(nearby.ai.last_known_position)
        self.assertGreaterEqual(nearby.ai.awareness, self.settings.global_config.alert_awareness)
        self.assertIsNone(distant.ai.last_known_position)

    def test_attack_slots_cap_simultaneous_engagement(self) -> None:
        coordinator = SquadCoordinator(self.settings)
        enemies = [make_tank(index, "enemy", (index + 1, 2)) for index in range(1, 7)]

        granted = [coordinator.request_attack_slot(enemy, 0.0) for enemy in enemies]

        self.assertEqual(sum(granted), self.settings.global_config.max_attackers)

    def test_incoming_projectile_triggers_defensive_utility(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (8, 6), kind="pink", intelligence="tactical", speed=125.0)
        player = make_tank(2, "player", (12, 6))
        enemy.ai.role = "flanker"
        bullet = Bullet(
            position=enemy.position - Vec2(60, 0),
            velocity=Vec2(230, 0),
            team="player",
            owner_id=player.tank_id,
            color=(0, 0, 0),
        )
        game = SimpleNamespace(world=world, player=player, bullets=[bullet])
        decision_system = UtilityDecisionSystem(game, self.settings)
        profile = self.settings.profile_for(enemy.kind, enemy.intelligence)
        perception = PerceptionSnapshot(
            target_position=player.position,
            target_visible=True,
            has_line_of_sight=True,
            can_engage=True,
            heard_contact=False,
            remembered_contact=True,
            just_confirmed=False,
        )

        decision = decision_system.update(enemy, profile, perception, 0.1)

        self.assertGreater(decision.threat, profile.retreat_threshold)
        self.assertIn(decision.state, {"cover", "retreat"})

    def test_mine_evasion_cannot_be_replaced_by_a_regular_decision(self) -> None:
        world = open_world()
        enemy = make_tank(1, "enemy", (4, 6), speed=58.0)
        player = make_tank(2, "player", (12, 6))
        enemy.path = [(3, 6)]
        enemy.ai.state = "evade"
        mine = Mine(cell_center((5, 6)), owner_id=99, team="player")
        game = SimpleNamespace(world=world, player=player, bullets=[], mines=[mine])
        decision_system = UtilityDecisionSystem(game, self.settings)
        profile = self.settings.profile_for(enemy.kind, enemy.intelligence)
        perception = PerceptionSnapshot(
            target_position=player.position,
            target_visible=True,
            has_line_of_sight=True,
            can_engage=True,
            heard_contact=False,
            remembered_contact=True,
            just_confirmed=False,
        )

        decision = decision_system.update(enemy, profile, perception, 0.2)

        self.assertEqual(decision.state, "evade")
        self.assertEqual(enemy.path, [(3, 6)])

    def test_wall_blocks_projectile_threat_estimation(self) -> None:
        world = open_world()
        tiles = [row[:] for row in world.tiles]
        tiles[6][7] = 1
        world.reset(tuple(tuple(row) for row in tiles))
        enemy = make_tank(1, "enemy", (8, 6), intelligence="medium_low", speed=58.0)
        player = make_tank(2, "player", (10, 6))
        bullet = Bullet(cell_center((6, 6)), Vec2(230, 0), "player", 2, (0, 0, 0), max_bounces=0)
        game = SimpleNamespace(world=world, player=player, bullets=[bullet], mines=[])
        decision_system = UtilityDecisionSystem(game, self.settings)
        profile = self.settings.profile_for(enemy.kind, enemy.intelligence)
        perception = PerceptionSnapshot(
            target_position=player.position,
            target_visible=True,
            has_line_of_sight=False,
            can_engage=True,
            heard_contact=False,
            remembered_contact=True,
            just_confirmed=False,
        )

        decision = decision_system.update(enemy, profile, perception, 0.1)

        self.assertLess(decision.threat, profile.retreat_threshold)


class NavigationBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = open_world()

    def make_ai(self, enemy: Tank, player: Tank, mines: list[Mine] | None = None) -> EnemyAISystem:
        game = SimpleNamespace(
            world=self.world,
            player=player,
            enemies=[enemy],
            mines=mines or [],
            bullets=[],
        )
        game.all_tanks = lambda: [player, enemy]
        game.combat = SimpleNamespace(active_bullets=lambda tank: 0)
        return EnemyAISystem(game)

    def test_tactical_plan_uses_one_navigation_field(self) -> None:
        enemy = make_tank(1, "enemy", (2, 2), kind="pink", intelligence="tactical", speed=125.0)
        player = make_tank(2, "player", (8, 6))
        ai = self.make_ai(enemy, player)
        calls = 0
        original = self.world.navigation_field

        def count_navigation(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        self.world.navigation_field = count_navigation
        self.world.find_path = lambda *args, **kwargs: self.fail("Per-candidate A* was used")

        ai.plan_path(enemy)

        self.assertEqual(calls, 1)
        self.assertTrue(enemy.path)

    def test_production_update_caps_navigation_work_per_frame(self) -> None:
        player = make_tank(100, "player", (8, 6))
        enemies = [
            make_tank(index, "enemy", (index + 1, 2), speed=58.0)
            for index in range(1, 8)
        ]
        combat = SimpleNamespace(
            prepare_friendly_fire_paths=lambda team: None,
            active_bullets=lambda tank: 0,
            movement_safe_from_friendly_fire=lambda tank, movement: True,
            friendly_fire_destination_clearance=lambda tank, movement: math.inf,
            can_shoot=lambda tank: False,
        )
        game = SimpleNamespace(
            world=self.world,
            player=player,
            enemies=enemies,
            mines=[],
            bullets=[],
            combat=combat,
            mine_system=SimpleNamespace(place=lambda tank: False),
        )
        game.all_tanks = lambda: [player, *enemies]
        ai = EnemyAISystem(game)
        starting_positions = {enemy.tank_id: enemy.position.copy() for enemy in enemies}
        calls = 0
        original = self.world.navigation_field

        def count_navigation(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        self.world.navigation_field = count_navigation

        ai.update(1 / 60)

        self.assertLessEqual(calls, ai.settings.global_config.max_path_plans_per_frame)
        for enemy in enemies:
            if enemy.goal is None:
                self.assertEqual(enemy.position, starting_positions[enemy.tank_id])

    def test_production_update_caps_expensive_shot_solutions(self) -> None:
        player = make_tank(100, "player", (8, 6))
        enemies = [make_tank(index, "enemy", (index + 1, 2)) for index in range(1, 8)]
        combat = SimpleNamespace(
            active_bullets=lambda tank: 0,
            can_shoot=lambda tank: True,
            movement_safe_from_friendly_fire=lambda tank, movement: True,
        )
        game = SimpleNamespace(
            world=self.world,
            player=player,
            enemies=enemies,
            mines=[],
            bullets=[],
            combat=combat,
        )
        game.all_tanks = lambda: [player, *enemies]
        ai = EnemyAISystem(game)
        ai._shot_budget = ai.settings.global_config.max_shot_plans_per_frame
        calls = []

        def no_solution(enemy: Tank) -> tuple[float, bool]:
            calls.append(enemy.tank_id)
            return 0.0, False

        ai.choose_shot = no_solution
        perception = PerceptionSnapshot(
            target_position=player.position,
            target_visible=True,
            has_line_of_sight=True,
            can_engage=True,
            heard_contact=False,
            remembered_contact=True,
            just_confirmed=False,
        )
        for enemy in enemies:
            profile = ai.profile_for(enemy)
            decision = TacticalDecision("attack", player.position, 0.0, True)
            ai.update_enemy(
                enemy,
                0.0,
                EnemyUpdateContext(profile, perception, decision),
            )

        self.assertEqual(len(calls), ai.settings.global_config.max_shot_plans_per_frame)

    def test_mine_escape_prefers_a_route_that_never_moves_closer(self) -> None:
        enemy = make_tank(1, "enemy", (4, 6), speed=58.0)
        player = make_tank(2, "player", (12, 6))
        mine = Mine(cell_center((5, 6)), owner_id=99, team="player")
        ai = self.make_ai(enemy, player, [mine])
        start_clearance = enemy.position.distance_to(mine.position)

        ai.plan_mine_escape(enemy)

        safe_distance = MINE_EXPLOSION_RADIUS + TANK_HALF + MINE_ESCAPE_MARGIN
        self.assertTrue(enemy.path)
        self.assertGreaterEqual(cell_center(enemy.goal).distance_to(mine.position), safe_distance)
        self.assertTrue(
            all(
                cell_center(cell).distance_to(mine.position) >= start_clearance
                for cell in enemy.path
            )
        )

    def test_mine_escape_can_use_a_safe_non_monotonic_detour(self) -> None:
        self.world.reset(MAP_LAYOUTS[0])
        enemy = make_tank(1, "enemy", (15, 2), speed=58.0)
        enemy.position = Vec2(930.52, 127.12)
        player = make_tank(2, "player", (1, 1))
        mine = Mine(Vec2(920.74, 153.84), owner_id=99, team="player")
        ai = self.make_ai(enemy, player, [mine])
        initial_clearance = enemy.position.distance_to(mine.position)

        ai.plan_mine_escape(enemy)

        route_points = [enemy.position, *(cell_center(cell) for cell in enemy.path)]
        minimum_clearance = min(
            math.sqrt(point_segment_distance_squared(mine.position, start, end))
            for start, end in zip(route_points, route_points[1:])
        )
        self.assertGreaterEqual(minimum_clearance, initial_clearance - 0.01)
        route_points = [enemy.position, *(cell_center(cell) for cell in enemy.path)]
        self.assertTrue(
            all(
                point_segment_distance_squared(mine.position, start, end)
                >= initial_clearance**2 - 0.01
                for start, end in zip(route_points, route_points[1:])
            )
        )


class ContinuousSafetyTests(unittest.TestCase):
    def test_friendly_fire_escape_cannot_cross_the_projectile_path(self) -> None:
        world = open_world()
        tank = make_tank(1, "enemy", (5, 5), speed=58.0)
        tank.position = Vec2(300, 101)
        bullet = Bullet(Vec2(120, 100), Vec2(230, 0), "enemy", 2, (0, 0, 0), max_bounces=0)
        game = SimpleNamespace(world=world, enemies=[tank], bullets=[bullet])
        combat = CombatSystem(game)

        self.assertFalse(combat.movement_safe_from_friendly_fire(tank, Vec2(0, -3)))


if __name__ == "__main__":
    unittest.main()
