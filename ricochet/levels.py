from __future__ import annotations

import random

from .config import ENEMY_SPAWNS
from .models import GridCell


def enemy_layout(level: int) -> list[tuple[str, GridCell]]:
    """Build the enemy types and spawn positions for an unlimited level number."""
    enemy_count = min(len(ENEMY_SPAWNS), 2 + (level - 1) // 2)
    dark_count = min(enemy_count - 1, level // 3)
    kinds = ["light_gray"] * (enemy_count - dark_count) + ["dark_gray"] * dark_count

    level_random = random.Random(level * 7_919)
    level_random.shuffle(kinds)
    spawn_offset = (level - 1) % len(ENEMY_SPAWNS)
    spawns = ENEMY_SPAWNS[spawn_offset:] + ENEMY_SPAWNS[:spawn_offset]
    return list(zip(kinds, spawns))
