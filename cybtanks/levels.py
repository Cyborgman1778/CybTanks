from __future__ import annotations

import random

from .config import ENEMY_SPAWNS
from .models import GridCell


def enemy_layout(level: int) -> list[tuple[str, GridCell]]:
    """Build the enemy types and spawn positions for an unlimited level number."""
    enemy_count = min(len(ENEMY_SPAWNS), 2 + (level - 1) // 2)
    special_slots = enemy_count - 1
    green_count = min(3, special_slots, max(0, (level - 5) // 3))
    yellow_count = min(3, special_slots - green_count, max(0, (level - 2) // 3))
    remaining = enemy_count - yellow_count - green_count
    dark_count = min(remaining - 1, level // 3)
    light_count = remaining - dark_count
    kinds = (
        ["light_gray"] * light_count
        + ["dark_gray"] * dark_count
        + ["yellow"] * yellow_count
        + ["dark_green"] * green_count
    )

    level_random = random.Random(level * 7_919)
    level_random.shuffle(kinds)
    spawn_offset = (level - 1) % len(ENEMY_SPAWNS)
    spawns = ENEMY_SPAWNS[spawn_offset:] + ENEMY_SPAWNS[:spawn_offset]
    return list(zip(kinds, spawns))
