from __future__ import annotations

from pathlib import Path

from core.file_reader import read_text_file


def list_log_files(logs_path: Path) -> list[str]:
    if not logs_path.exists():
        return []
    if not logs_path.is_dir():
        raise ValueError(f"No es directorio: {logs_path}")
    return sorted(str(path.name) for path in logs_path.glob("*.log") if path.is_file())


def read_log_file_tail(log_path: Path, lines: int = 200) -> str:
    if not log_path.exists():
        raise FileNotFoundError(f"No existe archivo de log: {log_path}")
    if not log_path.is_file():
        raise ValueError(f"No es archivo: {log_path}")

    content = read_text_file(log_path, max_chars=200_000)
    return "\n".join(content.splitlines()[-lines:])


def read_log_tail(logs_path: Path, log_name: str | None = None, lines: int = 200) -> str:
    if not logs_path.exists():
        raise FileNotFoundError(f"No existe directorio de logs: {logs_path}")
    if not logs_path.is_dir():
        raise ValueError(f"No es directorio: {logs_path}")

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

    return read_log_file_tail(target, lines=lines)
