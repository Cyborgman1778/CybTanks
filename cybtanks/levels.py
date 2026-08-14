from __future__ import annotations

import random

from .config import ENEMY_SPAWNS, MAP_ENEMY_LAYOUTS, MAP_LAYOUTS, MAP_PLAYER_SPAWNS
from .models import GridCell


PINK_FIRST_LEVEL = 10
DARK_GRAY_SHIELD_LEVEL = 12


def map_layout(level: int) -> tuple[tuple[int, ...], ...]:
    """Select a map deterministically and cycle layouts for unlimited levels."""
    if level < 1:
        raise ValueError("Level numbers start at 1")
    return MAP_LAYOUTS[(level - 1) % len(MAP_LAYOUTS)]


def player_spawn(level: int) -> GridCell:
    """Return the map-specific player spawn or the legacy starting cell."""
    if level < 1:
        raise ValueError("Level numbers start at 1")
    return MAP_PLAYER_SPAWNS[(level - 1) % len(MAP_LAYOUTS)] or (1, 1)


def enemy_layout(level: int) -> list[tuple[str, GridCell]]:
    """Build the enemy types and spawn positions for an unlimited level number."""
    if level < 1:
        raise ValueError("Level numbers start at 1")
    custom_layout = MAP_ENEMY_LAYOUTS[(level - 1) % len(MAP_LAYOUTS)]
    if custom_layout is not None:
        return list(custom_layout)
    enemy_count = min(len(ENEMY_SPAWNS), 2 + (level - 1) // 2)
    special_slots = enemy_count - (2 if level >= 3 else 1)
    green_count = min(3, special_slots, max(0, (level - 5) // 3))
    pink_count = min(
        3,
        special_slots - green_count,
        max(0, (level - (PINK_FIRST_LEVEL - 3)) // 3),
    )
    yellow_count = min(
        3,
        special_slots - green_count - pink_count,
        max(0, (level - 2) // 3),
    )
    remaining = enemy_count - yellow_count - green_count - pink_count
    dark_count = min(remaining - 1, level // 3)
    light_count = remaining - dark_count
    kinds = (
        ["light_gray"] * light_count
        + ["dark_gray"] * dark_count
        + ["yellow"] * yellow_count
        + ["dark_green"] * green_count
        + ["pink"] * pink_count
    )

    level_random = random.Random(level * 7_919)
    level_random.shuffle(kinds)
    spawn_offset = (level - 1) % len(ENEMY_SPAWNS)
    spawns = ENEMY_SPAWNS[spawn_offset:] + ENEMY_SPAWNS[:spawn_offset]
    return list(zip(kinds, spawns))


def shielded_dark_gray_count(level: int) -> int:
    if level < DARK_GRAY_SHIELD_LEVEL:
        return 0
    return 2 if level >= 21 else 1
