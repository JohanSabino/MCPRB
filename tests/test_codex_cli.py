from __future__ import annotations

import unittest

from core.codex_cli import build_add_command, configure_codex


class CodexCliTest(unittest.TestCase):
    def test_build_add_command_uses_main_repository(self) -> None:
        command = build_add_command()

        self.assertEqual(command[:6], ["codex.cmd", "mcp", "add", "rocketbot", "--", "uvx"])
        self.assertEqual(command[-2:], ["git+https://github.com/JohanSabino/MCPRB.git", "mcp-rocketbot"])

    def test_update_removes_and_readds_with_refresh(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def runner(command: list[str], **kwargs: object) -> object:
            calls.append((command, kwargs))
            return object()

        configure_codex("update", runner=runner)

        self.assertEqual(calls[0][0][:4], ["codex.cmd", "mcp", "remove", "rocketbot"])
        self.assertIn("--refresh", calls[1][0])
        self.assertTrue(calls[1][1]["check"])

    def test_uninstall_removes_server_and_package_cache(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def runner(command: list[str], **kwargs: object) -> object:
            calls.append((command, kwargs))
            return object()

        configure_codex("uninstall", runner=runner, clean_cache=True)

        self.assertEqual(calls[0][0][:4], ["codex.cmd", "mcp", "remove", "rocketbot"])
        self.assertEqual(calls[1][0], ["uv", "cache", "clean", "mcp-rocketbot"])


if __name__ == "__main__":
    unittest.main()
