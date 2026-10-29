from __future__ import annotations

import math
import pygame
import pytest

from cybtanks.config import BOARD_HEIGHT, BOARD_WIDTH, HUD_HEIGHT
from cybtanks.input_manager import InputManager, InputState, apply_deadzone


@pytest.fixture(autouse=True)
def init_pygame():
    pygame.init()
    yield
    pygame.quit()


def test_input_state_dataclass():
    move = pygame.Vector2(0, 1)
    aim = pygame.Vector2(1, 0)
    pos = pygame.Vector2(100, 200)
    state = InputState(
        move_vector=move,
        aim_vector=aim,
        aim_world_pos=pos,
        shoot_triggered=True,
        shoot_held=True,
        special_triggered=False,
        active_mode="KBM",
    )
    assert state.move_vector == move
    assert state.aim_vector == aim
    assert state.aim_world_pos == pos
    assert state.shoot_triggered is True
    assert state.shoot_held is True
    assert state.special_triggered is False
    assert state.active_mode == "KBM"


def test_apply_deadzone_below_threshold():
    # Below default threshold (0.18)
    res = apply_deadzone(0.1, 0.1)
    assert res == pygame.Vector2(0, 0)

    # Zero
    res_zero = apply_deadzone(0.0, 0.0)
    assert res_zero == pygame.Vector2(0, 0)


def test_apply_deadzone_above_threshold():
    # Above threshold
    res = apply_deadzone(1.0, 0.0)
    assert pytest.approx(res.x) == 1.0
    assert pytest.approx(res.y) == 0.0

    # Diagonal above threshold should be normalized
    res_diag = apply_deadzone(0.5, 0.5)
    assert pytest.approx(res_diag.length()) == 1.0


def test_apply_deadzone_custom_threshold():
    # Custom threshold 0.5
    res1 = apply_deadzone(0.4, 0.0, threshold=0.5)
    assert res1 == pygame.Vector2(0, 0)

    res2 = apply_deadzone(0.6, 0.0, threshold=0.5)
    assert pytest.approx(res2.x) == 1.0


def test_input_manager_init_no_gamepad():
    manager = InputManager()
    assert manager.active_mode == "KBM"
    assert manager.deadzone_threshold == 0.18
    assert manager.crosshair_distance == 120.0

    state = manager.get_state()
    assert isinstance(state, InputState)
    assert state.active_mode == "KBM"
    assert state.move_vector == pygame.Vector2(0, 0)


def test_mode_switching_keyboard_mouse():
    manager = InputManager()
    manager.active_mode = "GAMEPAD"

    # Key down switches to KBM
    event_key = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)
    manager.handle_event(event_key)
    assert manager.active_mode == "KBM"

    manager.active_mode = "GAMEPAD"
    # Mouse motion switches to KBM
    event_mouse = pygame.event.Event(pygame.MOUSEMOTION, pos=(100, 100), rel=(1, 1), buttons=(0, 0, 0))
    manager.handle_event(event_mouse)
    assert manager.active_mode == "KBM"

    manager.active_mode = "GAMEPAD"
    # Mouse button down switches to KBM
    event_click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(100, 100), button=1)
    manager.handle_event(event_click)
    assert manager.active_mode == "KBM"


def test_mode_switching_gamepad():
    manager = InputManager()
    assert manager.active_mode == "KBM"

    # Axis motion below threshold should not switch
    event_axis_small = pygame.event.Event(pygame.JOYAXISMOTION, joy=0, axis=0, value=0.05)
    manager.handle_event(event_axis_small)
    assert manager.active_mode == "KBM"

    # Axis motion above threshold switches to GAMEPAD
    event_axis_large = pygame.event.Event(pygame.JOYAXISMOTION, joy=0, axis=0, value=0.6)
    manager.handle_event(event_axis_large)
    assert manager.active_mode == "GAMEPAD"

    manager.active_mode = "KBM"
    # Button down switches to GAMEPAD
    event_btn = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0, button=0)
    manager.handle_event(event_btn)
    assert manager.active_mode == "GAMEPAD"


def test_gamepad_right_stick_persistence():
    manager = InputManager()
    manager.active_mode = "GAMEPAD"

    # Initial aim vector
    initial_aim = manager.last_aim_vector.copy()

    # Simulate right stick aim update manually or via mock
    new_dir = pygame.Vector2(0, -1).normalize()
    manager.last_aim_vector = new_dir.copy()

    # When update is called without stick input, aim_vector retains last valid direction
    player_pos = pygame.Vector2(200, 200)
    state = manager.update(player_pos)
    assert state.aim_vector == new_dir
    assert state.aim_vector != pygame.Vector2(0, 0)

    # Aim world pos should project at distance D
    expected_pos = player_pos + new_dir * manager.crosshair_distance
    assert state.aim_world_pos == expected_pos


def test_shooting_and_special_triggers():
    manager = InputManager()

    # Click triggers shoot
    event_click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(50, 50), button=1)
    manager.handle_event(event_click)
    assert manager.shoot_triggered is True

    # State update consumes one-frame trigger
    state = manager.update(pygame.Vector2(100, 100))
    assert state.shoot_triggered is True

    # Next update has shoot_triggered False
    state_next = manager.update(pygame.Vector2(100, 100))
    assert state_next.shoot_triggered is False

    # Space triggers special (mine)
    event_space = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)
    manager.handle_event(event_space)
    assert manager.special_triggered is True

    state_special = manager.update(pygame.Vector2(100, 100))
    assert state_special.special_triggered is True

    state_after = manager.update(pygame.Vector2(100, 100))
    assert state_after.special_triggered is False


def test_draw_crosshair():
    manager = InputManager()
    surface = pygame.Surface((BOARD_WIDTH, BOARD_HEIGHT))
    player_pos = pygame.Vector2(300, 300)

    # KBM mode
    manager.active_mode = "KBM"
    manager.draw_crosshair(surface, player_pos)

    # GAMEPAD mode
    manager.active_mode = "GAMEPAD"
    manager.draw_crosshair(surface, player_pos)


def test_hotplugging_events():
    manager = InputManager()

    # Device added and removed events should not crash
    event_add = pygame.event.Event(pygame.JOYDEVICEADDED, device_index=0)
    manager.handle_event(event_add)

    event_remove = pygame.event.Event(pygame.JOYDEVICEREMOVED, instance_id=0)
    manager.handle_event(event_remove)


def test_gamepad_buttons_mapping():
    manager = InputManager()
    manager.active_mode = "GAMEPAD"

    # Button 5: RB (shoot)
    event_rb = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0, button=5)
    manager.handle_event(event_rb)
    assert manager.shoot_triggered is True
    assert manager.shoot_held is True

    # Button 0: A (special)
    event_a = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0, button=0)
    manager.handle_event(event_a)
    assert manager.special_triggered is True
    assert manager.confirm_triggered is True

    # Button 3: Y (restart)
    event_y = pygame.event.Event(pygame.JOYBUTTONDOWN, joy=0, button=3)
    manager.handle_event(event_y)
    assert manager.restart_triggered is True

