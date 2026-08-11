from __future__ import annotations

import csv

from .config import (
    BULLET_SPEEDS,
    ENEMY_DATA_FILE,
    FIRE_RATE_DELAYS,
    MOVEMENT_SPEEDS,
    SHOT_THINK_DELAYS,
)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid color in {ENEMY_DATA_FILE}: {value!r}")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return red, green, blue


def load_enemy_catalog() -> dict[str, dict[str, str]]:
    with ENEMY_DATA_FILE.open(encoding="utf-8", newline="") as data_file:
        catalog = {row["tipo_id"]: row for row in csv.DictReader(data_file)}
    required = {"light_gray", "dark_gray", "yellow", "dark_green", "pink"}
    if not required.issubset(catalog):
        raise ValueError(f"Missing enemy definitions in {ENEMY_DATA_FILE}")
    for enemy_id, config in catalog.items():
        if config["velocidad_movimiento"] not in MOVEMENT_SPEEDS:
            raise ValueError(f"Invalid movement speed for {enemy_id}")
        if config["velocidad_bala"] not in BULLET_SPEEDS:
            raise ValueError(f"Invalid bullet speed for {enemy_id}")
        if config["cadencia_disparo"] not in FIRE_RATE_DELAYS:
            raise ValueError(f"Invalid fire rate for {enemy_id}")
        if config["tiempo_pensar_disparo"] not in SHOT_THINK_DELAYS:
            raise ValueError(f"Invalid shot thinking speed for {enemy_id}")
        if config["nivel_inteligencia"] not in {"medium", "medium_low", "tactical"}:
            raise ValueError(f"Invalid intelligence for {enemy_id}")
        if config["calculo_rebote"] not in {"accurate", "imperfect"}:
            raise ValueError(f"Invalid ricochet calculation for {enemy_id}")
        if config["evita_autodestruccion"].lower() not in {"true", "false"}:
            raise ValueError(f"Invalid self-preservation value for {enemy_id}")
        if int(config["maximo_balas"]) < 0 or int(config["rebotes_bala"]) < 0:
            raise ValueError(f"Invalid bullet limits for {enemy_id}")
        if int(config["maximo_minas"]) < 0:
            raise ValueError(f"Invalid mine limit for {enemy_id}")
        if not 0.0 <= float(config["probabilidad_acierto_rebote"]) <= 1.0:
            raise ValueError(f"Invalid ricochet success rate for {enemy_id}")
    return catalog
