# MCP Rocketbot

Servidor MCP en Python para:

- inspeccionar instalaciones y proyectos Rocketbot
- leer logs y variables
- crear y exportar archivos `.db`
- documentar bots y módulos en Obsidian

## Requisitos

- Python `>=3.10`
- Rocketbot Studio instalado
- acceso a proyectos, logs y variables de Rocketbot

## Instalación

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

### Git Bash

```bash
py -3.12 -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
pip install -e .
```

Dependencias del proyecto:

- `mcp[cli]>=1.8.0`
- `pydantic>=2.7.0`
- `python-dotenv>=1.0.1`

## Configuración

Crear `.env` desde `.env.example`.

```powershell
Copy-Item .env.example .env
```

Variables:

```env
ROCKETBOT_HOME=
ROCKETBOT_PROJECTS_DIR=
ROCKETBOT_LOGS_DIR=
ROCKETBOT_VARIABLES_FILE=
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8000
MCP_SSE_PATH=/sse
MCP_STREAMABLE_HTTP_PATH=/mcp
```

Notas:

- `mcp_server.py` sí respeta `MCP_TRANSPORT`
- `main.py` fuerza `stdio`
- no subir `.env`
- no subir `.venv`

## Ejecutar servidor

### Local `stdio`

```powershell
.\.venv\Scripts\python.exe mcp_server.py
```

### HTTP `streamable-http`

En `.env`:

```env
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8000
MCP_STREAMABLE_HTTP_PATH=/mcp
```

Ejecutar:

```powershell
.\.venv\Scripts\python.exe mcp_server.py
```

Endpoint:

```text
http://127.0.0.1:8000/mcp
```

### Inspector MCP

```powershell
.\.venv\Scripts\mcp.exe dev mcp_server.py
```

## Smoke test local

```powershell
.\.venv\Scripts\python.exe mcp_client.py
```

Qué hace:

- conecta por `stdio`
- lista tools
- lista resources
- lee `rocketbot://paths`

## Consumo

El usuario conversa con el agente del IDE. El agente interpreta el prompt y llama
las tools MCP con JSON. No es necesario editar ni llamar directamente
`mcp_server.py`.

### Analizar una DB existente

Prompt de ejemplo:

```text
Usa el MCP Rocketbot.

Toma esta DB:
C:\Bots\Facturacion\facturacion.db

1. Ejecuta export_rocketbot_db_json con include_raw_data=false.
2. Analiza los bots, subrobots, variables, módulos y comandos.
3. Resume el flujo por HU.
4. Señala módulos faltantes, variables sin uso y posibles errores.
5. Exporta la documentación a:
C:\Bots\Facturacion\documentacion

Usa export_rocketbot_db_obsidian para generar la documentación.
```

La ruta de la DB puede estar en cualquier carpeta accesible para el usuario que
ejecuta el MCP.

### Crear una DB desde un requerimiento

Prompt de ejemplo:

```text
Usa el MCP Rocketbot para crear:
C:\Bots\Salida\GestionCorreos.db

La instalación de módulos está en:
C:\Rocketbot\modules

Requerimiento:
- Crear un bot principal llamado main.
- HU01: conectarse a Microsoft 365 y obtener correos no leídos.
- HU02: leer cada correo y guardar asunto, remitente y contenido.
- HU03: abrir el portal https://portal.ejemplo.com.
- HU04: escribir el dato extraído en el formulario y enviarlo.
- HU05: enviar un correo con el resultado.

Antes de construir el flujo:
1. Ejecuta scan_rocketbot_modules_catalog sobre C:\Rocketbot\modules.
2. Usa los nombres, comandos y campos reales encontrados en package.json.
3. No inventes módulos ni parámetros.
4. Separa cada HU en un subrobot.
5. Crea variables con la convención v<Scope><Type><Nombre>.
6. Haz que main ejecute las HU en orden.
7. Genera la DB con create_rocketbot_db_file y overwrite=true.
8. Exporta la DB creada a JSON para verificar el resultado.
9. Informa bots creados, módulos usados y ruta final.
```

El agente debería ejecutar este flujo:

1. `scan_rocketbot_modules_catalog`
2. construir el objeto JSON con `main`, HUs, variables y comandos
3. `create_rocketbot_db_file`
4. `export_rocketbot_db_json`

Tipos de acción simplificados soportados:

- `set_variable`
- `exec_subrobot`
- `open_browser`
- `wait_for_object`
- `click`
- `write_input`
- `db_connect`
- `read_file`
- `create_folder`
- `o365_connect`
- `o365_get_all_emails`
- `o365_read_email`
- `o365_send_email`

Otros comandos pueden generarse como módulos genéricos, pero deben construirse
con los valores reales del `package.json` del módulo.

### Desde Inspector MCP

Ejemplo `get_rocketbot_paths`:

```json
{}
```

Ejemplo `list_project_files`:

```json
{
  "project_name": "MiProyecto"
}
```

Ejemplo `read_project_file`:

```json
{
  "project_name": "MiProyecto",
  "relative_path": "main.robot",
  "max_chars": 20000
}
```

### Crear `.db` desde JSON

Tool: `create_rocketbot_db_from_object`

```json
{
  "output_path": "C:/temp/robot.db",
  "overwrite": true,
  "bots": [
    {
      "name": "main",
      "description": "Flujo base",
      "version": "1.0.0",
      "project": {
        "project": {
          "commands": [],
          "ifs": [],
          "modules": [],
          "vars": [],
          "profile": {
            "name": "main",
            "description": "Flujo base"
          }
        }
      }
    }
  ]
}
```

### Exportar `.db` a JSON

Tool: `export_rocketbot_db_json`

```json
{
  "db_path": "C:/temp/robot.db",
  "output_json_path": "C:/temp/robot.json",
  "include_raw_data": false
}
```

### Exportar `.db` a Obsidian

Tool: `export_rocketbot_db_obsidian`

```json
{
  "db_path": "C:/temp/robot.db",
  "output_dir": "C:/temp/obsidian/robot",
  "include_raw_data": false
}
```

## Tools disponibles

- `get_rocketbot_paths`
- `list_projects`
- `list_project_files`
- `read_project_file`
- `search_in_project`
- `list_rocketbot_logs`
- `read_rocketbot_log`
- `get_rocketbot_variables`
- `create_rocketbot_db_file`
- `create_rocketbot_db_from_object`
- `export_rocketbot_db_json`
- `export_rocketbot_db_obsidian`
- `scan_rocketbot_modules_catalog`
- `export_rocketbot_modules_json`
- `export_rocketbot_modules_obsidian`

## Resources

- `rocketbot://paths`
- `rocketbot://variables`
