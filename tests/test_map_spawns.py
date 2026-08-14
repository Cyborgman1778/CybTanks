from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cybtanks import levels
from cybtanks.config import _load_map


MAP_ROWS = """\
11111
10001
10001
10001
11111
"""


class MapSpawnMetadataTests(unittest.TestCase):
    def load_definition(self, content: str):
        with tempfile.TemporaryDirectory() as directory:
            map_file = Path(directory) / "map.txt"
            map_file.write_text(content, encoding="utf-8")
            return _load_map(map_file)

    def test_custom_player_and_tank_types_are_loaded_from_comments(self) -> None:
        definition = self.load_definition(
            "# player_spawn = 1,1\n"
            "# enemy_spawn = pink,3,3\n"
            "# enemy_spawn = yellow,2,2\n"
            + MAP_ROWS
        )

        self.assertEqual(definition.player_spawn, (1, 1))
        self.assertEqual(
            definition.enemy_layout,
            (("pink", (3, 3)), ("yellow", (2, 2))),
        )

    def test_map_without_spawn_metadata_keeps_legacy_mode(self) -> None:
        definition = self.load_definition(MAP_ROWS)

        self.assertIsNone(definition.player_spawn)
        self.assertIsNone(definition.enemy_layout)

    def test_custom_metadata_requires_exactly_one_player(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing player_spawn"):
            self.load_definition("# enemy_spawn = pink,3,3\n" + MAP_ROWS)
        with self.assertRaisesRegex(ValueError, "Duplicate player spawn"):
            self.load_definition(
                "# player_spawn = 1,1\n# player_spawn = 2,2\n" + MAP_ROWS
            )

    def test_spawns_must_be_unique_known_types_on_floor(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid enemy_spawn metadata"):
            self.load_definition(
                "# player_spawn = 1,1\n# enemy_spawn = unknown,2,2\n" + MAP_ROWS
            )
        with self.assertRaisesRegex(ValueError, "Duplicate tank spawn"):
            self.load_definition(
                "# player_spawn = 1,1\n# enemy_spawn = pink,1,1\n" + MAP_ROWS
            )
        with self.assertRaisesRegex(ValueError, "Invalid tank spawn"):
            self.load_definition(
                "# player_spawn = 0,0\n# enemy_spawn = pink,2,2\n" + MAP_ROWS
            )

    def test_custom_maps_can_define_more_than_twelve_enemies(self) -> None:
        enemy_lines = "".join(
            f"# enemy_spawn = pink,{index % 5},{index // 5}\n"
            for index in range(1, 14)
        )
        definition = self.load_definition(
            "# player_spawn = 0,0\n" + enemy_lines + ("00000\n" * 5)
        )

        self.assertEqual(len(definition.enemy_layout or ()), 13)

    def test_level_uses_custom_player_position_and_exact_enemy_types(self) -> None:
        custom_enemies = (("pink", (3, 3)), ("yellow", (2, 2)))
        with (
            patch.object(levels, "MAP_PLAYER_SPAWNS", ((3, 1),)),
            patch.object(levels, "MAP_ENEMY_LAYOUTS", (custom_enemies,)),
            patch.object(levels, "MAP_LAYOUTS", (((0,),),)),
        ):
            self.assertEqual(levels.player_spawn(1), (3, 1))
            self.assertEqual(levels.enemy_layout(1), list(custom_enemies))

if __name__ == "__main__":
    unittest.main()
