"""Página de configuración: alias y prerrequisitos por materia (persistidos en JSON)."""
import difflib
import json

import pandas as pd
import streamlit as st

from simca.config_store import ConfigError, config_path, disk_revision, load_config, replace_config, save_asignaciones, save_materias
from simca.matrix import construir_matriz
from simca.requisitos import OTRO, inferir_requisito
from simca.state import get_models
from simca.text_utils import clean_text, normalize_key

ss = st.session_state
st.title("⚙️ Configuración de materias")

pensum, notas, matriculadas = get_models()
if not pensum:
    st.info("Primero carga los datos en la página **Matriz académica**.")
    st.page_link("views/matriz.py", label="Ir a la matriz", icon="🎓")
    st.stop()

cfg = ss["config"]
materias = {m.id: m for m in pensum}


def _etiqueta(mid: str) -> str:
    m = materias[mid]
    return f"S{m.semestre or 'E'} · {m.nombre} ({m.codigo})"


EXTRA, EXTRA_FISH, REQ = "__extra__", "__extra_fish__", "__req__"  # destinos especiales además de las materias del pensum


def _guardar(updates: dict, mensaje: str, *, asignaciones: bool = False) -> None:
    """Guarda con bloqueo + fusión por materia/registro y refresca la sesión."""
    try:
        guardar = save_asignaciones if asignaciones else save_materias
        r = guardar(updates, base_revision=ss["config"]["revision"])
    except ConfigError as exc:
        st.error(str(exc))
        return
    ss["config"] = r.config
    ss["flash"] = mensaje + (" (el archivo había cambiado en otra sesión; se fusionaron los cambios)" if r.conflicto_externo else "")
    st.rerun()


if msg := ss.pop("flash", None):
    st.success(msg)

top1, top2 = st.columns([4, 1])
top1.caption(f"Archivo: `{config_path().name}` · revisión {cfg['revision']} · {len(cfg['materias'])} materia(s) personalizada(s) · {len(cfg.get('asignaciones', {}))} asignación(es) manual(es) · actualizado: {cfg.get('actualizado') or '—'}")
if top2.button("↻ Recargar del disco"):
    res = load_config()
    ss["config"], ss["config_warnings"] = res.config, res.warnings
    st.rerun()
if disk_revision() != cfg["revision"]:
    st.warning("El archivo cambió en disco (otra pestaña o proceso). Pulsa **Recargar del disco** para ver los cambios.")

resultado = construir_matriz(pensum, notas, cfg, matriculadas)

# ---------------------------------------------------------------- 1. sin correspondencia
oficiales_req = [o["nombre"] for o in ss["datos"].get("requisitos_grado_oficiales", [])]
pendientes = [(n.nombre, f"{n.id} · {n.periodo} · nota {n.definitiva}", f"{n.id}_{n.periodo}", n.id) for n in resultado.sin_correspondencia]
pendientes += [(x.nombre, f"{x.codigo} · matriculada {x.periodo}", f"m{x.codigo}_{x.id_grupo}", x.codigo) for x in resultado.matriculadas_sin_correspondencia]
if pendientes:
    st.subheader("1 · Registros sin asociar")
    st.caption("Asócialos a una materia del pensum (crea un alias), márcalos como **electiva adicional** "
               "o como **requisito de grado**. La marca vale para todos los estudiantes (se guarda por ID de materia).")
    destinos = [c.id for c in resultado.celdas if c.estado not in ("aprobada", "en_curso")] or list(materias)
    opciones_dest = [*destinos, EXTRA, EXTRA_FISH, REQ]
    claves = [normalize_key(materias[d].nombre) for d in destinos]

    def _fmt(d: str) -> str:
        return {EXTRA: "➕ Electiva adicional (columna Electivas)", EXTRA_FISH: "➕ Electiva Fish adicional",
                REQ: "🎓 Requisito de grado"}.get(d) or _etiqueta(d)

    for nombre, detalle, k, clave_asig in pendientes:
        if inferir_requisito(nombre, oficiales_req):
            idx = opciones_dest.index(REQ)
        elif "fish" in normalize_key(nombre):
            idx = opciones_dest.index(EXTRA_FISH)
        elif (sug := difflib.get_close_matches(normalize_key(nombre), claves, n=1, cutoff=0.5)):
            idx = claves.index(sug[0])
        else:
            idx = 0
        a, b, c, d = st.columns([3, 3, 3, 1])
        a.text(f"{nombre}\n{detalle}")
        dest = b.selectbox("Asignar a", opciones_dest, index=idx, format_func=_fmt, key=f"dest_{k}", label_visibility="collapsed")
        req_sel = None
        if dest == REQ:
            sugerido = inferir_requisito(nombre, oficiales_req)
            opts_req = [*oficiales_req, OTRO]
            req_sel = c.selectbox("Cumple el requisito", opts_req, index=opts_req.index(sugerido) if sugerido else len(opts_req) - 1,
                                  key=f"req_{k}", label_visibility="collapsed")
        if d.button("Aplicar", key=f"btn_{k}"):
            if dest in (EXTRA, EXTRA_FISH):
                grupo = "fish" if dest == EXTRA_FISH else "complementaria"
                _guardar({clave_asig: {"tipo": "electiva_adicional", "nombre": nombre, "grupo": grupo}},
                         f"«{nombre}» marcada como electiva adicional ({'Fish' if grupo == 'fish' else 'programa'})", asignaciones=True)
            elif dest == REQ:
                _guardar({clave_asig: {"tipo": "requisito_grado", "nombre": nombre, "requisito": "" if req_sel == OTRO else req_sel}},
                         f"«{nombre}» marcada como requisito de grado", asignaciones=True)
            else:
                entry = dict(cfg["materias"].get(dest, {}))
                entry["aliases"] = [*entry.get("aliases", []), nombre]
                _guardar({dest: entry}, f"Alias «{nombre}» → {materias[dest].nombre}")
    st.divider()

