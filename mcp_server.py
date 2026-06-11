from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from dotenv import load_dotenv

from core.db_builder import create_rocketbot_db, create_rocketbot_db_from_bots, export_rocketbot_db
from core.file_reader import read_text_file, resolve_project_path
from core.logs import list_log_files, read_log_file_tail, read_log_tail
from core.module_catalog import export_module_catalog_json, export_module_catalog_obsidian, scan_rocketbot_modules
from core.obsidian_exporter import export_rocketbot_db_to_obsidian
from core.paths import describe_paths, logs_dir, modules_dir as detected_modules_dir, projects_dir, variables_file
from core.searcher import search_text
from core.variables import load_variables


load_dotenv()

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
MCP_SSE_PATH = os.getenv("MCP_SSE_PATH", "/sse").strip() or "/sse"
MCP_STREAMABLE_HTTP_PATH = os.getenv("MCP_STREAMABLE_HTTP_PATH", "/mcp").strip() or "/mcp"

mcp = FastMCP(
    "MCP Rocketbot",
    log_level="ERROR",
    host=MCP_HOST,
    port=MCP_PORT,
    sse_path=MCP_SSE_PATH,
    streamable_http_path=MCP_STREAMABLE_HTTP_PATH,
)


def _project_root(project_name: str | None = None) -> Path:
    base = projects_dir()
    if not project_name:
        return base
    target = (base / project_name).resolve()
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"Proyecto no encontrado: {project_name}")
    return target


@mcp.tool(description="Devuelve rutas clave detectadas para Rocketbot.")
def get_rocketbot_paths() -> dict[str, str]:
    return describe_paths()


@mcp.tool(description="Lista proyectos o carpetas dentro del directorio de proyectos de Rocketbot.")
def list_projects() -> list[str]:
    base = projects_dir()
    if not base.exists():
        return []
    return sorted(item.name for item in base.iterdir() if item.is_dir())


@mcp.tool(description="Lista archivos de un proyecto Rocketbot.")
def list_project_files(
    project_name: str = Field(description="Nombre del proyecto/carpeta"),
) -> list[str]:
    root = _project_root(project_name)
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )


@mcp.tool(description="Lee un archivo de un proyecto Rocketbot de forma segura.")
def read_project_file(
    project_name: str = Field(description="Nombre del proyecto/carpeta"),
    relative_path: str = Field(description="Ruta relativa al proyecto"),
    max_chars: int = Field(default=20000, ge=200, le=200000),
) -> str:
    root = _project_root(project_name)
    path = resolve_project_path(root, relative_path)
    return read_text_file(path, max_chars=max_chars)


@mcp.tool(description="Busca texto dentro de archivos de un proyecto Rocketbot.")
def search_in_project(
    project_name: str = Field(description="Nombre del proyecto/carpeta"),
    query: str = Field(description="Texto a buscar"),
    file_pattern: str = Field(default="*", description="Patrón glob, por ejemplo *.py"),
    max_results: int = Field(default=20, ge=1, le=100),
) -> list[dict[str, object]]:
    root = _project_root(project_name)
    return search_text(root, query=query, file_pattern=file_pattern, max_results=max_results)


@mcp.tool(
    description=(
        "Lista archivos .log. Acepta una ruta absoluta opcional; si se omite, "
        "usa ROCKETBOT_LOGS_DIR o la ruta autodetectada."
    )
)
def list_rocketbot_logs(
    logs_path: str | None = Field(
        default=None,
        description="Ruta absoluta opcional del directorio de logs",
    ),
) -> list[str]:
    target = Path(logs_path).expanduser().resolve() if logs_path else logs_dir()
    return list_log_files(target)


@mcp.tool(
    description=(
        "Lee las últimas líneas de un log. Usa log_path para cualquier archivo "
        "absoluto, o log_name junto con logs_path. Sin rutas usa el directorio configurado."
    )
)
def read_rocketbot_log(
    log_name: str | None = Field(default=None, description="Nombre del archivo .log; si se omite usa el más reciente"),
    lines: int = Field(default=200, ge=1, le=5000),
    log_path: str | None = Field(
        default=None,
        description="Ruta absoluta opcional de un archivo de log concreto",
    ),
    logs_path: str | None = Field(
        default=None,
        description="Ruta absoluta opcional del directorio que contiene log_name",
    ),
) -> str:
    if log_path:
        return read_log_file_tail(Path(log_path).expanduser().resolve(), lines=lines)

    target_dir = Path(logs_path).expanduser().resolve() if logs_path else logs_dir()
    return read_log_tail(target_dir, log_name=log_name, lines=lines)


@mcp.tool(
    description=(
        "Carga variables desde un archivo JSON, INI, ENV o TXT. Acepta una ruta "
        "absoluta opcional; si se omite, usa ROCKETBOT_VARIABLES_FILE."
    )
)
def get_rocketbot_variables(
    variables_path: str | None = Field(
        default=None,
        description="Ruta absoluta opcional del archivo de variables",
    ),
) -> dict[str, object]:
    target = Path(variables_path).expanduser().resolve() if variables_path else variables_file()
    return load_variables(target)


