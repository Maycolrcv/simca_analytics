"""Pruebas con HTML sintético que replica la estructura real de SIMCA (sin datos personales)."""
import json
import threading
from pathlib import Path

import pytest

from simca import config_store as cs
from simca.matrix import APROBADA, BLOQUEADA, DISPONIBLE, EN_CURSO, construir_matriz
from simca.models import MateriaPensum, RegistroNota
from simca.parsers import ParseError, parse_matriculadas_html, parse_notas_html, parse_pensum_html
from simca.text_utils import clean_text, normalize_key, parse_float

PENSUM = """<div id="formMateriasPendientes:materiaspendientes"><table><tbody id="formMateriasPendientes:materiaspendientes_data">
<tr data-ri="0"><td class="semestre" rowspan="2">1</td><td>A1</td><td>3</td><td>Calculo  I</td><td>
 <div class="overlayRequisito" id="prerrequisitos100"><ul><li><span>x</span></li></ul><div class="ui-datalist-empty-message">No records found.</div></div>
 <div class="overlayRequisito" id="correquisitos100"></div></td></tr>
<tr data-ri="1"><td>A2</td><td>3</td><td> Calculo II </td><td>
 <div class="overlayRequisito" id="prerrequisitos101"><ul><li><span>100--CODIGO--A1--Calculo I</span></li></ul></div>
 <div class="overlayRequisito" id="correquisitos101"></div></td></tr>
</tbody></table></div>"""

THEAD_BASE = ("<thead><tr><th class='periodo'>Periodo</th><th style='display:none'>Periodo</th><th>ID Materia</th><th>Materia</th>"
              "<th>Créditos</th><th>Semestre</th><th>Nota</th>{extra_h}<th>Definitiva</th>{tipo_h}</tr></thead>")


def _tabla_notas(con_hab: bool) -> str:
    head = THEAD_BASE.format(extra_h="<th>Habilitación</th>" if con_hab else "", tipo_h="<th>Tipo</th>" if con_hab else "")
    hab = lambda h: f"<td>{h}</td>" if con_hab else ""          # noqa: E731
    tipo = lambda t: f"<td>{t}</td>" if con_hab else ""         # noqa: E731
    return f"""<table>{head}<tbody id="j_idt1:hAcademicaNotasEstudianteDT_data">
<tr><td class="periodo" rowspan="2">2022.2<div><br/>Promedio: <b>3,7</b></div></td><td style="display:none">2022.2</td><td><span>100</span></td><td>Calculo I</td><td><span>3</span></td><td>1</td><td><span>  2.9</span></td>{hab("4.0")}<td><span>   4.0</span></td>{tipo("HABILITACION")}</tr>
<tr><td style="display:none">2022.2</td><td><span>999</span></td><td>Perdida</td><td><span>3</span></td><td>1</td><td><span>2.0</span></td>{hab("")}<td><span>2.0</span></td>{tipo("")}</tr>
</tbody></table>"""


NOTAS = _tabla_notas(con_hab=False)
NOTAS_HAB = _tabla_notas(con_hab=True)

MATRICULADAS = """<table><thead><tr><th>Periodo Matrícula</th><th>Semestre</th><th>Código Materia</th><th>Materia</th><th>Sec.</th><th>ID Grupo</th>
<th>Docentes</th><th>Repetición</th><th>Día</th><th>Horario</th><th>Salón</th><th>Ubicación</th></tr></thead>
<tbody id="j_idt9:tabView:materias_data">
<tr><td rowspan="1">2026.2</td><td rowspan="1">9</td><td rowspan="1">A2</td><td rowspan="2">Calculo II</td><td rowspan="2">B</td><td rowspan="2">77</td><td rowspan="2">DOC  UNO </td><td rowspan="2">0</td><td>LUNES</td><td>16:00-18:00</td><td>Salón 1</td><td>FAC</td></tr>
<tr><td>2026.2</td><td>9</td><td>A2</td><td>JUEVES</td><td>14:00-16:00</td><td>Salón 2</td><td>FAC</td></tr>
<tr><td>2026.2</td><td></td><td>M5</td><td>Optativa de Mercadeo II</td><td>A</td><td>88</td><td>DOC DOS</td><td>0</td><td>VIERNES</td><td>07:00-11:00</td><td>S3</td><td>FAC</td></tr>
</tbody></table>"""


def test_text_utils():
    assert clean_text(" a\xa0 b  ") == "a b" and clean_text(None) == "" and clean_text(float("nan")) == ""
    assert normalize_key("Formulación  y Evaluación") == "formulacion y evaluacion"
    assert parse_float("4,3") == 4.3 and parse_float("A") is None


