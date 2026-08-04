import tempfile
import unittest
import zipfile
import sqlite3
import runpy
import sys
import logging
from pathlib import Path

from core.db_builder import create_rocketbot_db
from core.python_project_builder import (
    generate_rocketbot_python_project,
    plan_rocketbot_python_project,
)


class PythonProjectBuilderTest(unittest.TestCase):
    def test_plan_requires_approval_and_generates_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "source.db"
            create_rocketbot_db(
                str(db_path),
                {
                    "bots": [
                        {"name": "main", "project": {"project": {"commands": []}}},
                        {"name": "HU1_Entrada", "project": {"project": {"commands": []}}},
                    ]
                },
            )
            plan = plan_rocketbot_python_project(str(db_path), str(root / "out"))
            self.assertEqual(plan["status"], "awaiting_approval")
            self.assertIn(
                "HU/HU01_Flujo.py",
                [entry["path"] for entry in plan["proposed_structure"]],
            )
            with self.assertRaises(PermissionError):
                generate_rocketbot_python_project(str(db_path), str(root / "out"), plan["plan_id"])

            result = generate_rocketbot_python_project(
                str(db_path), str(root / "out"), plan["plan_id"], approve=True, normalize_db=True
            )
            self.assertGreater(result["files_created"], 0)
            self.assertTrue(zipfile.is_zipfile(root / "out" / "config" / "config.xlsx"))

    def test_generation_normalizes_blocked_data_type_after_approval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "source.db"
            create_rocketbot_db(
                str(db_path),
                {"bots": [{"name": "main", "project": {"project": {"commands": []}}}]},
            )
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("UPDATE bots SET data_type = ''")
                connection.commit()
            finally:
                connection.close()

            plan = plan_rocketbot_python_project(str(db_path), str(root / "out"))
            self.assertTrue(plan["database_status"]["requires_normalization"])
            result = generate_rocketbot_python_project(
                str(db_path), str(root / "out"), plan["plan_id"], approve=True, normalize_db=True
            )

            normalization = result["normalization"]
            self.assertTrue(normalization["created_copy"])
            self.assertTrue(Path(normalization["normalized_db"]).exists())
            self.assertEqual(result["approval_plan_id"], plan["plan_id"])

    def test_executable_mode_translates_control_flow_without_stubs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "source.db"
            create_rocketbot_db(
                str(db_path),
                {
                    "bots": [
                        {
                            "name": "main",
                            "project": {
                                "project": {
                                    "commands": [{"type": "module", "name": "HU01"}],
                                    "modules": [{
                                        "name": "HU01",
                                        "commands": [
                                            {"type": "set_variable", "variable": "vLocStrX", "value": "ok"},
                                            {"type": "for", "iterable": "[]", "var": "item", "body": [{"type": "break"}]},
                                        ],
                                    }],
                                }
                            },
                        }
                    ]
                },
            )
            plan = plan_rocketbot_python_project(
                str(db_path), str(root / "out"), mode="executable", strict=True
            )
            self.assertEqual(plan["status"], "awaiting_approval")
            self.assertEqual(plan["translation"]["unsupported"], [])
            result = generate_rocketbot_python_project(
                str(db_path),
                str(root / "out"),
                plan["plan_id"],
                approve=True,
                mode="executable",
                strict=True,
            )
            self.assertEqual(result["validation"]["compile_errors"], [])
            self.assertTrue((root / "out" / "adapters" / "http.py").exists())
            self.assertNotIn("NotImplementedError", "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "out").rglob("*.py")
            ))

    def test_strict_mode_reports_unknown_module_before_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "source.db"
            create_rocketbot_db(
                str(db_path),
                {
                    "bots": [{
                        "name": "main",
                        "project": {
                            "project": {
                                "commands": [{"type": "module", "name": "HU01"}],
                                "modules": [{
                                    "name": "HU01",
                                    "commands": [{
                                        "type": "module",
                                        "module_name": "Custom",
                                        "module": "unknownCommand",
                                    }],
                                }],
                            }
                        },
                    }]
                },
            )
            plan = plan_rocketbot_python_project(
                str(db_path), str(root / "out"), mode="executable", strict=True
            )
            self.assertEqual(plan["status"], "blocked_unsupported")
            self.assertIn("module:unknowncommand", plan["translation"]["unsupported"])
            detail = plan["translation"]["unsupported_details"][0]
            self.assertEqual(detail["bot"], "HU01")
            self.assertEqual(detail["line"], 1)

    def test_executable_fixture_runs_scripts_and_reports_unsupported_commands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "fixture_script.py"
            script.write_text('SetVar("vLocStrX", "from_script")\n', encoding="utf-8")
            db_path = root / "source.db"
            create_rocketbot_db(
                str(db_path),
                {
                    "bots": [{
                        "name": "main",
                        "project": {
                            "project": {
                                "commands": [{"type": "module", "name": "HU01"}],
                                "modules": [{
                                    "name": "HU01",
                                    "commands": [
                                        {"type": "exec_python", "path": str(script)},
                                        {"type": "module", "module_name": "Custom", "module": "unknown"},
                                    ],
                                }],
                            }
                        },
                    }]
                },
            )
            plan = plan_rocketbot_python_project(
                str(db_path), str(root / "out"), mode="executable", strict=False
            )
            result = generate_rocketbot_python_project(
                str(db_path), str(root / "out"), plan["plan_id"],
                approve=True, mode="executable", strict=False,
            )
            main_source = (root / "out" / "main.py").read_text(encoding="utf-8")
            for helper in ("build_context", "run_bot", "resolve", "evaluate", "report_unsupported"):
                self.assertIn(helper, main_source)
            sys.path.insert(0, str(root / "out"))
            try:
                namespace = runpy.run_path(str(root / "out" / "main.py"))
                context = namespace["main"]()
            finally:
                sys.path.remove(str(root / "out"))
            logging.shutdown()
            self.assertEqual(context["vLocStrX"], "from_script")
            self.assertEqual(context["unsupported_commands"][0]["command"], "module:unknown")
            self.assertEqual(result["validation"]["not_implemented_errors"], [])


if __name__ == "__main__":
    unittest.main()
