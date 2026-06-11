from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.db_builder import export_rocketbot_db


FOOTER = "skill made by Johan Sabino  \nhttps://www.linkedin.com/in/johanandressabino/\n"


def _slugify(value: str) -> str:
    text = re.sub(r"[^\w\- ]+", "", value, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s\-]+", "-", text)
    return text or "bot"


def _bot_note_name(bot: dict[str, Any]) -> str:
    return _slugify(bot.get("name", "bot")) + ".md"


def _extract_project_sections(bot: dict[str, Any]) -> dict[str, Any]:
    project_wrapper = bot.get("project") or {}
    project = project_wrapper.get("project", {}) if isinstance(project_wrapper, dict) else {}
    return {
        "commands": project.get("commands", []),
        "ifs": project.get("ifs", []),
        "modules": project.get("modules", []),
        "vars": project.get("vars", []),
        "profile": project.get("profile", {}),
    }


def _summarize_names(items: list[Any], candidates: list[str], limit: int = 15) -> list[str]:
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in candidates:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
                break
        if len(names) >= limit:
            break
    return names


def _render_list(title: str, items: list[str]) -> str:
    if not items:
        return f"## {title}\n- Sin datos\n"
    body = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n{body}\n"


def _render_metadata(bot: dict[str, Any]) -> str:
    lines = [
        "## Metadatos",
        f"- ID: `{bot.get('id', '')}`",
        f"- Nombre: `{bot.get('name', '')}`",
        f"- Tipo: `{bot.get('data_type', '')}`",
        f"- Padre: `{bot.get('father', '')}`",
        f"- Versión: `{bot.get('version', '')}`",
        f"- Creado: `{bot.get('created_at', '')}`",
        f"- Descripción: {bot.get('description', '') or 'Sin descripción'}",
        "",
    ]
    return "\n".join(lines)


def _render_bot_note(bot: dict[str, Any], related_links: list[str]) -> str:
    lines = [f"# {bot.get('name', 'Bot')}", ""]
    lines.append(_render_metadata(bot))

    if bot.get("encrypted"):
        lines.extend(
            [
                "## Estado",
                "- Payload cifrado",
                f"- Longitud raw: `{bot.get('raw_data_length', 0)}`",
                "",
                "## Preview",
                "```text",
                bot.get("raw_data_preview", ""),
                "```",
                "",
            ]
        )
    else:
        sections = _extract_project_sections(bot)
        profile = sections["profile"] if isinstance(sections["profile"], dict) else {}
        lines.extend(
            [
                "## Resumen",
                f"- Comandos: `{len(sections['commands'])}`",
                f"- IFs: `{len(sections['ifs'])}`",
                f"- Módulos: `{len(sections['modules'])}`",
                f"- Variables: `{len(sections['vars'])}`",
                "",
                _render_list(
                    "Comandos Detectados",
                    _summarize_names(sections["commands"], ["command", "module_name", "group", "father"]),
                ),
                _render_list(
                    "Módulos Detectados",
                    _summarize_names(sections["modules"], ["module", "name", "id"]),
                ),
                _render_list(
                    "Variables Detectadas",
                    _summarize_names(sections["vars"], ["name", "var", "variable"]),
                ),
                "## Perfil",
                "```json",
                json.dumps(profile, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )

    lines.append("## Relacionados")
    if related_links:
        lines.extend(f"- [[{link}]]" for link in related_links)
    else:
        lines.append("- Sin relacionados")
    lines.extend(["", FOOTER])
    return "\n".join(lines)


def _render_index(project_name: str, bots: list[dict[str, Any]], note_map: dict[str, str]) -> str:
    process_lines = [f"- [[{note_map[bot['name']][:-3]}]]" for bot in bots]
    lines = [
        f"# {project_name}",
        "",
        "## Resumen Ejecutivo",
        f"- Bots detectados: `{len(bots)}`",
        "- Fuente: exportación desde Rocketbot `.db`",
        "",
        "## Notas",
    ]
    lines.extend(process_lines or ["- Sin bots"])
    lines.extend(
        [
            "",
            "## Procesos Detectados",
        ]
    )
    lines.extend(process_lines or ["- Sin procesos"])
    lines.extend(
        [
            "",
            "## Diagramas",
            "- [[diagrams]]",
            "",
            FOOTER,
        ]
    )
    return "\n".join(lines)


def _render_diagrams(project_name: str, bots: list[dict[str, Any]], note_map: dict[str, str]) -> str:
    lines = [
        f"# Diagramas {project_name}",
        "",
        "## Flujo General",
        "```mermaid",
        "flowchart TD",
    ]
    for bot in bots:
        node = _slugify(bot["name"])
        label = bot["name"].replace('"', "'")
        lines.append(f'    {node}["{label}"]')
    for bot in bots:
        parent = (bot.get("father") or "").strip()
        if parent and parent in note_map:
            lines.append(f"    {_slugify(parent)} --> {_slugify(bot['name'])}")
    lines.extend(["```", "", FOOTER])
    return "\n".join(lines)


def export_rocketbot_db_to_obsidian(
    db_path: str,
    output_dir: str,
    include_raw_data: bool = False,
) -> dict[str, Any]:
    exported = export_rocketbot_db(db_path=db_path, include_raw_data=include_raw_data)
    bots = exported["bots"]

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    project_name = Path(db_path).stem
    note_map = {bot["name"]: _bot_note_name(bot) for bot in bots}
    written_files: list[str] = []

    index_path = destination / "index.md"
    index_path.write_text(_render_index(project_name, bots, note_map), encoding="utf-8")
    written_files.append(str(index_path))

    diagrams_path = destination / "diagrams.md"
    diagrams_path.write_text(_render_diagrams(project_name, bots, note_map), encoding="utf-8")
    written_files.append(str(diagrams_path))

    for bot in bots:
        related = []
        parent = (bot.get("father") or "").strip()
        if parent and parent in note_map:
            related.append(note_map[parent][:-3])
        for child in bots:
            if (child.get("father") or "").strip() == bot["name"] and child["name"] in note_map:
                related.append(note_map[child["name"]][:-3])

        note_path = destination / note_map[bot["name"]]
        note_path.write_text(_render_bot_note(bot, related), encoding="utf-8")
        written_files.append(str(note_path))

    return {
        "source_db": exported["source_db"],
        "output_dir": str(destination),
        "files_created": written_files,
        "bots_count": exported["bots_count"],
    }
