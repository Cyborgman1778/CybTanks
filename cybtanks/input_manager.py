from __future__ import annotations

import os
from dataclasses import dataclass

import pygame
from pygame._sdl2 import controller as sdl_controller


KBM_MODE = "KBM"
GAMEPAD_MODE = "GAMEPAD"
DEFAULT_DEADZONE = 0.18
DEFAULT_TRIGGER_THRESHOLD = 0.5
DEFAULT_GAMEPAD_CURSOR_SPEED = 520.0
_CROSSHAIR_MARGIN = 18.0

_STEAM_WGI_GUID = "03000000de280000ff11000000007701"
_STEAM_DINPUT_GUID = "03000000de280000ff11000000000000"
_STEAM_DINPUT_ALT_GUID = "03000000de280000fc11000000000000"
_STEAM_WGI_SDL_MAPPING = (
    f"{_STEAM_WGI_GUID},Steam Virtual Gamepad,"
    "a:b0,b:b1,back:b6,dpdown:b12,dpleft:b13,dpright:b11,dpup:b10,"
    "leftshoulder:b4,leftstick:b8,lefttrigger:a4,leftx:a1,lefty:a0~,"
    "rightshoulder:b5,rightstick:b9,righttrigger:a5,rightx:a3,righty:a2~,"
    "start:b7,x:b2,y:b3,platform:Windows,"
)

if os.name == "nt" and _STEAM_WGI_GUID not in os.environ.get(
    "SDL_GAMECONTROLLERCONFIG",
    "",
):
    existing_mapping = os.environ.get("SDL_GAMECONTROLLERCONFIG", "")
    os.environ["SDL_GAMECONTROLLERCONFIG"] = "\n".join(
        value for value in (existing_mapping, _STEAM_WGI_SDL_MAPPING) if value
    )

_MOVEMENT_KEYS = frozenset(
    {
        pygame.K_w,
        pygame.K_a,
        pygame.K_s,
        pygame.K_d,
        pygame.K_UP,
        pygame.K_LEFT,
        pygame.K_DOWN,
        pygame.K_RIGHT,
    }
)
_SPECIAL_KEYS = frozenset(
    {pygame.K_SPACE, pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_e}
)


@dataclass
class InputState:
    move_vector: pygame.Vector2
    aim_vector: pygame.Vector2
    aim_world_pos: pygame.Vector2
    shoot_triggered: bool
    shoot_held: bool
    special_triggered: bool
    active_mode: str


@dataclass(frozen=True)
class _AxisBinding:
    index: int
    scale: float = 1.0


@dataclass(frozen=True)
class _TriggerBinding:
    index: int
    rest: float = -1.0
    pressed: float = 1.0


@dataclass(frozen=True)
class _RawGamepadMapping:
    left_stick: tuple[_AxisBinding, _AxisBinding]
    right_stick: tuple[_AxisBinding, _AxisBinding] | None
    left_trigger: _TriggerBinding | None = None
    right_trigger: _TriggerBinding | None = None
    shoot_buttons: tuple[int, ...] = (5,)
    special_buttons: tuple[int, ...] = (0,)


_STEAM_WGI_RAW_MAPPING = _RawGamepadMapping(
    left_stick=(_AxisBinding(1), _AxisBinding(0, -1.0)),
    right_stick=(_AxisBinding(3), _AxisBinding(2, -1.0)),
    left_trigger=_TriggerBinding(4),
    right_trigger=_TriggerBinding(5),
)
_STEAM_DINPUT_RAW_MAPPING = _RawGamepadMapping(
    left_stick=(_AxisBinding(0), _AxisBinding(1)),
    right_stick=(_AxisBinding(3), _AxisBinding(4)),
    left_trigger=_TriggerBinding(2, 0.0, 1.0),
    right_trigger=_TriggerBinding(2, 0.0, -1.0),
)
_STEAM_DINPUT_ALT_RAW_MAPPING = _RawGamepadMapping(
    left_stick=(_AxisBinding(0), _AxisBinding(1)),
    right_stick=(_AxisBinding(3), _AxisBinding(4)),
    left_trigger=_TriggerBinding(2),
    right_trigger=_TriggerBinding(5),
)


