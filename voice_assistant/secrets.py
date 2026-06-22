from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig


class SecretError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedSecret:
    api_key: str
    source: str
    path: Path | None


def _read_first_non_empty_line(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if value:
                return value
    raise SecretError(f"No se encontro una API key valida en {path}")


def _walk_limited(root: Path, max_depth: int) -> list[Path]:
    results: list[Path] = []
    try:
        for current_root, dirs, files in os.walk(root):
            current_path = Path(current_root)
            depth = len(current_path.relative_to(root).parts)
            if depth > max_depth:
                dirs[:] = []
                continue
            for filename in files:
                results.append(current_path / filename)
    except OSError:
        return []
    return results


def discover_usb_api_key_file(config: AppConfig) -> Path | None:
    matching: list[Path] = []
    fallback: list[Path] = []
    for root in config.usb_search_roots:
        if not root.exists():
            continue
        for candidate in _walk_limited(root, max_depth=4):
            if candidate.name != config.api_key_filename:
                continue
            if config.usb_label and config.usb_label in str(candidate):
                matching.append(candidate)
            else:
                fallback.append(candidate)
    ordered = sorted(matching) + sorted(fallback)
    return ordered[0] if ordered else None


def write_local_api_key(path: Path, api_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(f"{api_key}\n", encoding="utf-8")
    os.chmod(path, 0o600)


def resolve_api_key(config: AppConfig) -> ResolvedSecret:
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return ResolvedSecret(api_key=env_key, source="env", path=None)

    if config.local_api_key_path.exists():
        return ResolvedSecret(
            api_key=_read_first_non_empty_line(config.local_api_key_path),
            source="local_file",
            path=config.local_api_key_path,
        )

    usb_file = discover_usb_api_key_file(config)
    if usb_file is None:
        raise SecretError(
            "No hay OPENAI_API_KEY, no existe copia local y no se encontro "
            f"{config.api_key_filename} en los puntos de montaje USB visibles."
        )

    api_key = _read_first_non_empty_line(usb_file)
    write_local_api_key(config.local_api_key_path, api_key)
    return ResolvedSecret(
        api_key=api_key,
        source="usb_import",
        path=config.local_api_key_path,
    )
