from __future__ import annotations

import csv

from .ai_config import load_ai_settings
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
        reader = csv.DictReader(data_file)
        required_columns = {
            "tipo_id",
            "color_hex",
            "velocidad_movimiento",
            "velocidad_bala",
            "maximo_balas",
            "rebotes_bala",
            "maximo_minas",
            "cadencia_disparo",
            "tiempo_pensar_disparo",
            "nivel_inteligencia",
            "calculo_rebote",
            "probabilidad_acierto_rebote",
            "evita_autodestruccion",
        }
        if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
            raise ValueError(f"Missing columns in {ENEMY_DATA_FILE}")
        catalog = {}
        for row in reader:
            enemy_id = (row.get("tipo_id") or "").strip()
            if not enemy_id:
                raise ValueError(f"Empty enemy ID in {ENEMY_DATA_FILE}")
            if enemy_id in catalog:
                raise ValueError(f"Duplicate enemy definition {enemy_id!r} in {ENEMY_DATA_FILE}")
            catalog[enemy_id] = row
    required = {"light_gray", "dark_gray", "yellow", "dark_green", "pink"}
    if not required.issubset(catalog):
        raise ValueError(f"Missing enemy definitions in {ENEMY_DATA_FILE}")
    ai_settings = load_ai_settings()
    limits = ai_settings.global_config
    for enemy_id, config in catalog.items():
        parse_hex_color(config["color_hex"])
        if config["velocidad_movimiento"] not in MOVEMENT_SPEEDS:
            raise ValueError(f"Invalid movement speed for {enemy_id}")
        if config["velocidad_bala"] not in BULLET_SPEEDS:
            raise ValueError(f"Invalid bullet speed for {enemy_id}")
        if config["cadencia_disparo"] not in FIRE_RATE_DELAYS:
            raise ValueError(f"Invalid fire rate for {enemy_id}")
        if config["tiempo_pensar_disparo"] not in SHOT_THINK_DELAYS:
            raise ValueError(f"Invalid shot thinking speed for {enemy_id}")
        if config["nivel_inteligencia"] not in ai_settings.profiles:
            raise ValueError(f"Invalid intelligence for {enemy_id}")
        if config["calculo_rebote"] not in {"accurate", "imperfect"}:
            raise ValueError(f"Invalid ricochet calculation for {enemy_id}")
        if config["evita_autodestruccion"].lower() not in {"true", "false"}:
            raise ValueError(f"Invalid self-preservation value for {enemy_id}")
        max_bullets = int(config["maximo_balas"])
        max_bounces = int(config["rebotes_bala"])
        max_mines = int(config["maximo_minas"])
        if not 0 <= max_bullets <= limits.max_enemy_bullets:
            raise ValueError(f"Invalid bullet limits for {enemy_id}")
        if not 0 <= max_bounces <= limits.max_enemy_bounces:
            raise ValueError(f"Invalid ricochet limit for {enemy_id}")
        if not 0 <= max_mines <= limits.max_enemy_mines:
            raise ValueError(f"Invalid mine limit for {enemy_id}")
        if not 0.0 <= float(config["probabilidad_acierto_rebote"]) <= 1.0:
            raise ValueError(f"Invalid ricochet success rate for {enemy_id}")
    return catalog
