from __future__ import annotations

import csv
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
ASSET_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
ENEMY_DATA_FILE = DATA_DIR / "enemies.csv"
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

MOVEMENT_SPEEDS = {
    "stopped": 0.0,
    "slow": 58.0,
    "medium": 125.0,
    "fast": 180.0,
}
BULLET_SPEEDS = {
    "slow": 230.0,
    "fast": 400.0,
}
FIRE_RATE_DELAYS = {
    "slow": 0.75,
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
    "bullet_player",
    "bullet_enemy",
    "bullet_flame",
    "mine",
    "mine_warning",
)


def _load_map(map_file: Path) -> tuple[tuple[int, ...], ...]:
    rows = []
    for raw_line in map_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if set(line) - {"0", "1", "2", "3"}:
            raise ValueError(f"Invalid character in {map_file}: {line!r}")
        rows.append(tuple(int(value) for value in line))
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError(f"Invalid map dimensions in {map_file}")
    return tuple(rows)


def _load_spawns() -> tuple[tuple[int, int], ...]:
    with SPAWN_DATA_FILE.open(encoding="utf-8", newline="") as data_file:
        return tuple((int(row["col"]), int(row["row"])) for row in csv.DictReader(data_file))


MAP_LAYOUTS = tuple(_load_map(map_file) for map_file in MAP_FILES)
MAP = MAP_LAYOUTS[0]
ROWS = len(MAP)
COLS = len(MAP[0])
if any(len(layout) != ROWS or any(len(row) != COLS for row in layout) for layout in MAP_LAYOUTS):
    raise ValueError("All map layouts must have the same dimensions")
BOARD_WIDTH = COLS * TILE
BOARD_HEIGHT = ROWS * TILE
WINDOW_SIZE = (BOARD_WIDTH, BOARD_HEIGHT + HUD_HEIGHT)
ENEMY_SPAWNS = _load_spawns()

for map_file, layout in zip(MAP_FILES, MAP_LAYOUTS):
    for col, row in ENEMY_SPAWNS:
        if not 0 <= col < COLS or not 0 <= row < ROWS or layout[row][col] != 0:
            raise ValueError(f"Invalid enemy spawn ({col}, {row}) in {map_file}")
