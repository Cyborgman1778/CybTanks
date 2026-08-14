from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame

from cybtanks.game import Game
from cybtanks.input_manager import (
    GAMEPAD_MODE,
    KBM_MODE,
    InputManager,
    InputState,
    apply_deadzone,
)
from cybtanks.models import Vec2


class FakeJoystick:
    def __init__(
        self,
        instance_id: int,
        axes: list[float],
        buttons: list[int] | None = None,
        name: str = "Generic Gamepad",
        guid: str = "",
    ) -> None:
        self.instance_id = instance_id
        self.axes = axes
        self.buttons = buttons or [0] * 6
        self.name = name
        self.guid = guid
        self.initialized = True

    def get_init(self) -> bool:
        return self.initialized

    def init(self) -> None:
        self.initialized = True

    def quit(self) -> None:
        self.initialized = False

    def get_instance_id(self) -> int:
        return self.instance_id

    def get_numaxes(self) -> int:
        return len(self.axes)

    def get_axis(self, axis: int) -> float:
        return self.axes[axis]

    def get_numbuttons(self) -> int:
        return len(self.buttons)

    def get_button(self, button: int) -> int:
        return self.buttons[button]

    def get_name(self) -> str:
        return self.name

    def get_guid(self) -> str:
        return self.guid


class FakeController:
    def __init__(self) -> None:
        self.axes = {axis: 0 for axis in range(pygame.CONTROLLER_AXIS_MAX)}
        self.buttons = {
            button: False for button in range(pygame.CONTROLLER_BUTTON_MAX)
        }
        self.initialized = True

    def get_axis(self, axis: int) -> int:
        return self.axes[axis]

    def get_button(self, button: int) -> bool:
        return self.buttons[button]

    def quit(self) -> None:
        self.initialized = False


class PressedKeys:
    def __init__(self, *keys: int) -> None:
        self.keys = frozenset(keys)

    def __getitem__(self, key: int) -> bool:
        return key in self.keys


def make_manager(
    joysticks: list[FakeJoystick] | None = None,
    controllers: list[FakeController] | None = None,
) -> InputManager:
    connected = joysticks or []
    standardized = controllers or []
    controller_type = Mock()
    controller_type.side_effect = standardized
    with (
        patch("cybtanks.input_manager.pygame.joystick.init"),
        patch("cybtanks.input_manager.sdl_controller.init"),
        patch(
            "cybtanks.input_manager.sdl_controller.is_controller",
            side_effect=lambda index: index < len(standardized),
        ),
        patch("cybtanks.input_manager.sdl_controller.Controller", controller_type),
        patch(
            "cybtanks.input_manager.pygame.joystick.get_count",
            return_value=len(connected),
        ),
        patch(
            "cybtanks.input_manager.pygame.joystick.Joystick",
            side_effect=connected,
        ),
    ):
        return InputManager()


class DeadzoneTests(unittest.TestCase):
    def test_radial_deadzone_filters_drift_and_preserves_analog_range(self) -> None:
        self.assertEqual(apply_deadzone(0.1, 0.1), Vec2())

        direction = apply_deadzone(0.3, 0.4)

        self.assertAlmostEqual(direction.length(), (0.5 - 0.18) / (1 - 0.18))
        self.assertEqual(direction.normalize(), Vec2(0.6, 0.8))

    def test_radial_deadzone_preserves_every_stick_angle(self) -> None:
        expected_magnitude = (0.7 - 0.18) / (1 - 0.18)
        for degrees in range(0, 360, 15):
            with self.subTest(degrees=degrees):
                source = Vec2(0.7, 0).rotate(degrees)
                result = apply_deadzone(source.x, source.y)
                self.assertAlmostEqual(result.length(), expected_magnitude)
                self.assertAlmostEqual(result.normalize().dot(source.normalize()), 1.0)


