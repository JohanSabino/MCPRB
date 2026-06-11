from __future__ import annotations

from pathlib import Path


DEFAULT_MAX_CHARS = 20_000


def ensure_within(base_dir: Path, target: Path) -> Path:
    base = base_dir.resolve()
    resolved = target.resolve()

    if resolved != base and base not in resolved.parents:
        raise ValueError(f"Ruta fuera del directorio permitido: {resolved}")

    return resolved


def resolve_project_path(base_dir: Path, relative_path: str) -> Path:
    candidate = (base_dir / relative_path).resolve()
    return ensure_within(base_dir, candidate)


def read_text_file(path: Path, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    if not path.exists():
        raise FileNotFoundError(f"No existe: {path}")
    if not path.is_file():
        raise ValueError(f"No es archivo: {path}")

    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars:
        return content[:max_chars] + "\n\n...[truncado]..."
    return content
