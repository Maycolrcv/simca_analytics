"""Compatibilidad con el script original: exporta las materias aprobadas a CSV.

Ahora reutiliza ``simca.scraper`` + ``simca.parsers`` (parser corregido, credenciales
desde .env). Para el análisis completo usa la app:  ``streamlit run app.py``
"""
from __future__ import annotations

import sys

import pandas as pd

from simca.parsers import parse_notas_html
from simca.scraper import fetch_academic_pages
from simca.settings import get_credentials, get_student_code, is_headless


def obtener_historia_academica() -> None:
    creds = get_credentials()
    codigo = get_student_code() or input("Código o cédula a consultar: ").strip()
    fetch = fetch_academic_pages(creds.usuario, creds.password, codigo, paginas=("notas",), headless=is_headless())
    notas = parse_notas_html(fetch.html["notas"])
    aprobadas = [
        {"Periodo": r.periodo, "ID Materia": r.id, "Materia": r.nombre, "Créditos": r.creditos,
         "Semestre": r.semestre_cursado, "Nota": r.nota, "Habilitación": r.habilitacion,
         "Definitiva": r.definitiva, "Tipo": r.tipo}
        for r in notas.registros if r.aprobada
    ]
    if not aprobadas:
        print("[-] No se encontraron materias aprobadas.")
        return
    df = pd.DataFrame(aprobadas).drop_duplicates()
    print(df.to_string(index=False))
    df.to_csv("historia_academica_aprobadas.csv", index=False, encoding="utf-8-sig")  # ignorado por git
    print("\n[+] Exportado a 'historia_academica_aprobadas.csv'")


if __name__ == "__main__":
    try:
        obtener_historia_academica()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
