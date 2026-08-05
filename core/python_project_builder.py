from __future__ import annotations

import hashlib
import html
import json
import re
import zipfile
import ast
from datetime import datetime
from pathlib import Path
from typing import Any

from core.db_builder import (
    export_rocketbot_db,
    inspect_rocketbot_db,
    normalize_rocketbot_db_copy,
)


PLAN_VERSION = "1"
SENSITIVE_RE = re.compile(r"(?i)(token|api[-_]?key|password|passwd|secret|authorization|clave)")
SENSITIVE_VAR_RE = re.compile(r"(?i)(token|psw|pass|clave|secret|apikey|usuario|user)")
CONFIG_KEY_RE = re.compile(
    r"\bConfig\s*(?:\[\s*['\"]([^'\"]+)['\"]\s*\]|\.\s*get\s*\(\s*['\"]([^'\"]+)['\"])",
)
MINIMUM_CONFIG_KEYS = ("AsuntoInicio", "CuerpoInicio")
SUPPORTED_FATHERS = {
    "setvar", "execrocketbotdb", "evaluateif", "for", "evaluatewhile",
    "trycatch", "group", "break", "request", "log", "logging",
    "execpython", "execscriptpython",
}


def _command_payload(node: dict[str, Any]) -> dict[str, Any]:
    value = node.get("command", "")
    if not isinstance(value, str) or not value.lstrip().startswith("{"):
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_payload(value: Any, key: str = "") -> Any:
    if SENSITIVE_RE.search(key):
        return "<omitted>"
    if isinstance(value, dict):
        return {str(k): _safe_payload(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item, key) for item in value]
    if isinstance(value, str) and SENSITIVE_RE.search(value):
        return "<omitted>"
    return value


def _safe_ir_node(node: dict[str, Any], order: int) -> dict[str, Any]:
    payload = _command_payload(node)
    command = str(node.get("command", ""))
    if SENSITIVE_RE.search(command):
        command = "<omitted>"
    return {
        "order": order,
        "line": node.get("line", order),
        "father": str(node.get("father", "")),
        "module": str(node.get("module", payload.get("module", ""))),
        "command": command,
        "payload": _safe_payload(payload),
        "description": str(node.get("description", "")),
        "children": [
            _safe_ir_node(child, index + 1)
            for index, child in enumerate(node.get("children", []))
            if isinstance(child, dict)
        ],
        "else": [
            _safe_ir_node(child, index + 1)
            for index, child in enumerate(node.get("else", []))
            if isinstance(child, dict)
        ],
    }


def _bot_ir(bot: dict[str, Any]) -> dict[str, Any]:
    root = ((bot.get("project") or {}).get("project") or {})
    commands = root.get("commands", []) if isinstance(root, dict) else []
    return {
        "name": str(bot.get("name", "")),
        "variables": [
            _safe_payload(var) for var in root.get("vars", [])
            if isinstance(var, dict)
        ],
        "commands": [
            _safe_ir_node(node, index + 1)
            for index, node in enumerate(commands)
            if isinstance(node, dict)
        ],
    }


def _translation_key(node: dict[str, Any]) -> str:
    father = str(node.get("father", "")).strip().casefold()
    if father != "module":
        return father
    payload = _command_payload(node)
    module = str(node.get("module") or payload.get("module", "")).strip()
    module_name = str(payload.get("module_name", "")).strip()
    if module.casefold() == "cargarconfigpadre" or module_name.casefold() == "cargarconfigpadre":
        return "module:cargarconfigpadre"
    if module.casefold() in {"readfile", "createfolder", "request", "http"}:
        return f"module:{module.casefold()}"
    if module_name.casefold() in {"files", "requests", "http", "sqlite", "database", "logs", "logging", "sap"}:
        return f"module:{module_name.casefold()}"
    return f"module:{module.casefold() or 'unknown'}"


def _is_translatable(node: dict[str, Any], key: str | None = None) -> bool:
    key = key or _translation_key(node)
    supported = key in SUPPORTED_FATHERS or key in {
        "module:readfile", "module:createfolder", "module:request",
        "module:http", "module:files", "module:requests", "module:sqlite",
        "module:database", "module:logs", "module:logging",
        "module:cargarconfigpadre", "module:limpiarvariablesrobot",
        "module:validarrutas",
    }
    if not supported:
        return False
    father = str(node.get("father", "")).casefold()
    if father == "setvar":
        return not (
            SENSITIVE_VAR_RE.search(str(node.get("var", "")))
            or SENSITIVE_RE.search(str(_command_value(node)))
        )
    if father == "module" and key in {"module:request", "module:http", "module:requests"}:
        return not SENSITIVE_RE.search(json.dumps(_command_payload(node), ensure_ascii=False))
    if father in {"execpython", "execscriptpython"}:
        return not SENSITIVE_RE.search(str(node.get("command", "")))
    return True


