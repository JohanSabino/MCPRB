from __future__ import annotations

import json
from pathlib import Path
from typing import Any


FOOTER = "skill made by Johan Sabino  \nhttps://www.linkedin.com/in/johanandressabino/\n"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _normalize_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _pick_lang_block(item: dict[str, Any], lang: str) -> dict[str, Any]:
    block = item.get(lang)
    return block if isinstance(block, dict) else {}


def _extract_inputs(form: dict[str, Any]) -> list[dict[str, Any]]:
    inputs = form.get("inputs", [])
    if not isinstance(inputs, list):
        return []

    extracted: list[dict[str, Any]] = []
    for field in inputs:
        if not isinstance(field, dict):
            continue
        extracted.append(
            {
                "id": _normalize_text(field.get("id")),
                "type": _normalize_text(field.get("type")),
                "css": _normalize_text(field.get("css")),
                "title": field.get("title", {}),
                "description": field.get("description", {}),
                "placeholder": field.get("placeholder", {}),
                "help": field.get("help", {}),
            }
        )
    return extracted


def scan_rocketbot_modules(modules_dir: str) -> dict[str, Any]:
    base = Path(modules_dir).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"No existe directorio de módulos: {base}")

    modules: list[dict[str, Any]] = []

    for module_dir in sorted(path for path in base.iterdir() if path.is_dir()):
        package_path = module_dir / "package.json"
        if not package_path.exists():
            continue

        package = _read_json(package_path)
        children = package.get("children", [])
        if not isinstance(children, list):
            children = []

        commands: list[dict[str, Any]] = []
        for child in children:
            if not isinstance(child, dict):
                continue
            form = child.get("form", {})
            form = form if isinstance(form, dict) else {}
            commands.append(
                {
                    "module": _normalize_text(child.get("module")),
                    "module_name": _normalize_text(child.get("module_name")),
                    "father": _normalize_text(child.get("father")),
                    "group": _normalize_text(child.get("group")),
                    "visible": bool(child.get("visible", False)),
                    "options": child.get("options"),
                    "windows": bool(child.get("windows", False)),
                    "linux": bool(child.get("linux", False)),
                    "mac": bool(child.get("mac", False)),
                    "docker": bool(child.get("docker", False)),
                    "title": {
                        "es": _pick_lang_block(child, "es").get("title", ""),
                        "en": _pick_lang_block(child, "en").get("title", ""),
                        "pr": _pick_lang_block(child, "pr").get("title", ""),
                    },
                    "description": {
                        "es": _pick_lang_block(child, "es").get("description", ""),
                        "en": _pick_lang_block(child, "en").get("description", ""),
                        "pr": _pick_lang_block(child, "pr").get("description", ""),
                    },
                    "inputs": _extract_inputs(form),
                }
            )

        modules.append(
            {
                "name": _normalize_text(package.get("name")) or module_dir.name,
                "directory": str(module_dir),
                "version": _normalize_text(package.get("version")),
                "description": _normalize_text(package.get("description")),
                "title": package.get("title", {}),
                "windows": bool(package.get("windows", False)),
                "linux": bool(package.get("linux", False)),
                "mac": bool(package.get("mac", False)),
                "docker": bool(package.get("docker", False)),
                "dependencies": package.get("dependencies", {}),
                "commands_count": len(commands),
                "commands": commands,
            }
        )

    return {
        "modules_dir": str(base),
        "modules_count": len(modules),
        "modules": modules,
    }


def export_module_catalog_json(modules_dir: str, output_json_path: str | None = None) -> dict[str, Any]:
    catalog = scan_rocketbot_modules(modules_dir)
    if output_json_path:
        destination = Path(output_json_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        catalog["output_json_path"] = str(destination)
    return catalog


def export_module_catalog_obsidian(modules_dir: str, output_dir: str) -> dict[str, Any]:
    catalog = scan_rocketbot_modules(modules_dir)
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    written_files: list[str] = []
    note_names: dict[str, str] = {}

    for module in catalog["modules"]:
        note_names[module["name"]] = f"module-{module['name']}.md"

    index_lines = [
        "# Catalogo Modulos Rocketbot",
        "",
        f"- Modulos detectados: `{catalog['modules_count']}`",
        "",
        "## Modulos",
    ]
    for module in catalog["modules"]:
        index_lines.append(f"- [[{note_names[module['name']][:-3]}]]")
    index_lines.extend(["", FOOTER])

    index_path = destination / "index.md"
    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    written_files.append(str(index_path))

    diagrams_lines = [
        "# diagrams",
        "",
        "## Relacion Modulos",
        "```mermaid",
        "flowchart TD",
    ]
    for module in catalog["modules"]:
        node = module["name"].replace("-", "_").replace("+", "_").replace(" ", "_")
        diagrams_lines.append(f'    {node}["{module["name"]}"]')
        for command in module["commands"][:20]:
            cmd_node = f'{node}_{command["module"] or "cmd"}'.replace("-", "_").replace("+", "_")
            label = command["module"] or command["title"].get("es") or "cmd"
            diagrams_lines.append(f'    {cmd_node}["{label}"]')
            diagrams_lines.append(f"    {node} --> {cmd_node}")
    diagrams_lines.extend(["```", "", FOOTER])

    diagrams_path = destination / "diagrams.md"
    diagrams_path.write_text("\n".join(diagrams_lines), encoding="utf-8")
    written_files.append(str(diagrams_path))

    for module in catalog["modules"]:
        lines = [
            f"# {module['name']}",
            "",
            "## Resumen",
            f"- Version: `{module['version']}`",
            f"- Comandos: `{module['commands_count']}`",
            f"- Windows: `{module['windows']}`",
            f"- Linux: `{module['linux']}`",
            f"- Mac: `{module['mac']}`",
            f"- Docker: `{module['docker']}`",
            f"- Descripcion: {module['description'] or 'Sin descripcion'}",
            "",
            "## Dependencias",
        ]

        dependencies = module.get("dependencies", {})
        if isinstance(dependencies, dict) and dependencies:
            for dep_name, dep_version in dependencies.items():
                lines.append(f"- `{dep_name}`: `{dep_version}`")
        else:
            lines.append("- Sin dependencias")

        lines.extend(["", "## Comandos"])
        for command in module["commands"]:
            title = command["title"].get("es") or command["title"].get("en") or command["module"]
            lines.append(f"- `{command['module']}`: {title}")
            if command["inputs"]:
                for field in command["inputs"][:10]:
                    field_title = field["title"].get("es") or field["title"].get("en") or field["id"]
                    lines.append(f"  - `{field['id']}` `{field['type']}` {field_title}")

        lines.extend(["", "## Relacionados", "- [[index]]", "- [[diagrams]]", "", FOOTER])

        note_path = destination / note_names[module["name"]]
        note_path.write_text("\n".join(lines), encoding="utf-8")
        written_files.append(str(note_path))

    return {
        "modules_dir": catalog["modules_dir"],
        "output_dir": str(destination),
        "modules_count": catalog["modules_count"],
        "files_created": written_files,
    }
