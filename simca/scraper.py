"""Navegación con Playwright: login -> búsqueda -> historia académica y pénsum.

Solo obtiene HTML; el parseo vive en ``parsers.py``. Los selectores replican los
scripts base (codegen) con fallbacks para los IDs JSF autogenerados (``j_idtNN``).
"""
from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from .settings import SIMCA_BASE_URL, get_data_dir, is_debug, modo_nube

log = logging.getLogger(__name__)

NOTAS_BODY_SEL = '[id$="hAcademicaNotasEstudianteDT_data"]'
PENSUM_TABLE_SEL = '[id="formMateriasPendientes:materiaspendientes"]'
OVERLAY_SEL = f"{PENSUM_TABLE_SEL} .overlayRequisito"
MATRICULADAS_BODY_SEL = '[id$="tabView:materias_data"]'

# nombre -> (texto del enlace, selector de la tabla, espera extra, coincidencia exacta del enlace)
SECCIONES = {
    "notas": ("Historia Académica", NOTAS_BODY_SEL, None, False),
    "pensum": ("Pénsum / Currículo", PENSUM_TABLE_SEL, OVERLAY_SEL, False),
    "matriculadas": ("Materias", MATRICULADAS_BODY_SEL, None, True),  # exact: evita "Materias pendientes"
}
OPCIONALES = {"matriculadas"}  # si fallan, se degrada con una advertencia en vez de abortar


@dataclass
class FetchResult:
    html: dict[str, str]
    advertencias: list[str] = field(default_factory=list)


class ScrapingError(RuntimeError):
    """Error genérico de scraping."""


class LoginError(ScrapingError):
    """Credenciales rechazadas o formulario de login irreconocible."""


class DomChangedError(ScrapingError):
    """Un elemento esperado no apareció: probable cambio en el DOM de SIMCA."""


def _primer_visible(page: Page, selectores: list[str], descripcion: str, timeout: int = 6000) -> Locator:
    for sel in selectores:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except PlaywrightTimeout:
            continue
    raise DomChangedError(f"No se encontró {descripcion} (selectores probados: {selectores}).")


def _login(page: Page, usuario: str, password: str, timeout_ms: int) -> None:
    page.goto(SIMCA_BASE_URL, wait_until="domcontentloaded")
    user_in = _primer_visible(page, ['input[name="j_idt13:userName"]', 'input[id$=":userName"]', 'input[type="text"]'], "el campo de usuario")
    pwd_in = _primer_visible(page, ['[id="j_idt13:password"]', 'input[type="password"]'], "el campo de contraseña")
    user_in.fill(usuario)
    pwd_in.fill(password)
    try:
        page.get_by_role("button", name="Ingresar").click()
    except PlaywrightTimeout as exc:
        raise DomChangedError("No se encontró el botón 'Ingresar'.") from exc
    try:
        page.get_by_role("textbox", name="Digite el código,").wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeout as exc:
        try:
            sigue_login = pwd_in.is_visible()
        except PlaywrightError:
            sigue_login = False
        if sigue_login:
            raise LoginError("Login rechazado: revisa SIMCA_USER / SIMCA_PASSWORD.") from exc
        raise DomChangedError("Tras el login no apareció el buscador de estudiantes.") from exc


def _buscar_estudiante(page: Page, codigo: str) -> None:
    try:
        page.get_by_role("textbox", name="Digite el código,").fill(codigo)
        page.get_by_role("button", name="Buscar").click()
    except PlaywrightTimeout as exc:
        raise DomChangedError("No se pudo usar el buscador de estudiantes.") from exc


def _abrir_seccion(page: Page, link: str, selector: str, extra_wait: str | None, exact: bool = False) -> str:
    try:
        page.get_by_role("link", name=link, exact=exact).first.click()
    except PlaywrightTimeout as exc:
        raise DomChangedError(f"No se encontró el enlace '{link}' (¿el estudiante existe y hay permisos?).") from exc
    try:
        page.wait_for_selector(selector, state="attached")
    except PlaywrightTimeout as exc:
        raise DomChangedError(f"La sección '{link}' no cargó su tabla ({selector}).") from exc
    if extra_wait:
        try:  # carga dinámica de los overlays de requisitos: degradación, no fallo
            page.wait_for_selector(extra_wait, state="attached", timeout=8000)
        except PlaywrightTimeout:
            log.warning("No aparecieron contenedores overlayRequisito; el parser lo reportará.")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeout:
        pass  # best-effort
    return page.content()


def _lanzar_navegador(pw, headless: bool):
    """Lanza Chromium; si no está instalado (primer arranque en la nube) lo instala una vez y reintenta."""
    en_nube = modo_nube()
    args = ["--no-sandbox", "--disable-dev-shm-usage"] if en_nube else []  # requerido en contenedores
    try:
        return pw.chromium.launch(headless=True if en_nube else headless, args=args)
    except PlaywrightError as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
        log.warning("Chromium no instalado: instalándolo (solo la primera vez)…")
        res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                             capture_output=True, text=True, timeout=900)
        if res.returncode != 0:
            raise ScrapingError("No se pudo instalar Chromium: " + (res.stderr or res.stdout)[-300:]) from exc
        return pw.chromium.launch(headless=True if en_nube else headless, args=args)


def _fetch_once(usuario, password, codigo, paginas, headless, timeout_ms) -> FetchResult:
    with sync_playwright() as pw:
        browser = _lanzar_navegador(pw, headless)
        page = None
        try:
            context = browser.new_context()
            context.set_default_timeout(timeout_ms)
            page = context.new_page()
            _login(page, usuario, password, timeout_ms)
            _buscar_estudiante(page, codigo)
            res = FetchResult(html={})
            for nombre in paginas:
                try:
                    res.html[nombre] = _abrir_seccion(page, *SECCIONES[nombre])
                except DomChangedError as exc:
                    if nombre not in OPCIONALES:
                        raise
                    res.advertencias.append(f"Sección opcional '{nombre}' no disponible: {exc}")
            return res
        except ScrapingError:
            if is_debug() and not modo_nube() and page is not None:  # el HTML contiene datos personales: solo en dir privado
                try:
                    dbg = get_data_dir() / "debug"
                    dbg.mkdir(exist_ok=True)
                    (dbg / "ultimo_error.html").write_text(page.content(), encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
            raise
        finally:
            browser.close()


def fetch_academic_pages(
    usuario: str,
    password: str,
    codigo_estudiante: str,
    *,
    paginas: tuple[str, ...] = ("notas", "pensum", "matriculadas"),
    headless: bool = True,
    timeout_ms: int = 30_000,
    intentos: int = 2,
) -> FetchResult:
    """Devuelve el HTML de cada sección pedida. Reintenta solo ante timeouts de red."""
    desconocidas = set(paginas) - set(SECCIONES)
    if desconocidas:
        raise ValueError(f"Secciones desconocidas: {desconocidas}")
    if not codigo_estudiante.strip():
        raise ScrapingError("Falta el código/cédula del estudiante.")
    ultimo: Exception | None = None
    for intento in range(1, intentos + 1):
        try:
            return _fetch_once(usuario, password, codigo_estudiante.strip(), paginas, headless, timeout_ms)
        except (LoginError, DomChangedError):
            raise  # reintentar no ayuda (y un login fallido repetido puede bloquear la cuenta)
        except (PlaywrightTimeout, PlaywrightError) as exc:
            ultimo = exc
            log.warning("Intento %s/%s falló: %s", intento, intentos, type(exc).__name__)
    raise ScrapingError(f"SIMCA no respondió tras {intentos} intentos ({type(ultimo).__name__}).") from ultimo
