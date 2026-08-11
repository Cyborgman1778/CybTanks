from __future__ import annotations

from collections.abc import Callable

from .ai_config import AIProfile, AISettings
from .config import TILE
from .models import Tank


class SquadCoordinator:
    def __init__(self, settings: AISettings) -> None:
        self.settings = settings
        self.attack_slots: dict[int, float] = {}

    def reset(self) -> None:
        self.attack_slots.clear()

    def begin_frame(
        self,
        enemies: list[Tank],
        now: float,
        profile_for: Callable[[Tank], AIProfile],
    ) -> None:
        alive_ids = {enemy.tank_id for enemy in enemies if enemy.alive}
        self.attack_slots = {
            tank_id: expiry
            for tank_id, expiry in self.attack_slots.items()
            if tank_id in alive_ids and expiry > now
        }
        mobile = []
        for enemy in enemies:
            if not enemy.alive:
                continue
            role = profile_for(enemy).preferred_role
            if enemy.speed <= 0:
                role = "support"
            enemy.ai.role = role
            if enemy.speed > 0:
                mobile.append(enemy)
        if mobile and all(enemy.ai.role != "assault" for enemy in mobile):
            max(mobile, key=lambda enemy: (enemy.speed, -enemy.tank_id)).ai.role = "assault"

    def share_contact(
        self,
        observer: Tank,
        enemies: list[Tank],
        now: float,
        profile_for: Callable[[Tank], AIProfile],
    ) -> None:
        memory = observer.ai
        target = memory.last_known_position
        config = self.settings.global_config
        if target is None or now - memory.last_alert_time < config.alert_cooldown:
            return
        memory.last_alert_time = now
        communication_range = config.communication_range_tiles * TILE
        for ally in enemies:
            if (
                not ally.alive
                or ally.tank_id == observer.tank_id
                or ally.position.distance_to(observer.position) > communication_range
                or ally.ai.target_visible
            ):
                continue
            profile = profile_for(ally)
            ally.ai.last_known_position = target.copy()
            ally.ai.last_heard_position = target.copy()
            ally.ai.memory_remaining = max(ally.ai.memory_remaining, profile.memory_duration)
            ally.ai.hearing_remaining = max(
                ally.ai.hearing_remaining,
                profile.hearing_memory_duration,
            )
            ally.ai.awareness = max(ally.ai.awareness, config.alert_awareness)
            ally.ai.decision_timer = 0.0

    def request_attack_slot(self, enemy: Tank, now: float) -> bool:
        config = self.settings.global_config
        if enemy.tank_id in self.attack_slots:
            self.attack_slots[enemy.tank_id] = now + config.attack_slot_duration
            return True
        if len(self.attack_slots) >= config.max_attackers:
            return False
        self.attack_slots[enemy.tank_id] = now + config.attack_slot_duration
        return True

    def release_attack_slot(self, tank_id: int) -> None:
        self.attack_slots.pop(tank_id, None)
