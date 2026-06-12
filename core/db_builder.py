from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


SCHEMA_SQL = """
CREATE TABLE bots (
    id INTEGER PRIMARY KEY,
    name TEXT,
    data TEXT,
    created_at TIMESTAMP DEFAULT null,
    data_type TEXT DEFAULT 'normal',
    description TEXT DEFAULT null,
    version TEXT DEFAULT null,
    father TEXT DEFAULT null
)
"""


@dataclass
class BotDefinition:
    name: str
    project: dict[str, Any]
    description: str = ""
    version: str = ""
    father: str = ""
    created_at: str | None = None
    data_type: str = "normal"
    id: int | None = None


def _default_project(name: str) -> dict[str, Any]:
    return {
        "project": {
            "commands": [],
            "ifs": [],
            "modules": [],
            "profile": {
                "name": name,
                "description": "",
                "log_destination": "db_path",
                "deactivate_log": False,
                "log_path": "",
            },
            "vars": [],
            "expose": [],
        }
    }


def _normalize_project_payload(name: str, project: dict[str, Any] | None) -> dict[str, Any]:
    payload = _default_project(name)
    if not project:
        return payload

    if "project" in project and isinstance(project["project"], dict):
        merged = payload["project"]
        merged.update(project["project"])
        profile = dict(payload["project"].get("profile", {}))
        profile.update(merged.get("profile", {}))
        merged["profile"] = profile
        payload["project"] = merged
        return payload

    merged = payload["project"]
    merged.update(project)
    profile = dict(payload["project"].get("profile", {}))
    profile.update(merged.get("profile", {}))
    merged["profile"] = profile
    payload["project"] = merged
    return payload


