"""Extracción (solo parseo, sin red) del HTML de SIMCA: pensum y notas.

Estrategia anti-fragilidad:
  * Se localiza cada tabla por su ID estable (o sufijo del ID) y NO por ``j_idtNNNN``.
  * Cada fila se procesa dentro de try/except: una fila rara genera una advertencia,
    no tumba toda la extracción.
  * Si cambia el patrón de los contenedores ``overlayRequisito`` se usa un fallback
    posicional y se deja constancia en ``warnings``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, FeatureNotFound, Tag

from .models import Horario, MateriaMatriculada, MateriaPensum, RegistroNota, Requisito, SEMESTRE_ELECTIVAS
from .text_utils import clean_text, normalize_key, parse_float, parse_int

PENSUM_TABLE_ID = "formMateriasPendientes:materiaspendientes"
NOTAS_BODY_SUFFIX = "hAcademicaNotasEstudianteDT_data"
REQ_GRADO_BODY_SUFFIX = "hAcademicaRequisitosGradoDT_data"
MATRICULADAS_BODY_RE = re.compile(r"tabView:materias_data$")
_PERIODO_RE = re.compile(r"\d{4}\.\d")
_TRAILING_DIGITS_RE = re.compile(r"(\d+)$")

_ESTUDIANTE_LABELS = {
    "nombres": "nombres",
    "identificacion": "identificacion",
    "tipo de identificacion": "tipo_identificacion",
    "codigo": "codigo",
    "programa": "programa",
    "semestre": "semestre",
    "promedio carrera": "promedio_carrera",
    "promedio semestre anterior": "promedio_semestre_anterior",
    "estado": "estado",
}  # identificación y código se guardan a pedido del usuario (el snapshot vive en un directorio privado).


class ParseError(RuntimeError):
    """El HTML no contiene la estructura mínima esperada (probable cambio de DOM)."""


@dataclass
class PensumResult:
    materias: list[MateriaPensum]
    warnings: list[str] = field(default_factory=list)
    requisitos_grado: list[dict[str, str]] = field(default_factory=list)  # [{codigo, nombre}] oficiales


@dataclass
class MatriculadasResult:
    materias: list[MateriaMatriculada]
    periodo: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class NotasResult:
    registros: list[RegistroNota]
    promedios: dict[str, float]
    requisitos_grado: list[dict[str, Any]]
    estudiante: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(html, "html.parser")


def _classes(tag: Tag) -> list[str]:
    return tag.get("class") or []


# --------------------------------------------------------------------------- pensum
def _parse_requisito(raw: str, warnings: list[str], contexto: str) -> Requisito | None:
    """``'29296--CODIGO--A25034--Estadística Descriptiva'`` -> Requisito."""
    raw = clean_text(raw)
    if not raw:
        return None
    if "--CODIGO--" in raw:
        id_part, rest = raw.split("--CODIGO--", 1)
        codigo, _, nombre = rest.partition("--")
        return Requisito(
            id=clean_text(id_part) or None,
            codigo=clean_text(codigo) or None,
            nombre=clean_text(nombre) or clean_text(codigo),
        )
    warnings.append(f"{contexto}: formato de prerrequisito inesperado '{raw[:60]}' (se guarda solo el texto).")
    return Requisito(id=None, codigo=None, nombre=raw)


def _extract_requisitos(div: Tag | None, warnings: list[str], contexto: str) -> list[Requisito]:
    if div is None:
        return []
    out: list[Requisito] = []
    for span in div.select("li span"):
        req = _parse_requisito(span.get_text(), warnings, contexto)
        if req:
            out.append(req)
    return out


def parse_pensum_html(html: str) -> PensumResult:
    soup = _soup(html)
    warnings: list[str] = []

    table = soup.find(id=PENSUM_TABLE_ID)
    if table is None:
        table = soup.find(id=re.compile(r"materiaspendientes$"))
        if table is not None:
            warnings.append("No se halló el ID exacto de la tabla de pensum; se usó coincidencia por sufijo.")
    if table is None:
        raise ParseError(f"No se encontró la tabla '{PENSUM_TABLE_ID}' (¿cambió el DOM de SIMCA?).")

    body = table.find("tbody", id=re.compile(r"_data$")) or table.find("tbody")
    if body is None:
        raise ParseError("La tabla de pensum no tiene <tbody> de datos.")

    materias: dict[str, MateriaPensum] = {}
    semestre = SEMESTRE_ELECTIVAS
    overlays_vistos = 0

    for n_fila, row in enumerate(body.find_all("tr", recursive=False), start=1):
        try:
            tds = row.find_all("td", recursive=False)
            if len(tds) < 4:
                continue  # fila vacía / mensaje "no records"
            tiene_sem = "semestre" in _classes(tds[0]) or len(tds) >= 5
            offset = 1 if tiene_sem else 0
            if tiene_sem:
                semestre = parse_int(tds[0].get_text()) or SEMESTRE_ELECTIVAS
            codigo = clean_text(tds[offset].get_text())
            creditos = parse_int(tds[offset + 1].get_text())
            nombre = clean_text(tds[offset + 2].get_text())
            opciones = tds[offset + 3] if len(tds) > offset + 3 else row
            if not codigo or not nombre:
                warnings.append(f"Fila {n_fila}: código o nombre vacío; se omite.")
                continue

            overlays = opciones.find_all("div", class_="overlayRequisito")
            overlays_vistos += len(overlays)
            pre_div = next((d for d in overlays if str(d.get("id", "")).startswith("prerrequisitos")), None)
            co_div = next((d for d in overlays if str(d.get("id", "")).startswith("correquisitos")), None)
            if pre_div is None and overlays:  # fallback posicional
                pre_div = overlays[0]
                co_div = overlays[1] if len(overlays) > 1 else None
                warnings.append(f"Fila {n_fila} ({codigo}): ids de overlayRequisito inesperados; se usó orden posicional.")

            id_interno = None
            for div in (pre_div, co_div):
                if div is not None and (m := _TRAILING_DIGITS_RE.search(str(div.get("id", "")))):
                    id_interno = m.group(1)
                    break
            if id_interno is None:
                id_interno = codigo
                warnings.append(f"{codigo}: sin ID interno en overlayRequisito; se usa el código como ID (el cruce con notas puede fallar).")

            if id_interno in materias:
                warnings.append(f"{codigo}: ID interno duplicado ({id_interno}); se conserva la primera aparición.")
                continue

            materias[id_interno] = MateriaPensum(
                id=id_interno,
                codigo=codigo,
                nombre=nombre,
                creditos=creditos or 0,
                semestre=semestre,
                prerrequisitos=_extract_requisitos(pre_div, warnings, codigo),
                correquisitos=_extract_requisitos(co_div, warnings, codigo),
            )
        except Exception as exc:  # noqa: BLE001 - una fila mala no debe tumbar todo
            warnings.append(f"Fila {n_fila}: error inesperado ({type(exc).__name__}: {exc}).")

    if not materias:
        raise ParseError("La tabla de pensum no produjo ninguna materia.")
    if overlays_vistos == 0:
        warnings.append(
            "No se encontraron contenedores 'overlayRequisito': los prerrequisitos pueden estar INCOMPLETOS "
            "(todas las materias aparecerían como disponibles)."
        )
    return PensumResult(materias=list(materias.values()), warnings=warnings,
                        requisitos_grado=_parse_requisitos_oficiales(soup, warnings))


def _parse_requisitos_oficiales(soup: BeautifulSoup, warnings: list[str]) -> list[dict[str, str]]:
    """Requisitos de grado del pénsum (AFF, ECAES, idioma...). No es fatal si faltan."""
    body = soup.find("tbody", id=re.compile(r"requisitosGrado_data$"))
    if body is None:
        warnings.append("No se encontró la lista oficial de requisitos de grado en el pénsum.")
        return []
    out: list[dict[str, str]] = []
    vistos: set[str] = set()
    for tr in body.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) >= 2:
            codigo, nombre = clean_text(tds[0].get_text()), clean_text(tds[1].get_text())
            if nombre and normalize_key(nombre) not in vistos:  # SIMCA repite la lista varias veces
                vistos.add(normalize_key(nombre))
                out.append({"codigo": codigo, "nombre": nombre})
    return out


# --------------------------------------------------------------------------- tablas genéricas
def expand_grid(rows: list[Tag]) -> list[list[Tag]]:
    """Expande rowspan/colspan: cada fila devuelve una celda por columna lógica.

    Las celdas combinadas se repiten (mismo objeto Tag) en las filas que cubren; así la
    posición de cada columna es siempre la del encabezado, tenga o no la fila la celda propia.
    """
    pendientes: dict[int, tuple[Tag, int]] = {}
    grid: list[list[Tag]] = []
    for tr in rows:
        celdas = iter(tr.find_all(["td", "th"], recursive=False))
        fila: list[Tag] = []
        col = 0
        while True:
            if col in pendientes:
                celda, resto = pendientes[col]
                fila.append(celda)
                if resto <= 1:
                    del pendientes[col]
                else:
                    pendientes[col] = (celda, resto - 1)
                col += 1
                continue
            celda = next(celdas, None)
            if celda is None:
                break
            rs = min(max(parse_int(celda.get("rowspan")) or 1, 1), 500)
            cs = min(max(parse_int(celda.get("colspan")) or 1, 1), 50)
            for _ in range(cs):
                fila.append(celda)
                if rs > 1:
                    pendientes[col] = (celda, rs - 1)
                col += 1
        grid.append(fila)
    return grid


def _headers_for(body: Tag) -> list[str]:
    """Encabezados normalizados (``'id materia'``, ``'definitiva'``...) de la tabla que contiene ``body``."""
    nodo: Tag | None = body.find_parent("table")
    while nodo is not None:
        thead = nodo.find("thead")
        if thead is not None and (ths := thead.find_all("th")):
            return [normalize_key(th.get_text(" ")) for th in ths]
        nodo = nodo.find_parent()
    return []


def _col(headers: list[str], *nombres: str) -> int | None:
    for n in nombres:
        if n in headers:
            return headers.index(n)
    return None


def _es_fila_mensaje(cells: list[Tag]) -> bool:
    """Fila 'No records found': una sola celda con colspan."""
    return len({id(c) for c in cells}) <= 1


def _txt(cells: list[Tag], i: int | None) -> str:
    return clean_text(cells[i].get_text(" ")) if i is not None and i < len(cells) else ""


# --------------------------------------------------------------------------- notas
def parse_estudiante(html: str) -> dict[str, Any]:
    soup = _soup(html)
    out: dict[str, Any] = {}
    for tr in soup.select('table[id*="formDatosEstudiante"] tr'):
        tds = tr.find_all("td", recursive=False)
        if len(tds) == 2:
            clave = _ESTUDIANTE_LABELS.get(normalize_key(tds[0].get_text()))
            if clave:
                out[clave] = clean_text(tds[1].get_text())
    for k in ("promedio_carrera", "promedio_semestre_anterior"):
        if k in out:
            out[k] = parse_float(out[k])
    return out


def _parse_requisitos_grado(soup: BeautifulSoup, warnings: list[str]) -> list[dict[str, Any]]:
    body = soup.find("tbody", id=re.compile(REQ_GRADO_BODY_SUFFIX + "$"))
    if body is None:
        return []
    headers = _headers_for(body)
    i_per, i_id = _col(headers, "periodo"), _col(headers, "id materia")
    i_nom, i_cred, i_def = _col(headers, "materia"), _col(headers, "creditos"), _col(headers, "definitiva")
    if i_id is None or i_nom is None or i_def is None:
        warnings.append(f"Requisitos de grado: encabezados no reconocidos {headers}.")
        return []
    out: list[dict[str, Any]] = []
    for cells in expand_grid(body.find_all("tr", recursive=False)):
        try:
            if _es_fila_mensaje(cells) or len(cells) <= max(i_id, i_nom, i_def):
                continue
            definitiva = _txt(cells, i_def)
            out.append({
                "periodo": _txt(cells, i_per),
                "id": _txt(cells, i_id),
                "nombre": _txt(cells, i_nom).rstrip("* ").strip(),
                "creditos": parse_int(_txt(cells, i_cred)),
                "definitiva": definitiva,
                "aprobado": definitiva.upper() == "A" or (parse_float(definitiva) or 0) >= 3.0,
            })
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Requisito de grado: fila ilegible ({exc}).")
    return out


def parse_notas_html(html: str) -> NotasResult:
    """Parsea la historia académica ubicando cada columna por su ENCABEZADO.

    Las columnas varían entre estudiantes: quien tiene habilitaciones ve además
    «Habilitación» y «Tipo», y la posición de «Definitiva» cambia. Por eso nunca se
    indexa por posición fija; la nota que decide es siempre «Definitiva».
    """
    soup = _soup(html)
    warnings: list[str] = []

    body = soup.find("tbody", id=re.compile(NOTAS_BODY_SUFFIX + "$"))
    if body is None:
        raise ParseError(f"No se encontró la tabla de historia académica (*{NOTAS_BODY_SUFFIX}).")

    headers = _headers_for(body)
    i_per, i_id = _col(headers, "periodo"), _col(headers, "id materia")
    i_nom, i_cred = _col(headers, "materia"), _col(headers, "creditos")
    i_sem, i_nota = _col(headers, "semestre"), _col(headers, "nota")
    i_hab, i_def, i_tipo = _col(headers, "habilitacion"), _col(headers, "definitiva"), _col(headers, "tipo")
    faltan = [n for n, i in (("ID Materia", i_id), ("Materia", i_nom), ("Definitiva", i_def)) if i is None]
    if faltan:
        raise ParseError(f"Encabezados de la historia no reconocidos: faltan {faltan}; encabezados hallados: {headers}")

    filas = body.find_all("tr", recursive=False)
    registros: list[RegistroNota] = []
    promedios: dict[str, float] = {}
    filas_datos = 0

    for n_fila, cells in enumerate(expand_grid(filas), start=1):
        try:
            if not cells or _es_fila_mensaje(cells):
                continue
            filas_datos += 1
            if len(cells) < len(headers):
                warnings.append(f"Notas fila {n_fila}: {len(cells)} columnas (se esperaban {len(headers)}); se omite.")
                continue
            periodo = ""
            for c in cells:  # la celda de periodo (con promedio) y la oculta contienen 'AAAA.S'
                if m := _PERIODO_RE.search(clean_text(c.get_text(" "))):
                    periodo = m.group(0)
                    break
            if periodo and i_per is not None and (bold := cells[i_per].find("b")):
                if (prom := parse_float(bold.get_text())) is not None:
                    promedios[periodo] = prom
            id_, nombre = _txt(cells, i_id), _txt(cells, i_nom)
            if not id_ or not nombre:
                continue
            registros.append(RegistroNota(
                periodo=periodo,
                id=id_,
                nombre=nombre,
                creditos=parse_int(_txt(cells, i_cred)),
                semestre_cursado=parse_int(_txt(cells, i_sem)),
                nota=parse_float(_txt(cells, i_nota)),
                definitiva=parse_float(_txt(cells, i_def)),
                habilitacion=parse_float(_txt(cells, i_hab)),
                tipo=_txt(cells, i_tipo),
            ))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Notas fila {n_fila}: error inesperado ({type(exc).__name__}: {exc}).")

    if not registros:
        if filas_datos:
            detalle = " | ".join(warnings[:3]) or "sin detalle"
            raise ParseError(f"La tabla de historia tiene {filas_datos} fila(s) de datos pero ninguna reconocible. Detalle: {detalle}")
        warnings.append("La historia académica está vacía: el estudiante no tiene notas registradas en SIMCA.")

    return NotasResult(
        registros=registros,
        promedios=promedios,
        requisitos_grado=_parse_requisitos_grado(soup, warnings),
        estudiante=parse_estudiante(html),
        warnings=warnings,
    )


# --------------------------------------------------------------------------- matriculadas
def _find_matriculadas_body(soup: BeautifulSoup) -> Tag | None:
    body = soup.find("tbody", id=MATRICULADAS_BODY_RE)
    if body is not None:
        return body
    for tabla in soup.find_all("table"):  # fallback por encabezados (si cambia el id de la pestaña)
        if tabla.find("table") is None:
            heads = [normalize_key(th.get_text(" ")) for th in tabla.find_all("th")]
            if "codigo materia" in heads and "id grupo" in heads:
                return tabla.find("tbody")
    return None


def parse_matriculadas_html(html: str) -> MatriculadasResult:
    """Materias matriculadas del periodo actual; une las filas de horario de una misma materia."""
    soup = _soup(html)
    warnings: list[str] = []
    body = _find_matriculadas_body(soup)
    if body is None:
        raise ParseError("No se encontró la tabla de materias matriculadas (¿cambió el DOM o falta la sección 'Materias'?).")

    headers = _headers_for(body)
    i_per, i_sem = _col(headers, "periodo matricula", "periodo"), _col(headers, "semestre")
    i_cod, i_nom = _col(headers, "codigo materia"), _col(headers, "materia")
    i_sec, i_gru = _col(headers, "sec", "seccion"), _col(headers, "id grupo")
    i_doc, i_rep = _col(headers, "docentes", "docente"), _col(headers, "repeticion")
    i_dia, i_hor = _col(headers, "dia"), _col(headers, "horario")
    i_sal, i_ubi = _col(headers, "salon"), _col(headers, "ubicacion")
    if i_cod is None or i_nom is None:
        raise ParseError(f"Encabezados de matriculadas no reconocidos: {headers}")

    grupos: dict[tuple[str, str], MateriaMatriculada] = {}
    for n_fila, cells in enumerate(expand_grid(body.find_all("tr", recursive=False)), start=1):
        try:
            if not cells or _es_fila_mensaje(cells):
                continue
            codigo, nombre = _txt(cells, i_cod), _txt(cells, i_nom)
            if not codigo or not nombre:
                continue
            clave = (codigo, _txt(cells, i_gru) or normalize_key(nombre))
            mat = grupos.get(clave)
            if mat is None:
                mat = grupos[clave] = MateriaMatriculada(
                    periodo=_txt(cells, i_per), codigo=codigo, nombre=nombre,
                    semestre=parse_int(_txt(cells, i_sem)), seccion=_txt(cells, i_sec),
                    id_grupo=_txt(cells, i_gru), docentes=_txt(cells, i_doc),
                    repeticion=parse_int(_txt(cells, i_rep)) or 0,
                )
            h = Horario(_txt(cells, i_dia), _txt(cells, i_hor), _txt(cells, i_sal), _txt(cells, i_ubi))
            if (h.dia or h.horario) and h not in mat.horarios:
                mat.horarios.append(h)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Matriculadas fila {n_fila}: error inesperado ({type(exc).__name__}: {exc}).")

    materias = list(grupos.values())
    if not materias:
        warnings.append("El estudiante no tiene materias matriculadas en el periodo actual.")
    periodos = [m.periodo for m in materias if m.periodo]
    return MatriculadasResult(materias, max(set(periodos), key=periodos.count) if periodos else None, warnings)
