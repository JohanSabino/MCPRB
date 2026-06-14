from __future__ import annotations

import json
from typing import Any, Iterator

from core.db_builder import BotDefinition, compile_definition_to_bots
from core.module_catalog import scan_rocketbot_modules


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold()


def _is_required(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _normalize(value) in {"1", "true", "yes", "required"}


def _walk_commands(commands: Any) -> Iterator[dict[str, Any]]:
    if not isinstance(commands, list):
        return
    for command in commands:
        if not isinstance(command, dict):
            continue
        yield command
        yield from _walk_commands(command.get("children"))
        yield from _walk_commands(command.get("else"))


def _module_commands(bots: list[BotDefinition]) -> Iterator[tuple[str, dict[str, Any]]]:
    for bot in bots:
        project = bot.project.get("project", {})
        for command in _walk_commands(project.get("commands", [])):
            if _normalize(command.get("father")) == "module":
                yield bot.name, command


def validate_rocketbot_modules(
    definition_json: str | dict[str, Any] | list[Any],
    modules_dir: str,
) -> dict[str, Any]:
    bots = compile_definition_to_bots(definition_json)
    module_commands = list(_module_commands(bots))
    if not module_commands:
        return {
            "valid": True,
            "modules_checked": 0,
            "commands": [],
            "errors": [],
            "warnings": [],
        }

    catalog = scan_rocketbot_modules(modules_dir)
    command_index: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for package in catalog["modules"]:
        package_name = _normalize(package.get("name"))
        for command in package.get("commands", []):
            command_name = _normalize(command.get("module"))
            aliases = {package_name, _normalize(command.get("module_name"))}
            for alias in aliases - {""}:
                command_index.setdefault((alias, command_name), []).append(command)

    errors: list[str] = []
    warnings: list[str] = []
    checked: list[dict[str, str]] = []

    for bot_name, command in module_commands:
        raw_payload = command.get("command", "")
        try:
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
        except json.JSONDecodeError:
            errors.append(f"{bot_name}: comando de módulo con JSON inválido")
            continue

        if not isinstance(payload, dict):
            errors.append(f"{bot_name}: comando de módulo sin objeto JSON")
            continue

        module_name = str(payload.get("module_name", "")).strip()
        module_command = str(payload.get("module", command.get("module", ""))).strip()
        if not module_name or not module_command:
            errors.append(f"{bot_name}: módulo sin module_name o module")
            continue

        checked.append(
            {
                "bot": bot_name,
                "module_name": module_name,
                "module": module_command,
            }
        )
        candidates = command_index.get(
            (_normalize(module_name), _normalize(module_command)),
            [],
        )
        if not candidates:
            errors.append(
                f"{bot_name}: no existe {module_name}.{module_command} en el catálogo"
            )
            continue

        known_fields: set[str] = {"module_name", "module"}
        required_fields: set[str] = set()
        for candidate in candidates:
            for field in candidate.get("inputs", []):
                field_id = str(field.get("id", "")).strip()
                if not field_id:
                    continue
                known_fields.add(field_id)
                if _is_required(field.get("required")):
                    required_fields.add(field_id)

        missing = sorted(
            field
            for field in required_fields
            if field not in payload or payload[field] is None or payload[field] == ""
        )
        if missing:
            errors.append(
                f"{bot_name}: faltan parámetros requeridos en "
                f"{module_name}.{module_command}: {', '.join(missing)}"
            )

        unknown = sorted(set(payload) - known_fields)
        if unknown:
            warnings.append(
                f"{bot_name}: parámetros no publicados en "
                f"{module_name}.{module_command}: {', '.join(unknown)}"
            )

    if catalog["errors"]:
        warnings.append(
            f"El catálogo omitió {catalog['errors_count']} package.json inválido(s)"
        )

    return {
        "valid": not errors,
        "modules_checked": len(checked),
        "commands": checked,
        "errors": errors,
        "warnings": warnings,
    }
