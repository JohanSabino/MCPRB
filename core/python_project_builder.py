from __future__ import annotations

import hashlib
import html
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.db_builder import export_rocketbot_db


PLAN_VERSION = "1"
SENSITIVE_RE = re.compile(r"(?i)(token|api[-_]?key|password|passwd|secret|authorization|clave)")
SENSITIVE_VAR_RE = re.compile(r"(?i)(token|psw|pass|clave|secret|apikey|usuario|user)")


def _slug(value: str, fallback: str = "item") -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return value or fallback


def _walk_commands(nodes: Any):
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        yield node
        yield from _walk_commands(node.get("children"))
        yield from _walk_commands(node.get("else"))


def _latest_bots(exported: dict[str, Any]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for bot in exported.get("bots", []):
        name = str(bot.get("name", "")).strip()
        if not name:
            continue
        current = latest.get(name)
        candidate_key = (str(bot.get("created_at", "")), int(bot.get("id") or 0))
        current_key = (
            str(current.get("created_at", "")),
            int(current.get("id") or 0),
        ) if current else ("", 0)
        if current is None or candidate_key >= current_key:
            latest[name] = bot
    return sorted(latest.values(), key=lambda item: str(item.get("name", "")))


def _bot_summary(bot: dict[str, Any]) -> dict[str, Any]:
    project = bot.get("project") or {}
    root = project.get("project", {}) if isinstance(project, dict) else {}
    commands = list(_walk_commands(root.get("commands", [])))
    modules: set[str] = set()
    fathers: set[str] = set()
    sensitive = False
    for command in commands:
        father = str(command.get("father", ""))
        if father:
            fathers.add(father)
        raw = command.get("command", "")
        if isinstance(raw, str):
            sensitive = sensitive or bool(SENSITIVE_RE.search(raw))
            if raw.lstrip().startswith("{"):
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {}
                if isinstance(payload, dict) and payload.get("module"):
                    modules.add(str(payload["module"]))
        if command.get("module"):
            modules.add(str(command["module"]))
    return {
        "id": bot.get("id"),
        "name": str(bot.get("name", "")),
        "created_at": bot.get("created_at", ""),
        "description": bot.get("description", ""),
        "commands": len(commands),
        "modules": sorted(modules),
        "command_types": sorted(fathers),
        "contains_sensitive_fields": sensitive,
    }


def _config_fields(bots: list[dict[str, Any]], main_name: str) -> list[dict[str, Any]]:
    source = next((bot for bot in bots if str(bot.get("name", "")) == main_name), None)
    if not source:
        return []
    root = ((source.get("project") or {}).get("project") or {})
    fields = []
    for var in root.get("vars", []) if isinstance(root.get("vars", []), list) else []:
        if not isinstance(var, dict) or not str(var.get("name", "")).strip():
            continue
        name = str(var["name"])
        fields.append({
            "name": name,
            "type": str(var.get("type", "string")),
            "sensitive": bool(SENSITIVE_VAR_RE.search(name)),
        })
    return fields


def _group_hus(bots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for bot in bots:
        match = re.match(r"(?i)HU[_ -]?(\d+)", str(bot.get("name", "")))
        if match:
            groups.setdefault(f"HU{int(match.group(1)):02d}", []).append(str(bot["name"]))

    result = [{
        "path": "HU/HU00_Config.py",
        "purpose": "Carga de configuración, variables, rutas y preparación del entorno.",
        "source_bots": [],
    }]
    for prefix, names in sorted(groups.items()):
        suffixes = [name.split("_", 1)[1] for name in names if "_" in name]
        joined = " ".join(suffixes).lower()
        title = "Cola_y_Archivos" if "coladetrabajo" in joined and "obtenerarchivo" in joined else "Flujo"
        result.append({
            "path": f"HU/{prefix}_{title}.py",
            "purpose": "Unidad funcional propuesta a partir de los subbots Rocketbot.",
            "source_bots": sorted(names),
        })

    if any(str(bot.get("name", "")).lower().startswith("procesamiento") for bot in bots):
        result.append({
            "path": "HU/HU02_Procesamiento.py",
            "purpose": "Procesamiento de negocio y recorrido de diferencias.",
            "source_bots": sorted(
                str(bot["name"])
                for bot in bots
                if str(bot.get("name", "")).lower().startswith("procesamiento")
            ),
        })
    result.append({
        "path": "HU/HU99_Cierre.py",
        "purpose": "Notificación, consolidación de logs y cierre controlado.",
        "source_bots": sorted(
            str(bot["name"])
            for bot in bots
            if str(bot.get("name", "")).lower() in {"inicializacion", "finalizacion", "endprocessmvp2"}
        ),
    })
    return result


def _build_plan(db_path: str, output_dir: str, template: str) -> dict[str, Any]:
    source = Path(db_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"No existe la DB Rocketbot: {source}")
    if template != "makro":
        raise ValueError("Por ahora solo está disponible template='makro'")

    exported = export_rocketbot_db(str(source), include_raw_data=False)
    bots = _latest_bots(exported)
    summaries = [_bot_summary(bot) for bot in bots]
    main_bot = next((item for item in summaries if item["name"] == "main"), None)
    if main_bot is None:
        main_bot = next((item for item in summaries if item["name"].lower().startswith("epm_")), None)
    if main_bot is None and summaries:
        main_bot = summaries[0]

    hu_files = _group_hus(bots)
    main_name = str((main_bot or {}).get("name", ""))
    config_fields = _config_fields(bots, main_name)
    function_bots = [
        item for item in summaries
        if item["name"] not in {entry for hu in hu_files for entry in hu["source_bots"]}
        and item["name"] != (main_bot or {}).get("name")
    ]
    function_files = [
        {
            "path": f"Funciones/{_slug(item['name'])}.py",
            "purpose": f"Adaptador Python para el subbot {item['name']}.",
            "source_bots": [item["name"]],
        }
        for item in function_bots
    ]
    structure = [
        {"path": "main.py", "purpose": "Orquestador principal Python."},
        *hu_files,
        *function_files,
        {"path": "config/config.xlsx", "purpose": "Matriz editable de configuración."},
        {"path": "config/config.json", "purpose": "Configuración técnica sin secretos."},
        {"path": "Inputs/.gitkeep", "purpose": "Entradas del proceso."},
        {"path": "Outputs/.gitkeep", "purpose": "Salidas del proceso."},
        {"path": "Plantillas/.gitkeep", "purpose": "Plantillas y documentos de referencia."},
        {"path": "Logs/.gitkeep", "purpose": "Logs de ejecución."},
        {"path": "Temp/.gitkeep", "purpose": "Archivos temporales no versionables."},
        {"path": "tests/test_structure.py", "purpose": "Smoke test de estructura generada."},
        {"path": "docs/ROCKETBOT_MAPPING.json", "purpose": "Mapa seguro de bots, módulos y líneas."},
        {"path": "docs/CONVERSION_PLAN.md", "purpose": "Plan aprobado y límites de conversión."},
        {"path": ".env.example", "purpose": "Nombres de variables sensibles, sin valores."},
    ]
    warnings = [
        "Las filas duplicadas se redujeron a la versión más reciente por nombre de bot.",
        "No se copian comandos raw ni valores que parezcan secretos.",
        "Las acciones SAP GUI requieren implementación/adaptadores específicos en Funciones.",
        "HU y nombres de archivos son una propuesta revisable antes de generar.",
    ]
    if any(item["contains_sensitive_fields"] for item in summaries):
        warnings.append("La DB contiene campos sensibles; fueron omitidos del plan y del proyecto generado.")

    canonical = {
        "version": PLAN_VERSION,
        "source": str(source),
        "source_size": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "output_dir": str(Path(output_dir).expanduser().resolve()),
        "template": template,
        "structure": structure,
    }
    plan_id = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "plan_id": plan_id,
        "status": "awaiting_approval",
        "template": template,
        "source_db": str(source),
        "output_dir": str(Path(output_dir).expanduser().resolve()),
        "main_bot": main_bot,
        "latest_bots": summaries,
        "proposed_hus": hu_files,
        "proposed_functions": function_files,
        "config_fields_count": len(config_fields),
        "config_fields_preview": config_fields[:25],
        "proposed_structure": structure,
        "warnings": warnings,
        "approval_required": True,
    }


def plan_rocketbot_python_project(db_path: str, output_dir: str, template: str = "makro") -> dict[str, Any]:
    """Devuelve un plan; nunca escribe el proyecto ni modifica la DB."""
    return _build_plan(db_path, output_dir, template)


def _write_xlsx_placeholder(path: Path, config_fields: list[dict[str, Any]]) -> None:
    rows = [
        ["Clave", "Valor", "Descripción"],
        ["DANA_API_TOKEN", "", "Configurar fuera del repositorio"],
        ["RUTA_INPUTS", "Inputs", "Ruta de entradas"],
        ["RUTA_OUTPUTS", "Outputs", "Ruta de salidas"],
    ]
    rows.extend(
        [field["name"], "", "Variable Rocketbot migrada; revisar sensibilidad"]
        for field in config_fields
    )

    def cell(row: int, column: int, value: Any) -> str:
        letter = chr(64 + column)
        text = html.escape(str(value))
        return f'<c r="{letter}{row}" t="inlineStr"><is><t>{text}</t></is></c>'

    sheet_rows = "".join(
        f'<row r="{row_number}">'
        + "".join(cell(row_number, col, value) for col, value in enumerate(row, 1))
        + "</row>"
        for row_number, row in enumerate(rows, 1)
    )
    files = {
        "[Content_Types].xml": """<?xml version='1.0' encoding='UTF-8'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
<Default Extension='xml' ContentType='application/xml'/>
<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>
<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>
</Types>""",
        "_rels/.rels": """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version='1.0' encoding='UTF-8'?>
<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>
<sheets><sheet name='Config' sheetId='1' r:id='rId1'/></sheets></workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": f"""<?xml version='1.0' encoding='UTF-8'?>
<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>{sheet_rows}</sheetData></worksheet>""",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        for name, content in files.items():
            workbook.writestr(name, content)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _module_stub(item: dict[str, Any]) -> str:
    name = item["source_bots"][0] if item.get("source_bots") else Path(item["path"]).stem
    return f'''"""Adaptador Python generado desde el bot Rocketbot {name}."""


def run(context):
    """Ejecuta esta unidad después de completar su adaptación funcional."""
    raise NotImplementedError("Migrar pasos SAP/GUI y reglas específicas de {name}")
'''


def _write_generated_project(plan: dict[str, Any]) -> dict[str, Any]:
    root = Path(plan["output_dir"])
    root.mkdir(parents=True, exist_ok=True)
    for entry in plan["proposed_structure"]:
        path = root / entry["path"]
        if path.name == ".gitkeep":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        elif path.suffix == ".py":
            if path.name == "main.py":
                _write_text(path, '''"""Orquestador del proyecto Python generado desde Rocketbot."""

from HU.HU00_Config import build_context


def main():
    context = build_context()
    print("Proyecto generado; revisar docs/CONVERSION_PLAN.md antes de ejecutar HUs.")
    return context


if __name__ == "__main__":
    main()
''')
            elif path.name == "test_structure.py":
                _write_text(path, '''from pathlib import Path


def test_project_layout():
    root = Path(__file__).parents[1]
    for name in ("HU", "Funciones", "Inputs", "Outputs", "Plantillas", "Logs", "Temp"):
        assert (root / name).is_dir()
''')
            elif path.name == "HU00_Config.py":
                _write_text(path, '''from pathlib import Path


def build_context():
    root = Path(__file__).parents[1]
    return {"root": root, "inputs": root / "Inputs", "outputs": root / "Outputs"}
''')
            else:
                _write_text(path, _module_stub(entry))
        elif path.name == "config.json":
            _write_text(path, json.dumps({
                "inputs": "Inputs",
                "outputs": "Outputs",
                "logs": "Logs",
                "rocketbot_variables": [field["name"] for field in _config_fields(
                    _latest_bots(export_rocketbot_db(plan["source_db"], include_raw_data=False)),
                    str((plan.get("main_bot") or {}).get("name", "")),
                )],
            }, indent=2))
        elif path.name == "CONVERSION_PLAN.md":
            _write_text(path, "# Plan de conversión Rocketbot → Python\n\n" + json.dumps(plan, ensure_ascii=False, indent=2))
        elif path.name == "ROCKETBOT_MAPPING.json":
            _write_text(path, json.dumps({"source_db": plan["source_db"], "bots": plan["latest_bots"]}, ensure_ascii=False, indent=2))
        elif path.name == ".env.example":
            _write_text(path, "DANA_API_TOKEN=\n\n# No guardar valores reales en el repositorio.")
        elif path.name == "config.xlsx":
            exported = export_rocketbot_db(plan["source_db"], include_raw_data=False)
            fields = _config_fields(
                _latest_bots(exported),
                str((plan.get("main_bot") or {}).get("name", "")),
            )
            _write_xlsx_placeholder(path, fields)
    return {"output_dir": str(root), "files_created": len(plan["proposed_structure"]), "plan_id": plan["plan_id"]}


def generate_rocketbot_python_project(
    db_path: str,
    output_dir: str,
    plan_id: str,
    approve: bool = False,
    template: str = "makro",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Genera solo después de aprobación explícita y validación del plan."""
    if not approve:
        raise PermissionError("La generación requiere approve=true después de revisar el plan")
    plan = _build_plan(db_path, output_dir, template)
    if plan["plan_id"] != plan_id:
        raise ValueError("El plan_id no coincide; la DB, salida o estructura cambió")
    root = Path(plan["output_dir"])
    if root.exists() and any(root.iterdir()) and not overwrite:
        raise FileExistsError(f"La carpeta no está vacía: {root}; use overwrite=true si corresponde")
    return _write_generated_project(plan)
