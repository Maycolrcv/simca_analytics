"""CLI: ``python -m simca.cli_scrape``. Scrapea SIMCA y guarda el snapshot local.

Se ejecuta como subproceso desde Streamlit para aislar el event loop de Playwright
(evita conflictos asyncio/Windows). Nunca imprime credenciales.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .fileio import write_json_plain
from .parsers import ParseError
from .scraper import DomChangedError, LoginError, ScrapingError, fetch_academic_pages
from .settings import MissingCredentialsError, get_credentials, get_data_dir, get_student_code, is_debug, is_headless, modo_nube
from .snapshot import build_snapshot, save_snapshot


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scrapea SIMCA y guarda el snapshot.")
    ap.add_argument("--out", help="Archivo de salida (lo usa la interfaz con una carpeta temporal). Sin él, guarda en el directorio de datos.")
    args = ap.parse_args(argv)
    try:
        creds = get_credentials()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    codigo = get_student_code()
    if not codigo and sys.stdin.isatty():
        codigo = input("Código o cédula del estudiante: ").strip()
    if not codigo:
        print("ERROR: define SIMCA_STUDENT_CODE o digítalo en la interfaz.", file=sys.stderr)
        return 2
    try:
        fetch = fetch_academic_pages(creds.usuario, creds.password, codigo, headless=is_headless())
        html = fetch.html
        snap = build_snapshot(html["pensum"], html["notas"], html.get("matriculadas"))
        snap["advertencias"] += fetch.advertencias
        if args.out:
            ruta = Path(args.out)
            write_json_plain(ruta, snap)
        else:
            ruta = save_snapshot(snap)
    except LoginError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except (DomChangedError, ParseError) as exc:
        print(f"ERROR (estructura de SIMCA cambió): {exc}", file=sys.stderr)
        if is_debug() and not modo_nube() and isinstance(exc, ParseError) and "html" in locals():
            dbg = get_data_dir() / "debug"  # contiene datos personales: dir privado e ignorado por git
            dbg.mkdir(exist_ok=True)
            for nombre, contenido in html.items():
                (dbg / f"ultimo_{nombre}.html").write_text(contenido, encoding="utf-8")
            print(f"DEBUG: HTML guardado en {dbg}", file=sys.stderr)
        return 4
    except ScrapingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5
    print(f"OK: {len(snap['pensum'])} materias, {len(snap['notas'])} notas, {len(snap['matriculadas'])} matriculadas -> {ruta.name}")
    for w in snap["advertencias"]:
        print(f"AVISO: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
