"""Página principal: pensum oficial x notas."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

from simca.matrix import construir_matriz, matriz_a_dataframe
from simca.render import ESTADOS, render_leyenda_html, render_matriz_html
from simca.reglamento import ARTICULOS, SITUACIONES, evaluar_reglamento
from simca.requisitos import evaluar_requisitos
from simca.settings import PROJECT_ROOT, credentials_configured, get_student_code, modo_nube
from simca.snapshot import build_snapshot, save_snapshot
from simca.state import get_models

ss = st.session_state
st.title("🎓 Matriz académica")


def _actualizar_desde_simca(usuario: str, password: str, codigo: str) -> None:
    # Prioridad: lo digitado en la UI; si está vacío, lo que haya en .env / entorno.
    if not ((usuario.strip() and password) or credentials_configured()):
        st.error("Faltan credenciales: digítalas en la barra lateral o define SIMCA_USER y SIMCA_PASSWORD en `.env`.")
        return
    if not codigo.strip():
        st.error("Digita el código o cédula del estudiante.")
        return
    env = {**os.environ, "SIMCA_STUDENT_CODE": codigo.strip()}  # por entorno, no por argv
    if usuario.strip() and password:
        env["SIMCA_USER"], env["SIMCA_PASSWORD"] = usuario.strip(), password  # solo para el subproceso
    tmp = tempfile.mkdtemp(prefix="simca_")   # carpeta privada (0700) solo para esta consulta
    salida = Path(tmp) / "snapshot.json"
    try:
        with st.spinner("Consultando SIMCA (login, notas y pénsum)…"):
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "simca.cli_scrape", "--out", str(salida)],
                    capture_output=True, text=True, timeout=900, cwd=PROJECT_ROOT, env=env,
                )
            except subprocess.TimeoutExpired:
                st.error("La consulta superó el tiempo máximo. Inténtalo de nuevo.")
                return
        if proc.returncode != 0:
            st.error((proc.stderr or "Error desconocido").strip()[-600:])
            return
        snap = json.loads(salida.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ss["datos"] = snap
    if not modo_nube():   # en la nube nada de datos académicos toca el disco compartido
        save_snapshot(snap)
    st.success(proc.stdout.strip().splitlines()[0])


with st.sidebar:
    st.subheader("Fuente de datos")
    if modo_nube():
        st.caption("☁️ Modo nube: los datos de cada consulta viven solo en esta sesión y se pierden al cerrarla.")
    usuario = st.text_input("Usuario SIMCA", value=os.getenv("SIMCA_USER", ""), autocomplete="off")
    password = st.text_input(
        "Contraseña SIMCA", type="password", autocomplete="off",
        placeholder="(usa la de .env)" if credentials_configured() else "",
        help="No se guarda en disco ni se escribe en ningún archivo. Se envía solo al navegador automatizado durante la consulta.",
    )
    codigo = st.text_input("Código o cédula del estudiante", value=get_student_code(), help="Se usa solo para esta consulta; no se guarda.")
    if st.button("🔄 Actualizar desde SIMCA", type="primary"):
        _actualizar_desde_simca(usuario, password, codigo)

    with st.expander("📁 Cargar HTML guardados (sin conexión)"):
        up_p = st.file_uploader("Pénsum / Currículo (.html)", type=["html", "htm"], key="up_pensum")
        up_n = st.file_uploader("Historia Académica (.html)", type=["html", "htm"], key="up_notas")
        up_m = st.file_uploader("Materias matriculadas (.html, opcional)", type=["html", "htm"], key="up_matric")
        guardar = st.checkbox("Guardar copia local procesada", value=False, disabled=modo_nube(),
                              help="Desactivado en la nube: los datos viven solo en tu sesión." if modo_nube() else None)
        if st.button("Procesar archivos", disabled=not (up_p and up_n)):
            try:
                dec = lambda f: f.getvalue().decode("utf-8", "replace")  # noqa: E731
                snap = build_snapshot(dec(up_p), dec(up_n), dec(up_m) if up_m else None)
                ss["datos"] = snap
                if guardar and not modo_nube():
                    save_snapshot(snap)
                st.success("Archivos procesados.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo procesar: {exc}")
    st.subheader("Opciones")
    st.toggle("Ocultar cédula y código", key="ocultar_ids", help="Útil al compartir pantalla. Solo afecta lo que se muestra.")
    st.checkbox("Sancionado disciplinariamente", key="sancionado",
                help="Lo exige el Art. 7 (parágrafo) del reglamento. Se usa solo para esta sesión; NO se guarda en disco.")
    if ss.get("datos"):
        st.caption(f"Datos generados: {ss['datos'].get('generado', '—')}")

pensum, notas, matriculadas = get_models()
if not pensum:
    st.info("Aún no hay datos. Usa **Actualizar desde SIMCA** o carga los HTML guardados en la barra lateral.")
    st.stop()

for w in ss.get("config_warnings", []):
    st.warning(w)

est = ss["datos"].get("estudiante", {})


def _md(texto: object) -> str:
    """Escapa caracteres de Markdown en datos que vienen de SIMCA."""
    return "".join("\\" + ch if ch in "\\`*_{}[]<>()#+-.!|~$" else ch for ch in str(texto))


def _enmascarar(valor: str) -> str:
    return "•" * max(len(valor) - 4, 0) + valor[-4:] if valor else ""


if est:
    ocultar = ss.get("ocultar_ids", False)
    cedula, codigo_est = est.get("identificacion", ""), est.get("codigo", "")
    if ocultar:
        cedula, codigo_est = _enmascarar(cedula), _enmascarar(codigo_est)
    with st.container(border=True):
        p1, p2, p3, p4 = st.columns([3.2, 1.6, 1.8, 2.2])
        p1.markdown(f"**{_md(est.get('nombres', '—'))}**  \n{_md(est.get('programa', ''))}")
        p2.markdown(f"**Cédula**  \n{_md(cedula) if cedula else '—'}")
        p3.markdown(f"**Código**  \n{_md(codigo_est) if codigo_est else '—'}")
        prom = est.get("promedio_carrera")
        p4.markdown(f"**Semestre** {_md(est.get('semestre', '—'))} · **{_md(est.get('estado', '—'))}**  \n"
                    f"Promedio carrera: {prom if prom is not None else '—'}")
        if not est.get("identificacion"):
            st.caption("Este snapshot es anterior: actualiza los datos para ver cédula y código.")

if not notas:
    st.info("Este estudiante no tiene notas registradas en SIMCA: se muestra solo el pensum, con las materias sin prerrequisitos como disponibles.")

res = construir_matriz(pensum, notas, ss["config"], matriculadas)
m = res.metricas

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Avance (créditos)", f"{m['pct_avance']:.1f}%", f"{m['creditos_aprobados']}/{m['creditos_pensum']} cr", delta_color="off")
c2.metric("Promedio ponderado", f"{m['promedio_ponderado']:.2f}" if m["promedio_ponderado"] else "—")
c3.metric("Materias aprobadas", f"{m['n_aprobada']}/{m['n_total']}")
c4.metric("En curso", m["n_en_curso"], f"{m['creditos_en_curso']} cr" if m["n_en_curso"] else None, delta_color="off")
c5.metric("Disponibles ahora", m["n_disponible"], f"{m['n_bloqueada']} bloqueadas", delta_color="off")
if m["n_en_curso"]:
    st.caption(f"Avance proyectado si aprueba lo que cursa: **{m['pct_proyectado']:.1f}%** · periodo {ss['datos'].get('periodo_actual') or '—'}")
elif not ss["datos"].get("matriculadas_cargadas"):
    st.caption("Sin datos de matrícula actual (sección «Materias» no cargada).")
if m["n_adicionales"] or res.adicionales:
    st.caption(f"Electivas adicionales (sobre los cupos del pensum): **{m['n_adicionales']}** aprobadas · {m['creditos_adicionales']} cr — no suman al avance del pensum.")
st.progress(min(m["pct_avance"] / 100, 1.0))

f1, f2 = st.columns([3, 1])
estados_sel = f1.multiselect("Estados a mostrar", list(ESTADOS), default=list(ESTADOS), format_func=lambda e: ESTADOS[e][0])
con_electivas = f2.toggle("Incluir electivas", value=True)

reg = evaluar_reglamento(res, ss["datos"].get("periodo_actual"), bool(ss.get("sancionado")),
                         matriculadas_cargadas=bool(ss["datos"].get("matriculadas_cargadas")))
if reg.situacion == "perdida_derecho":
    st.error(f"⛔ {SITUACIONES[reg.situacion]}. Revisa el detalle más abajo y confírmalo con el programa.")
elif reg.situacion != "normal":
    st.warning(f"⚠️ {SITUACIONES[reg.situacion]}. Revisa el detalle más abajo.")

st.markdown(render_leyenda_html(), unsafe_allow_html=True)
st.markdown(render_matriz_html(res, set(estados_sel), con_electivas), unsafe_allow_html=True)

if res.sin_correspondencia or res.matriculadas_sin_correspondencia:
    with st.expander(f"⚠️ Registros sin materia asignada ({len(res.sin_correspondencia) + len(res.matriculadas_sin_correspondencia)})", expanded=True):
        for n in res.sin_correspondencia:
            st.text(f"Historia · {n.periodo} · {n.id} · {n.nombre} · {n.definitiva}")
        for mm in res.matriculadas_sin_correspondencia:
            st.text(f"Matriculada · {mm.periodo} · {mm.codigo} · {mm.nombre}")
        st.page_link("views/configuracion.py", label="Resolver con un alias en Configuración →", icon="⚙️")

adv = res.advertencias + ss["datos"].get("advertencias", [])
if adv:
    with st.expander(f"Avisos de extracción y unificación ({len(adv)})"):
        for a in adv:
            st.write("• " + a)

if matriculadas:
    with st.expander(f"📅 Materias matriculadas {ss['datos'].get('periodo_actual') or ''} ({len(matriculadas)})"):
        st.dataframe([{
            "Código": x.codigo, "Materia": x.nombre, "Sec.": x.seccion, "Docente": x.docentes,
            "Horario": " · ".join(f"{h.dia} {h.horario} ({h.salon})" for h in x.horarios), "Repetición": x.repeticion,
        } for x in matriculadas], hide_index=True)

with st.expander("Tabla detallada / exportar"):
    df = matriz_a_dataframe(res)
    st.dataframe(df, hide_index=True)
    st.download_button("⬇️ Descargar CSV", df.to_csv(index=False).encode("utf-8-sig"), "matriz_academica.csv", "text/csv")

if reg.filas or reg.hallazgos:
    with st.expander(f"📋 Reglamento estudiantil · materias repetidas ({len(reg.filas)})", expanded=reg.situacion != "normal"):
        st.markdown(f"**Situación:** {SITUACIONES[reg.situacion]} · matrículas condicionales usadas: **{reg.condicionales_usadas} de 2**"
                    + (f" · periodo evaluado: {reg.periodo_objetivo}" if reg.periodo_objetivo else ""))
        for h in reg.hallazgos:
            texto = f"**{h.articulo} · {h.titulo}**" + (f" ({h.periodo})" if h.periodo else "") + f" — {h.detalle}"
            {"critico": st.error, "alerta": st.warning}.get(h.nivel, st.info)(texto)
        if reg.filas:
            estado_txt = {"en_curso": "🔵 En curso", "por_repetir": "🟠 Por repetir", "aprobada": "✅ Aprobada"}
            st.dataframe([{
                "Materia": f.materia, "Intentos": f.intentos, "Trayectoria": f.trayectoria, "Estado": estado_txt[f.estado],
                "Repitente": f"{f.repitente}ª vez" if f.repitente else "—", "Observación": f.observacion,
            } for f in reg.filas], hide_index=True)
        st.caption("Validación orientativa calculada del historial según el Acuerdo 002 de 1988 y modificatorios (Arts. 6-11). "
                   "Solo cuentan los intentos con nota definitiva (una habilitación no es un intento). "
                   "Supone una matrícula condicional por cada periodo en que se pierde una asignatura como repitente por segunda vez. "
                   "La decisión oficial corresponde al programa y a Registro Académico.")
        with st.expander("Resumen de los artículos aplicados"):
            for n, t in ARTICULOS.items():
                st.write(f"**Art. {n}.** {t}")

datos = ss["datos"]
filas_req, otros_req = evaluar_requisitos(datos.get("requisitos_grado_oficiales", []), datos.get("requisitos_grado", []), res.requisitos_marcados)
if filas_req or otros_req:
    with st.expander("🎓 Requisitos de grado", expanded=True):
        icono = {"cumplido": "✅ Cumplido", "en_curso": "🔵 En curso", "pendiente": "⬜ Pendiente"}
        if filas_req:
            st.dataframe([{"Requisito": f["requisito"], "Estado": icono[f["estado"]], "Evidencia": "; ".join(f["evidencia"]) or "—"}
                          for f in filas_req], hide_index=True)
        if otros_req:
            st.write("**Otros reconocidos como requisito de grado**")
            st.dataframe([{"Registro": o["nombre"], "Estado": o["estado"].replace("_", " ").capitalize(), "Detalle": o["detalle"]}
                          for o in otros_req], hide_index=True)
        st.caption("La asociación de las filas de SIMCA a cada requisito se infiere por el nombre (AFF, inglés/idioma, ECAES). "
                   "Para marcar un registro del historial como requisito, usa **Configuración**.")
