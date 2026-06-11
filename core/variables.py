from __future__ import annotations

import json
from pathlib import Path


def _parse_key_value_lines(content: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_variables(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    if not path.is_file():
        raise ValueError(f"No es archivo: {path}")

    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".json":
        parsed = json.loads(content or "{}")
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("El JSON de variables debe ser un objeto")

    return _parse_key_value_lines(content)