def test_parse_pensum_prereqs_y_semestre():
    r = parse_pensum_html(PENSUM)
    assert [m.id for m in r.materias] == ["100", "101"]
    assert r.materias[1].semestre == 1 and r.materias[1].nombre == "Calculo II"
    assert r.materias[0].prerrequisitos[0].id is None    # formato desconocido: se conserva el texto, sin ID
    assert r.materias[1].prerrequisitos[0].id == "100"
    assert any("formato de prerrequisito" in w for w in r.warnings)


def test_parse_pensum_sin_overlays_advierte():
    r = parse_pensum_html(PENSUM.replace("overlayRequisito", "otra"))
    assert any("overlayRequisito" in w for w in r.warnings)


def test_parse_pensum_dom_cambiado():
    with pytest.raises(ParseError):
        parse_pensum_html("<html><body>nada</body></html>")


def test_parse_notas_alineacion():
    r = parse_notas_html(NOTAS)
    assert [(x.periodo, x.id, x.nombre, x.definitiva) for x in r.registros] == [("2022.2", "100", "Calculo I", 4.0), ("2022.2", "999", "Perdida", 2.0)]
    assert r.promedios == {"2022.2": 3.7}
    assert r.registros[0].aprobada and not r.registros[1].aprobada


def test_notas_con_habilitacion_toma_definitiva_sin_importar_posicion():
    """Con columnas Habilitación/Tipo la Definitiva se corre de lugar; debe seguir leyéndose bien."""
    base, hab = parse_notas_html(NOTAS).registros, parse_notas_html(NOTAS_HAB).registros
    assert [r.definitiva for r in hab] == [r.definitiva for r in base] == [4.0, 2.0]
    assert hab[0].nota == 2.9 and hab[0].habilitacion == 4.0 and hab[0].tipo == "HABILITACION" and hab[0].aprobada


def test_notas_sin_encabezados_falla_con_mensaje_claro():
    sin_head = NOTAS.replace("<thead>", "<x>").replace("</thead>", "</x>")
    with pytest.raises(ParseError, match="Encabezados"):
        parse_notas_html(sin_head)


def test_parse_matriculadas_rowspan_y_horarios():
    r = parse_matriculadas_html(MATRICULADAS)
    assert r.periodo == "2026.2" and len(r.materias) == 2
    calc, opt = r.materias
    assert (calc.codigo, calc.nombre, calc.seccion, calc.id_grupo, calc.docentes, calc.semestre) == ("A2", "Calculo II", "B", "77", "DOC UNO", 9)
    assert [(h.dia, h.horario) for h in calc.horarios] == [("LUNES", "16:00-18:00"), ("JUEVES", "14:00-16:00")]
    assert opt.semestre is None


def test_matriculadas_vacia_y_dom_cambiado():
    vacia = MATRICULADAS.split("<tbody")[0] + '<tbody id="x:tabView:materias_data"><tr><td colspan="12">No records found.</td></tr></tbody></table>'
    r = parse_matriculadas_html(vacia)
    assert r.materias == [] and r.warnings
    with pytest.raises(ParseError):
        parse_matriculadas_html("<html></html>")


def test_matriz_en_curso_y_desbloqueable():
    p = parse_pensum_html(PENSUM).materias
    n = parse_notas_html(NOTAS).registros                       # Calculo I aprobada (100)
    mats = parse_matriculadas_html(MATRICULADAS).materias       # Calculo II (código A2) en curso
    res = construir_matriz(p, n, None, mats)
    c = {x.id: x for x in res.celdas}
    assert c["101"].estado == EN_CURSO and c["101"].matricula["seccion"] == "B"
    assert res.metricas["n_en_curso"] == 1 and res.metricas["creditos_en_curso"] == 3
    assert "Optativa de Mercadeo II" in [m.nombre for m in res.matriculadas_sin_correspondencia]  # sin cupo en este pensum mínimo


def test_optativa_matriculada_usa_su_numeral():
    p = [MateriaPensum("1", "M1", "Optativa Profesional I", 3, 8), MateriaPensum("2", "M2", "Optativa Profesional II", 3, 9),
         MateriaPensum("3", "M3", "Optativa Profesional III", 3, 10)]
    from simca.models import MateriaMatriculada
    mats = [MateriaMatriculada("2026.2", "M9", "Optativa de Mercadeo III"), MateriaMatriculada("2026.2", "M8", "Optativa de Mercadeo II")]
    c = {x.id: x for x in construir_matriz(p, [], None, mats).celdas}
    assert c["3"].estado == EN_CURSO and c["3"].nombre_cursado == "Optativa de Mercadeo III"
    assert c["2"].estado == EN_CURSO and c["1"].estado == DISPONIBLE


