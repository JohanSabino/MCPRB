from __future__ import annotations

from pathlib import Path

from core.file_reader import read_text_file


TEXT_EXTENSIONS = {
    ".json",
    ".log",
    ".md",
    ".py",
    ".robot",
    ".sql",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def search_text(
    base_dir: Path,
    query: str,
    file_pattern: str = "*",
    max_results: int = 20,
) -> list[dict[str, object]]:
    normalized = query.lower()
    results: list[dict[str, object]] = []

    for path in sorted(base_dir.rglob(file_pattern)):
        if len(results) >= max_results:
            break
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue

        try:
            content = read_text_file(path, max_chars=100_000)
        except (OSError, UnicodeError, ValueError):
            continue

        for index, line in enumerate(content.splitlines(), start=1):
            if normalized in line.lower():
                results.append(
                    {
                        "file": str(path.relative_to(base_dir)),
                        "line": index,
                        "preview": line.strip(),
                    }
                )
                if len(results) >= max_results:
                    break

    return results
