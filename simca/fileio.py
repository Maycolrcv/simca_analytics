"""Escritura atómica y permisos privados para archivos locales."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def ensure_private_dir(path: Path) -> Path:
    """Crea el directorio (permisos 0700 en POSIX) y un ``.gitignore`` interno ``*``.

    El ``.gitignore`` interno es una defensa extra: aunque el del repositorio se
    modifique por error, nada de lo que viva en esta carpeta podrá ser añadido a git.
    """
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError, NotImplementedError):
        os.chmod(path, 0o700)
    guard = path / ".gitignore"
    if not guard.exists():
        with contextlib.suppress(OSError):
            guard.write_text("*\n", encoding="utf-8")
    return path


def atomic_write_json(path: Path, data: Any) -> None:
    """Escribe JSON en un temporal del mismo directorio y lo reemplaza con ``os.replace``.

    Si el proceso muere a mitad de la escritura, el archivo original queda intacto.
    """
    path = Path(path)
    ensure_private_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        with contextlib.suppress(OSError, NotImplementedError):
            os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def write_json_plain(path: Path, data: Any) -> None:
    """Escribe JSON con permisos 0600 SIN modificar el directorio (útil para carpetas temporales ajenas)."""
    path = Path(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    with contextlib.suppress(OSError, NotImplementedError):
        os.chmod(path, 0o600)
