"""HTML de la matriz (curriculum grid). Todo texto dinámico se escapa con html.escape."""
from __future__ import annotations

from html import escape

from .matrix import APROBADA, BLOQUEADA, DISPONIBLE, EN_CURSO, REPROBADA, CeldaMateria, MatrizResult
from .models import SEMESTRE_ELECTIVAS, SEMESTRE_FISH

ESTADOS = {
    APROBADA: ("Aprobada", "#2e9e5b"),
    EN_CURSO: ("En curso", "#3b82f6"),
    DISPONIBLE: ("Disponible", "#e0a100"),
    BLOQUEADA: ("Bloqueada", "#8a8f98"),
    REPROBADA: ("Reprobada", "#d64545"),
}

CSS = (
    "<style>"
    ".sx-grid{display:flex;gap:10px;overflow-x:auto;align-items:flex-start;padding-bottom:8px}"
    ".sx-col{min-width:200px;flex:1 0 200px}"
    ".sx-head{font-weight:700;font-size:.9rem;padding:4px 2px 6px;border-bottom:2px solid rgba(128,128,128,.35);margin-bottom:8px}"
    ".sx-head small{font-weight:400;opacity:.7;display:block}"
    ".sx-card{border-left:5px solid var(--c);background:rgba(128,128,128,.10);border-radius:6px;padding:6px 8px;margin-bottom:8px;font-size:.82rem;line-height:1.25}"
    ".sx-name{font-weight:600}"
    ".sx-meta{opacity:.75;font-size:.75rem}"
    ".sx-badge{display:inline-block;margin-top:3px;padding:0 6px;border-radius:9px;background:var(--c);color:#fff;font-size:.72rem;font-weight:600}"
    ".sx-alias{font-style:italic;opacity:.8;font-size:.74rem}"
    ".sx-legend span{margin-right:14px;font-size:.85rem}"
    ".sx-dot{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:4px;vertical-align:-1px}"
    "</style>"
)


def _tooltip(c: CeldaMateria) -> str:
    partes = [f"{c.nombre} ({c.codigo})"]
    if c.prereqs:
        partes.append("Prerrequisitos: " + ", ".join(
            f"{p['nombre']} {'✔' if p['aprobado'] else '✖'}{' *' if p['origen'] == 'personalizado' else ''}" for p in c.prereqs))
    else:
        partes.append("Sin prerrequisitos")
    if c.metodo:
        partes.append(f"Emparejada por: {c.metodo}")
    if c.matricula:
        partes.append(f"Docente: {c.matricula['docentes']}")
    return " | ".join(partes)


_DIAS = {"LUNES": "Lun", "MARTES": "Mar", "MIERCOLES": "Mié", "MIÉRCOLES": "Mié", "JUEVES": "Jue",
         "VIERNES": "Vie", "SABADO": "Sáb", "SÁBADO": "Sáb", "DOMINGO": "Dom"}


def _horario_corto(horarios: list[str]) -> str:
    out = []
    for h in horarios[:3]:
        dia, _, rango = h.partition(" ")
        out.append(f"{_DIAS.get(dia.upper(), dia[:3])} {rango}")
    return " · ".join(out)


def _card(c: CeldaMateria) -> str:
    etiqueta, color = ESTADOS[c.estado]
    nota = f" · {c.nota:.1f} · {escape(c.periodo or '')}" if c.nota is not None else ""
    if c.estado == EN_CURSO and c.matricula:
        nota = f" · Sec. {escape(c.matricula['seccion'])}"
    pend = [p for p in c.prereqs if not p["aprobado"]]
    extra = ""
    if c.nombre_cursado:
        extra += f"<div class='sx-alias'>Cursada como: {escape(c.nombre_cursado)}</div>"
    if c.estado == EN_CURSO and c.matricula and c.matricula["horarios"]:
        extra += f"<div class='sx-meta'>{escape(_horario_corto(c.matricula['horarios']))}</div>"
    if c.estado == BLOQUEADA and pend:
        extra += f"<div class='sx-meta'>Falta: {escape(', '.join(p['nombre'] for p in pend))}</div>"
    if c.desbloqueable:
        extra += "<div class='sx-meta'>🔓 Se habilita al aprobar lo que cursa ahora</div>"
    if c.adicional:
        extra += "<div class='sx-meta'>➕ Adicional (fuera de los cupos del pensum)</div>"
    star = " ✎" if c.personalizada else ""
    titulo, sub = c.nombre, c.codigo
    if c.semestre == SEMESTRE_ELECTIVAS and c.nombre_cursado:  # electiva: lo importante es cuál cursó
        titulo, sub = c.nombre_cursado, f"{c.nombre} · {c.codigo}"
        extra = extra.replace(f"<div class='sx-alias'>Cursada como: {escape(c.nombre_cursado)}</div>", "")
    return (
        f"<div class='sx-card' style='--c:{color}' title='{escape(_tooltip(c), quote=True)}'>"
        f"<div class='sx-name'>{escape(titulo)}{star}</div>"
        f"<div class='sx-meta'>{escape(sub)} · {f'{c.creditos} cr' if c.creditos else 'cr s/d'}</div>"
        f"<span class='sx-badge'>{etiqueta}{nota}</span>{extra}</div>"
    )


def render_matriz_html(res: MatrizResult, estados: set[str] | None = None, incluir_electivas: bool = True) -> str:
    estados = estados or set(ESTADOS)
    cols: list[str] = []
    for sem, celdas in res.por_semestre().items():
        if sem in (SEMESTRE_ELECTIVAS, SEMESTRE_FISH) and not incluir_electivas:
            continue
        visibles = [c for c in celdas if c.estado in estados]
        if not visibles:
            continue
        titulo = {SEMESTRE_ELECTIVAS: "Electivas", SEMESTRE_FISH: "Electivas Fish"}.get(sem, f"Semestre {sem}")
        cupos = [c for c in celdas if not c.adicional]
        extras = len(celdas) - len(cupos)
        if sem in (SEMESTRE_ELECTIVAS, SEMESTRE_FISH):  # cupos ocupados = cursadas o en curso (las perdidas no cuentan)
            ocupados = sum(1 for c in cupos if c.estado in (APROBADA, EN_CURSO))
            resumen = f"{ocupados}/{len(cupos)} cupos" + (f" · +{extras} adicional(es)" if extras else "") + " · cronológico"
        else:
            resumen = f"{sum(1 for c in celdas if c.estado == APROBADA)}/{len(celdas)} aprobadas · {sum(c.creditos for c in celdas)} cr"
        cols.append(
            f"<div class='sx-col'><div class='sx-head'>{titulo}<small>{resumen}</small></div>"
            + "".join(_card(c) for c in visibles) + "</div>"
        )
    cuerpo = "".join(cols) or "<p>No hay materias para los filtros seleccionados.</p>"
    return CSS + f"<div class='sx-grid'>{cuerpo}</div>"


def render_leyenda_html() -> str:
    items = "".join(
        f"<span><i class='sx-dot' style='background:{col}'></i>{nombre}</span>" for nombre, col in ESTADOS.values())
    return CSS + f"<div class='sx-legend'>{items}<span>✎ materia personalizada</span></div>"
