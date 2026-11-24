"""Estado de los requisitos de grado: lista oficial del pénsum vs. evidencias.

Evidencias:
  * filas de la tabla «Requisitos de Grado» de SIMCA (se asocian a un requisito oficial por nombre: heurística)
  * registros del historial/matrícula que el usuario marcó como requisito (asociación explícita)
"""
from __future__ import annotations

import re
from typing import Any

from .text_utils import normalize_key

# clave que debe aparecer en el requisito oficial -> palabras que delatan una evidencia
_REGLAS = (
    ("actividad fisica", ("aff", "actividad fisica", "deporte", "deportes")),
    ("idioma", ("ingles", "idioma", "lengua extranjera", "frances", "b1", "b2")),
    ("ecaes", ("ecaes", "saber pro")),
)
OTRO = "Otro requisito"


def inferir_requisito(nombre: str, oficiales: list[str]) -> str | None:
    key = normalize_key(nombre)
    for oficial in oficiales:
        ok = normalize_key(oficial)
        for clave, palabras in _REGLAS:
            if clave in ok and any(re.search(rf"\b{re.escape(p)}\b", key) for p in palabras):
                return oficial
        if ok and ok in key:
            return oficial
    return None


def evaluar_requisitos(
    oficiales: list[dict[str, str]],
    simca_items: list[dict[str, Any]],
    marcados: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Devuelve ``(filas_por_requisito_oficial, otros_reconocidos)``."""
    nombres = [o["nombre"] for o in oficiales]
    filas = {n: {"requisito": n, "estado": "pendiente", "evidencia": []} for n in nombres}
    otros: list[dict[str, Any]] = []

    def registrar(destino: str | None, nombre: str, estado: str, detalle: str) -> None:
        if destino and destino in filas:
            f = filas[destino]
            f["evidencia"].append(f"{nombre} ({detalle})")
            if estado == "aprobada":
                f["estado"] = "cumplido"
            elif estado == "en_curso" and f["estado"] != "cumplido":
                f["estado"] = "en_curso"
        else:
            otros.append({"nombre": nombre, "estado": estado, "detalle": detalle})

    for it in simca_items:
        estado = "aprobada" if it.get("aprobado") else "reprobada"
        detalle = f"{it.get('periodo', '')} · {it.get('definitiva', '')}".strip(" ·")
        registrar(inferir_requisito(it["nombre"], nombres), it["nombre"], estado, detalle)
    for m in marcados:  # asociación explícita elegida por el usuario ("" = otro)
        detalle = "marcado manualmente · " + ("en curso" if m["estado"] == "en_curso" else f"{m.get('periodo', '')} · {m.get('definitiva') or '—'}")
        registrar(m.get("requisito") or None, m["nombre"], m["estado"], detalle)

    return list(filas.values()), otros