def apply_deadzone(
    axis_x: float,
    axis_y: float,
    threshold: float = DEFAULT_DEADZONE,
) -> pygame.Vector2:
    """Apply a radial deadzone while preserving the stick's analog magnitude."""
    if not 0 <= threshold < 1:
        raise ValueError("threshold must be in the range [0, 1)")
    vector = pygame.Vector2(axis_x, axis_y)
    magnitude = min(vector.length(), 1.0)
    if magnitude <= threshold:
        return pygame.Vector2()
    scaled_magnitude = (magnitude - threshold) / (1.0 - threshold)
    return vector.normalize() * scaled_magnitude


class InputManager:
    def __init__(
        self,
        deadzone: float = DEFAULT_DEADZONE,
        trigger_threshold: float = DEFAULT_TRIGGER_THRESHOLD,
        gamepad_cursor_speed: float = DEFAULT_GAMEPAD_CURSOR_SPEED,
    ) -> None:
        if not 0 <= deadzone < 1:
            raise ValueError("deadzone must be in the range [0, 1)")
        if not 0 <= trigger_threshold < 1:
            raise ValueError("trigger_threshold must be in the range [0, 1)")
        if gamepad_cursor_speed <= 0:
            raise ValueError("gamepad_cursor_speed must be positive")

        self.deadzone = deadzone
        self.trigger_threshold = trigger_threshold
        self.gamepad_cursor_speed = gamepad_cursor_speed
        self.joysticks: dict[int, pygame.joystick.JoystickType] = {}
        self.controllers: dict[int, sdl_controller.Controller] = {}
        self._raw_mappings: dict[int, _RawGamepadMapping] = {}
        self._active_instance_id: int | None = None
        self._controller_api_ready = False
        self._last_kbm_aim = pygame.Vector2(1, 0)
        self._last_gamepad_aim = pygame.Vector2(1, 0)
        self._gamepad_cursor_world: pygame.Vector2 | None = None
        self._previous_gamepad_actions: dict[int, tuple[bool, bool]] = {}
        self._raw_event_trigger_states: dict[int, tuple[bool, bool]] = {}
        self._controller_event_trigger_states: dict[tuple[int, int], bool] = {}
        self._pending_kbm_shoot = False
        self._pending_kbm_special = False
        self._pending_gamepad_shoot: set[int] = set()
        self._pending_gamepad_special: set[int] = set()
        self.state = InputState(
            move_vector=pygame.Vector2(),
            aim_vector=pygame.Vector2(1, 0),
            aim_world_pos=pygame.Vector2(),
            shoot_triggered=False,
            shoot_held=False,
            special_triggered=False,
            active_mode=KBM_MODE,
        )

        try:
            pygame.joystick.init()
        except pygame.error:
            return

        try:
            sdl_controller.init()
            self._controller_api_ready = True
        except (pygame.error, sdl_controller.error):
            self._controller_api_ready = False

        try:
            for device_index in range(pygame.joystick.get_count()):
                self._add_joystick(device_index)
        except pygame.error:
            self.joysticks.clear()
            self.controllers.clear()

    @property
    def active_mode(self) -> str:
        return self.state.active_mode

    @property
    def joystick_count(self) -> int:
        return len(self.joysticks)

    @staticmethod
    def poll_events() -> list[pygame.event.Event]:
        return pygame.event.get()

    @staticmethod
    def mouse_position() -> tuple[int, int]:
        try:
            return pygame.mouse.get_pos()
        except pygame.error:
            return (0, 0)

    def handle_event(self, event: pygame.event.Event, actions_enabled: bool = True) -> None:
        if event.type == pygame.JOYDEVICEADDED:
            device_index = getattr(event, "device_index", getattr(event, "which", -1))
            if device_index >= 0:
                self._add_joystick(device_index)
            return

        if event.type == pygame.JOYDEVICEREMOVED:
            instance_id = self._event_instance_id(event)
            if instance_id is not None:
                self._remove_joystick(instance_id)
            return

        if event.type == pygame.KEYDOWN:
            if event.key in _MOVEMENT_KEYS or event.key in _SPECIAL_KEYS:
                self._set_active_mode(KBM_MODE)
            if actions_enabled and event.key in _SPECIAL_KEYS:
                self._pending_kbm_special = True
            return

        if event.type == pygame.MOUSEMOTION:
            self._set_active_mode(KBM_MODE)
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            self._set_active_mode(KBM_MODE)
            if actions_enabled and event.button == 1:
                self._pending_kbm_shoot = True
            return

        if event.type == pygame.CONTROLLERAXISMOTION:
            device = self._event_joystick(event)
            if device is None or device[0] not in self.controllers:
                return
            instance_id, _ = device
            controller = self.controllers[instance_id]
            axis = int(event.axis)
            value = self._normalize_controller_event_value(event.value)
            if self._controller_axis_motion_is_active(controller, axis, value):
                self._activate_gamepad(instance_id)
            self._record_controller_trigger_event(
                instance_id,
                axis,
                value,
                actions_enabled,
            )
            return

        if event.type == pygame.CONTROLLERBUTTONDOWN:
            device = self._event_joystick(event)
            if device is None or device[0] not in self.controllers:
                return
            instance_id, _ = device
            self._activate_gamepad(instance_id)
            if not actions_enabled:
                return
            if event.button == pygame.CONTROLLER_BUTTON_RIGHTSHOULDER:
                self._pending_gamepad_shoot.add(instance_id)
            if event.button == pygame.CONTROLLER_BUTTON_A:
                self._pending_gamepad_special.add(instance_id)
            return

        if event.type == pygame.JOYAXISMOTION:
            device = self._event_joystick(event)
            if device is None:
                return
            instance_id, joystick = device
            if instance_id in self.controllers:
                if self._controller_has_active_axis(self.controllers[instance_id]):
                    self._activate_gamepad(instance_id)
                return

            axis = int(event.axis)
            value = float(event.value)
            if self._raw_axis_motion_is_active(joystick, axis, value):
                self._activate_gamepad(instance_id)
            self._record_raw_trigger_event(
                instance_id,
                joystick,
                axis,
                value,
                actions_enabled,
            )
            return

        if event.type == pygame.JOYBUTTONDOWN:
            device = self._event_joystick(event)
            if device is None:
                return
            instance_id, joystick = device
            self._activate_gamepad(instance_id)
            if not actions_enabled or instance_id in self.controllers:
                return
            mapping = self._raw_mappings[instance_id]
            if event.button in mapping.shoot_buttons:
                self._pending_gamepad_shoot.add(instance_id)
            if event.button in mapping.special_buttons:
                self._pending_gamepad_special.add(instance_id)

    def update(
        self,
        player_world_pos: pygame.Vector2,
        mouse_world_pos: pygame.Vector2,
        actions_enabled: bool = True,
        dt: float = 0.0,
        world_size: tuple[float, float] | None = None,
    ) -> InputState:
        player_position = pygame.Vector2(player_world_pos)
        mouse_target = pygame.Vector2(mouse_world_pos)
        action_edges: dict[int, tuple[bool, bool]] = {}
        current_actions: dict[int, tuple[bool, bool]] = {}
        for instance_id, joystick in self.joysticks.items():
            actions = self._gamepad_actions(instance_id, joystick)
            previous = self._previous_gamepad_actions.get(instance_id, actions)
            action_edges[instance_id] = (
                actions[0] and not previous[0],
                actions[1] and not previous[1],
            )
            current_actions[instance_id] = actions
            self._previous_gamepad_actions[instance_id] = actions

        joystick = self._active_joystick()
        active_actions = current_actions.get(self._active_instance_id, (False, False))
        active_edges = action_edges.get(self._active_instance_id, (False, False))
        if joystick is None and self.active_mode == GAMEPAD_MODE:
            self._set_active_mode(KBM_MODE)

        if self.active_mode == GAMEPAD_MODE and joystick is not None:
            move_vector, gamepad_aim = self._gamepad_sticks(
                self._active_instance_id,
                joystick,
            )
            if self._gamepad_cursor_world is None:
                self._gamepad_cursor_world = mouse_target.copy()
            if gamepad_aim.length_squared() > 0 and dt > 0:
                self._gamepad_cursor_world += (
                    gamepad_aim * self.gamepad_cursor_speed * dt
                )
            self._clamp_gamepad_cursor(world_size)
            aim_difference = self._gamepad_cursor_world - player_position
            if aim_difference.length_squared() > 0:
                self._last_gamepad_aim = aim_difference.normalize()
            aim_vector = self._last_gamepad_aim.copy()
            aim_world_pos = self._gamepad_cursor_world.copy()
            shoot_held = active_actions[0]
        else:
            move_vector = self._keyboard_move()
            self._gamepad_cursor_world = mouse_target.copy()
            difference = mouse_target - player_position
            if difference.length_squared() > 0:
                self._last_kbm_aim = difference.normalize()
            aim_vector = self._last_kbm_aim.copy()
            aim_world_pos = mouse_target
            shoot_held = self._mouse_shoot_held()

        shoot_triggered = (
            self._pending_kbm_shoot
            or bool(self._pending_gamepad_shoot)
            or self.active_mode == GAMEPAD_MODE
            and active_edges[0]
        )
        special_triggered = (
            self._pending_kbm_special
            or bool(self._pending_gamepad_special)
            or self.active_mode == GAMEPAD_MODE
            and active_edges[1]
        )
        if not actions_enabled:
            shoot_triggered = False
            special_triggered = False

        self.state = InputState(
            move_vector=move_vector,
            aim_vector=aim_vector,
            aim_world_pos=aim_world_pos,
            shoot_triggered=shoot_triggered,
            shoot_held=shoot_held,
            special_triggered=special_triggered,
            active_mode=self.active_mode,
        )
        self._clear_pending_actions()
        return self.state

    def crosshair_position(self, gamepad_screen_pos: pygame.Vector2) -> pygame.Vector2:
        if self.active_mode == KBM_MODE:
            return pygame.Vector2(self.mouse_position())
        return pygame.Vector2(gamepad_screen_pos)

    def draw_crosshair(
        self,
        surface: pygame.Surface,
        gamepad_screen_pos: pygame.Vector2,
    ) -> None:
        center = self.crosshair_position(gamepad_screen_pos)
        color = (238, 232, 206)
        pygame.draw.circle(surface, color, center, 10, 1)
        pygame.draw.line(surface, color, center + (-18, 0), center + (-6, 0), 1)
        pygame.draw.line(surface, color, center + (18, 0), center + (6, 0), 1)
        pygame.draw.line(surface, color, center + (0, -18), center + (0, -6), 1)
        pygame.draw.line(surface, color, center + (0, 18), center + (0, 6), 1)

    def _clamp_gamepad_cursor(
        self,
        world_size: tuple[float, float] | None,
    ) -> None:
        if self._gamepad_cursor_world is None or world_size is None:
            return
        max_x = max(0.0, float(world_size[0]) - 1.0)
        max_y = max(0.0, float(world_size[1]) - 1.0)
        margin_x = min(_CROSSHAIR_MARGIN, max_x / 2)
        margin_y = min(_CROSSHAIR_MARGIN, max_y / 2)
        self._gamepad_cursor_world.update(
            max(margin_x, min(max_x - margin_x, self._gamepad_cursor_world.x)),
            max(margin_y, min(max_y - margin_y, self._gamepad_cursor_world.y)),
        )

    def close(self) -> None:
        for instance_id in tuple(self.joysticks):
            self._remove_joystick(instance_id)
        if self._controller_api_ready:
            try:
                sdl_controller.quit()
            except (pygame.error, sdl_controller.error):
                pass
        try:
            pygame.joystick.quit()
        except pygame.error:
            pass

    def _set_active_mode(self, mode: str) -> None:
        self.state.active_mode = mode

    def _activate_gamepad(self, instance_id: int) -> None:
        if instance_id not in self.joysticks:
            return
        self._active_instance_id = instance_id
        self._set_active_mode(GAMEPAD_MODE)

    def _add_joystick(self, device_index: int) -> None:
        try:
            joystick = pygame.joystick.Joystick(device_index)
            if not joystick.get_init():
                joystick.init()
            instance_id = joystick.get_instance_id()
        except pygame.error:
            return

        if instance_id in self.joysticks:
            # Pygame can return the cached object for its initial duplicate add event.
            self._try_open_controller(instance_id, device_index)
            return

        self.joysticks[instance_id] = joystick
        self._raw_mappings[instance_id] = self._detect_raw_mapping(joystick)
        self._try_open_controller(instance_id, device_index)

        actions = self._gamepad_actions(instance_id, joystick)
        self._previous_gamepad_actions[instance_id] = actions
        self._raw_event_trigger_states[instance_id] = self._raw_trigger_actions(joystick)
        if self._active_instance_id is None:
            self._active_instance_id = instance_id

    def _try_open_controller(self, instance_id: int, device_index: int) -> None:
        if not self._controller_api_ready or instance_id in self.controllers:
            return
        try:
            if not sdl_controller.is_controller(device_index):
                return
            # Use the current hotplug index. from_joystick() uses the obsolete
            # original device index internally in pygame 2.6.x.
            controller = sdl_controller.Controller(device_index)
        except (pygame.error, sdl_controller.error):
            return

        self.controllers[instance_id] = controller
        left_trigger, right_trigger = self._controller_trigger_actions(controller)
        self._controller_event_trigger_states[
            (instance_id, pygame.CONTROLLER_AXIS_TRIGGERLEFT)
        ] = left_trigger
        self._controller_event_trigger_states[
            (instance_id, pygame.CONTROLLER_AXIS_TRIGGERRIGHT)
        ] = right_trigger
        if instance_id in self._previous_gamepad_actions:
            self._previous_gamepad_actions[instance_id] = self._gamepad_actions(
                instance_id,
                self.joysticks[instance_id],
            )

    def _remove_joystick(self, instance_id: int) -> None:
        controller = self.controllers.pop(instance_id, None)
        if controller is not None:
            try:
                controller.quit()
            except (pygame.error, sdl_controller.error):
                pass
        joystick = self.joysticks.pop(instance_id, None)
        if joystick is not None:
            try:
                joystick.quit()
            except pygame.error:
                pass

        self._raw_mappings.pop(instance_id, None)
        self._previous_gamepad_actions.pop(instance_id, None)
        self._raw_event_trigger_states.pop(instance_id, None)
        self._pending_gamepad_shoot.discard(instance_id)
        self._pending_gamepad_special.discard(instance_id)
        for key in tuple(self._controller_event_trigger_states):
            if key[0] == instance_id:
                self._controller_event_trigger_states.pop(key)

        if self._active_instance_id == instance_id:
            self._active_instance_id = next(iter(self.joysticks), None)
        if not self.joysticks and self.active_mode == GAMEPAD_MODE:
            self._set_active_mode(KBM_MODE)

    @staticmethod
    def _event_instance_id(event: pygame.event.Event) -> int | None:
        for attribute in ("instance_id", "joy", "which"):
            instance_id = getattr(event, attribute, None)
            if instance_id is not None:
                return int(instance_id)
        return None

    def _event_joystick(
        self,
        event: pygame.event.Event,
    ) -> tuple[int, pygame.joystick.JoystickType] | None:
        instance_id = self._event_instance_id(event)
        if instance_id not in self.joysticks:
            return None
        return instance_id, self.joysticks[instance_id]

    def _active_joystick(self) -> pygame.joystick.JoystickType | None:
        if self._active_instance_id in self.joysticks:
            return self.joysticks[self._active_instance_id]
        self._active_instance_id = next(iter(self.joysticks), None)
        if self._active_instance_id is None:
            return None
        return self.joysticks[self._active_instance_id]

    def _gamepad_sticks(
        self,
        instance_id: int | None,
        joystick: pygame.joystick.JoystickType,
    ) -> tuple[pygame.Vector2, pygame.Vector2]:
        controller = self.controllers.get(instance_id)
        if controller is not None:
            return (
                self._controller_stick(
                    controller,
                    pygame.CONTROLLER_AXIS_LEFTX,
                    pygame.CONTROLLER_AXIS_LEFTY,
                ),
                self._controller_stick(
                    controller,
                    pygame.CONTROLLER_AXIS_RIGHTX,
                    pygame.CONTROLLER_AXIS_RIGHTY,
                ),
            )

        mapping = self._raw_mappings[instance_id]
        aim = (
            self._raw_stick(joystick, mapping.right_stick)
            if mapping.right_stick is not None
            else pygame.Vector2()
        )
        return self._raw_stick(joystick, mapping.left_stick), aim

    def _gamepad_actions(
        self,
        instance_id: int,
        joystick: pygame.joystick.JoystickType,
    ) -> tuple[bool, bool]:
        controller = self.controllers.get(instance_id)
        if controller is not None:
            left_trigger, right_trigger = self._controller_trigger_actions(controller)
            return (
                right_trigger
                or self._controller_button(
                    controller,
                    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER,
                ),
                left_trigger
                or self._controller_button(controller, pygame.CONTROLLER_BUTTON_A),
            )

        mapping = self._raw_mappings[instance_id]
        right_trigger, left_trigger = self._raw_trigger_actions(joystick)
        return (
            right_trigger
            or any(
                self._raw_button(joystick, button)
                for button in mapping.shoot_buttons
            ),
            left_trigger
            or any(
                self._raw_button(joystick, button)
                for button in mapping.special_buttons
            ),
        )

    def _controller_trigger_actions(
        self,
        controller: sdl_controller.Controller,
    ) -> tuple[bool, bool]:
        return (
            self._controller_axis(controller, pygame.CONTROLLER_AXIS_TRIGGERLEFT)
            > self.trigger_threshold,
            self._controller_axis(controller, pygame.CONTROLLER_AXIS_TRIGGERRIGHT)
            > self.trigger_threshold,
        )

    def _raw_trigger_actions(
        self,
        joystick: pygame.joystick.JoystickType,
        override: tuple[int, float] | None = None,
    ) -> tuple[bool, bool]:
        mapping = self._raw_mappings[self._safe_instance_id(joystick)]
        return (
            self._raw_trigger_value(joystick, mapping.right_trigger, override)
            > self.trigger_threshold,
            self._raw_trigger_value(joystick, mapping.left_trigger, override)
            > self.trigger_threshold,
        )

    def _record_controller_trigger_event(
        self,
        instance_id: int,
        axis: int,
        value: float,
        actions_enabled: bool,
    ) -> None:
        if axis not in (
            pygame.CONTROLLER_AXIS_TRIGGERLEFT,
            pygame.CONTROLLER_AXIS_TRIGGERRIGHT,
        ):
            return
        pressed = value > self.trigger_threshold
        key = (instance_id, axis)
        was_pressed = self._controller_event_trigger_states.get(key, False)
        self._controller_event_trigger_states[key] = pressed
        if not actions_enabled or not pressed or was_pressed:
            return
        if axis == pygame.CONTROLLER_AXIS_TRIGGERRIGHT:
            self._pending_gamepad_shoot.add(instance_id)
        else:
            self._pending_gamepad_special.add(instance_id)

    def _record_raw_trigger_event(
        self,
        instance_id: int,
        joystick: pygame.joystick.JoystickType,
        axis: int,
        value: float,
        actions_enabled: bool,
    ) -> None:
        mapping = self._raw_mappings[instance_id]
        trigger_axes = {
            binding.index
            for binding in (mapping.left_trigger, mapping.right_trigger)
            if binding is not None
        }
        if axis not in trigger_axes:
            return
        current = self._raw_trigger_actions(joystick, (axis, value))
        previous = self._raw_event_trigger_states.get(instance_id, (False, False))
        self._raw_event_trigger_states[instance_id] = current
        if not actions_enabled:
            return
        if current[0] and not previous[0]:
            self._pending_gamepad_shoot.add(instance_id)
        if current[1] and not previous[1]:
            self._pending_gamepad_special.add(instance_id)

    def _controller_axis_motion_is_active(
        self,
        controller: sdl_controller.Controller,
        axis: int,
        value: float,
    ) -> bool:
        pairs = (
            (pygame.CONTROLLER_AXIS_LEFTX, pygame.CONTROLLER_AXIS_LEFTY),
            (pygame.CONTROLLER_AXIS_RIGHTX, pygame.CONTROLLER_AXIS_RIGHTY),
        )
        for axes in pairs:
            if axis not in axes:
                continue
            axis_x = value if axis == axes[0] else self._controller_axis(controller, axes[0])
            axis_y = value if axis == axes[1] else self._controller_axis(controller, axes[1])
            return apply_deadzone(axis_x, axis_y, self.deadzone).length_squared() > 0
        if axis in (
            pygame.CONTROLLER_AXIS_TRIGGERLEFT,
            pygame.CONTROLLER_AXIS_TRIGGERRIGHT,
        ):
            return value > self.trigger_threshold
        return False

    def _controller_has_active_axis(
        self,
        controller: sdl_controller.Controller,
    ) -> bool:
        left = self._controller_stick(
            controller,
            pygame.CONTROLLER_AXIS_LEFTX,
            pygame.CONTROLLER_AXIS_LEFTY,
        )
        right = self._controller_stick(
            controller,
            pygame.CONTROLLER_AXIS_RIGHTX,
            pygame.CONTROLLER_AXIS_RIGHTY,
        )
        left_trigger, right_trigger = self._controller_trigger_actions(controller)
        return (
            left.length_squared() > 0
            or right.length_squared() > 0
            or left_trigger
            or right_trigger
        )

    def _raw_axis_motion_is_active(
        self,
        joystick: pygame.joystick.JoystickType,
        axis: int,
        value: float,
    ) -> bool:
        instance_id = self._safe_instance_id(joystick)
        mapping = self._raw_mappings[instance_id]
        for bindings in (mapping.left_stick, mapping.right_stick):
            if bindings is None or axis not in {binding.index for binding in bindings}:
                continue
            return (
                self._raw_stick(joystick, bindings, (axis, value)).length_squared()
                > 0
            )

        current_triggers = self._raw_trigger_actions(joystick, (axis, value))
        return current_triggers[0] or current_triggers[1]

    def _detect_raw_mapping(
        self,
        joystick: pygame.joystick.JoystickType,
    ) -> _RawGamepadMapping:
        guid = self._joystick_guid(joystick).lower()
        if guid == _STEAM_WGI_GUID:
            return _STEAM_WGI_RAW_MAPPING
        if guid == _STEAM_DINPUT_GUID:
            return _STEAM_DINPUT_RAW_MAPPING
        if guid == _STEAM_DINPUT_ALT_GUID:
            return _STEAM_DINPUT_ALT_RAW_MAPPING

        axis_count = self._raw_axis_count(joystick)
        name = self._joystick_name(joystick).lower()
        left_stick = (_AxisBinding(0), _AxisBinding(1))

        if "xbox" in name or "xinput" in name:
            if axis_count == 5:
                return _RawGamepadMapping(
                    left_stick=left_stick,
                    right_stick=(_AxisBinding(4), _AxisBinding(3)),
                    left_trigger=_TriggerBinding(2, 0.0, 1.0),
                    right_trigger=_TriggerBinding(2, 0.0, -1.0),
                )
            return _RawGamepadMapping(
                left_stick=left_stick,
                right_stick=(_AxisBinding(3), _AxisBinding(4)),
                left_trigger=_TriggerBinding(2),
                right_trigger=_TriggerBinding(5),
            )

        if "switch" in name:
            return _RawGamepadMapping(
                left_stick=left_stick,
                right_stick=(_AxisBinding(2), _AxisBinding(3)),
            )

        if axis_count == 4:
            right_stick = (_AxisBinding(2), _AxisBinding(3))
        else:
            right_stick = None
        # Raw axes have no universal semantics. Unknown devices use buttons for
        # actions so moving a misidentified stick can never fire or place a mine.
        return _RawGamepadMapping(left_stick=left_stick, right_stick=right_stick)

    def _controller_stick(
        self,
        controller: sdl_controller.Controller,
        axis_x: int,
        axis_y: int,
    ) -> pygame.Vector2:
        return apply_deadzone(
            self._controller_axis(controller, axis_x),
            self._controller_axis(controller, axis_y),
            self.deadzone,
        )

    def _raw_stick(
        self,
        joystick: pygame.joystick.JoystickType,
        bindings: tuple[_AxisBinding, _AxisBinding],
        override: tuple[int, float] | None = None,
    ) -> pygame.Vector2:
        return apply_deadzone(
            self._raw_axis_binding(joystick, bindings[0], override),
            self._raw_axis_binding(joystick, bindings[1], override),
            self.deadzone,
        )

    def _raw_trigger_value(
        self,
        joystick: pygame.joystick.JoystickType,
        binding: _TriggerBinding | None,
        override: tuple[int, float] | None = None,
    ) -> float:
        if binding is None:
            return 0.0
        raw_value = (
            override[1]
            if override is not None and override[0] == binding.index
            else self._raw_axis(joystick, binding.index)
        )
        span = binding.pressed - binding.rest
        if span == 0:
            return 0.0
        return max(0.0, min(1.0, (raw_value - binding.rest) / span))

    def _raw_axis_binding(
        self,
        joystick: pygame.joystick.JoystickType,
        binding: _AxisBinding,
        override: tuple[int, float] | None = None,
    ) -> float:
        value = (
            override[1]
            if override is not None and override[0] == binding.index
            else self._raw_axis(joystick, binding.index)
        )
        return max(-1.0, min(1.0, value * binding.scale))

    @staticmethod
    def _normalize_controller_event_value(value: int | float) -> float:
        if isinstance(value, int):
            return max(-1.0, min(1.0, value / 32_767.0))
        return max(-1.0, min(1.0, float(value)))

    @classmethod
    def _controller_axis(
        cls,
        controller: sdl_controller.Controller,
        axis: int,
    ) -> float:
        try:
            return cls._normalize_controller_event_value(controller.get_axis(axis))
        except (pygame.error, sdl_controller.error):
            return 0.0

    @staticmethod
    def _controller_button(
        controller: sdl_controller.Controller,
        button: int,
    ) -> bool:
        try:
            return bool(controller.get_button(button))
        except (pygame.error, sdl_controller.error):
            return False

    @staticmethod
    def _raw_axis_count(joystick: pygame.joystick.JoystickType) -> int:
        try:
            return joystick.get_numaxes()
        except pygame.error:
            return 0

    @classmethod
    def _raw_axis(
        cls,
        joystick: pygame.joystick.JoystickType,
        axis: int,
    ) -> float:
        if axis < 0 or axis >= cls._raw_axis_count(joystick):
            return 0.0
        try:
            return float(joystick.get_axis(axis))
        except pygame.error:
            return 0.0

    @staticmethod
    def _raw_button(
        joystick: pygame.joystick.JoystickType,
        button: int,
    ) -> bool:
        try:
            if button < 0 or button >= joystick.get_numbuttons():
                return False
            return bool(joystick.get_button(button))
        except pygame.error:
            return False

    @staticmethod
    def _safe_instance_id(joystick: pygame.joystick.JoystickType) -> int | None:
        try:
            return joystick.get_instance_id()
        except pygame.error:
            return None

    @staticmethod
    def _joystick_name(joystick: pygame.joystick.JoystickType) -> str:
        try:
            return str(joystick.get_name())
        except (AttributeError, pygame.error):
            return ""

    @staticmethod
    def _joystick_guid(joystick: pygame.joystick.JoystickType) -> str:
        try:
            return str(joystick.get_guid())
        except (AttributeError, pygame.error):
            return ""

    @staticmethod
    def _keyboard_move() -> pygame.Vector2:
        try:
            keys = pygame.key.get_pressed()
            horizontal = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(
                keys[pygame.K_a] or keys[pygame.K_LEFT]
            )
            vertical = int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(
                keys[pygame.K_w] or keys[pygame.K_UP]
            )
        except (IndexError, pygame.error):
            return pygame.Vector2()
        direction = pygame.Vector2(horizontal, vertical)
        return direction.normalize() if direction.length_squared() > 0 else direction

    @staticmethod
    def _mouse_shoot_held() -> bool:
        try:
            buttons = pygame.mouse.get_pressed()
            return bool(buttons and buttons[0])
        except pygame.error:
            return False

    def _clear_pending_actions(self) -> None:
        self._pending_kbm_shoot = False
        self._pending_kbm_special = False
        self._pending_gamepad_shoot.clear()
        self._pending_gamepad_special.clear()