def _translation_inventory(bots: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    unsupported: set[str] = set()
    unsupported_details: list[dict[str, Any]] = []
    for bot in bots:
        bot_name = str(bot.get("name", ""))
        for node in _walk_commands(((bot.get("project") or {}).get("project") or {}).get("commands", [])):
            key = _translation_key(node)
            counts[key] = counts.get(key, 0) + 1
            if not _is_translatable(node, key):
                unsupported.add(key)
                unsupported_details.append({
                    "command": key,
                    "bot": bot_name,
                    "line": node.get("line", ""),
                })
    return {
        "counts": dict(sorted(counts.items())),
        "supported": sum(counts[key] for key in counts if key not in unsupported),
        "total": sum(counts.values()),
        "unsupported": sorted(unsupported),
        "unsupported_details": unsupported_details,
    }


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


def _config_keys(bots: list[dict[str, Any]]) -> list[str]:
    keys = set(MINIMUM_CONFIG_KEYS)
    for bot in bots:
        root = ((bot.get("project") or {}).get("project") or {})
        for node in _walk_commands(root.get("commands", [])):
            source = str(node.get("command", ""))
            payload = _command_payload(node)
            if payload:
                source += " " + json.dumps(payload, ensure_ascii=False)
            for match in CONFIG_KEY_RE.finditer(source):
                keys.add(match.group(1) or match.group(2))
    return sorted(keys)


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
    variables = root.get("vars", [])
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
        "variables": len(variables) if isinstance(variables, list) else 0,
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


def _build_plan(
    db_path: str,
    output_dir: str,
    template: str,
    mode: str = "scaffold",
    strict: bool = False,
) -> dict[str, Any]:
    source = Path(db_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"No existe la DB Rocketbot: {source}")
    if template != "makro":
        raise ValueError("Por ahora solo está disponible template='makro'")

    if mode not in {"scaffold", "executable"}:
        raise ValueError("mode debe ser 'scaffold' o 'executable'")

    database_status = inspect_rocketbot_db(str(source))
    exported = export_rocketbot_db(
        str(source),
        include_raw_data=False,
        normalize_data_type=True,
    )
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
    config_keys = _config_keys(bots)
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
    module_names = sorted({module for item in summaries for module in item["modules"]})
    translation = _translation_inventory(bots)
    inventory = {
        "commands": sum(item["commands"] for item in summaries),
        "variables": sum(item["variables"] for item in summaries),
        "modules": module_names,
        "module_count": len(module_names),
        "adapter_candidates": module_names,
    }
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
    if mode == "executable":
        structure.extend([
            {"path": "adapters/__init__.py", "purpose": "Adaptadores de integraciones externas."},
            {"path": "adapters/http.py", "purpose": "Cliente HTTP estÃ¡ndar con datos del contexto."},
            {"path": "adapters/sqlite.py", "purpose": "Operaciones SQLite aisladas."},
            {"path": "adapters/files.py", "purpose": "Lectura y rutas de archivos."},
            {"path": "adapters/sap_gui.py", "purpose": "LÃ­mite explÃ­cito para SAP GUI."},
        ])
    warnings = [
        "Las filas duplicadas se redujeron a la versión más reciente por nombre de bot.",
        "No se copian comandos raw ni valores que parezcan secretos.",
        "Las acciones SAP GUI requieren implementación/adaptadores específicos en Funciones.",
        "HU y nombres de archivos son una propuesta revisable antes de generar.",
    ]
    if translation["unsupported"]:
        warnings.append(
            "Comandos sin traductor automÃ¡tico: "
            + ", ".join(translation["unsupported"])
            + "."
        )
    if any(item["contains_sensitive_fields"] for item in summaries):
        warnings.append("La DB contiene campos sensibles; fueron omitidos del plan y del proyecto generado.")
    if database_status["requires_normalization"]:
        if database_status["can_normalize"]:
            warnings.append(
                "La DB contiene payloads legibles con data_type distinto de normal; "
                "la generación creará una copia *_NORMALIZADA.db después de aprobar el plan."
            )
        else:
            warnings.append(
                "La DB tiene filas con data_type distinto de normal que no pudieron decodificarse; "
                "la conversión queda bloqueada hasta revisar esas filas."
            )

    if (
        database_status["unreadable_rows"]
        and not database_status["requires_normalization"]
    ):
        warnings.append(
            "La DB tiene payloads que no pudieron decodificarse; la conversion queda "
            "bloqueada hasta revisar esas filas."
        )

    canonical = {
        "version": PLAN_VERSION,
        "source": str(source),
        "source_size": source.stat().st_size,
        "source_mtime_ns": source.stat().st_mtime_ns,
        "output_dir": str(Path(output_dir).expanduser().resolve()),
        "template": template,
        "mode": mode,
        "strict": strict,
        "config_keys": config_keys,
        "structure": structure,
    }
    plan_id = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "plan_id": plan_id,
        "status": (
            "blocked_db"
            if database_status["unreadable_rows"] and not database_status["can_normalize"]
            else "blocked_unsupported"
            if mode == "executable" and strict and translation["unsupported"]
            else "awaiting_approval"
        ),
        "template": template,
        "mode": mode,
        "strict": strict,
        "source_db": str(source),
        "output_dir": str(Path(output_dir).expanduser().resolve()),
        "main_bot": main_bot,
        "latest_bots": summaries,
        "proposed_hus": hu_files,
        "proposed_functions": function_files,
        "config_fields_count": len(config_fields),
        "config_fields_preview": config_fields[:25],
        "config_keys": config_keys,
        "database_status": database_status,
        "inventory": inventory,
        "translation": translation,
        "intermediate_representation": [
            _bot_ir(bot) for bot in bots
            if bot.get("project") is not None
        ],
        "proposed_structure": structure,
        "warnings": warnings,
        "approval_required": True,
    }


