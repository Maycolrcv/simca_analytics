"""Normalización y limpieza de cadenas provenientes del scraping."""
from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def clean_text(value: object) -> str:
    """Devuelve texto sin NBSP, caracteres invisibles ni espacios repetidos.

    Tolera ``None`` y ``NaN`` (celdas vacías) devolviendo ``""``.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    text = str(value).translate(_ZERO_WIDTH).replace("\xa0", " ")
    text = unicodedata.normalize("NFC", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_key(value: object) -> str:
    """Clave de comparación: sin tildes, minúsculas, sin puntuación ni dobles espacios.

    ``"Formulación y  Evaluación de Proyectos"`` -> ``"formulacion y evaluacion de proyectos"``
    """
    text = unicodedata.normalize("NFKD", clean_text(value)).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _NON_ALNUM_RE.sub(" ", text).strip()


def parse_float(value: object) -> float | None:
    """Convierte ``"4,3"``/``"  4.3"`` en ``4.3``. Devuelve ``None`` si no es numérico (p. ej. ``"A"``)."""
    text = clean_text(value)
    if not _NUM_RE.match(text):
        return None
    return float(text.replace(",", "."))


def parse_int(value: object) -> int | None:
    number = parse_float(value)
    return int(number) if number is not None else None
