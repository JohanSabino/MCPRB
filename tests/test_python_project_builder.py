import tempfile
import unittest
import zipfile
import sqlite3
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
                str(db_path), str(root / "out"), plan["plan_id"], approve=True
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
                str(db_path), str(root / "out"), plan["plan_id"], approve=True
            )

            normalization = result["normalization"]
            self.assertTrue(normalization["created_copy"])
            self.assertTrue(Path(normalization["normalized_db"]).exists())
            self.assertEqual(result["approval_plan_id"], plan["plan_id"])


if __name__ == "__main__":
    unittest.main()