def plan_rocketbot_python_project(
    db_path: str,
    output_dir: str,
    template: str = "makro",
    mode: str = "scaffold",
    strict: bool = False,
) -> dict[str, Any]:
    """Devuelve un plan; nunca escribe el proyecto ni modifica la DB."""
    return _build_plan(db_path, output_dir, template, mode=mode, strict=strict)


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
    """Punto de entrada del andamio; requiere completar la migración."""
    raise RuntimeError("Scaffold sin ejecutar: {name}")
'''


def _command_value(node: dict[str, Any]) -> Any:
    value = node.get("command", "")
    if not isinstance(value, str):
        return value
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _payload_value(payload: dict[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return default


def _indent(lines: list[str], level: int) -> list[str]:
    prefix = "    " * level
    return [prefix + line if line else "" for line in lines]


def _unsupported_line(node: dict[str, Any], strict: bool) -> list[str]:
    key = _translation_key(node)
    detail = {
        "command": key,
        "bot": str(node.get("_bot", "")),
        "line": node.get("line", ""),
    }
    if strict:
        raise ValueError(
            f"Comando sin traductor en modo strict: {key} "
            f"(bot={detail['bot']}, linea={detail['line']})"
        )
    return [f"report_unsupported(context, {detail!r})"]


def _module_lines(node: dict[str, Any], strict: bool) -> list[str]:
    payload = _command_payload(node)
    module = str(node.get("module") or payload.get("module", "")).strip()
    module_name = str(payload.get("module_name", "")).strip()
    normalized = module.casefold()
    normalized_name = module_name.casefold()
    if normalized == "cargarconfigpadre" or normalized_name == "cargarconfigpadre":
        return ["load_config(context)"]
    if normalized == "limpiarvariablesrobot" or normalized_name == "limpiarvariablesrobot":
        variables = str(_payload_value(payload, "input_ListVariables", "variables", default=""))
        names = [name.strip() for name in variables.split(",") if name.strip()]
        return [f"clear_variables(context, {names!r})"]
    if normalized == "validarrutas" or normalized_name == "validarrutas":
        return [f"validate_paths(context, {payload!r})"]
    if normalized == "readfile":
        result = str(_payload_value(payload, "var_", "result_var"))
        path = _payload_value(payload, "file_", "path")
        return [f"context[{result!r}] = files.read_file(resolve({str(path)!r}, context))"]
    if normalized == "createfolder":
        result = str(_payload_value(payload, "var_", "result_var"))
        path = _payload_value(payload, "path")
        return [f"context[{result!r}] = files.create_folder(resolve({str(path)!r}, context))"]
    if normalized in {"request", "http"} or normalized_name in {"requests", "http"}:
        result = str(_payload_value(payload, "res", "result_var", "getvar", default="last_response"))
        url = _payload_value(payload, "url", "endpoint")
        method = _payload_value(payload, "method", "verb", default="GET")
        headers = _payload_value(payload, "headers", "headers_", default={})
        data = _payload_value(payload, "data", "body", "json", default=None)
        if SENSITIVE_RE.search(json.dumps(payload, ensure_ascii=False)):
            return _unsupported_line(node, strict)
        return [
            f"context[{result!r}] = http.request(resolve({str(url)!r}, context), "
            f"method={str(method)!r}, headers=resolve({headers!r}, context), "
            f"data=resolve({data!r}, context))"
        ]
    if normalized in {"query", "execquery", "execsqlite"} or normalized_name in {"sqlite", "database"}:
        result = str(_payload_value(payload, "res", "result_var", "getvar", default="last_query"))
        database = _payload_value(payload, "database", "db_path", "path")
        sql = _payload_value(payload, "sql", "query", "command")
        return [
            f"context[{result!r}] = sqlite.query(resolve({str(database)!r}, context), "
            f"resolve({str(sql)!r}, context))"
        ]
    if normalized_name in {"logs", "logging"} or normalized in {"log", "logging"}:
        message = _payload_value(payload, "message", "text", default=node.get("command", ""))
        return [f"logging.getLogger(__name__).info(resolve({str(message)!r}, context))"]
    if "sap" in normalized or "sap" in normalized_name:
        return _unsupported_line(node, strict)
    return _unsupported_line(node, strict)


def _command_lines(node: dict[str, Any], strict: bool) -> list[str]:
    father = str(node.get("father", "")).strip().casefold()
    if father == "setvar":
        variable = str(node.get("var", ""))
        value = _command_value(node)
        if SENSITIVE_VAR_RE.search(variable) or SENSITIVE_RE.search(str(value)):
            return _unsupported_line(node, strict)
        return [f"context[{variable!r}] = resolve({str(value)!r}, context)"]
    if father == "execrocketbotdb":
        return [f"run_bot(context, {str(node.get('command', ''))!r})"]
    if father == "evaluateif":
        lines = [f"if evaluate({str(node.get('command', ''))!r}, context):"]
        lines.extend(_indent(_commands_lines(node.get("children", []), strict), 1) or ["    pass"])
        alternate = node.get("else", [])
        if alternate:
            lines.append("else:")
            lines.extend(_indent(_commands_lines(alternate, strict), 1))
        return lines
    if father == "for":
        payload = _command_payload(node)
        iterable = _payload_value(payload, "iterable")
        variable = str(_payload_value(payload, "var", default="item"))
        lines = [f"for _item in (resolve({str(iterable)!r}, context) or []):", f"    context[{variable!r}] = _item"]
        lines.extend(_indent(_commands_lines(node.get("children", []), strict), 1))
        return lines
    if father == "evaluatewhile":
        lines = [f"while evaluate({str(node.get('command', ''))!r}, context):"]
        lines.extend(_indent(_commands_lines(node.get("children", []), strict), 1) or ["    pass"])
        return lines
    if father == "trycatch":
        lines = ["try:"]
        lines.extend(_indent(_commands_lines(node.get("children", []), strict), 1) or ["    pass"])
        lines.append("except Exception as exc:")
        lines.append("    context['last_error'] = exc")
        lines.extend(_indent(_commands_lines(node.get("else", []), strict), 1))
        return lines
    if father == "group":
        return _commands_lines(node.get("children", []), strict)
    if father == "break":
        return ["break"]
    if father == "module":
        return _module_lines(node, strict)
    if father in {"request", "log", "logging"}:
        return _module_lines({**node, "module": father}, strict)
    if father in {"execpython", "execscriptpython"}:
        script = str(node.get("command", ""))
        payload = _command_payload(node)
        script = str(_payload_value(payload, "path", "file", "script", default=script))
        if SENSITIVE_RE.search(script):
            return _unsupported_line(node, strict)
        if father == "execpython" and (
            script.casefold().endswith(".py")
            or "/" in script
            or "\\" in script
            or script.startswith(".")
        ):
            detail = {
                "command": "execPython",
                "bot": str(node.get("_bot", "")),
                "line": node.get("line", ""),
            }
            return [
                f"_script_path = Path(resolve({script!r}, context))",
                "if not _script_path.is_absolute():",
                "    _script_path = Path(context['root']) / _script_path",
                "if not _script_path.is_file():",
                f"    report_unsupported(context, {{**{detail!r}, 'reason': f'Archivo no existe: {{_script_path}}'}})",
                "else:",
                "    execute_rocketbot_file(_script_path, context)",
            ]
        return [f"execute_rocketbot_script({script!r}, context)"]
    return _unsupported_line(node, strict)


def _commands_lines(nodes: Any, strict: bool) -> list[str]:
    lines: list[str] = []
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict):
            lines.extend(_command_lines(node, strict))
    return lines


def _executable_source(name: str, commands: list[dict[str, Any]], strict: bool) -> str:
    lines = [
        f'"""Conversión ejecutable del bot Rocketbot {name}."""',
        "import logging",
        "from pathlib import Path",
        "from HU.HU00_Config import (",
        "    evaluate, execute_rocketbot_file, execute_rocketbot_script,",
        "    clear_variables, load_config, report_unsupported, resolve, run_bot,",
        "    validate_paths,",
        ")",
        "from adapters import files, http, sqlite",
        "",
        "",
        "def run(context):",
    ]
    body = _commands_lines(commands, strict)
    lines.extend(_indent(body or ["return context"], 1))
    if body:
        lines.append("    return context")
    return "\n".join(lines) + "\n"


def _source_commands(plan: dict[str, Any], source_bots: list[str]) -> list[dict[str, Any]]:
    exported = export_rocketbot_db(plan["source_db"], include_raw_data=False, normalize_data_type=True)
    by_name = {str(bot.get("name", "")): bot for bot in _latest_bots(exported)}
    def annotate(node: dict[str, Any], bot_name: str) -> dict[str, Any]:
        return {
            **node,
            "_bot": bot_name,
            "children": [annotate(child, bot_name) for child in node.get("children", []) if isinstance(child, dict)],
            "else": [annotate(child, bot_name) for child in node.get("else", []) if isinstance(child, dict)],
        }

    commands: list[dict[str, Any]] = []
    for name in source_bots:
        root = ((by_name.get(name, {}).get("project") or {}).get("project") or {})
        commands.extend(
            annotate(node, name)
            for node in root.get("commands", [])
            if isinstance(node, dict)
        )
    return commands


def _executable_config(required_keys: list[str]) -> str:
    required_keys_literal = repr(tuple(required_keys))
    template = '''import ast
