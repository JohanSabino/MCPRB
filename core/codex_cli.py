"""One-line install, update, and uninstall helpers for Codex CLI."""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Callable, Sequence

DEFAULT_REPOSITORY = "https://github.com/JohanSabino/MCPRB/archive/refs/heads/main.zip"
DEFAULT_SERVER_NAME = "rocketbot"
PACKAGE_NAME = "mcp-rocketbot"
DEFAULT_ENVIRONMENT = (
    "ROCKETBOT_HOME=",
    "ROCKETBOT_PROJECTS_DIR=",
    "ROCKETBOT_LOGS_DIR=",
    "ROCKETBOT_MODULES_DIR=",
    "ROCKETBOT_VARIABLES_FILE=",
    "MCP_TRANSPORT=stdio",
    "MCP_HOST=127.0.0.1",
    "MCP_PORT=8000",
    "MCP_SSE_PATH=/sse",
    "MCP_STREAMABLE_HTTP_PATH=/mcp",
    "MCP_ENABLE_RESOURCES=false",
)
Runner = Callable[..., subprocess.CompletedProcess[object]]


def _codex_command() -> str:
    return "codex.cmd" if os.name == "nt" else "codex"


def _package_source(repository: str) -> str:
    if repository.startswith("git+") or repository.lower().endswith((".zip", ".tar.gz", ".tgz")):
        return repository
    return f"git+{repository}"


def build_add_command(
    server_name: str = DEFAULT_SERVER_NAME,
    repository: str = DEFAULT_REPOSITORY,
    *,
    refresh: bool = False,
) -> list[str]:
    command = [_codex_command(), "mcp", "add", server_name]
    for variable in DEFAULT_ENVIRONMENT:
        command.extend(["--env", variable])
    command.extend(["--", "uvx"])
    if refresh:
        command.append("--refresh")
    command.extend(["--from", _package_source(repository), PACKAGE_NAME])
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
