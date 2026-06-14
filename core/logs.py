from __future__ import annotations

from pathlib import Path

from core.file_reader import resolve_project_path


TAIL_CHUNK_SIZE = 8192
MAX_TAIL_BYTES = 5_000_000


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
    if lines < 1:
        return ""

    chunks: list[bytes] = []
    bytes_read = 0
    newline_count = 0

    with log_path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()

        while position > 0 and newline_count <= lines and bytes_read < MAX_TAIL_BYTES:
            read_size = min(TAIL_CHUNK_SIZE, position, MAX_TAIL_BYTES - bytes_read)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            bytes_read += len(chunk)
            newline_count += chunk.count(b"\n")

    content = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return "\n".join(content.splitlines()[-lines:])


def read_log_tail(logs_path: Path, log_name: str | None = None, lines: int = 200) -> str:
    if not logs_path.exists():
        raise FileNotFoundError(f"No existe directorio de logs: {logs_path}")
    if not logs_path.is_dir():
        raise ValueError(f"No es directorio: {logs_path}")

    if log_name:
        target = resolve_project_path(logs_path, log_name)
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
