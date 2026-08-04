"""Small helpers for registering this MCP in Codex CLI."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable, Sequence

DEFAULT_REPOSITORY = "https://github.com/JohanSabino/MCPRB.git"
DEFAULT_SERVER_NAME = "rocketbot"
PACKAGE_NAME = "mcp-rocketbot"
Runner = Callable[..., subprocess.CompletedProcess[object]]


def _codex_executable() -> str:
    return "codex.cmd" if os.name == "nt" else "codex"


def _git_source(repository: str) -> str:
    return repository if repository.startswith("git+") else f"git+{repository}"


def build_add_command(
    server_name: str = DEFAULT_SERVER_NAME,
    repository: str = DEFAULT_REPOSITORY,
    *,
    refresh: bool = False,
) -> list[str]:
    command = [_codex_executable(), "mcp", "add", server_name, "--", "uvx"]
    if refresh:
        command.append("--refresh")
    command.extend(["--from", _git_source(repository), PACKAGE_NAME])
    return command


def configure_codex(
    action: str,
    server_name: str = DEFAULT_SERVER_NAME,
    repository: str = DEFAULT_REPOSITORY,
    *,
    runner: Runner = subprocess.run,
) -> int:
    if action == "update":
        runner(
            [_codex_executable(), "mcp", "remove", server_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    runner(build_add_command(server_name, repository, refresh=action == "update"), check=True)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PACKAGE_NAME,
        description="Instala o actualiza MCP Rocketbot en Codex CLI.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "update"):
        subparser = subparsers.add_parser(action, help=f"{action.capitalize()} el servidor rocketbot")
        subparser.add_argument("--name", default=DEFAULT_SERVER_NAME, help="Nombre del servidor MCP")
        subparser.add_argument("--repository", default=DEFAULT_REPOSITORY, help="URL Git del repositorio")
    return parser


def run_codex_cli(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return configure_codex(args.action, args.name, args.repository)
