"""Control de acceso básico por código (complementa, no reemplaza, la restricción de visores de Streamlit).

* Local: opcional. Si defines SIMCA_APP_ACCESS_CODE, se pide al entrar.
* Nube: OBLIGATORIO. Sin código la app se niega a cargar, porque maneja datos personales de estudiantes.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

from .settings import modo_nube

MAX_INTENTOS = 5


def acceso_valido(ingresado: str, esperado: str) -> bool:
    """Comparación en tiempo constante; falla si no hay código esperado."""
    return bool(esperado) and hmac.compare_digest(ingresado.encode("utf-8"), esperado.encode("utf-8"))


def requerir_acceso() -> None:
    esperado = os.getenv("SIMCA_APP_ACCESS_CODE", "")
    if not esperado:
        if modo_nube():
            st.error("🔒 Esta app maneja datos personales de estudiantes y no tiene código de acceso configurado. "
                     "Define `SIMCA_APP_ACCESS_CODE` en los Secrets de Streamlit para habilitarla.")
            st.stop()
        return
    ss = st.session_state
    if ss.get("_acceso_ok"):
        return
    st.title("🔒 SIMCA Analytics")
    if ss.get("_intentos", 0) >= MAX_INTENTOS:
        st.error("Demasiados intentos fallidos en esta sesión. Cierra la pestaña y vuelve a abrirla.")
        st.stop()
    with st.form("acceso"):
        codigo = st.text_input("Código de acceso", type="password")
        entrar = st.form_submit_button("Entrar", type="primary")
    if entrar:
        if acceso_valido(codigo, esperado):
            ss["_acceso_ok"] = True
            ss["_intentos"] = 0
            st.rerun()
        ss["_intentos"] = ss.get("_intentos", 0) + 1
        st.error("Código incorrecto.")
    st.stop()
