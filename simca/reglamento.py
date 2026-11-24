"""Validaciones del Reglamento Estudiantil (Acuerdo 002 de 1988 y modificatorios), Arts. 6-11,
sobre asignaturas repetidas. Es una ayuda orientativa calculada del historial: la decisión
oficial la toma el programa/Registro Académico.

Convención de intentos (solo cuentan los CALIFICADOS; cancelaciones o filas sin definitiva no cuentan,
y una habilitación no es un intento: manda la «Definitiva»):
    intento 1 = curso normal · intento 2 = repitente por 1.ª vez · 3 = por 2.ª vez · 4 = por 3.ª vez

Reglas implementadas (resumen):
    Art. 6   perder como repitente por 1.ª vez            -> bajo rendimiento académico
    Art. 7   perder como repitente por 2.ª vez            -> solo continúa con matrícula condicional el periodo siguiente;
             par.: si además tiene sanción disciplinaria  -> pierde el derecho a continuar
    Art. 8   con condicional, no aprobar como repitente 3.ª vez -> pierde el derecho a continuar
    Art. 9   con condicional solo puede matricular lo que cursa como repitente 3.ª vez y lo que deba repetir
    Art. 10  máximo dos ocasiones de matrícula condicional
    Art. 11  con dos condicionales usadas, perder como repitente 2.ª vez -> pierde el derecho a continuar

Supuestos (no hay un dato directo en SIMCA para ellos):
    * Cada periodo en que se pierde una asignatura como repitente 2.ª vez genera UNA matrícula condicional (el periodo siguiente).
    * «Sanción disciplinaria» la indica el usuario; no se guarda en disco.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .matrix import EN_CURSO, MatrizResult

ARTICULOS = {
    6: "Bajo rendimiento académico: perder una asignatura cursada como repitente por primera vez.",
    7: "Perder una asignatura como repitente por segunda vez: solo puede continuar con matrícula condicional el periodo "
       "siguiente, si no tiene sanción disciplinaria (con sanción pierde el derecho a continuar).",
    8: "Con matrícula condicional, no aprobar una asignatura como repitente por tercera vez: pierde definitivamente el derecho a continuar.",
    9: "Con matrícula condicional solo puede matricular lo que cursa como repitente por tercera vez y lo demás que deba repetir.",
    10: "Máximo dos ocasiones de matrícula condicional durante la carrera.",
    11: "Con dos matrículas condicionales usadas, perder una asignatura como repitente por segunda vez: pierde el derecho a continuar.",
}
SITUACIONES = {
    "normal": "Sin alertas de repitencia",
    "bajo_rendimiento": "Bajo rendimiento académico (Art. 6)",
    "matricula_condicional": "Matrícula condicional (Arts. 7, 9 y 10)",
    "perdida_derecho": "Posible pérdida del derecho a continuar (Arts. 7-11)",
}


@dataclass
class Hallazgo:
    nivel: str            # info | alerta | critico
    articulo: str         # "Art. 6", "Arts. 10 y 11"...
    titulo: str
    detalle: str
    materia: str = ""
    periodo: str = ""


@dataclass
class FilaRepetida:
    materia: str
    intentos: int
    trayectoria: str      # "2022.2: 2.0 → 2023.1: 3.4"
    estado: str           # aprobada | en_curso | por_repetir
    repitente: int        # veces previas perdidas = «repitente por nª vez» del intento en curso o siguiente
    observacion: str = ""


@dataclass
class ResultadoReglamento:
    situacion: str = "normal"
    hallazgos: list[Hallazgo] = field(default_factory=list)
    filas: list[FilaRepetida] = field(default_factory=list)
    condicionales_usadas: int = 0
    condicional_vigente: bool = False
    periodo_objetivo: str | None = None


def siguiente_periodo(periodo: str) -> str:
    """'2026.1' -> '2026.2'; '2026.2' -> '2027.1'."""
    try:
        anio, sem = periodo.split(".")
        return f"{anio}.2" if sem == "1" else f"{int(anio) + 1}.1"
    except (ValueError, AttributeError):
        return periodo


def _ordinal(n: int) -> str:
    return {1: "primera", 2: "segunda", 3: "tercera"}.get(n, f"{n}.ª")


def _riesgo(r: int, condicionales_usadas: int, sancionado: bool) -> str:
    """Qué pasa si pierde la asignatura que cursa (o cursará) como repitente por r-ésima vez."""
    if r <= 0:
        return ""
    if r == 1:
        return "Si la pierde: bajo rendimiento académico (Art. 6)."
    if r == 2:
        if sancionado:
            return "Si la pierde, con sanción disciplinaria: pierde el derecho a continuar (Art. 7, parágrafo)."
        if condicionales_usadas >= 2:
            return "Si la pierde: pierde el derecho a continuar, ya usó dos matrículas condicionales (Arts. 10 y 11)."
        return f"Si la pierde: matrícula condicional el periodo siguiente (Art. 7; sería la n.º {condicionales_usadas + 1} de 2)."
    return "Si no la aprueba: pierde definitivamente el derecho a continuar (Art. 8)."


def evaluar_reglamento(
    res: MatrizResult,
    periodo_actual: str | None = None,
    sancionado: bool = False,
    matriculadas_cargadas: bool = True,
) -> ResultadoReglamento:
    # ---- 1. grupos de intentos por asignatura (cupos del pensum + todo lo demás)
    grupos: dict[str, tuple[str, list[dict[str, Any]]]] = {c.id: (c.nombre, c.historial) for c in res.celdas}
    grupos.update({k: (v["nombre"], v["historial"]) for k, v in res.grupos_extra.items()})
    en_curso_pensum = {c.id: c for c in res.celdas if c.estado == EN_CURSO}

    ev6: list[tuple[str, str]] = []
    ev7: list[tuple[str, str]] = []
    ev8: list[tuple[str, str, int]] = []
    filas: list[FilaRepetida] = []
    previos_por_id: dict[str, int] = {}
    pendientes_3: list[str] = []   # asignaturas que ya perdió 3 veces y aún no aprueba

    for clave, (nombre, hist) in grupos.items():
        intentos = sorted((h for h in hist if h["definitiva"] is not None), key=lambda h: h["periodo"])
        fallos = [(i + 1, h) for i, h in enumerate(intentos) if not h["aprobada"]]
        previos_por_id[clave] = len(fallos)
        if not fallos:
            continue
        for k, h in fallos:
            if k == 2:
                ev6.append((nombre, h["periodo"]))
            elif k == 3:
                ev7.append((nombre, h["periodo"]))
            elif k >= 4:
                ev8.append((nombre, h["periodo"], k))
        aprobada = any(h["aprobada"] for h in intentos)
        estado = "aprobada" if aprobada else ("en_curso" if clave in en_curso_pensum else "por_repetir")
        trayectoria = " → ".join(f"{h['periodo']}: {h['definitiva']:.1f}" for h in intentos)
        if not aprobada and len(fallos) >= 3 and clave not in en_curso_pensum:
            pendientes_3.append(nombre)
        filas.append(FilaRepetida(nombre, len(intentos), trayectoria, estado, 0 if aprobada else len(fallos)))

    # ---- 2. eventos -> hallazgos
    out = ResultadoReglamento(filas=filas)
    for nombre, per in ev6:
        out.hallazgos.append(Hallazgo("alerta", "Art. 6", "Bajo rendimiento académico",
                                      f"Perdió «{nombre}» como repitente por primera vez.", nombre, per))
    periodos7 = sorted({p for _, p in ev7})
    out.condicionales_usadas = len(periodos7)
    for i, per in enumerate(periodos7, start=1):
        perdidas = ", ".join(f"«{n}»" for n, p in ev7 if p == per)
        if i >= 3:
            out.hallazgos.append(Hallazgo("critico", "Arts. 10 y 11", "Excede las dos matrículas condicionales",
                                          f"Perdió como repitente por segunda vez {perdidas} habiendo usado ya dos matrículas condicionales.", periodo=per))
        elif sancionado:
            out.hallazgos.append(Hallazgo("critico", "Art. 7, parágrafo", "Pierde el derecho a continuar (sanción disciplinaria)",
                                          f"Perdió como repitente por segunda vez {perdidas} y tiene sanción disciplinaria.", periodo=per))
        else:
            out.hallazgos.append(Hallazgo("alerta", "Art. 7", f"Matrícula condicional n.º {i} de 2 en {siguiente_periodo(per)}",
                                          f"Perdió como repitente por segunda vez {perdidas}.", periodo=per))
    for nombre, per, k in ev8:
        out.hallazgos.append(Hallazgo("critico", "Art. 8", "Pierde el derecho a continuar",
                                      f"No aprobó «{nombre}» como repitente por {_ordinal(k - 1)} vez (intento {k}).", nombre, per))

    # ---- 3. periodo objetivo y matrícula condicional vigente
    ultimo = max((h["periodo"] for _, hist in grupos.values() for h in hist if h["periodo"]), default=None)
    out.periodo_objetivo = periodo_actual or (siguiente_periodo(ultimo) if ultimo else None)
    out.condicional_vigente = out.periodo_objetivo in {siguiente_periodo(p) for p in periodos7}

    # ---- 4. lo que cursa ahora (o cursará): riesgo y Art. 9
    items: list[tuple[str, int, int, bool]] = []   # (nombre, repitente efectivo, repetición SIMCA, es_pensum)
    for c in res.celdas:
        if c.estado == EN_CURSO:
            prev = previos_por_id.get(c.id, 0)
            sim = int((c.matricula or {}).get("repeticion") or 0)
            items.append((c.nombre, max(prev, sim), sim, True))
            if prev != sim and (prev or sim):
                out.hallazgos.append(Hallazgo(
                    "info", "Verificar", "La repetición de SIMCA no coincide con el historial",
                    f"«{c.nombre}»: SIMCA indica repetición {sim} y el historial muestra {prev} intento(s) perdido(s).", c.nombre))
    for c in res.adicionales:
        if c.estado == EN_CURSO:
            sim = int((c.matricula or {}).get("repeticion") or 0)
            items.append((c.nombre, sim, sim, False))
    for mm in res.matriculadas_sin_correspondencia:
        items.append((mm.nombre, int(mm.repeticion or 0), int(mm.repeticion or 0), False))

    for fila in filas:
        if fila.estado == "en_curso":
            fila.observacion = _riesgo(fila.repitente, out.condicionales_usadas, sancionado)
            fila.repitente = max(fila.repitente, next((r for n, r, _, _ in items if n == fila.materia), 0))
        elif fila.estado == "por_repetir":
            fila.observacion = "Debe repetirla. " + _riesgo(fila.repitente, out.condicionales_usadas, sancionado)
        else:
            fila.observacion = f"Aprobada en el intento {fila.intentos}."
    for nombre, r, sim, en_pensum in items:
        if r >= 1 and not en_pensum:  # las del pensum ya están en `filas`
            out.filas.append(FilaRepetida(nombre, r + 1, "(según SIMCA)", "en_curso", r, _riesgo(r, out.condicionales_usadas, sancionado)))

    if out.condicional_vigente and matriculadas_cargadas:
        out.hallazgos.append(Hallazgo(
            "alerta", "Art. 9", f"Matrícula condicional vigente en {out.periodo_objetivo}",
            "Solo puede matricular las asignaturas que cursa como repitente por tercera vez y las demás que deba repetir."))
        for nombre, r, _, _ in items:
            if r == 0:
                out.hallazgos.append(Hallazgo(
                    "alerta", "Art. 9", "Matriculó una asignatura nueva con matrícula condicional",
                    f"«{nombre}» no figura como repetición: verificar la matrícula.", nombre, out.periodo_objetivo or ""))
        en_curso_nombres = {n for n, *_ in items}
        for nombre in pendientes_3:
            if nombre not in en_curso_nombres:
                out.hallazgos.append(Hallazgo(
                    "alerta", "Art. 9", "Debe cursar como repitente por tercera vez",
                    f"«{nombre}» ya se perdió 3 veces y no figura matriculada.", nombre, out.periodo_objetivo or ""))

    # ---- 5. situación general
    if any(h.nivel == "critico" for h in out.hallazgos):
        out.situacion = "perdida_derecho"
    elif out.condicional_vigente:
        out.situacion = "matricula_condicional"
    elif any(f.estado != "aprobada" and f.repitente >= 1 and any(n == f.materia for n, _ in ev6) for f in out.filas):
        out.situacion = "bajo_rendimiento"
    orden = {"critico": 0, "alerta": 1, "info": 2}
    out.hallazgos.sort(key=lambda h: (orden[h.nivel], h.periodo))
    out.filas.sort(key=lambda f: ({"en_curso": 0, "por_repetir": 1, "aprobada": 2}[f.estado], -f.repitente))
    return out