import json
import logging
import re
from pathlib import Path

_PLACEHOLDER = re.compile(r"\\{([^{}]+)\\}")
REQUIRED_CONFIG_KEYS = __REQUIRED_CONFIG_KEYS__


def resolve(value, context):
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\\{([^{}]+)\\}", value.strip())
    if match:
        return context.get(match.group(1), "")
    return _PLACEHOLDER.sub(lambda item: str(context.get(item.group(1), item.group(0))), value)


def evaluate(expression, context):
    value = resolve(expression, context)
    if isinstance(value, bool):
        return value
    try:
        literal = ast.literal_eval(str(value))
        if isinstance(literal, bool):
            return literal
    except (SyntaxError, ValueError):
        pass
    try:
        return bool(eval(str(value), {"__builtins__": {}}, dict(context)))
    except Exception:
        return bool(value)


def report_unsupported(context, command):
    context.setdefault("unsupported_commands", []).append(command)
    logging.getLogger(__name__).warning("Comando Rocketbot no traducido: %s", command)


def run_bot(context, name):
    runner = context.get("bot_registry", {}).get(name)
    if runner is None:
        report_unsupported(context, f"execRocketBotDB:{name}")
        return None
    return runner(context)


def GetVar(name, context):
    value = context.get(name, "")
    if isinstance(value, (dict, list)):
        return repr(value)
    return value


