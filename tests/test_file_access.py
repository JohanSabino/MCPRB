from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.logs import read_log_file_tail, read_log_tail
from core.variables import load_variables
from mcp_server import _project_root


class FileAccessTests(unittest.TestCase):
    def test_log_name_cannot_escape_logs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            logs = root / "logs"
            logs.mkdir()
            (root / "outside.log").write_text("secret", encoding="utf-8")

            with self.assertRaises(ValueError):
                read_log_tail(logs, "../outside.log")

    def test_project_name_cannot_escape_projects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            projects = root / "projects"
            projects.mkdir()
            (root / "outside").mkdir()

            with patch.dict(
                "os.environ",
                {"ROCKETBOT_PROJECTS_DIR": str(projects)},
            ):
                with self.assertRaises(ValueError):
                    _project_root("../outside")

    def test_reads_true_tail_of_large_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "large.log"
            log_path.write_text(
                "\n".join(f"{index:05d}-{'x' * 20}" for index in range(20_000)),
                encoding="utf-8",
            )

            self.assertEqual(
                read_log_file_tail(log_path, lines=3).splitlines(),
                [
                    "19997-xxxxxxxxxxxxxxxxxxxx",
                    "19998-xxxxxxxxxxxxxxxxxxxx",
                    "19999-xxxxxxxxxxxxxxxxxxxx",
                ],
            )

    def test_missing_variables_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                load_variables(Path(temp_dir) / "missing.json")


if __name__ == "__main__":
    unittest.main()
