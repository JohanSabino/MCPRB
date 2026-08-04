"""One-line install, update, and uninstall helpers for Codex CLI."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable, Sequence

DEFAULT_REPOSITORY = "https://github.com/JohanSabino/MCPRB.git"
DEFAULT_SERVER_NAME = "rocketbot"
PACKAGE_NAME = "mcp-rocketbot"
Runner = Callable[..., subprocess.CompletedProcess[object]]


def _codex_command() -> str:
    return "codex.cmd" if os.name == "nt" else "codex"


def _git_source(repository: str) -> str:
    return repository if repository.startswith("git+") else f"git+{repository}"


def build_add_command(
    server_name: str = DEFAULT_SERVER_NAME,
    repository: str = DEFAULT_REPOSITORY,
    *,
    refresh: bool = False,
) -> list[str]:
    command = [_codex_command(), "mcp", "add", server_name, "--", "uvx"]
    if refresh:
        command.append("--refresh")
    command.extend(["--from", _git_source(repository), PACKAGE_NAME])
    return command


def configure_codex(
    action: str,
    server_name: str = DEFAULT_SERVER_NAME,
    repository: str = DEFAULT_REPOSITORY,
    *,
    clean_cache: bool = False,
    runner: Runner = subprocess.run,
) -> int:
    if action in {"update", "uninstall"}:
        runner(
            [_codex_command(), "mcp", "remove", server_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if action in {"install", "update"}:
        runner(build_add_command(server_name, repository, refresh=action == "update"), check=True)

    if action == "uninstall" and clean_cache:
        runner(["uv", "cache", "clean", PACKAGE_NAME], check=True)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PACKAGE_NAME,
        description="Instala, actualiza o desinstala MCP Rocketbot en Codex CLI.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "update"):
        subparser = subparsers.add_parser(action, help=f"{action.capitalize()} el servidor rocketbot")
        subparser.add_argument("--name", default=DEFAULT_SERVER_NAME, help="Nombre del servidor MCP")
        subparser.add_argument("--repository", default=DEFAULT_REPOSITORY, help="URL Git del repositorio")

    uninstall = subparsers.add_parser("uninstall", help="Quita rocketbot de Codex CLI")
    uninstall.add_argument("--name", default=DEFAULT_SERVER_NAME, help="Nombre del servidor MCP")
    uninstall.add_argument(
        "--keep-cache",
        action="store_true",
        help="Conserva la caché local de uvx",
    )
    return parser


def run_codex_cli(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return configure_codex(
        args.action,
        args.name,
        getattr(args, "repository", DEFAULT_REPOSITORY),
        clean_cache=args.action == "uninstall" and not args.keep_cache,
    )