class KeyboardMouseInputTests(unittest.TestCase):
    def test_keyboard_mouse_state_exposes_edges_holds_and_aim(self) -> None:
        manager = make_manager()
        manager.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
        manager.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(20, 10))
        )

        with (
            patch(
                "cybtanks.input_manager.pygame.key.get_pressed",
                return_value=PressedKeys(pygame.K_d),
            ),
            patch(
                "cybtanks.input_manager.pygame.mouse.get_pressed",
                return_value=(1, 0, 0),
            ),
        ):
            first = manager.update(Vec2(10, 10), Vec2(20, 10))
            second = manager.update(Vec2(10, 10), Vec2(20, 10))

        self.assertEqual(first.active_mode, KBM_MODE)
        self.assertEqual(first.move_vector, Vec2(1, 0))
        self.assertEqual(first.aim_vector, Vec2(1, 0))
        self.assertEqual(first.aim_world_pos, Vec2(20, 10))
        self.assertTrue(first.shoot_triggered)
        self.assertTrue(first.shoot_held)
        self.assertFalse(second.shoot_triggered)
        self.assertTrue(second.shoot_held)

    def test_space_shift_and_e_trigger_the_special_action(self) -> None:
        for key in (pygame.K_SPACE, pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_e):
            with self.subTest(key=key):
                manager = make_manager()
                manager.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
                with (
                    patch(
                        "cybtanks.input_manager.pygame.key.get_pressed",
                        return_value=PressedKeys(),
                    ),
                    patch(
                        "cybtanks.input_manager.pygame.mouse.get_pressed",
                        return_value=(0, 0, 0),
                    ),
                ):
                    state = manager.update(Vec2(), Vec2(1, 0))
                self.assertTrue(state.special_triggered)

    def test_mouse_motion_takes_control_back_from_gamepad(self) -> None:
        joystick = FakeJoystick(7, [1, 0, 0, 0, -1, -1])
        manager = make_manager([joystick])
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=7,
                axis=0,
                value=1.0,
            )
        )
        self.assertEqual(manager.active_mode, GAMEPAD_MODE)

        manager.handle_event(
            pygame.event.Event(pygame.MOUSEMOTION, pos=(20, 20), rel=(1, 0))
        )

        self.assertEqual(manager.active_mode, KBM_MODE)