def SetVar(name, value, context):
    context[name] = value


def clear_variables(context, names):
    for name in names:
        context[name] = ""


def validate_paths(context, payload):
    root = Path(context["root"])
    paths = {
        "check_ArchivosRecibidos": root / "Inputs",
        "check_Trazabilidad": root / "Logs",
        "check_Formatos": root / "Plantillas",
    }
    for option, path in paths.items():
        if payload.get(option):
            path.mkdir(parents=True, exist_ok=True)
    return True


def execute_rocketbot_script(source, context, filename="<rocketbot>"):
    namespace = {
        "context": context,
        "GetVar": lambda name: GetVar(name, context),
        "SetVar": lambda name, value: SetVar(name, value, context),
    }
    exec(compile(source, filename, "exec"), namespace, namespace)


def execute_rocketbot_file(path, context):
    script_path = Path(path)
    if not script_path.is_file():
        raise FileNotFoundError(f"Archivo Rocketbot no encontrado: {script_path}")
    execute_rocketbot_script(
        script_path.read_text(encoding="utf-8"),
        context,
        str(script_path),
    )


def load_config(context, required_keys=REQUIRED_CONFIG_KEYS):
    config_path = Path(context["root"]) / "config" / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Falta el archivo de configuración: {config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Configuración JSON inválida en {config_path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"La configuración debe ser un objeto JSON en {config_path}")
    missing = [key for key in required_keys if key not in config]
    if missing:
        raise ValueError(
            f"Falta configuración requerida '{missing[0]}' en {config_path}"
        )
    context["vGblDicConfig"] = config
    return config


def build_context():
    root = __import__("pathlib").Path(__file__).parents[1]
    logging.basicConfig(filename=root / "Logs" / "execution.log", level=logging.INFO)
    return {"root": root, "inputs": root / "Inputs", "outputs": root / "Outputs"}
'''
    return template.replace("__REQUIRED_CONFIG_KEYS__", required_keys_literal)


def _adapter_source(path: str) -> str:
    if path.endswith("http.py"):
        return '''from urllib.request import Request, urlopen
import json


def request(url, method="GET", headers=None, data=None):
    body = None if data is None else (json.dumps(data).encode() if isinstance(data, (dict, list)) else str(data).encode())
    request = Request(url, data=body, headers=headers or {}, method=method.upper())
    with urlopen(request) as response:
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
'''
    if path.endswith("sqlite.py"):
        return '''import sqlite3


def query(database, sql, params=()):
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
'''
    if path.endswith("files.py"):
        return '''from pathlib import Path


def read_file(path):
    return Path(path).read_text(encoding="utf-8")


def create_folder(path):
    destination = Path(path)
    destination.mkdir(parents=True, exist_ok=True)
    return str(destination)
'''
    if path.endswith("sap_gui.py"):
        return '''def execute(*args, **kwargs):
    raise RuntimeError("SAP GUI requiere un adaptador real validado en Windows")
'''
    return ""


def _executable_main(plan: dict[str, Any]) -> str:
    imports = [
        "from pathlib import Path",
        "from HU.HU00_Config import (",
        "    build_context,",
        "    run_bot,",
        "    resolve,",
        "    evaluate,",
        "    clear_variables,",
        "    load_config,",
        "    report_unsupported,",
        "    validate_paths,",
        "    execute_rocketbot_file,",
        "    execute_rocketbot_script,",
        ")",
    ]
    registry: list[str] = []
    for index, entry in enumerate(plan["proposed_structure"]):
        if not entry.get("source_bots") or not entry["path"].endswith(".py"):
            continue
        if entry["path"].endswith("HU00_Config.py"):
            continue
        module = entry["path"].replace("/", ".")[:-3]
        alias = f"_run_{index}"
        imports.append(f"from {module} import run as {alias}")
        registry.extend(f"    {name!r}: {alias}," for name in entry["source_bots"])
    main_name = str((plan.get("main_bot") or {}).get("name", "main"))
    lines = [
        '"""Orquestador ejecutable generado desde Rocketbot."""',
        *imports,
        "",
        "",
        "def main():",
        "    context = build_context()",
        "    context['bot_registry'] = {",
        *registry,
        "    }",
    ]
    body = _commands_lines(_source_commands(plan, [main_name]), bool(plan.get("strict")))
    lines.extend(_indent(body or ["return context"], 1))
    if body:
        lines.append("    return context")
    lines.extend(["", "", "if __name__ == \"__main__\":", "    main()"])
    return "\n".join(lines) + "\n"


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
                _write_text(path, _executable_main(plan) if plan.get("mode") == "executable" else '''"""Orquestador del proyecto Python generado desde Rocketbot."""

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
                _write_text(path, _executable_config(plan.get("config_keys", [])) if plan.get("mode") == "executable" else '''from pathlib import Path


def build_context():
    root = Path(__file__).parents[1]
    return {"root": root, "inputs": root / "Inputs", "outputs": root / "Outputs"}
''')
            elif path.parts[0] == "adapters":
                _write_text(path, _adapter_source(entry["path"]))
            else:
                if plan.get("mode") == "executable":
                    source_bots = entry.get("source_bots") or [Path(entry["path"]).stem]
                    name = source_bots[0]
                    _write_text(path, _executable_source(
                        str(name),
                        _source_commands(plan, source_bots),
                        bool(plan.get("strict")),
                    ))
                else:
                    _write_text(path, _module_stub(entry))
        elif path.name == "config.json":
            config = {
                "inputs": "Inputs",
                "outputs": "Outputs",
                "logs": "Logs",
                "rocketbot_variables": [field["name"] for field in _config_fields(
                    _latest_bots(export_rocketbot_db(plan["source_db"], include_raw_data=False)),
                    str((plan.get("main_bot") or {}).get("name", "")),
                )],
            }
            for key in plan.get("config_keys", []):
                config[key] = (
                    "[PRUEBA] NOMBRE_ROBOT"
                    if key == "AsuntoInicio"
                    else "Inicio del robot NOMBRE_ROBOT"
                    if key == "CuerpoInicio"
                    else "False"
                    if key.casefold().startswith("booleano")
                    else ""
                )
            _write_text(path, json.dumps(config, indent=2, ensure_ascii=False))
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
    python_files = [path for path in root.rglob("*.py") if path.is_file()]
    compile_errors = []
    for python_file in python_files:
        source = python_file.read_text(encoding="utf-8")
        if "NotImplementedError" in source:
            compile_errors.append(f"{python_file}: NotImplementedError")
        try:
            compile(source, str(python_file), "exec")
        except SyntaxError as exc:
            compile_errors.append(f"{python_file}: {exc}")
    if compile_errors:
        raise RuntimeError("El proyecto generado no pasa validaciÃ³n: " + "; ".join(compile_errors))
    result = {
        "output_dir": str(root),
        "files_created": len(plan["proposed_structure"]),
        "plan_id": plan["plan_id"],
        "validation": {
            "python_files": len(python_files),
            "compile_errors": compile_errors,
            "not_implemented_errors": [],
            "mode": plan.get("mode", "scaffold"),
        },
    }
    if "approval_plan_id" in plan:
        result["approval_plan_id"] = plan["approval_plan_id"]
    if "normalization" in plan:
        result["normalization"] = plan["normalization"]
    return result


def generate_rocketbot_python_project(
    db_path: str,
    output_dir: str,
    plan_id: str,
    approve: bool = False,
    template: str = "makro",
    overwrite: bool = False,
    mode: str = "scaffold",
    strict: bool = False,
    normalize_db: bool = False,
) -> dict[str, Any]:
    """Genera solo después de aprobación explícita y validación del plan."""
    if not approve:
        raise PermissionError("La generación requiere approve=true después de revisar el plan")
    plan = _build_plan(db_path, output_dir, template, mode=mode, strict=strict)
    if plan["plan_id"] != plan_id:
        raise ValueError("El plan_id no coincide; la DB, salida o estructura cambió")
    if plan["status"] != "awaiting_approval":
        raise PermissionError(f"El plan no estÃ¡ listo para generar: {plan['status']}")
    if normalize_db and plan["database_status"]["requires_normalization"]:
        normalized = normalize_rocketbot_db_copy(plan["source_db"])
        generated_plan = _build_plan(
            normalized["normalized_db"],
            output_dir,
            template,
            mode=mode,
            strict=strict,
        )
        generated_plan["approval_plan_id"] = plan_id
        generated_plan["source_db_original"] = plan["source_db"]
        generated_plan["normalization"] = normalized
        generated_plan["plan_id"] = plan_id
        plan = generated_plan
    else:
        plan["approval_plan_id"] = plan_id
    root = Path(plan["output_dir"])
    if root.exists() and any(root.iterdir()) and not overwrite:
        raise FileExistsError(f"La carpeta no está vacía: {root}; use overwrite=true si corresponde")
    return _write_generated_project(plan)
