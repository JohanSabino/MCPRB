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

## Subir a GitHub

`.gitignore` ya excluye:

- `.env`
- `.venv/`
- `__pycache__/`
- `*.pyc`
- `dist/`
- `build/`
- `*.egg-info/`

Si todavía no existe repo remoto:

1. crear repo vacío en GitHub
2. copiar la URL HTTPS o SSH
3. ejecutar:

```powershell
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <URL_DEL_REPO>
git push -u origin main
```

Si ya existe repo remoto:

```powershell
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <URL_DEL_REPO>
git push -u origin main
```

## Seguridad

- no versionar `.env`
- no pegar credenciales en issues, README o ejemplos
- usar `include_raw_data=false` salvo necesidad real
- exportar `.db`, JSON y Obsidian fuera del repo si contienen datos sensibles