class GamepadInputTests(unittest.TestCase):
    def test_sdl_mapping_normalizes_controls_and_preserves_a_fast_trigger_tap(self) -> None:
        joystick = FakeJoystick(
            10,
            [0, 0, 0, 0, 0, 0],
            buttons=[0] * 16,
            name="PS4 Controller",
        )
        controller = FakeController()
        manager = make_manager([joystick], [controller])
        controller.axes[pygame.CONTROLLER_AXIS_RIGHTY] = -32_768
        manager.update(Vec2(100, 100), Vec2(100, 100))
        manager.handle_event(
            pygame.event.Event(
                pygame.CONTROLLERAXISMOTION,
                instance_id=10,
                axis=pygame.CONTROLLER_AXIS_RIGHTY,
                value=-32_768,
            )
        )
        aimed = manager.update(
            Vec2(100, 100),
            Vec2(100, 100),
            dt=0.1,
            world_size=(1000, 800),
        )

        manager.handle_event(
            pygame.event.Event(
                pygame.CONTROLLERAXISMOTION,
                instance_id=10,
                axis=pygame.CONTROLLER_AXIS_TRIGGERRIGHT,
                value=32_767,
            )
        )
        manager.handle_event(
            pygame.event.Event(
                pygame.CONTROLLERAXISMOTION,
                instance_id=10,
                axis=pygame.CONTROLLER_AXIS_TRIGGERRIGHT,
                value=0,
            )
        )
        tapped = manager.update(
            Vec2(100, 100),
            Vec2(100, 100),
            dt=0.1,
            world_size=(1000, 800),
        )

        self.assertEqual(aimed.active_mode, GAMEPAD_MODE)
        self.assertEqual(aimed.aim_vector, Vec2(0, -1))
        self.assertTrue(tapped.shoot_triggered)
        self.assertFalse(tapped.shoot_held)

    def test_standard_raw_axes_keep_last_aim_and_rb_edge(self) -> None:
        joystick = FakeJoystick(
            11,
            [0.6, 0, 0, 1],
        )
        manager = make_manager([joystick])
        manager.update(Vec2(100, 100), Vec2(100, 100))
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=11,
                axis=3,
                value=1.0,
            )
        )

        first = manager.update(
            Vec2(100, 100),
            Vec2(100, 100),
            dt=0.1,
            world_size=(1000, 800),
        )
        joystick.axes[2] = 0
        joystick.axes[3] = 0
        second = manager.update(
            Vec2(100, 100),
            Vec2(100, 100),
            dt=0.1,
            world_size=(1000, 800),
        )
        joystick.buttons[5] = 1
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYBUTTONDOWN,
                instance_id=11,
                button=5,
            )
        )
        trigger_down = manager.update(Vec2(100, 100), Vec2())
        trigger_held = manager.update(Vec2(100, 100), Vec2())

        self.assertEqual(first.active_mode, GAMEPAD_MODE)
        self.assertAlmostEqual(first.move_vector.x, (0.6 - 0.18) / (1 - 0.18))
        self.assertEqual(first.move_vector.y, 0)
        self.assertEqual(first.aim_vector, Vec2(0, 1))
        self.assertEqual(first.aim_world_pos, Vec2(100, 152))
        self.assertEqual(second.aim_world_pos, first.aim_world_pos)
        self.assertEqual(second.aim_vector, Vec2(0, 1))
        self.assertTrue(trigger_down.shoot_triggered)
        self.assertTrue(trigger_down.shoot_held)
        self.assertFalse(trigger_held.shoot_triggered)
        self.assertTrue(trigger_held.shoot_held)

    def test_alternate_axes_support_combined_triggers(self) -> None:
        joystick = FakeJoystick(
            12,
            [0, 0, 0, -1, 0],
            guid="03000000de280000ff11000000000000",
        )
        manager = make_manager([joystick])
        manager.update(Vec2(), Vec2())
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=12,
                axis=3,
                value=-1.0,
            )
        )

        aimed = manager.update(Vec2(), Vec2(), dt=0.1)
        joystick.axes[2] = -0.8
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=12,
                axis=2,
                value=-0.8,
            )
        )
        shot = manager.update(Vec2(), Vec2())
        joystick.axes[2] = 0
        manager.update(Vec2(), Vec2())
        joystick.axes[2] = 0.8
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=12,
                axis=2,
                value=0.8,
            )
        )
        special = manager.update(Vec2(), Vec2())

        self.assertEqual(aimed.aim_vector, Vec2(-1, 0))
        self.assertTrue(shot.shoot_triggered)
        self.assertTrue(special.special_triggered)

    def test_steam_dinput_alternate_guid_separates_right_stick_and_triggers(self) -> None:
        joystick = FakeJoystick(
            20,
            [0, 0, -1, 0, 1, -1],
            guid="03000000de280000fc11000000000000",
        )
        manager = make_manager([joystick])
        manager.update(Vec2(), Vec2())
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=20,
                axis=4,
                value=1.0,
            )
        )
        aimed = manager.update(Vec2(), Vec2(), dt=0.1)
        joystick.axes[5] = 1
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=20,
                axis=5,
                value=1.0,
            )
        )
        shot = manager.update(Vec2(), Vec2())

        self.assertEqual(aimed.aim_vector, Vec2(0, 1))
        self.assertFalse(aimed.shoot_triggered)
        self.assertFalse(aimed.special_triggered)
        self.assertTrue(shot.shoot_triggered)

    def test_steam_wgi_profile_fixes_rotated_sticks_without_triggering_actions(self) -> None:
        joystick = FakeJoystick(
            16,
            [0, 0, 0, 0, -1, -1],
            name="Steam Virtual Gamepad",
            guid="03000000de280000ff11000000007701",
        )
        manager = make_manager([joystick])
        cases = (
            ((0, -1), Vec2(-1, 0)),
            ((0, 1), Vec2(1, 0)),
            ((1, 0), Vec2(0, -1)),
            ((-1, 0), Vec2(0, 1)),
            ((2**-0.5, 2**-0.5), Vec2(2**-0.5, -2**-0.5)),
        )

        for (raw_axis_0, raw_axis_1), expected in cases:
            with self.subTest(expected=expected):
                joystick.axes[0] = raw_axis_0
                joystick.axes[1] = raw_axis_1
                manager.handle_event(
                    pygame.event.Event(
                        pygame.JOYAXISMOTION,
                        instance_id=16,
                        axis=0,
                        value=raw_axis_0,
                    )
                )
                state = manager.update(Vec2(), Vec2())
                self.assertAlmostEqual(
                    state.move_vector.normalize().dot(expected.normalize()),
                    1.0,
                )
                self.assertFalse(state.shoot_triggered)
                self.assertFalse(state.special_triggered)

        joystick.axes[0] = 0
        joystick.axes[1] = 0
        joystick.axes[2] = 0.4
        joystick.axes[3] = 0.6
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=16,
                axis=3,
                value=0.6,
            )
        )
        aimed = manager.update(Vec2(), Vec2(), dt=0.1)

        self.assertAlmostEqual(aimed.aim_vector.x, 0.6 / math.hypot(0.6, -0.4))
        self.assertAlmostEqual(aimed.aim_vector.y, -0.4 / math.hypot(0.6, -0.4))
        self.assertFalse(aimed.shoot_triggered)
        self.assertFalse(aimed.special_triggered)

    def test_unknown_raw_stick_axes_never_act_as_triggers(self) -> None:
        joystick = FakeJoystick(17, [0, 0, 0, 0, 0, 0])
        manager = make_manager([joystick])
        for axis in range(6):
            with self.subTest(axis=axis):
                joystick.axes[axis] = 0.8
                manager.handle_event(
                    pygame.event.Event(
                        pygame.JOYAXISMOTION,
                        instance_id=17,
                        axis=axis,
                        value=0.8,
                    )
                )
                state = manager.update(Vec2(), Vec2())
                self.assertFalse(state.shoot_triggered)
                self.assertFalse(state.shoot_held)
                self.assertFalse(state.special_triggered)
                joystick.axes[axis] = 0
                manager.update(Vec2(), Vec2())

    def test_hotplug_opens_and_closes_standardized_controller(self) -> None:
        manager = make_manager()
        joystick = FakeJoystick(18, [0, 0, 0, 0, 0, 0])
        controller = FakeController()
        with (
            patch(
                "cybtanks.input_manager.pygame.joystick.Joystick",
                return_value=joystick,
            ),
            patch(
                "cybtanks.input_manager.sdl_controller.is_controller",
                return_value=True,
            ),
            patch(
                "cybtanks.input_manager.sdl_controller.Controller",
                return_value=controller,
            ) as controller_type,
        ):
            manager.handle_event(
                pygame.event.Event(pygame.JOYDEVICEADDED, device_index=0)
            )

        controller_type.assert_called_once_with(0)
        self.assertIs(manager.controllers[18], controller)
        manager.handle_event(
            pygame.event.Event(pygame.JOYDEVICEREMOVED, instance_id=18)
        )
        self.assertFalse(controller.initialized)

    def test_duplicate_add_retries_failed_controller_promotion(self) -> None:
        manager = make_manager()
        joystick = FakeJoystick(19, [0, 0, 0, 0, 0, 0])
        controller = FakeController()
        with (
            patch(
                "cybtanks.input_manager.pygame.joystick.Joystick",
                return_value=joystick,
            ),
            patch(
                "cybtanks.input_manager.sdl_controller.is_controller",
                return_value=True,
            ),
            patch(
                "cybtanks.input_manager.sdl_controller.Controller",
                side_effect=[pygame.error("temporary failure"), controller],
            ),
        ):
            added = pygame.event.Event(pygame.JOYDEVICEADDED, device_index=0)
            manager.handle_event(added)
            self.assertNotIn(19, manager.controllers)
            manager.handle_event(added)

        self.assertIs(manager.controllers[19], controller)

    def test_rb_and_a_buttons_trigger_actions(self) -> None:
        joystick = FakeJoystick(13, [0, 0, 0, 0, -1, -1])
        manager = make_manager([joystick])
        joystick.buttons[5] = 1
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYBUTTONDOWN,
                instance_id=13,
                button=5,
            )
        )
        shot = manager.update(Vec2(), Vec2())
        joystick.buttons[5] = 0
        manager.update(Vec2(), Vec2())
        joystick.buttons[0] = 1
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYBUTTONDOWN,
                instance_id=13,
                button=0,
            )
        )
        special = manager.update(Vec2(), Vec2())

        self.assertTrue(shot.shoot_triggered)
        self.assertTrue(special.special_triggered)

    def test_xbox_raw_fallback_supports_separate_rt_and_lt_axes(self) -> None:
        joystick = FakeJoystick(
            25,
            [0, 0, -1, 0, 0, -1],
            name="Xbox Controller",
        )
        manager = make_manager([joystick])
        joystick.axes[5] = 1
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=25,
                axis=5,
                value=1.0,
            )
        )
        shot = manager.update(Vec2(), Vec2())
        joystick.axes[5] = -1
        manager.update(Vec2(), Vec2())
        joystick.axes[2] = 1
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=25,
                axis=2,
                value=1.0,
            )
        )
        special = manager.update(Vec2(), Vec2())

        self.assertTrue(shot.shoot_triggered)
        self.assertTrue(special.special_triggered)

    def test_radial_motion_switches_mode_when_each_component_is_below_threshold(self) -> None:
        joystick = FakeJoystick(14, [0.13, 0.13, 0, 0, -1, -1])
        manager = make_manager([joystick])

        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=14,
                axis=0,
                value=0.13,
            )
        )

        self.assertEqual(manager.active_mode, GAMEPAD_MODE)

    def test_accepted_action_survives_a_same_frame_mode_change(self) -> None:
        joystick = FakeJoystick(15, [0, 0, 1, 0])
        manager = make_manager([joystick])
        manager.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(20, 20))
        )
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=15,
                axis=2,
                value=1.0,
            )
        )

        state = manager.update(Vec2(), Vec2())

        self.assertEqual(state.active_mode, GAMEPAD_MODE)
        self.assertTrue(state.shoot_triggered)

    def test_hotplug_adds_and_removes_by_instance_id(self) -> None:
        manager = make_manager()
        joystick = FakeJoystick(21, [0, 0, 0, 0, -1, -1])
        with patch(
            "cybtanks.input_manager.pygame.joystick.Joystick",
            return_value=joystick,
        ), patch(
            "cybtanks.input_manager.sdl_controller.is_controller",
            return_value=False,
        ):
            manager.handle_event(
                pygame.event.Event(pygame.JOYDEVICEADDED, device_index=0)
            )

        self.assertEqual(manager.joystick_count, 1)
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYBUTTONDOWN,
                instance_id=21,
                button=1,
            )
        )
        self.assertEqual(manager.active_mode, GAMEPAD_MODE)

        manager.handle_event(
            pygame.event.Event(pygame.JOYDEVICEREMOVED, instance_id=21)
        )

        self.assertEqual(manager.joystick_count, 0)
        self.assertEqual(manager.active_mode, KBM_MODE)
        self.assertFalse(joystick.initialized)

    def test_duplicate_initial_add_does_not_close_the_cached_joystick(self) -> None:
        joystick = FakeJoystick(23, [0, 0, 0, 0, -1, -1])
        manager = make_manager([joystick])
        with patch(
            "cybtanks.input_manager.pygame.joystick.Joystick",
            return_value=joystick,
        ):
            manager.handle_event(
                pygame.event.Event(pygame.JOYDEVICEADDED, device_index=0)
            )

        self.assertEqual(manager.joystick_count, 1)
        self.assertTrue(joystick.initialized)

    def test_ambiguous_sony_raw_axes_are_not_guessed_as_sticks_or_triggers(self) -> None:
        joystick = FakeJoystick(
            24,
            [0, 0, 1, -1, -1, 0],
            buttons=[0] * 11,
            name="Sony Interactive Entertainment Wireless Controller",
        )
        manager = make_manager([joystick])
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=24,
                axis=2,
                value=1.0,
            )
        )
        aimed = manager.update(Vec2(), Vec2())
        aimed_mode = aimed.active_mode
        joystick.buttons[5] = 1
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYBUTTONDOWN,
                instance_id=24,
                button=5,
            )
        )
        shot = manager.update(Vec2(), Vec2())

        self.assertEqual(aimed.aim_vector, Vec2(1, 0))
        self.assertEqual(aimed_mode, KBM_MODE)
        self.assertFalse(aimed.shoot_triggered)
        self.assertFalse(aimed.special_triggered)
        self.assertTrue(shot.shoot_triggered)

    def test_crosshair_uses_mouse_or_free_gamepad_cursor(self) -> None:
        manager = make_manager()
        with patch(
            "cybtanks.input_manager.pygame.mouse.get_pos",
            return_value=(45, 60),
        ):
            self.assertEqual(manager.crosshair_position(Vec2(100, 100)), Vec2(45, 60))

        joystick = FakeJoystick(22, [0, 0, 1, 0])
        manager = make_manager([joystick])
        manager.update(Vec2(100, 100), Vec2(100, 100))
        manager.handle_event(
            pygame.event.Event(
                pygame.JOYAXISMOTION,
                instance_id=22,
                axis=2,
                value=1.0,
            )
        )
        state = manager.update(
            Vec2(100, 100),
            Vec2(100, 100),
            dt=1.0,
            world_size=(1000, 800),
        )
        screen_cursor = state.aim_world_pos + Vec2(0, 86)

        self.assertGreater(state.aim_world_pos.distance_to(Vec2(100, 100)), 120)
        self.assertEqual(manager.crosshair_position(screen_cursor), screen_cursor)

        clamped = manager.update(
            Vec2(100, 100),
            Vec2(100, 100),
            dt=2.0,
            world_size=(1000, 800),
        )
        self.assertEqual(clamped.aim_world_pos.x, 981)
        joystick.axes[2] = 0
        stationary = manager.update(
            Vec2(250, 100),
            Vec2(100, 100),
            dt=1.0,
            world_size=(1000, 800),
        )
        self.assertEqual(stationary.aim_world_pos, clamped.aim_world_pos)


