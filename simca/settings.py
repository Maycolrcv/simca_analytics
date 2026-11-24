"""Configuración y credenciales.

Las credenciales se leen EXCLUSIVAMENTE de variables de entorno / archivo ``.env``
(vía python-dotenv). No existe ningún valor por defecto ni fallback en el código.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .fileio import ensure_private_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

SIMCA_BASE_URL = os.getenv("SIMCA_BASE_URL", "https://simca.unicauca.edu.co/simca/")
CONFIG_FILENAME = "config_materias.json"
SNAPSHOT_FILENAME = "snapshot_academico.json"


class MissingCredentialsError(RuntimeError):
    """Faltan SIMCA_USER / SIMCA_PASSWORD en el entorno."""


@dataclass(frozen=True)
class Credentials:
    usuario: str = field(repr=False)
    password: str = field(repr=False)  # repr=False: nunca aparece en logs/tracebacks


def credentials_configured() -> bool:
    return bool(os.getenv("SIMCA_USER", "").strip() and os.getenv("SIMCA_PASSWORD", ""))


def get_credentials() -> Credentials:
    usuario = os.getenv("SIMCA_USER", "").strip()
    password = os.getenv("SIMCA_PASSWORD", "")
    if not usuario or not password:
        raise MissingCredentialsError(
            "Faltan credenciales. Copia '.env.example' a '.env' y define "
            "SIMCA_USER y SIMCA_PASSWORD."
        )
    return Credentials(usuario=usuario, password=password)


def get_student_code() -> str:
    return os.getenv("SIMCA_STUDENT_CODE", "").strip()


def is_headless() -> bool:
    return os.getenv("SIMCA_HEADLESS", "true").strip().lower() not in {"0", "false", "no"}


def is_debug() -> bool:
    return os.getenv("SIMCA_DEBUG", "0").strip().lower() in {"1", "true", "yes"}


def modo_nube() -> bool:
    """True en Streamlit Community Cloud (o con SIMCA_MODO_NUBE=1).

    En modo nube el disco es efímero y COMPARTIDO entre todos los visitantes, así que los datos
    académicos de cada consulta viven solo en su sesión: nunca se guardan ni se leen de disco.
    """
    flag = os.getenv("SIMCA_MODO_NUBE", "").strip().lower()
    if flag in {"1", "true", "yes", "si", "sí"}:
        return True
    if flag in {"0", "false", "no"}:
        return False
    return Path("/mount/src").exists()  # Streamlit Cloud monta el repositorio aquí


def get_data_dir() -> Path:
    """Directorio privado para config/snapshot. ``SIMCA_DATA_DIR`` permite sacarlo del repo."""
    custom = os.getenv("SIMCA_DATA_DIR", "").strip()
    base = Path(custom).expanduser() if custom else PROJECT_ROOT / "data"
    try:
        return ensure_private_dir(base)
    except OSError:  # p. ej. repositorio de solo lectura en la nube
        return ensure_private_dir(Path(tempfile.gettempdir()) / "simca_analytics")
