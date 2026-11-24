"""Punto de entrada:  streamlit run app.py"""
import sys
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:      # el paquete `simca` debe encontrarse sin importar desde dónde se lance
    sys.path.insert(0, str(RAIZ))

st.set_page_config(page_title="SIMCA Analytics", page_icon="🎓", layout="wide")

# Verificación previa: en Streamlit Cloud el mensaje original de ImportError está oculto, así que se diagnostica aquí.
REQUERIDOS = (
    "simca/__init__.py", "simca/auth.py", "simca/cli_scrape.py", "simca/config_store.py", "simca/fileio.py",
    "simca/matrix.py", "simca/models.py", "simca/parsers.py", "simca/reglamento.py", "simca/render.py",
    "simca/requisitos.py", "simca/scraper.py", "simca/settings.py", "simca/snapshot.py", "simca/state.py",
    "simca/text_utils.py", "views/matriz.py", "views/configuracion.py",
)
faltan = [f for f in REQUERIDOS if not (RAIZ / f).is_file()]
if faltan:
    st.error("Al repositorio publicado le faltan archivos de la aplicación.")
    st.code("\n".join(faltan))
    st.markdown("**Cómo corregirlo:** en la carpeta del proyecto ejecuta `git add -A`, `git commit -m \"completar\"` y "
                "`git push` (o usa la opción 3 de `desplegar.bat`). Evita subir archivos sueltos desde la web de GitHub: "
                "no conserva las carpetas. Después, en *Manage app* pulsa **Reboot app**.")
    st.stop()

try:
    from simca.auth import requerir_acceso
    from simca.state import init_state
except ImportError as exc:   # p. ej. una dependencia sin instalar (revisa requirements.txt)
    st.error("No se pudo importar un módulo de la aplicación.")
    st.code(f"{type(exc).__name__}: {exc}")
    st.stop()

requerir_acceso()   # antes de leer o mostrar cualquier dato
init_state()

pagina = st.navigation([
    st.Page("views/matriz.py", title="Matriz académica", icon="🎓", default=True),
    st.Page("views/configuracion.py", title="Configuración de materias", icon="⚙️"),
])
pagina.run()
