from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
ASSET_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
ENEMY_DATA_FILE = DATA_DIR / "enemies.csv"
AI_DATA_FILE = DATA_DIR / "ai_profiles.json"
MAP_FILE = DATA_DIR / "map.txt"
MAP_FILES = (
    MAP_FILE,
    DATA_DIR / "map_2.txt",
    DATA_DIR / "map_3.txt",
    DATA_DIR / "map_4.txt",
    DATA_DIR / "map_5.txt",
    DATA_DIR / "map_6.txt",
    DATA_DIR / "map_7.txt",
    DATA_DIR / "map_8.txt",
)
SPAWN_DATA_FILE = DATA_DIR / "spawns.csv"

TILE = 60
HUD_HEIGHT = 86
TANK_HALF = 17.0
BULLET_RADIUS = 4.5
MAX_BOUNCES = 1
MAX_PLAYER_BULLETS = 5
MAX_PLAYER_MINES = 2
PLAYER_STARTING_LIVES = 3
MINE_AUTO_TRIGGER_TIME = 8.0
MINE_WARNING_DURATION = 1.5
MINE_COLLISION_RADIUS = 11.0
MINE_TRIGGER_RADIUS = 25.0
MINE_EXPLOSION_RADIUS = TILE * 1.5
MINE_BEEP_INTERVAL = 0.18
MINE_MIN_SEPARATION = 30.0
MINE_ESCAPE_MARGIN = 12.0
EXPLOSION_EFFECT_DURATION = 0.7
TRACK_LIFETIME = 4.0
TRACK_SPACING = 8.0
SHIELD_FLASH_DURATION = 0.35

MOVEMENT_SPEEDS = {
    "stopped": 0.0,
    "slow": 58.0,
    "medium": 125.0,
    "fast": 180.0,
}
BULLET_SPEEDS = {
    "slow": 230.0,
    "fast": 516.0,
}
FIRE_RATE_DELAYS = {
    "slow": 0.75,
    "medium": 0.55,
    "tactical": 0.5,
    "normal": 0.38,
    "fast": 0.16,
}
SHOT_THINK_DELAYS = {
    "slow": 0.9,
    "medium": 0.5,
    "fast": 0.15,
}
PLAYER_SPEED = MOVEMENT_SPEEDS["medium"]
PLAYER_BULLET_SPEED = BULLET_SPEEDS["slow"]
PLAYER_FIRE_RATE = "fast"
PLAYER_SHOT_THINK_SPEED = "fast"
PLAYER_MIN_RICOCHET_DISTANCE = 24.0

BACKGROUND = (10, 15, 11)
CREAM = (238, 232, 206)
MUTED = (151, 168, 153)
FLOOR_A = (202, 191, 153)
PLAYER_COLOR = (82, 216, 244)
LIGHT_GRAY = (202, 207, 202)

ASSET_NAMES = (
    "floor_a",
    "floor_b",
    "wall",
    "wall_breakable",
    "hole",
    "player_body",
    "player_turret",
    "light_gray_body",
    "light_gray_turret",
    "dark_gray_body",
    "dark_gray_turret",
    "yellow_body",
    "yellow_turret",
    "dark_green_body",
    "dark_green_turret",
    "pink_body",
    "pink_turret",
    "bullet_player",
    "bullet_enemy",
    "bullet_flame",
    "mine",
    "mine_warning",
)


CUSTOM_ENEMY_KINDS = frozenset(
    {"light_gray", "dark_gray", "yellow", "dark_green", "pink"}
)


@dataclass(frozen=True)
class MapDefinition:
    layout: tuple[tuple[int, ...], ...]
    player_spawn: tuple[int, int] | None = None
    enemy_layout: tuple[tuple[str, tuple[int, int]], ...] | None = None


