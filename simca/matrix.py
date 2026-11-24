"""Unificación pensum oficial x notas x matrícula actual x configuración -> Matriz de Visualización.

Emparejamiento nota -> materia del pensum (la primera regla que aplique gana):
  1. alias definidos por el usuario (nombre alternativo o ID de SIMCA)  [intención explícita]
  2. ID interno idéntico
  3. nombre normalizado idéntico
  4. electivas/optativas: en orden cronológico a los cupos libres de su grupo
Emparejamiento matriculada -> materia: código del pensum, alias, nombre, y por último
cupo libre del grupo (usando el número romano/arábigo: «Optativa de Mercadeo II» -> «Optativa Profesional II»).

Electivas (dos columnas: «Electivas» del programa y «Electivas Fish»):
  * solo cuentan las APROBADAS o EN CURSO; las perdidas se ignoran por completo
  * se muestran en orden cronológico; los cupos libres del pensum quedan al final
  * las que exceden los cupos (9 del programa + 3 Fish) se agregan en la misma columna como «adicionales»
  * asignaciones manuales de la configuración (electiva adicional / requisito de grado) tienen prioridad

Semáforo: aprobada · en_curso · disponible · bloqueada · reprobada
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .models import MateriaMatriculada, MateriaPensum, RegistroNota, SEMESTRE_ELECTIVAS, SEMESTRE_FISH
from .text_utils import normalize_key

APROBADA, EN_CURSO, DISPONIBLE, BLOQUEADA, REPROBADA = "aprobada", "en_curso", "disponible", "bloqueada", "reprobada"
ESTADOS_ORDEN = (APROBADA, EN_CURSO, DISPONIBLE, BLOQUEADA, REPROBADA)
_ORDINALES = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "1": 1, "2": 2, "3": 3, "4": 4}


@dataclass
class CeldaMateria:
    id: str
    codigo: str
    nombre: str
    creditos: int
    semestre: int
    estado: str
    nota: float | None = None
    periodo: str | None = None
    intentos: int = 0
    metodo: str | None = None          # alias | id | nombre | electiva
    nombre_cursado: str | None = None  # nombre con que la cursó (si difiere del oficial)
    prereqs: list[dict[str, Any]] = field(default_factory=list)  # {id,nombre,aprobado,en_curso,origen}
    aliases: list[str] = field(default_factory=list)
    personalizada: bool = False
    adicional: bool = False            # electiva por encima de los cupos del pensum
    historial: list[dict[str, Any]] = field(default_factory=list)  # todos los intentos (cronológico) para el reglamento
    matricula: dict[str, Any] | None = None   # sección, docentes, horarios (si está en curso)
    desbloqueable: bool = False        # bloqueada solo por materias que hoy está cursando


@dataclass
class MatrizResult:
    celdas: list[CeldaMateria]
    sin_correspondencia: list[RegistroNota]
    matriculadas_sin_correspondencia: list[MateriaMatriculada]
    metricas: dict[str, Any]
    advertencias: list[str]
    adicionales: list[CeldaMateria] = field(default_factory=list)
    requisitos_marcados: list[dict[str, Any]] = field(default_factory=list)
    # intentos de asignaturas que NO quedaron en un cupo del pensum (sin asociar, electivas perdidas/adicionales,
    # requisitos): {"nota:<ID>": {"nombre", "historial"}}. Los usa el reglamento para contar repitencias.
    grupos_extra: dict[str, dict[str, Any]] = field(default_factory=dict)

    def por_semestre(self) -> dict[int, list[CeldaMateria]]:
        """Columnas: semestres 1..N, «Electivas» (0) y «Electivas Fish» (-2).

        En las dos de electivas: cursadas/en curso en orden cronológico y los cupos libres al final.
        """
        out: dict[int, list[CeldaMateria]] = defaultdict(list)
        for c in [*self.celdas, *self.adicionales]:
            out[c.semestre].append(c)
        for sem in (SEMESTRE_ELECTIVAS, SEMESTRE_FISH):  # cursadas/en curso por fecha; cupos vacíos al final
            if sem in out:
                out[sem].sort(key=lambda c: (c.periodo is None, c.periodo or ""))  # sort estable: conserva orden del pensum
        peso = lambda sem: 0 if sem > 0 else (1 if sem == SEMESTRE_ELECTIVAS else 2)  # noqa: E731
        return dict(sorted(out.items(), key=lambda kv: (peso(kv[0]), kv[0])))


def _intento(r: RegistroNota) -> dict[str, Any]:
    return {"periodo": r.periodo, "nombre": r.nombre, "nota": r.nota, "habilitacion": r.habilitacion,
            "definitiva": r.definitiva, "aprobada": r.aprobada}


def _grupo_slot(key: str) -> str | None:
    if key.startswith("electiva fish"):
        return "fish"
    if key.startswith("electiva complementaria"):
        return "complementaria"
    if key.startswith("optativa profesional"):
        return "optativa"
    return None


def _grupo_nota(key: str) -> str | None:
    if key.startswith("electiva fish") or key.startswith("fish"):
        return "fish"
    if key.startswith("electiva") or key.startswith("elec "):
        return "complementaria"
    if key.startswith("optativa"):
        return "optativa"
    return None


def _ordinal(key: str) -> int | None:
    return _ORDINALES.get(key.split()[-1]) if key else None


def _ciclos(grafo: dict[str, set[str]]) -> list[str]:
    """Nodos atrapados en dependencias circulares (Kahn)."""
    indeg = {n: len(d) for n, d in grafo.items()}
    dependientes: dict[str, list[str]] = defaultdict(list)
    for n, deps in grafo.items():
        for d in deps:
            dependientes[d].append(n)
    cola = [n for n, k in indeg.items() if k == 0]
    while cola:
        n = cola.pop()
        for m in dependientes[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                cola.append(m)
    return [n for n, k in indeg.items() if k > 0]


def construir_matriz(
    pensum: list[MateriaPensum],
    notas: list[RegistroNota],
    config: dict[str, Any] | None,
    matriculadas: list[MateriaMatriculada] | None = None,
) -> MatrizResult:
    cfg_mats: dict[str, dict] = (config or {}).get("materias", {})
    materias = {m.id: m for m in pensum}
    orden = {m.id: i for i, m in enumerate(pensum)}
    por_nombre = {normalize_key(m.nombre): m.id for m in pensum}
    warnings: list[str] = []

    asignadas: dict[str, list[int]] = defaultdict(list)
    metodo: dict[str, str] = {}
    libres = set(range(len(notas)))

    def asignar(mid: str, idx: int, how: str) -> None:
        asignadas[mid].append(idx)
        metodo.setdefault(mid, how)
        libres.discard(idx)

    asign: dict[str, dict] = (config or {}).get("asignaciones", {})
    extras: list[dict[str, Any]] = []        # electivas adicionales (historial y matrícula)
    req_marcados: list[dict[str, Any]] = []  # registros marcados como requisito de grado

    def estado_de(n: RegistroNota) -> str:
        return APROBADA if n.aprobada else (REPROBADA if n.definitiva is not None else EN_CURSO)

    def col_grupo(grupo: str | None) -> str:
        return "fish" if grupo == "fish" else "complementaria"

    def extra_de_nota(n: RegistroNota, origen: str, grupo: str | None) -> None:
        if n.definitiva is not None and not n.aprobada:  # electiva reprobada: no se tiene en cuenta
            return
        extras.append({"id": n.id, "nombre": n.nombre, "creditos": n.creditos or 0, "estado": estado_de(n),
                       "nota": n.definitiva, "periodo": n.periodo, "origen": origen, "matricula": None,
                       "grupo": col_grupo(grupo)})

    # --- 0. asignaciones manuales (intención explícita: ganan sobre cualquier regla automática)
    for idx in sorted(libres):
        n = notas[idx]
        if not (a := asign.get(n.id)):
            continue
        libres.discard(idx)
        if a["tipo"] == "electiva_adicional":
            extra_de_nota(n, "manual", a.get("grupo") or _grupo_nota(normalize_key(n.nombre)))
        else:
            req_marcados.append({"clave": n.id, "nombre": n.nombre, "periodo": n.periodo, "creditos": n.creditos or 0,
                                 "definitiva": n.definitiva, "estado": estado_de(n), "requisito": a["requisito"],
                                 "fuente": "historial"})

    # --- 1. alias del usuario
    alias_keys: dict[str, set[str]] = {}
    for mid, entry in cfg_mats.items():
        if mid not in materias:
            warnings.append(f"La configuración referencia la materia {mid}, que ya no existe en el pensum.")
            continue
        alias_keys[mid] = {normalize_key(a) for a in entry.get("aliases", [])} - {""}
        for idx in sorted(libres):
            n = notas[idx]
            if normalize_key(n.nombre) in alias_keys[mid] or normalize_key(n.id) in alias_keys[mid]:
                asignar(mid, idx, "alias")
    cuenta: dict[str, list[str]] = defaultdict(list)
    for mid, keys in alias_keys.items():
        for k in keys:
            cuenta[k].append(mid)
    for clave, mids in cuenta.items():
        if len(mids) > 1:
            warnings.append(f"El alias '{clave}' está repetido en varias materias: {', '.join(mids)}.")

    # --- 2. ID idéntico  3. nombre idéntico
    for idx in sorted(libres):
        if notas[idx].id in materias:
            asignar(notas[idx].id, idx, "id")
    for idx in sorted(libres):
        if mid := por_nombre.get(normalize_key(notas[idx].nombre)):
            asignar(mid, idx, "nombre")

    # --- 4. electivas / optativas del historial
    for grupo in ("fish", "complementaria", "optativa"):
        cupos = [m.id for m in pensum if _grupo_slot(normalize_key(m.nombre)) == grupo and m.id not in asignadas]
        candidatas = sorted(
            (i for i in libres if notas[i].aprobada and _grupo_nota(normalize_key(notas[i].nombre)) == grupo),
            key=lambda i: (notas[i].periodo, notas[i].id),
        )
        for mid, idx in zip(cupos, candidatas):
            asignar(mid, idx, "electiva")
    # electivas aprobadas sin cupo (más de 12) -> adicionales. Las REPROBADAS se ignoran por completo:
    # no ocupan cupo, no son adicionales y tampoco se listan como "sin asociar".
    electivas_ignoradas = 0
    for idx in sorted(libres, key=lambda i: (notas[i].periodo, notas[i].id)):
        n = notas[idx]
        if n.definitiva is not None and (grupo_n := _grupo_nota(normalize_key(n.nombre))) in ("fish", "complementaria"):
            libres.discard(idx)
            if n.aprobada:
                extra_de_nota(n, "auto", grupo_n)
            else:
                electivas_ignoradas += 1

    # --- 5. materias matriculadas (periodo actual)
    en_curso: dict[str, MateriaMatriculada] = {}
    mat_sin: list[MateriaMatriculada] = []
    por_codigo = {normalize_key(m.codigo): m.id for m in pensum}

    def mat_info(mm: MateriaMatriculada) -> dict[str, Any]:
        return {"seccion": mm.seccion, "docentes": mm.docentes, "repeticion": mm.repeticion,
                "horarios": [f"{h.dia} {h.horario}".strip() for h in mm.horarios]}

    for mm in matriculadas or []:
        ck, nk = normalize_key(mm.codigo), normalize_key(mm.nombre)
        grupo = _grupo_nota(nk)
        if a := asign.get(mm.codigo):  # asignación manual
            if a["tipo"] == "electiva_adicional":
                extras.append({"id": mm.codigo, "nombre": mm.nombre, "creditos": 0, "estado": EN_CURSO, "nota": None,
                               "periodo": mm.periodo, "origen": "manual", "matricula": mat_info(mm),
                               "grupo": col_grupo(a.get("grupo") or grupo)})
            else:
                req_marcados.append({"clave": mm.codigo, "nombre": mm.nombre, "periodo": mm.periodo, "creditos": 0,
                                     "definitiva": None, "estado": EN_CURSO, "requisito": a["requisito"], "fuente": "matricula"})
            continue
        mid = por_codigo.get(ck)
        if mid is None:
            mid = next((i for i, keys in alias_keys.items() if nk in keys or ck in keys), None)
        if mid is None:
            mid = por_nombre.get(nk)
        if mid is None and grupo:
            cupos = [m.id for m in pensum
                     if _grupo_slot(normalize_key(m.nombre)) == grupo and m.id not in asignadas and m.id not in en_curso]
            ordn = _ordinal(nk)
            mid = next((c for c in cupos if ordn and _ordinal(normalize_key(materias[c].nombre)) == ordn), None) or (cupos[0] if cupos else None)
        if mid is None and grupo in ("fish", "complementaria"):  # electiva sin cupo -> adicional en curso
            extras.append({"id": mm.codigo, "nombre": mm.nombre, "creditos": 0, "estado": EN_CURSO, "nota": None,
                           "periodo": mm.periodo, "origen": "auto", "matricula": mat_info(mm), "grupo": col_grupo(grupo)})
            continue
        if mid is None:
            mat_sin.append(mm)
            continue
        if mid in en_curso:
            warnings.append(f"Dos materias matriculadas apuntan a '{materias[mid].nombre}': {en_curso[mid].codigo} y {mm.codigo}.")
            mat_sin.append(mm)
            continue
        en_curso[mid] = mm
    if mat_sin:
        warnings.append("Matriculadas sin materia en el pensum: " + ", ".join(f"{m.codigo} {m.nombre}" for m in mat_sin))

    # --- estado de aprobación (los prerrequisitos dependen de él)
    def historial(mid: str) -> list[RegistroNota]:
        return sorted((notas[i] for i in asignadas.get(mid, [])), key=lambda r: r.periodo)

    def mejor(mid: str) -> RegistroNota | None:
        regs = historial(mid)
        aprob = [r for r in regs if r.aprobada]
        return aprob[-1] if aprob else (regs[-1] if regs else None)

    aprobadas = {mid for mid in materias if (b := mejor(mid)) and b.aprobada}
    for mid in set(en_curso) & aprobadas:
        warnings.append(f"'{materias[mid].nombre}' está matriculada pero ya figura aprobada.")

    # --- prerrequisitos efectivos = (oficiales - removidos) U extra
    efectivos: dict[str, set[str]] = {}
    for m in pensum:
        e = cfg_mats.get(m.id, {})
        oficiales = {r.id for r in m.prerrequisitos if r.id}
        ef = (oficiales - set(e.get("prereqs_removidos", []))) | set(e.get("prereqs_extra", []))
        ef.discard(m.id)
        desconocidos = {p for p in ef if p not in materias}
        if desconocidos:
            warnings.append(f"{m.nombre}: prerrequisitos que no existen en el pensum ({', '.join(sorted(desconocidos))}); se ignoran.")
        efectivos[m.id] = ef - desconocidos
    if atrapadas := _ciclos(efectivos):
        warnings.append("Dependencia circular de prerrequisitos entre: " + ", ".join(materias[i].nombre for i in atrapadas))

    celdas: list[CeldaMateria] = []
    for m in pensum:
        b = mejor(m.id)
        pend = [p for p in efectivos[m.id] if p not in aprobadas]
        # reprobada = hubo un intento CALIFICADO por debajo de 3.0 (cancelaciones/sin nota no cuentan)
        gslot = _grupo_slot(normalize_key(m.nombre))
        # reprobada solo aplica a materias regulares; en los cupos de electivas las perdidas no se consideran
        perdio = gslot not in ("fish", "complementaria") and any(r.definitiva is not None and not r.aprobada for r in historial(m.id))
        if m.id in aprobadas:
            estado = APROBADA
        elif m.id in en_curso:
            estado = EN_CURSO
            sin_cursar = [p for p in pend if p not in en_curso]
            if sin_cursar:
                warnings.append(f"'{m.nombre}' está matriculada sin tener aprobados: " + ", ".join(materias[p].nombre for p in sin_cursar))
        elif perdio:
            estado = REPROBADA
        elif pend:
            estado = BLOQUEADA
        else:
            estado = DISPONIBLE
        oficiales = {r.id for r in m.prerrequisitos if r.id}
        e = cfg_mats.get(m.id, {})
        mm = en_curso.get(m.id)
        celdas.append(CeldaMateria(
            id=m.id, codigo=m.codigo, nombre=m.nombre, creditos=m.creditos,
            semestre={"fish": SEMESTRE_FISH, "complementaria": SEMESTRE_ELECTIVAS}.get(gslot, m.semestre),
            estado=estado,
            nota=b.definitiva if b else None,
            periodo=b.periodo if b else (mm.periodo if mm else None),
            intentos=len(asignadas.get(m.id, [])),
            metodo=metodo.get(m.id),
            nombre_cursado=(b.nombre if b and normalize_key(b.nombre) != normalize_key(m.nombre) else
                            mm.nombre if mm and normalize_key(mm.nombre) != normalize_key(m.nombre) else None),
            prereqs=[
                {"id": p, "nombre": materias[p].nombre, "aprobado": p in aprobadas, "en_curso": p in en_curso,
                 "origen": "oficial" if p in oficiales else "personalizado"}
                for p in sorted(efectivos[m.id], key=lambda x: orden[x])
            ],
            aliases=list(e.get("aliases", [])),
            personalizada=bool(e),
            historial=[_intento(r) for r in historial(m.id)],
            matricula=mat_info(mm) if mm else None,
            desbloqueable=(estado == BLOQUEADA and bool(pend) and all(p in en_curso for p in pend)),
        ))

    extras.sort(key=lambda e: (e["periodo"] or "9999.9", e["id"]))  # cronológico; las matriculadas (periodo actual) al final
    adicionales = [CeldaMateria(
        id=f"extra:{e['id']}", codigo=e["id"], nombre=e["nombre"], creditos=e["creditos"],
        semestre=SEMESTRE_FISH if e["grupo"] == "fish" else SEMESTRE_ELECTIVAS,
        estado=e["estado"], nota=e["nota"], periodo=e["periodo"], metodo=f"adicional-{e['origen']}",
        personalizada=e["origen"] == "manual", adicional=True, matricula=e["matricula"],
    ) for e in extras]
    sin = [notas[i] for i in sorted(libres)]
    en_pensum = {i for lst in asignadas.values() for i in lst}
    grupos_extra: dict[str, dict[str, Any]] = {}
    for i, n in sorted(enumerate(notas), key=lambda t: (t[1].periodo, t[1].id)):
        if i not in en_pensum:
            g = grupos_extra.setdefault(f"nota:{n.id}", {"nombre": n.nombre, "historial": []})
            g["historial"].append(_intento(n))
    cred_total = sum(m.creditos for m in pensum)
    cred_apr = sum(m.creditos for m in pensum if m.id in aprobadas)
    cred_cur = sum(m.creditos for m in pensum if m.id in en_curso and m.id not in aprobadas)
    cred_hist = sum(n.creditos or 0 for n in notas if n.aprobada)
    cred_adic = sum(c.creditos for c in adicionales if c.estado == APROBADA)
    cred_req = sum(r["creditos"] for r in req_marcados if r["fuente"] == "historial" and r["estado"] == APROBADA)
    pond = [(n.definitiva, n.creditos) for n in notas if n.definitiva is not None and n.creditos]
    peso = sum(c for _, c in pond)
    metricas = {
        "creditos_pensum": cred_total,
        "creditos_aprobados": cred_apr,
        "creditos_en_curso": cred_cur,
        "creditos_historia": cred_hist,
        "creditos_adicionales": cred_adic,
        "electivas_reprobadas_ignoradas": electivas_ignoradas,
        "n_adicionales": sum(1 for c in adicionales if c.estado == APROBADA),
        "pct_avance": (cred_apr / cred_total * 100) if cred_total else 0.0,
        "pct_proyectado": ((cred_apr + cred_cur) / cred_total * 100) if cred_total else 0.0,
        "promedio_ponderado": (sum(d * c for d, c in pond) / peso) if peso else None,
        "n_total": len(celdas),
        **{f"n_{e}": sum(1 for c in celdas if c.estado == e) for e in ESTADOS_ORDEN},
        "n_desbloqueables": sum(1 for c in celdas if c.desbloqueable),
    }
    if cred_hist != cred_apr + cred_adic + cred_req:
        warnings.append(
            f"Créditos aprobados en la historia ({cred_hist}) ≠ pensum ({cred_apr}) + adicionales ({cred_adic}) "
            f"+ requisitos marcados ({cred_req}): hay {len(sin)} registro(s) sin correspondencia. "
            "Revisa la página de Configuración."
        )
    return MatrizResult(celdas, sin, mat_sin, metricas, warnings, adicionales, req_marcados, grupos_extra)


def matriz_a_dataframe(res: MatrizResult) -> pd.DataFrame:
    return pd.DataFrame([{
        "Semestre": {SEMESTRE_ELECTIVAS: "Electivas", SEMESTRE_FISH: "Electivas Fish"}.get(c.semestre, str(c.semestre)),
        "Adicional": "Sí" if c.adicional else "",
        "Código": c.codigo,
        "Materia": c.nombre,
        "Créditos": c.creditos,
        "Estado": c.estado.replace("_", " ").capitalize(),
        "Nota": c.nota,
        "Periodo": c.periodo,
        "Sección": (c.matricula or {}).get("seccion", ""),
        "Docente": (c.matricula or {}).get("docentes", ""),
        "Horario": " · ".join((c.matricula or {}).get("horarios", [])),
        "Cursada como": c.nombre_cursado or "",
        "Emparejada por": c.metodo or "",
        "Prerrequisitos": "; ".join(p["nombre"] + ("" if p["aprobado"] else " (cursando)" if p["en_curso"] else " (pend.)") for p in c.prereqs),
    } for celdas in res.por_semestre().values() for c in celdas])
