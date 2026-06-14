from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.db_builder import compile_definition_to_bots, create_rocketbot_db, export_rocketbot_db


def dsl_definition(actions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "bots": [
            {
                "name": "main",
                "project": {
                    "project": {
                        "commands": [{"type": "module", "name": "HU01"}],
                        "modules": [{"name": "HU01", "commands": actions}],
                        "vars": [],
                    }
                },
            }
        ]
    }


class DBBuilderTests(unittest.TestCase):
    def test_partial_profile_keeps_defaults(self) -> None:
        bots = compile_definition_to_bots(
            {
                "bots": [
                    {
                        "name": "main",
                        "project": {
                            "project": {
                                "profile": {"description": "Custom"},
                            }
                        },
                    }
                ]
            }
        )
        profile = bots[0].project["project"]["profile"]

        self.assertEqual(profile["name"], "main")
        self.assertEqual(profile["description"], "Custom")
        self.assertEqual(profile["log_destination"], "db_path")

    def test_compiles_official_native_logic(self) -> None:
        definition = dsl_definition(
            [
                {
                    "type": "for",
                    "iterable": "{vLocLstItems}",
                    "var": "vLocObjItem",
                    "body": [{"type": "break"}],
                },
                {
                    "type": "while",
                    "condition": "{vLocBooActivo}",
                    "body": [{"type": "break"}],
                },
                {
                    "type": "group",
                    "body": [
                        {
                            "type": "if",
                            "condition": "True",
                            "then": [],
                            "else": [],
                        }
                    ],
                },
                {"type": "try_catch", "try": [], "catch": []},
            ]
        )

        bots = compile_definition_to_bots(definition)
        commands = bots[1].project["project"]["commands"]

        self.assertEqual(commands[0]["father"], "for")
        self.assertEqual(
            json.loads(commands[0]["command"]),
            {"iterable": "{vLocLstItems}", "var": "vLocObjItem"},
        )
        self.assertEqual(commands[0]["children"][0]["father"], "break")
        self.assertEqual(commands[1]["father"], "evaluatewhile")
        self.assertEqual(commands[2]["father"], "group")
        self.assertEqual(commands[3]["father"], "trycatch")

    def test_rejects_non_official_continue_action(self) -> None:
        with self.assertRaisesRegex(ValueError, "continue"):
            compile_definition_to_bots(dsl_definition([{"type": "continue"}]))

    def test_o365_send_email_uses_package_parameter_names(self) -> None:
        bots = compile_definition_to_bots(
            dsl_definition(
                [
                    {
                        "type": "o365_send_email",
                        "to": "user@example.com",
                        "subject": "Test",
                        "body": "Body",
                        "cc": "copy@example.com",
                        "bcc": "hidden@example.com",
                    }
                ]
            )
        )
        payload = json.loads(
            bots[1].project["project"]["commands"][0]["command"]
        )

        self.assertEqual(payload["body"], "Body")
        self.assertEqual(payload["cc"], "copy@example.com")
        self.assertEqual(payload["bcc"], "hidden@example.com")
        self.assertNotIn("body_", payload)

    def test_failed_overwrite_preserves_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "robot.db"
            original = b"existing-data"
            destination.write_bytes(original)

            with self.assertRaises(ValueError):
                create_rocketbot_db(
                    str(destination),
                    dsl_definition([{"type": "unknown"}]),
                    overwrite=True,
                )

            self.assertEqual(destination.read_bytes(), original)

    def test_create_and_export_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "robot.db"
            result = create_rocketbot_db(
                str(destination),
                dsl_definition([{"type": "set_variable", "variable": "vLocStrX", "value": "ok"}]),
            )
            exported = export_rocketbot_db(str(destination))

            self.assertEqual(result["bots_created"], 2)
            self.assertEqual(exported["bots_count"], 2)
            self.assertEqual(exported["bots"][1]["name"], "HU01")


if __name__ == "__main__":
    unittest.main()
