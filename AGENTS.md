# AGENTS.md

## Alcance rápido
- Este repo es un servidor MCP en Python para inspeccionar instalaciones/proyectos de Rocketbot Studio, leer logs/variables, crear/exportar `.db` Rocketbot y generar documentación Obsidian.
- La entrada real es `mcp_server.py`. `main.py` solo lanza `stdio` fijo; si necesitas respetar `MCP_TRANSPORT`, ejecuta `mcp_server.py` directamente.

## Comandos verificados
- Crear entorno e instalar en editable: `py -3.12 -m venv .venv` -> `.\.venv\Scripts\activate` -> `pip install -e .`
- Servidor MCP por stdio: `.\.venv\Scripts\python.exe mcp_server.py`
- Inspector MCP: `.\.venv\Scripts\mcp.exe dev mcp_server.py`
- Cliente de smoke test: `.\.venv\Scripts\python.exe mcp_client.py`
- HTTP/streamable transport: define `MCP_TRANSPORT=streamable-http` en `.env` y luego ejecuta `mcp_server.py`.

## Estructura que importa
- `mcp_server.py`: registra tools/resources y carga `.env` al importar.
- `core/paths.py`: autodetecta `ROCKETBOT_HOME`, proyectos, logs y variables; si el entorno no está claro, empieza aquí.
- `core/file_reader.py`: protege contra path traversal; no reemplaces `resolve_project_path`/`ensure_within` por joins manuales.
- `core/db_builder.py`: fuente real para el formato `.db`; hoy solo soporta `data_type="normal"` al crear y no reconstruye `encrypt`.
- `core/obsidian_exporter.py` y `core/module_catalog.py`: generan archivos Markdown/JSON y crean directorios destino si no existen.

## Lógica Rocketbot que el agente debe respetar
- Para dudas de semántica de Rocketbot Studio, comandos, módulos o estructura de bots, consulta primero fuentes oficiales de Rocketbot antes de asumir: `https://docs.rocketbot.com/` (manual/docs) y `https://rocketbot.com/en/studio-rpa/` o `https://rocketbot.com/en/rpa-studio-landing/` (producto).
- En este repo, `package.json` de cada módulo Rocketbot es la fuente principal para catálogo de módulos; un `.db` real se usa para verificar la serialización final de `project.commands`.
- El generador `.db` usa `data` como `base64(json)` para bots `normal`.
- La DSL simplificada en `core/db_builder.py` ya mapea varios tipos (`set_variable`, `open_browser`, `click`, `write_input`, `db_connect`, `o365_*`, etc.); si agregas otro, modifica el router `_build_action` en vez de serializarlo ad hoc en varios sitios.
- La convención de variables Rocketbot documentada en `README.md` (`v<Scope><Type><Nombre>`) afecta la inferencia de tipos en `_infer_var_type`; no cambies nombres de ejemplo sin revisar ese comportamiento.

## Verificación práctica
- No hay configuración verificada de `pytest`, `ruff`, `mypy`, CI ni pre-commit en el repo actual.
- Después de cambios funcionales, usa al menos un smoke test real: `mcp_client.py` para stdio o `mcp dev mcp_server.py` para probar tools manualmente.
- Si cambias transporte HTTP, verifica el endpoint configurado por `MCP_STREAMABLE_HTTP_PATH` (por defecto `/mcp`).

## Seguridad y manejo de datos
- `.env` está ignorado; no lo sobrescribas con valores reales ni copies secretos al repo.
- Tools como `get_rocketbot_variables`, lectura de logs y exportaciones `.db` pueden exponer credenciales, tokens, rutas internas y datos de negocio: minimiza lecturas, no pegues secretos completos en respuestas y prefiere resumir.
- Mantén `include_raw_data=false` salvo que sea estrictamente necesario; el payload raw de bots cifrados puede contener datos sensibles.
- Escribe `.db`, JSON exportados y notas Obsidian en rutas temporales o externas al repo salvo que el usuario pida versionarlas explícitamente.