def test_intento_sin_nota_no_cuenta_como_reprobada():
    p = [MateriaPensum("1", "A", "Algo", 3, 1)]
    n = [RegistroNota("2026.1", "1", "Algo", 3, 1, None, None)]   # cancelada / sin calificar
    assert construir_matriz(p, n, None).celdas[0].estado == DISPONIBLE


def test_matriz_estados_y_alias():
    p = parse_pensum_html(PENSUM).materias
    n = parse_notas_html(NOTAS).registros
    res = construir_matriz(p, n, None)
    estados = {c.id: c.estado for c in res.celdas}
    assert estados == {"100": APROBADA, "101": DISPONIBLE}
    # prerrequisito personalizado imposible -> bloquea; alias recupera una nota renombrada
    cfg = {"materias": {"101": {"aliases": ["Perdida"], "prereqs_extra": [], "prereqs_removidos": []}}}
    assert construir_matriz(p, n, cfg).celdas[1].metodo == "alias"
    n2 = [RegistroNota("2022.2", "5", "Calc 1 viejo", 3, 1, 3.5, 3.5)]
    cfg2 = {"materias": {"100": {"aliases": ["Calc 1 viejo"]}, "101": {"prereqs_extra": ["999"]}}}
    res2 = construir_matriz(p, n2, cfg2)
    assert res2.celdas[0].estado == APROBADA and res2.celdas[0].nombre_cursado == "Calc 1 viejo"
    assert not res2.sin_correspondencia


def test_ciclo_detectado():
    p = [MateriaPensum("a", "A", "A", 3, 1), MateriaPensum("b", "B", "B", 3, 1)]
    cfg = {"materias": {"a": {"prereqs_extra": ["b"]}, "b": {"prereqs_extra": ["a"]}}}
    assert any("circular" in w for w in construir_matriz(p, [], cfg).advertencias)


# ------------------------------------------------------------------ persistencia
def test_config_roundtrip_y_sanitizacion(tmp_path):
    f = tmp_path / "c.json"
    assert cs.load_config(f).config["materias"] == {}
    r = cs.save_materias({"100": {"aliases": ["  Viejo  ", "viejo", "", None], "prereqs_extra": ["1 2", "ok"], "prereqs_removidos": []}}, path=f)
    assert r.config["materias"]["100"] == {"aliases": ["Viejo"], "prereqs_extra": ["ok"], "prereqs_removidos": []}
    assert cs.load_config(f).config["revision"] == 1
    cs.save_materias({"100": None}, path=f)
    assert cs.load_config(f).config["materias"] == {}
    assert f.with_suffix(".json.bak").exists()