class PlayerInputIntegrationTests(unittest.TestCase):
    def test_player_consumes_input_state_for_movement_aim_and_actions(self) -> None:
        player = SimpleNamespace(
            alive=True,
            position=Vec2(100, 100),
            speed=100.0,
            velocity=Vec2(),
            body_angle=0.0,
            turret_angle=0.0,
        )
        movements: list[Vec2] = []

        def move_tank(tank: SimpleNamespace, movement: Vec2, tanks: list[object]) -> Vec2:
            movements.append(movement.copy())
            tank.position += movement
            return movement

        game = Game.__new__(Game)
        game.player = player
        game.enemies = []
        game.world = SimpleNamespace(move_tank=move_tank)
        game.combat = SimpleNamespace(shoot=Mock())
        game.mine_system = SimpleNamespace(place=Mock())
        state = InputState(
            move_vector=Vec2(0.3, 0.4),
            aim_vector=Vec2(0, -1),
            aim_world_pos=Vec2(115, 0),
            shoot_triggered=True,
            shoot_held=True,
            special_triggered=True,
            active_mode=GAMEPAD_MODE,
        )

        with patch(
            "cybtanks.game.pygame.key.get_pressed",
            side_effect=AssertionError("player must not read keyboard state"),
        ):
            Game.update_player(game, 0.5, state)

        self.assertEqual(movements, [Vec2(15, 20)])
        self.assertEqual(player.velocity, Vec2(30, 40))
        self.assertAlmostEqual(player.body_angle, math.atan2(20, 15))
        self.assertAlmostEqual(player.turret_angle, -math.pi / 2)
        game.combat.shoot.assert_called_once_with(player)
        game.mine_system.place.assert_called_once_with(player)

    def test_player_recalculates_aim_after_moving_past_the_cursor(self) -> None:
        player = SimpleNamespace(
            alive=True,
            position=Vec2(100, 100),
            speed=100.0,
            velocity=Vec2(),
            body_angle=0.0,
            turret_angle=0.0,
        )

        def move_tank(tank: SimpleNamespace, movement: Vec2, tanks: list[object]) -> Vec2:
            tank.position += movement
            return movement

        game = Game.__new__(Game)
        game.player = player
        game.enemies = []
        game.world = SimpleNamespace(move_tank=move_tank)
        game.combat = SimpleNamespace(shoot=Mock())
        game.mine_system = SimpleNamespace(place=Mock())
        state = InputState(
            move_vector=Vec2(1, 0),
            aim_vector=Vec2(1, 0),
            aim_world_pos=Vec2(150, 100),
            shoot_triggered=True,
            shoot_held=False,
            special_triggered=False,
            active_mode=GAMEPAD_MODE,
        )

        Game.update_player(game, 1.0, state)

        self.assertEqual(player.position, Vec2(200, 100))
        self.assertEqual(state.aim_vector, Vec2(-1, 0))
        self.assertAlmostEqual(abs(player.turret_angle), math.pi)
        game.combat.shoot.assert_called_once_with(player)