# ---------------------------------------------------------------- 1b. asignaciones manuales vigentes
asig = cfg.get("asignaciones", {})
if asig:
    with st.expander(f"Asignaciones manuales vigentes ({len(asig)})"):
        for clave, a_ in asig.items():
            x, y = st.columns([6, 1])
            etiqueta = (f"Electiva adicional ({'Fish' if a_.get('grupo') == 'fish' else 'programa'})" if a_["tipo"] == "electiva_adicional" else f"Requisito de grado → {a_['requisito'] or 'otro'}")
            x.text(f"{a_['nombre']}  ·  ID {clave}  ·  {etiqueta}")
            if y.button("Quitar", key=f"quitar_{clave}"):
                _guardar({clave: None}, f"Asignación de «{a_['nombre']}» eliminada", asignaciones=True)
    st.divider()

# ---------------------------------------------------------------- 2. editor por materia
st.subheader("2 · Editar una materia")
filtro = st.text_input("Buscar materia", placeholder="nombre o código…")
opciones = [m.id for m in sorted(pensum, key=lambda m: (m.semestre == 0, m.semestre, m.nombre))
            if not filtro or normalize_key(filtro) in normalize_key(f"{m.nombre} {m.codigo}")]
if not opciones:
    st.info("Ninguna materia coincide con la búsqueda.")
else:
    mid = st.selectbox("Materia", opciones, format_func=_etiqueta)
    m = materias[mid]
    entry = cfg["materias"].get(mid, {})
    oficiales = [r for r in m.prerrequisitos if r.id]
    oficiales_ids = [r.id for r in oficiales]
    actuales = [p for p in (set(oficiales_ids) - set(entry.get("prereqs_removidos", []))) | set(entry.get("prereqs_extra", [])) if p in materias and p != mid]

    with st.form(f"form_{mid}"):
        st.markdown(f"**{m.nombre}** · {m.codigo} · {m.creditos} créditos · ID SIMCA `{m.id}`")
        st.caption("Prerrequisitos oficiales: " + (", ".join(r.nombre for r in oficiales) or "ninguno"))
        st.write("**Alias** (nombres antiguos o ID de SIMCA con que aparece en la historia académica)")
        alias_df = st.data_editor(
            pd.DataFrame({"alias": pd.Series(entry.get("aliases", []), dtype="object")}),
            num_rows="dynamic", hide_index=True, key=f"alias_{mid}",
            column_config={"alias": st.column_config.TextColumn("Alias", max_chars=120)},
        )
        sel = st.multiselect(
            "Prerrequisitos efectivos (quita los oficiales que no apliquen o agrega nuevos)",
            [i for i in materias if i != mid], default=actuales, format_func=_etiqueta,
        )
        g, r = st.columns(2)
        guardar = g.form_submit_button("💾 Guardar cambios", type="primary")
        restablecer = r.form_submit_button("Restablecer esta materia")

    if guardar:
        aliases = [clean_text(a) for a in alias_df["alias"].tolist() if clean_text(a)]
        oficial_set, sel_set = set(oficiales_ids), set(sel)
        nueva = {"aliases": aliases, "prereqs_extra": sorted(sel_set - oficial_set), "prereqs_removidos": sorted(oficial_set - sel_set)}
        _guardar({mid: nueva}, f"Guardado: {m.nombre}")
    if restablecer:
        _guardar({mid: None}, f"Restablecida: {m.nombre}")

# ---------------------------------------------------------------- 3. pensum extraído
st.divider()
st.subheader("3 · Pensum extraído")
celdas = {c.id: c for c in resultado.celdas}
st.dataframe(pd.DataFrame([{
    "Semestre": str(m.semestre) if m.semestre else "Electivas", "Código": m.codigo, "Créditos": m.creditos, "Materia": m.nombre,
    "Prerrequisitos oficiales": "; ".join(r.nombre for r in m.prerrequisitos),
    "Prerrequisitos efectivos": "; ".join(p["nombre"] for p in celdas[m.id].prereqs),
    "Alias": "; ".join(celdas[m.id].aliases),
    "Personalizada": celdas[m.id].personalizada,
} for m in pensum]), hide_index=True)


# ---------------------------------------------------------------- 5. exportar / importar
st.divider()
with st.expander("💾 Exportar / importar configuración (útil en la nube, donde el disco es efímero)"):
    st.download_button("⬇️ Exportar configuración (.json)", json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8"),
                       "config_materias.json", "application/json")
    subido = st.file_uploader("Importar configuración (.json)", type=["json"], key="imp_cfg")
    if subido is not None and st.button("Importar y reemplazar la configuración actual"):
        try:
            if subido.size > 1_000_000:
                raise ConfigError("El archivo supera 1 MB.")
            r = replace_config(json.loads(subido.getvalue().decode("utf-8")), base_revision=ss["config"]["revision"])
            ss["config"] = r.config
            ss["flash"] = "Configuración importada."
            st.rerun()
        except (ValueError, ConfigError) as exc:
            st.error(f"No se pudo importar: {exc}")
