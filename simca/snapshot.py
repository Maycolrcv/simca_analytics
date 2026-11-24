"""Matriz base unificada: pensum + notas -> JSON local (sin cédula ni código)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .fileio import atomic_write_json
from .models import MateriaMatriculada, MateriaPensum, RegistroNota
from .parsers import ParseError, parse_estudiante, parse_matriculadas_html, parse_notas_html, parse_pensum_html
from .settings import SNAPSHOT_FILENAME, get_data_dir

log = logging.getLogger(__name__)
SNAPSHOT_VERSION = 1


def build_snapshot(pensum_html: str, notas_html: str, matriculadas_html: str | None = None) -> dict[str, Any]:
    pensum = parse_pensum_html(pensum_html)
    notas = parse_notas_html(notas_html)
    estudiante = notas.estudiante or parse_estudiante(pensum_html)
    avisos = pensum.warnings + notas.warnings
    mat = None
    if matriculadas_html:  # opcional: si falla, el resto de la app sigue funcionando
        try:
            mat = parse_matriculadas_html(matriculadas_html)
            avisos += mat.warnings
        except ParseError as exc:
            avisos.append(f"Materias matriculadas no disponibles: {exc}")
    return {
        "version": SNAPSHOT_VERSION,
        "generado": datetime.now().isoformat(timespec="seconds"),
        "estudiante": estudiante,
        "pensum": [asdict(m) for m in pensum.materias],
        "notas": [asdict(r) for r in notas.registros],
        "promedios_periodo": notas.promedios,
        "requisitos_grado": notas.requisitos_grado,
        "requisitos_grado_oficiales": pensum.requisitos_grado,
        "matriculadas": [asdict(m) for m in mat.materias] if mat else [],
        "periodo_actual": mat.periodo if mat else None,
        "matriculadas_cargadas": mat is not None,
        "advertencias": avisos,
    }


def snapshot_path() -> Path:
    return get_data_dir() / SNAPSHOT_FILENAME


def save_snapshot(snapshot: dict[str, Any], path: Path | None = None) -> Path:
    path = path or snapshot_path()
    atomic_write_json(path, snapshot)
    return path


def load_snapshot(path: Path | None = None) -> dict[str, Any] | None:
    path = path or snapshot_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "pensum" not in data or "notas" not in data:
            raise ValueError("estructura inválida")
        return data
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("Snapshot ilegible (%s); se ignora.", exc)
        return None


def snapshot_to_models(snapshot: dict[str, Any]) -> tuple[list[MateriaPensum], list[RegistroNota], list[MateriaMatriculada]]:
    return (
        [MateriaPensum.from_dict(m) for m in snapshot["pensum"]],
        [RegistroNota.from_dict(n) for n in snapshot["notas"]],
        [MateriaMatriculada.from_dict(m) for m in snapshot.get("matriculadas", [])],  # ausente en snapshots viejos
    )
