from __future__ import annotations

import os
from pathlib import Path


def _existing_dir(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _existing_file(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def rocketbot_home() -> Path:
    env_value = os.getenv("ROCKETBOT_HOME", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()

    home = Path.home()
    candidates = [
        home / "Rocketbot",
        home / "Documents" / "Rocketbot",
        home / "AppData" / "Local" / "Rocketbot",
        home / "AppData" / "Roaming" / "Rocketbot",
    ]
    return (_existing_dir(candidates) or (home / "Rocketbot")).resolve()


def projects_dir() -> Path:
    env_value = os.getenv("ROCKETBOT_PROJECTS_DIR", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()

    root = rocketbot_home()
    candidates = [
        root / "projects",
        root / "Projects",
        root / "modules",
        root,
    ]
    return (_existing_dir(candidates) or (root / "projects")).resolve()


def logs_dir() -> Path:
    env_value = os.getenv("ROCKETBOT_LOGS_DIR", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()

    root = rocketbot_home()
    candidates = [
        root / "logs",
        root / "Logs",
        root / "log",
    ]
    return (_existing_dir(candidates) or (root / "logs")).resolve()


def modules_dir() -> Path:
    env_value = os.getenv("ROCKETBOT_MODULES_DIR", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()

    home = Path.home()
    root = rocketbot_home()
    candidates = [
        root / "modules",
        root / "Modules",
        root / "Rocketbot" / "modules",
        home / "Desktop" / "Rocketbot" / "Rocketbot" / "modules",
        home / "Desktop" / "Rocketbot" / "modules",
        home / "Documents" / "Rocketbot" / "Rocketbot" / "modules",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Rocketbot" / "modules",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Rocketbot" / "modules",
    ]
    return (_existing_dir(candidates) or (root / "modules")).resolve()


def variables_file() -> Path:
    env_value = os.getenv("ROCKETBOT_VARIABLES_FILE", "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()

    root = rocketbot_home()
    candidates = [
        root / "variables.json",
        root / "Variables.json",
        root / "variables.ini",
        root / "variables.env",
        root / "variables.txt",
    ]
    return (_existing_file(candidates) or (root / "variables.json")).resolve()


def describe_paths() -> dict[str, str]:
    return {
        "rocketbot_home": str(rocketbot_home()),
        "projects_dir": str(projects_dir()),
        "logs_dir": str(logs_dir()),
        "modules_dir": str(modules_dir()),
        "variables_file": str(variables_file()),
    }


def describe_paths_status() -> dict[str, dict[str, object]]:
    definitions = {
        "rocketbot_home": (rocketbot_home(), "directory", "ROCKETBOT_HOME"),
        "projects_dir": (projects_dir(), "directory", "ROCKETBOT_PROJECTS_DIR"),
        "logs_dir": (logs_dir(), "directory", "ROCKETBOT_LOGS_DIR"),
        "modules_dir": (modules_dir(), "directory", "ROCKETBOT_MODULES_DIR"),
        "variables_file": (variables_file(), "file", "ROCKETBOT_VARIABLES_FILE"),
    }
    return {
        name: {
            "path": str(path),
            "exists": path.exists(),
            "kind": kind,
            "configured": bool(os.getenv(environment_name, "").strip()),
            "environment": environment_name,
        }
        for name, (path, kind, environment_name) in definitions.items()
    }
