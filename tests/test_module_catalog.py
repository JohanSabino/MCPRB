from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.module_catalog import scan_rocketbot_modules, search_rocketbot_modules
from core.module_validation import validate_rocketbot_modules


def write_catalog(root: Path) -> None:
    valid = root / "Files"
    valid.mkdir()
    (valid / "package.json").write_text(
        json.dumps(
            {
                "name": "Files",
                "children": [
                    {
                        "module": "exists",
                        "module_name": "Files",
                        "es": {"title": "Existe archivo", "description": "Valida una ruta"},
                        "form": {
                            "inputs": [
                                {"id": "path", "type": "text", "required": True},
                                {"id": "var_", "type": "text", "required": False},
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    invalid = root / "Broken"
    invalid.mkdir()
    (invalid / "package.json").write_text("{invalid", encoding="utf-8")


def module_definition(params: dict[str, object], module: str = "exists") -> dict[str, object]:
    return {
        "bots": [
            {
                "name": "main",
                "project": {
                    "project": {
                        "commands": [{"type": "module", "name": "HU01"}],
                        "modules": [
                            {
                                "name": "HU01",
                                "commands": [
                                    {
                                        "type": "module",
                                        "module_name": "Files",
                                        "module": module,
                                        "params": params,
                                    }
                                ],
                            }
                        ],
                        "vars": [],
                    }
                },
            }
        ]
    }


class ModuleCatalogTests(unittest.TestCase):
    def test_scan_continues_after_invalid_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_catalog(root)

            catalog = scan_rocketbot_modules(str(root))

            self.assertEqual(catalog["modules_count"], 1)
            self.assertEqual(catalog["errors_count"], 1)
            self.assertEqual(catalog["native_logic"], ["if", "for", "while", "try_catch", "break", "group"])

    def test_search_returns_compact_matching_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_catalog(root)

            result = search_rocketbot_modules(str(root), "archivo")

            self.assertEqual(result["matches_count"], 1)
            self.assertEqual(result["matches"][0]["module"], "exists")

    def test_validation_checks_command_and_required_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_catalog(root)

            valid = validate_rocketbot_modules(
                module_definition({"path": "C:/input.txt", "var_": "vLocBooExiste"}),
                str(root),
            )
            missing = validate_rocketbot_modules(module_definition({}), str(root))
            unknown = validate_rocketbot_modules(
                module_definition({"path": "C:/input.txt"}, module="missing"),
                str(root),
            )

            self.assertTrue(valid["valid"])
            self.assertFalse(missing["valid"])
            self.assertIn("path", missing["errors"][0])
            self.assertFalse(unknown["valid"])
            self.assertIn("Files.missing", unknown["errors"][0])


if __name__ == "__main__":
    unittest.main()
