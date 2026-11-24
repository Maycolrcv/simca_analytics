"""Persistencia de alias y prerrequisitos personalizados (config_materias.json).

Garantías:
  * Lectura tolerante: archivo ausente -> config vacía; JSON corrupto -> se aparta a
    ``*.corrupt-<fecha>.json`` y se arranca limpio (nunca se pierde ni se sobrescribe).
  * Escritura segura: bloqueo entre procesos (filelock) + escritura atómica + ``.bak``.
  * Fusión por materia: al guardar se relee el disco bajo el bloqueo y solo se
    reemplazan las materias editadas, así dos pestañas no se pisan entre sí.
  * Sanitización de todo lo leído/guardado (tipos, longitudes, duplicados).

Esquema (aditivo; los archivos anteriores sin "asignaciones" siguen cargando):
  materias:     {id_materia: {aliases, prereqs_extra, prereqs_removidos}}
  asignaciones: {id_registro: {tipo: electiva_adicional | requisito_grado, nombre, requisito, grupo: fish|complementaria|""}}
                (id_registro = "ID Materia" de la historia, o código de la matriculada)
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from .fileio import atomic_write_json
from .settings import CONFIG_FILENAME, get_data_dir
from .text_utils import clean_text, normalize_key

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
LOCK_TIMEOUT_S = 10
MAX_ALIASES = 50
MAX_ALIAS_LEN = 120
MAX_PREREQS = 40
TIPOS_ASIGNACION = ("electiva_adicional", "requisito_grado")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


class ConfigError(RuntimeError):
    """No se pudo leer/escribir la configuración (p. ej. bloqueo ocupado)."""


@dataclass
class LoadResult:
    config: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass
class SaveResult:
    config: dict[str, Any]
    conflicto_externo: bool  # el archivo en disco había cambiado desde que la sesión lo cargó


def config_path() -> Path:
    return get_data_dir() / CONFIG_FILENAME


def empty_config() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "revision": 0, "actualizado": None, "materias": {}, "asignaciones": {}}


def _lock(path: Path) -> FileLock:
    return FileLock(str(path) + ".lock", timeout=LOCK_TIMEOUT_S)


# ----------------------------------------------------------------- sanitización
def sanitize_entry(raw: Any) -> dict[str, list[str]] | None:
    """Normaliza una entrada de materia. Devuelve ``None`` si queda vacía."""
    if not isinstance(raw, dict):
        return None

    aliases, vistos = [], set()
    for a in raw.get("aliases") or []:
        texto = clean_text(a)[:MAX_ALIAS_LEN]
        clave = normalize_key(texto)
        if clave and clave not in vistos:
            vistos.add(clave)
            aliases.append(texto)

    def ids(key: str) -> list[str]:
        out: list[str] = []
        for v in raw.get(key) or []:
            v = clean_text(v)
            if _ID_RE.match(v) and v not in out:
                out.append(v)
        return sorted(out)[:MAX_PREREQS]

    entry = {
        "aliases": aliases[:MAX_ALIASES],
        "prereqs_extra": ids("prereqs_extra"),
        "prereqs_removidos": ids("prereqs_removidos"),
    }
    entry["prereqs_extra"] = [i for i in entry["prereqs_extra"] if i not in entry["prereqs_removidos"]]
    return entry if any(entry.values()) else None


def sanitize_asignacion(raw: Any) -> dict[str, str] | None:
    """Normaliza una asignación manual. ``None`` si es inválida."""
    if not isinstance(raw, dict) or raw.get("tipo") not in TIPOS_ASIGNACION:
        return None
    nombre = clean_text(raw.get("nombre"))[:MAX_ALIAS_LEN]
    if not nombre:
        return None
    requisito = clean_text(raw.get("requisito"))[:MAX_ALIAS_LEN] if raw["tipo"] == "requisito_grado" else ""
    grupo = raw.get("grupo") if raw["tipo"] == "electiva_adicional" and raw.get("grupo") in ("fish", "complementaria") else ""
    return {"tipo": raw["tipo"], "nombre": nombre, "requisito": requisito, "grupo": grupo}


def _sanitize_config(raw: Any) -> tuple[dict[str, Any], list[str]]:
    if (not isinstance(raw, dict) or not isinstance(raw.get("materias", {}), dict)
            or not isinstance(raw.get("asignaciones", {}), dict)):
        raise ValueError("estructura raíz inválida")
    cfg = empty_config()
    warnings: list[str] = []
    rev = raw.get("revision")
    cfg["revision"] = rev if isinstance(rev, int) and rev >= 0 else 0
    cfg["actualizado"] = raw.get("actualizado") if isinstance(raw.get("actualizado"), str) else None
    for mid, entry in raw.get("materias", {}).items():
        mid = clean_text(mid)
        clean = sanitize_entry(entry)
        if _ID_RE.match(mid) and clean:
            cfg["materias"][mid] = clean
        else:
            warnings.append(f"Entrada de configuración descartada por inválida: '{mid[:30]}'.")
    for key, raw_a in raw.get("asignaciones", {}).items():
        key = clean_text(key)
        clean_a = sanitize_asignacion(raw_a)
        if _ID_RE.match(key) and clean_a:
            cfg["asignaciones"][key] = clean_a
        else:
            warnings.append(f"Asignación descartada por inválida: '{key[:30]}'.")
    return cfg, warnings


# ----------------------------------------------------------------- lectura
def _read_unlocked(path: Path) -> LoadResult:
    if not path.exists():
        return LoadResult(empty_config())
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cfg, warns = _sanitize_config(raw)
        return LoadResult(cfg, warns)
    except (ValueError, OSError) as exc:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        destino = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
        try:
            shutil.move(str(path), str(destino))
            msg = f"La configuración estaba dañada ({exc}); se movió a '{destino.name}' y se inició una vacía."
        except OSError:
            msg = f"La configuración estaba dañada ({exc}) y no pudo respaldarse; se inició una vacía."
        log.warning(msg)
        return LoadResult(empty_config(), [msg])


def load_config(path: Path | None = None) -> LoadResult:
    path = path or config_path()
    try:
        with _lock(path):
            return _read_unlocked(path)
    except Timeout as exc:
        raise ConfigError("El archivo de configuración está ocupado por otro proceso; reintenta.") from exc


def disk_revision(path: Path | None = None) -> int:
    """Revisión actual en disco (0 si no existe). Lectura sin bloqueo ni efectos secundarios."""
    path = path or config_path()
    try:
        rev = json.loads(path.read_text(encoding="utf-8")).get("revision", 0)
        return rev if isinstance(rev, int) else 0
    except (OSError, ValueError, AttributeError):
        return 0


# ----------------------------------------------------------------- escritura
def _mutar(mutador, base_revision: int | None, path: Path | None) -> SaveResult:
    """Lee bajo bloqueo, aplica ``mutador(cfg)``, sube la revisión y escribe atómicamente."""
    path = path or config_path()
    try:
        with _lock(path):
            cfg = _read_unlocked(path).config
            conflicto = base_revision is not None and cfg["revision"] != base_revision
            mutador(cfg)
            cfg["revision"] += 1
            cfg["actualizado"] = datetime.now().isoformat(timespec="seconds")
            if path.exists():
                try:
                    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
                except OSError:
                    log.warning("No se pudo crear el respaldo .bak")
            atomic_write_json(path, cfg)
            return SaveResult(cfg, conflicto)
    except Timeout as exc:
        raise ConfigError("El archivo de configuración está ocupado por otro proceso; reintenta.") from exc


def _id_valido(valor: Any) -> str:
    valor = clean_text(valor)
    if not _ID_RE.match(valor):
        raise ConfigError(f"ID inválido: {valor[:30]!r}")
    return valor


def save_materias(updates: dict[str, Any], *, base_revision: int | None = None, path: Path | None = None) -> SaveResult:
    """Aplica ``{id_materia: entrada | None}`` (None/vacía = borrar). Fusiona por materia."""
    def mutar(cfg: dict[str, Any]) -> None:
        for mid, entry in updates.items():
            mid = _id_valido(mid)
            if clean := sanitize_entry(entry):
                cfg["materias"][mid] = clean
            else:
                cfg["materias"].pop(mid, None)
    return _mutar(mutar, base_revision, path)


def save_asignaciones(updates: dict[str, Any], *, base_revision: int | None = None, path: Path | None = None) -> SaveResult:
    """Aplica ``{id_registro: asignación | None}`` (None = quitar). Fusiona por registro."""
    def mutar(cfg: dict[str, Any]) -> None:
        for key, asig in updates.items():
            key = _id_valido(key)
            if clean := sanitize_asignacion(asig):
                cfg["asignaciones"][key] = clean
            else:
                cfg["asignaciones"].pop(key, None)
    return _mutar(mutar, base_revision, path)


def replace_config(raw: Any, *, base_revision: int | None = None, path: Path | None = None) -> SaveResult:
    """Importa una configuración completa (p. ej. exportada antes): reemplaza materias y asignaciones."""
    try:
        nueva, _ = _sanitize_config(raw)
    except ValueError as exc:
        raise ConfigError(f"Archivo de configuración inválido: {exc}") from exc

    def mutar(cfg: dict[str, Any]) -> None:
        cfg["materias"], cfg["asignaciones"] = nueva["materias"], nueva["asignaciones"]
    return _mutar(mutar, base_revision, path)