class GameEventIntegrationTests(unittest.TestCase):
    def test_controller_a_confirms_every_end_state(self) -> None:
        cases = (
            ("level_clear", "next_level"),
            ("life_lost", "respawn_player"),
            ("game_over", "start_level"),
        )
        for state, expected_method in cases:
            with self.subTest(state=state):
                event = pygame.event.Event(
                    pygame.CONTROLLERBUTTONDOWN,
                    instance_id=1,
                    button=pygame.CONTROLLER_BUTTON_A,
                )
                input_manager = SimpleNamespace(
                    poll_events=lambda: [event],
                    handle_event=Mock(),
                )
                game = Game.__new__(Game)
                game.input_manager = input_manager
                game._input_actions_blocked = False
                game.state = state
                game.running = True
                game.next_level = Mock()
                game.respawn_player = Mock()
                game.start_level = Mock()

                Game.handle_events(game)

                getattr(game, expected_method).assert_called_once_with()
                self.assertTrue(game._input_actions_blocked)
                input_manager.handle_event.assert_called_once_with(
                    event,
                    actions_enabled=False,
                )

    def test_controller_a_remains_a_gameplay_action_while_playing(self) -> None:
        event = pygame.event.Event(
            pygame.CONTROLLERBUTTONDOWN,
            instance_id=1,
            button=pygame.CONTROLLER_BUTTON_A,
        )
        input_manager = SimpleNamespace(
            poll_events=lambda: [event],
            handle_event=Mock(),
        )
        game = Game.__new__(Game)
        game.input_manager = input_manager
        game._input_actions_blocked = False
        game.state = "playing"
        game.running = True
        game.next_level = Mock()
        game.respawn_player = Mock()
        game.start_level = Mock()

        Game.handle_events(game)

        input_manager.handle_event.assert_called_once_with(
            event,
            actions_enabled=True,
        )
        self.assertFalse(game._input_actions_blocked)
        game.next_level.assert_not_called()
        game.respawn_player.assert_not_called()
        game.start_level.assert_not_called()

    def test_state_transition_blocks_gameplay_actions_until_update_finishes(self) -> None:
        neutral_state = InputState(
            move_vector=Vec2(),
            aim_vector=Vec2(1, 0),
            aim_world_pos=Vec2(),
            shoot_triggered=False,
            shoot_held=False,
            special_triggered=False,
            active_mode=KBM_MODE,
        )
        click = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            button=1,
            pos=(100, 100),
        )
        input_manager = SimpleNamespace(
            poll_events=lambda: [click],
            handle_event=Mock(),
            mouse_position=lambda: (100, 100),
            update=Mock(return_value=neutral_state),
        )
        player = SimpleNamespace(
            tank_id=1,
            position=Vec2(100, 100),
            alive=True,
            cooldown=0.0,
            shot_think_timer=0.0,
            shield_flash=0.0,
        )
        game = Game.__new__(Game)
        game.input_manager = input_manager
        game._input_actions_blocked = False
        game.state = "life_lost"
        game.running = True
        game.mouse_world = Vec2()
        game.mouse_on_board = False
        game.elapsed = 0.0
        game.player = player
        game.enemies = []
        game.all_tanks = lambda: [player]
        game.respawn_player = Mock(side_effect=lambda: setattr(game, "state", "playing"))
        game.next_level = Mock()
        game.start_level = Mock()
        game.update_player = Mock()
        game.enemy_ai = SimpleNamespace(update=Mock())
        game.record_tank_tracks = Mock()
        game.combat = SimpleNamespace(update=Mock())
        game.mine_system = SimpleNamespace(update=Mock())
        game.evaluate_state = Mock()
        game.update_particles = Mock()
        game.update_effects = Mock()

        Game.handle_events(game)
        self.assertTrue(game._input_actions_blocked)
        Game.update(game, 0.01)

        input_manager.update.assert_called_once_with(
            player.position,
            game.mouse_world,
            actions_enabled=False,
            dt=0.01,
            world_size=(1020, 780),
        )
        self.assertFalse(game._input_actions_blocked)


if __name__ == "__main__":
    unittest.main()
