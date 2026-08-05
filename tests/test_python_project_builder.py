import tempfile
import unittest
import zipfile
import sqlite3
import runpy
import sys
import logging
import json
from pathlib import Path

from core.db_builder import create_rocketbot_db
from core.python_project_builder import (
    generate_rocketbot_python_project,
    plan_rocketbot_python_project,
)


def _reset_generated_runtime():
    logging.shutdown()
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    for name in list(sys.modules):
        if name == "HU" or name.startswith("HU.") or name == "adapters" or name.startswith("adapters."):
            sys.modules.pop(name, None)


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
                _reset_generated_runtime()
            self.assertEqual(context["vLocStrX"], "from_script")
            self.assertEqual(context["unsupported_commands"][0]["command"], "module:unknown")
            self.assertEqual(result["validation"]["not_implemented_errors"], [])

    def test_executable_translates_limpiar_variables_robot(self):
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
                                    "commands": [
                                        {"type": "set_variable", "variable": "vFoo", "value": "value"},
                                        {
                                            "type": "module",
                                            "module_name": "2NV",
                                            "module": "Logs",
                                            "option_": "Informativo",
                                            "input_2": "Procesando {vFoo}",
                                            "input_3": "Prueba",
                                            "input_4": "HU01",
                                        },
                                        {
                                            "type": "module",
                                            "module_name": "2NV",
                                            "module": "LimpiarVariablesRobot",
                                            "input_ListVariables": "vFoo,vBar",
                                        },
                                        {
                                            "type": "module",
                                            "module_name": "2NV",
                                            "module": "ValidarRutas",
                                            "check_ArchivosRecibidos": True,
                                            "check_Trazabilidad": True,
                                            "check_Formatos": True,
                                        },
                                        {
                                            "type": "module",
                                            "module_name": "2NV",
                                            "module": "CerrarAplicaciones",
                                            "input_ListAplicaciones": "EXCEL.EXE,notepad.exe",
                                        },
                                    ],
                                }],
                            }
                        },
                    }]
                },
            )

            output = root / "out"
            plan = plan_rocketbot_python_project(
                str(db_path), str(output), mode="executable", strict=True
            )
            self.assertEqual(plan["translation"]["unsupported"], [])
            result = generate_rocketbot_python_project(
                str(db_path), str(output), plan["plan_id"],
                approve=True, mode="executable", strict=True,
            )

            sys.path.insert(0, str(output))
            try:
                namespace = runpy.run_path(str(output / "main.py"))
                context = namespace["main"]()
            finally:
                sys.path.remove(str(output))
                _reset_generated_runtime()
            self.assertEqual(context["vFoo"], "")
            self.assertEqual(context["vBar"], "")
            self.assertEqual(context["rocketbot_logs"][0]["message"], "Procesando value")
            functional_log = output / "Logs" / "rocketbot.log.jsonl"
            self.assertTrue(functional_log.is_file())
            self.assertEqual(json.loads(functional_log.read_text().splitlines()[0])["title"], "Prueba")
            self.assertTrue((output / "Inputs").is_dir())
            self.assertTrue((output / "Logs").is_dir())
            self.assertTrue((output / "Plantillas").is_dir())
            self.assertEqual(
                context["simulated_actions"][0],
                {
                    "action": "close_applications",
                    "applications": ["EXCEL.EXE", "notepad.exe"],
                    "simulated": True,
                },
            )
            self.assertEqual(result["validation"]["compile_errors"], [])

    def test_executable_cargar_config_padre_loads_config_before_script(self):
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
                                    "commands": [
                                        {
                                            "type": "module",
                                            "module_name": "CargarConfigPadre",
                                            "module": "2NV",
                                        },
                                        {
                                            "type": "exec_python",
                                            "path": "{vGblStrRutaPython}CargarVariables.py",
                                        },
                                        {
                                            "type": "exec_script_python",
                                            "script": (
                                                "Config=eval(GetVar('vGblDicConfig'))\n"
                                                "SetVar('vGblStrAsuntoCorreo', Config['AsuntoInicio'])\n"
                                                "SetVar('vGblStrCuerpoCorreo', Config['CuerpoInicio'])\n"
                                            ),
                                        },
                                        {
                                            "type": "module",
                                            "module_name": "Custom",
                                            "module": "unknown",
                                        },
                                    ],
                                }],
                            }
                        },
                    }]
                },
            )

            output = root / "out"
            plan = plan_rocketbot_python_project(
                str(db_path), str(output), mode="executable", strict=False
            )
            self.assertNotIn("module:cargarconfigpadre", plan["translation"]["unsupported"])
            self.assertIn("AsuntoInicio", plan["config_keys"])
            self.assertIn("CuerpoInicio", plan["config_keys"])
            result = generate_rocketbot_python_project(
                str(db_path), str(output), plan["plan_id"],
                approve=True, mode="executable", strict=False,
            )

            config = json.loads((output / "config" / "config.json").read_text(encoding="utf-8"))
            self.assertTrue(config["AsuntoInicio"])
            self.assertTrue(config["CuerpoInicio"])
            generated_source = "\n".join(
                path.read_text(encoding="utf-8")
                for path in output.rglob("*.py")
            )
            self.assertNotIn("NotImplementedError", generated_source)
            self.assertEqual(result["validation"]["compile_errors"], [])

            sys.path.insert(0, str(output))
            try:
                namespace = runpy.run_path(str(output / "main.py"))
                context = namespace["main"]()
            finally:
                sys.path.remove(str(output))
                _reset_generated_runtime()
            self.assertIsInstance(context["vGblDicConfig"], dict)
            self.assertTrue(context["vGblDicConfig"])
            self.assertGreater(context["rocketbot_variables_loaded"], 0)
            self.assertEqual(context["RUTA_INPUTS"], "Inputs")
            self.assertEqual(context["vGblStrAsuntoCorreo"], config["AsuntoInicio"])
            self.assertEqual(context["vGblStrCuerpoCorreo"], config["CuerpoInicio"])
            self.assertEqual(context["unsupported_commands"][0]["command"], "module:unknown")

            config_path = output / "config" / "config.json"
            config_namespace = runpy.run_path(str(output / "HU" / "HU00_Config.py"))
            config_without_required_key = dict(config)
            config_without_required_key.pop("AsuntoInicio")
            config_path.write_text(
                json.dumps(config_without_required_key),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError,
                r"Falta configuración requerida 'AsuntoInicio' en .*config[\\/]config\.json",
            ):
                config_namespace["load_config"](config_namespace["build_context"]())

            config_path.unlink()
            with self.assertRaisesRegex(
                FileNotFoundError,
                r"Falta el archivo de configuración: .*config[\\/]config\.json",
            ):
                config_namespace["load_config"](config_namespace["build_context"]())
            _reset_generated_runtime()


if __name__ == "__main__":
    unittest.main()