@mcp.tool(
    description=(
        "Crea un archivo .db SQLite compatible con Rocketbot en formato normal. "
        "Acepta una definición JSON con bot principal, HUs/subrobots, variables y comandos. "
        "Antes de usar módulos externos, consulta scan_rocketbot_modules_catalog y usa "
        "los nombres y parámetros reales del package.json."
    )
)
def create_rocketbot_db_file(
    output_path: str = Field(description="Ruta destino del archivo .db"),
    definition_json: Any = Field(
        description=(
            "JSON del flujo. Acepta objeto, lista o string JSON. "
            "Formato: {'bots':[...]} o una lista. "
            "Cada bot requiere 'name' y opcional 'project', 'description', 'version', 'father'."
        )
    ),
    overwrite: bool = Field(default=False, description="Sobrescribe si el archivo ya existe"),
) -> dict[str, object]:
    return create_rocketbot_db(
        output_path=output_path,
        definition_json=definition_json,
        overwrite=overwrite,
    )


@mcp.tool(
    description=(
        "Crea un archivo .db SQLite Rocketbot recibiendo directamente la lista de bots. "
        "Recomendado para Inspector y clientes MCP con una estructura Rocketbot ya compilada."
    )
)
def create_rocketbot_db_from_object(
    output_path: str = Field(description="Ruta destino del archivo .db"),
    bots: list[dict[str, Any]] = Field(description="Lista de bots a persistir"),
    overwrite: bool = Field(default=False, description="Sobrescribe si el archivo ya existe"),
) -> dict[str, object]:
    return create_rocketbot_db_from_bots(
        output_path=output_path,
        bots=bots,
        overwrite=overwrite,
    )


@mcp.tool(
    description=(
        "Lee una DB de Rocketbot desde cualquier ruta accesible y la exporta a JSON editable. "
        "Úsala para analizar bots, HUs, variables, módulos y comandos. Si está en encrypt, "
        "exporta metadatos y preview del payload."
    )
)
def export_rocketbot_db_json(
    db_path: str = Field(description="Ruta del archivo .db de Rocketbot"),
    output_json_path: str | None = Field(default=None, description="Ruta opcional para guardar el JSON exportado"),
    include_raw_data: bool = Field(default=False, description="Incluye payload completo raw"),
) -> dict[str, object]:
    return export_rocketbot_db(
        db_path=db_path,
        output_json_path=output_json_path,
        include_raw_data=include_raw_data,
    )


@mcp.tool(description="Exporta un .db de Rocketbot a Markdown para Obsidian: index, diagrams y un .md por bot/HU/subrobot.")
def export_rocketbot_db_obsidian(
    db_path: str = Field(description="Ruta del archivo .db de Rocketbot"),
    output_dir: str = Field(description="Directorio destino para notas Markdown"),
    include_raw_data: bool = Field(default=False, description="Incluye payload raw en notas de bots cifrados"),
) -> dict[str, object]:
    return export_rocketbot_db_to_obsidian(
        db_path=db_path,
        output_dir=output_dir,
        include_raw_data=include_raw_data,
    )


@mcp.tool(
    description=(
        "Escanea los package.json de Rocketbot/modules y devuelve nombres, comandos, "
        "parámetros y compatibilidad. Úsala antes de crear una DB que requiera módulos "
        "externos para evitar inventar comandos o campos."
    )
)
def scan_rocketbot_modules_catalog(
    modules_dir: str | None = Field(
        default=None,
        description=(
            "Ruta absoluta opcional de la carpeta modules. Si se omite, usa "
            "ROCKETBOT_MODULES_DIR o la autodetección."
        ),
    ),
) -> dict[str, object]:
    target = (
        Path(modules_dir).expanduser().resolve()
        if isinstance(modules_dir, str) and modules_dir.strip()
        else detected_modules_dir()
    )
    return scan_rocketbot_modules(str(target))


@mcp.tool(description="Exporta catálogo de módulos Rocketbot a JSON.")
def export_rocketbot_modules_json(
    modules_dir: str | None = Field(
        default=None,
        description="Ruta opcional de modules; si se omite usa la autodetección",
    ),
    output_json_path: str | None = Field(default=None, description="Ruta opcional de salida JSON"),
) -> dict[str, object]:
    target = (
        Path(modules_dir).expanduser().resolve()
        if isinstance(modules_dir, str) and modules_dir.strip()
        else detected_modules_dir()
    )
    return export_module_catalog_json(
        modules_dir=str(target),
        output_json_path=(
            output_json_path
            if isinstance(output_json_path, str) and output_json_path.strip()
            else None
        ),
    )


@mcp.tool(description="Exporta catálogo de módulos Rocketbot a Markdown para Obsidian.")
def export_rocketbot_modules_obsidian(
    output_dir: str = Field(description="Directorio destino para notas Markdown"),
    modules_dir: str | None = Field(
        default=None,
        description="Ruta opcional de modules; si se omite usa la autodetección",
    ),
) -> dict[str, object]:
    target = (
        Path(modules_dir).expanduser().resolve()
        if isinstance(modules_dir, str) and modules_dir.strip()
        else detected_modules_dir()
    )
    return export_module_catalog_obsidian(
        modules_dir=str(target),
        output_dir=output_dir,
    )


@mcp.resource("rocketbot://paths", mime_type="application/json")
def rocketbot_paths_resource() -> str:
    return json.dumps(describe_paths(), ensure_ascii=False, indent=2)


@mcp.resource("rocketbot://variables", mime_type="application/json")
def rocketbot_variables_resource() -> str:
    return json.dumps(load_variables(variables_file()), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower() or "stdio"
    mcp.run(transport=transport)
