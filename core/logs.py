from __future__ import annotations

from pathlib import Path

from core.file_reader import read_text_file


def list_log_files(logs_path: Path) -> list[str]:
    if not logs_path.exists():
        return []
    return sorted(str(path.name) for path in logs_path.glob("*.log") if path.is_file())


def read_log_tail(logs_path: Path, log_name: str | None = None, lines: int = 200) -> str:
    if not logs_path.exists():
        raise FileNotFoundError(f"No existe directorio de logs: {logs_path}")

    if log_name:
        target = logs_path / log_name
    else:
        candidates = sorted(
            (path for path in logs_path.glob("*.log") if path.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError("No hay logs .log disponibles")
        target = candidates[0]

    content = read_text_file(target, max_chars=200_000)
    return "\n".join(content.splitlines()[-lines:])
