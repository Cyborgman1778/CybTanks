from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING
import pygame

from .config import BOARD_HEIGHT, BOARD_WIDTH, HUD_HEIGHT
from .geometry import clamp

if TYPE_CHECKING:
    from .models import Tank


@dataclass
class InputState:
    move_vector: pygame.Vector2       # Vector normalizado (-1.0 a 1.0) para movimiento continuo
    aim_vector: pygame.Vector2        # Vector unitario de dirección de apuntado
    aim_world_pos: pygame.Vector2     # Coordenada absoluta de apuntado (cursor en KBM / proyección en mando)
    shoot_triggered: bool             # True si se disparó en este frame (click / RT down)
    shoot_held: bool                  # True si se mantiene presionado el botón de disparo
    special_triggered: bool           # True si se activó la habilidad especial en este frame
    active_mode: str                  # 'KBM' | 'GAMEPAD'


def apply_deadzone(axis_x: float, axis_y: float, threshold: float = 0.18) -> pygame.Vector2:
    vec = pygame.Vector2(axis_x, axis_y)
    if vec.length() < threshold:
        return pygame.Vector2(0, 0)
    return vec.normalize()


class InputManager:
    def __init__(
        self,
        deadzone_threshold: float = 0.18,
        crosshair_distance: float = 120.0,
        board_offset: tuple[float, float] = (0.0, float(HUD_HEIGHT)),
    ) -> None:
        self.deadzone_threshold = deadzone_threshold
        self.crosshair_distance = crosshair_distance
        self.board_offset = pygame.Vector2(board_offset)
        self.active_mode = "KBM"

        # Persistence for right stick aiming
        self.last_aim_vector = pygame.Vector2(1.0, 0.0)

        # Trigger states
        self.shoot_triggered = False
        self.shoot_held = False
        self.special_triggered = False
        self.confirm_triggered = False
        self.restart_triggered = False
        self.escape_triggered = False

        self._prev_rt_down = False
        self._prev_lt_down = False

        # Joysticks management
        self.joysticks: dict[int, pygame.joystick.Joystick] = {}
        self._init_joysticks()

        # Initial state snapshot
        self.current_state = InputState(
            move_vector=pygame.Vector2(0, 0),
            aim_vector=self.last_aim_vector.copy(),
            aim_world_pos=pygame.Vector2(BOARD_WIDTH / 2, BOARD_HEIGHT / 2),
            shoot_triggered=False,
            shoot_held=False,
            special_triggered=False,
            active_mode=self.active_mode,
        )

    def _init_joysticks(self) -> None:
        if not pygame.joystick.get_init():
            try:
                pygame.joystick.init()
            except pygame.error:
                return
        for index in range(pygame.joystick.get_count()):
            self._add_joystick(index)

    def _add_joystick(self, device_index: int) -> None:
        try:
            joy = pygame.joystick.Joystick(device_index)
            joy.init()
            instance_id = joy.get_instance_id() if hasattr(joy, "get_instance_id") else joy.get_id()
            self.joysticks[instance_id] = joy
        except pygame.error:
            pass

    def _remove_joystick(self, instance_id: int) -> None:
        if instance_id in self.joysticks:
            try:
                self.joysticks[instance_id].quit()
            except pygame.error:
                pass
            del self.joysticks[instance_id]

    def handle_event(self, event: pygame.event.Event) -> None:
        # Hotplugging
        if event.type == pygame.JOYDEVICEADDED:
            device_index = getattr(event, "device_index", getattr(event, "which", 0))
            self._add_joystick(device_index)
        elif event.type == pygame.JOYDEVICEREMOVED:
            instance_id = getattr(event, "instance_id", getattr(event, "which", 0))
            self._remove_joystick(instance_id)

        # Device active mode detection & KBM inputs
        elif event.type == pygame.KEYDOWN:
            self.active_mode = "KBM"
            if event.key in (pygame.K_SPACE, pygame.K_LSHIFT, pygame.K_e):
                self.special_triggered = True
            elif event.key == pygame.K_r:
                self.restart_triggered = True
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.confirm_triggered = True
            elif event.key == pygame.K_ESCAPE:
                self.escape_triggered = True

        elif event.type == pygame.MOUSEMOTION:
            self.active_mode = "KBM"

        elif event.type == pygame.MOUSEBUTTONDOWN:
            self.active_mode = "KBM"
            if event.button == 1:
                self.shoot_triggered = True
                self.shoot_held = True

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.shoot_held = False

        # Gamepad inputs
        elif event.type == pygame.JOYAXISMOTION:
            if abs(event.value) > self.deadzone_threshold:
                self.active_mode = "GAMEPAD"

        elif event.type == pygame.JOYBUTTONDOWN:
            self.active_mode = "GAMEPAD"
            # Button 5: RB / R1 -> Shoot
            if event.button == 5:
                self.shoot_triggered = True
                self.shoot_held = True
            # Button 0: A / Cross, Button 4: LB / L1 -> Special
            elif event.button in (0, 4):
                self.special_triggered = True
                self.confirm_triggered = True
            # Button 2: X / Square, Button 3: Y / Triangle, Button 6: Back / Select -> Restart
            elif event.button in (2, 3, 6):
                self.restart_triggered = True
            # Button 7: Start / Options -> Confirm
            elif event.button == 7:
                self.confirm_triggered = True

        elif event.type == pygame.JOYBUTTONUP:
            if event.button == 5:
                self.shoot_held = False

        elif event.type == pygame.JOYHATMOTION:
            if event.value != (0, 0):
                self.active_mode = "GAMEPAD"

    def _read_right_stick(self, joy: pygame.joystick.Joystick) -> pygame.Vector2:
        num_axes = joy.get_numaxes()
        candidate_pairs = []
        if num_axes >= 4:
            candidate_pairs.append((2, 3))
        if num_axes >= 5:
            candidate_pairs.append((3, 4))

        for ax_idx, ay_idx in candidate_pairs:
            try:
                vx = joy.get_axis(ax_idx)
                vy = joy.get_axis(ay_idx)
                # Check for rested trigger artifact (un-actuated trigger resting at -1.0)
                if abs(vx + 1.0) < 0.05 or abs(vy + 1.0) < 0.05:
                    continue
                vec = apply_deadzone(vx, vy, self.deadzone_threshold)
                if vec.length_squared() > 0:
                    return vec
            except pygame.error:
                continue
        return pygame.Vector2(0, 0)

    def _read_triggers(self, joy: pygame.joystick.Joystick) -> tuple[float, float]:
        num_axes = joy.get_numaxes()
        rt_val = 0.0
        lt_val = 0.0
        try:
            if num_axes >= 6:
                lt_raw = joy.get_axis(4)
                rt_raw = joy.get_axis(5)
                lt_val = max(0.0, lt_raw) if lt_raw > 0.0 else 0.0
                rt_val = max(0.0, rt_raw) if rt_raw > 0.0 else 0.0
            elif num_axes >= 5:
                rt_raw = joy.get_axis(4)
                rt_val = max(0.0, rt_raw) if rt_raw > 0.0 else 0.0
        except pygame.error:
            pass

        # Also support bumper / trigger buttons fallback
        try:
            if joy.get_numbuttons() > 5:
                if joy.get_button(5):  # RB
                    rt_val = max(rt_val, 1.0)
                if joy.get_button(4):  # LB
                    lt_val = max(lt_val, 1.0)
        except pygame.error:
            pass

        return rt_val, lt_val

    def update(self, player_world_pos: pygame.Vector2 | tuple[float, float] | None = None) -> InputState:
        player_pos = (
            pygame.Vector2(player_world_pos)
            if player_world_pos is not None
            else pygame.Vector2(BOARD_WIDTH / 2, BOARD_HEIGHT / 2)
        )

        # 1. Continuous movement vector
        if self.active_mode == "KBM":
            keys = pygame.key.get_pressed()
            dx = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(
                keys[pygame.K_a] or keys[pygame.K_LEFT]
            )
            dy = int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(
                keys[pygame.K_w] or keys[pygame.K_UP]
            )
            move_vector = pygame.Vector2(dx, dy)
            if move_vector.length_squared() > 0:
                move_vector.normalize_ip()
        else:
            move_vector = pygame.Vector2(0, 0)
            for joy in self.joysticks.values():
                try:
                    if joy.get_numaxes() >= 2:
                        lx = joy.get_axis(0)
                        ly = joy.get_axis(1)
                        ls_vec = apply_deadzone(lx, ly, self.deadzone_threshold)
                        if ls_vec.length_squared() > 0:
                            move_vector = ls_vec
                            break
                    if move_vector.length_squared() == 0 and joy.get_numhats() > 0:
                        hx, hy = joy.get_hat(0)
                        if hx != 0 or hy != 0:
                            move_vector = pygame.Vector2(hx, -hy).normalize()
                            break
                except pygame.error:
                    continue

        # 2. Continuous aim vector & world coordinate
        if self.active_mode == "KBM":
            mouse_screen = pygame.mouse.get_pos()
            board_x = clamp(mouse_screen[0] - self.board_offset.x, 0, BOARD_WIDTH)
            board_y = clamp(mouse_screen[1] - self.board_offset.y, 0, BOARD_HEIGHT)
            aim_world_pos = pygame.Vector2(board_x, board_y)
            diff = aim_world_pos - player_pos
            if diff.length_squared() > 0:
                self.last_aim_vector = diff.normalize()
            aim_vector = self.last_aim_vector.copy()
        else:
            rs_vec = pygame.Vector2(0, 0)
            for joy in self.joysticks.values():
                rs_vec = self._read_right_stick(joy)
                if rs_vec.length_squared() > 0:
                    break
            if rs_vec.length_squared() > 0:
                self.last_aim_vector = rs_vec.normalize()
            aim_vector = self.last_aim_vector.copy()
            aim_world_pos = player_pos + aim_vector * self.crosshair_distance
            aim_world_pos.x = clamp(aim_world_pos.x, 0, BOARD_WIDTH)
            aim_world_pos.y = clamp(aim_world_pos.y, 0, BOARD_HEIGHT)

        # 3. Gamepad analog triggers checking
        if self.active_mode == "GAMEPAD":
            rt_down = False
            lt_down = False
            for joy in self.joysticks.values():
                rt_val, lt_val = self._read_triggers(joy)
                if rt_val > 0.5:
                    rt_down = True
                if lt_val > 0.5:
                    lt_down = True

            if rt_down and not self._prev_rt_down:
                self.shoot_triggered = True
            if rt_down:
                self.shoot_held = True
            if lt_down and not self._prev_lt_down:
                self.special_triggered = True

            self._prev_rt_down = rt_down
            self._prev_lt_down = lt_down
        else:
            mouse_pressed = pygame.mouse.get_pressed()
            if mouse_pressed[0]:
                self.shoot_held = True

        state = InputState(
            move_vector=move_vector,
            aim_vector=aim_vector,
            aim_world_pos=aim_world_pos,
            shoot_triggered=self.shoot_triggered,
            shoot_held=self.shoot_held,
            special_triggered=self.special_triggered,
            active_mode=self.active_mode,
        )
        self.current_state = state

        # Clear one-frame triggers
        self.shoot_triggered = False
        self.special_triggered = False

        return state

    def get_state(self) -> InputState:
        return self.current_state

    def draw_crosshair(
        self,
        surface: pygame.Surface,
        player_screen_pos: pygame.Vector2,
        color: tuple[int, int, int] = (238, 232, 206),
        radius: float = 10.0,
    ) -> None:
        if self.active_mode == "KBM":
            mouse_pos = pygame.mouse.get_pos()
            crosshair_pos = pygame.Vector2(
                mouse_pos[0] - self.board_offset.x,
                mouse_pos[1] - self.board_offset.y,
            )
        else:
            crosshair_pos = player_screen_pos + self.last_aim_vector * self.crosshair_distance

        cx = round(crosshair_pos.x)
        cy = round(crosshair_pos.y)
        pygame.draw.circle(surface, color, (cx, cy), max(1, round(radius)), 1)
        pygame.draw.line(surface, color, (cx - 18, cy), (cx - 6, cy), 1)
        pygame.draw.line(surface, color, (cx + 18, cy), (cx + 6, cy), 1)
        pygame.draw.line(surface, color, (cx, cy - 18), (cx, cy - 6), 1)
        pygame.draw.line(surface, color, (cx, cy + 18), (cx, cy + 6), 1)

    def rumble(self, low_frequency: float = 0.5, high_frequency: float = 0.5, duration_ms: int = 200) -> None:
        for joy in self.joysticks.values():
            try:
                joy.rumble(low_frequency, high_frequency, duration_ms)
            except (AttributeError, pygame.error):
                pass