def _encode_normal_payload(project: dict[str, Any]) -> str:
    raw = json.dumps(project, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_normal_payload(data: str) -> dict[str, Any]:
    decoded = base64.b64decode(data.encode("ascii"))
    return json.loads(decoded.decode("utf-8"))


def parse_db_definition(definition_json: str | dict[str, Any] | list[Any]) -> list[BotDefinition]:
    if isinstance(definition_json, str):
        parsed = json.loads(definition_json)
    else:
        parsed = definition_json

    # Algunos clientes MCP pueden anidar el payload completo de la tool
    # dentro de `definition_json`. Desenrollamos ese caso aquí.
    if isinstance(parsed, dict) and "definition_json" in parsed and "bots" not in parsed:
        nested = parsed.get("definition_json")
        if isinstance(nested, str):
            parsed = json.loads(nested)
        else:
            parsed = nested

    if isinstance(parsed, dict) and "bots" in parsed:
        items = parsed["bots"]
    elif isinstance(parsed, list):
        items = parsed
    else:
        items = [parsed]

    if not isinstance(items, list) or not items:
        raise ValueError("La definición debe incluir una lista no vacía de bots")

    bots: list[BotDefinition] = []

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Bot inválido en posición {index}")

        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError(f"Falta 'name' en bot #{index}")

        data_type = str(item.get("data_type", "normal")).strip() or "normal"
        if data_type != "normal":
            raise ValueError("Solo se soporta data_type='normal'")

        project = _normalize_project_payload(name, item.get("project"))
        project["project"]["profile"]["name"] = name

        bots.append(
            BotDefinition(
                id=item.get("id"),
                name=name,
                project=project,
                description=str(item.get("description", "")),
                version=str(item.get("version", "")),
                father=str(item.get("father", "")),
                created_at=item.get("created_at"),
                data_type=data_type,
            )
        )

    return bots


def _new_id() -> str:
    return str(uuid4())


def _infer_var_type(name: str, value: Any) -> str:
    if name.startswith("vLocBoo") or name.startswith("vGblBoo") or isinstance(value, bool):
        return "boolean"
    if name.startswith("vLocInt") or name.startswith("vGblInt") or (isinstance(value, int) and not isinstance(value, bool)):
        return "int"
    if name.startswith("vLocDec") or name.startswith("vGblDec") or isinstance(value, float):
        return "float"
    if name.startswith("vLocLst") or name.startswith("vGblLst") or isinstance(value, list):
        return "list"
    if name.startswith("vLocObj") or name.startswith("vGblObj") or isinstance(value, dict):
        return "dict"
    return "string"


def _serialize_var_value(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value if value is not None else ""
    return json.dumps(value, ensure_ascii=False)


def _build_var(item: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(item.get("name", "")).strip()
    value = item.get("value", "")
    return {
        "name": name,
        "data": _serialize_var_value(value),
        "type": _infer_var_type(name, value),
        "category": str(item.get("category", "")),
        "status": str(item.get("status", "0")),
        "constant": bool(item.get("constant", False)),
        "defaultValue": item.get("defaultValue", ""),
        "disabled": bool(item.get("disabled", False)),
        "index": index,
        "id": str(item.get("id", _new_id())),
    }


def _command_base(
    father: str,
    command: str,
    group: str,
    index: int,
    line: str | int,
    description: str = "",
) -> dict[str, Any]:
    return {
        "father": father,
        "command": command,
        "index": index,
        "execute_debugg": 0,
        "img": "",
        "screenshot": "",
        "line": line,
        "description": description,
        "stop_onerror": False,
        "run_onerror": False,
        "stop_robot_onerror": False,
        "run_onerror_robot": "",
        "run_when": "True",
        "id": _new_id(),
        "group": group,
        "mode_live": False,
        "children": [],
        "else": [],
        "execute": 2,
        "message": "",
        "time": "0",
        "extra": [],
    }


def _build_set_var(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="setVar",
        command=repr(action.get("value", "")),
        group="system",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["var"] = str(action.get("variable", ""))
    return cmd


def _build_exec_bot(bot_name: str, index: int, line: str | int, description: str = "") -> dict[str, Any]:
    return _command_base(
        father="execRocketBotDB",
        command=bot_name,
        group="scripts",
        index=index,
        line=line,
        description=description,
    )


def _build_module_command(
    module_name: str,
    module: str,
    payload: dict[str, Any],
    index: int,
    line: str | int,
    description: str = "",
    group: str = "scripts",
) -> dict[str, Any]:
    serialized = dict(payload)
    serialized["module_name"] = module_name
    serialized["module"] = module
    cmd = _command_base(
        father="module",
        command=json.dumps(serialized, ensure_ascii=False, separators=(",", ":")),
        group=group,
        index=index,
        line=line,
        description=description,
    )
    cmd["module"] = module
    return cmd


def _build_open_browser(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="openbrowser",
        command=json.dumps(
            {
                "url": str(action.get("url", "")),
                "id_driver": str(action.get("id_driver", "")),
                "profile": str(action.get("profile", "")),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        group="web",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["option"] = str(action.get("browser", action.get("option", "chrome")))
    return cmd


def _build_wait_for_object(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="waitforobject",
        command=json.dumps(
            {
                "object": str(action.get("object", action.get("selector", ""))),
                "wait_time": str(action.get("wait_time", "30")),
                "wait_for": str(action.get("wait_for", "present")),
                "before": str(action.get("before", "")),
                "after": str(action.get("after", "")),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        group="web",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["getvar"] = str(action.get("result_var", action.get("getvar", "")))
    cmd["option"] = str(action.get("selector_type", action.get("option", "xpath")))
    return cmd


def _build_click_web(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    return _command_base(
        father="click_web",
        command=json.dumps(
            {
                "data": str(action.get("selector", action.get("data", ""))),
                "data_type": str(action.get("selector_type", action.get("data_type", "xpath"))),
                "wait_time": str(action.get("wait_time", "10")),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        group="web",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_sendkey_web(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    return _command_base(
        father="sendkey_web",
        command=json.dumps(
            {
                "data": str(action.get("selector", action.get("data", ""))),
                "data_type": str(action.get("selector_type", action.get("data_type", "xpath"))),
                "text": str(action.get("value", action.get("text", ""))),
                "wait_time": str(action.get("wait_time", "10")),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        group="web",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_db_connect(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="connect",
        command=json.dumps(
            {
                "host": action.get("host", ""),
                "port": action.get("port", 3306),
                "database": action.get("database", ""),
                "user": action.get("user", ""),
                "password": action.get("password", ""),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        group="db",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["disabled"] = bool(action.get("disabled", False))
    cmd["getvar"] = str(action.get("result_var", action.get("getvar", "db_connection")))
    return cmd


def _build_read_file(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    return _build_module_command(
        module_name=str(action.get("module_name", "Files")),
        module="readFile",
        payload={
            "file_": str(action.get("path", action.get("file_", ""))),
            "var_": str(action.get("result_var", action.get("var_", ""))),
        },
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_create_folder(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    return _build_module_command(
        module_name=str(action.get("module_name", "Files")),
        module="createFolder",
        payload={
            "path": str(action.get("path", "")),
            "var_": str(action.get("result_var", action.get("var_", ""))),
        },
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_o365_connect(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    return _build_module_command(
        module_name="O365",
        module="connect",
        payload={
            "client_id": str(action.get("client_id", "")),
            "client_secret": str(action.get("client_secret", "")),
            "tenant": str(action.get("tenant", "")),
            "session": str(action.get("session", "1")),
            "res": str(action.get("result_var", action.get("res", "res_cont"))),
        },
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_o365_get_all_emails(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    return _build_module_command(
        module_name="O365",
        module="getAllEmails",
        payload={
            "limit": str(action.get("limit", "1")),
            "res": str(action.get("result_var", action.get("res", "mails"))),
            "session": str(action.get("session", "1")),
        },
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_o365_read_email(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    return _build_module_command(
        module_name="O365",
        module="readEmail",
        payload={
            "id_": str(action.get("email_id", action.get("id_", ""))),
            "not_parsed": bool(action.get("not_parsed", True)),
            "raw": bool(action.get("raw", True)),
            "res": str(action.get("result_var", action.get("res", "read_mail"))),
            "session": str(action.get("session", "1")),
        },
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_o365_send_email(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    payload = {
        "to_": str(action.get("to", action.get("to_", ""))),
        "subject": str(action.get("subject", "")),
        "session": str(action.get("session", "1")),
    }
    body = action.get("body", action.get("body_", ""))
    if body != "":
        payload["body_"] = str(body)
    cc = action.get("cc", action.get("cc_", ""))
    if cc != "":
        payload["cc_"] = str(cc)
    bcc = action.get("bcc", action.get("bcc_", ""))
    if bcc != "":
        payload["bcc_"] = str(bcc)
    return _build_module_command(
        module_name="O365",
        module="sendEmail",
        payload=payload,
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_generic_module(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    action_type = str(action.get("type", "customModule"))
    params = action.get("params", {})
    if params is not None and not isinstance(params, dict):
        raise ValueError("params debe ser un objeto JSON")

    ignored = {"type", "description", "group", "params"}
    payload = {key: value for key, value in action.items() if key not in ignored}
    payload.update(params or {})
    module_name = str(action.get("module_name", "")).strip()
    module_command = str(
        action.get("module") or (action_type if action_type != "module" else "")
    ).strip()
    payload["module"] = module_command
    payload["module_name"] = module_name
    if not module_name or not module_command:
        raise ValueError("Los módulos externos requieren module_name y module")

    cmd = _command_base(
        father="module",
        command=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        group=str(action.get("group", "scripts")),
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["module"] = str(payload["module"])
    return cmd


def _build_nested_actions(
    actions: Any,
    parent_line: str | int | None = None,
) -> list[dict[str, Any]]:
    if actions is None:
        return []
    if not isinstance(actions, list):
        raise ValueError("Las acciones anidadas deben ser una lista")

    commands: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Cada acción debe ser un objeto JSON")

        index = len(commands)
        line = f"{parent_line}.{index + 1}" if parent_line is not None else index + 1
        commands.append(_build_action(action, index=index, line=line))

        action_type = str(action.get("type", "")).strip().lower()
        finally_actions = action.get("finally")
        if action_type in {"try", "try_catch", "trycatch"} and finally_actions:
            finally_index = len(commands)
            finally_line = (
                f"{parent_line}.{finally_index + 1}"
                if parent_line is not None
                else finally_index + 1
            )
            commands.append(
                _build_finally(
                    {"body": finally_actions, "description": action.get("finally_description", "")},
                    index=finally_index,
                    line=finally_line,
                )
            )

    return commands


def _build_if(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="evaluateIf",
        command=str(action.get("condition", action.get("command", ""))),
        group="logic",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["children"] = _build_nested_actions(
        action.get("then", action.get("children", [])),
        parent_line=line,
    )
    cmd["else"] = _build_nested_actions(action.get("else", []), parent_line=line)
    return cmd


def _build_for(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="for",
        command=json.dumps(
            {
                "iterable": str(action.get("iterable", "")),
                "count": int(action.get("count", 0)),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        group="logic",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["children"] = _build_nested_actions(
        action.get("body", action.get("children", [])),
        parent_line=line,
    )
    return cmd


def _build_try_catch(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="trycatch",
        command="",
        group="logic",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["children"] = _build_nested_actions(
        action.get("try", action.get("children", [])),
        parent_line=line,
    )
    cmd["else"] = _build_nested_actions(
        action.get("catch", action.get("else", [])),
        parent_line=line,
    )
    return cmd


def _build_finally(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    cmd = _command_base(
        father="finally",
        command="",
        group="logic",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )
    cmd["children"] = _build_nested_actions(
        action.get("body", action.get("children", [])),
        parent_line=line,
    )
    return cmd


def _build_loop_control(
    action: dict[str, Any],
    index: int,
    line: str | int,
    father: str,
) -> dict[str, Any]:
    return _command_base(
        father=father,
        command="",
        group="logic",
        index=index,
        line=line,
        description=str(action.get("description", "")),
    )


def _build_action(action: dict[str, Any], index: int, line: str | int) -> dict[str, Any]:
    action_type = str(action.get("type", "")).strip().lower()
    if action_type == "set_variable":
        return _build_set_var(action, index=index, line=line)
    if action_type in {"exec_subrobot", "exec_robot", "exec_rocketbot_db"}:
        return _build_exec_bot(
            bot_name=str(action.get("name", action.get("bot_name", action.get("command", "")))),
            index=index,
            line=line,
            description=str(action.get("description", "")),
        )
    if action_type == "open_browser":
        return _build_open_browser(action, index=index, line=line)
    if action_type in {"wait_for_object", "wait_object"}:
        return _build_wait_for_object(action, index=index, line=line)
    if action_type == "click":
        return _build_click_web(action, index=index, line=line)
    if action_type in {"write_input", "send_keys_web"}:
        return _build_sendkey_web(action, index=index, line=line)
    if action_type == "db_connect":
        return _build_db_connect(action, index=index, line=line)
    if action_type == "read_file":
        return _build_read_file(action, index=index, line=line)
    if action_type == "create_folder":
        return _build_create_folder(action, index=index, line=line)
    if action_type == "o365_connect":
        return _build_o365_connect(action, index=index, line=line)
    if action_type in {"get_all_emails", "o365_get_all_emails"}:
        return _build_o365_get_all_emails(action, index=index, line=line)
    if action_type in {"read_email", "o365_read_email"}:
        return _build_o365_read_email(action, index=index, line=line)
    if action_type in {"send_email", "o365_send_email"}:
        return _build_o365_send_email(action, index=index, line=line)
    if action_type in {"if", "condition", "evaluate_if"}:
        return _build_if(action, index=index, line=line)
    if action_type in {"for", "foreach"}:
        return _build_for(action, index=index, line=line)
    if action_type in {"try", "try_catch", "trycatch"}:
        return _build_try_catch(action, index=index, line=line)
    if action_type == "finally":
        return _build_finally(action, index=index, line=line)
    if action_type in {"break", "continue"}:
        return _build_loop_control(
            action,
            index=index,
            line=line,
            father=action_type,
        )
    if action_type == "module" or action.get("module_name") or action.get("module"):
        return _build_generic_module(action, index=index, line=line)
    raise ValueError(
        f"Tipo de acción no soportado: {action_type or '<vacío>'}. "
        "Para módulos externos incluye module_name y module."
    )


def _compile_dsl_bot(item: dict[str, Any], index: int) -> BotDefinition:
    name = str(item.get("name", "")).strip()
    description = str(item.get("description", ""))
    version = str(item.get("version", ""))

    project = _default_project(name)
    root = project["project"]

    declared_commands = item.get("project", {}).get("project", {}).get("commands", [])
    declared_modules = item.get("project", {}).get("project", {}).get("modules", [])
    declared_vars = item.get("project", {}).get("project", {}).get("vars", [])
    declared_profile = item.get("project", {}).get("project", {}).get("profile", {})

    module_names = []
    for step_index, command in enumerate(declared_commands):
        if isinstance(command, dict) and str(command.get("type")) == "module":
            module_name = str(command.get("name", "")).strip()
            if module_name:
                module_names.append(module_name)
                root["commands"].append(
                    _build_exec_bot(
                        bot_name=module_name,
                        index=step_index,
                        line=step_index + 1,
                        description=str(command.get("description", "")),
                    )
                )

    root["modules"] = [
        {
            "name": str(module.get("name", "")),
            "status": str(module.get("status", "Installed")),
            "version": str(module.get("version", version or "1.0.0")),
            "last_version": str(module.get("last_version", version or "1.0.0")),
        }
        for module in declared_modules
        if isinstance(module, dict) and module.get("name")
    ]

    root["vars"] = [
        _build_var(var_item, var_index + 1)
        for var_index, var_item in enumerate(declared_vars)
        if isinstance(var_item, dict) and str(var_item.get("name", "")).strip()
    ]

    profile = dict(root["profile"])
    if isinstance(declared_profile, dict):
        profile.update(declared_profile)
    profile["name"] = name
    if description and not profile.get("description"):
        profile["description"] = description
    root["profile"] = profile

    return BotDefinition(
        id=item.get("id", index),
        name=name,
        project=project,
        description=description,
        version=version,
        father=str(item.get("father", "")),
        created_at=item.get("created_at"),
        data_type="normal",
    )


def _compile_dsl_subbots(item: dict[str, Any], start_id: int) -> list[BotDefinition]:
    root_project = item.get("project", {}).get("project", {})
    modules = root_project.get("modules", [])
    vars_ = root_project.get("vars", [])
    version = str(item.get("version", ""))
    compiled: list[BotDefinition] = []

    for offset, module in enumerate(modules, start=0):
        if not isinstance(module, dict):
            continue
        name = str(module.get("name", "")).strip()
        if not name:
            continue

        project = _default_project(name)
        root = project["project"]
        root["modules"] = []
        root["ifs"] = []
        root["expose"] = []
        root["vars"] = [
            _build_var(var_item, var_index + 1)
            for var_index, var_item in enumerate(vars_)
            if isinstance(var_item, dict) and str(var_item.get("name", "")).strip()
        ]
        root["profile"]["name"] = name
        root["profile"]["description"] = str(module.get("description", ""))

        actions = module.get("commands", [])
        if isinstance(actions, list):
            root["commands"].extend(_build_nested_actions(actions))

        compiled.append(
            BotDefinition(
                id=start_id + offset,
                name=name,
                project=project,
                description=str(module.get("description", "")),
                version=version,
                father="",
                created_at=item.get("created_at"),
                data_type="normal",
            )
        )

    return compiled


def compile_definition_to_bots(definition_json: str | dict[str, Any] | list[Any]) -> list[BotDefinition]:
    parsed = parse_db_definition(definition_json)
    compiled: list[BotDefinition] = []

    next_id = 1
    for bot in parsed:
        bot_dict = {
            "id": bot.id,
            "name": bot.name,
            "description": bot.description,
            "version": bot.version,
            "father": bot.father,
            "created_at": bot.created_at,
            "project": bot.project,
        }
        root_project = bot.project.get("project", {})
        declared_modules = root_project.get("modules", [])
        declared_commands = root_project.get("commands", [])

        is_dsl = (
            isinstance(declared_modules, list)
            and declared_modules
            and any(isinstance(item, dict) and "commands" in item for item in declared_modules)
            and isinstance(declared_commands, list)
            and any(isinstance(item, dict) and str(item.get("type")) == "module" for item in declared_commands)
        )

        if is_dsl:
            main_bot = _compile_dsl_bot(bot_dict, next_id)
            compiled.append(main_bot)
            next_id += 1
            subbots = _compile_dsl_subbots(bot_dict, next_id)
            compiled.extend(subbots)
            next_id += len(subbots)
        else:
            if bot.id is None:
                bot.id = next_id
            compiled.append(bot)
            next_id += 1

    return compiled


def create_rocketbot_db(
    output_path: str,
    definition_json: str | dict[str, Any] | list[Any],
    overwrite: bool = False,
) -> dict[str, Any]:
    destination = Path(output_path).expanduser().resolve()

    if destination.exists() and not overwrite:
        raise FileExistsError(f"El archivo ya existe: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    bots = compile_definition_to_bots(definition_json)

    connection = sqlite3.connect(destination)
    try:
        cursor = connection.cursor()
        cursor.execute(SCHEMA_SQL)

        inserted: list[dict[str, Any]] = []

        for sequence, bot in enumerate(bots, start=1):
            created_at = bot.created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            encoded_data = _encode_normal_payload(bot.project)
            bot_id = bot.id if bot.id is not None else sequence

            cursor.execute(
                """
                INSERT INTO bots (
                    id, name, data, created_at, data_type, description, version, father
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_id,
                    bot.name,
                    encoded_data,
                    created_at,
                    bot.data_type,
                    bot.description,
                    bot.version,
                    bot.father,
                ),
            )

            inserted.append(
                {
                    "id": bot_id,
                    "name": bot.name,
                    "data_type": bot.data_type,
                    "description": bot.description,
                    "version": bot.version,
                    "father": bot.father,
                }
            )

        connection.commit()
    finally:
        connection.close()

    return {
        "output_path": str(destination),
        "bots_created": len(bots),
        "bots": inserted,
    }


def create_rocketbot_db_from_bots(
    output_path: str,
    bots: list[dict[str, Any]],
    overwrite: bool = False,
) -> dict[str, Any]:
    return create_rocketbot_db(
        output_path=output_path,
        definition_json={"bots": bots},
        overwrite=overwrite,
    )


def export_rocketbot_db(
    db_path: str,
    output_json_path: str | None = None,
    include_raw_data: bool = False,
) -> dict[str, Any]:
    source = Path(db_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"No existe: {source}")

    connection = sqlite3.connect(source)
    try:
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            SELECT id, name, data, created_at, data_type, description, version, father
            FROM bots
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()

    bots: list[dict[str, Any]] = []

    for row in rows:
        bot_id, name, data, created_at, data_type, description, version, father = row
        item: dict[str, Any] = {
            "id": bot_id,
            "name": name or "",
            "created_at": created_at or "",
            "data_type": data_type or "",
            "description": description or "",
            "version": version or "",
            "father": father or "",
        }

        if (data_type or "") == "normal":
            try:
                item["project"] = _decode_normal_payload(data or "")
            except Exception as exc:
                item["project_decode_error"] = str(exc)
                if include_raw_data:
                    item["raw_data"] = data or ""
        else:
            item["project"] = None
            item["encrypted"] = True
            item["raw_data_preview"] = (data or "")[:200]
            item["raw_data_length"] = len(data or "")
            if include_raw_data:
                item["raw_data"] = data or ""

        bots.append(item)

    exported = {
        "source_db": str(source),
        "bots_count": len(bots),
        "bots": bots,
    }

    if output_json_path:
        destination = Path(output_json_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(exported, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        exported["output_json_path"] = str(destination)

    return exported