def test_config_corrupta_se_respalda(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("{no es json", encoding="utf-8")
    res = cs.load_config(f)
    assert res.config["materias"] == {} and res.warnings
    assert list(tmp_path.glob("c.corrupt-*.json"))


def test_conflicto_y_fusion_por_materia(tmp_path):
    f = tmp_path / "c.json"
    cs.save_materias({"A": {"aliases": ["uno"]}}, path=f)                    # sesión 1 (rev 1)
    cs.save_materias({"B": {"aliases": ["dos"]}}, path=f)                    # sesión 2 (rev 2)
    r = cs.save_materias({"C": {"aliases": ["tres"]}}, base_revision=1, path=f)  # sesión 1 desactualizada
    assert r.conflicto_externo and set(r.config["materias"]) == {"A", "B", "C"}


def test_escrituras_concurrentes_no_corrompen(tmp_path):
    f = tmp_path / "c.json"
    hilos = [threading.Thread(target=cs.save_materias, args=({f"M{i}": {"aliases": [f"a{i}"]}},), kwargs={"path": f}) for i in range(12)]
    [h.start() for h in hilos]; [h.join() for h in hilos]
    data = json.loads(f.read_text(encoding="utf-8"))
    assert len(data["materias"]) == 12 and data["revision"] == 12


def test_historia_vacia_no_es_error():
    vacia = "<table>" + THEAD_BASE.format(extra_h="", tipo_h="") + '<tbody id="j_idt1:hAcademicaNotasEstudianteDT_data"><tr><td colspan="8">No records found.</td></tr></tbody></table>'
    r = parse_notas_html(vacia)
    assert r.registros == [] and any("vacía" in w for w in r.warnings)
    # y la matriz funciona sin notas
    p = parse_pensum_html(PENSUM).materias
    assert {c.estado for c in construir_matriz(p, [], None).celdas} == {DISPONIBLE, BLOQUEADA}


def test_filas_irreconocibles_si_es_error():
    rara = "<table>" + THEAD_BASE.format(extra_h="", tipo_h="") + '<tbody id="j_idt1:hAcademicaNotasEstudianteDT_data"><tr><td>a</td><td>b</td><td>c</td></tr></tbody></table>'
    with pytest.raises(ParseError, match="ninguna reconocible"):
        parse_notas_html(rara)


# ------------------------------------------------------------------ electivas adicionales y requisitos
from simca.requisitos import evaluar_requisitos, inferir_requisito  # noqa: E402
from simca.models import MateriaMatriculada, SEMESTRE_ELECTIVAS, SEMESTRE_FISH  # noqa: E402


def _pensum_electivas():
    return [MateriaPensum("1", "E1", "Electiva-Complementaria 1", 3, 0), MateriaPensum("2", "F1", "Electiva Fish - I", 2, 0)]


def test_electivas_dos_columnas_cronologicas_sin_reprobadas():
    notas = [RegistroNota("2024.2", "11", "Electiva - Dos", 3, 2, 4.2, 4.2),      # fuera de orden a propósito
             RegistroNota("2024.1", "10", "Electiva - Uno", 3, 1, 4.0, 4.0),
             RegistroNota("2025.1", "12", "Elec. Tres", 3, 3, 2.5, 2.5),          # perdida: se ignora
             RegistroNota("2025.2", "13", "Electiva - Cuatro", 3, 4, 4.4, 4.4),   # excede el único cupo -> adicional
             RegistroNota("2024.1", "20", "Electiva Fish- Cine", 2, 1, 4.5, 4.5)]
    r = construir_matriz(_pensum_electivas(), notas, None)
    cols = r.por_semestre()
    assert list(cols) == [SEMESTRE_ELECTIVAS, SEMESTRE_FISH]                      # dos columnas separadas
    assert [c.periodo for c in cols[SEMESTRE_ELECTIVAS]] == ["2024.1", "2024.2", "2025.2"]   # cronológico, aunque llegaron desordenadas
    assert [c.nombre for c in cols[SEMESTRE_FISH]] == ["Electiva Fish - I"] and cols[SEMESTRE_FISH][0].nota == 4.5
    adic = {c.nombre for c in r.adicionales}
    assert adic == {"Electiva - Dos", "Electiva - Cuatro"} and all(c.adicional for c in r.adicionales)
    assert "Elec. Tres" not in adic and not r.sin_correspondencia                  # perdida descartada, sin molestar
    assert r.metricas["n_total"] == 2 and r.metricas["creditos_aprobados"] == 5   # los adicionales no inflan el avance


def test_cupos_libres_van_al_final_de_la_columna():
    p = [MateriaPensum("1", "E1", "Electiva-Complementaria 1", 3, 0), MateriaPensum("2", "E2", "Electiva-Complementaria 2", 3, 0)]
    r = construir_matriz(p, [RegistroNota("2025.1", "10", "Electiva - X", 3, 1, 4.0, 4.0)], None,
                         [MateriaMatriculada("2026.2", "M9", "Electiva - En curso")])
    col = r.por_semestre()[SEMESTRE_ELECTIVAS]
    assert [(c.estado, c.periodo) for c in col] == [(APROBADA, "2025.1"), (EN_CURSO, "2026.2")]


def test_electiva_matriculada_sin_cupo_es_adicional_en_curso_en_su_columna():
    p = [MateriaPensum("1", "E1", "Electiva-Complementaria 1", 3, 0), MateriaPensum("2", "F1", "Electiva Fish - I", 2, 0)]
    notas = [RegistroNota("2024.1", "10", "Electiva - Uno", 3, 1, 4.0, 4.0), RegistroNota("2024.1", "11", "Electiva Fish- Uno", 2, 1, 4.0, 4.0)]
    r = construir_matriz(p, notas, None, [MateriaMatriculada("2026.2", "M9", "Electiva Fish- Nueva")])
    assert [(c.nombre, c.estado, c.semestre) for c in r.adicionales] == [("Electiva Fish- Nueva", EN_CURSO, SEMESTRE_FISH)]
    assert not r.matriculadas_sin_correspondencia


def test_asignacion_manual_electiva_adicional_y_requisito():
    p = [MateriaPensum("1", "A", "Algo", 3, 1)]
    notas = [RegistroNota("2023.2", "34130", "Ingles 1-B1", 2, 3, 3.8, 3.8), RegistroNota("2024.1", "777", "Curso libre", 3, 4, 4.0, 4.0)]
    assert len(construir_matriz(p, notas, None).sin_correspondencia) == 2
    cfg = {"asignaciones": {
        "34130": {"tipo": "requisito_grado", "nombre": "Ingles 1-B1", "requisito": "Prueba de Suficiencia en Idioma Extranjero"},
        "777": {"tipo": "electiva_adicional", "nombre": "Curso libre", "requisito": ""}}}
    r = construir_matriz(p, notas, cfg)
    assert not r.sin_correspondencia and [c.nombre for c in r.adicionales] == ["Curso libre"] and r.adicionales[0].personalizada
    assert r.adicionales[0].semestre == SEMESTRE_ELECTIVAS
    cfg["asignaciones"]["777"]["grupo"] = "fish"                                   # el usuario la ubica en la columna Fish
    assert construir_matriz(p, notas, cfg).adicionales[0].semestre == SEMESTRE_FISH
    assert r.requisitos_marcados[0]["requisito"].startswith("Prueba") and r.requisitos_marcados[0]["estado"] == APROBADA
    assert not any("Créditos" in w for w in r.advertencias)


def test_evaluar_requisitos():
    oficiales = [{"codigo": "1", "nombre": "Actividad Física Formativa"}, {"codigo": "2", "nombre": "ECAES"},
                 {"codigo": "3", "nombre": "Prueba de Suficiencia en Idioma Extranjero"}]
    simca = [{"nombre": "AFF- Deportes alternativos", "aprobado": True, "periodo": "2023.1", "definitiva": "A"},
             {"nombre": "Inglés 2 - B1", "aprobado": False, "periodo": "2025.1", "definitiva": "2.0"}]
    filas, otros = evaluar_requisitos(oficiales, simca, [])
    est = {f["requisito"]: f["estado"] for f in filas}
    assert est == {"Actividad Física Formativa": "cumplido", "ECAES": "pendiente", "Prueba de Suficiencia en Idioma Extranjero": "pendiente"}
    marcados = [{"nombre": "Prueba Saber Pro", "estado": "aprobada", "requisito": "ECAES", "periodo": "2026.1", "definitiva": 3.0},
                {"nombre": "Taller raro", "estado": "en_curso", "requisito": "", "periodo": "2026.2", "definitiva": None}]
    filas, otros = evaluar_requisitos(oficiales, simca, marcados)
    assert {f["requisito"]: f["estado"] for f in filas}["ECAES"] == "cumplido" and [o["nombre"] for o in otros] == ["Taller raro"]
    assert inferir_requisito("Curso de cocina", [o["nombre"] for o in oficiales]) is None


def test_config_asignaciones_persisten_y_se_sanean(tmp_path):
    f = tmp_path / "c.json"
    cs.save_materias({"A": {"aliases": ["x"]}}, path=f)
    r = cs.save_asignaciones({"34130": {"tipo": "requisito_grado", "nombre": " Ingles  1 ", "requisito": "Idioma"},
                              "9": {"tipo": "otra_cosa", "nombre": "x"}}, path=f)             # tipo inválido: se ignora
    assert r.config["asignaciones"] == {"34130": {"tipo": "requisito_grado", "nombre": "Ingles 1", "requisito": "Idioma", "grupo": ""}}
    assert cs.load_config(f).config["materias"]["A"]["aliases"] == ["x"]                        # no pisa las materias
    cs.save_asignaciones({"34130": None}, path=f)
    assert cs.load_config(f).config["asignaciones"] == {}
    f.write_text(json.dumps({"version": 1, "revision": 3, "materias": {}}), encoding="utf-8")   # archivo de versión anterior
    assert cs.load_config(f).config["asignaciones"] == {}


def test_pensum_requisitos_oficiales_deduplicados():
    html = PENSUM + """<table><tbody id="formMateriasPendientes:requisitosGrado_data">
      <tr><td>21793</td><td>Actividad Física Formativa</td></tr><tr><td>21792</td><td>ECAES</td></tr><tr><td>21793</td><td>Actividad Física Formativa</td></tr></tbody></table>"""
    assert [r["nombre"] for r in parse_pensum_html(html).requisitos_grado] == ["Actividad Física Formativa", "ECAES"]


def test_electivas_completo_dos_columnas_matriculadas_y_perdidas():
    p = [MateriaPensum("1", "F1", "Electiva Fish - I", 2, 0), MateriaPensum("2", "F2", "Electiva Fish - II", 2, 0),
         MateriaPensum("3", "C1", "Electiva-Complementaria 1", 3, 0), MateriaPensum("4", "C2", "Electiva-Complementaria 2", 3, 0),
         MateriaPensum("5", "C3", "Electiva-Complementaria 3", 3, 0)]
    notas = [RegistroNota("2025.1", "30", "Electiva - Tardía", 3, 6, 4.0, 4.0),
             RegistroNota("2023.1", "20", "Electiva Fish- Temprana", 2, 2, 4.0, 4.0),
             RegistroNota("2024.1", "25", "Electiva - Perdida", 3, 4, 2.0, 2.0),            # perdida: ignorada
             RegistroNota("2024.2", "26", "Electiva - Media", 3, 5, 3.5, 3.5),
             RegistroNota("2026.1", "40", "Electiva - Extra A", 3, 8, 4.0, 4.0),             # sobra -> adicional
             RegistroNota("2025.2", "41", "Electiva - Extra B", 3, 7, 4.1, 4.1)]             # cabe en el 3er cupo
    mats = [MateriaMatriculada("2026.2", "M5", "Electiva - Actual")]                         # sobra -> adicional en curso
    r = construir_matriz(p, notas, None, mats)
    cols = r.por_semestre()
    comp, fish = cols[SEMESTRE_ELECTIVAS], cols[SEMESTRE_FISH]
    # Electivas del programa: cronológico (Media, Tardía, Extra B) y luego los adicionales (Extra A 2026.1, Actual 2026.2)
    assert [c.nombre_cursado or c.nombre for c in comp] == [
        "Electiva - Media", "Electiva - Tardía", "Electiva - Extra B", "Electiva - Extra A", "Electiva - Actual"]
    assert [c.adicional for c in comp] == [False, False, False, True, True]
    assert comp[-1].estado == EN_CURSO
    # Fish: la cursada primero y el cupo libre (Fish II) al final
    assert [(c.estado, c.periodo) for c in fish] == [(APROBADA, "2023.1"), (DISPONIBLE, None)]
    assert "Electiva - Perdida" not in [c.nombre for c in comp] and not r.sin_correspondencia
    assert r.metricas["electivas_reprobadas_ignoradas"] == 1


# ------------------------------------------------------------------ reglamento estudiantil (Arts. 6-11)
from simca.reglamento import evaluar_reglamento, siguiente_periodo  # noqa: E402


def _regl(intentos_por_materia, mats=None, periodo_actual="2026.2", sancionado=False):
    """intentos_por_materia: {id: [(periodo, definitiva), ...]} sobre un pénsum de 4 materias regulares."""
    p = [MateriaPensum(str(i), f"A{i}", n, 3, 1) for i, n in enumerate(["Calculo", "Fisica", "Quimica", "Nueva"], start=1)]
    notas = [RegistroNota(per, mid, p[int(mid) - 1].nombre, 3, 1, d, d) for mid, its in intentos_por_materia.items() for per, d in its]
    res = construir_matriz(p, notas, None, mats)
    return evaluar_reglamento(res, periodo_actual, sancionado)


def test_siguiente_periodo():
    assert siguiente_periodo("2026.1") == "2026.2" and siguiente_periodo("2026.2") == "2027.1"


def test_perder_una_vez_y_aprobar_no_genera_alertas():
    r = _regl({"1": [("2024.1", 2.0), ("2024.2", 3.5)]})
    assert r.situacion == "normal" and not r.hallazgos
    assert r.filas[0].estado == "aprobada" and r.filas[0].intentos == 2


def test_art6_bajo_rendimiento_al_perder_como_repitente_primera_vez():
    r = _regl({"1": [("2024.1", 2.0), ("2024.2", 2.5)]}, periodo_actual="2025.1")
    assert r.situacion == "bajo_rendimiento"
    assert [h.articulo for h in r.hallazgos] == ["Art. 6"] and r.hallazgos[0].periodo == "2024.2"
    assert r.filas[0].estado == "por_repetir" and "Art. 7" in r.filas[0].observacion       # el próximo intento es repitente 2.ª vez


def test_art7_matricula_condicional_y_art9_solo_repeticiones():
    nueva = MateriaMatriculada("2026.2", "A4", "Nueva", repeticion=0)                      # materia nueva
    repite = MateriaMatriculada("2026.2", "A1", "Calculo", repeticion=3)
    r = _regl({"1": [("2025.1", 2.0), ("2025.2", 2.0), ("2026.1", 2.0)]}, [nueva, repite], periodo_actual="2026.2")
    assert r.condicionales_usadas == 1 and r.condicional_vigente and r.situacion == "matricula_condicional"
    arts = [(h.articulo, h.materia) for h in r.hallazgos]
    assert ("Art. 7", "") in arts and ("Art. 9", "Nueva") in arts
    assert not any(a == ("Art. 9", "Calculo") for a in arts)                                # la repetición sí está permitida
    assert "Art. 8" in next(f.observacion for f in r.filas if f.estado == "en_curso")       # cursa como repitente 3.ª vez


def test_art7_parrafo_con_sancion_disciplinaria_pierde_derecho():
    r = _regl({"1": [("2025.1", 2.0), ("2025.2", 2.0), ("2026.1", 2.0)]}, periodo_actual="2026.2", sancionado=True)
    assert r.situacion == "perdida_derecho" and r.hallazgos[0].nivel == "critico" and "parágrafo" in r.hallazgos[0].articulo


def test_art8_perder_como_repitente_tercera_vez():
    r = _regl({"1": [("2024.1", 2.0), ("2024.2", 2.0), ("2025.1", 2.0), ("2025.2", 2.0)]}, periodo_actual="2026.1")
    assert r.situacion == "perdida_derecho" and any(h.articulo == "Art. 8" and h.nivel == "critico" for h in r.hallazgos)


def test_art10_11_tercera_perdida_como_repitente_segunda_vez():
    h = {"1": [("2023.1", 2.0), ("2023.2", 2.0), ("2024.1", 2.0)],     # 1.ª condicional (2024.2)
         "2": [("2024.2", 2.0), ("2025.1", 2.0), ("2025.2", 2.0)],     # 2.ª condicional (2026.1)
         "3": [("2026.1", 2.0), ("2026.2", 2.0), ("2027.1", 2.0)]}     # 3.ª -> excede
    r = _regl(h, periodo_actual="2027.2")
    assert r.condicionales_usadas == 3 and r.situacion == "perdida_derecho"
    assert any(x.articulo == "Arts. 10 y 11" and x.nivel == "critico" for x in r.hallazgos)


def test_riesgo_de_lo_que_cursa_ahora_y_verificacion_de_repeticion():
    mats = [MateriaMatriculada("2026.2", "A1", "Calculo", repeticion=1)]
    r = _regl({"1": [("2026.1", 2.0)]}, mats)
    fila = next(f for f in r.filas if f.materia == "Calculo")
    assert fila.estado == "en_curso" and fila.repitente == 1 and "Art. 6" in fila.observacion and not r.hallazgos
    mats = [MateriaMatriculada("2026.2", "A1", "Calculo", repeticion=2)]                    # SIMCA dice 2, el historial solo 1
    assert any(h.titulo.startswith("La repetición de SIMCA") for h in _regl({"1": [("2026.1", 2.0)]}, mats).hallazgos)
    r = _regl({"1": [("2026.1", 2.0)]}, [MateriaMatriculada("2026.2", "A1", "Calculo", repeticion=1)], sancionado=True)
    assert r.situacion == "normal"                                                           # el riesgo es solo informativo


def test_intentos_sin_nota_no_cuentan_como_repeticion():
    p = [MateriaPensum("1", "A1", "Calculo", 3, 1)]
    notas = [RegistroNota("2025.1", "1", "Calculo", 3, 1, 2.0, 2.0), RegistroNota("2025.2", "1", "Calculo", 3, 1, None, None),
             RegistroNota("2026.1", "1", "Calculo", 3, 1, 2.4, 2.4)]
    r = evaluar_reglamento(construir_matriz(p, notas, None), "2026.2")
    assert r.filas[0].intentos == 2 and [h.articulo for h in r.hallazgos] == ["Art. 6"]    # la cancelación no se cuenta


def test_parser_guarda_identificacion_y_codigo():
    from simca.parsers import parse_estudiante
    html = """<table id="formOpcionesConsulta:formDatosEstudiante:x"><tr><td>Nombres:</td><td>PEREZ JUAN</td></tr>
    <tr><td>Identificación:</td><td>123456</td></tr><tr><td>Código:</td><td>1025</td></tr>
    <tr><td>Promedio Carrera:</td><td>4.057</td></tr></table>"""
    e = parse_estudiante(html)
    assert (e["identificacion"], e["codigo"], e["promedio_carrera"]) == ("123456", "1025", 4.057)


# ------------------------------------------------------------------ despliegue / modo nube
import os  # noqa: E402
from pathlib import Path  # noqa: E402


def test_acceso_valido():
    from simca.auth import acceso_valido
    assert acceso_valido("secreto", "secreto") and not acceso_valido("otro", "secreto") and not acceso_valido("", "")


def test_modo_nube_por_bandera(monkeypatch):
    from simca.settings import modo_nube
    monkeypatch.setenv("SIMCA_MODO_NUBE", "1")
    assert modo_nube()
    monkeypatch.setenv("SIMCA_MODO_NUBE", "0")
    assert not modo_nube()


def test_write_json_plain_no_toca_el_directorio(tmp_path):
    from simca.fileio import write_json_plain
    d = tmp_path / "ajeno"
    d.mkdir(mode=0o755)
    write_json_plain(d / "x.json", {"a": 1})
    assert json.loads((d / "x.json").read_text()) == {"a": 1}
    assert (d.stat().st_mode & 0o777) == 0o755 and not (d / ".gitignore").exists()


def test_cli_out_escribe_en_archivo_indicado(monkeypatch, tmp_path):
    from simca import cli_scrape
    from simca.scraper import FetchResult
    monkeypatch.setenv("SIMCA_USER", "u"); monkeypatch.setenv("SIMCA_PASSWORD", "p"); monkeypatch.setenv("SIMCA_STUDENT_CODE", "123")
    monkeypatch.setattr(cli_scrape, "fetch_academic_pages", lambda *a, **k: FetchResult({"pensum": PENSUM, "notas": NOTAS, "matriculadas": MATRICULADAS}))
    monkeypatch.setattr(cli_scrape, "save_snapshot", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe guardar en el directorio de datos")))
    salida = tmp_path / "s.json"
    assert cli_scrape.main(["--out", str(salida)]) == 0
    snap = json.loads(salida.read_text(encoding="utf-8"))
    assert len(snap["pensum"]) == 2 and snap["matriculadas_cargadas"] is True


def test_cli_sin_credenciales_devuelve_2(monkeypatch):
    from simca import cli_scrape
    monkeypatch.delenv("SIMCA_USER", raising=False); monkeypatch.delenv("SIMCA_PASSWORD", raising=False)
    monkeypatch.setattr("simca.settings.credentials_configured", lambda: False)
    assert cli_scrape.main([]) == 2


def test_replace_config_importa_y_rechaza_basura(tmp_path):
    f = tmp_path / "c.json"
    r = cs.replace_config({"materias": {"100": {"aliases": ["Viejo"]}}, "asignaciones": {"5": {"tipo": "requisito_grado", "nombre": "X"}}}, path=f)
    assert r.config["materias"]["100"]["aliases"] == ["Viejo"] and "5" in r.config["asignaciones"]
    with pytest.raises(cs.ConfigError):
        cs.replace_config(["no", "es", "un", "dict"], path=f)


def _hay_app(monkeypatch, tmp_path, **env):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("SIMCA_DATA_DIR", str(tmp_path))
    for k in ("SIMCA_APP_ACCESS_CODE", "SIMCA_MODO_NUBE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60)


def test_app_con_codigo_de_acceso(monkeypatch, tmp_path):
    at = _hay_app(monkeypatch, tmp_path, SIMCA_APP_ACCESS_CODE="abc123").run()
    assert not at.exception and at.text_input[0].label == "Código de acceso" and not at.metric
    at.text_input[0].set_value("mal"); at.button[0].click(); at.run()
    assert any("incorrecto" in e.value for e in at.error)
    at.text_input[0].set_value("abc123"); at.button[0].click(); at.run()
    assert not at.exception and not any(t.label == "Código de acceso" for t in at.text_input)   # ya entró


def test_nube_sin_codigo_no_carga_y_no_lee_datos_de_disco(monkeypatch, tmp_path):
    at = _hay_app(monkeypatch, tmp_path, SIMCA_MODO_NUBE="1").run()
    assert any("código de acceso" in e.value for e in at.error) and not at.metric
    # con código: aunque exista un snapshot en disco (de otro usuario), NO se precarga
    from simca.snapshot import save_snapshot
    save_snapshot({"pensum": [], "notas": [], "estudiante": {"nombres": "OTRO ESTUDIANTE"}}, tmp_path / "snapshot_academico.json")
    at = _hay_app(monkeypatch, tmp_path, SIMCA_MODO_NUBE="1", SIMCA_APP_ACCESS_CODE="k").run()
    at.text_input[0].set_value("k"); at.button[0].click(); at.run()
    assert at.session_state["datos"] is None and not any("OTRO ESTUDIANTE" in m.value for m in at.markdown)


def test_app_diagnostica_archivos_faltantes_del_repositorio(tmp_path, monkeypatch):
    """Si el repositorio de la nube no trae simca/auth.py, la app lo dice en vez de fallar con un error oculto."""
    import shutil
    from streamlit.testing.v1 import AppTest
    raiz = Path(__file__).resolve().parent.parent
    copia = tmp_path / "repo"
    shutil.copytree(raiz, copia, ignore=shutil.ignore_patterns("__pycache__", ".git", ".venv", "data", "tests"))
    (copia / "simca" / "auth.py").unlink()
    monkeypatch.setenv("SIMCA_DATA_DIR", str(tmp_path / "d"))
    at = AppTest.from_file(str(copia / "app.py"), default_timeout=60).run()
    assert not at.exception and any("faltan archivos" in e.value for e in at.error)
    assert any("simca/auth.py" in c.value for c in at.code)