def _load_map(map_file: Path) -> MapDefinition:
    rows = []
    player_spawn = None
    enemy_layout = []
    custom_spawns = False
    for line_number, raw_line in enumerate(
        map_file.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            key, separator, value = line[1:].partition("=")
            key = key.strip().lower()
            if not separator or key not in {"player_spawn", "enemy_spawn"}:
                continue
            custom_spawns = True
            parts = tuple(part.strip() for part in value.split(","))
            try:
                if key == "player_spawn":
                    if len(parts) != 2:
                        raise ValueError
                    if player_spawn is not None:
                        raise ValueError(
                            f"Duplicate player spawn in {map_file} on line {line_number}"
                        )
                    player_spawn = (int(parts[0]), int(parts[1]))
                else:
                    if len(parts) != 3 or parts[0] not in CUSTOM_ENEMY_KINDS:
                        raise ValueError
                    enemy_layout.append(
                        (parts[0], (int(parts[1]), int(parts[2])))
                    )
            except ValueError as error:
                if str(error).startswith("Duplicate player spawn"):
                    raise
                raise ValueError(
                    f"Invalid {key} metadata in {map_file} on line {line_number}"
                ) from error
            continue
        if set(line) - {"0", "1", "2", "3"}:
            raise ValueError(f"Invalid character in {map_file}: {line!r}")
        rows.append(tuple(int(value) for value in line))
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError(f"Invalid map dimensions in {map_file}")
    layout = tuple(rows)
    if not custom_spawns:
        return MapDefinition(layout)
    if player_spawn is None:
        raise ValueError(f"Missing player_spawn metadata in {map_file}")

    occupied = {player_spawn}
    for kind, spawn in enemy_layout:
        if spawn in occupied:
            raise ValueError(f"Duplicate tank spawn {spawn} in {map_file}")
        occupied.add(spawn)
    for col, row in occupied:
        if (
            not 0 <= row < len(layout)
            or not 0 <= col < len(layout[row])
            or layout[row][col] != 0
        ):
            raise ValueError(f"Invalid tank spawn ({col}, {row}) in {map_file}")
    return MapDefinition(layout, player_spawn, tuple(enemy_layout))


def _load_spawns() -> tuple[tuple[int, int], ...]:
    with SPAWN_DATA_FILE.open(encoding="utf-8", newline="") as data_file:
        reader = csv.DictReader(data_file)
        if reader.fieldnames is None or not {"col", "row"}.issubset(reader.fieldnames):
            raise ValueError(f"Missing columns in {SPAWN_DATA_FILE}")
        spawns = tuple((int(row["col"]), int(row["row"])) for row in reader)
    if not spawns:
        raise ValueError(f"No enemy spawns in {SPAWN_DATA_FILE}")
    if len(set(spawns)) != len(spawns):
        raise ValueError(f"Duplicate enemy spawns in {SPAWN_DATA_FILE}")
    return spawns


MAP_DEFINITIONS = tuple(_load_map(map_file) for map_file in MAP_FILES)
MAP_LAYOUTS = tuple(definition.layout for definition in MAP_DEFINITIONS)
MAP_PLAYER_SPAWNS = tuple(definition.player_spawn for definition in MAP_DEFINITIONS)
MAP_ENEMY_LAYOUTS = tuple(definition.enemy_layout for definition in MAP_DEFINITIONS)
MAP = MAP_LAYOUTS[0]
ROWS = len(MAP)
COLS = len(MAP[0])
if any(len(layout) != ROWS or any(len(row) != COLS for row in layout) for layout in MAP_LAYOUTS):
    raise ValueError("All map layouts must have the same dimensions")
BOARD_WIDTH = COLS * TILE
BOARD_HEIGHT = ROWS * TILE
WINDOW_SIZE = (BOARD_WIDTH, BOARD_HEIGHT + HUD_HEIGHT)
ENEMY_SPAWNS = _load_spawns()

for map_file, layout, custom_enemy_layout in zip(
    MAP_FILES,
    MAP_LAYOUTS,
    MAP_ENEMY_LAYOUTS,
):
    if custom_enemy_layout is not None:
        continue
    for col, row in ENEMY_SPAWNS:
        if not 0 <= col < COLS or not 0 <= row < ROWS or layout[row][col] != 0:
            raise ValueError(f"Invalid enemy spawn ({col}, {row}) in {map_file}")
